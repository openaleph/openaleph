"""Tests for the entity percolation endpoint.

Requires ``OPENALEPH_SEARCH_PERCOLATION=1`` in the pytest env
(set in ``pyproject.toml``).

The flow:
1. Index a Person entity with a known name → ES stores a percolator query
2. Index a Document entity whose text mentions that name
3. ``GET /entities/<document_id>/percolate`` should return the Person as a hit
"""

from aleph.core import db
from aleph.index.util import index_entity
from aleph.tests.util import TestCase


class PercolateApiTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.role, self.headers = self.login(is_admin=True)
        self.col = self.create_collection(creator=self.role)

        # A person entity with a distinctive name — this gets a stored
        # percolator query built from its name variants at index time.
        person_data = {
            "schema": "Person",
            "properties": {
                "name": ["Paul Manafort"],
            },
        }
        self.person = self.create_entity(person_data, self.col)
        index_entity(self.person)

        # A document entity with text content that mentions the person.
        # The bodyText property becomes the indexed `content` field that
        # the percolator matches against.
        doc_data = {
            "schema": "PlainText",
            "properties": {
                "name": ["news_article.txt"],
                "bodyText": [
                    "Paul Manafort was convicted of tax and bank fraud "
                    "in a federal court in Virginia."
                ],
            },
        }
        self.doc = self.create_entity(doc_data, self.col)
        index_entity(self.doc)
        db.session.commit()

    def test_percolate_requires_auth(self):
        url = f"/api/2/entities/{self.doc.id}/percolate"
        res = self.client.get(url)
        assert res.status_code == 403, res

    def test_percolate_returns_matching_entities(self):
        url = f"/api/2/entities/{self.doc.id}/percolate"
        res = self.client.get(url, headers=self.headers)
        assert res.status_code == 200, res.json
        results = res.json.get("results", [])
        matched_ids = {r["id"] for r in results}
        assert self.person.id in matched_ids, (
            f"Expected person {self.person.id} in percolation results, "
            f"got: {[r.get('caption') for r in results]}"
        )

    def test_percolate_with_filter(self):
        """Percolation respects standard entity filters."""
        url = f"/api/2/entities/{self.doc.id}/percolate?filter:schema=Company"
        res = self.client.get(url, headers=self.headers)
        assert res.status_code == 200, res.json
        # Person should not appear when filtering for Company
        results = res.json.get("results", [])
        matched_ids = {r["id"] for r in results}
        assert self.person.id not in matched_ids

    def test_percolate_nonexistent_entity(self):
        url = "/api/2/entities/nonexistent-id/percolate"
        res = self.client.get(url, headers=self.headers)
        assert res.status_code == 404, res

    def test_percolate_non_document_entity(self):
        """Percolating a non-document entity (no text content) returns 400."""
        url = f"/api/2/entities/{self.person.id}/percolate"
        res = self.client.get(url, headers=self.headers)
        assert res.status_code == 400, res.json
