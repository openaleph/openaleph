"""Elasticsearch index operations for collections.

Pure ES layer – no resolver registrations, no pydantic schemas,
no caching logic. The resolver registrations live in
``aleph/logic/collections.py``.
"""

import logging

from followthemoney import model
from normality import normalize
from openaleph_search.index.indexer import (
    configure_index,
    delete_safe,
    index_safe,
    query_delete,
)
from openaleph_search.index.indexes import entities_read_index
from openaleph_search.index.mapping import FieldType
from openaleph_search.index.util import (
    index_name,
    index_settings,
)
from openaleph_search.query.util import BoolQuery, bool_query

from aleph.core import es
from aleph.model import Collection, CollectionStatistics, Entity

STATS_FACETS = [
    "schema",
    "names",
    "addresses",
    "phones",
    "emails",
    "countries",
    "languages",
]
log = logging.getLogger(__name__)


def _collection_things_count_query(collection_id: int) -> BoolQuery:
    query = bool_query()
    query["bool"]["must"] = [{"term": {"collection_id": collection_id}}]
    # don't count too much:
    query["bool"]["must_not"] = [
        {"term": {"schema": "Mention"}},
        {"term": {"schema": "Page"}},
    ]
    return query


def collections_index() -> str:
    """Combined index to run all queries against."""
    return index_name("collection", "v1")


def configure_collections():
    mapping = {
        "date_detection": False,
        "dynamic": False,
        "dynamic_templates": [
            {"fields": {"match": "schemata.*", "mapping": {"type": "long"}}}
        ],
        "_source": {"excludes": ["text"]},
        "properties": {
            "label": {
                "type": "text",
                "copy_to": "text",
                "analyzer": "default",
                "fields": {"kw": FieldType.KEYWORD},
            },
            "collection_id": FieldType.KEYWORD,
            "foreign_id": FieldType.KEYWORD_COPY,
            "languages": FieldType.KEYWORD_COPY,
            "countries": FieldType.KEYWORD_COPY,
            "category": FieldType.KEYWORD_COPY,
            "frequency": FieldType.KEYWORD_COPY,
            "summary": {"type": "text", "copy_to": "text", "index": False},
            "publisher": FieldType.KEYWORD_COPY,
            "publisher_url": FieldType.KEYWORD_COPY,
            "data_url": FieldType.KEYWORD_COPY,
            "info_url": FieldType.KEYWORD_COPY,
            "creator_id": FieldType.KEYWORD,
            "team_id": FieldType.KEYWORD,
            "text": {
                "type": "text",
                "analyzer": "default",
                "store": True,
            },
            "casefile": FieldType.BOOL,
            "restricted": FieldType.BOOL,
            "secret": FieldType.BOOL,
            "xref": FieldType.BOOL,
            "contains_ai": FieldType.BOOL,
            "contains_ai_comment": {"type": "text"},
            "taggable": FieldType.BOOL,
            "external": FieldType.BOOL,
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "count": {"type": "long"},
            "schemata": {"dynamic": True, "type": "object"},
        },
    }
    index = collections_index()
    settings = index_settings(shards=1)
    return configure_index(index, mapping, settings)


def index_collection(collection: Collection, sync: bool = False):
    """Index a collection document into ES."""
    if collection.deleted_at is not None:
        return delete_collection_index(collection.id)

    data = collection.to_dict()

    # Count things for the ES document.
    index = entities_read_index(schema=Entity.THING)
    query = _collection_things_count_query(collection.id)
    result = es.count(index=index, body={"query": query})
    data["count"] = result.get("count", 0)

    log.info(
        "[%s] Index: %s (%s things)...",
        collection,
        data.get("label"),
        data.get("count"),
    )
    text = [data.get("label")]
    text.append(normalize(data.get("label")))
    text.append(normalize(data.get("foreign_id")))
    text.append(normalize(data.get("summary")))
    data["text"] = text
    data.pop("id", None)
    return index_safe(collections_index(), collection.id, data, sync=sync)


def compute_collection_statistics(
    collection_id: int, facets: list[str] = STATS_FACETS
) -> CollectionStatistics:
    """Run the ES aggregation query and return a ``CollectionStatistics``."""
    aggs = {}
    for facet in facets:
        # Regarding facet size, 300 would be optimal because it's
        # guaranteed to capture all schemata and countries. But it
        # adds a whole lot to the compute time, so let's see how
        # this goes.
        aggs[facet + ".values"] = {"terms": {"field": facet, "size": 100}}
        aggs[facet + ".total"] = {"cardinality": {"field": facet}}
    query = _collection_things_count_query(collection_id)
    body = {"size": 0, "query": query, "aggs": aggs}
    index = entities_read_index()
    result = es.search(index=index, body=body, request_timeout=3600, timeout="20m")
    results = result.get("aggregations", {})
    facet_data = {}
    for facet in facets:
        buckets = results.get(facet + ".values").get("buckets", [])
        values = {b["key"]: b["doc_count"] for b in buckets}
        total = results.get(facet + ".total", {}).get("value", 0)
        facet_data[facet] = {"values": values, "total": total}
    return CollectionStatistics(collection_id=str(collection_id), **facet_data)


def get_things_count(collection_id: int) -> dict[str, int]:
    """Count of Thing-typed entities per schema for a collection.

    Runs a live ES aggregation via ``compute_collection_statistics``.
    """
    stats = compute_collection_statistics(collection_id, ["schema"])
    things = {}
    for schema_name, count in stats.schema_.values.items():
        schema = model.get(schema_name)
        if schema is not None and schema.is_a(Entity.THING):
            things[schema.name] = count
    return things


def delete_collection_index(collection_id: int, sync: bool = False) -> None:
    """Delete the collection document from ES. Does NOT remove entities."""
    delete_safe(collections_index(), collection_id)


def delete_entities(
    collection_id: int, origin: str | None = None, schema=None, sync: bool = False
):
    """Delete entities from a collection."""
    filters = [{"term": {"collection_id": collection_id}}]
    if origin is not None:
        filters.append({"term": {"origin": origin}})
    query = {"bool": {"filter": filters}}
    query_delete(entities_read_index(schema), query, sync=sync)
