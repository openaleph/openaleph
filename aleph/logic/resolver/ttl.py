"""Central TTL constants for the resolver cache.

All per-class TTLs are defined here so they can be tuned in one place.
The store-level default (``STORE_TTL``) applies when a registered class
doesn't specify its own ``ttl=`` in the ``@register`` decorator.

TTLs are a safety net, not the primary invalidation mechanism — every
mutation path calls ``Resolver.invalidate()`` so stale data is evicted
immediately. Long TTLs are safe and avoid unnecessary upstream fetches.
"""

# Store-level default — passed to ``get_store()`` in
# ``get_resolver_store()``.
STORE_TTL = 7 * 24 * 60 * 60  # 7 days

# Stable resources (Role, Collection, Entity, Alert, …).
# Mutations call invalidate(); TTL is just a backstop.
TTL_RESOURCE = 24 * 60 * 60  # 24 hours

# Aggregates (CollectionStatistics, CollectionStatus, CollectionDiscovery).
# These are recomputed during ingestion — invalidate() covers most
# cases but a shorter backstop catches edge cases where the recompute
# runs outside the normal mutation path (e.g. direct ES update).
TTL_AGGREGATE = 2 * 60 * 60  # 2 hours
