"""
Xref match export to Excel. Extracted from process.py.

This is a legacy feature that will be removed eventually.
"""

import logging
import shutil
from tempfile import mkdtemp

from followthemoney.export.excel import ExcelWriter
from followthemoney.proxy import EntityProxy
from followthemoney.types import registry
from openaleph_search.settings import BULK_PAGE
from servicelayer.archive.util import ensure_path

from aleph.authz import Authz
from aleph.core import db
from aleph.index.xref import iter_edges
from aleph.logic.export import complete_export
from aleph.logic.resolver import cache
from aleph.logic.util import entity_url
from aleph.model import Collection, CollectionSchema, EntitySchema, Export, Role, Status

log = logging.getLogger(__name__)


def _format_date(proxy: EntityProxy) -> str:
    dates = proxy.get_type_values(registry.date)
    if not len(dates):
        return ""
    return min(dates)


def _format_country(proxy: EntityProxy) -> str:
    countries = [c.upper() for c in proxy.countries]
    return ", ".join(countries)


def _collect_batch_ids(batch) -> tuple[set[str], set[int]]:
    """Extract entity IDs and collection IDs from a match batch."""
    entity_ids: set[str] = set()
    collection_ids: set[int] = set()
    for match in batch:
        entity_ids.add(match.get("source"))
        entity_ids.add(match.get("target"))
        target_cids = match.get("target_collection_id")
        if isinstance(target_cids, set):
            collection_ids.update(target_cids)
        elif target_cids is not None:
            collection_ids.add(target_cids)
    entity_ids.discard(None)
    return entity_ids, collection_ids


def _resolve_match_collection(
    target_cids, coll_by_id: dict[int, CollectionSchema]
) -> CollectionSchema | None:
    """Pick the first resolvable collection from target_collection_id."""
    if isinstance(target_cids, set):
        for cid in target_cids:
            coll = coll_by_id.get(cid)
            if coll is not None:
                return coll
    elif target_cids is not None:
        return coll_by_id.get(target_cids)
    return None


def _iter_match_batch(excel, sheet, batch):
    entity_ids, collection_ids = _collect_batch_ids(batch)

    # Batch-fetch entities via the resolver.
    fetched = cache.get_many(EntitySchema, list(entity_ids))
    entities = {e.id: e for e in fetched}

    # Batch-fetch collections
    coll_by_id = {
        int(c.id): c for c in cache.get_many(CollectionSchema, map(str, collection_ids))
    }

    for obj in batch:
        entity = entities.get(str(obj.get("source")))
        match_entity = entities.get(str(obj.get("target")))
        collection = _resolve_match_collection(
            obj.get("target_collection_id"), coll_by_id
        )
        if entity is None or match_entity is None or collection is None:
            continue
        eproxy = entity.to_proxy()
        mproxy = match_entity.to_proxy()
        sheet.append(
            [
                obj.get("score"),
                eproxy.caption,
                _format_date(eproxy),
                _format_country(eproxy),
                collection.title,
                mproxy.caption,
                _format_date(mproxy),
                _format_country(mproxy),
                entity_url(eproxy.id),
                entity_url(mproxy.id),
            ]
        )


def export_matches(export_id):
    """Export the top N matches of cross-referencing for the given collection
    to an Excel formatted export."""
    export = Export.by_id(export_id)
    export_dir = ensure_path(mkdtemp(prefix="aleph.export."))
    try:
        role = Role.by_id(export.creator_id)
        authz = Authz.from_role(role)
        collection = Collection.by_id(export.collection_id)
        file_name = "%s - Crossreference.xlsx" % collection.label  # codespell:ignore
        file_path = export_dir.joinpath(f"{export_id}.xslx")
        excel = ExcelWriter()
        headers = [
            "Score",
            "Entity Name",
            "Entity Date",
            "Entity Countries",
            "Candidate Collection",
            "Candidate Name",
            "Candidate Date",
            "Candidate Countries",
            "Entity Link",
            "Candidate Link",
        ]
        sheet = excel.make_sheet("Cross-reference", headers)
        batch = []

        for match in iter_edges(collection, authz):
            batch.append(match)
            if len(batch) >= BULK_PAGE:
                _iter_match_batch(excel, sheet, batch)
                batch = []
        if len(batch):
            _iter_match_batch(excel, sheet, batch)

        with open(file_path, "wb") as fp:
            buffer = excel.get_bytesio()
            for data in buffer:
                fp.write(data)

        complete_export(export_id, file_path, file_name)
    except Exception:
        log.exception("Failed to process export [%s]", export_id)
        export = Export.by_id(export_id)
        export.set_status(status=Status.FAILED)
        db.session.commit()
    finally:
        shutil.rmtree(export_dir)
