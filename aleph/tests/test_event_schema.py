"""Pure pydantic smoke tests for ``aleph.model.event.EventSchema``."""

from aleph.model import CollectionSchema, EntitySchema, Events, EventSchema
from aleph.model.common import model_dump


def test_event_schema_serializes_lazy_gettext():
    """lazy_gettext proxies on title/template must serialize to plain strings."""
    e = Events.INGEST_DOCUMENT
    dumped = model_dump(e)
    assert isinstance(dumped["title"], str)
    assert isinstance(dumped["template"], str)
    assert "{{actor}}" in dumped["template"]


def test_event_schema_params_strips_schema_suffix():
    """Wire-format params should use lowered class names without 'schema' suffix."""
    e = Events.INGEST_DOCUMENT
    dumped = model_dump(e)
    assert dumped["params"] == {"document": "entity", "collection": "collection"}


def test_event_schema_param_types_excluded_from_dump():
    """param_types holds class objects – must not appear in serialized output."""
    e = Events.INGEST_DOCUMENT
    dumped = model_dump(e)
    assert "param_types" not in dumped


def test_event_schema_param_types_are_pydantic_classes():
    """param_types should map to pydantic schema classes for resolver dispatch."""
    e = Events.INGEST_DOCUMENT
    assert e.param_types["document"] is EntitySchema
    assert e.param_types["collection"] is CollectionSchema


def test_event_schema_constructed_manually():
    """EventSchema can be constructed outside the Events registry."""
    e = EventSchema(
        name="test_event",
        title="Test",
        template="{{actor}} did {{thing}}",
        param_types={"thing": EntitySchema},
    )
    dumped = model_dump(e)
    assert dumped["name"] == "test_event"
    assert dumped["params"] == {"thing": "entity"}
    assert "param_types" not in dumped


def test_events_registry_lists_all():
    """Events.names() should return all registered event names."""
    names = Events.names()
    assert "CREATE_COLLECTION" in names
    assert "INGEST_DOCUMENT" in names
    assert "MATCH_ALERT" in names
    assert len(names) >= 9


def test_events_get_returns_event_schema():
    e = Events.get("CREATE_COLLECTION")
    assert isinstance(e, EventSchema)
    assert e.name == "CREATE_COLLECTION"
