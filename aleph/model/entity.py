import logging
from datetime import datetime
from typing import Any

from flask_babel import gettext
from followthemoney import EntityProxy, model
from followthemoney.exc import InvalidData
from followthemoney.types import registry
from ftmq.model.entity import EntityModel
from nomenklatura.judgement import Judgement
from pydantic import ConfigDict, field_validator
from sqlalchemy.dialects.postgresql import JSONB

from aleph.core import db
from aleph.model.collection import Collection, CollectionSchema
from aleph.model.common import (
    ENTITY_ID_LEN,
    APIBaseModel,
    DatedModel,
    SDict,
    iso_text,
    make_textid,
)
from aleph.model.role import RoleSchema
from aleph.util import make_entity_proxy

log = logging.getLogger(__name__)


class Entity(db.Model, DatedModel):
    THING = "Thing"
    LEGAL_ENTITY = "LegalEntity"
    ANALYZABLE = "Analyzable"

    id = db.Column(
        db.String(ENTITY_ID_LEN),
        primary_key=True,
        default=make_textid,
        nullable=False,
        unique=False,
    )
    schema = db.Column(db.String(255), index=True)
    data = db.Column("data", JSONB)

    role_id = db.Column(db.Integer, db.ForeignKey("role.id"), nullable=True)
    collection_id = db.Column(db.Integer, db.ForeignKey("collection.id"), index=True)
    collection = db.relationship(
        Collection, backref=db.backref("entities", lazy="dynamic")
    )

    @property
    def model(self):
        return model.get(self.schema)

    def update(self, data, collection, sign=True):
        proxy = make_entity_proxy(data, cleaned=False)
        if sign:
            proxy = collection.ns.apply(proxy)
        self.schema = proxy.schema.name
        previous = self.to_proxy()
        for prop in proxy.schema.properties.values():
            # Do not allow the user to overwrite hashes because this could
            # lead to a user accessing random objects.
            if prop.type == registry.checksum:
                prev = previous.get(prop)
                proxy.set(prop, prev, cleaned=True, quiet=True)
        self.data = proxy.properties
        self.updated_at = datetime.utcnow()
        db.session.add(self)

    def to_proxy(self) -> EntityProxy:
        data = {
            "id": self.id,
            "schema": self.schema,
            "properties": self.data,
            "created_at": iso_text(self.created_at),
            "updated_at": iso_text(self.updated_at),
            "role_id": self.role_id,
            "mutable": True,
        }
        return make_entity_proxy(data, cleaned=False)

    @classmethod
    def create(cls, data, collection, sign=True, role_id=None):
        entity = cls()
        entity_id = data.get("id") or make_textid()
        if not registry.entity.validate(entity_id):
            raise InvalidData(gettext("Invalid entity ID"))
        entity.id = collection.ns.sign(entity_id)
        entity.collection_id = collection.id
        entity.role_id = role_id
        entity.update(data, collection, sign=sign)
        return entity

    @classmethod
    def by_id(cls, entity_id, collection=None):
        q = cls.all().filter(cls.id == entity_id)
        if collection is not None:
            q = q.filter(cls.collection_id == collection.id)
        return q.first()

    @classmethod
    def by_collection(cls, collection_id):
        q = cls.all()
        q = q.filter(Entity.collection_id == collection_id)
        q = q.yield_per(5000)
        return q

    @classmethod
    def delete_by_collection(cls, collection_id):
        pq = db.session.query(cls)
        pq = pq.filter(cls.collection_id == collection_id)
        pq.delete(synchronize_session=False)

    def __repr__(self):
        return "<Entity(%r, %r)>" % (self.id, self.schema)


# === Pydantic schemas ===
#
# Entities are FollowTheMoney entities served via OpenAleph. The wire
# format extends the canonical ``ftmq.model.entity.EntityModel`` (which
# itself wraps the FTM ``EntityModel``) with Aleph-specific extras:
# nested collection / role, search-time fields (``score``, ``highlight``),
# document-detail fields (``safeHtml``, ``processing_status``,
# ``links.file``/``pdf``/``csv``), per-user state (``bookmarked``) and
# the runtime ``links`` block.
#
# The ``properties`` field is inherited from ``EntityModel`` and remains
# a ``Mapping[str, Sequence[str | EntityModel]]`` — nested entities
# inside properties are served in the FTM-canonical "shallow" form
# without Aleph extras (matching the existing ``shallow=True`` behaviour
# of the legacy serializer).


class EntitySchema(EntityModel):
    """Wire format for an OpenAleph entity.

    Subclasses :class:`ftmq.model.entity.EntityModel` for the canonical
    FollowTheMoney shape (``id``, ``caption``, ``schema``, ``properties``,
    ``datasets``, ``referents``) and adds Aleph-specific fields on top.
    """

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )

    # Populated by the ES indexer — the schema ancestor chain.
    # Defaults to empty so entities from older indexes or minimal
    # test fixtures still validate.
    schemata: list[str] = []

    # Every indexed entity carries its collection_id (int PK) from the
    # ES document. Used by authz checks and xref cluster resolution.
    collection_id: int

    # Resolved nested resources, populated by the response builder.
    collection: CollectionSchema | None = None
    role_id: str | None = None
    role: RoleSchema | None = None

    # FTM property aggregates surfaced as flat fields for facet display.
    countries: list[str] = []
    languages: list[str] = []
    dates: list[str] = []

    # Search-time fields.
    score: float | None = None
    highlight: list[str] = []

    # Per-user state.
    bookmarked: bool | None = None

    # Document detail fields (only populated for Document-derived schemata
    # in detail views).
    safeHtml: list[str] | None = None
    processing_status: SDict | None = None

    # Transliterated property values — computed by the response builder,
    # not part of the cached entity. Defaults to empty so the resolver
    # can cache the raw ES payload without needing to compute it.
    latinized: SDict = {}

    # Request-time computed fields populated by the response builder.
    writeable: bool = False
    shallow: bool = True
    links: SDict = {}

    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    @property
    def cache_key(self) -> str:
        return self.id

    @field_validator("role_id", mode="before")
    @classmethod
    def clean_role_id(cls, v: Any) -> str | None:
        if isinstance(v, int):
            return str(v)


class EntityTagSchema(APIBaseModel):
    """One row of an entity tag aggregation
    (``GET /api/2/entities/<id>/tags``)."""

    id: str
    field: str
    value: str
    count: int = 0


class EntityExpandSchema(APIBaseModel):
    """One bucket of an entity expansion
    (``GET /api/2/entities/<id>/expand``)."""

    property: str
    count: int = 0
    entities: list[EntitySchema] = []


class SimilarSchema(APIBaseModel):
    """One result of a similar-entity query
    (``GET /api/2/entities/<id>/similar``)."""

    score: float | None = None
    entity: EntitySchema | None = None
    judgement: Judgement | None = None
