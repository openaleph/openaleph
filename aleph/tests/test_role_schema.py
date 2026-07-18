"""Pure pydantic smoke tests for the schemas in ``aleph.model.role``
and the request bodies in ``aleph.api.requests.role``.

No DB, no Flask app context, no fixtures. These exist to catch
field-level regressions independently of the integration tests in
``test_role_model.py`` and ``test_roles_api.py``.
"""

import pytest
from pydantic import ValidationError

from aleph.api.requests.role import (
    RoleCodeCreate,
    RoleCreate,
    RoleLogin,
    RoleUpdate,
)
from aleph.model.common import model_dump
from aleph.model.role import RoleSchema


def _role(**overrides) -> RoleSchema:
    """Build a RoleSchema with the now-required fields populated."""
    base = {
        "id": "42",
        "type": "user",
        "name": "Alice",
        "foreign_id": "alice@example.org",
        "label": "Alice",
    }
    base.update(overrides)
    return RoleSchema(**base)


def test_role_schema_cache_key_uses_id():
    """Roles are referenced by int PK everywhere (Permission.role_id,
    Alert.role_id, notification actor_id, …) so the resolver keys
    roles under their id, not foreign_id."""
    role = _role()
    assert role.cache_key == "42"


def test_role_schema_required_fields_raise_on_missing():
    with pytest.raises(ValidationError):
        RoleSchema(id="42", type="user")  # missing name, foreign_id, label
    with pytest.raises(ValidationError):
        RoleSchema(id="42", type="user", name="Alice")  # missing foreign_id, label


def test_role_schema_dump_strips_unset_fields_and_hides_cache_key():
    role = _role()
    dumped = model_dump(role)
    assert "cache_key" not in dumped
    assert dumped["id"] == "42"
    assert dumped["type"] == "user"
    assert dumped["name"] == "Alice"
    assert dumped["foreign_id"] == "alice@example.org"
    assert dumped["label"] == "Alice"
    # Optional sensitive fields are unset → stripped:
    for k in ("email", "api_key", "is_admin", "has_password"):
        assert k not in dumped


def test_role_schema_validate_from_dict_with_iso_datestrings():
    role = RoleSchema.model_validate(
        {
            "id": "42",
            "type": "user",
            "name": "Alice",
            "foreign_id": "alice@example.org",
            "label": "Alice",
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-02-02T00:00:00",
        }
    )
    assert role.created_at is not None and role.created_at.year == 2024
    assert role.updated_at is not None and role.updated_at.month == 2


def test_role_login_requires_both_fields():
    RoleLogin.model_validate({"email": "a@b.org", "password": "secret"})
    with pytest.raises(ValidationError):
        RoleLogin.model_validate({"email": "a@b.org"})
    with pytest.raises(ValidationError):
        RoleLogin.model_validate({"password": "secret"})


def test_role_code_create_requires_email():
    RoleCodeCreate.model_validate({"email": "a@b.org"})
    with pytest.raises(ValidationError):
        RoleCodeCreate.model_validate({})


def test_role_create_password_min_length():
    RoleCreate.model_validate({"password": "secret123", "code": "abc"})
    with pytest.raises(ValidationError):
        RoleCreate.model_validate({"password": "short", "code": "abc"})
    with pytest.raises(ValidationError):
        RoleCreate.model_validate({"password": "longenough"})  # missing code


def test_role_update_all_optional():
    # Empty update is valid (every field optional)
    RoleUpdate.model_validate({})
    RoleUpdate.model_validate({"is_muted": True})
    RoleUpdate.model_validate(
        {"name": "Renamed", "password": "newpassword", "current_password": "old"}
    )
    # Name min length still enforced when supplied:
    with pytest.raises(ValidationError):
        RoleUpdate.model_validate({"name": "abc"})  # < 4 chars


def test_role_schema_none_values_fall_back_to_defaults():
    # APIBaseModel inherits StripNoneMixin: explicit ``None`` input is
    # dropped before validation, so every defaulted field falls back to
    # its declared default instead of raising type errors.
    r = RoleSchema.model_validate(
        {
            "id": "5",
            "type": "user",
            "name": "n",
            "foreign_id": "f",
            "label": "L",
            "is_admin": None,
            "writeable": None,
            "shallow": None,
        }
    )
    assert r.is_admin is None  # optional flag: default None preserved
    assert r.writeable is False  # non-optional bool: default applies
    assert r.shallow is True  # non-False default applies too
