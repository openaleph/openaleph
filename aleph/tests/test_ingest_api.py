import hashlib
import json
from io import BytesIO
from pprint import pprint  # noqa
from unittest.mock import patch

from aleph.core import db
from aleph.logic.collections import reindex_collection
from aleph.model import Document
from aleph.procrastinate.status import get_collection_status
from aleph.tests.util import TestCase


class IngestApiTestCase(TestCase):
    def setUp(self):
        super(IngestApiTestCase, self).setUp()
        self.rolex = self.create_user(foreign_id="user_3")
        self.col = self.create_collection()
        self.url = "/api/2/collections/%s/ingest" % self.col.id

    def test_upload_logged_out(self):
        data = {"meta": json.dumps({})}
        res = self.client.post(self.url, data=data)
        assert res.status_code == 403, res

    def test_upload_no_meta(self):
        _, headers = self.login(is_admin=True)
        data = {"meta": "hihi"}
        res = self.client.post(self.url, data=data, headers=headers)
        assert res.status_code == 400, res

    def test_upload_csv_doc(self):
        _, headers = self.login(is_admin=True)
        meta = {
            "countries": ["de", "usa"],
            "languages": ["en"],
            "mime_type": "text/csv",
            "source_url": "http://pudo.org/experts.csv",
        }
        csv_path = self.get_fixture_path("experts.csv")
        data = {
            "meta": json.dumps(meta),
            "foo": open(csv_path, "rb"),
        }
        res = self.client.post(self.url, data=data, headers=headers)
        assert res.status_code == 201, (res, res.data)
        assert "id" in res.json, res.json

        db_id, _ = res.json.get("id").split(".", 1)
        doc = Document.by_id(db_id)
        assert doc.schema == Document.SCHEMA, doc.schema
        assert doc.meta["countries"] == ["de", "us"], doc.meta
        assert doc.meta["languages"] == ["eng"], doc.meta

        # just try that this doesn't fail
        _ = get_collection_status(self.col, include_collection_data=False)

        # FIXME we need to patch test runtime envs to actually defer ingest
        # tasks to make this work:

        # assert status == {"finished": 0, "running": 0, "pending": 0, "jobs": []}
        # assert status.get("pending") == 1, status
        # job = status.get("jobs")[0]
        # assert job.get("pending") == 1, job
        # stage = job.get("stages")[0]
        # assert stage.get("stage") == OP_INGEST, stage
        # assert stage.get("pending") == 1, stage

    def test_upload_filename_fallback(self):
        _, headers = self.login(is_admin=True)
        for index, metadata in enumerate(({}, {"file_name": None}, {"file_name": ""})):
            with self.subTest(metadata=metadata):
                metadata = {
                    "countries": ["de", "usa"],
                    "languages": ["en"],
                    "title": "Message title",
                    **metadata,
                }
                data = {
                    "meta": json.dumps(metadata),
                    "file": (
                        BytesIO(f"Subject: Example {index}\r\n\r\nBody".encode()),
                        "../Example message.eml",
                    ),
                }
                with patch("aleph.views.ingest_api.queue_ingest") as queued:
                    res = self.client.post(self.url, data=data, headers=headers)
                assert res.status_code == 201, (res, res.data)
                db_id, _ = res.json["id"].split(".", 1)
                document = Document.by_id(db_id)
                assert document.meta["file_name"] == "Example_message.eml"
                assert document.meta["countries"] == ["de", "us"]
                assert document.meta["languages"] == ["eng"]
                assert document.meta["title"] == "Message title"
                proxy = queued.call_args.args[1]
                assert proxy.get("fileName") == ["Example_message.eml"]

    def test_upload_preserves_explicit_filename(self):
        _, headers = self.login(is_admin=True)
        data = {
            "meta": json.dumps({"file_name": "Original message.eml"}),
            "file": (BytesIO(b"Subject: Example\r\n\r\nBody"), "upload.bin"),
        }
        with patch("aleph.views.ingest_api.queue_ingest") as queued:
            res = self.client.post(self.url, data=data, headers=headers)
        assert res.status_code == 201, (res, res.data)
        db_id, _ = res.json["id"].split(".", 1)
        document = Document.by_id(db_id)
        assert document.meta["file_name"] == "Original message.eml"
        assert queued.call_args.args[1].get("fileName") == ["Original message.eml"]

    def test_reupload_preserves_stored_filename(self):
        _, headers = self.login(is_admin=True)
        _, _, first_id = self._upload_filename_document(
            headers,
            {"foreign_id": "same-source", "file_name": "Curated message.eml"},
        )
        document, proxy, second_id = self._upload_filename_document(
            headers, {"foreign_id": "same-source"}, filename="renamed.bin"
        )
        assert second_id == first_id
        assert document.meta["file_name"] == "Curated message.eml"
        assert proxy.get("fileName") == ["Curated message.eml"]

    def _upload_filename_document(
        self,
        headers,
        metadata,
        filename="upload.bin",
        body=b"Subject: Example\r\n\r\nBody",
    ):
        data = {
            "meta": json.dumps(metadata),
            "file": (BytesIO(body), filename),
        }
        with patch("aleph.views.ingest_api.queue_ingest") as queued:
            res = self.client.post(self.url, data=data, headers=headers)
        assert res.status_code == 201, (res, res.data)
        queued.assert_called_once()
        document = Document.by_id(res.json["id"])
        db.session.refresh(document)
        return document, queued.call_args.args[1], res.json["id"]

    def test_reupload_replaces_explicit_filename(self):
        _, headers = self.login(is_admin=True)
        _, _, first_id = self._upload_filename_document(
            headers, {"foreign_id": "same-source", "file_name": "old.eml"}
        )
        document, proxy, second_id = self._upload_filename_document(
            headers, {"foreign_id": "same-source", "file_name": "new.eml"}
        )
        assert second_id == first_id
        assert document.meta["file_name"] == "new.eml"
        assert proxy.get("fileName") == ["new.eml"]

    def test_reupload_cleared_filename_uses_fallback(self):
        _, headers = self.login(is_admin=True)
        for index, value in enumerate((None, "", " \t ")):
            with self.subTest(file_name=value):
                foreign_id = f"same-source-{index}"
                _, _, first_id = self._upload_filename_document(
                    headers, {"foreign_id": foreign_id, "file_name": "old.eml"}
                )
                document, proxy, second_id = self._upload_filename_document(
                    headers,
                    {"foreign_id": foreign_id, "file_name": value},
                    filename="replacement.eml",
                )
                assert second_id == first_id
                assert document.meta["file_name"] == "replacement.eml"
                assert proxy.get("fileName") == ["replacement.eml"]

    def test_reupload_new_content_preserves_filename(self):
        _, headers = self.login(is_admin=True)
        _, _, first_id = self._upload_filename_document(
            headers, {"foreign_id": "same-source", "file_name": "Curated message.eml"}
        )
        body = b"Subject: Replacement\r\n\r\nChanged bytes"
        document, proxy, second_id = self._upload_filename_document(
            headers, {"foreign_id": "same-source"}, filename="changed.bin", body=body
        )
        assert second_id == first_id
        assert document.content_hash == hashlib.sha1(body).hexdigest()
        assert proxy.get("contentHash") == [document.content_hash]
        assert document.meta["file_name"] == "Curated message.eml"
        assert proxy.get("fileName") == ["Curated message.eml"]

    def test_reupload_same_content_preserves_filename(self):
        _, headers = self.login(is_admin=True)
        _, _, first_id = self._upload_filename_document(
            headers, {}, filename="first.eml"
        )
        document, proxy, second_id = self._upload_filename_document(
            headers, {}, filename="second.bin"
        )
        assert second_id == first_id
        assert document.meta["file_name"] == "first.eml"
        assert proxy.get("fileName") == ["first.eml"]

    def test_directory_without_filename(self):
        _, headers = self.login(is_admin=True)
        data = {"meta": json.dumps({"foreign_id": "unnamed-folder"})}
        with patch("aleph.views.ingest_api.queue_ingest") as queued:
            res = self.client.post(self.url, data=data, headers=headers)
        assert res.status_code == 201, (res, res.data)
        db_id, _ = res.json["id"].split(".", 1)
        document = Document.by_id(db_id)
        assert document.schema == Document.SCHEMA_FOLDER
        assert "file_name" not in document.meta
        assert queued.call_args.args[1].get("fileName") == []

    def test_upload_filename_with_parent(self):
        _, headers = self.login(is_admin=True)
        with patch("aleph.views.ingest_api.queue_ingest"):
            res = self.client.post(
                self.url,
                data={"meta": json.dumps({"foreign_id": "parent-folder"})},
                headers=headers,
            )
        assert res.status_code == 201, (res, res.data)
        parent_id = res.json["id"]
        data = {
            "meta": json.dumps({"parent_id": parent_id}),
            "file": (BytesIO(b"Subject: Child\r\n\r\nBody"), "child.eml"),
        }
        with patch("aleph.views.ingest_api.queue_ingest") as queued:
            res = self.client.post(self.url, data=data, headers=headers)
        assert res.status_code == 201, (res, res.data)
        db_id, _ = res.json["id"].split(".", 1)
        document = Document.by_id(db_id)
        assert document.meta["file_name"] == "child.eml"
        assert str(document.parent_id) == parent_id.split(".", 1)[0]
        proxy = queued.call_args.args[1]
        assert proxy.get("fileName") == ["child.eml"]
        assert proxy.get("parent") == [parent_id]
        assert parent_id in proxy.get("ancestors")

    def test_invalid_meta(self):
        _, headers = self.login(is_admin=True)
        meta = {"title": 3, "file_name": ""}
        data = {
            "meta": json.dumps(meta),
            "foo": (BytesIO(b"this is a futz with a banana"), "futz.html"),
        }
        res = self.client.post(self.url, data=data, headers=headers)
        assert res.status_code == 400, res

    def test_invalid_directory_without_foreign_id(self):
        _, headers = self.login(is_admin=True)
        meta = {"title": "test"}
        data = {"meta": json.dumps(meta)}
        res = self.client.post(self.url, data=data, headers=headers)
        assert res.status_code == 400, res

    def test_directory_with_file(self):
        _, headers = self.login(is_admin=True)
        meta = {
            "file_name": "directory",
            "foreign_id": "directory",
            "schema": "Folder",
            "collection_id": self.col.id,
        }
        data = {"meta": json.dumps(meta)}
        res = self.client.post(self.url, data=data, headers=headers)
        assert res.status_code == 201, res
        assert "id" in res.json, res.json
        directory = res.json["id"]

        meta = {
            "file_name": "subdirectory",
            "foreign_id": "subdirectory",
            "parent": {"id": directory},
            "collection_id": self.col.id,
        }
        data = {"meta": json.dumps(meta)}
        res = self.client.post(self.url, data=data, headers=headers)
        assert res.status_code == 201, res
        reindex_collection(self.col)
        assert "id" in res.json, res.json
        url = "/api/2/entities/%s" % res.json["id"]
        res = self.client.get(url, headers=headers)
        assert res.status_code == 200, res
        props = res.json.get("properties")
        assert "subdirectory" in props["fileName"], res.json
