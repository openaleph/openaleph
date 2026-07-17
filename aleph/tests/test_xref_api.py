from aleph.core import db
from aleph.index.util import index_entity
from aleph.index.xref import delete_xref
from aleph.logic import xref
from aleph.logic.xref.resolver import get_resolver
from aleph.tests.util import TestCase, get_caption


class XrefApiTestCase(TestCase):
    def setUp(self):
        super(XrefApiTestCase, self).setUp()
        delete_xref()
        xref.SCORE_CUTOFF = 0.01
        self.creator = self.create_user(foreign_id="creator")
        self.outsider = self.create_user(foreign_id="outsider")

        # First public collection and entities
        self.residents = self.create_collection(
            label="Residents of Habitat Ring",
            foreign_id="test_residents",
            creator=self.creator,
        )

        self.ent = self.create_entity(
            {"schema": "Person", "properties": {"name": "Elim Garak"}}, self.residents
        )

        self.ent2 = self.create_entity(
            {"schema": "Person", "properties": {"name": "Leeta"}}, self.residents
        )

        # Second public collection and entities
        self.dabo = self.create_collection(
            label="Dabo Girls", foreign_id="test_dabo", creator=self.creator
        )
        self.grant_publish(self.dabo)

        self.ent3 = self.create_entity(
            {"schema": "Person", "properties": {"name": "MPella"}}, self.dabo
        )

        self.ent4 = self.create_entity(
            {"schema": "Person", "properties": {"name": "Leeta"}}, self.dabo
        )

        self.ent5 = self.create_entity(
            {"schema": "Person", "properties": {"name": "Mardah"}}, self.dabo
        )

        # Private collection and entities
        self.obsidian = self.create_collection(
            label="Obsidian Order", foreign_id="test_obsidian", creator=self.creator
        )

        self.ent6 = self.create_entity(
            {"schema": "Person", "properties": {"name": "Elim Garak"}}, self.obsidian
        )

        self.ent7 = self.create_entity(
            {"schema": "Person", "properties": {"name": "Enabran Tain"}}, self.obsidian
        )

        db.session.commit()
        index_entity(self.ent)
        index_entity(self.ent2)
        index_entity(self.ent3)
        index_entity(self.ent4)
        index_entity(self.ent5)
        index_entity(self.ent6)
        index_entity(self.ent7)

    def test_export(self):
        xref.xref_collection(self.residents)
        url = "/api/2/collections/%s/xref.xlsx" % self.obsidian.id
        res = self.client.post(url)
        assert res.status_code == 403, res

        _, headers = self.login(foreign_id="creator")
        res = self.client.post(url, headers=headers)
        assert res.status_code == 202, res

    def test_matches(self):
        xref.xref_collection(self.residents)
        url = "/api/2/collections/%s/xref" % self.residents.id
        # Not logged in
        res = self.client.get(url)
        assert res.status_code == 403, res

        self.grant_publish(self.residents)
        res = self.client.get(url)
        assert res.status_code == 200, res
        assert res.json["total"] == 1, res.json
        res0 = res.json["results"][0]
        assert "Leeta" in get_caption(res0["entity"])
        assert "Garak" not in get_caption(res0["entity"])
        assert "Tain" not in get_caption(res0["match"])
        assert "MPella" not in get_caption(res0["match"])

        # Logged in as outsider (restricted)
        _, headers = self.login("outsider")

        res = self.client.get(url, headers=headers)
        assert res.status_code == 200, res
        assert res.json["total"] == 1, res.json
        res0 = res.json["results"][0]
        assert "Leeta" in get_caption(res0["entity"])
        assert "Garak" not in get_caption(res0["entity"])
        assert "Tain" not in get_caption(res0["match"])
        assert "MPella" not in get_caption(res0["match"])

        # Logged in as creator (all access)
        _, headers = self.login("creator")

        res = self.client.get(url, headers=headers)
        assert res.status_code == 200, res
        assert res.json["total"] == 2, res.json
        res0 = res.json["results"][0]
        assert "Garak" in get_caption(res0["entity"])
        assert "Leeta" not in get_caption(res0["entity"])
        assert "Tain" not in get_caption(res0["match"])
        assert "MPella" not in get_caption(res0["match"])
        res1 = res.json["results"][1]
        assert "Leeta" in get_caption(res1["entity"])
        assert "Garak" not in get_caption(res1["entity"])
        assert "Tain" not in get_caption(res1["match"])
        assert "MPella" not in get_caption(res1["match"])

    def test_orientation(self):
        """entity (left) should always belong to the perspective collection."""
        delete_xref()
        xref.xref_collection(self.residents)
        self.grant_publish(self.residents)
        _, headers = self.login("creator")

        # Query from residents' perspective
        residents_id = str(self.residents.id)
        url = "/api/2/collections/%s/xref" % self.residents.id
        res = self.client.get(url, headers=headers)
        assert res.status_code == 200, res
        for result in res.json["results"]:
            assert (
                result["entity"]["collection"]["id"] == residents_id
            ), "entity should belong to perspective collection (residents)"
            assert (
                result["match"]["collection"]["id"] != residents_id
            ), "match should belong to the other collection"

        # Query from dabo's perspective — orientation should flip
        dabo_id = str(self.dabo.id)
        url = "/api/2/collections/%s/xref" % self.dabo.id
        res = self.client.get(url, headers=headers)
        assert res.status_code == 200, res
        for result in res.json["results"]:
            assert (
                result["entity"]["collection"]["id"] == dabo_id
            ), "entity should belong to perspective collection (dabo)"
            assert (
                result["match"]["collection"]["id"] != dabo_id
            ), "match should belong to the other collection"

    def test_create_matches(self):
        url = "/api/2/collections/%s/xref" % self.residents.id
        res = self.client.post(url)
        assert res.status_code == 403, res

        _, headers = self.login("outsider")
        res = self.client.post(url, headers=headers)
        assert res.status_code == 403, res

        _, headers = self.login("creator")
        res = self.client.post(url, headers=headers)
        assert res.status_code == 202, res

        res = self.client.get(url, headers=headers)
        assert res.status_code == 200, res
        assert res.json["total"] == 2, res.json

    def test_decide(self):
        _, headers = self.login("creator")
        url = "/api/2/collections/%s/xref" % self.residents.id
        res = self.client.post(url, headers=headers)
        assert res.status_code == 202, res

        res = self.client.get(url, headers=headers)
        assert res.json["total"] == 2, res.json
        xref = res.json["results"][0]
        assert xref.get("judgement") == "no_judgement", xref

        decide_url = "/api/2/xref/_decide"
        res = self.client.post(
            decide_url,
            headers=headers,
            json={
                "judgement": "positive",
                "entity_id": xref["entity"]["id"],
                "match_id": xref["match"]["id"],
            },
        )
        assert res.status_code == 200, res.json
        assert "canonical_id" in res.json, res.json

        # After a positive decision, query with show_decided to see it
        res = self.client.get(url + "?filter:judgement=positive", headers=headers)

        decide_url = "/api/2/xref/_decide"
        res = self.client.post(
            decide_url,
            headers=headers,
            json={
                "judgement": "negative",
                "entity_id": xref["entity"]["id"],
                "match_id": xref["match"]["id"],
            },
        )
        assert res.status_code == 200, res.json

    def test_canonical_transitivity(self):
        """Deciding A=B and B=C should transitively make A=C."""
        xref.xref_collection(self.residents)
        _, headers = self.login("creator")
        decide_url = "/api/2/xref/_decide"

        # A=Garak(residents), B=Garak(obsidian), C=Leeta(residents)
        a_id = self.ent.id
        b_id = self.ent6.id
        c_id = self.ent2.id

        # Decide A=B
        res = self.client.post(
            decide_url,
            headers=headers,
            json={"judgement": "positive", "entity_id": a_id, "match_id": b_id},
        )
        assert res.status_code == 200, res.json

        # Decide B=C
        res = self.client.post(
            decide_url,
            headers=headers,
            json={"judgement": "positive", "entity_id": b_id, "match_id": c_id},
        )
        assert res.status_code == 200, res.json

        # A, B, C should all resolve to the same canonical
        resolver = get_resolver()
        canon_a = resolver.get_canonical(a_id)
        canon_b = resolver.get_canonical(b_id)
        canon_c = resolver.get_canonical(c_id)
        assert canon_a == canon_b, (canon_a, canon_b)
        assert canon_b == canon_c, (canon_b, canon_c)
