from sqlalchemy import select

from aleph.logic.aggregator import get_aggregator
from aleph.logic.profiles import ORIGIN as PROFILE_ORIGIN
from aleph.logic.profiles import collection_profiles, decide_pairwise, profile_fragments
from aleph.model import Judgement
from aleph.tests.util import TestCase


class ProfileTestCase(TestCase):
    def test_decide_xref(self):
        w = self.create_user("user")
        coll = self.create_collection()
        a1 = {"id": "a1", "schema": "Person"}
        a2 = {"id": "a2", "schema": "Person"}
        profile_t1 = decide_pairwise(
            coll, a1, coll, a2, judgement=Judgement.POSITIVE, authz=w
        )
        assert profile_t1.collection_id == coll.id, profile_t1
        assert len(profile_t1.items().all()) == 2, profile_t1
        assert all(
            e.judgement == Judgement.POSITIVE and e.entity_id in ("a1", "a2")
            for e in profile_t1.items()
        )

        b1 = {"id": "b1", "schema": "Person"}
        profile_t2 = decide_pairwise(
            coll, a1, coll, b1, judgement=Judgement.NEGATIVE, authz=w
        )
        assert profile_t1.id == profile_t2.id, (profile_t1, profile_t2)
        assert len(profile_t2.items().all()) == 3, profile_t2
        assert all(
            (
                e.judgement == Judgement.POSITIVE
                if e.entity_id.startswith("a")
                else Judgement.NEGATIVE
            )
            for e in profile_t2.items()
        )

        b2 = {"id": "b2", "schema": "Person"}
        profile_t3 = decide_pairwise(
            coll, b1, coll, b2, judgement=Judgement.NEGATIVE, authz=w
        )
        assert profile_t1.id != profile_t3.id != profile_t2.id

        profile_t4 = decide_pairwise(
            coll, a1, coll, b1, judgement=Judgement.UNSURE, authz=w
        )
        assert profile_t4.id == profile_t2.id

    def test_collection_profiles(self):
        w = self.create_user("user")
        coll = self.create_collection()
        a1 = {"id": "a1", "schema": "Person"}
        a2 = {"id": "a2", "schema": "Person"}
        for judgement in Judgement:
            decide_pairwise(coll, a1, coll, a2, judgement=judgement, authz=w)
            result = list(collection_profiles(coll.id))
            assert len(result) == 1, len(result)
            profile, items = result[0]
            assert profile.collection_id == coll.id, profile.collection_id
            if judgement != Judgement.NO_JUDGEMENT:
                assert len(items) == 2, (judgement, len(items))
                assert [r == judgement for r in items]

        result = list(collection_profiles(coll.id, deleted=True))
        assert len(result) == 1, len(result)
        profile, items = result[0]
        assert profile.collection_id == coll.id, profile.collection_id
        assert len(items) == len(Judgement), len(items)

        decide_pairwise(coll, a1, coll, a2, judgement=Judgement.NEGATIVE, authz=w)
        result = list(collection_profiles(coll.id, judgements=[Judgement.POSITIVE]))
        assert len(result) == 1, len(result)
        profile, items = result[0]
        assert len(items) == 1
        assert items[0].entity_id == "a1"

    def _profile_stubs(self, coll):
        """Map entity_id -> profile_id for the profile stubs in the aggregator."""
        aggregator = get_aggregator(coll)
        table = aggregator.table
        query = select(table.c.id, table.c.entity).where(
            table.c.origin == PROFILE_ORIGIN
        )
        with aggregator.store.engine.connect() as conn:
            rows = conn.execute(query).fetchall()
        return {row.id: row.entity["profile_id"] for row in rows}

    def test_profile_fragments_keep_other_entities(self):
        # https://github.com/openaleph/openaleph/issues/146
        w = self.create_user("user")
        coll = self.create_collection()
        a1 = {"id": "a1", "schema": "Person"}
        a2 = {"id": "a2", "schema": "Person"}
        b1 = {"id": "b1", "schema": "Person"}
        b2 = {"id": "b2", "schema": "Person"}
        profile_a = decide_pairwise(
            coll, a1, coll, a2, judgement=Judgement.POSITIVE, authz=w
        )
        profile_b = decide_pairwise(
            coll, b1, coll, b2, judgement=Judgement.POSITIVE, authz=w
        )
        assert profile_a.id != profile_b.id

        # Deciding on b1/b2 must not drop the stubs written for a1/a2.
        stubs = self._profile_stubs(coll)
        assert stubs == {
            "a1": profile_a.id,
            "a2": profile_a.id,
            "b1": profile_b.id,
            "b2": profile_b.id,
        }, stubs

    def test_profile_fragments_remove_only_reverted_entity(self):
        w = self.create_user("user")
        coll = self.create_collection()
        a1 = {"id": "a1", "schema": "Person"}
        a2 = {"id": "a2", "schema": "Person"}
        a3 = {"id": "a3", "schema": "Person"}
        profile = decide_pairwise(
            coll, a1, coll, a2, judgement=Judgement.POSITIVE, authz=w
        )
        decide_pairwise(coll, a1, coll, a3, judgement=Judgement.POSITIVE, authz=w)
        assert set(self._profile_stubs(coll)) == {"a1", "a2", "a3"}

        # Reverting a2 removes its stub only.
        decide_pairwise(coll, a1, coll, a2, judgement=Judgement.NEGATIVE, authz=w)
        stubs = self._profile_stubs(coll)
        assert stubs == {"a1": profile.id, "a3": profile.id}, stubs

    def test_profile_fragments_full_rebuild(self):
        w = self.create_user("user")
        coll = self.create_collection()
        a1 = {"id": "a1", "schema": "Person"}
        a2 = {"id": "a2", "schema": "Person"}
        b1 = {"id": "b1", "schema": "Person"}
        b2 = {"id": "b2", "schema": "Person"}
        decide_pairwise(coll, a1, coll, a2, judgement=Judgement.POSITIVE, authz=w)
        decide_pairwise(coll, b1, coll, b2, judgement=Judgement.POSITIVE, authz=w)

        # Without an entity_id, all stubs are rebuilt from the profiles.
        aggregator = get_aggregator(coll)
        aggregator.delete(origin=PROFILE_ORIGIN)
        assert self._profile_stubs(coll) == {}
        profile_fragments(coll, aggregator)
        assert set(self._profile_stubs(coll)) == {"a1", "a2", "b1", "b2"}
