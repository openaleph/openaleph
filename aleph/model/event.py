from datetime import datetime
from typing import Any, Type

from flask_babel import lazy_gettext
from pydantic import BaseModel, Field, computed_field, field_serializer, field_validator

from aleph.model.alert import AlertSchema
from aleph.model.collection import CollectionSchema
from aleph.model.common import APIBaseModel, SDict
from aleph.model.entity import EntitySchema
from aleph.model.entityset import EntitySetSchema
from aleph.model.export import ExportSchema
from aleph.model.role import RoleSchema


class EventSchema(APIBaseModel):
    """Event definition and wire format.

    Each event carries a ``title``, ``template`` (with ``{{param}}``
    placeholders), and a ``param_types`` map from param name to pydantic
    schema class. The schema class is used by the resolver to fetch the
    object; on the wire, ``params`` is serialized as a map from param
    name to the lower-cased class name (e.g. ``{"document":
    "entityschema", "collection": "collectionschema"}``).

    The ``name`` is set by the ``EventsRegistry`` metaclass at class
    definition time.
    """

    model_config = {"arbitrary_types_allowed": True}

    name: str | None = None
    title: Any  # lazy_gettext proxy
    template: Any  # lazy_gettext proxy
    link_to: str | None = None
    # Runtime type map for resolver dispatch – excluded from serialization
    # because class objects can't be JSON-serialized. The wire-format
    # ``params`` computed field produces the string version.
    param_types: dict[str, Type[BaseModel]] = Field(default={}, exclude=True)

    @field_serializer("title", "template")
    @classmethod
    def _stringify_lazy(cls, v: Any) -> str:
        """Force lazy_gettext proxies to plain strings for JSON serialization."""
        return str(v)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def params(self) -> dict[str, str]:
        """Wire-format params: ``{name: lowered_model_name}``.

        Strips the ``Schema`` suffix so the wire format stays
        backwards-compatible with the old SQLA class names
        (e.g. ``"collection"`` not ``"collectionschema"``).
        """
        return {
            p: c.__name__.lower().removesuffix("schema")
            for p, c in self.param_types.items()
        }


class EventsRegistry(type):
    def __init__(cls, name, bases, dct):
        cls.registry = {}
        for ename, event in dct.items():
            if isinstance(event, EventSchema):
                event.name = ename
                cls.registry[ename] = event
        super(EventsRegistry, cls).__init__(name, bases, dct)


class Events(object, metaclass=EventsRegistry):
    @classmethod
    def get(cls, name):
        return cls.registry.get(name)

    @classmethod
    def names(cls):
        return list(cls.registry.keys())

    # CREATE COLLECTION
    CREATE_COLLECTION = EventSchema(
        title=lazy_gettext("New datasets"),
        template=lazy_gettext("{{actor}} created {{collection}}"),
        param_types={"collection": CollectionSchema},
        link_to="collection",
    )

    # UPLOAD DOCUMENT
    INGEST_DOCUMENT = EventSchema(
        title=lazy_gettext("Document uploads"),
        template=lazy_gettext("{{actor}} added {{document}} to {{collection}}"),
        param_types={"document": EntitySchema, "collection": CollectionSchema},
        link_to="document",
    )

    # EXECUTE MAPPING
    LOAD_MAPPING = EventSchema(
        title=lazy_gettext("Entities generated"),
        template=lazy_gettext(
            "{{actor}} generated entities from {{table}} in {{collection}}"
        ),
        param_types={"table": EntitySchema, "collection": CollectionSchema},
        link_to="table",
    )

    # CREATE DIAGRAM
    CREATE_DIAGRAM = EventSchema(
        title=lazy_gettext("New network diagram"),
        template=lazy_gettext(
            "{{actor}} began diagramming {{diagram}} in {{collection}}"
        ),
        param_types={"diagram": EntitySetSchema, "collection": CollectionSchema},
        link_to="table",
    )

    # CREATE ENTITYSET
    CREATE_ENTITYSET = EventSchema(
        title=lazy_gettext("New diagrams and lists"),
        template=lazy_gettext("{{actor}} created {{entityset}} in {{collection}}"),
        param_types={"entityset": EntitySetSchema, "collection": CollectionSchema},
        link_to="table",
    )

    # ALERT MATCH
    MATCH_ALERT = EventSchema(
        title=lazy_gettext("Alert notifications"),
        template=lazy_gettext("{{entity}} matches your alert for {{alert}}"),
        param_types={"entity": EntitySchema, "alert": AlertSchema, "role": RoleSchema},
        link_to="entity",
    )

    # GRANT COLLECTION
    GRANT_COLLECTION = EventSchema(
        title=lazy_gettext("Dataset access change"),
        template=lazy_gettext("{{actor}} gave {{role}} access to {{collection}}"),
        param_types={"collection": CollectionSchema, "role": RoleSchema},
        link_to="collection",
    )

    # PUBLISH COLLECTION
    PUBLISH_COLLECTION = EventSchema(
        title=lazy_gettext("Dataset published"),
        template=lazy_gettext("{{actor}} published {{collection}}"),
        param_types={"collection": CollectionSchema},
        link_to="collection",
    )

    # EXPORT PUBLISHED
    COMPLETE_EXPORT = EventSchema(
        title=lazy_gettext("Exports completed"),
        template=lazy_gettext("{{export}} is ready for download"),
        param_types={"export": ExportSchema},
        link_to="export",
    )


class NotificationSchema(APIBaseModel):
    """Canonical wire format for a notification entry.

    Notifications live in the Elasticsearch ``notifications`` index;
    there is no SQLAlchemy model. The cache key is the ES document id
    that ``index_notification`` derives from the (actor, event,
    channels, params) tuple.

    Every field on the ES doc is populated by ``index_notification``:
    ``actor_id``, ``event``, ``params``, ``channels`` and
    ``created_at``. The ``event`` is resolved into an :class:`EventSchema`
    by the response builder.

    The ``params`` field is a slot map from param name (defined by the
    matching :class:`EventSchema`) to the *resolved* nested object.
    """

    id: str
    event: EventSchema
    actor_id: str
    params: SDict
    channels: list[str]
    created_at: datetime

    @field_validator("event", mode="before")
    @classmethod
    def _resolve_event(cls, v: Any) -> EventSchema:
        """ES stores the event name as a string; look it up in the registry."""
        if isinstance(v, str):
            resolved = Events.get(v)
            if resolved is None:
                raise ValueError(f"Unknown event: {v!r}")
            return resolved
        return v

    @property
    def cache_key(self) -> str:
        return self.id
