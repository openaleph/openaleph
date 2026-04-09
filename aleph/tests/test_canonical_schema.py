"""Pure pydantic smoke tests for the wire-format schemas in
``aleph.model.canonical`` (CanonicalSchema, StatementSchema)."""

import pytest
from pydantic import ValidationError

from aleph.model.canonical import CanonicalSchema, StatementSchema
from aleph.model.collection import CollectionSchema
from aleph.model.common import model_dump
from aleph.model.entity import EntitySchema


def _entity(entity_id: str, name: str) -> EntitySchema:
    return EntitySchema(
        id=entity_id,
        schema="Person",
        properties={"name": [name]},
        schemata=["Person", "LegalEntity", "Thing"],
        collection_id=1,
        latinized={},
    )


def test_canonical_schema_minimal():
    c = CanonicalSchema(
        id="NK-abc",
        merged=_entity("NK-abc", "Alice Smith"),
    )
    assert c.cache_key == "NK-abc"
    dumped = model_dump(c)
    assert dumped["id"] == "NK-abc"
    assert dumped["merged"]["properties"]["name"] == ["Alice Smith"]


def test_canonical_schema_required_fields_raise_on_missing():
    with pytest.raises(ValidationError):
        CanonicalSchema(id="NK-abc")  # missing merged


def test_canonical_schema_with_constituents():
    c = CanonicalSchema(
        id="NK-abc",
        merged=_entity("NK-abc", "Alice Smith"),
        entities=[_entity("a", "Alice"), _entity("b", "Alicia")],
        collection_ids=["leaks", "opensanctions"],
        writeable=True,
    )
    dumped = model_dump(c)
    assert dumped["merged"]["properties"]["name"] == ["Alice Smith"]
    assert len(dumped["entities"]) == 2
    assert dumped["collection_ids"] == ["leaks", "opensanctions"]


def test_statement_schema_value_property():
    s = StatementSchema(
        id="stmt-1",
        entity_id="a",
        canonical_id="NK-abc",
        schema="Person",
        prop="name",
        prop_type="name",
        value="Alice",
        dataset="leaks",
    )
    dumped = model_dump(s)
    assert dumped["schema"] == "Person"  # JSON alias
    assert dumped["prop"] == "name"
    assert dumped["value"] == "Alice"
    assert dumped["dataset"] == "leaks"


def test_statement_schema_required_fields_raise_on_missing():
    with pytest.raises(ValidationError):
        StatementSchema(entity_id="a")
    with pytest.raises(ValidationError):
        StatementSchema(entity_id="a", schema="Person", prop="name")
        # missing value, dataset, id
    with pytest.raises(ValidationError):
        # FTM Statement always derives an id; the schema requires one too.
        StatementSchema(
            entity_id="a",
            schema="Person",
            prop="name",
            value="Alice",
            dataset="leaks",
        )  # missing id


def test_statement_schema_entity_value():
    # When `prop_type == "entity"` the response builder swaps the value
    # for a nested EntitySchema.
    s = StatementSchema(
        id="stmt-2",
        entity_id="a",
        canonical_id="NK-abc",
        schema="Person",
        prop="ownership",
        prop_type="entity",
        value=_entity("b", "Bob"),
        dataset=CollectionSchema(name="leaks", title="Leaks"),
    )
    dumped = model_dump(s)
    assert dumped["value"]["id"] == "b"
    assert dumped["dataset"]["name"] == "leaks"


def test_statement_schema_cache_key_uses_id():
    # FTM Statement always has an id, so the cache_key is always the id.
    s = StatementSchema(
        id="stmt-1",
        entity_id="a",
        canonical_id="NK-abc",
        schema="Person",
        prop="name",
        prop_type="name",
        value="Alice",
        dataset="leaks",
    )
    assert s.cache_key == "stmt-1"
