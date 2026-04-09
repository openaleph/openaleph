"""Pure pydantic smoke tests for the schemas in ``aleph.model.tag``
and the request body in ``aleph.api.requests.tag``."""

import pytest
from pydantic import ValidationError

from aleph.api.requests.tag import TagCreate
from aleph.model.common import model_dump
from aleph.model.entity import EntitySchema
from aleph.model.role import RoleSchema
from aleph.model.tag import TagSchema


def _tag(**overrides) -> TagSchema:
    base = {
        "id": "9",
        "tag": "suspicious",
        "entity_id": "abc-123",
        "collection_id": "7",
        "role_id": "42",
    }
    base.update(overrides)
    return TagSchema(**base)


def _entity() -> EntitySchema:
    return EntitySchema(
        id="abc-123",
        schema="Person",
        properties={"name": ["Alice"]},
        schemata=["Person", "LegalEntity", "Thing"],
        collection_id=1,
        latinized={},
    )


def _role() -> RoleSchema:
    return RoleSchema(
        id="42",
        type="user",
        name="Curator",
        foreign_id="curator@example.org",
        label="Curator",
    )


def test_tag_schema_minimal():
    t = _tag()
    assert t.cache_key == "9"
    dumped = model_dump(t)
    assert dumped["tag"] == "suspicious"
    assert dumped["entity_id"] == "abc-123"
    assert dumped["collection_id"] == "7"
    assert dumped["role_id"] == "42"


def test_tag_schema_required_fields_raise_on_missing():
    with pytest.raises(ValidationError):
        TagSchema(id="9", tag="suspicious")  # missing entity_id, collection_id, role_id


def test_tag_schema_with_nested_entity_and_role():
    t = _tag(entity=_entity(), role=_role())
    dumped = model_dump(t)
    assert dumped["entity"]["id"] == "abc-123"
    assert dumped["entity"]["caption"] == "Alice"
    assert dumped["role"]["name"] == "Curator"


def test_tag_schema_aggregate_count():
    t = _tag(count=42)
    dumped = model_dump(t)
    assert dumped["count"] == 42


def test_tag_create_requires_entity_id_and_tag():
    TagCreate.model_validate({"entity_id": "abc", "tag": "x"})
    with pytest.raises(ValidationError):
        TagCreate.model_validate({"entity_id": "abc"})
    with pytest.raises(ValidationError):
        TagCreate.model_validate({"tag": "x"})


def test_tag_create_max_length():
    TagCreate.model_validate({"entity_id": "abc", "tag": "x" * 128})
    with pytest.raises(ValidationError):
        TagCreate.model_validate({"entity_id": "abc", "tag": "x" * 129})
    with pytest.raises(ValidationError):
        TagCreate.model_validate({"entity_id": "abc", "tag": ""})  # min_length=1
