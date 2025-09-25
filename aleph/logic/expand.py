import logging

from banal import ensure_list
from followthemoney import model
from followthemoney.graph import Node
from followthemoney.types import registry
from openaleph_search.index.entities import ENTITY_SOURCE
from openaleph_search.index.indexes import entities_read_index
from openaleph_search.index.util import unpack_result
from openaleph_search.query.util import field_filter_query, schema_query

from aleph.authz import Authz
from aleph.core import es
from aleph.logic.graph import Graph
from aleph.model import Entity
from aleph.settings import SETTINGS
from aleph.util import get_entity_proxy

log = logging.getLogger(__name__)
DEFAULT_TAGS = set(registry.pivots)
DEFAULT_TAGS.remove(registry.entity)
FILTERS_COUNT_LIMIT = SETTINGS.INDEX_EXPAND_CLAUSE_LIMIT


def _expand_properties(proxies, properties):
    properties = ensure_list(properties)
    props = set()
    for proxy in ensure_list(proxies):
        for prop in proxy.schema.properties.values():
            if prop.type != registry.entity:
                continue
            if len(properties) and prop.name not in properties:
                continue
            props.add(prop)
    return props


def _expand_adjacent(graph, proxy, prop):
    """Return all proxies related to the given proxy/prop combo as an array.
    This creates the very awkward return format for the API, which simply
    gives you a list of entities and lets the UI put them in some meaningful
    relation. Gotta revise this some day...."""
    # Too much effort to do this right. This works, too:
    adjacent = set()
    node = Node.from_proxy(proxy)
    for edge in graph.get_adjacent(node, prop=prop):
        for part in (edge.proxy, edge.source.proxy, edge.target.proxy):
            if part is not None and part != proxy:
                adjacent.add(part)
    return adjacent


def expand_proxies(proxies, authz, properties=None, limit=0):
    """Expand an entity's graph to find adjacent entities that are connected
    by a property (eg: Passport entity linked to a Person) or an Entity type
    edge (eg: Person connected to Company through Directorship).

    properties: list of FtM Properties to expand as edges.
    limit: max number of entities to return
    """
    graph = Graph(edge_types=(registry.entity,))
    for proxy in proxies:
        graph.add(proxy)

    queries = {}
    entity_ids = [proxy.id for proxy in proxies]
    # First, find all the entities pointing to the current one via a stub
    # property. This will return the intermediate edge entities in some
    # cases - then we'll use graph.resolve() to get the far end of the
    # edge.
    for prop in _expand_properties(proxies, properties):
        if not prop.stub:
            continue
        field = "properties.%s" % prop.reverse.name
        queries[(prop.reverse.schema, prop.qname)] = field_filter_query(
            field, entity_ids
        )

    entities, counts = _counted_msearch(queries, authz, limit=limit)
    for entity in entities:
        graph.add(get_entity_proxy(entity))

    if limit > 0:
        graph.resolve()

    results = []
    for prop in _expand_properties(proxies, properties):
        # For stub properties, we need to sum counts across all schemas for this property
        count = 0
        if prop.stub:
            # Sum counts from all relevant schemas
            for schema_key, schema_count in counts.items():
                if schema_key == prop.qname:
                    count += schema_count
        else:
            count = sum(len(p.get(prop)) for p in proxies)

        entities = set()
        for proxy in proxies:
            entities.update(_expand_adjacent(graph, proxy, prop))

        if count > 0:
            item = {
                "property": prop.name,
                "count": count,
                "entities": entities,
            }
            results.append(item)

    # pprint(results)
    return results


