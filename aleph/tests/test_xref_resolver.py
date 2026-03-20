from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest
from followthemoney import Statement
from nomenklatura.judgement import Judgement
from nomenklatura.resolver import Identifier
from nomenklatura.resolver.edge import Edge

from aleph.index.xref import delete_xref
from aleph.logic.xref.resolver import ElasticsearchResolver, get_resolver


@pytest.fixture()
def resolver():
    """Provide a fresh ElasticsearchResolver with a clean xref index."""
    from openaleph_search.core import get_es

    from aleph.index.xref import configure_xref, xref_index

    # Drop stale index and recreate with proper mapping (copy_to: entities)
    es = get_es()
    es.indices.delete(index=xref_index(), ignore=[404])
    configure_xref()
    return get_resolver(sync=True)


def test_resolver(resolver: ElasticsearchResolver):

    a_canon = resolver.decide("a1", "a2", Judgement.POSITIVE)
    assert a_canon.canonical, a_canon
    assert Identifier.get("a2") in resolver.connected(Identifier.get("a1"))
    assert set(n.id for n in resolver.nodes) == {"a1", "a2", a_canon.id}

    assert resolver.get_judgement("a1", "a2") == Judgement.POSITIVE
    resolver.decide("b1", "b2", Judgement.POSITIVE)
    assert resolver.get_judgement("a1", "b1") == Judgement.NO_JUDGEMENT
    neg_canon = resolver.decide("a2", "b2", Judgement.NEGATIVE)
    assert neg_canon.id == "b2", neg_canon
    assert resolver.get_judgement("a2", "b2") == Judgement.NEGATIVE
    assert resolver.get_judgement("a1", "b1") == Judgement.NEGATIVE
    resolver.suggest("a1", "b1", 7.0)
    assert resolver.get_judgement("a1", "b1") == Judgement.NEGATIVE

    resolver.decide("c1", "c2", Judgement.POSITIVE)
    assert len(list(resolver.canonicals())) == 3, list(resolver.canonicals())
    resolver.remove("c1")
    resolver.remove("c2")
    assert len(list(resolver.canonicals())) == 2, list(resolver.canonicals())

    assert resolver.get_canonical("a1") == a_canon
    assert resolver.get_canonical("a2") == a_canon
    assert resolver.get_canonical("banana") == "banana"

    resolver.decide("a1", "a17", Judgement.POSITIVE)
    assert resolver.get_canonical("a1") == a_canon
    assert resolver.get_canonical("a17") == a_canon
    resolver.decide("a1", "a0", Judgement.POSITIVE)
    assert resolver.get_canonical("a1") == a_canon
    assert resolver.get_canonical("a0") == a_canon
    assert len(list(resolver.canonicals())) == 2, list(resolver.canonicals())

    resolver.decide("a1", "a42", Judgement.POSITIVE)
    assert resolver.get_canonical("a42") == a_canon
    resolver.remove("a42")
    assert resolver.get_canonical("a42") == "a42"

    resolver.suggest("c1", "c2", 7.0)
    assert (c1c2 := resolver.get_edge("c1", "c2")) and c1c2.score == 7.0
    resolver.suggest("c1", "c2", 8.0)
    edge_count = len(resolver.edges)
    # subsequent suggest() updates score
    assert (c1c2 := resolver.get_edge("c1", "c2")) and c1c2.score == 8.0
    assert c1c2 in resolver.edges, resolver.edges
    ccn = resolver.decide("c1", "c2", Judgement.POSITIVE)
    assert resolver.get_edge("c1", "c2") is None
    assert (ccnc2 := resolver.get_edge(ccn, "c2")) and ccnc2.score is None
    # positive decide() replaces non-canon edge with two towards canonical

    assert ccnc2.key in resolver.edges, resolver.edges
    assert c1c2.key not in resolver.edges, resolver.edges
    assert len(resolver.edges) == edge_count + 1

    assert "a1" in resolver.get_referents(a_canon)
    assert "a1" in resolver.get_referents(a_canon, canonicals=False)
    # assert a_canon.id in resolver.get_referents(a_canon)
    assert a_canon.id not in resolver.get_referents(a_canon, canonicals=False)

    resolver.explode("a1")
    assert resolver.get_canonical("a17") == "a17"
    assert resolver.get_judgement(a_canon, "a1") == Judgement.NO_JUDGEMENT
    assert resolver.get_judgement("b1", "b2") == Judgement.POSITIVE

    # Can we actually commit after all these operations?
    resolver.commit()


