from aleph.index.collections import delete_entities
from aleph.logic.collections import delete_collection, reindex_collection
from aleph.tests.util import TestCase


class IndexTestCase(TestCase):
    def test_delete_collection(self):
        self.load_fixtures()
        url = "/api/2/entities?filter:schemata=Thing&q=kwazulu"
        res = self.client.get(url)
        assert res.json["total"] == 1, res.json
        delete_collection(self.public_coll)
        res = self.client.get(url)
        assert res.json["total"] == 0, res.json

    def test_collection_taggable_default(self):
        role, _ = self.login()
        collection = self.create_collection(role, label="Test Collection")

        # Default taggable should be False
        assert collection.taggable is False

        # Test serialization includes taggable field
        data = collection.to_dict()
        assert "taggable" in data
        assert data["taggable"] is False

    def test_reindex_collection_queue_batches(self):
        self.load_fixtures()
        _, headers = self.login()
        # Use private_coll which has 22 entities from fixtures
        # Delete all entities from the index first
        res = self.client.get(
            f"/api/2/entities?filter:collection_id={self.private_coll.id}",
            headers=headers,
        )
        assert res.json["total"] == 22, res.json
        delete_entities(self.private_coll.id, sync=True)

        # Verify entities are gone from the index
        res = self.client.get(
            f"/api/2/entities?filter:collection_id={self.private_coll.id}",
            headers=headers,
        )
        assert res.json["total"] == 0, res.json

        # Test reindexing with queue_batches=True and batch_size=10
        # This will create 3 batches
        reindex_collection(
            self.private_coll, queue_batches=True, batch_size=10, sync=True
        )

        # Verify collection has been reindexed
        res = self.client.get(
            f"/api/2/entities?filter:collection_id={self.private_coll.id}",
            headers=headers,
        )
        assert res.json["total"] == 22, res.json
