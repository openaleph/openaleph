from aleph.logic.discover import compute_collection_discovery
from aleph.logic.resolver import cache
from aleph.model.discover import CollectionDiscovery
from aleph.tests.util import TestCase


class DiscoveryApiTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.load_fixtures()

    def test_discover_unauthorized(self):
        """Test discovery endpoint without authentication."""
        url = f"/api/2/collections/{self.private_coll.id}/discover"
        res = self.client.get(url)
        assert res.status_code == 403, res

    def test_discover_not_found(self):
        """Test discovery endpoint with non-existent collection."""
        _, headers = self.login(is_admin=True)
        url = "/api/2/collections/99999/discover"
        res = self.client.get(url, headers=headers)
        assert res.status_code == 404, res

    def test_discover_login_access(self):
        """Test discovery endpoint with read access to collection."""
        _, headers = self.login(foreign_id="user_read_access")
        url = f"/api/2/collections/{self.private_coll.id}/discover"
        res = self.client.get(url, headers=headers)
        assert res.status_code == 200, res

    def test_discover_private_collection_with_access(self):
        """Test discovery endpoint on private collection with proper access."""
        _, headers = self.login(is_admin=True)
        url = f"/api/2/collections/{self.private_coll.id}/discover"

        # Clear cache to ensure fresh computation
        cid = str(self.private_coll.id)
        cache.invalidate(CollectionDiscovery, cid)

        res = self.client.get(url, headers=headers)
        assert res.status_code == 200, res
        CollectionDiscovery.model_validate(res.json)

        # Check response structure
        data = res.json
        assert "collection_id" in data
        assert data["collection_id"] == cid
        assert "peopleMentioned" in data
        assert "companiesMentioned" in data
        assert "locationMentioned" in data
        assert "namesMentioned" in data

        # Each field should be a list
        assert isinstance(data["peopleMentioned"], list)
        assert isinstance(data["companiesMentioned"], list)
        assert isinstance(data["locationMentioned"], list)
        assert isinstance(data["namesMentioned"], list)

    def test_discover_public_collection(self):
        """Test discovery endpoint on public collection."""
        # Public collection should be accessible without authentication
        url = f"/api/2/collections/{self.public_coll.id}/discover"

        # Clear cache to ensure fresh computation
        cid = str(self.public_coll.id)
        cache.invalidate(CollectionDiscovery, cid)

        res = self.client.get(url)
        assert res.status_code == 200, res
        CollectionDiscovery.model_validate(res.json)

        data = res.json
        assert data["collection_id"] == cid

    def test_discover_caching(self):
        """Test that discovery endpoint uses caching properly."""
        _, headers = self.login(is_admin=True)
        url = f"/api/2/collections/{self.private_coll.id}/discover"

        # Clear cache first
        cid = str(self.private_coll.id)
        cache.invalidate(CollectionDiscovery, cid)

        # First request should compute and cache
        res1 = self.client.get(url, headers=headers)
        assert res1.status_code == 200
        data1 = res1.json

        # Second request should use cache
        res2 = self.client.get(url, headers=headers)
        assert res2.status_code == 200
        data2 = res2.json

        # Results should be identical
        assert data1 == data2

    def test_discover_response_format(self):
        """Test that discovery response has correct format for significant terms."""
        _, headers = self.login(is_admin=True)
        url = f"/api/2/collections/{self.private_coll.id}/discover"

        # Pre-populate cache with test data to ensure consistent response
        cid = str(self.private_coll.id)
        cache.refresh(CollectionDiscovery, cid)

        res = self.client.get(url, headers=headers)
        assert res.status_code == 200

        data = res.json

        # If there are any significant terms, verify structure
        for category in [
            "peopleMentioned",
            "companiesMentioned",
            "locationMentioned",
            "namesMentioned",
        ]:
            if data[category]:
                for significant_term in data[category]:
                    # Each significant term should have a 'term' field
                    assert "term" in significant_term
                    assert "name" in significant_term["term"]
                    assert "count" in significant_term["term"]
                    # And the mentioned categories
                    assert "peopleMentioned" in significant_term
                    assert "companiesMentioned" in significant_term
                    assert "locationMentioned" in significant_term
                    assert "namesMentioned" in significant_term

    def test_discover_with_real_data(self):
        """Test discovery endpoint with actual fixture data computation."""
        _, headers = self.login(is_admin=True)
        url = f"/api/2/collections/{self.private_coll.id}/discover"
        cid = str(self.private_coll.id)

        # Clear cache to force computation on next refresh
        cache.invalidate(CollectionDiscovery, cid)

        # Use the real discovery computation
        discovery_result = compute_collection_discovery(self.private_coll.id)

        # Now test the API endpoint
        res = self.client.get(url, headers=headers)
        assert res.status_code == 200

        # The API should return the same data structure
        api_data = res.json
        expected_data = discovery_result.model_dump(mode="json")

        assert api_data["collection_id"] == expected_data["collection_id"]

        # Compare structure (content may vary based on Elasticsearch state)
        for category in [
            "peopleMentioned",
            "companiesMentioned",
            "locationMentioned",
            "namesMentioned",
        ]:
            assert isinstance(api_data[category], list)
            assert len(api_data[category]) == len(expected_data[category])

    def test_discover_content_type(self):
        """Test that discovery endpoint returns proper content type."""
        _, headers = self.login(is_admin=True)
        url = f"/api/2/collections/{self.private_coll.id}/discover"

        res = self.client.get(url, headers=headers)
        assert res.status_code == 200
        assert res.content_type == "application/json"

    def test_discover_different_collections(self):
        """Test discovery endpoint works with different collection types."""
        _, headers = self.login(is_admin=True)

        # Test private collection
        private_url = f"/api/2/collections/{self.private_coll.id}/discover"
        private_res = self.client.get(private_url, headers=headers)
        assert private_res.status_code == 200
        assert private_res.json["collection_id"] == str(self.private_coll.id)

        # Test public collection
        public_url = f"/api/2/collections/{self.public_coll.id}/discover"
        public_res = self.client.get(public_url, headers=headers)
        assert public_res.status_code == 200
        assert public_res.json["collection_id"] == str(self.public_coll.id)

        # Results should be different (different collections)
        assert private_res.json["collection_id"] != public_res.json["collection_id"]

    def test_discover_empty_collection(self):
        """Test discovery endpoint with empty collection."""
        _, headers = self.login(is_admin=True)

        # Create empty collection
        empty_coll = self.create_collection(
            foreign_id="empty_test",
            label="Empty Test Collection",
            creator=self.admin,
        )

        url = f"/api/2/collections/{empty_coll.id}/discover"
        res = self.client.get(url, headers=headers)

        assert res.status_code == 200
        data = res.json

        # Should have empty discovery data
        assert data["collection_id"] == str(empty_coll.id)
        assert len(data["peopleMentioned"]) == 0
        assert len(data["companiesMentioned"]) == 0
        assert len(data["locationMentioned"]) == 0
        assert len(data["namesMentioned"]) == 0
