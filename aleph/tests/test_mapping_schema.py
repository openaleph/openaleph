"""Pure pydantic smoke tests for the schemas in ``aleph.model.mapping``
and the request bodies in ``aleph.api.requests.mapping``."""

import pytest
from pydantic import ValidationError

from aleph.api.requests.mapping import MappingCreate, MappingUpdate
from aleph.model.common import model_dump
from aleph.model.entity import EntitySchema
from aleph.model.entityset import EntitySetSchema
from aleph.model.mapping import MappingSchema


def _mapping(**overrides) -> MappingSchema:
    base = {
        "id": "11",
        "collection_id": "42",
        "role_id": "7",
        "table_id": "table-abc",
        "query": {"persons": {"schema": "Person"}},
    }
    base.update(overrides)
    return MappingSchema(**base)


def test_mapping_schema_minimal():
    m = _mapping()
    assert m.cache_key == "11"
    dumped = model_dump(m)
    assert dumped["id"] == "11"
    assert dumped["table_id"] == "table-abc"
    assert dumped["query"] == {"persons": {"schema": "Person"}}


def test_mapping_schema_required_fields_raise_on_missing():
    with pytest.raises(ValidationError):
        MappingSchema(id="11")
    with pytest.raises(ValidationError):
        MappingSchema(
            id="11",
            collection_id="42",
            role_id="7",
            table_id="table-abc",
        )  # missing query


def test_mapping_schema_with_nested_entityset_and_table():
    m = _mapping(
        entityset_id="set-xyz",
        entityset=EntitySetSchema(
            id="set-xyz",
            type="list",
            label="Persons",
            role_id="7",
            collection_id="42",
        ),
        table=EntitySchema(
            id="table-abc",
            schema="Table",
            properties={"fileName": ["data.csv"]},
            schemata=["Table", "Document", "Folder", "Thing"],
            latinized={},
        ),
    )
    dumped = model_dump(m)
    assert dumped["entityset"]["id"] == "set-xyz"
    assert dumped["entityset"]["type"] == "list"
    assert dumped["table"]["id"] == "table-abc"
    assert dumped["table"]["caption"] == "data.csv"


def test_mapping_schema_with_run_status():
    m = _mapping(last_run_status="successful", last_run_err_msg=None)
    dumped = model_dump(m)
    assert dumped["last_run_status"] == "successful"
    assert "last_run_err_msg" not in dumped  # None → stripped


def test_mapping_create_requires_table_id_and_query():
    MappingCreate.model_validate(
        {"table_id": "table-abc", "mapping_query": {"persons": {}}}
    )
    with pytest.raises(ValidationError):
        MappingCreate.model_validate({"table_id": "table-abc"})  # missing query
    with pytest.raises(ValidationError):
        MappingCreate.model_validate({"mapping_query": {}})  # missing table_id


def test_mapping_update_extends_create():
    MappingUpdate.model_validate(
        {
            "table_id": "table-abc",
            "mapping_query": {"persons": {}},
            "entityset_id": "set-xyz",
        }
    )
