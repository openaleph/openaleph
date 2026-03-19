from datetime import datetime
from typing import Self

from anystore.types import SDict
from anystore.util.data import model_dump
from banal import hash_data
from nomenklatura.resolver.edge import Edge
from nomenklatura.resolver.identifier import StrIdent
from pydantic import BaseModel, ConfigDict, Field

SYSTEM_USER = "__system__"


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

    @property
    def _id(self) -> str:
        return edge_id(self.source, self.target)

    @property
    def _source(self) -> SDict:
        # turn into ES clean doc, but always include score for Edge.from_dict compat
        data = model_dump(self, clean=True)
        if "score" not in data:
            data["score"] = None
        return data

    @classmethod
    def from_edge(cls, e: Edge, **metadata) -> Self:
        data = e.to_dict()
        data.update(**metadata)
        return cls(**data)
