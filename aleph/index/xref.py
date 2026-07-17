import logging
from datetime import datetime, timezone
from typing import Any, Iterable, TypeAlias

from anystore.types import SDict
from elasticsearch import NotFoundError
from elasticsearch.helpers import scan
from followthemoney.types import registry
from openaleph_search.core import get_es
from openaleph_search.index.indexer import Actions, bulk_actions
from openaleph_search.index.indexes import configure_index
from openaleph_search.index.mapping import Field, FieldType
from openaleph_search.index.util import index_name, index_settings, unpack_result
from openaleph_search.model import SearchAuth
from openaleph_search.query import bool_query
from openaleph_search.settings import Settings

from aleph.model.collection import Collection
from aleph.model.xref import ESEdge, edge_id

log = logging.getLogger(__name__)
settings = Settings()
XREF_SOURCE = {"excludes": ["text", "countries"]}
XREF_VERSION = "v2"

Filters: TypeAlias = list[SDict]


def xref_index():
    return index_name("xref", XREF_VERSION)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


# -- filter helpers ---


def _active_edges_query(filters: Filters | None = None) -> SDict:
    """Build a bool query for active (non-deleted) edges with optional filters."""
    q = bool_query()
    q["bool"]["must_not"].append({"exists": {"field": "deleted_at"}})
    if filters:
        q["bool"]["filter"].extend(filters)
    return q


def exclude_no_judgement() -> SDict:
    """Exclude NO_JUDGEMENT edges (usable as a bool filter clause)"""
    return {"bool": {"must_not": [{"term": {"judgement": "no_judgement"}}]}}


def entities_filter(entity_id: str) -> SDict:
    """Filter by entity id (non directional)"""
    return {"term": {Field.ENTITIES: entity_id}}


def _collections_filter(collection_id: int) -> SDict:
    """Filter by collection id (non directional)"""
    return {"term": {Field.COLLECTION_ID: collection_id}}


def auth_filters(auth: SearchAuth) -> Filters:
    """Auth filters requiring BOTH collections on an xref edge to be readable.

    The multi-value ``collection_id`` field only guarantees that *one* side
    matches.  Filter on the individual fields instead so that edges are only
    visible when the user can read both collections.
    """
    return [
        auth.datasets_query("source_collection_id"),
        auth.datasets_query("target_collection_id"),
    ]


# -- index configuration ---


