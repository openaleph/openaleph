from collections import defaultdict
from typing import Any

from followthemoney import Property, model
from openaleph_search import EntitiesQuery, SearchQueryParser
from openaleph_search.model import SearchAuth

from aleph.core import cache
from aleph.model import Collection
from aleph.model.discover import (
    DatasetDiscovery,
    MentionedTerms,
    SignificantTerms,
    Term,
)

ANALYZABLE = model["Analyzable"]
PROPS = (
    ANALYZABLE.properties["peopleMentioned"],
    ANALYZABLE.properties["companiesMentioned"],
    ANALYZABLE.properties["locationMentioned"],
    ANALYZABLE.properties["namesMentioned"],
)
MAX_TERMS = 10


def _prop_agg_key(prop: Property, suffix: str | None = "values") -> str:
    return f"properties.{prop.name}.{suffix or 'values'}"


def _unpack_buckets(agg: dict[str, Any], ignore_term: str) -> MentionedTerms:
    data: dict[str, list[Term]] = defaultdict(list)
    for prop in PROPS:
        key = _prop_agg_key(prop, "significant_terms")
        buckets = agg.get(key, {}).get("buckets", [])
        for bucket in buckets:
            if bucket["key"] != ignore_term:
                data[prop.name].append(
                    Term(name=bucket["key"], count=bucket["doc_count"])
                )
    return MentionedTerms(**dict(data))


def _discovery_key(collection_id: int) -> str:
    return cache.object_key(Collection, collection_id, "discovery")


def get_collection_discovery(collection_id: int, dataset: str) -> DatasetDiscovery:
    """Retrieve cached discovery analysis for a collection."""
    key = _discovery_key(collection_id)
    data = cache.get_complex(key)
    if data is not None:
        return DatasetDiscovery(**data)
    # regenerate and update cache
    return update_collection_discovery(collection_id, dataset)


def update_collection_discovery(collection_id: int, dataset: str) -> DatasetDiscovery:
    """Compute and cache discovery analysis for a collection."""
    q_terms = [("facet_significant", f"properties.{p.name}") for p in PROPS] + [
        (f"facet_significant_size:properties.{p.name}", MAX_TERMS) for p in PROPS
    ]
    q_facets = [("facet", f"properties.{prop.name}") for prop in PROPS] + [
        (f"facet_size:properties.{prop.name}", MAX_TERMS) for prop in PROPS
    ]
    base_args = [
        ("filter:collection_id", collection_id),
        ("limit", 0),
    ]

    # authz = Authz.from_role(Role.load_cli_user())
    # we avoid the db call here (due to potential transaction timeout after very
    # long running tasks) and assume that the permission check is already done
    # somewhere up in the context before calling `update_collections_discovery`
    search_auth = SearchAuth(is_admin=True)

    # get most mentioned thingy names
    parser = SearchQueryParser([*base_args, *q_facets], auth=search_auth)
    query = EntitiesQuery(parser)
    result = query.search()
    aggregations = result.get("aggregations", {})

    data: dict[str, list[SignificantTerms]] = defaultdict(list)

    # expand each for significant terms
    if aggregations:
        for prop in PROPS:
            key = _prop_agg_key(prop)
            for bucket in aggregations.get(key, {}).get("buckets", []):
                sub_parser = SearchQueryParser(
                    [*base_args, *q_terms, ("filter:names", bucket["key"])],
                    auth=search_auth,
                )
                sub_result = EntitiesQuery(sub_parser).search()
                mentioned_terms = _unpack_buckets(
                    sub_result.get("aggregations", {}), ignore_term=bucket["key"]
                )
                terms = SignificantTerms(
                    term=Term(name=bucket["key"], count=bucket["doc_count"]),
                    **mentioned_terms.model_dump(),
                )
                data[prop.name].append(terms)

    discovery = DatasetDiscovery(name=dataset, **data)
    cache.set_complex(
        _discovery_key(collection_id), discovery.model_dump(), expires=cache.EXPIRE
    )
    return discovery
