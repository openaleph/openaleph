from datetime import datetime

from normality import stringify
from sqlalchemy import event

from aleph.core import db
from aleph.logic.resolver import cache
from aleph.model.common import DatedModel, DatedSchema, SDict
from aleph.model.role import Role


class Alert(db.Model, DatedModel):
    """A subscription to notifications on a given query."""

    __tablename__ = "alert"

    id = db.Column(db.Integer, primary_key=True)
    query = db.Column(db.Unicode, nullable=True)
    notified_at = db.Column(db.DateTime, nullable=True)

    role_id = db.Column(db.Integer, db.ForeignKey("role.id"), index=True)
    role = db.relationship(Role, backref=db.backref("alerts", lazy="dynamic"))

    def update(self):
        self.notified_at = datetime.utcnow()
        self.updated_at = self.notified_at
        db.session.add(self)
        db.session.flush()

    def to_dict(self):
        data = self.to_dict_dates()
        data.update(
            {
                "id": stringify(self.id),
                "query": self.query,
                "role_id": stringify(self.role_id),
                "notified_at": self.notified_at,
            }
        )
        return data

    @classmethod
    def by_id(cls, id, role_id=None):
        q = cls.all().filter_by(id=id)
        if role_id is not None:
            q = q.filter(cls.role_id == role_id)
        return q.first()

    @classmethod
    def by_role_id(cls, role_id):
        q = cls.all()
        q = q.filter(cls.role_id == role_id)
        q = q.order_by(cls.created_at.desc())
        q = q.order_by(cls.id.desc())
        return q

    @classmethod
    def create(cls, data, role_id):
        alert = cls()
        alert.role_id = role_id
        alert.query = stringify(data.get("query"))
        alert.update()
        return alert

    def __repr__(self):
        return "<Alert(%r, %r)>" % (self.id, self.query)


# === Pydantic schemas ===


class AlertSchema(DatedSchema):
    """Canonical wire format for an :class:`Alert`.

    ``query`` and ``role_id`` are application invariants – every alert
    is created with both. The DB columns are technically nullable but
    the application never persists an alert without them.
    """

    query: str
    role_id: str
    notified_at: datetime | None = None

    writeable: bool = False
    links: SDict = {}


# === Resolver invalidation via SQLA events ===


def _invalidate_alert(mapper, connection, target: Alert):
    cache.invalidate(AlertSchema, str(target.id))


event.listen(Alert, "after_insert", _invalidate_alert)
event.listen(Alert, "after_update", _invalidate_alert)
event.listen(Alert, "after_delete", _invalidate_alert)