def test_cluster_to_cluster(resolver: ElasticsearchResolver):
    a_canon = resolver.decide("a1", "a2", Judgement.POSITIVE)
    b_canon = resolver.decide("b1", "b2", Judgement.POSITIVE)
    resolver.decide(a_canon, b_canon, Judgement.UNSURE)
    resolver.decide(a_canon, "a3", Judgement.POSITIVE)
    resolver.remove("a3")

    assert "a1" in resolver.connected(Identifier.get("a1"))
    assert "a2" in resolver.connected(Identifier.get("a1"))
    assert "b1" not in resolver.connected(Identifier.get("a1"))
    assert Edge(a_canon, b_canon) == resolver.get_resolved_edge("a1", "b1")

    # ab_canon = resolver.decide("a1", "b1", Judgement.POSITIVE)
    # TODO: There's a bug here - decide(a, b, POSITIVE) must always return a canonical.
    # assert ab_canon.canonical, ab_canon
    acbc_canon = resolver.decide(a_canon, b_canon, Judgement.POSITIVE)
    assert acbc_canon.canonical, acbc_canon
    assert resolver.get_resolved_edge("a1", "a2") is not None
    assert resolver.get_edge("a1", "a2") is None
    # A referent and canonical
    assert resolver.get_resolved_edge("a1", a_canon) is not None
    assert resolver.get_edge("a1", a_canon) == Edge("a1", a_canon)
    # Two referents whose canonicals were decided upon
    assert resolver.get_resolved_edge("a1", "b1") is not None
    assert resolver.get_edge("a1", "b1") is None

    # indirect canonical
    a_ultimate = resolver.get_canonical("a1")
    b_ultimate = resolver.get_canonical("b1")
    assert a_ultimate == b_ultimate
    assert set(resolver.canonicals()) == {a_ultimate}
    assert len(list(resolver.canonicals())) == 1

    # indirect connected
    expected = {
        Identifier.get("a1"),
        Identifier.get("a2"),
        Identifier.get("b1"),
        Identifier.get(a_canon),
        Identifier.get(b_canon),
    }
    connected = resolver.connected(Identifier.get("a1"))
    assert expected.issubset(connected), (expected, connected)
    assert "a3" not in connected

    # Can we actually commit after all these operations?
    resolver.commit()


def test_linker(resolver: ElasticsearchResolver):
    canon_a = resolver.decide("a1", "a2", Judgement.POSITIVE)
    canon_a = resolver.decide(canon_a, "a3", Judgement.POSITIVE)
    resolver.remove("a3")
    canon_b = resolver.decide("b1", "b2", Judgement.POSITIVE)
    resolver.decide("a1", "Q123", Judgement.POSITIVE)
    resolver.decide("a2", "c2", Judgement.NEGATIVE)
    resolver.commit()
    linker = resolver.get_linker()

    assert len(linker.connected(canon_a)) == 4
    assert len(linker.connected(canon_b)) == 3

    # clusters:
    #   Q123 canon_a a1 a2 # removed a3
    #   canon_b b1 b2
    #   c2
    assert len(linker._entities) == 7, linker._entities
    assert "a1" in linker.get_referents("Q123")
    assert "a2" in linker.get_referents("Q123")
    assert canon_a.id in linker.get_referents("Q123")
    assert "Q123" not in linker.get_referents("Q123")
    assert linker.get_canonical("a1") == "Q123"
    assert linker.get_canonical("b1") == canon_b
    assert linker.get_canonical("c2") == "c2"
    assert linker.get_canonical("x1") == "x1"
    assert linker.get_canonical("a3") == "a3"


def test_resolver_store_load(resolver: ElasticsearchResolver):
    with NamedTemporaryFile("w") as fh:
        path = Path(fh.name)

        canon_a = resolver.decide("a1", "a2", Judgement.POSITIVE)
        resolver.decide(canon_a, "a3", Judgement.POSITIVE)
        resolver.remove("a3")
        resolver.decide("a2", "b2", Judgement.NEGATIVE)
        resolver.suggest("a1", "c1", 7.0)
        resolver.dump(path)

        with open(path, "r") as fh:
            assert len(fh.readlines()) == 3  # no soft-delete

        # clear ES
        delete_xref(sync=True)
        assert len(resolver.edges) == 0

        resolver.load(path)
        assert len(resolver.edges) == 3

        edge = resolver.get_edge("a2", "b2")
        assert edge is not None, edge

        assert resolver.get_canonical("a1") == canon_a

        edge = resolver.get_edge("a1", "c1")
        assert edge is None, edge


