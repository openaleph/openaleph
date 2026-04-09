# Resolver & Cache

!!! info "Ongoing refactor"
    The resolver/cache layer is part of an ongoing refactor that migrates OpenAleph from Flask to FastAPI. The new `cache` singleton described here coexists with the legacy `aleph.cache` module during the transition. Some call sites (serializer, xref pipeline) still use the legacy free-function API (`queue`/`resolve`/`get`) which will be ported as the migration progresses.

The resolver (`aleph/logic/resolver/`) is a per-request batch loader that sits between the API layer and the backing stores (PostgreSQL, Elasticsearch). It caches pydantic schema instances in a persistent [anystore](https://docs.investigraph.dev/lib/anystore)-backed store (Redis in production, `memory://` in tests) and provides content-derived ETags for HTTP cache validation.

## Three-layer cache

Every `resolver.get(SchemaClass, identifier)` call walks three layers:

1. **Local dict** (per-request). Garbage-collected when the request ends. Holds both positive hits and *negative* hits (a `None` sentinel records "we already asked upstream and it doesn't exist – don't ask again this request").
2. **Persistent store** (anystore – Redis, filesystem, S3). Shared across requests and workers. Reads use `model_validate=False` so pydantic validators are skipped on cache hits – the data was already validated at write time. This is the main performance win for FTM-heavy schemas like `EntitySchema`.
3. **Upstream fetch** via the registry. Each schema class registers a fetch function (and optionally a batch fetch function) that knows how to load from the backing store (SQLA `by_id`, ES `get_entity`, etc.).

Misses are **never** persisted to the store layer. A negative result is recorded only in the per-request local cache. This prevents cache poisoning: a deleted entity doesn't stay "missing" across requests until explicit invalidation – the next request re-checks upstream.

## Registry

Each schema registers its fetcher at module import time via the `@register` decorator in its owning logic module:

```
aleph/logic/roles.py     → @register(RoleSchema, ttl=TTL_RESOURCE)
aleph/logic/entities.py  → @register(EntitySchema, fetch_many=..., ttl=TTL_RESOURCE)
aleph/index/collections.py → @register(CollectionSchema, ttl=TTL_RESOURCE)
```

The registry is module-global in `aleph/logic/resolver/registry.py`. The resolver imports the registry, never the individual logic modules, so there are no import cycles.

Optional `fetch_many` enables a batched fast path. For `EntitySchema`, this issues a single ES `mget` instead of N individual queries – critical for the search response hot path (~120 entities per page).

## Cache keys

Store keys are path-style: `ClassName/identifier`.

| Resource | Lookup | Store key |
|---|---|---|
| Role (id=42) | `cache.get(RoleSchema, "42")` | `RoleSchema/42` |
| Collection (foreign_id=foo) | `cache.get(CollectionSchema, "foo")` | `CollectionSchema/foo` |
| Entity (id=xyz) | `cache.get(EntitySchema, "xyz")` | `EntitySchema/xyz` |
| CollectionStatistics | `cache.get(CollectionStatistics, CollectionStatistics.make_cache_key("foo"))` | `CollectionStatistics/foo/stats` |

For leaf schemas the identifier is a plain `str(id)` or `foreign_id`. For aggregates the caller builds a composite key via the model's `make_cache_key` classmethod.

## Content-derived ETags

Every cached object exposes a content ETag via `cache.get_etag(SchemaClass, identifier)`. ETags are:

- **Opaque** – always an 11-character url-safe base64 hash, RFC 7232-quoted. No raw IDs, timestamps, or content leak on the wire.
- **Content-derived** – changes exactly when the underlying data changes. Custom ETag seed functions (registered via `@register_etag`) return a raw version string (e.g. `f"{id}:{updated_at}"`); the decorator automatically hashes it. The default (no custom function) hashes `model_dump_json()`.
- **Stable across re-fetches** – a spurious `invalidate()` that doesn't change the upstream content produces the same ETag after re-fetch, so the client still gets a 304.

For list-style responses, `cache.get_many_etag(SchemaClass, ids, extra="query_string")` combines constituent ETags into a single response ETag. The `extra` discriminator ensures different filter combinations get different ETags.

## Invalidation

### SQLA-backed models

Invalidation is automatic via SQLAlchemy `after_insert` / `after_update` / `after_delete` event listeners registered at the bottom of each model file. Any ORM operation that modifies a row fires the listener, which calls `cache.invalidate(SchemaClass, identifier)`. There is nothing to forget at the call site.

### ES-backed models

`EntitySchema` has no SQLA model in the write path. Invalidation is manual in `aleph/logic/entities.py:refresh_entity()`, which is the convergence point for all entity mutations (`upsert_entity`, `delete_entity`, `prune_entity`).

### Aggregates

`CollectionStatistics` and `DatasetDiscovery` are invalidated in `aleph/logic/collections.py:refresh_collection()`, which is called after any entity-level change that could affect the aggregate counts.

## TTL strategy

TTLs are defined in `aleph/logic/resolver/ttl.py`:

| Constant | Value | Used for |
|---|---|---|
| `STORE_TTL` | 7 days | Store-level default (anystore `default_ttl`) |
| `TTL_RESOURCE` | 24 hours | Stable resources (Role, Collection, Entity, ...) |
| `TTL_AGGREGATE` | 2 hours | Volatile aggregates (statistics, discovery) |

TTLs are a **safety net**, not the primary invalidation mechanism. Every mutation path fires an invalidation, so stale data is evicted immediately. The TTL catches edge cases where invalidation is missed (e.g. direct DB update outside the ORM).

## The `cache` singleton

`aleph.logic.resolver` exports a module-level `cache` instance:

```python
from aleph.logic.resolver import cache

entity = cache.get(EntitySchema, entity_id)
etag = cache.get_etag(EntitySchema, entity_id)
cache.invalidate(EntitySchema, entity_id)
cache.flush_all()
```

All methods (`get`, `get_many`, `get_etag`, `get_many_etag`, `invalidate`, `invalidate_many`, `invalidate_prefix`, `flush_all`) are instance methods that act on the instance's store, enabling future storage tiering (e.g. routing hot schemas to Redis and cold schemas to filesystem).

## Batch fetch (MGET shortcut)

`cache.get_many(EntitySchema, [id1, id2, ...])` splits into the same three layers. For the persistent-store layer, when the underlying store is Redis-backed, the resolver issues a single `MGET` command (via `_mget`) instead of N sequential `GET` calls. This is the critical latency optimisation for the entity search response path. For non-Redis backends the resolver falls back to per-key reads transparently.

## Legacy API

The legacy free-function API (`queue` / `resolve` / `get` / `cached_entities_by_ids` in `aleph/logic/resolver/_legacy.py`) is preserved for call sites that haven't been migrated yet (the serializer, xref pipeline, diagram builder, facet code). It is loaded lazily via `__getattr__` in the package `__init__.py` to avoid circular imports. It will be removed once all call sites are ported.
