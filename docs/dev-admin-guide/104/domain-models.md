# Domain Models (Pydantic Layer)

!!! info "Ongoing refactor"
    The pydantic domain layer is part of an ongoing refactor that migrates OpenAleph from Flask to FastAPI. The patterns described here are stable and actively used, but some call sites still go through legacy code paths (e.g. the dict-based serializer in `aleph/views/serializers.py`) that will be replaced as the migration progresses.

OpenAleph's API surface is defined by pydantic v2 models that live alongside the SQLAlchemy ORM classes in `aleph/model/`. This page describes the architectural patterns and conventions for experienced developers diving into the codebase.

## Dual-model layout

Each `aleph/model/<resource>.py` file contains **both** the SQLAlchemy ORM class (the persistence layer) and the pydantic schema (the API/wire layer):

```
aleph/model/role.py
  ├── class Role(db.Model, ...)       # SQLA – owns the DB table
  └── class RoleSchema(DatedSchema)   # pydantic – owns the wire format
```

The pydantic schema is the **single source of truth** for what the API returns. It is also what the resolver caches and what the serializer assembles into a response. The SQLA model is the source of truth for what the DB stores.

The two are connected via `model_config = ConfigDict(from_attributes=True)` on the pydantic side: `RoleSchema.model_validate(role)` reads attributes directly off the SQLA instance. For models where the SQLA columns and the pydantic fields don't align cleanly (e.g. `Collection`, which needs to map flat SQLA columns into nested FTM-canonical structures like `DataCoverage` and `DataPublisher`), a `@model_validator(mode="before")` on the schema handles the conversion.

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
- `cache_key` property – stable identifier the resolver uses to build store keys. Defaults to `foreign_id` if present, else `str(id)`. Override in subclasses where the cache key is something else (e.g. `RoleSchema` returns `str(id)` because every FK references roles by int PK, not by `foreign_id`).

**`DatedSchema`** adds the SQLA timestamp fields (`id`, `created_at`, `updated_at`, `deleted_at`). The `id` field has a `mode="before"` validator that coerces SQLA integer PKs to strings – the API boundary always uses string IDs.

## FTM-canonical schemas

`EntitySchema` and `CollectionSchema` subclass `ftmq` base models rather than `DatedSchema`:

- `EntitySchema(ftmq.model.entity.EntityModel)` – the canonical FollowTheMoney entity shape (`id`, `caption`, `schema`, `properties`, `datasets`, `referents`) plus Aleph-specific fields (`collection`, `role`, `countries`, `score`, `highlight`, `latinized`, ...).
- `CollectionSchema(ftmq.model.dataset.Dataset)` – the canonical FTM dataset shape (`name`, `title`, `summary`, `publisher`, `coverage`) plus Aleph access-control fields (`creator`, `team`, `writeable`, ...).

Both define their own `model_config` with `from_attributes=True` and `populate_by_name=True`, and both have a `cache_key` property. `CollectionSchema.cache_key` returns `self.name` (= `Collection.foreign_id`). `EntitySchema.cache_key` returns `self.id` (the ES document ID).

## Request body schemas

Request bodies live separately in `aleph/api/requests/` – one module per resource. They encode an HTTP contract (what the client sends), not a persisted shape. The dependency direction is `aleph.api.requests → aleph.model` (never the reverse).

## Aggregates

Some schemas represent pre-computed aggregates rather than individual DB rows:

- `CollectionStatistics` – per-dataset facet counts (schema distribution, countries, names, ...).
- `CollectionStatus` – processing job status for a dataset.
- `DatasetDiscovery` – significant-terms analysis for a dataset.

These inherit from `APIBaseModel` (not `DatedSchema` – they have no SQLA row) and define a `make_cache_key(foreign_id)` classmethod that produces a composite suffix (e.g. `"foo-dataset/stats"`). The instance `cache_key` property delegates to the same classmethod.

## Serialization conventions

- **`model_dump(model, clean=True)`** (via `aleph.model.common.model_dump`) is the canonical way to serialize a response. It strips `None`, empty strings, and empty containers recursively. The `cache_key` property is a plain `@property` (not a `computed_field`) so it never appears in the dump.
- **`exclude_none=True`** is the default. The frontend uses defensive accessors, so omitting empty values is safe and reduces payload size.
