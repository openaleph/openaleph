from datetime import datetime
from typing import Annotated, Self

from anystore.types import SDict
from anystore.util.data import model_dump
from banal import hash_data
from nomenklatura.judgement import Judgement
from nomenklatura.resolver.edge import Edge
from nomenklatura.resolver.identifier import StrIdent
from pydantic import BaseModel, ConfigDict, Field, computed_field

from aleph.model.collection import CollectionSchema
from aleph.model.common import APIBaseModel, ResolveFrom
from aleph.model.entity import EntitySchema
from aleph.settings import SETTINGS

SYSTEM_USER = SETTINGS.SYSTEM_USER


def edge_id(source: StrIdent, target: StrIdent) -> str:
    """Deterministic document ID from a pair of entity IDs."""
    pair = tuple(sorted([str(source), str(target)]))
    return hash_data(pair)


class ESEdge(BaseModel):
    """Extend nomenklatura Edge with OpenAleph metadata"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    source: str
    target: str
    judgement: str
    score: float | None = None
    user: str = SYSTEM_USER
    created_at: datetime | None = None
    deleted_at: datetime | None = None
    source_collection_id: set[int] = set()
    target_collection_id: set[int] = set()
    method: str | None = None
    schema_: str | None = Field(None, alias="schema")
    text: list[str] = []
    countries: list[str] = []

    @computed_field
    @property
    def collection_id(self) -> set[int]:
        return self.source_collection_id | self.target_collection_id

    @property
    def _id(self) -> str:
        return edge_id(self.source, self.target)

    @property
    def _source(self) -> SDict:
        # turn into ES clean doc, but always include score for Edge.from_dict compat
        data = model_dump(self, clean=True)
        data["score"] = data.get("score")
        return data

    @classmethod
    def from_edge(cls, e: Edge, **metadata) -> Self:
        data = e.to_dict()
        data.update(**metadata)
        return cls(**data)


# === API wire-format schemas ===
#
# ESEdge above is the internal storage shape for the nomenklatura
# resolver. The schemas below are the API wire formats that the
# response builder produces from edges + canonical clusters.


class XrefSchema(APIBaseModel):
    """Wire format for a cross-reference match — one ranked pair of
    similar entities, perspective-aware so the requested collection's
    entity is always served as ``entity`` (left).

    Both ``entity`` and ``match`` are required: ``XrefSerializer``
    drops the row entirely if either side fails to resolve, so a
    half-populated XrefSchema would be a bug. ``score`` is also
    required — every edge produced by the nomenklatura resolver
    carries one.
    """

    source: str
    target: str
    entity: Annotated[EntitySchema | None, ResolveFrom("source", EntitySchema)] = None
    match: Annotated[EntitySchema | None, ResolveFrom("target", EntitySchema)] = None
    score: float
    collections: list[CollectionSchema] = []
    writeable: bool = False

    # ES edge metadata — needed for orientation and collection resolution
    source_collection_id: list[int] = []
    target_collection_id: list[int] = []
    collection_id: list[int] = []

    method: str | None = None
    judgement: Judgement | None = None

    @property
    def cache_key(self) -> str:
        # Pair-deterministic key matching ESEdge.edge_id semantics.
        # Both entity and match are required so neither id can be empty.
        a, b = sorted([self.entity.id, self.match.id])
        return f"{a}/{b}"
