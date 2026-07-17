"""Pure pydantic smoke tests for the wire-format schemas in
``aleph.model.xref`` (XrefSchema, CanonicalSchema, StatementSchema)."""

import pytest
from nomenklatura.judgement import Judgement
from pydantic import ValidationError

from aleph.model.collection import CollectionSchema
from aleph.model.common import model_dump
from aleph.model.entity import EntitySchema
from aleph.model.xref import CanonicalSchema, StatementSchema, XrefSchema


def _entity(entity_id: str, name: str) -> EntitySchema:
    return EntitySchema(
        id=entity_id,
        schema="Person",
        properties={"name": [name]},
        schemata=["Person", "LegalEntity", "Thing"],
        latinized={},
    )


def _xref(**overrides) -> XrefSchema:
    base = {
        "score": 0.95,
        "entity": _entity("a", "Alice"),
        "match": _entity("b", "Bob"),
    }
    base.update(overrides)
    return XrefSchema(**base)


def test_xref_schema_minimal():
    x = _xref(method="name_match")
    dumped = model_dump(x)
    assert dumped["score"] == 0.95
    assert dumped["entity"]["id"] == "a"
    assert dumped["match"]["id"] == "b"


def test_xref_schema_required_fields_raise_on_missing():
    with pytest.raises(ValidationError):
        XrefSchema(score=0.95)  # missing entity, match
    with pytest.raises(ValidationError):
        XrefSchema(
            entity=_entity("a", "Alice"),
            match=_entity("b", "Bob"),
        )  # missing score


def test_xref_schema_cache_key_is_pair_deterministic_and_non_empty():
    # The cache key sorts the (entity, match) pair so it's stable
    # regardless of which side is "left".
    x1 = _xref()
    x2 = _xref(entity=_entity("b", "Bob"), match=_entity("a", "Alice"))
    assert x1.cache_key == x2.cache_key == "a/b"
    # Neither side can be None now, so the key never degrades to "/".
    assert "/" in x1.cache_key
    assert not x1.cache_key.startswith("/")
    assert not x1.cache_key.endswith("/")


def test_xref_schema_with_collections_and_judgement():
    x = _xref(
        collections=[
            CollectionSchema(name="leaks", title="Leaks"),
            CollectionSchema(name="opensanctions", title="OpenSanctions"),
        ],
        judgement=Judgement.POSITIVE,
        writeable=True,
    )
    dumped = model_dump(x)
    assert len(dumped["collections"]) == 2
    assert dumped["collections"][0]["name"] == "leaks"
    assert dumped["judgement"] == "positive"
    assert dumped["writeable"] is True


def test_canonical_schema_minimal():
    c = CanonicalSchema(
        id="NK-abc",
        merged={"id": "NK-abc", "schema": "Person", "name": "Alice Smith"},
    )
    assert c.cache_key == "NK-abc"
    dumped = model_dump(c)
    assert dumped["id"] == "NK-abc"
    assert dumped["merged"]["name"] == "Alice Smith"


def test_canonical_schema_required_fields_raise_on_missing():
    with pytest.raises(ValidationError):
        CanonicalSchema(id="NK-abc")  # missing merged


def test_canonical_schema_with_constituents():
    c = CanonicalSchema(
        id="NK-abc",
        merged={"id": "NK-abc", "schema": "Person", "name": "Alice Smith"},
        entities=[_entity("a", "Alice"), _entity("b", "Alicia")],
        collection_ids=["leaks", "opensanctions"],
        writeable=True,
    )
    dumped = model_dump(c)
    assert dumped["merged"]["name"] == "Alice Smith"
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
        schema="Person",
        prop="name",
        value="Alice",
        dataset="leaks",
    )
    assert s.cache_key == "stmt-1"
