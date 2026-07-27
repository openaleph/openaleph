# Assemblers (Response Builder Layer)

!!! info "Ongoing refactor"
    The assembler layer is part of an ongoing refactor that migrates OpenAleph from Flask to FastAPI. The patterns described here are stable and actively used. A thin Flask shim (`aleph/views/serializers.py`) adapts the assemblers to the legacy `Serializer` interface that Flask views expect. This shim will disappear once the FastAPI migration is complete.

Assemblers enrich pydantic schema objects with request-scoped data — links, writeable flags, resolved nested resources — before they are serialized to the API response. They sit between the [resolver cache](resolver-cache.md) and the HTTP layer:

```
Resolver cache → pydantic schema → Assembler → enriched schema → model_dump() → JSON response
```

## Architecture

```
aleph/api/assemblers/
├── base.py           # Generic Assembler with auto-resolution
├── collection.py     # CollectionAssembler
├── entity.py         # EntityAssembler
└── __init__.py

aleph/views/serializers.py   # Flask shim: Serializer classes that wrap assemblers
```

## Instance-based design

Assemblers are instantiated once per request with `resolver`, `authz`, and `detail` bound:

```python
from aleph.api.assemblers.entity import EntityAssembler
from aleph.logic.resolver import RequestResolver

resolver = RequestResolver()
assembler = EntityAssembler(resolver, authz, detail=True)

entity = assembler.assemble(entity_schema)       # single object
entities = assembler.assemble_many(entity_list)   # batch with prefetch
```

Internal helpers access `self.resolver`, `self.authz`, `self.detail` — no parameter threading. When one assembler needs another (e.g. `EntityAssembler` resolving the nested collection), it constructs a child instance sharing the same resolver and authz:

```python
# Inside EntityAssembler
def _resolve_collection(self, collection_id):
    coll = self.resolver.get_or_404(CollectionSchema, str(collection_id))
    return CollectionAssembler(self.resolver, self.authz).assemble(coll)
```

## Generic auto-resolution via `ResolveFrom`

Most pydantic schemas declare pairs of `foo_id: str` + `foo: FooSchema | None` fields. The base `Assembler` auto-resolves these using metadata markers:

```python
from typing import Annotated
from aleph.model.common import ResolveFrom

class EntitySetSchema(DatedSchema):
    collection_id: str
    collection: Annotated[
        CollectionSchema | None,
        ResolveFrom("collection_id", CollectionSchema),
    ] = None

    role_id: str
    role: Annotated[
        RoleSchema | None,
        ResolveFrom("role_id", RoleSchema),
    ] = None
```

`ResolveFrom("collection_id", CollectionSchema)` tells the assembler:

1. Read the cache key from `obj.collection_id`
2. Look up `CollectionSchema` in the resolver via `resolver.get(CollectionSchema, key)`
3. Set the result on `obj.collection`

This happens automatically in `Assembler.assemble()` — subclasses that call `super().assemble(obj)` get it for free. Resolution is **recursive**: a resolved `CollectionSchema` that itself has `ResolveFrom` fields (e.g. `creator`) gets its nested fields resolved too.

### Batch pre-loading

`assemble_many()` calls `prefetch()` before iterating. The base `prefetch` scans all objects for `ResolveFrom` metadata, collects the keys per schema type, and issues one `resolver.get_many()` per type — turning N+1 lookups into a constant number of batch fetches.

## Subclass pattern

Simple resources override `assemble` and call `super()` for generic resolution:

```python
class AlertAssembler(Assembler):
    def assemble(self, obj: AlertSchema) -> AlertSchema:
        obj = super().assemble(obj)  # auto-resolves ResolveFrom fields
        obj.links = {"self": url_for("alerts_api.view", alert_id=obj.id)}
        obj.writeable = self.authz.can_write_role(obj.role_id)
        return obj
```

Complex resources (`EntityAssembler`, `CollectionAssembler`) override `assemble` and `prefetch` entirely — they have custom resolution logic (recursive entity properties, archive URLs, team visibility filtering) that the generic path can't handle.

Resources with no custom logic (`SimilarAssembler`, `MappingAssembler`, `TagAssembler`) just inherit `Assembler` directly — the generic auto-resolution is all they need.

## Flask shim (`serializers.py`)

The Flask views call `FooSerializer.jsonify(obj)` or `FooSerializer.jsonify_result(result)`. Each serializer is a two-line class:

```python
class AlertSerializer(Serializer):
    SCHEMA = AlertSchema
    ASSEMBLER = AlertAssembler
```

The `Serializer` base handles the pipeline:

1. `_to_schema(obj)` — validate input to pydantic (`model_validate` from SQLA object, dict, or pass-through if already a `BaseModel`)
2. `_make_assembler(authz)` — construct the assembler instance with a fresh `RequestResolver`
3. `assemble(schema)` — run the assembler
4. `model_dump(assembled)` — serialize to dict for the JSON response

```python
class Serializer:
    SCHEMA: type[BaseModel] | None = None
    ASSEMBLER: type[Assembler] = Assembler

    def serialize(self, obj, authz=None):
        schema = self._to_schema(obj)
        assembled = self._make_assembler(authz).assemble(schema)
        return model_dump(assembled) if assembled else None
```

## FastAPI end state

Once the Flask→FastAPI migration is complete, the `Serializer` shim disappears. FastAPI endpoints return pydantic models directly:

```python
# Simple resource — generic assembler is enough
@router.get("/api/2/alerts/{alert_id}")
def view(alert: AlertReadDep, assembler: AlertAssemblerDep) -> AlertSchema:
    return assembler.assemble(alert)

# Complex resource — custom assembler
@router.get("/api/2/entities/{entity_id}")
def view(entity: EntityReadDep, assembler: EntityAssemblerDep) -> EntitySchema:
    return assembler.assemble(entity)
```

The assemblers themselves don't change — they're already Flask-free. `Depends()` injects `resolver` and `authz`, constructs the assembler once per request.

## All assembler subclasses

| Assembler | Schema | Custom logic |
|---|---|---|
| `CollectionAssembler` | `CollectionSchema` | Links, creator/team resolution with visibility filter |
| `EntityAssembler` | `EntitySchema` | Recursive property resolution, archive URLs, latinized, canonical cluster, document processing status |
| `RoleAssembler` | `RoleSchema` | Sensitive field stripping (email, api_key, etc.) when nested or not writeable |
| `AlertAssembler` | `AlertSchema` | Links, writeable from role ownership |
| `ExportAssembler` | `ExportSchema` | Download link from archive URL |
| `PermissionAssembler` | `PermissionSchema` | Writeable from role readability |
| `EntitySetAssembler` | `EntitySetSchema` | Writeable from collection, shallow flag |
| `EntitySetItemAssembler` | `EntitySetItemSchema` | Authz gate on collection, writeable from entityset collection |
| `XrefAssembler` | `XrefSchema` | Drop results with unresolvable entity/match, writeable from nested entities |
| `BookmarkAssembler` | `BookmarkSchema` | Resolve entity, drop if unresolvable |
| `NotificationAssembler` | `NotificationSchema` | Resolve actor + polymorphic event params |
| `StatementAssembler` | `StatementSchema` | Resolve dataset (foreign_id → collection), entity values |
| `CanonicalAssembler` | `CanonicalSchema` | Writeable from collection_ids, latinized merged proxy |
| `SimilarAssembler` | `SimilarSchema` | Generic only (auto-resolution) |
| `MappingAssembler` | `MappingSchema` | Generic only |
| `TagAssembler` | `TagSchema` | Generic only |
