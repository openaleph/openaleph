"""Wire-format schemas for canonical clusters and statements.

Canonical clusters are the merged view of deduplicated entities
resolved by the nomenklatura resolver. Statements are the individual
FTM (entity, schema, prop, value) tuples that make up a merged entity.

Decoupled from xref internals — these are API-facing resources with
their own endpoint (``views/canonical_api.py``).
"""

from datetime import datetime

from pydantic import Field

from aleph.model.collection import CollectionSchema
from aleph.model.common import APIBaseModel
from aleph.model.entity import EntitySchema


class CanonicalSchema(APIBaseModel):
    """Wire format for a canonical (clustered) entity — replaces the
    legacy Profile shape.

    A canonical cluster is the merged view of N constituent entities
    that the resolver has judged the same. ``merged`` is the FTM
    proxy of the merged result; ``entities`` are the constituent
    entities (typically served shallow). The cluster only exists
    *because* there's a merged proxy — ``merged`` is required, and
    the legacy ``CanonicalSerializer._serialize`` raises ``KeyError``
    on the same invariant.
    """

    id: str
    merged: EntitySchema
    entities: list[EntitySchema] = []
    collection_ids: list[str] = []
    writeable: bool = False
    shallow: bool = False

    @property
    def cache_key(self) -> str:
        return self.id


class StatementSchema(APIBaseModel):
    """Wire format for a single FollowTheMoney statement
    (``GET /api/2/statements`` and embedded in canonical lineage views).

    A statement is one (entity, schema, prop, value) tuple sourced from
    one dataset — all five parts are required. ``id`` is also required
    because :class:`followthemoney.statement.Statement` always has one
    (the ``Statement.__init__`` derives it via ``generate_key()`` if no
    explicit id was passed). When ``prop`` is an entity-typed property
    the value is resolved to a nested :class:`EntitySchema` by the
    response builder.
    """

    id: str
    entity_id: str
    schema_: str = Field(alias="schema")
    prop: str
    value: str | EntitySchema
    dataset: CollectionSchema | str

    canonical_id: str
    prop_type: str
    first_seen: datetime | None = None
    last_seen: datetime | None = None

    @property
    def cache_key(self) -> str:
        return self.id
