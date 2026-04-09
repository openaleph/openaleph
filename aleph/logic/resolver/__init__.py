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
"""

from aleph.logic.resolver._legacy import (
    LOADERS,
    CollectionByForeignId,
    cached_entities_by_ids,
    get,
    queue,
    resolve,
)
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
