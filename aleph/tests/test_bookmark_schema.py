"""Pure pydantic smoke tests for the schemas in ``aleph.model.bookmark``
and the request body in ``aleph.api.requests.bookmark``."""

import pytest
from pydantic import ValidationError

from aleph.api.requests.bookmark import BookmarkCreate
from aleph.model.bookmark import BookmarkSchema
from aleph.model.common import model_dump


def _bookmark(**overrides) -> BookmarkSchema:
    base = {
        "id": "11",
        "entity_id": "abc-123",
        "role_id": "42",
        "collection_id": "7",
        "created_at": "2024-01-01T00:00:00",
    }
    base.update(overrides)
    return BookmarkSchema(**base)


def test_bookmark_schema_minimal():
    bm = _bookmark()
    # cache_key falls back to bookmark row id (no foreign_id on this resource)
    assert bm.cache_key == "11"
    dumped = model_dump(bm)
    assert dumped["id"] == "11"
    assert dumped["entity_id"] == "abc-123"
    assert dumped["role_id"] == "42"
    assert dumped["collection_id"] == "7"
    assert dumped["created_at"] == "2024-01-01T00:00:00"


def test_bookmark_schema_required_fields_raise_on_missing():
    # All five fields are app invariants – none can be omitted.
    with pytest.raises(ValidationError):
        BookmarkSchema(id="11", entity_id="abc-123")
    with pytest.raises(ValidationError):
        BookmarkSchema(
            id="11",
            entity_id="abc-123",
            role_id="42",
            collection_id="7",
        )  # missing created_at


def test_bookmark_int_id_coercion():
    bm = _bookmark(role_id=42, collection_id=7)
    assert bm.role_id == "42"
    assert bm.collection_id == "7"


def test_bookmark_create_requires_entity_id():
    BookmarkCreate.model_validate({"entity_id": "abc-123"})
    with pytest.raises(ValidationError):
        BookmarkCreate.model_validate({})
