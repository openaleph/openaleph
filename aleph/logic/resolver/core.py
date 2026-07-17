"""Resolver cache and per-request batch loader.

Two classes:

- :class:`Cache` – the module-level singleton (``cache``). Lives for
  the entire process lifetime. No per-request local dict – every
  ``get`` hits the persistent store directly. Used by SQLA events,
  logic functions, CLI commands, and anything outside a request cycle.

- :class:`RequestResolver` – constructed once per HTTP request and
  discarded on response. Adds a per-request ``_local`` dict on top of
  the persistent store for request-scoped deduplication and negative-hit
  caching. Used by serializers and view functions via FastAPI
  ``Depends(get_resolver)`` or Flask request lifecycle.

Both share the same persistent store (Redis / memory / fs via anystore).
The ``cache`` singleton is the canonical interface for all non-request
code: ``from aleph.logic.resolver import cache``.

Spurious ``invalidate()`` calls are cheap – content-derived ETags
stay stable across re-fetches when the upstream content is unchanged,
so the client still gets a 304. Mutation paths can invalidate
liberally without paying for it on the wire.

The resolver also doubles as the source of truth for HTTP cache
validators: every cached object exposes a content-derived ETag
(:meth:`Cache.get_etag`, :meth:`Cache.get_many_etag`)
which the API layer puts on the response so browsers can revalidate
with ``If-None-Match`` and get a 304. ETags rotate automatically
whenever :meth:`Cache.invalidate` is called from a mutation path,
so the wire-level cache stays consistent with the backing store
without any per-endpoint bookkeeping.
"""

from typing import Any, Iterable, Type

from anystore import get_store
from anystore.logic.serialize import from_store
from anystore.store import Store
from pydantic import BaseModel
from werkzeug.exceptions import NotFound

from aleph.logic.resolver.etag import _short_hash, compute_etag
from aleph.logic.resolver.registry import M, fetch_many, fetch_one, get_ttl
from aleph.logic.resolver.ttl import STORE_TTL
from aleph.settings import SETTINGS

# Sentinel so the per-request local cache can record "fetched, not found"
# distinct from "never asked". ``dict.get(key)`` returns None for both –
# which would cause the resolver to refetch every miss within a single
# request, defeating the point of the local cache. Using a unique
# sentinel object as the ``default`` argument disambiguates the two.
_MISSING: Any = object()


def get_resolver_store() -> Store:
    """Shared anystore Store backing every Cache / RequestResolver.

    Reads ``SETTINGS.RESOLVER_STORE_URI`` (defined in
    :mod:`aleph.settings`), which defaults to the same Redis instance
    the legacy ``aleph.cache`` uses. Tests override the URI to
    ``memory://`` via ``[tool.pytest_env]`` so each test run starts
    clean without any monkey-patching.

    The ``aleph/resolver`` prefix keeps the new keyspace cleanly
    separated from the legacy ``aleph:object:*`` keys.
    ``anystore.get_store()`` is itself runtime-cached on
    (uri, backend_config), so production callers share one Redis
    connection.

    ``raise_on_nonexist=False`` is essential – anystore's default is
    True (it raises ``DoesNotExist`` on missing keys), but the
    resolver's cache logic depends on ``Store.get`` returning ``None``
    for misses so it can fall through to the upstream fetcher.
    """
    return get_store(
        uri=SETTINGS.RESOLVER_STORE_URI,
        raise_on_nonexist=False,
        backend_config={"redis_prefix": f"{SETTINGS.APP_NAME}/resolver"},
        default_ttl=STORE_TTL,
    )


