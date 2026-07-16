from urllib.parse import parse_qs, urlparse

from aleph.core import archive, db
from aleph.index.util import index_entity
from aleph.logic.util import archive_token, archive_url
from aleph.tests.util import TestCase


class ArchiveApiTestCase(TestCase):
    def setUp(self):
        super(ArchiveApiTestCase, self).setUp()
        self.fixture = self.get_fixture_path("samples/website.html")
        self.content_hash = archive.archive_file(self.fixture)
        self.fixture2 = self.get_fixture_path("samples/taggable.txt")
        self.content_hash2 = archive.archive_file(self.fixture2)
        self.role, self.headers = self.login(foreign_id="archive_admin", is_admin=True)
        self.col = self.create_collection(creator=self.role)
        doc = {
            "schema": "PlainText",
            "properties": {
                "fileName": "website.html",
                "mimeType": "text/html",
                "contentHash": self.content_hash,
            },
        }
        self.doc = self.create_entity(doc, self.col)
        self.doc_id = self.col.ns.sign(self.doc.id)
        db.session.commit()
        index_entity(self.doc)

    def test_no_token(self):
        res = self.client.get("/api/2/archive")
        assert res.status_code == 401, res

    def test_invalid_token(self):
        res = self.client.get("/api/2/archive?token=banana")
        assert res.status_code == 401, res

    def test_with_token(self):
        claim_url = archive_url(self.content_hash, file_name="foo")
        res = self.client.get(claim_url)
        assert res.status_code == 200, res.status_code
        disposition = res.headers.get("Content-Disposition")
        assert "foo" in disposition, disposition

    def test_with_token_role_id(self):
        claim_url = archive_url(self.content_hash, file_name="foo")
        parsed_url = urlparse(claim_url)
        token = parse_qs(parsed_url.query).get("token", [None])[0]
        assert token is not None
        role_id = archive_token(token)[-1]
        assert role_id is None

        # explicitly pass through role id to jwt
        claim_url = archive_url(self.content_hash, file_name="foo", role_id=1)
        parsed_url = urlparse(claim_url)
        token = parse_qs(parsed_url.query).get("token", [None])[0]
        assert token is not None
        role_id = archive_token(token)[-1]
        assert role_id == 1

    def test_resolve_missing_params(self):
        res = self.client.get("/api/2/archive/resolve", headers=self.headers)
        assert res.status_code == 400, res

        url = "/api/2/archive/resolve?entity=%s&prop=banana" % self.doc_id
        res = self.client.get(url, headers=self.headers)
        assert res.status_code == 400, res

    def test_resolve_anonymous(self):
        url = "/api/2/archive/resolve?entity=%s&prop=contentHash" % self.doc_id
        res = self.client.get(url)
        assert res.status_code == 403, res

    def test_resolve_missing_hash(self):
        url = "/api/2/archive/resolve?entity=%s&prop=pdfHash" % self.doc_id
        res = self.client.get(url, headers=self.headers)
        assert res.status_code == 404, res

    def test_resolve_redirect(self):
        url = "/api/2/archive/resolve?entity=%s&prop=contentHash" % self.doc_id
        res = self.client.get(url, headers=self.headers)
        assert res.status_code == 302, res
        location = res.headers.get("Location")
        assert "/api/2/archive?token=" in location, location

        # the signed token carries the requesting role
        parsed_url = urlparse(location)
        token = parse_qs(parsed_url.query).get("token", [None])[0]
        assert token is not None
        role_id = archive_token(token)[-1]
        assert role_id == self.role.id

        # the redirect target serves the actual blob
        res = self.client.get(location)
        assert res.status_code == 200, res.status_code
        disposition = res.headers.get("Content-Disposition")
        assert "website.html" in disposition, disposition

    def test_resolve_json(self):
        url = "/api/2/archive/resolve?entity=%s&redirect=false" % self.doc_id
        res = self.client.get(url, headers=self.headers)
        assert res.status_code == 200, res
        claim_url = res.json.get("url")
        assert "/api/2/archive?token=" in claim_url, res.json

        res = self.client.get(claim_url)
        assert res.status_code == 200, res.status_code
        disposition = res.headers.get("Content-Disposition")
        assert "website.html" in disposition, disposition
