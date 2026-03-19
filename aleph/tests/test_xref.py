import json
from unittest import skip  # noqa

from aleph.authz import Authz
from aleph.core import db
from aleph.index.xref import iter_edges
from aleph.logic.xref import xref_collection
from aleph.tests.util import JSON, TestCase


class XrefTestCase(TestCase):
    def setUp(self):
        super(XrefTestCase, self).setUp()
        self.user = self.create_user()
        self.coll_a = self.create_collection(creator=self.user)
        self.coll_b = self.create_collection(creator=self.user)
        self.coll_c = self.create_collection(creator=self.user)
        db.session.commit()
        self.authz = Authz.from_role(self.user)

        _, headers = self.login(foreign_id=self.user.foreign_id)
        url = "/api/2/entities"

        entity1 = {
            "schema": "Person",
            "collection_id": str(self.coll_a.id),
            "properties": {"name": "Carlos Danger", "nationality": "US"},
        }
        self.entity1 = self.client.post(
            url,
            data=json.dumps(entity1),
            headers=headers,
            content_type=JSON,
        )
        entity2 = {
            "schema": "Person",
            "collection_id": str(self.coll_b.id),
            "properties": {"name": "Carlos Danger", "nationality": "US"},
        }
        self.entity2 = self.client.post(
            url,
            data=json.dumps(entity2),
            headers=headers,
            content_type=JSON,
        )
        entity3 = {
            "schema": "LegalEntity",
            "collection_id": str(self.coll_b.id),
            "properties": {"name": "Carlos Danger", "country": "GB"},
        }
        self.entity3 = self.client.post(
            url,
            data=json.dumps(entity3),
            headers=headers,
            content_type=JSON,
        )
        entity4 = {
            "schema": "Person",
            "collection_id": str(self.coll_b.id),
            "properties": {"name": "Pure Risk", "nationality": "US"},
        }
        self.entity4 = self.client.post(
            url,
            data=json.dumps(entity4),
            headers=headers,
            content_type=JSON,
        )

        entity5 = {
            "schema": "LegalEntity",
            "collection_id": str(self.coll_c.id),
            "properties": {"name": "Carlos Danger", "country": "GB"},
        }
        self.entity5 = self.client.post(
            url,
            data=json.dumps(entity5),
            headers=headers,
            content_type=JSON,
        )

    def test_xref(self):
        xref_collection(self.coll_a)
        edges = list(iter_edges(self.coll_a, self.authz.search_auth))

        # Collect all entity IDs referenced in match edges
        entity_ids = set()
        collection_ids = set()
        for edge in edges:
            assert edge.source != edge.target
            entity_ids.add(edge.source)
            entity_ids.add(edge.target)
            collection_ids.add(edge.source_collection_id)
            collection_ids.add(edge.target_collection_id)
            # All should be suggestions
            assert edge.judgement == "no_judgement", edge

        entity1_id = self.entity1.get_json().get("id")
        entity2_id = self.entity2.get_json().get("id")
        entity3_id = self.entity3.get_json().get("id")
        entity5_id = self.entity5.get_json().get("id")

        # entity1 (coll_a, Carlos Danger) should match entity2, entity3, entity5
        assert entity1_id in entity_ids, entity_ids
        assert entity2_id in entity_ids, entity_ids
        assert entity3_id in entity_ids, entity_ids
        assert entity5_id in entity_ids, entity_ids

        assert not collection_ids - {self.coll_a.id, self.coll_b.id, self.coll_c.id}
