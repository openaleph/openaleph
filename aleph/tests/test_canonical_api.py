from aleph.core import db
from aleph.index.util import index_entity
from aleph.logic import xref
from aleph.tests.util import TestCase
from aleph.util import make_entity_proxy


class CanonicalApiTestCase(TestCase):
    def setUp(self):
        super(CanonicalApiTestCase, self).setUp()
        self.rolex = self.create_user(foreign_id="rolex")
        self.col1 = self.create_collection(creator=self.rolex)

        ent1 = {
            "schema": "LegalEntity",
            "properties": {
                "name": "Donald Trump",
                "address": "721 Fifth Avenue, New York, NY",
                "phone": "+12024561414",
            },
        }
        self.ent1 = self.create_entity(ent1, self.col1)
        index_entity(self.ent1)

        self.col2 = self.create_collection(creator=self.rolex)
        self.grant_publish(self.col2)
        ent2 = {
            "schema": "Person",
            "properties": {
                "name": "Donald J. Trump",
                "position": "45th President of the US",
                "phone": "+12024561414",
            },
        }
        self.ent2 = self.create_entity(ent2, self.col2)
        index_entity(self.ent2)

        ent_false = {
            "schema": "LegalEntity",
            "properties": {"name": "Donald Trump, Jr", "email": "junior@trump.org"},
        }
        self.ent_false = self.create_entity(ent_false, self.col2)
        index_entity(self.ent_false)

        self.col3 = self.create_collection(creator=self.rolex)
        ent3 = {
            "schema": "LegalEntity",
            "properties": {"name": "Donald John Trump", "birthDate": "1964"},
        }
        self.ent3 = self.create_entity(ent3, self.col3)
        index_entity(self.ent3)

        db.session.commit()

        # Generate xref edges so the decide endpoint can find the entities
        xref.xref_collection(self.col1)

        # Decide: ent1 = ent2 (positive)
        _, self.headers = self.login(foreign_id="rolex")
        decide_url = "/api/2/xref/_decide"
        res = self.client.post(
            decide_url,
            headers=self.headers,
            json={
                "judgement": "positive",
                "entity_id": self.ent1.id,
                "match_id": self.ent2.id,
            },
        )
        assert res.status_code == 200, res.json
        self.canonical_id = res.json["canonical_id"]

    def test_canonical_view(self):
        res = self.client.get("/api/2/canonical/bananana")
        assert res.status_code == 404, res.json

        url = "/api/2/canonical/%s" % self.canonical_id
        res = self.client.get(url)
        assert res.status_code == 404, res.status_code

        _, headers = self.login(foreign_id="rolex")
        res = self.client.get(url, headers=headers)
        assert res.status_code == 200, res.json
        merged = make_entity_proxy(res.json.get("merged"))
        assert merged.schema.name == "Person", merged.schema
        assert "Fifth" in merged.first("address"), merged.to_dict()
        assert not merged.has("email"), merged.to_dict()

    def test_entity_canonical(self):
        """Resolve an entity to its canonical cluster."""
        url = "/api/2/entities/%s/canonical" % self.ent1.id
        _, headers = self.login(foreign_id="rolex")
        res = self.client.get(url, headers=headers)
        assert res.status_code == 200, res.json
        assert res.json["merged"]["id"] == self.canonical_id, res.json

        # ent2 resolves to the same canonical
        url = "/api/2/entities/%s/canonical" % self.ent2.id
        res = self.client.get(url, headers=headers)
        assert res.status_code == 200, res.json
        assert res.json["merged"]["id"] == self.canonical_id, res.json

    def test_canonical_tags(self):
        url = "/api/2/canonical/%s/tags" % self.canonical_id
        res = self.client.get(url)
        assert res.status_code == 404, res.json
        _, headers = self.login(foreign_id="rolex")
        res = self.client.get(url, headers=headers)
        assert res.status_code == 200, res.json
        assert res.json["total"] == 1, res.json
        assert res.json["results"][0]["field"] == "phones", res.json

    def test_canonical_similar(self):
        url = "/api/2/canonical/%s/similar" % self.canonical_id
        res = self.client.get(url)
        assert res.status_code == 404, res.json
        _, headers = self.login(foreign_id="rolex")
        res = self.client.get(url, headers=headers)
        assert res.status_code == 200, res.json

    def test_canonical_expand(self):
        usg = {
            "schema": "PublicBody",
            "properties": {"name": "US Government"},
        }
        usg = self.create_entity(usg, self.col2)
        index_entity(usg)
        membership = {
            "schema": "Membership",
            "properties": {
                "organization": usg.id,
                "member": self.ent2.id,
                "role": "Chief executive",
            },
        }
        membership = self.create_entity(membership, self.col2)
        index_entity(membership)
        passport = {
            "schema": "Passport",
            "properties": {"holder": self.ent1.id},
        }
        passport = self.create_entity(passport, self.col1)
        index_entity(passport)

        url = "/api/2/canonical/%s/expand" % self.canonical_id
        res = self.client.get(url)
        assert res.status_code == 404, res.json
        _, headers = self.login(foreign_id="rolex")
        res = self.client.get(url, headers=headers)
        assert res.status_code == 200, res.json
        assert res.json["total"] == 2, res.json
