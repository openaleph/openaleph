"""Pure pydantic smoke tests for the schemas in ``aleph.model.entity``
and the request bodies in ``aleph.api.requests.entity``."""

import pytest
from nomenklatura.judgement import Judgement
from pydantic import ValidationError

from aleph.api.requests.entity import EntityCreate, EntityUpdate
from aleph.model.collection import CollectionSchema
from aleph.model.common import model_dump
from aleph.model.entity import (
    EntityExpandSchema,
    EntitySchema,
    EntityTagSchema,
    SimilarSchema,
)


def _entity(**overrides) -> EntitySchema:
    base = {
        "id": "alice-id",
        "schema": "Person",
        "properties": {"name": ["Alice Smith"]},
        "schemata": ["Person", "LegalEntity", "Thing"],
        "collection_id": 1,
        "latinized": {},
    }
    base.update(overrides)
    return EntitySchema(**base)


def test_entity_schema_minimal_with_auto_caption():
    e = _entity()
    # FTM EntityModel auto-derives caption from name property values.
    assert e.caption == "Alice Smith"
    assert e.cache_key == "alice-id"


def test_entity_schema_dump_uses_schema_alias_and_hides_cache_key():
    e = _entity(id="x", properties={"name": ["Alice"]})
    dumped = model_dump(e)
    assert dumped["schema"] == "Person"  # JSON alias, not `schema_`
    assert "cache_key" not in dumped


def test_entity_schema_required_fields_raise_on_missing():
    # ``id``, ``schema`` (via alias ``schema_``), ``properties`` and
    # ``collection_id`` are required. ``schemata`` and ``latinized``
    # both default to empty so raw ES payloads and minimal test
    # constructions validate without them.
    with pytest.raises(ValidationError):
        EntitySchema(schema="Person", properties={"name": ["Alice"]})  # missing id
    with pytest.raises(ValidationError):
        # missing collection_id
        EntitySchema(id="x", schema="Person", properties={"name": ["Alice"]})
    # Minimal valid construction.
    EntitySchema(
        id="x", schema="Person", properties={"name": ["Alice"]}, collection_id=1
    )


def test_entity_schema_with_aleph_extras():
    e = _entity(
        id="x",
        schema="Document",
        properties={"fileName": ["report.pdf"]},
        schemata=["Document", "Folder", "Thing"],
        countries=["us"],
        languages=["eng"],
        score=0.95,
        bookmarked=True,
        writeable=True,
        links={"self": "/api/2/entities/x"},
        collection=CollectionSchema(id="1", name="leaks", title="Leaks"),
    )
    dumped = model_dump(e)
    assert dumped["countries"] == ["us"]
    assert dumped["score"] == 0.95
    assert dumped["bookmarked"] is True
    assert dumped["writeable"] is True
    assert dumped["links"] == {"self": "/api/2/entities/x"}
    assert dumped["collection"]["name"] == "leaks"


def test_entity_schema_validates_from_dict_with_datasets_referents():
    e = EntitySchema.model_validate(
        {
            "id": "x",
            "schema": "Person",
            "properties": {"name": ["Bob"]},
            "schemata": ["Person", "LegalEntity", "Thing"],
            "collection_id": 1,
            "latinized": {},
            "datasets": ["leaks", "opensanctions"],
            "referents": ["ofac-1234"],
            "countries": ["us"],
        }
    )
    assert e.datasets == ["leaks", "opensanctions"]
    assert e.referents == ["ofac-1234"]


def test_entity_schema_nested_entities_in_properties_stay_shallow():
    # Nested entities in `properties` are typed as the FTM EntityModel,
    # not the Aleph-extended EntitySchema.
    e = _entity(
        id="parent",
        schema="LegalEntity",
        schemata=["LegalEntity", "Thing"],
        properties={
            "name": ["Parent"],
            "owner": [
                {"id": "child", "schema": "Person", "properties": {"name": ["Owner"]}}
            ],
        },
    )
    dumped = model_dump(e)
    assert dumped["properties"]["owner"][0]["id"] == "child"


def test_entity_tag_schema():
    t = EntityTagSchema(id="countries:us", field="countries", value="us", count=42)
    dumped = model_dump(t)
    assert dumped == {
        "id": "countries:us",
        "field": "countries",
        "value": "us",
        "count": 42,
    }


def test_entity_expand_schema_nests_entities():
    parent = _entity(id="x", properties={"name": ["Alice"]})
    expand = EntityExpandSchema(property="ownershipOwner", count=1, entities=[parent])
    dumped = model_dump(expand)
    assert dumped["property"] == "ownershipOwner"
    assert dumped["count"] == 1
    assert dumped["entities"][0]["id"] == "x"


def test_similar_schema_judgement_serialises_as_string():
    e = _entity(id="x", properties={"name": ["Alice"]})
    s = SimilarSchema(score=0.9, entity=e, judgement=Judgement.POSITIVE)
    dumped = model_dump(s)
    assert dumped["score"] == 0.9
    assert dumped["judgement"] == "positive"
    assert dumped["entity"]["id"] == "x"


def test_entity_update_requires_schema():
    EntityUpdate.model_validate({"schema": "Person"})
    with pytest.raises(ValidationError):
        EntityUpdate.model_validate({})  # missing required `schema`


def test_entity_create_accepts_inline_collection():
    payload = {
        "schema": "Person",
        "properties": {"name": ["Alice"]},
        "collection": {"id": "1", "name": "leaks", "title": "Leaks"},
        "foreign_id": "alice-fid",
    }
    ec = EntityCreate.model_validate(payload)
    assert ec.foreign_id == "alice-fid"
    assert ec.collection is not None
    assert ec.collection["name"] == "leaks"


def test_entity_create_optional_id_and_collection_id():
    EntityCreate.model_validate({"schema": "Person", "properties": {"name": ["Alice"]}})


def test_entity_collection_id_extracted_from_nested_collection():
    """collection_id is pulled from a nested collection dict when not provided directly."""
    e = EntitySchema(
        id="x",
        schema="Person",
        properties={"name": ["Alice"]},
        collection={"id": "42", "name": "leaks", "title": "Leaks"},
    )
    assert e.collection_id == 42
    assert e.collection is not None
    assert e.collection.name == "leaks"


def test_entity_collection_id_direct_takes_precedence():
    """Explicit collection_id is not overwritten by a nested collection dict."""
    e = EntitySchema(
        id="x",
        schema="Person",
        properties={"name": ["Alice"]},
        collection_id=1,
        collection={"id": "99", "name": "other", "title": "Other"},
    )
    assert e.collection_id == 1


def test_entity_role_id_type_mismatch():
    data = _entity().model_dump()
    data["role_id"] = 1  # should be str, will be converted
    EntitySchema.model_validate(data)
