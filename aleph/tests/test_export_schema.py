"""Pure pydantic smoke tests for the schemas in ``aleph.model.export``."""

import pytest
from pydantic import ValidationError

from aleph.model.common import model_dump
from aleph.model.export import ExportSchema


def _export(**overrides) -> ExportSchema:
    base = {
        "id": "1",
        "label": "Search: putin",
        "operation": "export.search",
        "creator_id": "42",
        "expires_at": "2024-12-31T00:00:00",
        "deleted": False,
        "status": "pending",
        "mime_type": "application/zip",
        "meta": {},
    }
    base.update(overrides)
    return ExportSchema(**base)


def test_export_schema_minimal():
    exp = _export()
    assert exp.cache_key == "1"
    dumped = model_dump(exp)
    assert dumped["id"] == "1"
    assert dumped["label"] == "Search: putin"
    assert dumped["operation"] == "export.search"
    assert dumped["creator_id"] == "42"
    assert dumped["status"] == "pending"
    assert dumped["mime_type"] == "application/zip"


def test_export_schema_required_fields_raise_on_missing():
    with pytest.raises(ValidationError):
        ExportSchema(id="1")
    with pytest.raises(ValidationError):
        ExportSchema(
            id="1",
            label="Search: putin",
            operation="export.search",
            # missing creator_id, expires_at, deleted, status, mime_type, meta
        )


def test_export_schema_with_download_link():
    exp = _export(
        status="successful",
        file_name="search.zip",
        file_size=12345,
        content_hash="abc123",
        meta={"query": "putin", "schemata": ["Person"]},
        links={"download": "/api/2/archive?token=..."},
    )
    dumped = model_dump(exp)
    assert dumped["file_name"] == "search.zip"
    assert dumped["file_size"] == 12345
    assert dumped["meta"] == {"query": "putin", "schemata": ["Person"]}
    assert dumped["links"] == {"download": "/api/2/archive?token=..."}


def test_export_int_id_coercion():
    exp = _export(creator_id=42, collection_id=7)
    assert exp.creator_id == "42"
    assert exp.collection_id == "7"


def test_export_status_localized():
    exp = _export(status="success")
    assert exp.status == "successful"


def test_export_schema_bool_false_is_kept():
    # `deleted=False` carries meaning (it's not "empty"), so it stays in
    # the dump. anystore.clean_dict only strips None / empty strings /
    # empty containers.
    exp = _export()
    dumped = model_dump(exp)
    assert dumped["deleted"] is False
