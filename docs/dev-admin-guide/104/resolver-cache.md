# Resolver & Cache

!!! info "Ongoing refactor"
    The resolver/cache layer is part of an ongoing refactor that migrates OpenAleph from Flask to FastAPI. The `cache` singleton described here is the canonical caching interface. A minimal legacy `aleph.cache` module remains only for auth/OAuth session state.

The resolver (`aleph/logic/resolver/`) is a typed cache layer that sits between the API views and the backing stores (PostgreSQL, Elasticsearch). It caches pydantic schema instances in a persistent [anystore](https://docs.investigraph.dev/lib/anystore)-backed store (Redis in production, `memory://` in tests) and provides content-derived ETags for HTTP cache validation.

## Two cache classes

| Class | Lifetime | `_local` dict | Used by |
|---|---|---|---|
| `Cache` | Process (singleton) | No | SQLA events, logic functions, CLI commands |
| `RequestResolver` | Per-request | Yes | Serializers, view functions |

**`Cache`** is the module-level singleton (`from aleph.logic.resolver import cache`). Every `get` hits the persistent store directly. No per-request local dict — safe for long-lived use without memory pressure.

**`RequestResolver`** extends `Cache` with a request-scoped `_local` dict that deduplicates lookups and caches negative hits within a single request. Constructed via `get_resolver()` and discarded on response.

## Cache layers

`cache.get(SchemaClass, identifier)` walks two layers:

1. **Persistent store** ([anystore](https://docs.investigraph.dev/lib/anystore) – Redis, filesystem, S3). Shared across requests and workers. Reads use `model_validate=False` so pydantic validators are skipped on cache hits.
2. **Upstream fetch** via the registry. Each schema class registers a fetch function that knows how to load from the backing store (SQLA `by_id`, ES `get_entity`, etc.).

`RequestResolver.get()` adds a third layer on top:

1. **Local dict** (per-request). Holds both positive and negative hits so repeated lookups within the same request don't re-hit the store.

Misses are **never** persisted to the store layer. Negative results are recorded only in the `RequestResolver`'s local cache.

## Registry

Each schema registers its fetcher at module import time via the `@register` decorator:

```
aleph/logic/roles.py        → @register(RoleSchema, ttl=TTL_RESOURCE)
aleph/logic/entities.py     → @register(EntitySchema, fetch_many=..., ttl=TTL_RESOURCE)
aleph/logic/collections.py  → @register(CollectionSchema, ttl=TTL_RESOURCE)
aleph/logic/collections.py  → @register(CollectionStatistics, ttl=TTL_AGGREGATE)
aleph/logic/collections.py  → @register(GlobalStatistics, ttl=TTL_AGGREGATE)
aleph/logic/discover.py     → @register(DatasetDiscovery, ttl=TTL_AGGREGATE)
aleph/logic/notifications.py → @register(RoleChannels, ttl=TTL_RESOURCE)
```

Optional `fetch_many` enables a batched fast path. For `EntitySchema`, this issues a single ES `mget` instead of N individual queries.

## Cache keys

Store keys are path-style: `ClassName/identifier`.

| Resource | Lookup | Store key |
|---|---|---|
| Role (id=42) | `cache.get(RoleSchema, "42")` | `RoleSchema/42` |
| Collection (id=1) | `cache.get(CollectionSchema, "1")` | `CollectionSchema/1` |
| Entity (id=xyz) | `cache.get(EntitySchema, "xyz")` | `EntitySchema/xyz` |
| CollectionStatistics | `cache.get(CollectionStatistics, "1/stats")` | `CollectionStatistics/1/stats` |

All cache keys use `str(collection_id)` (the integer PK as string). Aggregates use `make_cache_key(collection_id)` to build composite suffixes.

## Content-derived ETags

Every cached object exposes a content ETag via `cache.get_etag(SchemaClass, identifier)`. ETags are:

- **Opaque** – always an 11-character url-safe base64 hash, RFC 7232-quoted.
- **Content-derived** – custom ETag seed functions (registered via `@register_etag`) return a raw version string; the decorator automatically hashes it.
- **Stable across re-fetches** – a spurious `invalidate()` that doesn't change the upstream content produces the same ETag after re-fetch.

## Invalidation

### SQLA-backed models

Automatic via SQLAlchemy `after_insert` / `after_update` / `after_delete` event listeners at the bottom of each model file. For `Collection`, the event also syncs to Elasticsearch atomically (`sync=True`).

### ES-backed models

`EntitySchema` has no SQLA model in the write path. Invalidation is manual in `aleph/logic/entities.py:refresh_entity()`.

### Aggregates

`CollectionStatistics` and `DatasetDiscovery` are invalidated in `aleph/logic/collections.py:refresh_collection()`, called after entity-level changes.

## TTL strategy

TTLs are defined in `aleph/logic/resolver/ttl.py`:

| Constant | Value | Used for |
|---|---|---|
| `STORE_TTL` | 7 days | Store-level default |
| `TTL_RESOURCE` | 24 hours | Stable resources (Role, Collection, Entity, …) |
| `TTL_AGGREGATE` | 2 hours | Volatile aggregates (statistics, discovery) |

TTLs are a **safety net** — every mutation path fires an invalidation.

## The `cache` singleton

```python
from aleph.logic.resolver import cache

entity = cache.get(EntitySchema, entity_id)
etag = cache.get_etag(EntitySchema, entity_id)
cache.invalidate(EntitySchema, entity_id)
cache.refresh(EntitySchema, entity_id)  # re-fetch from upstream
cache.flushall()
```

## View-layer resource accessors

`aleph/views/resources.py` wraps the cache with authz checks:

```python
from aleph.views import resources

# Read paths — pydantic models from cache
entity = resources.get_entity(entity_id, request.authz.READ)
collection = resources.get_collection(collection_id, request.authz.READ)
detail = resources.get_detail_collection(collection_id, request.authz.READ)

# Write paths — SQLA instances for ORM mutations
collection = resources.get_db_collection(collection_id, request.authz.WRITE)
```

## Batch fetch (MGET shortcut)

`cache.get_many(EntitySchema, [id1, id2, ...])` issues a single Redis `MGET` when the store is Redis-backed. This is the critical latency optimisation for the entity search response path.

## Layer separation

```
views/resources.py     → authz-checked accessors (get_entity, get_collection, ...)
views/serializers.py   → dict-based response assembly (uses cache.get via queue/resolve)
logic/collections.py   → resolver registrations + business logic
logic/entities.py      → resolver registrations + entity logic
index/collections.py   → pure ES operations (no resolver, no caching)
model/collection.py    → SQLA model + pydantic schemas + event listeners
```

The index layer is pure ES operations. All resolver registrations live in the logic layer. SQLA events in the model layer handle cache invalidation and ES sync.
