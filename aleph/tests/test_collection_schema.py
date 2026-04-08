"""Pure pydantic smoke tests for the schemas in ``aleph.model.collection``
and the request bodies in ``aleph.api.requests.collection``."""

import pytest
from pydantic import ValidationError

from aleph.api.requests.collection import CollectionCreate, CollectionUpdate
from aleph.model.collection import (
    CollectionDeepSchema,
    CollectionJobStatus,
    CollectionSchema,
    CollectionStatistics,
    CollectionStatus,
    FacetCounts,
)
from aleph.model.common import model_dump


def test_collection_schema_minimal_dict():
    c = CollectionSchema(name="opensanctions", title="OpenSanctions")
    assert c.name == "opensanctions"
    assert c.title == "OpenSanctions"
    assert c.cache_key == "opensanctions"
    dumped = model_dump(c)
    assert dumped["name"] == "opensanctions"
    assert dumped["title"] == "OpenSanctions"
    assert "cache_key" not in dumped


def test_collection_schema_with_ftm_coverage_and_publisher():
    c = CollectionSchema.model_validate(
        {
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
    c = CollectionSchema(name="x", title="X")
    dumped = model_dump(c)
    assert dumped["restricted"] is False
    assert dumped["xref"] is False
    assert dumped["taggable"] is False


def test_facet_counts_default_empty():
    f = FacetCounts()
    dumped = model_dump(f)
    # Empty values dict + zero total → fully stripped
    assert dumped is None or dumped == {} or dumped == {"total": 0}


def test_facet_counts_round_trip():
    f = FacetCounts(values={"Person": 42, "Company": 12}, total=54)
    dumped = model_dump(f)
    assert dumped == {"values": {"Person": 42, "Company": 12}, "total": 54}


def test_collection_statistics_cache_key_path_style():
    s = CollectionStatistics(foreign_id="opensanctions")
    assert s.cache_key == "opensanctions/stats"


def test_collection_statistics_with_facets():
    s = CollectionStatistics.model_validate(
        {
            "foreign_id": "opensanctions",
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


def test_collection_status_cache_key_path_style():
    st = CollectionStatus(foreign_id="opensanctions")
    assert st.cache_key == "opensanctions/status"


def test_collection_status_with_jobs():
    st = CollectionStatus(
        foreign_id="opensanctions",
        finished=12,
        pending=3,
        running=1,
        jobs=[
            CollectionJobStatus(finished=5, pending=2),
            CollectionJobStatus(finished=7, running=1),
        ],
    )
    dumped = model_dump(st)
    assert dumped["finished"] == 12
    assert len(dumped["jobs"]) == 2


def test_collection_deep_schema_includes_aggregates():
    c = CollectionDeepSchema(
        name="opensanctions",
        title="OpenSanctions",
        statistics=CollectionStatistics(foreign_id="opensanctions"),
        status=CollectionStatus(foreign_id="opensanctions", finished=10),
    )
    dumped = model_dump(c)
    assert dumped["statistics"]["foreign_id"] == "opensanctions"
    assert dumped["status"]["finished"] == 10


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
