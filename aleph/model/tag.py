from typing import Annotated

from normality import stringify

from aleph.core import db
from aleph.model.common import (
    ENTITY_ID_LEN,
    DatedModel,
    DatedSchema,
    IdModel,
    ResolveFrom,
    SDict,
)
from aleph.model.entity import EntitySchema
from aleph.model.role import RoleSchema


class Tag(db.Model, IdModel, DatedModel):
    """A tag for an entity created by a user."""

    role_id = db.Column(db.Integer, db.ForeignKey("role.id"))
    collection_id = db.Column(db.Integer, db.ForeignKey("collection.id"))
    entity_id = db.Column(db.String(ENTITY_ID_LEN), index=True)
    tag = db.Column(db.String(ENTITY_ID_LEN), index=True)

    def to_dict(self):
        return {
            "id": stringify(self.id),
            "tag": self.tag,
            "role_id": stringify(self.role_id),
            "created_at": self.created_at,
            "entity_id": self.entity_id,
            "collection_id": self.collection_id,
        }

    @classmethod
    def delete_by_entity(cls, entity_id):
        query = db.session.query(Tag)
        query = query.filter(Tag.entity_id == entity_id)
        query.delete(synchronize_session=False)


# === Pydantic schemas ===


class TagSchema(DatedSchema):
    """Canonical wire format for a :class:`Tag`.

    Every tag row has a ``tag`` value, an ``entity_id``, a
    ``collection_id`` (the entity's parent) and a ``role_id`` (who
    created it). The DB columns are technically nullable but every
    write site populates them.
    """

    tag: str
    entity_id: str
    collection_id: str
    role_id: str

    # Resolved nested resources, populated by the assembler.
    entity: Annotated[EntitySchema | None, ResolveFrom("entity_id", EntitySchema)] = (
        None
    )
    role: Annotated[RoleSchema | None, ResolveFrom("role_id", RoleSchema)] = None

    # Set on aggregated tag responses (count of times this tag appears).
    count: int | None = None

    writeable: bool = False
    links: SDict = {}
