import csv
import logging
import os
import shutil
from tempfile import mkdtemp
from zipfile import ZipFile

import orjson
from flask import render_template
from followthemoney.export.excel import ExcelExporter
from followthemoney.helpers import entity_filename
from normality import safe_filename
from openaleph_procrastinate import defer
from openaleph_procrastinate.app import make_app
from openaleph_search.index.entities import checksums_count, iter_proxies
from servicelayer.archive.util import checksum, ensure_path

from aleph.core import archive, db
from aleph.index.collections import get_collection
from aleph.logic.aggregator import get_aggregator_name
from aleph.logic.mail import email_role
from aleph.logic.notifications import publish
from aleph.logic.util import archive_url, entity_url, ui_url
from aleph.model import Entity, Events, Export, Role, Status
from aleph.settings import SETTINGS

log = logging.getLogger(__name__)
app = make_app(SETTINGS.PROCRASTINATE_TASKS)

EXTRA_HEADERS = ["url", "collection"]
WARNING = """
This data export was aborted before it was complete, because the %s
exported entities exceeds the limits set by the system operators.

Contact the operator to discuss bulk exports.
"""

# operation
EXPORT_XREF = "exportxref"


def get_export(export_id):
    if export_id is None:
        return
    export = Export.by_id(export_id, deleted=True)
    if export is not None:
        return export.to_dict()


def write_document(export_dir, zf, collection, entity):
    content_hash = entity.first("contentHash", quiet=True)
    if content_hash is None:
        return False
    file_name = entity_filename(entity)
    arcname = "{0}-{1}".format(entity.id, file_name)
    arcname = os.path.join(collection.get("label"), arcname)
    log.info("Export file: %s", arcname)
    try:
        local_path = archive.load_file(content_hash, temp_path=export_dir)
        if local_path is not None and os.path.exists(local_path):
            zf.write(local_path, arcname=arcname)
            return True
        return False
    finally:
        archive.cleanup_file(content_hash, temp_path=export_dir)


def _collect_proxies(export):
    """Collect proxies from ES into a list to avoid scroll TTL issues
    during slow downstream work (file downloads, zipping, etc.)."""
    filters = [export.meta.get("query", {"match_none": {}})]
    schemata = export.meta.get("schemata", [Entity.THING])
    proxies = []
    collections = {}
    for entity in iter_proxies(schemata=schemata, filters=filters):
        collection_id = entity.context.get("collection_id")
        if collection_id not in collections:
            collections[collection_id] = get_collection(collection_id)
        if collections[collection_id] is None:
            continue
        proxies.append(entity)
        if len(proxies) >= SETTINGS.EXPORT_MAX_RESULTS:
            break
    return proxies, collections


def export_entities(export_id):
    export = Export.by_id(export_id)
    log.info("Export entities [%r]...", export)
    export_dir = ensure_path(mkdtemp(prefix="aleph.export."))
    try:
        proxies, collections = _collect_proxies(export)
        file_path = export_dir.joinpath("export.zip")
        with ZipFile(file_path, mode="w") as zf:
            excel_name = safe_filename(export.label, extension="xlsx")
            excel_path = export_dir.joinpath(excel_name)
            exporter = ExcelExporter(excel_path, extra=EXTRA_HEADERS)
            for entity in proxies:
                collection_id = entity.context.get("collection_id")
                collection = collections[collection_id]
                extra = [entity_url(entity.id), collection.get("label")]
                exporter.write(entity, extra=extra)
                write_document(export_dir, zf, collection, entity)
                if file_path.stat().st_size >= SETTINGS.EXPORT_MAX_SIZE:
                    concern = "total size of the"
                    zf.writestr("EXPORT_TOO_LARGE.txt", WARNING % concern)
                    break
            exporter.finalize()
            zf.write(excel_path, arcname=excel_name)
        file_name = safe_filename(export.label, extension="zip")
        complete_export(export_id, file_path, file_name)
    except Exception:
        log.exception("Failed to process export [%s]", export_id)
        export = Export.by_id(export_id)
        export.set_status(status=Status.FAILED)
        db.session.commit()
    finally:
        shutil.rmtree(export_dir)


def export_files(export_id):
    export = Export.by_id(export_id)
    log.info("Export files [%r]...", export)
    export_dir = ensure_path(mkdtemp(prefix="aleph.export."))
    try:
        proxies, collections = _collect_proxies(export)
        file_path = export_dir.joinpath("export.zip")

        files_written = 0
        size_exceeded = False

        with ZipFile(file_path, mode="w") as zf:
            for entity in proxies:
                collection_id = entity.context.get("collection_id")
                collection = collections[collection_id]
                if collection is None:
                    continue

                if write_document(export_dir, zf, collection, entity):
                    files_written += 1

                if file_path.stat().st_size >= SETTINGS.EXPORT_MAX_SIZE:
                    size_exceeded = True
                    break

        if files_written == 0:
            # No files found
            export.file_name = None
            export.file_size = 0
            export.content_hash = None
            export.set_status(status=Status.SUCCESS)
            export.meta = {**export.meta, "no_files": True}
            db.session.commit()
            return

        if size_exceeded:
            # Export too large
            export.file_name = None
            export.file_size = 0
            export.content_hash = None
            export.set_status(status=Status.SUCCESS)
            export.meta = {**export.meta, "too_large": True}
            db.session.commit()
            return

        file_name = safe_filename(export.label, extension="zip")
        complete_export(export_id, file_path, file_name)
    except Exception:
        log.exception("Failed to process files export [%s]", export_id)
        export = Export.by_id(export_id)
        export.set_status(status=Status.FAILED)
        db.session.commit()
    finally:
        shutil.rmtree(export_dir)


