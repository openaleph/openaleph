"""Resource fetcher registry for the object resolver.

Each pydantic schema in :mod:`aleph.model` registers a fetch function
here so the resolver knows how to load it from upstream (DB, ES, ...)
when its persistent cache misses. Optional ``fetch_many`` enables a
batched fast path; ``ttl`` per-class overrides the store-level default.

Usage from the owning logic module:

    from aleph.logic.resolver import register, register_etag
    from aleph.logic.resolver.ttl import TTL_RESOURCE
    from aleph.model.role import RoleSchema

    @register(RoleSchema, ttl=TTL_RESOURCE)
    def _fetch_role(role_id: str) -> RoleSchema | None:
        ...

    @register_etag(RoleSchema)
    def _role_etag(role: RoleSchema) -> str:
        ...

The registry is module-global. Registration happens at import time —
each ``aleph/logic/<resource>.py`` registers its own classes. The
resolver imports the registry, never the individual logic modules, so
there is no import cycle.
"""

from collections.abc import Iterable, Iterator
from typing import Callable, Type, TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)
FetchOne = Callable[[str], M | None]
FetchMany = Callable[[Iterable[str]], Iterable[M]]
# ETag seed: takes a model, returns a raw version string (e.g.
# "42:1735689600"). The register_etag decorator wraps it with
# _short_hash + quoting so every custom ETag is opaque on the wire.
EtagFn = Callable[..., str]
F = TypeVar("F", bound=Callable[..., str])

_REGISTRY: dict[Type[BaseModel], tuple[FetchOne, FetchMany | None, int | None]] = {}
_ETAG_FNS: dict[Type[BaseModel], EtagFn] = {}


def register(
    cls: Type[M],
    *,
    fetch_many: FetchMany | None = None,
    ttl: int | None = None,
) -> Callable[[FetchOne], FetchOne]:
    """Decorator to register a fetch function for a pydantic schema.

    Args:
        cls: The pydantic schema class to register.
        fetch_many: Optional batch fetcher. If absent, the resolver
            falls back to per-id ``fetch_one`` calls. Recommended for
            entities (ES mget) and other resources that support bulk
            backend reads.
        ttl: Per-class TTL for cache writes. Defaults to ``None`` =
            store-level default. Set short for fast-moving aggregates
            (CollectionStatistics, CollectionDiscovery), long for stable
            resources (Entity, Collection).

    Returns:
        The (unmodified) fetch function.
    """

    def deco(fn: FetchOne) -> FetchOne:
        _REGISTRY[cls] = (fn, fetch_many, ttl)
        return fn

    return deco


def register_etag(cls: Type[M]) -> Callable[[F], F]:
    """Decorator to register a custom ETag seed function.

    The decorated function should return a **raw version string**
    (e.g. ``f"{obj.id}:{epoch}"``). The decorator automatically wraps
    it with ``_short_hash`` + RFC 7232 quoting so the on-wire ETag is
    always opaque and compact — the registered function never has to
    think about hashing or formatting.

    For ES-sourced classes (``EntitySchema``), return
    ``f"{_seq_no}:{_primary_term}"``. For SQLA-sourced classes, return
    ``f"{id}:{updated_at_epoch}"``. The default (no registered
    function) content-hashes ``model_dump_json``.
    """
    from aleph.logic.resolver.etag import _short_hash

    def deco(seed_fn: F) -> F:
        def _wrapped(obj: M) -> str:
            return f'"{_short_hash(seed_fn(obj).encode())}"'

        _ETAG_FNS[cls] = _wrapped
        return seed_fn

    return deco


def fetch_one(cls: Type[M], identifier: str) -> M | None:
    """Look up the fetch function for ``cls`` and call it with
    ``identifier``. Raises ``KeyError`` if no fetcher is registered."""
    fn, _, _ = _REGISTRY[cls]
    return fn(identifier)


def fetch_many(cls: Type[M], ids: Iterable[str]) -> Iterator[M]:
    """Look up the batch fetch function for ``cls`` and call it with
    ``ids``. Falls back to N ``fetch_one`` calls if no batch fetcher
    is registered. Yields only non-None results."""
    _, fn_many, _ = _REGISTRY[cls]
    if fn_many is not None:
        yield from fn_many(ids)
        return
    for identifier in ids:
        item = fetch_one(cls, identifier)
        if item is not None:
            yield item


def get_ttl(cls: Type[M]) -> int | None:
    """Return the per-class TTL override, or None if the resolver
    should use the store-level default."""
    entry = _REGISTRY.get(cls)
    if entry is None:
        return None
    return entry[2]


def get_etag_fn(cls: Type[M]) -> EtagFn | None:
    """Return the custom ETag function for ``cls``, or None if the
    resolver should fall back to a content hash."""
    return _ETAG_FNS.get(cls)
