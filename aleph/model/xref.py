from datetime import datetime
from typing import Self

from anystore.types import SDict
from anystore.util.data import model_dump
from banal import hash_data
from nomenklatura.resolver.edge import Edge
from nomenklatura.resolver.identifier import StrIdent
from pydantic import BaseModel, ConfigDict, Field, computed_field
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from aleph.core import db
from aleph.settings import SETTINGS

SYSTEM_USER = SETTINGS.SYSTEM_USER
NODE_ID_LEN = 512


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


# === SQL system of record (see xref-resolver-sql.md) ===
#
# The judgement graph lives in Postgres: `xref_edge` holds decided edges
# (positive/negative/unsure — suggestions stay in ES), `xref_cluster` is
# the cluster membership materialized in the same transaction as the
# edges. ESEdge above remains the wire/projection format for the ES index.


class XrefEdge(db.Model):
    """A decided judgement edge between two entity identifiers.

    Exactly one live (deleted_at IS NULL) row exists per pair; superseding
    a decision soft-deletes the old row and inserts a new one, preserving
    history. Column order (target, source) follows Identifier.pair: the
    target is the greater identifier.
    """

    __tablename__ = "xref_edge"

    id = db.Column(db.BigInteger, primary_key=True)
    target = db.Column(db.Unicode(NODE_ID_LEN), nullable=False)
    source = db.Column(db.Unicode(NODE_ID_LEN), nullable=False)
    judgement = db.Column(db.Unicode(14), nullable=False)
    score = db.Column(db.Float, nullable=True)
    user = db.Column(db.Unicode(NODE_ID_LEN), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    source_collection_ids = db.Column(
        ARRAY(db.Integer), nullable=False, server_default="{}"
    )
    target_collection_ids = db.Column(
        ARRAY(db.Integer), nullable=False, server_default="{}"
    )
    # method, schema, text, countries, future fields
    meta = db.Column(JSONB, nullable=False, server_default="{}")

    __table_args__ = (
        db.Index(
            "ix_xref_edge_pair_live",
            "source",
            "target",
            unique=True,
            postgresql_where=db.text("deleted_at IS NULL"),
        ),
        db.Index(
            "ix_xref_edge_source_live",
            "source",
            postgresql_where=db.text("deleted_at IS NULL"),
        ),
        db.Index(
            "ix_xref_edge_target_live",
            "target",
            postgresql_where=db.text("deleted_at IS NULL"),
        ),
        db.Index(
            "ix_xref_edge_created_live",
            "created_at",
            postgresql_where=db.text("deleted_at IS NULL"),
        ),
        db.Index(
            "ix_xref_edge_source_colls",
            "source_collection_ids",
            postgresql_using="gin",
        ),
        db.Index(
            "ix_xref_edge_target_colls",
            "target_collection_ids",
            postgresql_using="gin",
        ),
    )


class XrefCluster(db.Model):
    """Materialized cluster membership, maintained transactionally.

    One row per node of every positive cluster — entities, all NK-* ids
    (including intermediate ones), legacy profile ids — each pointing to
    the cluster's current canonical, which also has a self-row. Singletons
    have no rows. The primary key on entity_id IS the union-find invariant:
    a node belongs to exactly one cluster, enforced by the database.

    Auth is deliberately not modeled here: membership resolves the
    candidate cluster; per-user visibility is applied over the cluster's
    edges at read time (aleph/logic/xref/store.py).
    """

    __tablename__ = "xref_cluster"

    entity_id = db.Column(db.Unicode(NODE_ID_LEN), primary_key=True)
    canonical_id = db.Column(db.Unicode(NODE_ID_LEN), nullable=False, index=True)