CSV_HEADERS = ["caption", "schema", "collection", "collection_fid", "url"]


def export_csv(export_id):
    export = Export.by_id(export_id)
    log.info("Export CSV [%r]...", export)
    export_dir = ensure_path(mkdtemp(prefix="aleph.export."))
    try:
        proxies, collections = _collect_proxies(export)
        file_name = safe_filename(export.label, extension="csv")
        file_path = export_dir.joinpath(file_name)
        with open(file_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(CSV_HEADERS)
            for entity in proxies:
                collection_id = entity.context.get("collection_id")
                collection = collections[collection_id]
                writer.writerow(
                    [
                        entity.caption,
                        entity.schema.name,
                        collection.get("label"),
                        collection.get("foreign_id"),
                        entity_url(entity.id),
                    ]
                )
        complete_export(export_id, file_path, file_name)
    except Exception:
        log.exception("Failed to process CSV export [%s]", export_id)
        export = Export.by_id(export_id)
        export.set_status(status=Status.FAILED)
        db.session.commit()
    finally:
        shutil.rmtree(export_dir)


def export_entities_jsonl(export_id):
    export = Export.by_id(export_id)
    log.info("Export entities JSONL [%r]...", export)
    export_dir = ensure_path(mkdtemp(prefix="aleph.export."))
    try:
        proxies, collections = _collect_proxies(export)
        file_name = safe_filename(export.label, extension="jsonl")
        file_path = export_dir.joinpath(file_name)
        with open(file_path, "wb") as fh:
            for entity in proxies:
                fh.write(orjson.dumps(entity.to_dict()))
                fh.write(b"\n")
        complete_export(export_id, file_path, file_name)
    except Exception:
        log.exception("Failed to process JSONL export [%s]", export_id)
        export = Export.by_id(export_id)
        export.set_status(status=Status.FAILED)
        db.session.commit()
    finally:
        shutil.rmtree(export_dir)


def create_export(
    operation,
    role_id,
    label,
    collection=None,
    mime_type=None,
    meta=None,
):
    export = Export.create(
        operation,
        role_id,
        label,
        collection=collection,
        mime_type=mime_type,
        meta=meta,
    )
    db.session.commit()
    return export


def complete_export(export_id, file_path, file_name):
    export = Export.by_id(export_id)
    file_path = ensure_path(file_path)
    export.file_name = file_name
    export.file_size = file_path.stat().st_size
    export.content_hash = checksum(file_path)
    try:
        archive.archive_file(
            file_path, content_hash=export.content_hash, mime_type=export.mime_type
        )
        export.set_status(status=Status.SUCCESS)
    except Exception:
        log.exception("Failed to upload export: %s", export)
        export.set_status(status=Status.FAILED)

    db.session.commit()
    params = {"export": export}
    role = Role.by_id(export.creator_id)
    log.info("Export [%r] complete: %s", export, export.status)
    publish(
        Events.COMPLETE_EXPORT,
        params=params,
        channels=[role],
    )
    # Email notifications disabled - users check /exports page instead
    # send_export_notification(export)


def delete_expired_exports():
    """Delete export files from the archive after their time
    limit has expired."""
    expired_exports = Export.get_expired(deleted=False)
    for export in expired_exports:
        log.info("Deleting expired export: %r", export)
        if export.should_delete_publication():
            if export.content_hash is not None:
                counts = list(checksums_count([export.content_hash]))
                if counts[0][1] == 0:
                    archive.delete_file(export.content_hash)
        export.deleted = True
        db.session.add(export)
    db.session.commit()


def retry_exports():
    from aleph.procrastinate.queues import (
        OP_EXPORT_CSV,
        OP_EXPORT_ENTITIES,
        OP_EXPORT_FILES,
        OP_EXPORT_XREF,
    )

    for export in Export.get_pending():
        if export.operation in (
            OP_EXPORT_FILES,
            OP_EXPORT_CSV,
            OP_EXPORT_ENTITIES,
        ):
            defer.export_search(app, export_id=export.id)
        elif export.operation == OP_EXPORT_XREF:
            dataset = get_aggregator_name(export.collection)
            defer.export_xref(app, dataset, export_id=export.id)
        else:
            raise ValueError(f"Unknown export operation: `{export.operation}`")


# def send_export_notification(export):
#     download_url = archive_url(
#         export.content_hash,
#         file_name=export.file_name,
#         mime_type=export.mime_type,
#         expire=export.expires_at,
#     )
#     params = dict(
#         role=export.creator,
#         export_label=export.label,
#         download_url=download_url,
#         expiration_date=export.expires_at.strftime("%Y-%m-%d"),
#         exports_url=ui_url("exports"),
#         ui_url=SETTINGS.APP_UI_URL,
#         app_title=SETTINGS.APP_TITLE,
#     )
#     plain = render_template("email/export.txt", **params)
#     html = render_template("email/export.html", **params)
#     log.info("Notification: %s", plain)
#     subject = "Export ready for download"
#     email_role(export.creator, subject, html=html, plain=plain)