def test_resolver_candidates(resolver: ElasticsearchResolver):
    candidates = list(resolver.get_candidates())
    assert len(candidates) == 0, candidates

    resolver.decide("a1", "a2", Judgement.POSITIVE)
    resolver.decide("a2", "b2", Judgement.NEGATIVE)
    resolver.suggest("a1", "b2", 7.0)
    resolver.suggest("a1", "c1", 5.0)
    resolver.suggest("a1", "d1", 4.0)

    candidates = list(resolver.get_candidates())
    assert len(candidates) == 2, candidates
    assert candidates[0][2] == 5.0, candidates

    resolver.prune()
    candidates = list(resolver.get_candidates())
    assert len(candidates) == 0, candidates
    resolver.commit()


def test_get_judgements(resolver: ElasticsearchResolver):
    canon = resolver.decide("a1", "a2", Judgement.POSITIVE)
    resolver.decide(canon, "a3", Judgement.POSITIVE)
    resolver.decide(canon, "a4", Judgement.POSITIVE)
    resolver.decide(canon, "b1", Judgement.NEGATIVE)
    resolver.decide(canon, "b2", Judgement.NEGATIVE)
    resolver.decide(canon, "a3", Judgement.UNSURE)
    resolver.remove("b2")
    edges = resolver.get_judgements(limit=3)
    jgmts = [(e.source.id, e.judgement) for e in edges]
    assert jgmts == [
        ("a3", Judgement.UNSURE),  # first, because it's the last edit
        # b2 was "soft deleted"
        ("b1", Judgement.NEGATIVE),
        ("a4", Judgement.POSITIVE),
        # a1 and a2 to canon excluded by limit.
    ]


def test_suggest_metadata(resolver: ElasticsearchResolver):
    """suggest() persists collection IDs and other metadata on xref edges."""
    from aleph.index.xref import scan_edges

    resolver.suggest(
        "e1",
        "e2",
        score=0.85,
        source_collection_id={10},
        target_collection_id={20},
        method="logic-v1",
        schema="Person",
        text=["Alice", "Alicia"],
        countries=["us", "mx"],
    )

    # Read back the raw ES edge
    edges = list(scan_edges([]))
    assert len(edges) == 1
    edge = edges[0]
    assert {edge.source, edge.target} == {"e1", "e2"}
    assert edge.score == 0.85
    assert edge.source_collection_id == {10}
    assert edge.target_collection_id == {20}
    assert edge.method == "logic-v1"
    assert edge.schema_ == "Person"
    assert set(edge.text) == {"Alice", "Alicia"}
    assert set(edge.countries) == {"us", "mx"}

    # Update score on same edge
    resolver.suggest(
        "e1",
        "e2",
        score=0.95,
        source_collection_id={10},
        target_collection_id={20},
        method="logic-v1",
        schema="Person",
    )
    edges = list(scan_edges([]))
    assert len(edges) == 1
    assert edges[0].score == 0.95

    # decide() with collection metadata
    resolver.decide(
        "e3",
        "e4",
        Judgement.NEGATIVE,
        source_collection_id={30},
        target_collection_id={40},
    )
    filters = [{"term": {"judgement": "negative"}}]
    neg_edges = list(scan_edges(filters))
    assert len(neg_edges) == 1
    assert neg_edges[0].source_collection_id == {30}
    assert neg_edges[0].target_collection_id == {40}

    # POSITIVE decision propagates cluster collection_ids to canonical edges
    resolver.decide(
        "e5",
        "e6",
        Judgement.POSITIVE,
        source_collection_id={50},
        target_collection_id={60},
    )
    pos_filters = [{"term": {"judgement": "positive"}}]
    pos_edges = list(scan_edges(pos_filters))
    # Two canonical edges: e5→NK-* and e6→NK-*
    assert len(pos_edges) == 2, pos_edges
    for edge in pos_edges:
        # The NK-* side carries both cluster collection_ids
        all_colls = edge.source_collection_id | edge.target_collection_id
        assert {50, 60} == all_colls, (edge, all_colls)


def test_resolver_statements(resolver: ElasticsearchResolver):
    canon = resolver.decide("a1", "a2", Judgement.POSITIVE)
    resolver.decide("a2", "b2", Judgement.NEGATIVE)

    stmt = Statement("a1", "holder", "Passport", "b2", "test")

    # A resolver canonicalises the statement entity ID but not ID values.
    stmt = resolver.apply_statement(stmt)
    assert stmt.canonical_id == canon.id
    assert stmt.value == "b2"
