"""Tests for the text-only entity percolation endpoint.

This is part of the /beta/ API.

Requires ``OPENALEPH_SEARCH_PERCOLATION=1`` in the pytest env
(set in ``pyproject.toml``).

The flow:
1. Index a Person entity with a known name → ES stores a percolator query
2. ``POST /beta/percolate`` with a text mentioning the person name should
return the Person as a hit
3. Index a Company entity with a known name → ES stores a percolator query
4. ``POST /beta/percolate?filter:schema=Company`` with a text mentioning
the person name should not return the Person nor the Company

"""

from aleph.core import db
from aleph.index.util import index_entity
from aleph.tests.util import TestCase


class PercolateTextBetaApiTestCase(TestCase):
    """POST /api/2/beta/percolate — the text-first counterpart to the
    entity-scoped GET endpoint (openaleph/openaleph#105)."""

    def setUp(self):
        super().setUp()
        self.role, self.headers = self.login(is_admin=True)
        self.col = self.create_collection(creator=self.role)

        # A Person whose stored percolator query we expect to fire, and a
        # Company that must NOT fire so the schema filter is exercised.
        self.person = self.create_entity(
            {"schema": "Person", "properties": {"name": ["Paul Manafort"]}},
            self.col,
        )
        index_entity(self.person)
        self.company = self.create_entity(
            {"schema": "Company", "properties": {"name": ["Acme Holdings Ltd"]}},
            self.col,
        )
        index_entity(self.company)
        db.session.commit()

        self.article = (
            "Paul Manafort was convicted of tax and bank fraud in a "
            "federal court in Virginia."
        )

    def test_percolate_text_requires_auth(self):
        res = self.client.post("/api/2/beta/percolate", json={"text": self.article})
        assert res.status_code == 403, res

    def test_percolate_text_returns_matching_entities(self):
        res = self.client.post(
            "/api/2/beta/percolate", json={"text": self.article}, headers=self.headers
        )
        assert res.status_code == 200, res.json
        matched = {r["id"] for r in res.json.get("results", [])}
        assert self.person.id in matched, (
            f"expected {self.person.id} in results, got "
            f"{[r.get('caption') for r in res.json.get('results', [])]}"
        )

    def test_percolate_text_respects_filters(self):
        res = self.client.post(
            "/api/2/beta/percolate?filter:schema=Company",
            json={"text": self.article},
            headers=self.headers,
        )
        assert res.status_code == 200, res.json
        matched = {r["id"] for r in res.json.get("results", [])}
        assert self.person.id not in matched

    def test_percolate_text_missing_text_is_400(self):
        res = self.client.post("/api/2/beta/percolate", json={}, headers=self.headers)
        assert res.status_code == 400, res.json

    def test_percolate_text_empty_text_is_400(self):
        res = self.client.post(
            "/api/2/beta/percolate", json={"text": "   "}, headers=self.headers
        )
        assert res.status_code == 400, res.json

    def test_percolate_text_over_limit_is_400(self):
        from aleph.settings import SETTINGS

        big = "a " * (SETTINGS.PERCOLATE_MAX_TEXT // 2 + 10)
        res = self.client.post(
            "/api/2/beta/percolate", json={"text": big}, headers=self.headers
        )
        assert res.status_code == 400, res.json
