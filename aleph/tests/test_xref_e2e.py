"""End-to-end tests for the xref decide flow.

Tests the full roundtrip: API endpoint → resolver → ES xref index,
verifying edge state and canonical resolution at each step.
"""

from aleph.core import db
from aleph.index.util import index_entity
from aleph.index.xref import delete_xref, scan_edges
from aleph.logic import xref
from aleph.logic.xref.resolver import get_resolver
from aleph.tests.util import TestCase


class XrefDecideE2ETestCase(TestCase):
    """E2E: Coll A has Entity 1, Coll B has Entity 2, Coll C has Entity 3.

    Tests the decide endpoint and verifies resolver state + xref edge index.
    """

    def setUp(self):
        super().setUp()
        delete_xref()

        self.creator = self.create_user(foreign_id="creator")

        self.coll_a = self.create_collection(
            label="Collection A",
            foreign_id="coll_a",
            creator=self.creator,
        )
        self.coll_b = self.create_collection(
            label="Collection B",
            foreign_id="coll_b",
            creator=self.creator,
        )
        self.coll_c = self.create_collection(
            label="Collection C",
            foreign_id="coll_c",
            creator=self.creator,
        )

        self.ent1 = self.create_entity(
            {"schema": "Person", "properties": {"name": "Jane Doe"}},
            self.coll_a,
        )
        self.ent2 = self.create_entity(
            {"schema": "Person", "properties": {"name": "Jane Doe"}},
            self.coll_b,
        )
        self.ent3 = self.create_entity(
            {"schema": "Person", "properties": {"name": "Jane Doe"}},
            self.coll_c,
        )

        db.session.commit()
        index_entity(self.ent1)
        index_entity(self.ent2)
        index_entity(self.ent3)

    def _decide(self, headers, entity_id, match_id, judgement):
        return self.client.post(
            "/api/2/xref/_decide",
            headers=headers,
            json={
                "entity_id": entity_id,
                "match_id": match_id,
                "judgement": judgement,
            },
        )

    def _assert_entity_canonical_id(self, headers, entity_id, expected_canonical_id):
        """Assert the entity detail endpoint returns the expected canonical_id."""
        res = self.client.get(f"/api/2/entities/{entity_id}", headers=headers)
        assert res.status_code == 200, res.json
        actual = res.json.get("canonical_id")
        assert actual == expected_canonical_id, (
            f"Entity {entity_id}: expected canonical_id={expected_canonical_id}, "
            f"got {actual}"
        )

    def test_positive_decide_creates_canonical(self):
        """Decide entity1 = entity2 → NK-* canonical, correct edges in index."""
        _, headers = self.login("creator")

        # Step 1: Decide POSITIVE
        res = self._decide(headers, self.ent1.id, self.ent2.id, "positive")
        assert res.status_code == 200, res.json
        canonical_id = res.json["canonical_id"]
        assert canonical_id.startswith("NK-"), canonical_id

        # Step 2: Both entities resolve to the same NK-* canonical
        resolver = get_resolver()
        assert resolver.get_canonical(self.ent1.id) == canonical_id
        assert resolver.get_canonical(self.ent2.id) == canonical_id

        # Step 3: Verify xref edge index state
        # With a fresh decide (no prior suggestion), the resolver creates the
        # ent1↔ent2 edge then immediately replaces it with two canonical edges.
        # The original edge is soft-deleted only if it existed as a prior
        # NO_JUDGEMENT suggestion; otherwise only the 2 canonical edges exist.
        all_edges = list(scan_edges([], include_deleted=True))

        active_edges = [e for e in all_edges if e.deleted_at is None]
        assert len(active_edges) == 2, [
            (e.source, e.target, e.judgement) for e in active_edges
        ]
        for edge in active_edges:
            assert edge.judgement == "positive", edge
            entity_ids = {edge.source, edge.target}
            assert canonical_id in entity_ids, (edge.source, edge.target, canonical_id)
            other_id = (entity_ids - {canonical_id}).pop()
            assert other_id in (self.ent1.id, self.ent2.id), other_id

        # Entity detail endpoints return canonical_id
        self._assert_entity_canonical_id(headers, self.ent1.id, canonical_id)
        self._assert_entity_canonical_id(headers, self.ent2.id, canonical_id)
        # E3 is not part of the cluster
        self._assert_entity_canonical_id(headers, self.ent3.id, None)

    def test_positive_decide_with_prior_suggestion(self):
        """xref_collection creates a NO_JUDGEMENT suggestion first,
        then decide POSITIVE replaces it with canonical edges."""
        _, headers = self.login("creator")

        # Run xref to create a NO_JUDGEMENT suggestion edge between ent1↔ent2
        xref.SCORE_CUTOFF = 0.01
        xref.xref_collection(self.coll_a)

        # Verify the suggestion edge exists
        pre_edges = list(scan_edges([]))
        assert len(pre_edges) >= 1, "xref_collection should create suggestion edges"
        suggestion = [
            e for e in pre_edges if {e.source, e.target} == {self.ent1.id, self.ent2.id}
        ]
        assert len(suggestion) == 1, [
            (e.source, e.target, e.judgement) for e in pre_edges
        ]
        assert suggestion[0].judgement == "no_judgement"

        # Decide POSITIVE via the API
        res = self._decide(headers, self.ent1.id, self.ent2.id, "positive")
        assert res.status_code == 200, res.json
        canonical_id = res.json["canonical_id"]
        assert canonical_id.startswith("NK-"), canonical_id

        # Both entities resolve to the same canonical
        resolver = get_resolver()
        assert resolver.get_canonical(self.ent1.id) == canonical_id
        assert resolver.get_canonical(self.ent2.id) == canonical_id

        # Verify edge index for the decided pair.
        # xref_collection may also create suggestion edges for ent1↔ent3,
        # so filter to edges involving the canonical or both decided entities.
        decided_ids = {self.ent1.id, self.ent2.id, canonical_id}
        all_edges = list(scan_edges([], include_deleted=True))
        relevant = [
            e
            for e in all_edges
            if {e.source, e.target} & decided_ids == {e.source, e.target}
        ]
        active_edges = [e for e in relevant if e.deleted_at is None]
        deleted_edges = [e for e in relevant if e.deleted_at is not None]

        # 2 active POSITIVE edges: ent1→NK-* and ent2→NK-*
        assert len(active_edges) == 2, [
            (e.source, e.target, e.judgement) for e in active_edges
        ]
        for edge in active_edges:
            assert edge.judgement == "positive", edge
            entity_ids = {edge.source, edge.target}
            assert canonical_id in entity_ids, (edge.source, edge.target, canonical_id)

        # 1 soft-deleted edge: the original ent1↔ent2 suggestion
        assert len(deleted_edges) == 1, [
            (e.source, e.target, e.judgement, e.deleted_at) for e in deleted_edges
        ]
        deleted_entity_ids = {deleted_edges[0].source, deleted_edges[0].target}
        assert deleted_entity_ids == {self.ent1.id, self.ent2.id}

    def test_canonical_cluster_after_positive_decide(self):
        """After decide POSITIVE, the canonical endpoint returns merged cluster."""
        _, headers = self.login("creator")

        res = self._decide(headers, self.ent1.id, self.ent2.id, "positive")
        canonical_id = res.json["canonical_id"]

        # Canonical endpoint returns the merged cluster
        res = self.client.get(f"/api/2/canonical/{canonical_id}", headers=headers)
        assert res.status_code == 200, res.json
        assert res.json["id"] == canonical_id
        entity_ids = {e["id"] for e in res.json["entities"]}
        assert self.ent1.id in entity_ids
        assert self.ent2.id in entity_ids
        assert len(entity_ids) == 2

        # Entity-to-canonical lookup also works
        res = self.client.get(
            f"/api/2/entities/{self.ent1.id}/canonical", headers=headers
        )
        assert res.status_code == 200, res.json
        assert res.json["id"] == canonical_id

        # Entity detail endpoints return canonical_id
        self._assert_entity_canonical_id(headers, self.ent1.id, canonical_id)
        self._assert_entity_canonical_id(headers, self.ent2.id, canonical_id)

    def test_undecide_entity_from_canonical(self):
        """After decide E1=E2, undeciding E1→NK-* breaks the cluster.

        Expected state after undecide:
        - E1→NK-* edge becomes NO_JUDGEMENT
        - E2→NK-* edge remains POSITIVE
        - E1 no longer resolves to a canonical (get_canonical returns E1)
        - E2 still resolves to NK-*, but the cluster has only 1 real entity
          so get_canonical_cluster returns None
        - The canonical endpoint returns 404 for both sides
        """
        _, headers = self.login("creator")

        # First: create the canonical cluster
        res = self._decide(headers, self.ent1.id, self.ent2.id, "positive")
        canonical_id = res.json["canonical_id"]

        # Verify cluster exists before undecide
        res = self.client.get(f"/api/2/canonical/{canonical_id}", headers=headers)
        assert res.status_code == 200

        # Undecide: set E1→NK-* to no_judgement
        res = self._decide(headers, self.ent1.id, canonical_id, "no_judgement")
        assert res.status_code == 200, res.json

        # Resolver state: E1 no longer resolves to canonical
        resolver = get_resolver()
        assert resolver.get_canonical(self.ent1.id) == self.ent1.id
        # E2 still resolves to NK-* at the resolver level
        assert resolver.get_canonical(self.ent2.id) == canonical_id

        # Edge state: E1→NK-* is now NO_JUDGEMENT, E2→NK-* still POSITIVE
        active_edges = list(scan_edges([]))
        edges_by_entity = {}
        for edge in active_edges:
            ids = {edge.source, edge.target}
            if canonical_id in ids:
                other = (ids - {canonical_id}).pop()
                edges_by_entity[other] = edge.judgement
        assert edges_by_entity.get(self.ent1.id) == "no_judgement", edges_by_entity
        assert edges_by_entity.get(self.ent2.id) == "positive", edges_by_entity

        # Canonical cluster no longer valid (only 1 real entity remains)
        # → canonical endpoint returns 404
        res = self.client.get(f"/api/2/canonical/{canonical_id}", headers=headers)
        assert res.status_code == 404, res.json

        # Entity-to-canonical lookup also returns 404
        res = self.client.get(
            f"/api/2/entities/{self.ent1.id}/canonical", headers=headers
        )
        assert res.status_code == 404, res.json
        res = self.client.get(
            f"/api/2/entities/{self.ent2.id}/canonical", headers=headers
        )
        assert res.status_code == 404, res.json

        # Entity detail view should NOT return canonical_id when cluster is broken
        self._assert_entity_canonical_id(headers, self.ent1.id, None)
        self._assert_entity_canonical_id(headers, self.ent2.id, None)

    def test_redecide_after_undecide_restores_cluster(self):
        """Undecide E1→NK-*, then re-decide E1→NK-* as POSITIVE.

        The resolver should restore the same NK-* canonical (E2→NK-* is still
        POSITIVE, so connected(NK-*) includes NK-* and the max is still NK-*).
        The cluster should be fully restored.
        """
        _, headers = self.login("creator")

        # Create canonical cluster
        res = self._decide(headers, self.ent1.id, self.ent2.id, "positive")
        canonical_id = res.json["canonical_id"]

        # Undecide E1→NK-*
        res = self._decide(headers, self.ent1.id, canonical_id, "no_judgement")
        assert res.status_code == 200

        # Re-decide E1→NK-* as POSITIVE
        res = self._decide(headers, self.ent1.id, canonical_id, "positive")
        assert res.status_code == 200, res.json
        # Should return the same NK-* canonical
        assert res.json["canonical_id"] == canonical_id, (
            f"Expected same canonical {canonical_id}, "
            f"got {res.json['canonical_id']}"
        )

        # Both entities resolve to the original canonical again
        resolver = get_resolver()
        assert resolver.get_canonical(self.ent1.id) == canonical_id
        assert resolver.get_canonical(self.ent2.id) == canonical_id

        # Canonical endpoint returns the restored cluster
        res = self.client.get(f"/api/2/canonical/{canonical_id}", headers=headers)
        assert res.status_code == 200, res.json
        entity_ids = {e["id"] for e in res.json["entities"]}
        assert entity_ids == {self.ent1.id, self.ent2.id}

        # Both edges are POSITIVE again
        active_edges = list(scan_edges([]))
        edges_by_entity = {}
        for edge in active_edges:
            ids = {edge.source, edge.target}
            if canonical_id in ids:
                other = (ids - {canonical_id}).pop()
                edges_by_entity[other] = edge.judgement
        assert edges_by_entity.get(self.ent1.id) == "positive", edges_by_entity
        assert edges_by_entity.get(self.ent2.id) == "positive", edges_by_entity

        # Entity detail endpoints return canonical_id again
        self._assert_entity_canonical_id(headers, self.ent1.id, canonical_id)
        self._assert_entity_canonical_id(headers, self.ent2.id, canonical_id)

    def test_undecide_then_negative_kills_canonical(self):
        """After decide E1=E2, undecide E1→NK-*, then NEGATIVE E2→NK-*.

        Both edges to NK-* are now non-POSITIVE, so the canonical is dead:
        - E1→NK-* is NO_JUDGEMENT
        - E2→NK-* is NEGATIVE
        - Neither entity resolves to NK-*
        - Canonical endpoint returns 404
        """
        _, headers = self.login("creator")

        # Create canonical cluster
        res = self._decide(headers, self.ent1.id, self.ent2.id, "positive")
        canonical_id = res.json["canonical_id"]

        # Undecide E1→NK-*
        res = self._decide(headers, self.ent1.id, canonical_id, "no_judgement")
        assert res.status_code == 200

        # Negative E2→NK-*
        res = self._decide(headers, self.ent2.id, canonical_id, "negative")
        assert res.status_code == 200, res.json

        # Neither entity resolves to the canonical anymore
        resolver = get_resolver()
        assert resolver.get_canonical(self.ent1.id) == self.ent1.id
        assert resolver.get_canonical(self.ent2.id) == self.ent2.id

        # Edge state
        active_edges = list(scan_edges([]))
        edges_by_entity = {}
        for edge in active_edges:
            ids = {edge.source, edge.target}
            if canonical_id in ids:
                other = (ids - {canonical_id}).pop()
                edges_by_entity[other] = edge.judgement
        assert edges_by_entity.get(self.ent1.id) == "no_judgement", edges_by_entity
        assert edges_by_entity.get(self.ent2.id) == "negative", edges_by_entity

        # Canonical endpoint returns 404
        res = self.client.get(f"/api/2/canonical/{canonical_id}", headers=headers)
        assert res.status_code == 404, res.json

        # Entity detail endpoints should not return canonical_id
        self._assert_entity_canonical_id(headers, self.ent1.id, None)
        self._assert_entity_canonical_id(headers, self.ent2.id, None)

    def test_add_entity_directly_to_canonical(self):
        """Decide E1=E2, then decide E3→NK-* to add E3 to the cluster.

        This is the "add to cluster" flow: instead of E2=E3 (transitive),
        the user directly decides E3 = NK-* (the canonical ID).
        """
        _, headers = self.login("creator")

        # Create canonical cluster from E1=E2
        res = self._decide(headers, self.ent1.id, self.ent2.id, "positive")
        canonical_id = res.json["canonical_id"]

        # Add E3 directly to the cluster via E3→NK-*
        res = self._decide(headers, self.ent3.id, canonical_id, "positive")
        assert res.status_code == 200, res.json
        # Should return the same NK-* canonical
        assert res.json["canonical_id"] == canonical_id, (
            f"Expected same canonical {canonical_id}, "
            f"got {res.json['canonical_id']}"
        )

        # All three entities resolve to the same canonical
        resolver = get_resolver()
        assert resolver.get_canonical(self.ent1.id) == canonical_id
        assert resolver.get_canonical(self.ent2.id) == canonical_id
        assert resolver.get_canonical(self.ent3.id) == canonical_id

        # Canonical endpoint returns cluster with all 3 entities
        res = self.client.get(f"/api/2/canonical/{canonical_id}", headers=headers)
        assert res.status_code == 200, res.json
        entity_ids = {e["id"] for e in res.json["entities"]}
        assert entity_ids == {self.ent1.id, self.ent2.id, self.ent3.id}

        # 3 active POSITIVE edges: E1→NK-*, E2→NK-*, E3→NK-*
        active_edges = list(scan_edges([]))
        canonical_edges = [
            e for e in active_edges if canonical_id in {e.source, e.target}
        ]
        assert len(canonical_edges) == 3, [
            (e.source, e.target, e.judgement) for e in canonical_edges
        ]
        members = set()
        for edge in canonical_edges:
            assert edge.judgement == "positive", edge
            other = ({edge.source, edge.target} - {canonical_id}).pop()
            members.add(other)
        assert members == {self.ent1.id, self.ent2.id, self.ent3.id}

        # Entity detail endpoints return canonical_id for all 3
        self._assert_entity_canonical_id(headers, self.ent1.id, canonical_id)
        self._assert_entity_canonical_id(headers, self.ent2.id, canonical_id)
        self._assert_entity_canonical_id(headers, self.ent3.id, canonical_id)

        # Similar endpoint: each entity should see the other 2 with positive judgement
        for ent in [self.ent1, self.ent2, self.ent3]:
            others = {self.ent1.id, self.ent2.id, self.ent3.id} - {ent.id}
            res = self.client.get(f"/api/2/entities/{ent.id}/similar", headers=headers)
            assert res.status_code == 200, res.json
            similar_by_id = {
                r["entity"]["id"]: r["judgement"] for r in res.json["results"]
            }
            for other_id in others:
                assert other_id in similar_by_id, (
                    f"Entity {ent.id}: expected {other_id} in similar results, "
                    f"got {list(similar_by_id.keys())}"
                )
                assert similar_by_id[other_id] == "positive", (
                    f"Entity {ent.id} → {other_id}: expected positive, "
                    f"got {similar_by_id[other_id]}"
                )

    def test_undecide_one_from_three_entity_cluster(self):
        """3-entity cluster: undecide E1→NK-*, cluster shrinks to E2+E3."""
        _, headers = self.login("creator")

        # Build 3-entity cluster: E1=E2, then E3→NK-*
        res = self._decide(headers, self.ent1.id, self.ent2.id, "positive")
        canonical_id = res.json["canonical_id"]
        res = self._decide(headers, self.ent3.id, canonical_id, "positive")
        assert res.status_code == 200

        # Undecide E1→NK-*
        res = self._decide(headers, self.ent1.id, canonical_id, "no_judgement")
        assert res.status_code == 200

        # E1 no longer in cluster, E2 and E3 still are
        resolver = get_resolver()
        assert resolver.get_canonical(self.ent1.id) == self.ent1.id
        assert resolver.get_canonical(self.ent2.id) == canonical_id
        assert resolver.get_canonical(self.ent3.id) == canonical_id

        # Canonical endpoint still returns a valid cluster (2 entities)
        res = self.client.get(f"/api/2/canonical/{canonical_id}", headers=headers)
        assert res.status_code == 200, res.json
        entity_ids = {e["id"] for e in res.json["entities"]}
        assert entity_ids == {self.ent2.id, self.ent3.id}

        # E1 no longer has a canonical cluster
        res = self.client.get(
            f"/api/2/entities/{self.ent1.id}/canonical", headers=headers
        )
        assert res.status_code == 404, res.json

        # Entity detail: E1 has no canonical_id, E2 and E3 still do
        self._assert_entity_canonical_id(headers, self.ent1.id, None)
        self._assert_entity_canonical_id(headers, self.ent2.id, canonical_id)
        self._assert_entity_canonical_id(headers, self.ent3.id, canonical_id)

    def test_decide_entity_already_in_cluster(self):
        """Decide A=B (creates NK-*), then decide A=C.

        C should join the existing NK-* cluster. No direct A→C POSITIVE edge
        should exist – only entity→NK-* edges.
        """
        _, headers = self.login("creator")

        # Create cluster: A=B → NK-*
        res = self._decide(headers, self.ent1.id, self.ent2.id, "positive")
        canonical_id = res.json["canonical_id"]

        # Decide A=C – should add C to the existing NK-* cluster
        res = self._decide(headers, self.ent1.id, self.ent3.id, "positive")
        assert res.status_code == 200, res.json
        # Should return the same NK-* canonical
        assert res.json["canonical_id"] == canonical_id, (
            f"Expected same canonical {canonical_id}, "
            f"got {res.json['canonical_id']}"
        )

        # All three resolve to the same canonical
        resolver = get_resolver()
        assert resolver.get_canonical(self.ent1.id) == canonical_id
        assert resolver.get_canonical(self.ent2.id) == canonical_id
        assert resolver.get_canonical(self.ent3.id) == canonical_id

        # Verify edges: only entity→NK-* edges, no direct entity→entity POSITIVE
        active_edges = list(scan_edges([]))
        for edge in active_edges:
            if edge.judgement == "positive":
                ids = {edge.source, edge.target}
                assert canonical_id in ids, (
                    f"POSITIVE edge between non-canonical IDs: "
                    f"{edge.source} → {edge.target}"
                )

        # Exactly 3 canonical POSITIVE edges
        canonical_edges = [
            e
            for e in active_edges
            if canonical_id in {e.source, e.target} and e.judgement == "positive"
        ]
        assert len(canonical_edges) == 3, [
            (e.source, e.target, e.judgement) for e in canonical_edges
        ]
        members = {
            ({e.source, e.target} - {canonical_id}).pop() for e in canonical_edges
        }
        assert members == {self.ent1.id, self.ent2.id, self.ent3.id}

        # Canonical endpoint shows all 3
        res = self.client.get(f"/api/2/canonical/{canonical_id}", headers=headers)
        assert res.status_code == 200, res.json
        entity_ids = {e["id"] for e in res.json["entities"]}
        assert entity_ids == {self.ent1.id, self.ent2.id, self.ent3.id}

        # Entity detail endpoints
        self._assert_entity_canonical_id(headers, self.ent1.id, canonical_id)
        self._assert_entity_canonical_id(headers, self.ent2.id, canonical_id)
        self._assert_entity_canonical_id(headers, self.ent3.id, canonical_id)
