"""Pure pydantic smoke tests for the schemas in ``aleph.model.collection``
and the request bodies in ``aleph.api.requests.collection``."""

import pytest
from pydantic import ValidationError

from aleph.api.requests.collection import CollectionCreate, CollectionUpdate
from aleph.model.collection import (
    CollectionDetailSchema,
    CollectionSchema,
    CollectionStatistics,
    CollectionStatus,
    FacetCounts,
)
from aleph.model.common import model_dump


def test_collection_schema_minimal_dict():
    c = CollectionSchema(id="42", name="opensanctions", title="OpenSanctions")
    assert c.name == "opensanctions"
    assert c.title == "OpenSanctions"
    assert c.cache_key == "42"
    assert c.foreign_id == "opensanctions"
    assert c.label == "OpenSanctions"
    dumped = model_dump(c)
    assert dumped["name"] == "opensanctions"
    assert dumped["title"] == "OpenSanctions"
    assert dumped["foreign_id"] == "opensanctions"
    assert dumped["label"] == "OpenSanctions"
    assert "cache_key" not in dumped


def test_collection_schema_with_ftm_coverage_and_publisher():
    c = CollectionSchema.model_validate(
        {
            "id": "42",
            "name": "opensanctions",
            "title": "OpenSanctions",
            "summary": "Sanctions and PEPs",
            "url": "https://opensanctions.org",
            "publisher": {"name": "OpenSanctions", "url": "https://opensanctions.org"},
            "coverage": {"countries": ["us", "de"], "frequency": "daily"},
            "languages": ["eng", "deu"],
            "restricted": False,
            "xref": True,
        }
    )
    dumped = model_dump(c)
    assert dumped["coverage"]["countries"] == ["us", "de"]
    assert dumped["coverage"]["frequency"] == "daily"
    assert dumped["publisher"]["name"] == "OpenSanctions"
    assert dumped["languages"] == ["eng", "deu"]
    assert dumped["xref"] is True


def test_collection_schema_aleph_extras_default_false():
    c = CollectionSchema(id="1", name="x", title="X")
    dumped = model_dump(c)
    assert dumped["restricted"] is False
    assert dumped["xref"] is False
    assert dumped["taggable"] is False


def test_collection_schema_none_bools_fall_back_to_default():
    # StripNoneMixin: explicit ``None`` values are dropped from mapping
    # input before validation (legacy dicts / nullable SQLA columns), so
    # pydantic applies the field default instead of raising bool_type
    # errors – e.g. ``contains_ai``.
    c = CollectionSchema.model_validate(
        {
            "id": "42",
            "name": "x",
            "title": "X",
            "contains_ai": None,
            "external": None,
            "secret": None,
            "languages": None,
        }
    )
    assert c.contains_ai is False
    assert c.external is False
    assert c.secret is False
    assert c.languages == []


def test_collection_schema_legacy_flat_publisher():
    # Legacy dicts (``Collection.to_dict()`` / old index docs) carry
    # ``publisher`` as a plain string with ``publisher_url`` beside it –
    # the dict branch of ``_from_collection`` folds both into the FTM
    # ``DataPublisher`` shape and maps ``info_url`` → ``url``.
    c = CollectionSchema.model_validate(
        {
            "id": "7",
            "foreign_id": "cpr",
            "label": "CPR",
            "publisher": "Corporate Prosecution Registry",
            "publisher_url": "https://example.org",
            "info_url": "https://example.org/about",
        }
    )
    assert c.publisher is not None
    assert c.publisher.name == "Corporate Prosecution Registry"
    assert str(c.publisher.url).startswith("https://example.org")
    assert str(c.url) == "https://example.org/about"
    # dict-shaped publishers (cached schema dumps) pass through untouched
    c2 = CollectionSchema.model_validate(
        {"id": "9", "name": "y", "title": "Y", "publisher": {"name": "P"}}
    )
    assert c2.publisher is not None
    assert c2.publisher.name == "P"


