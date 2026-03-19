"""
Test auth-filtered canonical cluster resolution directly against the resolver.

Tests the ElasticsearchResolver's auth filtering when traversing POSITIVE edges
to build canonical clusters. Specifically tests transitive chains (A=B, B=C)
where intermediate collections may not be readable by the user.

NK-* canonical edges aggregate all cluster collection_ids on the target side
(e.g., target_collection_id={colA, colB}). Because ES terms queries are
disjunctive (match if ANY value matches), the resolver-level get_canonical()
can still traverse through NK-* edges the user shouldn't fully see.
get_canonical_cluster() mitigates this: when only one referent is visible
after auth-filtered traversal, it falls back to the entity's own ID instead
of the NK-* canonical, preventing the opaque ID from leaking.
"""

from nomenklatura.judgement import Judgement

from aleph.authz import Authz
from aleph.core import db
from aleph.index.util import index_entity
from aleph.logic.xref.canonical import get_canonical_cluster
from aleph.logic.xref.resolver import get_resolver
from aleph.tests.util import TestCase


class CanonicalAuthTestCase(TestCase):
    """Test auth-filtered canonical cluster resolution (no API layer)."""

    def setUp(self):
        super().setUp()

        # Admin user (makes the decisions)
        self.admin = self.create_user(foreign_id="admin", is_admin=True)

        # 3 collections, each with one entity
        self.col_a = self.create_collection(
            foreign_id="col_a", label="Collection A", creator=self.admin
        )
        self.col_b = self.create_collection(
            foreign_id="col_b", label="Collection B", creator=self.admin
        )
        self.col_c = self.create_collection(
            foreign_id="col_c", label="Collection C", creator=self.admin
        )

        self.ent_a = self.create_entity(
            {"schema": "Person", "properties": {"name": "Alice Alpha"}},
            self.col_a,
        )
        self.ent_b = self.create_entity(
            {"schema": "Person", "properties": {"name": "Alice Bravo"}},
            self.col_b,
        )
        self.ent_c = self.create_entity(
            {"schema": "Person", "properties": {"name": "Alice Charlie"}},
            self.col_c,
        )

        index_entity(self.ent_a)
        index_entity(self.ent_b)
        index_entity(self.ent_c)
        db.session.commit()

        # Make decisions with admin-level resolver (no auth filtering)
        resolver = get_resolver(sync=True)

        # Decision 1: ent_a = ent_b → creates NK-* canonical
        canonical = resolver.decide(
            self.ent_a.id,
            self.ent_b.id,
            Judgement.POSITIVE,
            source_collection_id=self.col_a.id,
            target_collection_id=self.col_b.id,
        )
        self.canonical_id = canonical.id

        # Decision 2: ent_b = ent_c → extends the chain via ent_b→ent_c edge
        resolver.decide(
            self.ent_b.id,
            self.ent_c.id,
            Judgement.POSITIVE,
            source_collection_id=self.col_b.id,
            target_collection_id=self.col_c.id,
        )

        # Create test users
        self.user1 = self.create_user(foreign_id="user1")
        self.user2 = self.create_user(foreign_id="user2")

        # user1: full access (col_a, col_b, col_c)
        self.grant(self.col_a, self.user1, True, False)
        self.grant(self.col_b, self.user1, True, False)
        self.grant(self.col_c, self.user1, True, False)

        # user2: partial access (col_a, col_c — NOT col_b)
        self.grant(self.col_a, self.user2, True, False)
        self.grant(self.col_c, self.user2, True, False)

        Authz.flush()

    def _auth_for(self, role):
        return Authz.from_role(role).search_auth

    # -- Test case 1: Admin (is_admin=True) sees everything --

    def test_admin_canonical_resolves_same(self):
        """Admin: all 3 entities resolve to the same NK-* canonical."""
        auth = self._auth_for(self.admin)
        resolver = get_resolver(auth=auth, sync=True)

        canon_a = resolver.get_canonical(self.ent_a.id)
        canon_b = resolver.get_canonical(self.ent_b.id)
        canon_c = resolver.get_canonical(self.ent_c.id)
        assert (
            canon_a == canon_b == canon_c
        ), f"Admin should see unified canonical: {canon_a}, {canon_b}, {canon_c}"

    def test_admin_cluster_has_all_entities(self):
        """Admin: cluster contains all 3 entities and 3 collection_ids."""
        auth = self._auth_for(self.admin)
        cluster = get_canonical_cluster(self.ent_a.id, auth=auth)
        assert cluster is not None, "Admin cluster should not be None"

        entity_ids = {e.id for e in cluster["entities"]}
        assert self.ent_a.id in entity_ids
        assert self.ent_b.id in entity_ids
        assert self.ent_c.id in entity_ids
        assert len(cluster["collection_ids"]) == 3

    # -- Test case 2: User1 (has col_a, col_b, col_c) — full access --

    def test_user1_canonical_resolves_same(self):
        """User1 (full access): all 3 entities resolve to same canonical."""
        auth = self._auth_for(self.user1)
        resolver = get_resolver(auth=auth, sync=True)

        canon_a = resolver.get_canonical(self.ent_a.id)
        canon_b = resolver.get_canonical(self.ent_b.id)
        canon_c = resolver.get_canonical(self.ent_c.id)
        assert canon_a == canon_b == canon_c

    def test_user1_cluster_has_all_entities(self):
        """User1 (full access): full cluster with 3 entities, 3 collections."""
        auth = self._auth_for(self.user1)
        cluster = get_canonical_cluster(self.ent_a.id, auth=auth)
        assert cluster is not None

        entity_ids = {e.id for e in cluster["entities"]}
        assert len(entity_ids) == 3
        assert len(cluster["collection_ids"]) == 3

    # -- Test case 3: User2 (has col_a, col_c but NOT col_b) — chain broken --
    #
    # The resolver-level get_canonical() can still reach NK-* for ent_a due
    # to the disjunctive terms query on target_collection_id={colA, colB}.
    # But get_canonical_cluster() catches this: when only one referent is
    # visible, it falls back to entity_id. No entity data or NK-* ids leak.

    def test_user2_ent_a_no_cluster(self):
        """User2: ent_a should have no cluster.

        The resolver-level get_canonical() still reaches NK-* due to the
        disjunctive terms query on the ent_a→NK-* edge. But
        get_canonical_cluster() detects that only one referent is visible
        and returns None — a single entity is not a cluster.
        """
        auth = self._auth_for(self.user2)

        cluster = get_canonical_cluster(self.ent_a.id, auth=auth)
        assert cluster is None, (
            f"Expected no cluster for ent_a, got {len(cluster['entities'])} entities. "
            "Single-referent result should return None."
        )
        assert get_canonical_cluster(self.ent_b.id, auth=auth) is None
        assert get_canonical_cluster(self.ent_c.id, auth=auth) is None

    def test_user2_ent_c_no_canonical(self):
        """User2: ent_c should resolve to itself (no canonical visible).

        ent_b→ent_c has source_collection_id={colB}. User2 cannot read colB,
        so this edge should be invisible. ent_c should resolve to itself.
        """
        auth = self._auth_for(self.user2)
        resolver = get_resolver(auth=auth, sync=True)

        canon_c = resolver.get_canonical(self.ent_c.id)
        assert canon_c == self.ent_c.id, (
            f"Expected ent_c to resolve to itself, got {canon_c}. "
            "User2 should not see through col_b."
        )

    def test_user2_ent_b_no_canonical(self):
        """User2: ent_b should resolve to itself (can't read col_b)."""
        auth = self._auth_for(self.user2)
        resolver = get_resolver(auth=auth, sync=True)

        canon_b = resolver.get_canonical(self.ent_b.id)
        assert canon_b == self.ent_b.id, (
            f"Expected ent_b to resolve to itself, got {canon_b}. "
            "User2 cannot read col_b."
        )
