"""Per-request batch loader for cached pydantic resources.

The :class:`Resolver` is constructed once per HTTP request and exposes
typed ``get`` / ``get_many`` / ``get_etag`` / ``invalidate`` methods.

Three layers, in priority order:

1. **Per-instance local dict** (request-scoped). Garbage collected when
   the request ends. Holds both hits and *negative* hits — see the
   ``_MISSING`` sentinel below — so a request asking for the same
   missing id twice issues only one upstream call.
2. **Persistent ``anystore.Store``** — Redis in production, ``memory://``
   in tests, file/S3 in offline modes. Same code path either way; the
   resolver doesn't know the backend. Misses are *never* persisted to
   this layer (only to local), to avoid poisoning the store with stale
   negatives across requests.
3. **Upstream fetch** via the registry (DB / Elasticsearch / wherever
   the owning logic module knows how to load from).

The hot-path read uses ``model_validate=False`` so cached payloads
skip pydantic validators. They were already validated at write time
and the persistent store is a trust boundary the resolver controls
end-to-end.

The resolver also doubles as the source of truth for HTTP cache
validators: every cached object exposes a content-derived ETag
(:meth:`Resolver.get_etag`, :meth:`Resolver.get_many_etag`)
which the API layer puts on the response so browsers can revalidate
with ``If-None-Match`` and get a 304. ETags rotate automatically
whenever :meth:`Resolver.invalidate` is called from a mutation path,
so the wire-level cache stays consistent with the backing store
without any per-endpoint bookkeeping.

Spurious ``invalidate()`` calls are cheap — content-derived ETags
stay stable across re-fetches when the upstream content is unchanged,
so the client still gets a 304. Mutation paths can invalidate
liberally without paying for it on the wire.
"""

from typing import Any, Type, TypeVar

from anystore import get_store
from anystore.store import Store
from pydantic import BaseModel
from servicelayer.settings import REDIS_LONG

from aleph.logic.resolver.etag import _short_hash, compute_etag
from aleph.logic.resolver.registry import fetch_many, fetch_one, get_ttl
from aleph.settings import SETTINGS

T = TypeVar("T", bound=BaseModel)

# Sentinel so the per-request local cache can record "fetched, not found"
# distinct from "never asked". ``dict.get(key)`` returns None for both —
# which would cause the resolver to refetch every miss within a single
# request, defeating the point of the local cache. Using a unique
# sentinel object as the ``default`` argument disambiguates the two.
_MISSING: Any = object()


def get_resolver_store() -> Store:
    """Shared anystore Store backing every Resolver instance.

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

    ``raise_on_nonexist=False`` is essential — anystore's default is
    True (it raises ``DoesNotExist`` on missing keys), but the
    resolver's three-layer cache logic depends on ``Store.get``
    returning ``None`` for misses so it can fall through to the
    upstream fetcher.
    """
    return get_store(
        uri=SETTINGS.RESOLVER_STORE_URI,
        raise_on_nonexist=False,
        backend_config={"redis_prefix": f"{SETTINGS.APP_NAME}/resolver"},
        ttl=REDIS_LONG,  # FIXME servicelayer dependency
    )


