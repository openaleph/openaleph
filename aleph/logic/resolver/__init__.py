"""Object resolver package.

Two parallel APIs live here:

1. The typed :class:`Resolver` class plus its registry helpers
   (:func:`register`, :func:`register_etag`) — see :mod:`.core` and
   :mod:`.registry`. New code should use this.

2. The legacy free-function API (``queue`` / ``resolve`` / ``get`` /
   ``cached_entities_by_ids``) — see :mod:`._legacy`.

Both surfaces are re-exported here so callers can do
``from aleph.logic.resolver import Resolver`` or
``from aleph.logic.resolver import queue, resolve, get``.

The legacy API is loaded lazily (via ``__getattr__``) to avoid
circular imports — the legacy module imports fetcher functions from
``aleph.logic.{roles,alerts,...}`` which in turn register with the
new resolver registry at import time.
"""

from aleph.logic.resolver.core import (
    Resolver,
    get_resolver,
    get_resolver_store,
)
from aleph.logic.resolver.etag import compute_etag
from aleph.logic.resolver.registry import (
    fetch_many,
    fetch_one,
    is_registered,
    register,
    register_etag,
)

__all__ = [
    # New API
    "Resolver",
    "compute_etag",
    "fetch_many",
    "fetch_one",
    "get_resolver",
    "get_resolver_store",
    "is_registered",
    "register",
    "register_etag",
    # Legacy API (deprecated)
    "LOADERS",
    "CollectionByForeignId",
    "cached_entities_by_ids",
    "get",
    "queue",
    "resolve",
]

_LEGACY_NAMES = frozenset(
    {
        "LOADERS",
        "CollectionByForeignId",
        "cached_entities_by_ids",
        "get",
        "queue",
        "resolve",
    }
)


def __getattr__(name: str):
    if name in _LEGACY_NAMES:
        from aleph.logic.resolver import _legacy

        return getattr(_legacy, name)
    raise AttributeError(f"module 'aleph.logic.resolver' has no attribute {name}")
