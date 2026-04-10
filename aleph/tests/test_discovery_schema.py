"""Pure pydantic smoke tests for the schemas in ``aleph.model.discover``."""

from aleph.model.common import model_dump
from aleph.model.discover import (
    CollectionDiscovery,
    MentionedTerms,
    SignificantTerms,
    Term,
)


def test_term_computed_label_is_in_dump():
    t = Term(name="angela merkel", count=12)
    dumped = model_dump(t)
    assert dumped == {"name": "angela merkel", "count": 12, "label": "Angela Merkel"}


def test_mentioned_terms_empty_lists_preserved():
    mt = MentionedTerms()
    dumped = model_dump(mt)
    assert dumped["peopleMentioned"] == []
    assert dumped["companiesMentioned"] == []
    assert dumped["locationMentioned"] == []
    assert dumped["namesMentioned"] == []


def test_significant_terms_nests_term():
    st = SignificantTerms(term=Term(name="putin", count=3))
    dumped = model_dump(st)
    assert dumped["term"]["name"] == "putin"
    assert dumped["term"]["label"] == "Putin"
    assert dumped["peopleMentioned"] == []
    assert dumped["companiesMentioned"] == []
    assert dumped["locationMentioned"] == []
    assert dumped["namesMentioned"] == []


def test_collection_discovery_cache_key():
    d = CollectionDiscovery(collection_id="42")
    assert d.cache_key == "42"


def test_collection_discovery_cache_key_invisible_in_dump():
    d = CollectionDiscovery(
        collection_id="42",
        peopleMentioned=[
            SignificantTerms(term=Term(name="putin", count=10)),
        ],
    )
    dumped = model_dump(d)
    assert "cache_key" not in dumped
    assert dumped["collection_id"] == "42"
    assert dumped["peopleMentioned"][0]["term"]["name"] == "putin"