def test_collection_schema_legacy_flat_frequency():
    # Legacy flat ``frequency`` folds into ``coverage.frequency`` with the
    # Aleph→FTM value mapping ("annual" → "annually") applied.
    c = CollectionSchema.model_validate(
        {"id": "7", "foreign_id": "cpr", "label": "CPR", "frequency": "annual"}
    )
    assert c.coverage is not None
    assert c.coverage.frequency == "annually"
    # an existing coverage dict (cached schema dumps) keeps its own value
    c2 = CollectionSchema.model_validate(
        {
            "id": "9",
            "name": "y",
            "title": "Y",
            "frequency": "annual",
            "coverage": {"frequency": "daily"},
        }
    )
    assert c2.coverage is not None
    assert c2.coverage.frequency == "daily"
    # absent / None frequency conjures no coverage
    c3 = CollectionSchema.model_validate(
        {"id": "10", "name": "z", "title": "Z", "frequency": None}
    )
    assert c3.coverage is None


def test_collection_schema_none_optional_and_required():
    # Optional fields keep their ``None`` default; required fields
    # without a fallback still fail – as "missing" instead of a type
    # error, since the ``None`` is stripped before validation.
    c = CollectionSchema.model_validate(
        {"id": "42", "name": "x", "title": "X", "summary": None}
    )
    assert c.summary is None
    with pytest.raises(ValidationError) as exc:
        CollectionSchema.model_validate({"name": "x", "title": "X", "id": None})
    assert exc.value.errors()[0]["type"] == "missing"
    assert exc.value.errors()[0]["loc"] == ("id",)


def test_facet_counts_default_empty():
    f = FacetCounts()
    dumped = model_dump(f)
    # Empty values dict + zero total → fully stripped
    assert dumped is None or dumped == {} or dumped == {"total": 0}


def test_facet_counts_round_trip():
    f = FacetCounts(values={"Person": 42, "Company": 12}, total=54)
    dumped = model_dump(f)
    assert dumped == {"values": {"Person": 42, "Company": 12}, "total": 54}


def test_collection_statistics_cache_key():
    s = CollectionStatistics(collection_id="42")
    assert s.cache_key == "42"


def test_collection_statistics_with_facets():
    s = CollectionStatistics.model_validate(
        {
            "collection_id": "42",
            "schema": {  # JSON key is `schema`, python attr is `schema_`
                "values": {"Person": 100, "Company": 30},
                "total": 130,
            },
            "countries": {"values": {"us": 80, "de": 50}, "total": 130},
        }
    )
    dumped = model_dump(s)
    # Output uses the JSON alias `schema`
    assert dumped["schema"]["values"]["Person"] == 100
    assert dumped["schema"]["total"] == 130
    assert dumped["countries"]["values"]["us"] == 80
    assert "cache_key" not in dumped


def test_collection_status_from_dataset_name():
    """CollectionStatus derives collection_id from the aggregator
    dataset name (``collection_<id>``)."""
    st = CollectionStatus(name="collection_42")
    assert st.collection_id == "42"
    dumped = model_dump(st)
    assert dumped["collection_id"] == "42"
    assert dumped["name"] == "collection_42"


def test_collection_status_counts():
    st = CollectionStatus(
        name="collection_42",
        todo=3,
        doing=1,
        succeeded=12,
    )
    dumped = model_dump(st)
    assert dumped["succeeded"] == 12
    assert dumped["todo"] == 3
    assert dumped["doing"] == 1


def test_collection_detail_schema_includes_aggregates():
    c = CollectionDetailSchema(
        id="42",
        name="opensanctions",
        title="OpenSanctions",
        statistics=CollectionStatistics(collection_id="42"),
        status=CollectionStatus(name="collection_42", succeeded=10),
    )
    dumped = model_dump(c)
    assert dumped["statistics"]["collection_id"] == "42"
    assert dumped["status"]["succeeded"] == 10
    assert dumped["status"]["collection_id"] == "42"
    assert dumped["foreign_id"] == "opensanctions"
    assert dumped["label"] == "OpenSanctions"


def test_collection_create_label_min_length():
    CollectionCreate.model_validate({"label": "OK label"})
    with pytest.raises(ValidationError):
        CollectionCreate.model_validate({"label": "x"})  # < 2
    with pytest.raises(ValidationError):
        CollectionCreate.model_validate({})  # missing label


def test_collection_update_extends_create_with_creator():
    CollectionUpdate.model_validate(
        {
            "label": "OK label",
            "creator_id": "42",
            "creator": {
                "id": "42",
                "type": "user",
                "name": "Alice",
                "foreign_id": "alice@example.org",
                "label": "Alice",
            },
        }
    )
