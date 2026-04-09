"""Pure pydantic smoke tests for the wire-format schemas in
``aleph.model.xref`` (XrefSchema, ESEdge)."""

import pytest
from nomenklatura.judgement import Judgement
from pydantic import ValidationError

from aleph.model.collection import CollectionSchema
from aleph.model.common import model_dump
from aleph.model.entity import EntitySchema
from aleph.model.xref import XrefSchema


def _entity(entity_id: str, name: str) -> EntitySchema:
    return EntitySchema(
        id=entity_id,
        schema="Person",
        properties={"name": [name]},
        schemata=["Person", "LegalEntity", "Thing"],
        collection_id=1,
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
