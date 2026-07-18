"""Pure pydantic smoke tests for the schemas in ``aleph.model.event``."""

import pytest
from pydantic import ValidationError

from aleph.model import CollectionSchema, EntitySchema
from aleph.model.common import model_dump
from aleph.model.event import EventSchema, NotificationSchema


def _event(**overrides) -> EventSchema:
    base = {
        "name": "ingest_document",
        "title": "Document uploads",
        "template": "{{actor}} added {{document}} to {{collection}}",
        "param_types": {"document": EntitySchema, "collection": CollectionSchema},
    }
    base.update(overrides)
    return EventSchema(**base)


def _notification(**overrides) -> NotificationSchema:
    base = {
        "id": "notif-1",
        "event": _event(),
        "actor_id": "42",
        "params": {},
        "channels": [],
        "created_at": "2024-04-01T12:00:00",
    }
    base.update(overrides)
    return NotificationSchema(**base)


def test_event_schema_minimal():
    e = _event()
    dumped = model_dump(e)
    assert dumped["name"] == "ingest_document"
    assert dumped["params"] == {"document": "entity", "collection": "collection"}


def test_notification_schema_minimal():
    n = _notification()
    assert n.cache_key == "notif-1"
    dumped = model_dump(n)
    assert dumped["id"] == "notif-1"
    assert dumped["actor_id"] == "42"
    assert dumped["created_at"] == "2024-04-01T12:00:00"
    assert dumped["event"]["name"] == "ingest_document"


def test_notification_int_actor_id_coercion():
    n = _notification(actor_id=42)
    assert n.actor_id == "42"


def test_notification_schema_required_fields_raise_on_missing():
    with pytest.raises(ValidationError):
        NotificationSchema(
            id="notif-1", actor_id="42"
        )  # missing event/params/channels/created_at


def test_notification_schema_with_event_and_resolved_params():
    # Once the assembler resolves the param IDs into nested objects,
    # the result lives in `params` as opaque dicts (polymorphic).
    n = _notification(
        event=EventSchema(
            name="grant_collection",
            title="Dataset access change",
            template="{{actor}} gave {{role}} access to {{collection}}",
            params={"collection": "collection", "role": "role"},
        ),
        params={
            "actor": {"id": "42", "type": "user", "name": "Alice"},
            "collection": {"name": "leaks", "title": "Leaks"},
            "role": {"id": "99", "type": "user", "name": "Bob"},
        },
        channels=["role:42", "global"],
    )
    dumped = model_dump(n)
    assert dumped["event"]["name"] == "grant_collection"
    assert dumped["event"]["title"] == "Dataset access change"
    assert dumped["params"]["actor"]["name"] == "Alice"
    assert dumped["params"]["collection"]["name"] == "leaks"
    assert dumped["channels"] == ["role:42", "global"]
    assert dumped["created_at"] == "2024-04-01T12:00:00"
