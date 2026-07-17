# Domain Models (Pydantic Layer)

!!! info "Ongoing refactor"
    The pydantic domain layer is part of an ongoing refactor that migrates OpenAleph from Flask to FastAPI. The patterns described here are stable and actively used, but some call sites still go through legacy code paths (e.g. the dict-based serializer in `aleph/views/serializers.py`) that will be replaced as the migration progresses.

OpenAleph's API surface is defined by pydantic v2 models that live alongside the SQLAlchemy ORM classes in `aleph/model/`. This page describes the architectural patterns and conventions for experienced developers diving into the codebase.

## Dual-model layout

Each `aleph/model/<resource>.py` file contains **both** the SQLAlchemy ORM class (the persistence layer) and the pydantic schema (the API/wire layer):

```
aleph/model/role.py
  ├── class Role(db.Model, ...)       # SQLA – owns the DB table
  ├── class RoleSchema(DatedSchema)   # pydantic – owns the wire format
  ├── class RoleChannels(APIBaseModel) # internal cache model
  └── SQLA event listeners             # auto-invalidate resolver cache
```

The pydantic schema is the **single source of truth** for what the API returns. It is also what the resolver caches and what the serializer assembles into a response. The SQLA model is the source of truth for what the DB stores.

The two are connected via `model_config = ConfigDict(from_attributes=True)` on the pydantic side: `RoleSchema.model_validate(role)` reads attributes directly off the SQLA instance. For models where the SQLA columns and the pydantic fields don't align cleanly (e.g. `Collection`, which needs to map flat SQLA columns into nested FTM-canonical structures like `DataCoverage` and `DataPublisher`), a `@model_validator(mode="before")` on the schema handles the conversion.

SQLA event listeners (`after_insert`, `after_update`, `after_delete`) at the bottom of each model file automatically invalidate the resolver cache when a row changes. For `Collection`, the event also syncs the row to Elasticsearch atomically.

## Base classes

```
BaseModel (pydantic)
  └── APIBaseModel          # from_attributes, populate_by_name, cache_key property
        └── DatedSchema     # id: str, created_at, updated_at, deleted_at
              └── RoleSchema, AlertSchema, ExportSchema, ...
```

**`APIBaseModel`** is the root for every API schema. It provides:

- `from_attributes=True` – validate directly from SQLA instances.
- `populate_by_name=True` – aliases work (e.g. `schema_` field aliased to `schema` on the wire).
- `cache_key` property – stable identifier the resolver uses to build store keys. Defaults to `foreign_id` if present, else `str(id)`. Override in subclasses where the cache key differs (e.g. `RoleSchema` and `CollectionSchema` both return `str(id)` because all cache keys use the integer PK).

**`DatedSchema`** adds the SQLA timestamp fields (`id`, `created_at`, `updated_at`, `deleted_at`). The `id` field has a `mode="before"` validator that coerces SQLA integer PKs to strings – the API boundary always uses string IDs.

## FTM-canonical schemas

`EntitySchema` and `CollectionSchema` subclass `ftmq` base models rather than `DatedSchema`:

- `EntitySchema(ftmq.model.entity.EntityModel)` – the canonical FollowTheMoney entity shape (`id`, `caption`, `schema`, `properties`, `datasets`, `referents`) plus Aleph-specific fields (`collection_id`, `collection`, `role`, `countries`, `score`, `highlight`, `latinized`, ...). `collection_id: int` is required (every indexed entity has one).
- `CollectionSchema(ftmq.model.dataset.Dataset)` – the canonical FTM dataset shape (`name`, `title`, `summary`, `publisher`, `coverage`) plus Aleph access-control fields (`creator`, `team`, `writeable`, ...). Has `id: str` (the integer PK as string) and backwards-compat `computed_field` aliases (`foreign_id` → `name`, `label` → `title`).
- `CollectionDetailSchema(CollectionSchema)` – detail-view shape with nested `statistics`, `counts`, and live `status` (procrastinate job state, never cached).

Both define their own `model_config` with `from_attributes=True` and `populate_by_name=True`, and both have a `cache_key` property returning `str(id)`.

## Request body schemas

Request bodies live separately in `aleph/api/requests/` – one module per resource. They encode an HTTP contract (what the client sends), not a persisted shape. The dependency direction is `aleph.api.requests → aleph.model` (never the reverse).

## Aggregates

Some schemas represent pre-computed aggregates rather than individual DB rows:

- `CollectionStatistics` – per-dataset facet counts (schema distribution, countries, names, ...). Keyed by `<collection_id>/stats`.
- `GlobalStatistics` – system-wide counts (total collections, things, countries). Singleton keyed by `global`.
- `DatasetDiscovery` – significant-terms analysis for a dataset. Keyed by `<collection_id>/discovery`.
- `RoleChannels` – notification channels for a role. Keyed by `role_id`.

These inherit from `APIBaseModel` (not `DatedSchema` – they have no SQLA row). Aggregates with composite keys define a `make_cache_key(collection_id)` classmethod.

## Event-driven schemas

- `EventSchema` – event definition (title, template, param_types). The `param_types` field maps param names to pydantic schema classes for resolver dispatch. A `@computed_field` `params` property produces the wire-format `{name: lowered_class_name}` map.
- `CollectionStatus(DatasetStatus)` – procrastinate job state enriched with `collection_id` (computed from the aggregator dataset name).

## Canonical / Xref schemas

- `CanonicalSchema` – canonical cluster (merged entity + constituents). Lives in `model/canonical.py`.
- `StatementSchema` – FTM statement with resolved dataset and entity references.
- `XrefSchema` – cross-reference match pair with score and judgement. Lives in `model/xref.py`.

## View-layer resource accessors

`aleph/views/resources.py` provides authz-checked resource lookups:

```python
from aleph.views import resources

entity = resources.get_entity(entity_id, request.authz.READ)
collection = resources.get_collection(collection_id, request.authz.READ)
detail = resources.get_detail_collection(collection_id, request.authz.READ)
entityset = resources.get_entityset(entityset_id, request.authz.WRITE)
collection = resources.get_db_collection(collection_id, request.authz.WRITE)  # SQLA for write paths
```

Read paths return pydantic models from the resolver cache. Write paths use `get_db_collection` / `get_db_entityset` which return SQLA instances for ORM mutations.

## Serialization conventions

- **`model_dump(model)`** (via `aleph.model.common.model_dump`) is the canonical way to serialize a response. It strips `None`, empty strings, and empty containers recursively. `cache_key` is a regular `@property` so it never appears in the dump.
- The serializer's `_to_dict` method handles pydantic models via `isinstance(obj, BaseModel)` → `model_dump()`.
- **`exclude_none=True`** is the default. The frontend uses defensive accessors, so omitting empty values is safe and reduces payload size.
