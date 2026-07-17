from datetime import datetime
from typing import Annotated

from normality import stringify

from aleph.core import db
from aleph.model.common import ENTITY_ID_LEN, APIBaseModel, IdModel, ResolveFrom
from aleph.model.entity import EntitySchema


class Bookmark(db.Model, IdModel):
    """A bookmark of an entity created by a user."""

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    role_id = db.Column(db.Integer, db.ForeignKey("role.id"))
    collection_id = db.Column(db.Integer, db.ForeignKey("collection.id"))
    entity_id = db.Column(db.String(ENTITY_ID_LEN))

    def to_dict(self):
        return {
            "id": stringify(self.id),
            "created_at": self.created_at,
            "entity_id": self.entity_id,
            "collection_id": self.collection_id,
        }

    @classmethod
    def delete_by_entity(cls, entity_id):
        query = db.session.query(Bookmark)
        query = query.filter(Bookmark.entity_id == entity_id)
        query.delete(synchronize_session=False)


# === Pydantic schemas ===


class BookmarkSchema(APIBaseModel):
    """Canonical wire format for a :class:`Bookmark`.

    The legacy response replaces the bookmark row id with the bookmarked
    entity id. ``BookmarkSchema`` carries the bookmark row ``id`` and
    the underlying ``entity_id`` separately so the resolver can cache
    by row id while the response writer is free to project either.

    All identifier fields and ``created_at`` are application invariants
    – every bookmark is created with a row id, an entity reference, a
    collection reference, an owning role and a timestamp. The DB
    columns are technically nullable but the application never
    persists a bookmark without them.
    """

    id: str
    entity_id: str
    entity: Annotated[EntitySchema | None, ResolveFrom("entity_id", EntitySchema)] = (
        None
    )
    role_id: str
    collection_id: str
    created_at: datetime

    @property
    def cache_key(self) -> str:
        return self.id
