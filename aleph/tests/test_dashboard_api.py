from unittest.mock import patch

from aleph.model import CollectionStatus
from aleph.tests.util import TestCase


class DashboardApiTestCase(TestCase):
    def setUp(self):
        super(DashboardApiTestCase, self).setUp()

    def test_index(self):
        res = self.client.get("/api/2/status")
        assert res.status_code == 403, res
        _, headers = self.login()
        res = self.client.get("/api/2/status", headers=headers)
        assert res.status_code == 200, res
        assert res.json.get("total") == 0, res.json
        _, headers = self.login(is_admin=True)
        res = self.client.get("/api/2/status", headers=headers)
        assert res.status_code == 200, res
        assert res.json.get("total") == 0, res.json
        assert "results" in res.json

    def test_status_embeds_collection(self):
        # Regression (82697f337): dropping inline_collection_data() left the
        # status payload without the serialized collection – the status UI
        # then rendered the dataset name ("collection_<id>") instead of the
        # label and lost its cancel button (gated on collection.writeable).
        _, headers = self.login(is_admin=True)
        collection = self.create_collection(label="Status Collection")
        status = CollectionStatus(name=f"collection_{collection.id}")
        with patch(
            "aleph.views.status_api.get_active_collections_status",
            return_value=iter([status]),
        ):
            res = self.client.get("/api/2/status", headers=headers)
        assert res.status_code == 200, res
        assert res.json["total"] == 1, res.json
        result = res.json["results"][0]
        assert result["collection"] is not None, result
        assert result["collection"]["label"] == "Status Collection", result
        assert result["collection"]["writeable"] is True, result
