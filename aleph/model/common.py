import logging
import secrets
import uuid
from datetime import date, datetime

from anystore.types import SDict
from anystore.util import clean_dict
from anystore.util import model_dump as _anystore_model_dump
from flask_babel import lazy_gettext
from pydantic import BaseModel, ConfigDict
from sqlalchemy import false

from aleph.core import db

log = logging.getLogger(__name__)
ENTITY_ID_LEN = 128


def make_textid():
    return uuid.uuid4().hex


def make_token():
    return secrets.token_urlsafe()


def iso_text(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj


def query_like(column, text):
    if text is None or len(text) < 3:
        return false()
    text = text.replace("%", " ").replace("_", " ")
    text = "%%%s%%" % text
    return column.ilike(text)


class IdModel(object):
    id = db.Column(db.Integer(), primary_key=True)


class DatedModel(object):
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    @classmethod
    def all(cls, deleted=False):
        return db.session.query(cls)

    @classmethod
    def all_ids(cls, deleted=False):
        q = db.session.query(cls.id)
        q = q.order_by(cls.id.asc())
        return q

    @classmethod
    def all_by_ids(cls, ids, deleted=False):
        # Convert all ids to int for compatibility with psycopg3
        try:
            ids = [int(id) for id in ids if id is not None]
        except (ValueError, TypeError):
            ids = []
        return cls.all(deleted=deleted).filter(cls.id.in_(ids))

    @classmethod
    def by_id(cls, id, deleted=False):
        if id is None:
            return
        # Explicitly convert to int for compatibility with psycopg3
        try:
            id = int(id)
        except (ValueError, TypeError):
            return None
        return cls.all(deleted=deleted).filter_by(id=id).first()

    def delete(self):
        # hard delete
        db.session.delete(self)

    def to_dict_dates(self):
        return {"created_at": self.created_at, "updated_at": self.updated_at}


class SoftDeleteModel(DatedModel):
    deleted_at = db.Column(db.DateTime, default=None, nullable=True)

    def delete(self, deleted_at=None):
        self.deleted_at = deleted_at or datetime.utcnow()
        db.session.add(self)

    def to_dict_dates(self):
        data = super(SoftDeleteModel, self).to_dict_dates()
        if self.deleted_at:
            data["deleted_at"] = self.deleted_at
        return data

    @classmethod
    def all(cls, deleted=False):
        q = super(SoftDeleteModel, cls).all()
        if not deleted:
            q = q.filter(cls.deleted_at == None)  # noqa: E711
        return q

    @classmethod
    def all_ids(cls, deleted=False):
        q = super(SoftDeleteModel, cls).all_ids()
        if not deleted:
            q = q.filter(cls.deleted_at == None)  # noqa: E711
        return q

    @classmethod
    def cleanup_deleted(cls):
        pq = db.session.query(cls)
        pq = pq.filter(cls.deleted_at != None)  # noqa: E711
        log.info("[%s]: %d deleted objects", cls.__name__, pq.count())
        pq.delete(synchronize_session=False)


class Status(object):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    DEFAULT = PENDING

    LABEL = {
        PENDING: lazy_gettext("pending"),
        SUCCESS: lazy_gettext("successful"),
        FAILED: lazy_gettext("failed"),
    }


# === Pydantic foundation ===
#
# These classes are the base for every API resource model. The pydantic
# layer sits above SQLAlchemy and below the (future) FastAPI layer:
#
# - SQLAlchemy classes (Role, Collection, Entity, ...) handle persistence
# - Pydantic schemas (RoleSchema, CollectionSchema, ...) handle the wire
#   format and the resolver cache
#
# The pydantic schemas use ``from_attributes=True`` so they can be
# instantiated directly from a SQLAlchemy row instance:
#
#     role = Role.by_id(1)
#     schema = RoleSchema.model_validate(role)
#
# No ``to_dict()`` method is needed on the SQLA side. Computed properties
# (e.g. ``Role.has_password``) are read transparently as if they were
# attributes.


class APIBaseModel(BaseModel):
    """Base for every API model.

    - ``from_attributes=True`` lets us validate directly off SQLAlchemy
      instances: ``RoleSchema.model_validate(role)`` reads attributes
      from the SQLA object as if it were a dict.
    - ``populate_by_name=True`` allows aliases for fields whose JSON name
      differs from the python attribute (e.g. ``schema_`` ↔ ``schema``).

    Subclasses inherit ``cache_key`` as a regular ``@property`` that
    defaults to the model's ``foreign_id`` (if it has one) or its
    ``id``. Override in subclasses for aggregates whose cache key needs
    more parts — e.g. ``CollectionStatistics`` returns
    ``f"{self.foreign_id}/stats"``. Because it is a plain property and
    not a ``computed_field``, ``cache_key`` is invisible to
    ``model_dump()`` and never leaks into API responses.
    """

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )

    @property
    def cache_key(self) -> str:
        """Stable identifier used by the resolver to compute store keys.

        Prefers ``foreign_id`` (durable across the eventual int → UUID7
        migration) over ``id`` (the SQLAlchemy integer PK that will go
        away). The resolver prefixes this with the class name to build
        a path-style key like ``Collection/foo-dataset`` or ``Role/42``.

        Raises :class:`ValueError` if neither ``foreign_id`` nor ``id``
        carries a usable value — a model with no cache key is a bug we
        want to surface loudly rather than store under an empty key.
        Subclasses that compose their own keys (e.g. aggregates like
        ``CollectionStatistics``) should override this and raise the
        same way on missing inputs.
        """
        fid = getattr(self, "foreign_id", None)
        if fid:
            return str(fid)
        oid = getattr(self, "id", None)
        if oid:
            return str(oid)
        raise ValueError(
            f"{type(self).__name__} has neither foreign_id nor id; "
            "cannot derive a cache_key"
        )


class DatedSchema(APIBaseModel):
    """Common base for any resource backed by a ``DatedModel`` /
    ``SoftDeleteModel`` SQLA row. Inherits ``cache_key`` from
    ``APIBaseModel``."""

    id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None


def model_dump(model: BaseModel | None) -> SDict | None:
    """Dump a pydantic model to a dict, dropping ``None``, empty strings
    and empty containers recursively.

    Thin ``None``-tolerant wrapper around
    ``anystore.util.model_dump(obj, clean=True)``. Replaces
    ``aleph.views.util.clean_object()`` and is the canonical way to
    serialize an API response. The frontend uses defensive accessors
    (``entity?.collection?.foreign_id``), so dropping empty values is
    safe. ``cache_key`` is a regular ``@property`` on
    :class:`APIBaseModel` so it never appears in the dump output.
    """
    if model is None:
        return None
    return _anystore_model_dump(model, clean=True)


__all__ = [
    "APIBaseModel",
    "DatedSchema",
    "ENTITY_ID_LEN",
    "DatedModel",
    "IdModel",
    "SoftDeleteModel",
    "Status",
    "SDict",
    "clean_dict",
    "iso_text",
    "make_textid",
    "make_token",
    "model_dump",
    "query_like",
]