class Cache:
    """Process-level cache backed by the persistent store.

    No per-request local dict – safe for use as a long-lived singleton.
    Every ``get`` hits the store (Redis / memory) directly. Mutations
    (``invalidate``, ``populate``) take effect immediately for all
    subsequent reads across all requests.

    This is the ``cache`` singleton exported from
    ``aleph.logic.resolver``.
    """

    ERROR_NOT_FOUND = NotFound

    def __init__(self, store: Store | None = None) -> None:
        self._store = store or get_resolver_store()

    @staticmethod
    def _key(cls_: Type[M], identifier: str) -> str:
        """Path-style store key: ``ClassName/identifier``."""
        return f"{cls_.__name__}/{identifier}"

    # --- read API ----------------------------------------------------------

    def get_or_404(self, cls: Type[M], identifier: str) -> M:
        """Like :meth:`get` but raises :attr:`ERROR_NOT_FOUND` if the
        object is not found. Convenience for view functions that would
        otherwise do ``obj_or_404(cache.get(...))``.

        The exception class is a class attribute so it can be swapped
        for frameworks that use a different 404 (e.g. FastAPI's
        ``HTTPException(404)``).
        """
        obj = self.get(cls, identifier)
        if obj is None:
            raise self.ERROR_NOT_FOUND()
        return obj

    def get(self, cls: Type[M], identifier: str) -> M | None:
        """Get a single object by identifier. Returns None if the
        object is not found anywhere (store, upstream).

        ``identifier`` must be a non-empty string. The resolver
        deliberately does not handle ``None`` / empty input – callers
        with an Optional source filter at the call site, so accidental
        ``None``s show up as a ``ValueError`` instead of silently
        returning empty data.
        """
        if not identifier:
            raise ValueError(
                f"Cache.get({cls.__name__}, ...) requires a non-empty identifier"
            )
        obj = self._store.get(
            self._key(cls, identifier),
            model=cls,
            model_validate=False,
        )
        if obj is None:
            obj = fetch_one(cls, identifier)
            if obj is not None:
                self._store.put(
                    self._key(cls, identifier),
                    obj,
                    model=cls,
                    ttl=get_ttl(cls),
                )
            # IMPORTANT: do NOT cache None to the persistent store.
            # Cache misses go only into the per-request local cache,
            # otherwise crawlers hitting deleted ids would poison the
            # store and a deleted-then-recreated entity would stay
            # "missing" until explicit invalidation. The local cache
            # below in RequestResolver is request-scoped so this is safe.

        return obj

    # --- batch API ---------------------------------------------------------

    def get_many(self, cls: Type[M], identifiers: Iterable[str]) -> list[M]:
        """Batch-fetch from the store + upstream. Uses Redis MGET when
        available; falls back to per-key reads for other backends.
        """
        identifiers = set([i for i in identifiers if i])
        if not identifiers:
            return []

        results: list[M] = []

        # 1. Persistent cache store.
        keys = [self._key(cls, i) for i in identifiers]
        upstream_misses: list[str] = []
        for identifier, obj in zip(identifiers, self._mget(cls, keys)):
            if obj is None:
                upstream_misses.append(identifier)
            else:
                results.append(obj)

        # 2. Upstream fetch for misses.
        if upstream_misses:
            ttl = get_ttl(cls)
            for obj in fetch_many(cls, upstream_misses):
                if obj is None:
                    continue
                key = obj.cache_key  # type: ignore[attr-defined]
                self._store.put(self._key(cls, key), obj, model=cls, ttl=ttl)
                results.append(obj)

        return results

    def _mget(self, cls: Type[M], keys: Iterable[str]) -> list[M | None]:
        """Batch read from the underlying store.

        For Redis backends, issues a single ``MGET`` and deserializes
        each value with ``model_validate=False``. For other backends,
        falls back to N ``Store.get`` calls. Either way returns a list
        of pydantic instances (or None for misses) in the same order
        as the input keys.

        The Redis fast path peeks at the underlying fsspec backend
        (``store._fs``) and the redis client it owns. If the shape
        doesn't match – different backend, future fsspec rev – we
        silently fall back to the generic per-key path. The generic
        path is correct for every backend; the MGET shortcut is purely
        a latency win for the entity hot path.
        """
        keys = set(keys)
        backend = self._store._fs
        client = getattr(backend, "client", None)
        if client is not None and hasattr(client, "mget"):
            fs_keys = [self._store._keys.to_fs_key(k) for k in keys]
            raw_values = client.mget(fs_keys)
            return [
                from_store(v, model=cls, model_validate=False) if v else None
                for v in raw_values
            ]
        # Generic per-key fallback. Correct for every backend.
        return [self._store.get(k, model=cls, model_validate=False) for k in keys]

    # --- mutation hook -----------------------------------------------------

    def refresh(self, cls_: Type[M], identifier: str) -> None:
        """Refresh the object in persistent cache from upstream."""
        if not identifier:
            raise ValueError(
                f"Resolver.refresh({cls_.__name__}, ...) requires a "
                "non-empty identifier"
            )
        obj = fetch_one(cls_, identifier)
        if obj is not None:
            self._store.put(
                self._key(cls_, identifier), obj, model=cls_, ttl=get_ttl(cls_)
            )

    def invalidate(self, cls_: Type[M], identifier: str) -> None:
        """Drop a key from the persistent store. Called from logic
        paths that mutate the underlying object. ``identifier`` must
        be a non-empty string – the same tight contract as :meth:`get`.

        Acts on this instance's store, enabling future storage tiering
        (e.g. fs-backed store for some schemas, hot redis for others).
        """
        if not identifier:
            raise ValueError(
                f"Resolver.invalidate({cls_.__name__}, ...) requires a "
                "non-empty identifier"
            )
        self._store.delete(
            self._key(cls_, identifier),
            ignore_errors=True,
        )

    def invalidate_many(self, cls_: Type[M], identifiers: list[str]) -> None:
        """Drop several keys for the same class."""
        for identifier in identifiers:
            self.invalidate(cls_, identifier)

    def flushall(self) -> None:
        """Wipe the entire persistent store."""
        for key in self._store.iterate_keys():
            self._store.delete(key, ignore_errors=True)


