from aleph.logic.collections import delete_collection
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