def configure_xref():
    mapping = {
        "date_detection": False,
        "dynamic": False,
        "properties": {
            # Core Edge fields (nomenklatura-compatible)
            "source": {**FieldType.KEYWORD, "copy_to": Field.ENTITIES},
            "target": {**FieldType.KEYWORD, "copy_to": Field.ENTITIES},
            "judgement": FieldType.KEYWORD,
            "score": {"type": "float"},
            "user": FieldType.KEYWORD,
            "created_at": {"type": "date"},
            "deleted_at": {"type": "date"},
            # Extended metadata
            "source_collection_id": FieldType.KEYWORD,
            "target_collection_id": FieldType.KEYWORD,
            "method": FieldType.KEYWORD,
            "schema": FieldType.KEYWORD,
            "text": FieldType.TEXT,
            # country filter
            registry.country.group: FieldType.KEYWORD,
            # source/target id copy_to "entities"
            Field.ENTITIES: FieldType.KEYWORD,
            # Union of source + target collection IDs (computed by ESEdge._source)
            Field.COLLECTION_ID: FieldType.KEYWORD,
        },
    }
    settings_ = index_settings(settings.index_shards // 5)
    return configure_index(xref_index(), mapping, settings_)


# -- edge write ---


def index_edge(doc: ESEdge, sync: bool = False):
    """Index a single edge document."""
    es = get_es()
    es.index(index=xref_index(), id=doc._id, body=doc._source, refresh=sync)


def bulk_index_edges(docs: Iterable[ESEdge], sync: bool = False):
    """Bulk index edge documents using parallelized bulk_actions."""

    def _actions() -> Actions:
        for doc in docs:
            yield {"_index": xref_index(), "_id": doc._id, "_source": doc._source}

    bulk_actions(_actions(), sync=sync)


def soft_delete_edge(source: str, target: str, sync: bool = False):
    """Soft-delete an edge by setting deleted_at."""
    es = get_es()
    doc_id = edge_id(source, target)
    try:
        es.update(
            index=xref_index(),
            id=doc_id,
            body={"doc": {"deleted_at": _now()}},
            refresh=sync,
        )
    except NotFoundError:
        pass  # Edge may not exist (e.g., during canonical creation)


def remove_nodes(node_ids: Iterable[str], sync: bool = False) -> None:
    """Soft-delete all edges touching any of the given nodes"""
    ids = sorted(set(node_ids))
    if not ids:
        return
    es = get_es()
    q = _active_edges_query([{"terms": {Field.ENTITIES: ids}}])
    es.update_by_query(
        index=xref_index(),
        body={
            "query": q,
            "script": {
                "source": "ctx._source.deleted_at = params.ts",
                "params": {"ts": _now()},
            },
        },
        conflicts="proceed",
        refresh=sync,
    )


def refresh_xref() -> None:
    """Force an index refresh so subsequent searches see all prior writes."""
    es = get_es()
    es.indices.refresh(index=xref_index())


# -- edge read ---


def query_edges(
    filters: list[dict[str, Any]], sort: list[SDict] | None = None, size: int = 10
) -> list[SDict]:
    """Flexible ES query wrapper for edges. Excludes soft-deleted by default."""
    es = get_es()
    query: SDict = {"query": _active_edges_query(filters)}
    if sort:
        query["sort"] = sort
    query["size"] = size
    result = es.search(index=xref_index(), body=query)
    hits = map(unpack_result, result.get("hits", {}).get("hits", []))
    return [h for h in hits if h is not None]


def scan_edges(filters: Filters, include_deleted: bool = False) -> Iterable[ESEdge]:
    """Scroll/scan for bulk reads of edges."""
    es = get_es()
    if include_deleted:
        q = bool_query()
        if filters:
            q["bool"]["filter"].extend(filters)
    else:
        q = _active_edges_query(filters)
    for res in scan(es, index=xref_index(), query={"query": q}):
        doc = unpack_result(res)
        if doc is not None:
            yield ESEdge(**doc)


def count_edges(filters: Filters | None = None) -> int:
    """Count active (non-deleted) edges."""
    es = get_es()
    result = es.count(index=xref_index(), body={"query": _active_edges_query(filters)})
    return result.get("count", 0)


def scan_node_ids(filters: Filters | None = None) -> Iterable[str]:
    """Iterate all distinct node IDs from active edges via composite aggregation."""
    es = get_es()
    query = _active_edges_query(filters)
    after = None
    while True:
        agg: SDict = {
            "unique_nodes": {
                "composite": {
                    "size": 10000,
                    "sources": [{"node": {"terms": {"field": Field.ENTITIES}}}],
                },
            }
        }
        if after is not None:
            agg["unique_nodes"]["composite"]["after"] = after
        body: SDict = {"query": query, "size": 0, "aggs": agg}
        result = es.search(index=xref_index(), body=body)
        buckets = (
            result.get("aggregations", {}).get("unique_nodes", {}).get("buckets", [])
        )
        if not buckets:
            break
        for bucket in buckets:
            yield bucket["key"]["node"]
        after = buckets[-1]["key"]


def iter_edges(
    collection: Collection, auth: SearchAuth | None = None
) -> Iterable[ESEdge]:
    """Scan all matching xref results for export. Backcompat wrapper."""
    filters = [_collections_filter(collection.id)]
    if auth is not None:
        filters.extend(auth_filters(auth))
    yield from scan_edges(filters)


# -- bulk operations ---


def delete_xref(
    collection: Collection | None = None,
    entity_id: str | None = None,
    sync: bool = False,
):
    """Delete xref edges involving a collection or entity (hard delete)."""
    es = get_es()
    filters = []
    if collection is not None:
        filters.append(_collections_filter(collection.id))
    if entity_id is not None:
        filters.append(entities_filter(entity_id))
    if filters:
        q = bool_query()
        q["bool"]["filter"].extend(filters)
    else:
        q = {"match_all": {}}
    es.delete_by_query(
        index=xref_index(),
        body={"query": q},
        refresh=sync,
        conflicts="proceed",
    )


def prune_edges(user: str | None = None, sync: bool = False) -> None:
    """Hard-delete all NO_JUDGEMENT edges."""
    es = get_es()
    q = bool_query()
    q["bool"]["filter"].append({"term": {"judgement": "no_judgement"}})
    if user is not None:
        q["bool"]["filter"].append({"term": {"user": user}})
    es.delete_by_query(
        index=xref_index(),
        body={"query": q},
        refresh=sync,
        conflicts="proceed",
    )