class RequestResolver(Cache):
    """Per-request batch loader. Extends :class:`Cache` with a
    request-scoped ``_local`` dict for deduplication and negative-hit
    caching.

    Constructed once per HTTP request and discarded on response.
    The ``_local`` dict is garbage collected with the instance.
    """

    def __init__(self, store: Store | None = None) -> None:
        super().__init__(store)
        self._local: dict[tuple[type, str], BaseModel | None] = {}

    def get(self, cls: Type[M], identifier: str) -> M | None:
        """Three-layer lookup: local → store → upstream.

        Negative hits (upstream returned None) are recorded in the
        local cache only – never in the persistent store – to avoid
        poisoning the store with stale negatives across requests.
        """
        if not identifier:
            raise ValueError(
                f"RequestResolver.get({cls.__name__}, ...) requires a "
                "non-empty identifier"
            )
        local_key = (cls, identifier)
        if local_key in self._local:
            return self._local[local_key]  # type: ignore[return-value]

        obj = super().get(cls, identifier)
        self._local[local_key] = obj
        return obj

    def get_many(self, cls: Type[M], identifiers: Iterable[str]) -> list[M]:
        """Batched three-layer lookup with request-scoped deduplication. First
        try local request-scoped cache, fall through Cache backend."""
        identifiers = set([i for i in identifiers if i])
        if not identifiers:
            return []

        results: list[M] = []
        missing: list[str] = []
        for identifier in identifiers:
            obj = self._local.get((cls, identifier), _MISSING)
            if obj is _MISSING:
                missing.append(identifier)
            elif obj is not None:
                results.append(obj)
        if missing:
            results.extend(super().get_many(cls, missing))
        return results

    # --- etag logic -----------------------------------------------------

    def get_etag(self, cls: Type[M], identifier: str) -> str | None:
        """Return the content ETag for a single object, or ``None`` if
        the object doesn't exist. Cheap once the object is in local
        cache; otherwise hits the store layer via :meth:`get`. Same
        non-empty-identifier contract as :meth:`get`."""
        obj = self.get(cls, identifier)
        if obj is not None:
            return compute_etag(cls, obj)

    def get_many_etag(self, cls: Type[M], ids: list[str], extra: str = "") -> str:
        """Combined ETag for a list-style response (companion to
        :meth:`get_many`).

        The ETag is a content hash of the constituent ETags joined with
        a newline plus an optional ``extra`` discriminator (typically
        the search query string, so different filters get different
        ETags). Each constituent ETag is fetched via :meth:`get_etag`,
        so this populates the local cache as a side effect – the
        following ``get_many`` for the same ids will hit the local
        layer.
        """
        parts = [self.get_etag(cls, i) or "" for i in ids]
        if extra:
            parts.append(extra)
        return f'"{_short_hash(chr(10).join(parts).encode())}"'

    def flushall(self) -> None:
        """Wipe the persistent store and local cache."""
        self._local.clear()
        super().flushall()


def get_resolver() -> RequestResolver:
    """FastAPI dependency. Yields a fresh Resolver per request – the
    local cache lifetime is a single request, garbage collected on
    response. The persistent store is shared.
    """
    return RequestResolver()


# app wide singleton for persistent cache
cache: Cache = Cache()
