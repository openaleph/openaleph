from normality import stringify

from aleph.core import db
from aleph.model.common import ENTITY_ID_LEN, DatedModel, IdModel


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