def entity_tags(proxy, authz: Authz, prop_types=DEFAULT_TAGS):
    """For a given proxy, determine how many other mentions exist for each
    property value associated, if it is one of a set of types."""
    queries = {}
    lookup = {}
    values = set()
    for prop, value in proxy.itervalues():
        if prop.type not in prop_types:
            continue
        if not prop.matchable:
            continue
        if prop.specificity(value) > 0.1:
            values.add((prop.type, value))

    type_names = [t.name for t in prop_types]
    log.debug("Tags[%s]: %s values", type_names, len(values))
    for type_, value in values:
        key = type_.node_id(value)
        lookup[key] = (type_, value)
        # Determine which schemata may contain further mentions (only things).
        schemata = model.get_type_schemata(type_)
        schemata = [s for s in schemata if s.is_a(Entity.THING)]
        for schema in schemata:
            queries[(schema, key)] = field_filter_query(type_.group, value)

    _, counts = _counted_msearch(queries, authz)
    results = []
    for key, count in counts.items():
        if count > 1:
            type_, value = lookup[key]
            result = {
                "id": key,
                "field": type_.group,
                "value": value,
                "count": count - 1,
            }
            results.append(result)

    results.sort(key=lambda p: p["count"], reverse=True)
    # pprint(results)
    return results


def _counted_msearch(queries, authz: Authz, limit=0):
    """Run batched queries to count or retrieve entities with certain property values.
    Groups queries by Elasticsearch index to optimize performance."""
    search_auth = authz.search_auth

    # Group queries by index since multiple schemas share the same index
    grouped = {}
    for (schema, key), query in sorted(queries.items()):
        index = entities_read_index(schema)
        group_key = (index, key)

        if group_key not in grouped:
            grouped[group_key] = {
                "index": index,
                "schemas": {schema},
                "filters": [query],
                "counts": {key: query},
            }
        else:
            grouped[group_key]["schemas"].add(schema)
            grouped[group_key]["filters"].append(query)
            grouped[group_key]["counts"][key] = query

    log.debug("Counts: %s queries, %s groups", len(queries), len(grouped))

    body = []
    for group in grouped.values():
        index = {"index": group.get("index")}
        schemas = group.get("schemas")
        filters = group.get("filters")
        counts = list(group.get("counts").items())

        # Having too many filters in a single query increase heap memory
        # usage in ElasticSearch. This can lead to OOM errors in the worst
        # case. So we group the filters into smaller batches.
        while len(filters) > 0:
            filters_batch = filters[:FILTERS_COUNT_LIMIT]
            filters = filters[FILTERS_COUNT_LIMIT:]
            counts_batch = dict(counts[:FILTERS_COUNT_LIMIT])
            counts = counts[FILTERS_COUNT_LIMIT:]

            # Skip this batch if there are no counts to aggregate
            if not counts_batch:
                continue

            # Build the filter query with auth, schema and property constraints
            query_filters = [
                search_auth.datasets_query(),
                schema_query(schemas, include_descendants=True),
            ]

            if len(filters_batch) > 1:
                # Multiple property filters should be OR'd together
                query_filters.append(
                    {"bool": {"should": filters_batch, "minimum_should_match": 1}}
                )
            else:
                # Single filter can be added directly
                query_filters.extend(filters_batch)

            query = {
                "size": limit,
                "query": {"bool": {"filter": query_filters}},
                "aggs": {"counts": {"filters": {"filters": counts_batch}}},
                "_source": ENTITY_SOURCE,
            }
            body.append(index)
            body.append(query)

    log.debug("Counts: %s grouped queries", len(body) // 2)

    if not body:
        return [], {}

    response = es.msearch(body=body)

    # Note: We don't track which query each entity came from. This is fine for current
    # usage since expand_proxies uses graph traversal to find relationships, and
    # entity_tags only needs the aggregation counts.
    counts = {}
    entities = []
    for resp in response.get("responses", []):
        for result in resp.get("hits", {}).get("hits", []):
            entities.append(unpack_result(result))
        buckets = resp.get("aggregations", {}).get("counts", {}).get("buckets", {})
        for key, count in buckets.items():
            doc_count = count.get("doc_count", 0)
            # Don't overwrite existing positive counts with zeros from other schema batches
            if key not in counts or doc_count > 0:
                counts[key] = doc_count
    return entities, counts
