import logging
from datetime import datetime, timedelta

from normality import stringify
from pydantic import field_validator
from servicelayer.cache import make_key
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB

from aleph.core import db
from aleph.logic.resolver import cache
from aleph.model.collection import Collection
from aleph.model.common import (
    DatedModel,
    DatedSchema,
    IdModel,
    SDict,
    Status,
)
from aleph.model.role import Role

log = logging.getLogger(__name__)


class Export(db.Model, IdModel, DatedModel):
    """A data export run in the background. The data is stored in a cloud
    storage bucket and the user is given a link to download the data. The link
    expires after a fixed duration and the exported data is deleted."""

    DEFAULT_EXPIRATION = timedelta(days=30)  # After 30 days

    label = db.Column(db.Unicode)
    operation = db.Column(db.Unicode)
    creator_id = db.Column(db.Integer, db.ForeignKey("role.id"))
    creator = db.relationship(Role, backref=db.backref("exports", lazy="dynamic"))
    collection_id = db.Column(
        db.Integer, db.ForeignKey("collection.id"), index=True, nullable=True
    )
    collection = db.relationship(
        Collection, backref=db.backref("exports", lazy="dynamic")
    )

    expires_at = db.Column(db.DateTime, default=None, nullable=True)
    deleted = db.Column(db.Boolean, default=False)
    status = db.Column("export_status", db.Unicode, default=Status.DEFAULT)

    content_hash = db.Column(db.Unicode(65), index=True, nullable=True)
    file_size = db.Column(db.BigInteger, nullable=True)  # In bytes
    file_name = db.Column(db.Unicode, nullable=True)
    mime_type = db.Column(db.Unicode)
    meta = db.Column(JSONB, default={})

    def to_dict(self):
        data = self.to_dict_dates()
        data.update(
            {
                "id": stringify(self.id),
                "label": self.label,
                "operation": self.operation,
                "creator_id": stringify(self.creator_id),
                "collection_id": self.collection_id,
                "expires_at": self.expires_at,
                "deleted": self.deleted,
                "status": Status.LABEL.get(self.status),
                "content_hash": self.content_hash,
                "file_size": self.file_size,
                "file_name": self.file_name,
                "mime_type": self.mime_type,
                "meta": self.meta,
            }
        )
        return data

    @classmethod
    def create(
        cls, operation, role_id, label, collection=None, mime_type=None, meta=None
    ):
        export = cls()
        export.creator_id = role_id
        export.operation = operation
        export.label = label
        if collection is not None:
            export.collection_id = collection.id
        export.mime_type = mime_type
        export.updated_at = datetime.utcnow()
        export.expires_at = datetime.utcnow() + cls.DEFAULT_EXPIRATION
        export.meta = meta or {}
        db.session.add(export)
        return export

    @property
    def namespace(self):
        return make_key("role", self.creator_id)

    def set_status(self, status):
        self.status = status
        self.updated_at = datetime.utcnow()
        db.session.add(self)

    def should_delete_publication(self):
        """Check whether the published export should be deleted from the archive

        Since we store exports by contenthash, there may be other non-expired exports
        that point to the same file in the archive"""
        q = (
            Export.all()
            .filter(Export.content_hash == self.content_hash)
            .filter(Export.deleted.isnot(True))
            .filter(Export.id != self.id)
        )
        return q.first() is None

    @classmethod
    def get_expired(cls, deleted=False):
        q = cls.all()
        q = q.filter(cls.expires_at <= datetime.utcnow())
        if not deleted:
            q = q.filter(cls.deleted == deleted)
        return q

    @classmethod
    def get_pending(cls):
        q = cls.all()
        q = q.filter(cls.status == Status.PENDING)
        q = q.filter(cls.deleted == False)  # noqa: E712
        return q

    @classmethod
    def by_id(cls, id, role_id=None, deleted=False):
        q = cls.all().filter_by(id=id)
        if role_id is not None:
            q = q.filter(cls.creator_id == role_id)
        if not deleted:
            q = q.filter(cls.deleted == False)  # noqa: E712
        return q.first()

    @classmethod
    def by_role_id(cls, role_id, deleted=False):
        q = cls.all()
        q = q.filter(cls.creator_id == role_id)
        if not deleted:
            q = q.filter(cls.deleted == False)  # noqa: E712
            q = q.filter(cls.expires_at > datetime.utcnow())
        q = q.order_by(cls.created_at.desc())
        return q

    @classmethod
    def by_content_hash(cls, content_hash, deleted=False):
        q = cls.all()
        q = q.filter(cls.content_hash == content_hash)
        if not deleted:
            q = q.filter(cls.deleted == False)  # noqa: E712
        return q

    def __repr__(self):
        return "<Export(%r, %r, %r)>" % (self.id, self.creator_id, self.label)


# === Pydantic schemas ===


class ExportSchema(DatedSchema):
    """Canonical wire format for an :class:`Export`.

    Every export row has a ``label``, ``operation``, ``creator_id``,
    ``status``, ``mime_type``, ``expires_at`` (set to ``now +
    DEFAULT_EXPIRATION`` on create) and ``meta`` (defaulted to ``{}``).
    The ``deleted`` flag also always has a value (defaulting to
    ``False``). The DB columns are technically nullable but
    ``Export.create`` populates all of them.

    The optional fields (``collection_id``, ``content_hash``,
    ``file_name``, ``file_size``) are populated by the export worker
    only after the run completes successfully — exports that are
    pending or scoped to no collection legitimately omit them.
    """

    label: str
    operation: str
    creator_id: str
    expires_at: datetime
    deleted: bool
    status: str
    meta: SDict = {}

    collection_id: str | None = None
    content_hash: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    mime_type: str | None = None

    links: SDict = {}

    @field_validator("status", mode="before")
    @classmethod
    def _localize_status(cls, v: str) -> str:
        """Map raw DB enum to localized label string."""
        return str(Status.LABEL.get(v, v))


# === Resolver invalidation via SQLA events ===


def _invalidate_export(mapper, connection, target: Export):
    cache.invalidate(ExportSchema, str(target.id))


event.listen(Export, "after_insert", _invalidate_export)
event.listen(Export, "after_update", _invalidate_export)
event.listen(Export, "after_delete", _invalidate_export)
