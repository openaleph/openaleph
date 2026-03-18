import logging
from datetime import datetime, timezone
from typing import Any, Iterable, TypeAlias

from anystore.types import SDict
from elasticsearch.helpers import bulk, scan
from followthemoney.types import registry
from nomenklatura.resolver.identifier import StrIdent
from openaleph_search.core import get_es
from openaleph_search.index.indexes import configure_index
from openaleph_search.index.mapping import Field, FieldType
from openaleph_search.index.util import index_name, index_settings, unpack_result
from openaleph_search.model import SearchAuth
from openaleph_search.settings import Settings

from aleph.model.collection import Collection
from aleph.model.xref import ESEdge, edge_id

log = logging.getLogger(__name__)
settings = Settings()
XREF_SOURCE = {"excludes": ["text", "countries"]}
XREF_VERSION = "v2"
MAX_NAMES = 30

Filters: TypeAlias = list[SDict]


def xref_index():
    return index_name("xref", XREF_VERSION)


def _exclude_deleted(filters: Filters) -> Filters:
    """Apply soft delete filter"""
    return filters + [{"bool": {"must_not": {"exists": {"field": "deleted_at"}}}}]


def _entities_filter(entity_id: str) -> SDict:
    return {"term": {str(registry.entity.group): entity_id}}


def _collections_filter(collection_id: int) -> SDict:
    return {"term": {Field.COLLECTION_ID: collection_id}}


def configure_xref():
    mapping = {
        "date_detection": False,
        "dynamic": False,
        "properties": {
            # Core Edge fields (nomenklatura-compatible)
            "source": {**FieldType.KEYWORD, "copy_to": registry.entity.group},
            "target": {**FieldType.KEYWORD, "copy_to": registry.entity.group},
            "judgement": FieldType.KEYWORD,
            "score": {"type": "float"},
            "user": FieldType.KEYWORD,
            "created_at": {"type": "date"},
            "deleted_at": {"type": "date"},
            # Extended metadata
            "source_collection_id": {
                **FieldType.KEYWORD,
                "copy_to": "collection_id",
            },
            "target_collection_id": {
                **FieldType.KEYWORD,
                "copy_to": "collection_id",
            },
            "method": FieldType.KEYWORD,
            "schema": FieldType.KEYWORD,
            "text": FieldType.TEXT,
            # country filter
            registry.country.group: FieldType.KEYWORD,
            # source/target id copy_to "entities"
            registry.entity.group: FieldType.KEYWORD,
            # source/target coll id copy_to "collection_id"
            Field.COLLECTION_ID: FieldType.KEYWORD,
        },
    }
    settings_ = index_settings(settings.index_shards // 5)
    return configure_index(xref_index(), mapping, settings_)


def index_edge(doc: ESEdge, sync: bool = False):
    """Index a single edge document."""
    es = get_es()
    es.index(
        index=xref_index(),
        id=doc._id,
        body=doc.model_dump(mode="json"),
        refresh=True if sync else False,
    )


def bulk_index_edges(docs: Iterable[ESEdge], sync: bool = False):
    """Bulk index edge documents."""
    es = get_es()
    actions = []
    for doc in docs:
        actions.append(
            {
                "_index": xref_index(),
                "_id": doc._id,
                "_source": doc.model_dump(mode="json"),
            }
        )
        if len(actions) >= 1000:
            bulk(es, actions, refresh=True if sync else False)
            actions = []
    if actions:
        bulk(es, actions, refresh=True if sync else False)


def get_edge_doc(source: StrIdent, target: StrIdent) -> SDict | None:
    """Get an edge document by source/target pair."""
    es = get_es()
    doc_id = edge_id(source, target)
    result = es.get(index=xref_index(), id=doc_id)
    if result is not None:
        return unpack_result(result)


def soft_delete_edge(source: StrIdent, target: StrIdent, sync: bool = False):
    """Soft-delete an edge by setting deleted_at."""
    es = get_es()
    doc_id = edge_id(source, target)
    es.update(
        index=xref_index(),
        id=doc_id,
        body={"doc": {"deleted_at": datetime.now(timezone.utc).isoformat()}},
        refresh=True if sync else False,
    )


def query_edges(filters: list[dict[str, Any]], sort: str | None = None, size: int = 10):
    """Flexible ES query wrapper for edges."""
    # Always exclude soft-deleted edges by default
    es = get_es()
    query = {"query": {"bool": {"filter": _exclude_deleted(filters)}}}
    if sort:
        query["sort"] = sort
    query["size"] = size
    result = es.search(index=xref_index(), body=query)
    hits = map(unpack_result, result.get("hits", {}).get("hits", []))
    return [h for h in hits if h is not None]


def scan_edges(filters: Filters, include_deleted: bool = False) -> Iterable[ESEdge]:
    """Scroll/scan for bulk reads of edges."""
    es = get_es()
    if not include_deleted:
        filters = _exclude_deleted(filters)
    query = {"query": {"bool": {"filter": filters}}}
    for res in scan(es, index=xref_index(), query=query):
        doc = unpack_result(res)
        if doc is not None:
            yield ESEdge(**doc)


def delete_xref(
    collection: Collection, entity_id: str | None = None, sync: bool = False
):
    """Delete xref edges involving a collection or entity (hard delete)."""
    es = get_es()
    if entity_id is not None:
        filter_ = _entities_filter(entity_id)
    else:
        filter_ = _collections_filter(collection.id)
    query = {"filter": filter_}
    es.delete_by_query(
        index=xref_index(),
        body={"query": query},
        refresh=True if sync else False,
        conflicts="proceed",
        # ignore=[404],
    )


def iter_matches(collection: Collection, auth: SearchAuth) -> Iterable[ESEdge]:
    """Scan all matching xref results for export. Backcompat wrapper."""
    filters = [_collections_filter(collection.id), auth.datasets_query()]
    yield from scan_edges(filters)
