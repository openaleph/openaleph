"""Object resolver package.

The typed :class:`Resolver` class plus its registry helpers
(:func:`register`, :func:`register_etag`).

The module-level :data:`cache` singleton is the canonical interface
for all callers: ``from aleph.logic.resolver import cache``.
"""

from aleph.logic.resolver.core import (
    Resolver,
    cache,
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
    "Resolver",
    "cache",
    "compute_etag",
    "fetch_many",
    "fetch_one",
    "get_resolver",
    "get_resolver_store",
    "is_registered",
    "register",
    "register_etag",
]
