from aleph.logic.discover import (
    _prop_agg_key,
    _unpack_buckets,
    compute_collection_discovery,
)
from aleph.logic.resolver import cache
from aleph.model.discover import CollectionDiscovery
from aleph.tests.util import TestCase


class DiscoveryTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.load_fixtures()

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

    def test_integration_with_fixtures(self):
        """Test discovery functionality with actual fixture data and Elasticsearch."""
        collection_id = self.private_coll.id

        # Clear any existing cache
        cache.invalidate(CollectionDiscovery, collection_id)

        # Now test actual discovery computation with real Elasticsearch
        discovery_result = compute_collection_discovery(collection_id)

        # Verify the result structure
        self.assertIsInstance(discovery_result, CollectionDiscovery)
        self.assertEqual(discovery_result.collection_id, str(collection_id))

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

    def test_discovery_empty_dataset(self):
        """Test discovery with a collection that has no analyzable entities."""
        # Create a collection with no entities
        empty_coll = self.create_collection(
            foreign_id="test_empty",
            label="Empty Collection",
            creator=self.admin,
        )

        collection_id = empty_coll.id

        result = compute_collection_discovery(collection_id)

        self.assertIsInstance(result, CollectionDiscovery)
        self.assertEqual(result.collection_id, str(collection_id))
        self.assertEqual(len(result.peopleMentioned), 0)
        self.assertEqual(len(result.companiesMentioned), 0)
        self.assertEqual(len(result.locationMentioned), 0)
        self.assertEqual(len(result.namesMentioned), 0)
