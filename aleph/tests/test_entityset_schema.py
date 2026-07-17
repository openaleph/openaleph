"""Pure pydantic smoke tests for the schemas in ``aleph.model.entityset``."""

import pytest
from pydantic import ValidationError

from aleph.model.collection import CollectionSchema
from aleph.model.common import model_dump
from aleph.model.entityset import (
    DiagramEdge,
    DiagramLayout,
    DiagramVertex,
    EntitySetItemSchema,
    EntitySetSchema,
)
from aleph.model.role import RoleSchema


def _entityset(**overrides) -> EntitySetSchema:
    base = {
        "id": "abc",
        "type": "list",
        "label": "My list",
        "role_id": "42",
        "collection_id": "7",
    }
    base.update(overrides)
    return EntitySetSchema(**base)


def _entityset_item(**overrides) -> EntitySetItemSchema:
    base = {
        "id": "abc$xyz",
        "entityset_id": "abc",
        "entity_id": "xyz",
        "collection_id": "7",
        "entityset_collection_id": "7",
    }
    base.update(overrides)
    return EntitySetItemSchema(**base)


def _role() -> RoleSchema:
    return RoleSchema(
        id="42",
        type="user",
        name="Alice",
        foreign_id="alice@example.org",
        label="Alice",
    )


def _collection() -> CollectionSchema:
    return CollectionSchema(id="1", name="opensanctions", title="OpenSanctions")


def test_entityset_schema_minimal_list():
    es = _entityset()
    assert es.cache_key == "abc"
    dumped = model_dump(es)
    assert dumped["id"] == "abc"
    assert dumped["type"] == "list"
    assert dumped["label"] == "My list"
    assert dumped["role_id"] == "42"
    assert dumped["collection_id"] == "7"
    assert "cache_key" not in dumped
    assert "layout" not in dumped


def test_entityset_schema_required_fields_raise_on_missing():
    with pytest.raises(ValidationError):
        EntitySetSchema(id="abc", type="list")  # missing label, role_id, collection_id


def test_entityset_schema_diagram_with_layout():
    es = _entityset(
        type="diagram",
        label="Network",
        layout=DiagramLayout(
            vertices=[DiagramVertex(id="v1", label="Alice", entityId="alice")],
            edges=[DiagramEdge(id="e1", sourceId="v1", targetId="v2")],
        ),
    )
    dumped = model_dump(es)
    assert dumped["layout"]["vertices"][0]["id"] == "v1"
    assert dumped["layout"]["vertices"][0]["label"] == "Alice"
    assert dumped["layout"]["edges"][0]["sourceId"] == "v1"


def test_entityset_schema_with_nested_collection_and_role():
    es = _entityset(
        type="timeline",
        label="Timeline",
        collection=_collection(),
        role=_role(),
    )
    dumped = model_dump(es)
    assert dumped["collection"]["name"] == "opensanctions"
    assert dumped["role"]["name"] == "Alice"


def test_entityset_schema_rejects_profile_type():
    # Profile was removed when xref moved to nomenklatura.
    with pytest.raises(ValidationError):
        _entityset(type="profile")


def test_entityset_item_cache_key_is_path_style():
    item = _entityset_item()
    assert item.cache_key == "abc/xyz"


def test_entityset_item_required_fields_raise_on_missing():
    with pytest.raises(ValidationError):
        EntitySetItemSchema(id="abc$xyz", entityset_id="abc", entity_id="xyz")
        # missing collection_id, entityset_collection_id


def test_entityset_int_id_coercion():
    es = _entityset(role_id=7, collection_id=42)
    assert es.role_id == "7"
    assert es.collection_id == "42"


def test_entityset_item_int_id_coercion():
    item = _entityset_item(collection_id=7, entityset_collection_id=42)
    assert item.collection_id == "7"
    assert item.entityset_collection_id == "42"


def test_entityset_item_dump_omits_dropped_legacy_fields():
    item = _entityset_item()
    dumped = model_dump(item)
    # judgement and compared_to_entity_id were profile-leakage and are gone.
    assert "judgement" not in dumped
    assert "compared_to_entity_id" not in dumped
    assert dumped["entityset_id"] == "abc"
    assert dumped["entity_id"] == "xyz"
    assert dumped["collection_id"] == "7"
    assert dumped["entityset_collection_id"] == "7"


def test_entityset_item_with_nested_entity_slot():
    # The `entity` slot is opaque (SDict) at this layer; the assembler
    # later replaces it with a typed EntitySchema.
    item = _entityset_item(
        entity={"id": "xyz", "schema": "Person", "name": "Alice"},
    )
    dumped = model_dump(item)
    assert dumped["entity"]["id"] == "xyz"
    assert dumped["entity"]["schema"] == "Person"