class Resolver:
    """Per-request batch loader. See module docstring for the cache
    layering and rationale.

    Constructed once per request and discarded on response. In FastAPI:
    ``Depends(get_resolver)``. In Flask: one is attached to
    ``flask.request._resolver`` by the serializer shim.
    """

    def __init__(self, store: Store | None = None) -> None:
        # The local cache holds three states:
        #   - key absent             → never asked this request
        #   - key present, value=obj → cached pydantic instance
        #   - key present, value=None → negative hit (already missed
        #                               upstream this request, don't refetch)
        self._local: dict[tuple[type, str], BaseModel | None] = {}
        self._store = store or get_resolver_store()

    # --- key construction --------------------------------------------------

    @staticmethod
    def _key(cls_: Type[BaseModel], identifier: str) -> str:
        """Path-style key: ``Role/1``, ``Collection/foo-dataset/stats``, …

        First segment is ``cls.__name__``; remaining segments come from
        the lookup identifier the caller passes. For aggregates, the
        caller composes the suffix via the model's ``make_cache_key``
        classmethod — there is no automatic key derivation here.
        """
        return f"{cls_.__name__}/{identifier}"

    # --- single-object API -------------------------------------------------

    def get(self, cls: Type[T], identifier: str) -> T | None:
        """Get a single object by identifier. Returns None if the
        object is not found anywhere (local, store, upstream).

        ``identifier`` must be a non-empty string. The resolver
        deliberately does not handle ``None`` / empty input — callers
        with an Optional source filter at the call site, so accidental
        ``None``s show up as a ``ValueError`` instead of silently
        returning empty data.
        """
        if not identifier:
            raise ValueError(
                f"Resolver.get({cls.__name__}, ...) requires a non-empty " "identifier"
            )
        local_key = (cls, identifier)
        if local_key in self._local:
            return self._local[local_key]  # type: ignore[return-value]

        # Persistent store layer — anystore handles the pydantic
        # round-trip. ``model_validate=False`` skips re-running validators
        # on a payload that was already validated at write time.
        obj = self._store.get(
            self._key(cls, identifier),
            model=cls,
            model_validate=False,
        )
        if obj is None:
            obj = fetch_one(cls, identifier)
            if obj is not None:
                # Write path: full validation runs (no model_validate
                # flag passed → upstream default is True). Stored
                # payloads are trusted by every subsequent read.
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
            # below is request-scoped so this is safe.

        self._local[local_key] = obj
        return obj  # type: ignore[return-value]

    def get_etag(self, cls: Type[BaseModel], identifier: str) -> str | None:
        """Return the content ETag for a single object, or ``None`` if
        the object doesn't exist. Cheap once the object is in local
        cache; otherwise hits the store layer via :meth:`get`. Same
        non-empty-identifier contract as :meth:`get`."""
        obj = self.get(cls, identifier)
        if obj is not None:
            return compute_etag(cls, obj)

    # --- batch API ---------------------------------------------------------

    def get_many(self, cls: Type[T], identifiers: list[str]) -> list[T]:
        """Batched: split into local-cached, store-cached, upstream-fetch.
        Returns objects in the input order, omitting missing ones.

        Hot-path optimization for the entity batch case (~120 entities
        per search response). Uses Redis ``MGET`` directly when the
        underlying store is Redis-backed; falls back to per-key
        ``Store.get`` for other backends.
        """
        if not identifiers:
            return []

        results: dict[str, BaseModel] = {}
        store_misses = self._fill_from_local(cls, identifiers, results)
        upstream_misses = self._fill_from_store(cls, store_misses, results)
        self._fill_from_upstream(cls, upstream_misses, results)
        return [results[i] for i in identifiers if i in results]  # type: ignore[misc]

    def _fill_from_local(
        self,
        cls: Type[T],
        identifiers: list[str],
        results: dict[str, BaseModel],
    ) -> list[str]:
        """Step 1: drain the per-request local cache.

        Updates ``results`` in place with hits, returns the list of ids
        that need to fall through to the persistent store. ``_MISSING``
        means "never asked this request"; a stored ``None`` means
        "already missed upstream — skip".
        """
        store_misses: list[str] = []
        for identifier in identifiers:
            local = self._local.get((cls, identifier), _MISSING)
            if local is _MISSING:
                store_misses.append(identifier)
            elif local is not None:
                results[identifier] = local
        return store_misses

    def _fill_from_store(
        self,
        cls: Type[T],
        store_misses: list[str],
        results: dict[str, BaseModel],
    ) -> list[str]:
        """Step 2: batch read the persistent store for the local misses.

        Redis backends get a single MGET via :meth:`_mget`; other
        backends fall back to N per-key gets. Updates ``results`` in
        place with hits, populates the local cache for them, and
        returns the list of ids that still need to be fetched upstream.
        """
        if not store_misses:
            return []
        upstream_misses: list[str] = []
        keys = [self._key(cls, i) for i in store_misses]
        for identifier, raw in zip(store_misses, self._mget(cls, keys)):
            if raw is None:
                upstream_misses.append(identifier)
            else:
                results[identifier] = raw
                self._local[(cls, identifier)] = raw
        return upstream_misses

    def _fill_from_upstream(
        self,
        cls: Type[T],
        upstream_misses: list[str],
        results: dict[str, BaseModel],
    ) -> None:
        """Step 3: batch fetch upstream for the store misses.

        Uses the registered ``fetch_many`` if any, otherwise N
        ``fetch_one`` calls. Each fetched object's ``cache_key`` is
        used as the lookup identifier (so e.g. CollectionSchema is
        keyed by ``foreign_id`` rather than the SQLA int PK). Anything
        not returned by upstream is recorded as a *negative* hit in
        the local cache only — never in the persistent store, to
        avoid poisoning the cache with stale negatives.
        """
        if not upstream_misses:
            return
        ttl = get_ttl(cls)
        fetched_keys: set[str] = set()
        for obj in fetch_many(cls, upstream_misses):
            if obj is None:
                continue
            # Use the model's own ``cache_key`` (foreign_id, composite
            # path, …) instead of guessing the SQLA primary key —
            # the lookup identifier the caller passed in is exactly
            # what each schema's ``cache_key`` returns.
            key = obj.cache_key  # type: ignore[attr-defined]
            self._store.put(self._key(cls, key), obj, model=cls, ttl=ttl)
            results[key] = obj
            self._local[(cls, key)] = obj
            fetched_keys.add(key)
        # Record persistent misses in the local cache only — never in
        # the persistent store (see comment in `get()`).
        for identifier in upstream_misses:
            if identifier not in fetched_keys:
                self._local[(cls, identifier)] = None

    def _mget(self, cls: Type[T], keys: list[str]) -> list[T | None]:
        """Batch read from the underlying store.

        For Redis backends, issues a single ``MGET`` and deserializes
        each value with ``model_validate=False``. For other backends,
        falls back to N ``Store.get`` calls. Either way returns a list
        of pydantic instances (or None for misses) in the same order
        as the input keys.

        The Redis fast path peeks at the underlying fsspec backend
        (``store._fs``) and the redis client it owns. If the shape
        doesn't match — different backend, future fsspec rev — we
        silently fall back to the generic per-key path. The generic
        path is correct for every backend; the MGET shortcut is purely
        a latency win for the entity hot path.
        """
        backend = self._store._fs
        client = getattr(backend, "client", None)
        if client is not None and hasattr(client, "mget"):
            from anystore.logic.serialize import from_store

            fs_keys = [self._store._keys.to_fs_key(k) for k in keys]
            raw_values = client.mget(fs_keys)
            return [
                from_store(v, model=cls, model_validate=False) if v else None
                for v in raw_values
            ]
        # Generic per-key fallback. Correct for every backend.
        return [self._store.get(k, model=cls, model_validate=False) for k in keys]

    def get_many_etag(
        self, cls: Type[BaseModel], ids: list[str], extra: str = ""
    ) -> str:
        """Combined ETag for a list-style response (companion to
        :meth:`get_many`).

        The ETag is a content hash of the constituent ETags joined with
        a newline plus an optional ``extra`` discriminator (typically
        the search query string, so different filters get different
        ETags). Each constituent ETag is fetched via :meth:`get_etag`,
        so this populates the local cache as a side effect — the
        following ``get_many`` for the same ids will hit the local
        layer.
        """
        parts = [self.get_etag(cls, i) or "" for i in ids]
        if extra:
            parts.append(extra)
        return f'"{_short_hash(chr(10).join(parts).encode())}"'

    # --- mutation hook -----------------------------------------------------

    @staticmethod
    def invalidate(cls_: Type[BaseModel], identifier: str) -> None:
        """Drop a key from the persistent store. Called from logic
        paths that mutate the underlying object. ``identifier`` must
        be a non-empty string — the same tight contract as :meth:`get`.

        Static so callers don't need a Resolver instance — invalidation
        is a write to the shared store, not a per-request operation.
        """
        if not identifier:
            raise ValueError(
                f"Resolver.invalidate({cls_.__name__}, ...) requires a "
                "non-empty identifier"
            )
        get_resolver_store().delete(
            Resolver._key(cls_, identifier),
            ignore_errors=True,
        )

    @staticmethod
    def invalidate_many(cls_: Type[BaseModel], identifiers: list[str]) -> None:
        """Drop several keys for the same class. No batched delete in
        the underlying store interface, so this is just a loop —
        kept as a method for caller readability."""
        for identifier in identifiers:
            Resolver.invalidate(cls_, identifier)

    @staticmethod
    def invalidate_prefix(cls_: Type[BaseModel], identifier_prefix: str) -> None:
        """Drop every key under a path prefix.

        Aggregate-aware invalidation: invalidating a Collection by its
        ``foreign_id`` should also drop the matching CollectionStatistics
        and CollectionStatus aggregates that share the same prefix.
        Each aggregate's ``make_cache_key`` is rooted at the parent
        identifier so a single prefix sweep covers them all.
        """
        store = get_resolver_store()
        prefix = Resolver._key(cls_, identifier_prefix)
        for key in store.iterate_keys(prefix=prefix):
            store.delete(key, ignore_errors=True)


def get_resolver() -> Resolver:
    """FastAPI dependency. Yields a fresh Resolver per request — the
    local cache lifetime is a single request, garbage collected on
    response. The persistent store is shared.
    """
    return Resolver()
