"""Pure pydantic smoke tests for the schemas in ``aleph.model.discover``."""

from aleph.model.common import model_dump
from aleph.model.discover import (
    DatasetDiscovery,
    MentionedTerms,
    SignificantTerms,
    Term,
)


def test_term_computed_label_is_in_dump():
    t = Term(name="angela merkel", count=12)
    dumped = model_dump(t)
    assert dumped == {"name": "angela merkel", "count": 12, "label": "Angela Merkel"}


def test_mentioned_terms_empty_lists_stripped():
    mt = MentionedTerms()
    assert model_dump(mt) is None or model_dump(mt) == {}


def test_significant_terms_nests_term():
    st = SignificantTerms(term=Term(name="putin", count=3))
    dumped = model_dump(st)
    assert dumped["term"]["name"] == "putin"
    assert dumped["term"]["label"] == "Putin"


def test_dataset_discovery_cache_key_includes_dataset_path():
    d = DatasetDiscovery(name="opensanctions")
    assert d.cache_key == "opensanctions/discovery"


def test_dataset_discovery_cache_key_invisible_in_dump():
    d = DatasetDiscovery(
        name="opensanctions",
        peopleMentioned=[
            SignificantTerms(term=Term(name="putin", count=10)),
        ],
    )
    dumped = model_dump(d)
    assert "cache_key" not in dumped
    assert dumped["name"] == "opensanctions"
    assert dumped["peopleMentioned"][0]["term"]["name"] == "putin"
