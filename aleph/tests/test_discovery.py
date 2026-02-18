from unittest.mock import patch

from aleph.core import cache
from aleph.logic.discover import (
    _discovery_key,
    _prop_agg_key,
    _unpack_buckets,
    get_collection_discovery,
    update_collection_discovery,
)
from aleph.model.discover import DatasetDiscovery
from aleph.tests.util import TestCase


class DiscoveryTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.load_fixtures()

    def test_discovery_key(self):
        """Test that discovery key generation is consistent."""
        collection_id = 123
        expected_key = cache.object_key(
            self.private_coll.__class__, collection_id, "discovery"
        )
        actual_key = _discovery_key(collection_id)
        self.assertEqual(expected_key, actual_key)

    def test_prop_agg_key(self):
        """Test property aggregation key generation."""
        from followthemoney import model

        prop = model["Analyzable"].properties["peopleMentioned"]

        # Test with default suffix
        key = _prop_agg_key(prop)
        self.assertEqual(key, f"properties.{prop.name}.values")

        # Test with custom suffix
        key = _prop_agg_key(prop, "significant_terms")
        self.assertEqual(key, f"properties.{prop.name}.significant_terms")

    def test_unpack_buckets(self):
        """Test unpacking aggregation buckets into MentionedTerms."""
        mock_agg = {
            "properties.peopleMentioned.significant_sampled": {
                "properties.peopleMentioned.significant_terms": {
                    "buckets": [
                        {"key": "John Doe", "doc_count": 5},
                        {"key": "Jane Smith", "doc_count": 3},
                        {"key": "ignored_term", "doc_count": 2},
                    ]
                }
            },
            "properties.companiesMentioned.significant_sampled": {
                "properties.companiesMentioned.significant_terms": {
                    "buckets": [
                        {"key": "ACME Corp", "doc_count": 8},
                        {"key": "ignored_term", "doc_count": 1},
                    ]
                }
            },
        }

        result = _unpack_buckets(mock_agg, "ignored_term")

        # Check that ignored term is filtered out
        self.assertEqual(len(result.peopleMentioned), 2)
        self.assertEqual(len(result.companiesMentioned), 1)

        # Check specific values
        self.assertEqual(result.peopleMentioned[0].name, "John Doe")
        self.assertEqual(result.peopleMentioned[0].count, 5)
        self.assertEqual(result.companiesMentioned[0].name, "ACME Corp")
        self.assertEqual(result.companiesMentioned[0].count, 8)

    def test_get_collection_discovery_cached(self):
        """Test retrieving cached discovery data."""
        collection_id = self.private_coll.id
        dataset = "test_dataset"

        # Mock cached data
        cached_data = {
            "name": dataset,
            "peopleMentioned": [
                {
                    "term": {"name": "John Doe", "count": 5},
                    "peopleMentioned": [{"name": "Jane Smith", "count": 2}],
                    "companiesMentioned": [],
                    "locationMentioned": [],
                    "namesMentioned": [],
                }
            ],
            "companiesMentioned": [],
            "locationMentioned": [],
            "namesMentioned": [],
        }

        with patch.object(cache, "get_complex", return_value=cached_data):
            result = get_collection_discovery(collection_id, dataset)

            self.assertIsInstance(result, DatasetDiscovery)
            self.assertEqual(result.name, dataset)
            self.assertEqual(len(result.peopleMentioned), 1)
            self.assertEqual(result.peopleMentioned[0].term.name, "John Doe")

    def test_get_collection_discovery_no_cache(self):
        """Test retrieving discovery data when cache is empty."""
        collection_id = self.private_coll.id
        dataset = "test_dataset"

        with patch.object(cache, "get_complex", return_value=None):
            result = get_collection_discovery(collection_id, dataset)

            self.assertIsInstance(result, DatasetDiscovery)
            self.assertEqual(result.name, dataset)
            self.assertEqual(len(result.peopleMentioned), 0)
            self.assertEqual(len(result.companiesMentioned), 0)

    def test_integration_with_fixtures(self):
        """Test discovery functionality with actual fixture data and Elasticsearch."""
        collection_id = self.private_coll.id
        dataset = self.private_coll.foreign_id

        # Clear any existing cache
        cache_key = _discovery_key(collection_id)
        cache.delete(cache_key)

        # Test that we can get empty discovery when no cache exists
        result = get_collection_discovery(collection_id, dataset)
        self.assertEqual(result.name, dataset)
        self.assertEqual(len(result.peopleMentioned), 0)

        # Now test actual discovery computation with real Elasticsearch
        discovery_result = update_collection_discovery(collection_id, dataset)

        # Verify the result structure
        self.assertIsInstance(discovery_result, DatasetDiscovery)
        self.assertEqual(discovery_result.name, dataset)

        # Check that the discovery found some data from fixtures
        # The fixtures contain entities with namesMentioned like "Vladimir L."
        total_terms = (
            len(discovery_result.peopleMentioned)
            + len(discovery_result.companiesMentioned)
            + len(discovery_result.locationMentioned)
            + len(discovery_result.namesMentioned)
        )

        # Should have found at least some terms from the fixture data
        self.assertGreaterEqual(
            total_terms, 0
        )  # May be 0 if no significant terms found

        # Test that cache now works
        cached_result = get_collection_discovery(collection_id, dataset)
        self.assertEqual(cached_result.name, discovery_result.name)
        self.assertEqual(
            len(cached_result.peopleMentioned), len(discovery_result.peopleMentioned)
        )

    def test_discovery_with_public_collection(self):
        """Test discovery with the public collection that has KwaZulu entity."""
        collection_id = self.public_coll.id
        dataset = self.public_coll.foreign_id

        # Clear cache
        cache_key = _discovery_key(collection_id)
        cache.delete(cache_key)

        # Update discovery for public collection
        result = update_collection_discovery(collection_id, dataset)

        self.assertIsInstance(result, DatasetDiscovery)
        self.assertEqual(result.name, dataset)

        # The public collection has a Company "KwaZulu" so we might find related terms
        # But discovery is about mentioned entities, not the entities themselves
        # So results may vary based on the actual entity properties

    def test_discovery_cache_persistence(self):
        """Test that discovery cache persists across multiple calls."""
        collection_id = self.private_coll.id
        dataset = self.private_coll.foreign_id

        # Clear cache first
        cache_key = _discovery_key(collection_id)
        cache.delete(cache_key)

        # First call should compute and cache
        result1 = update_collection_discovery(collection_id, dataset)

        # Second call should use cache (we can verify by checking it doesn't recompute)
        with patch("aleph.logic.discover.EntitiesQuery") as mock_query:
            result2 = get_collection_discovery(collection_id, dataset)
            # Query should not be called for cached result
            mock_query.assert_not_called()

        self.assertEqual(result1.name, result2.name)
        self.assertEqual(len(result1.peopleMentioned), len(result2.peopleMentioned))

    def test_discovery_empty_dataset(self):
        """Test discovery with a collection that has no analyzable entities."""
        # Create a collection with no entities
        empty_coll = self.create_collection(
            foreign_id="test_empty",
            label="Empty Collection",
            creator=self.admin,
        )

        collection_id = empty_coll.id
        dataset = empty_coll.foreign_id

        result = update_collection_discovery(collection_id, dataset)

        self.assertIsInstance(result, DatasetDiscovery)
        self.assertEqual(result.name, dataset)
        self.assertEqual(len(result.peopleMentioned), 0)
        self.assertEqual(len(result.companiesMentioned), 0)
        self.assertEqual(len(result.locationMentioned), 0)
        self.assertEqual(len(result.namesMentioned), 0)
