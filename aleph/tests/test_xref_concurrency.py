"""
Concurrency tests for the SQL judgement graph.

Graph mutations serialize on a global advisory lock inside one
transaction each; racing decides/imports must never split canonicals or
violate the one-cluster-per-node membership invariant (PK on entity_id).
"""

import threading

from nomenklatura.judgement import Judgement
from sqlalchemy import text as sa_text

from aleph.core import db
from aleph.logic.xref.resolver import get_resolver
from aleph.model.xref import ESEdge

# Reuse the app-context + clean-stores fixtures from the resolver tests.
from aleph.tests.test_xref_resolver import flask_app, resolver  # noqa: F401


def _run_threads(workers) -> list[Exception]:
    errors: list[Exception] = []

    def wrap(fn):
        def inner():
            try:
                fn()
            except Exception as exc:  # pragma: no cover - failure evidence
                errors.append(exc)

        return inner

    threads = [threading.Thread(target=wrap(fn)) for fn in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


def _assert_membership_invariant() -> None:
    """Every node belongs to exactly one cluster (PK) and every member of a
    cluster points at the cluster's canonical (no dangling pointers)."""
    with db.engine.connect() as conn:
        dangling = conn.execute(sa_text("""
                SELECT c.entity_id FROM xref_cluster c
                LEFT JOIN xref_cluster canon
                  ON canon.entity_id = c.canonical_id
                WHERE canon.entity_id IS NULL
                """)).all()
    assert dangling == [], dangling


def test_concurrent_decides(flask_app, resolver):  # noqa: F811
    """Racing overlapping POSITIVE decides converge on one canonical."""

    def decide(left: str, right: str):
        def run():
            with flask_app.app_context():
                get_resolver(sync=True).decide(left, right, Judgement.POSITIVE)

        return run

    errors = _run_threads(
        [
            decide("a1", "b1"),
            decide("b1", "c1"),
            decide("a1", "d1"),
            decide("c1", "e1"),
        ]
    )
    assert errors == [], errors

    canonical = resolver.get_canonical("a1")
    assert canonical.startswith("NK-"), canonical
    for node in ("a1", "b1", "c1", "d1", "e1"):
        assert resolver.get_canonical(node) == canonical, node
    _assert_membership_invariant()


def test_concurrent_import_and_decide(flask_app, resolver):  # noqa: F811
    """A bulk import racing a UI decide serializes without losing edges."""
    docs = [
        ESEdge(source=f"i{n}", target=f"i{n + 1}", judgement="positive", user="import")
        for n in range(30)
    ]

    def import_worker():
        with flask_app.app_context():
            get_resolver(sync=True).import_decisions(iter(docs))

    def decide_worker():
        with flask_app.app_context():
            r = get_resolver(sync=True)
            r.decide("i5", "x1", Judgement.POSITIVE)

    errors = _run_threads([import_worker, decide_worker])
    assert errors == [], errors

    canonical = resolver.get_canonical("i0")
    assert canonical.startswith("NK-"), canonical
    for node in ("i0", "i15", "i30", "i5", "x1"):
        assert resolver.get_canonical(node) == canonical, node
    _assert_membership_invariant()


def test_import_cluster_size_cap(resolver):  # noqa: F811
    """Merges beyond the cap are queued as suggestions, not applied."""
    from aleph.index.xref import query_edges

    docs = [
        ESEdge(
            source=f"m{n}",
            target=f"m{n + 1}",
            judgement="positive",
            user="auto-merge",
            score=0.9,
        )
        for n in range(5)
    ]
    stats = resolver.import_decisions(iter(docs), max_cluster_size=3)
    assert stats["diverted"] == 1, stats
    assert stats["applied"] == 6, stats

    # The diverted merge became a reviewable suggestion with its score.
    suggested = query_edges([{"term": {"judgement": "no_judgement"}}], size=10)
    assert len(suggested) == 1, suggested
    assert suggested[0]["score"] == 0.9

    # Two separate clusters of three; the capped link never merged them.
    assert resolver.get_canonical("m0") == resolver.get_canonical("m2")
    assert resolver.get_canonical("m3") == resolver.get_canonical("m5")
    assert resolver.get_canonical("m0") != resolver.get_canonical("m3")
    _assert_membership_invariant()
