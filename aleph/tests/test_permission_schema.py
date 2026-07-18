"""Pure pydantic smoke tests for the schemas in ``aleph.model.permission``
and the request body in ``aleph.api.requests.permission``."""

import pytest
from pydantic import ValidationError

from aleph.api.requests.permission import PermissionUpdate
from aleph.model.common import model_dump
from aleph.model.permission import PermissionSchema
from aleph.model.role import RoleSchema


def _role(**overrides) -> RoleSchema:
    base = {
        "id": "42",
        "type": "user",
        "name": "Alice",
        "foreign_id": "alice@example.org",
        "label": "Alice",
    }
    base.update(overrides)
    return RoleSchema(**base)


def test_permission_schema_minimal():
    p = PermissionSchema(
        id="5", collection_id="7", role_id="42", read=False, write=False
    )
    assert p.cache_key == "5"
    dumped = model_dump(p)
    assert dumped["id"] == "5"
    assert dumped["collection_id"] == "7"
    assert dumped["role_id"] == "42"
    assert dumped["read"] is False
    assert dumped["write"] is False


def test_permission_schema_required_fields_raise_on_missing():
    with pytest.raises(ValidationError):
        PermissionSchema(id="5")
    with pytest.raises(ValidationError):
        PermissionSchema(id="5", collection_id="7", role_id="42")  # missing read/write
    with pytest.raises(ValidationError):
        PermissionSchema(
            id="5", collection_id="7", read=True, write=True
        )  # missing role_id


def test_permission_schema_with_nested_role():
    p = PermissionSchema(
        id="5",
        collection_id="7",
        role_id="42",
        read=True,
        write=True,
        role=_role(),
    )
    dumped = model_dump(p)
    assert dumped["role"]["id"] == "42"
    assert dumped["role"]["name"] == "Alice"
    # Nested role's cache_key is not in the dump
    assert "cache_key" not in dumped["role"]


def test_permission_int_id_coercion():
    p = PermissionSchema(id="5", collection_id=7, role_id=42, read=True, write=False)
    assert p.collection_id == "7"
    assert p.role_id == "42"


def test_permission_update_requires_read_and_write():
    PermissionUpdate.model_validate({"read": True, "write": False})
    with pytest.raises(ValidationError):
        PermissionUpdate.model_validate({"read": True})  # missing write
    with pytest.raises(ValidationError):
        PermissionUpdate.model_validate({"write": True})  # missing read


def test_permission_update_accepts_nested_role():
    PermissionUpdate.model_validate(
        {
            "read": True,
            "write": True,
            "role": {
                "id": "42",
                "type": "user",
                "name": "Alice",
                "foreign_id": "alice@example.org",
                "label": "Alice",
            },
        }
    )
