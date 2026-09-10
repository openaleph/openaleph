import logging
from typing import Any, Generator

from followthemoney import model
from followthemoney.types import registry
from openaleph_search.core import get_es
from openaleph_search.index.entities import checksums_count
from openaleph_search.index.indexes import entities_read_index
from openaleph_search.index.util import MAX_REQUEST_TIMEOUT, MAX_TIMEOUT

from aleph.core import archive, db
from aleph.model import Document, Export

log = logging.getLogger(__name__)

# how many checksum buckets to fetch per composite aggregation page
INDEX_PAGE_SIZE = 1000
# how many rows to buffer when streaming the documents table
DOCUMENT_BATCH_SIZE = 10000


def _chunked_hashes(prefix, batch_size=500):
    batch = set()
    for content_hash in archive.list_files(prefix=prefix):
        batch.add(content_hash)
        if len(batch) >= batch_size:
            yield batch
            batch = set()
    if len(batch) > 0:
        yield batch


def cleanup_archive(prefix=None):
    """Clean up the blob archive behind aleph. Files inside of the archive
    are keyed on their SHA1 checksum, but the archive itself doesn't know
    what entities or exports a blob is linked to. So this is basically a
    garbage collector that needs to determine if any part of the database
    or index references the given hash. It's a messy process and it should
    be applied carefully."""
    for batch in _chunked_hashes(prefix):
        for content_hash, count in checksums_count(batch):
            if count > 0:
                # log.info("Used hash: %s", content_hash)
                continue
            # In theory, this is a redundant check. In practice, it's shit
            # to delete seed data from the docs table by accident:
            docs = Document.by_content_hash(content_hash)
            if docs.count() > 0:
                # log.info("Doc hash: %s", content_hash)
                continue
            exports = Export.by_content_hash(content_hash)
            if exports.count() > 0:
                continue
            # path = archive.load_file(content_hash)
            # log.info("Dangling hash [%s]: %s", content_hash, path)
            log.info("Dangling hash: %s", content_hash)
            archive.delete_file(content_hash)


def iter_document_checksums(
    batch_size: int = DOCUMENT_BATCH_SIZE,
) -> Generator[str, None, None]:
    """Stream the distinct content hashes stored in the documents table."""
    q = db.session.query(Document.content_hash).distinct()
    q = q.filter(Document.content_hash != None)  # noqa: E711
    for (content_hash,) in q.yield_per(batch_size):
        yield content_hash


def iter_index_checksums(
    page_size: int = INDEX_PAGE_SIZE,
) -> Generator[str, None, None]:
    """Stream the distinct checksums mentioned by entities in the search
    index. This sweeps the checksum group field of all schemata that can
    carry one (documents, but also e.g. pages and packages) using a
    composite aggregation, which pages through the terms in order."""
    schemata = model.get_type_schemata(registry.checksum)
    index = entities_read_index(schemata)
    es = get_es()
    after: dict[str, Any] | None = None
    while True:
        composite: dict[str, Any] = {
            "size": page_size,
            "sources": [{"checksum": {"terms": {"field": registry.checksum.group}}}],
        }
        if after is not None:
            composite["after"] = after
        body = {
            "size": 0,
            "timeout": MAX_TIMEOUT,
            "aggs": {"checksums": {"composite": composite}},
        }
        result = es.search(index=index, body=body, request_timeout=MAX_REQUEST_TIMEOUT)
        agg = result.get("aggregations", {}).get("checksums", {})
        buckets = agg.get("buckets", [])
        for bucket in buckets:
            yield bucket.get("key", {}).get("checksum")
        after = agg.get("after_key")
        if after is None or not len(buckets):
            break


def iter_checksums() -> Generator[str, None, None]:
    r"""Stream all the content hashes aleph knows about: the ones stored in
    the documents table, followed by the ones mentioned by entities in the
    search index. Hashes are de-duplicated within each of the two sources,
    but not across them.

    This does not touch the archive itself. The hashes of the blobs stored
    in a local (file-based) archive are the names of its leaf directories,
    so they can be listed without aleph:

        find /path/to/archive -type d -links 2 -printf '%f\n'
    """
    yield from iter_document_checksums()
    yield from iter_index_checksums()
