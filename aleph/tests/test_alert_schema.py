"""Pure pydantic smoke tests for the schemas in ``aleph.model.alert``
and the request body in ``aleph.api.requests.alert``."""

import pytest
from pydantic import ValidationError

from aleph.api.requests.alert import AlertCreate
from aleph.model.alert import AlertSchema
from aleph.model.common import model_dump


def test_alert_schema_minimal():
    alert = AlertSchema(id="7", query="putin", role_id="42")
    assert alert.cache_key == "7"
    dumped = model_dump(alert)
    assert dumped["id"] == "7"
    assert dumped["query"] == "putin"
    assert dumped["role_id"] == "42"
    assert "cache_key" not in dumped
    assert "notified_at" not in dumped


def test_alert_schema_required_fields_raise_on_missing():
    with pytest.raises(ValidationError):
        AlertSchema(id="7")  # missing query and role_id
    with pytest.raises(ValidationError):
        AlertSchema(id="7", query="putin")  # missing role_id
    with pytest.raises(ValidationError):
        AlertSchema(id="7", role_id="42")  # missing query


def test_alert_schema_with_dates_and_links():
    alert = AlertSchema(
        id="7",
        query="putin",
        role_id="42",
        notified_at="2024-03-15T12:00:00",
        created_at="2024-01-01T00:00:00",
        writeable=True,
        links={"self": "/api/2/alerts/7"},
    )
    dumped = model_dump(alert)
    assert dumped["notified_at"] == "2024-03-15T12:00:00"
    assert dumped["writeable"] is True
    assert dumped["links"] == {"self": "/api/2/alerts/7"}


def test_alert_create_query_min_max_length():
    AlertCreate.model_validate({"query": "putin"})
    with pytest.raises(ValidationError):
        AlertCreate.model_validate({"query": "ab"})  # < 3
    with pytest.raises(ValidationError):
        AlertCreate.model_validate({"query": "x" * 101})  # > 100


def test_alert_create_query_required():
    with pytest.raises(ValidationError):
        AlertCreate.model_validate({})
