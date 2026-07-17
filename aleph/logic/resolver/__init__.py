"""Object resolver package.

Two cache layers:

- :class:`Cache` – process-level singleton (``cache``). No per-request
  local dict. Used by SQLA events, logic functions, CLI commands.
- :class:`RequestResolver` – per-request, adds a ``_local`` dict for
  request-scoped deduplication. Used by serializers and view functions.

The module-level :data:`cache` singleton is the canonical interface
for all non-request code: ``from aleph.logic.resolver import cache``.
"""

import functools

from aleph.logic.resolver.core import (
    Cache,
    RequestResolver,
    cache,
    get_resolver,
    get_resolver_store,
)
from aleph.logic.resolver.etag import compute_etag
from aleph.logic.resolver.registry import (
    fetch_many,
    fetch_one,
    register,
    register_etag,
)

__all__ = [
    "Cache",
    "RequestResolver",
    "cache",
    "compute_etag",
    "fetch_many",
    "fetch_one",
    "get_resolver",
    "get_resolver_store",
    "register",
    "register_etag",
    "register_all",
]


@functools.cache
def register_all() -> None:
    """Import all modules that register fetchers via ``@register``.

    Must be called once at app startup (in the Flask app factory or
    test setUp) so the registry is populated before any ``cache.get``
    call. Decorated with ``@functools.cache`` so repeated calls are
    free no-ops.
    """
    import aleph.logic.alerts  # noqa: F401
    import aleph.logic.collections  # noqa: F401
    import aleph.logic.discover  # noqa: F401
    import aleph.logic.entities  # noqa: F401
    import aleph.logic.entitysets  # noqa: F401
    import aleph.logic.export  # noqa: F401
    import aleph.logic.notifications  # noqa: F401
    import aleph.logic.roles  # noqa: F401
