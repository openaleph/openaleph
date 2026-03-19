"""
Cross-reference processing logic. Moved from aleph/logic/xref.py.

Handles entity comparison, scoring, and match generation for xref.
"""

import logging
import shutil
from dataclasses import dataclass
from functools import cache
from tempfile import mkdtemp
from timeit import default_timer
from typing import Generator, Iterable, TypeAlias, TypedDict

import followthemoney
from followthemoney import E, Schema, compare, model
from followthemoney.exc import InvalidData
from followthemoney.export.excel import ExcelWriter
from followthemoney.helpers import name_entity
from followthemoney.proxy import EntityProxy
from followthemoney.types import registry
from followthemoney_compare.models import GLMBernoulli2EEvaluator
from nomenklatura.matching import ScoringConfig, get_algorithm
from nomenklatura.matching.types import ScoringAlgorithm
from openaleph_search.index.entities import ENTITY_SOURCE, iter_proxies
from openaleph_search.index.indexes import entities_read_index
from openaleph_search.index.util import unpack_result
from openaleph_search.query import none_query
from openaleph_search.query.matching import match_query
from openaleph_search.settings import BULK_PAGE
from prometheus_client import Counter, Histogram
from servicelayer.archive.util import ensure_path

from aleph.authz import Authz
from aleph.core import db, es
from aleph.index.xref import iter_edges
from aleph.logic import resolver
from aleph.logic.aggregator import get_aggregator
from aleph.logic.collections import reindex_collection
from aleph.logic.export import complete_export
from aleph.logic.util import entity_url
from aleph.logic.xref.resolver import ElasticsearchResolver, get_resolver
from aleph.model import Collection, Entity, Export, Role, Status
from aleph.settings import SETTINGS
from aleph.util import make_entity_proxy

log = logging.getLogger(__name__)
ORIGIN = "xref"
MODEL = None
FTM_VERSION_STR = f"ftm-{followthemoney.__version__}"
SCORE_CUTOFF = 0.5

XREF_ENTITIES = Counter(
    "aleph_xref_entities_total",
    "Total number of entities and mentions that have been xref'ed",
)

XREF_MATCHES = Histogram(
    "aleph_xref_matches",
    "Number of matches per xref'ed entity or mention",
    buckets=[0, 5, 10, 25, 50],
)

XREF_CANDIDATES_QUERY_DURATION = Histogram(
    "aleph_xref_candidates_query_duration_seconds",
    "Processing duration of the candidates query (excl. network, serialization etc.)",
)

XREF_CANDIDATES_QUERY_ROUNDTRIP_DURATION = Histogram(
    "aleph_xref_candidates_query_roundtrip_duration_seconds",
    "Roundtrip duration of the candidates query (incl. network, serialization etc.)",
)

Result: TypeAlias = tuple[float, float | None, str]


class Suggestion(TypedDict):
    left_id: str | None
    right_id: str | None
    score: float
    user: str | None
    source_collection_id: int | None
    target_collection_id: int | None
    method: str | None
    schema: str
    text: list[str]
    countries: list[str]


MAX_NAMES = 30


@cache
def _get_nk_algorithm() -> type[ScoringAlgorithm] | None:
    if SETTINGS.XREF_ALGORITHM is not None:
        return get_algorithm(SETTINGS.XREF_ALGORITHM)


NK_SCORING_CONFIG = ScoringConfig.defaults()


def _load_model():
    """Load the FTM-compare ML model, falling back to None on failure."""
    global MODEL
    if MODEL is not None:
        return MODEL
    try:
        with open(SETTINGS.XREF_MODEL, "rb") as fd:
            MODEL = GLMBernoulli2EEvaluator.from_pickles(fd.read())
        return MODEL
    except FileNotFoundError:
        log.exception(f"Could not find model file: {SETTINGS.XREF_MODEL}")
        SETTINGS.XREF_MODEL = None
        return None


# -- Public API --


def compare_entities(left: E, right: E) -> Result:
    """Compare two entities using the configured algorithm/model.

    Returns (score, confidence, method).
    Dispatch: nomenklatura algorithm > ML model > followthemoney compare.
    """
    algorithm = _get_nk_algorithm()
    if algorithm is not None:
        result = algorithm.compare(left, right, NK_SCORING_CONFIG)
        return result.score, None, algorithm.NAME
    if SETTINGS.XREF_MODEL is not None and _load_model() is not None:
        score, confidence = next(zip(*MODEL.predict_proba_std([(left, right)])))
        return score, confidence, MODEL.version
    return compare.compare(left, right), None, FTM_VERSION_STR


def make_suggestion(
    left: EntityProxy,
    right: EntityProxy,
    source_collection_id: int | None = None,
    target_collection_id: int | None = None,
    user: str | None = None,
    score: float | None = None,
    method: str | None = None,
) -> Suggestion:
    """Compare two entities and build a suggestion dict.

    The returned dict can be passed directly to resolver.suggest(**suggestion).
    If score/method are provided, skips re-comparing (used by batch xref).
    """
    if score is None:
        score, _, method = compare_entities(left, right)
    text = set([left.caption, right.caption])
    text.update(left.get_type_values(registry.name)[:MAX_NAMES])
    text.update(right.get_type_values(registry.name)[:MAX_NAMES])
    text.discard(None)
    countries = set(left.get_type_values(registry.country))
    countries.update(right.get_type_values(registry.country))
    return {
        "left_id": left.id,
        "right_id": right.id,
        "score": score,
        "user": user,
        "source_collection_id": source_collection_id,
        "target_collection_id": target_collection_id,
        "method": method,
        "schema": right.schema.name,
        "text": list(text),
        "countries": list(countries),
    }


# -- Internal --


@dataclass
class Match:
    score: float
    method: str
    entity: EntityProxy
    collection_id: str
    match: EntityProxy


Matches: TypeAlias = Generator[Match, None, None]


def _merge_schemata(proxy: EntityProxy, schemata: Iterable[Schema]):
    for other in schemata:
        try:
            other = model.get(other)
            proxy.schema = model.common_schema(proxy.schema, other)
        except InvalidData:
            proxy.schema = model[Entity.LEGAL_ENTITY]


def _query_item(entity: EntityProxy) -> Matches:
    """Cross-reference an entity or document, given as an indexed document."""
    query = match_query(entity)
    if query == none_query():
        return

    query = {"query": query, "size": 50, "_source": ENTITY_SOURCE}
    schemata = list(entity.schema.matchable_schemata)
    index = entities_read_index(schema=schemata, expand=False)

    start_time = default_timer()
    result = es.search(index=index, body=query)
    roundtrip_duration = max(0, default_timer() - start_time)
    query_duration = result.get("took")
    if query_duration is not None:
        query_duration = result.get("took") / 1000

    candidates = []
    for hit in result.get("hits").get("hits"):
        hit = unpack_result(hit)
        if hit is None:
            continue
        candidate = make_entity_proxy(hit)
        candidates.append(candidate)
    log.debug(
        "Candidate [%s]: %s: %d possible matches",
        entity.schema.name,
        entity.caption,
        len(candidates),
    )

    match_count = 0
    for candidate in candidates:
        score, _, method = compare_entities(entity, candidate)
        log.debug(
            "Match: %s: %s <[%.2f]> %s",
            method,
            entity.caption,
            score or 0.0,
            candidate.caption,
        )
        if score > 0:
            yield Match(
                score=score,
                method=method,
                entity=entity,
                collection_id=candidate.context["collection_id"],
                match=candidate,
            )
        if score > SCORE_CUTOFF:
            match_count += 1

    XREF_ENTITIES.inc()
    XREF_MATCHES.observe(match_count)
    XREF_CANDIDATES_QUERY_ROUNDTRIP_DURATION.observe(roundtrip_duration)
    if query_duration:
        XREF_CANDIDATES_QUERY_DURATION.observe(query_duration)


def _iter_mentions(collection: Collection) -> Generator[EntityProxy, None, None]:
    """Combine mentions into pseudo-entities used for xref."""
    log.info("[%s] Generating mention-based xref...", collection)
    proxy = model.make_entity(Entity.LEGAL_ENTITY)
    for mention in iter_proxies(
        collection_id=collection.id,
        schemata=["Mention"],
        sort={"properties.resolved": "desc"},
        es_scroll=SETTINGS.XREF_SCROLL,
        es_scroll_size=SETTINGS.XREF_SCROLL_SIZE,
    ):
        resolved_id = mention.first("resolved")
        if resolved_id != proxy.id:
            if proxy.id is not None:
                yield proxy
            proxy = model.make_entity(Entity.LEGAL_ENTITY)
            proxy.id = resolved_id
        _merge_schemata(proxy, mention.get("detectedSchema"))
        proxy.add("name", mention.get("name"))
        proxy.add("country", mention.get("contextCountry"))
    if proxy.id is not None:
        yield proxy


def _suggest_match(
    collection: Collection, xref_resolver: ElasticsearchResolver, match: Match
):
    """Convert a Match object into a resolver.suggest() call."""
    suggestion = make_suggestion(
        match.entity,
        match.match,
        source_collection_id=collection.id,
        target_collection_id=int(match.collection_id),
        score=match.score,
        method=match.method,
    )
    xref_resolver.suggest(**suggestion)


def _query_mentions(collection: Collection, xref_resolver: ElasticsearchResolver):
    aggregator = get_aggregator(collection, origin=ORIGIN)
    aggregator.delete(origin=ORIGIN)
    writer = aggregator.bulk()
    for proxy in _iter_mentions(collection):
        schemata = set()
        countries = set()
        for match in _query_item(proxy):
            schemata.add(match.match.schema)
            countries.update(match.match.get_type_values(registry.country))
            _suggest_match(collection, xref_resolver, match)
        if len(schemata):
            countries = countries.intersection(proxy.get("country"))
            proxy.set("country", countries)
            _merge_schemata(proxy, schemata)
            proxy = name_entity(proxy)
            log.debug("Reifying [%s]: %s", proxy.schema.name, proxy)
            writer.put(proxy, fragment="mention")
    writer.flush()


def _query_entities(collection: Collection, xref_resolver: ElasticsearchResolver):
    """Generate matches for indexing."""
    log.info("[%s] Generating entity-based xref...", collection)
    matchable = [s.name for s in model if s.matchable]
    for proxy in iter_proxies(
        collection_id=collection.id,
        schemata=matchable,
        es_scroll=SETTINGS.XREF_SCROLL,
        es_scroll_size=SETTINGS.XREF_SCROLL_SIZE,
    ):
        for match in _query_item(proxy):
            _suggest_match(collection, xref_resolver, match)


def xref_entity(collection: Collection, proxy: EntityProxy):
    """Cross-reference a single proxy in the context of a collection."""
    if not proxy.schema.matchable:
        return
    log.info("[%s] Generating xref: %s...", collection, proxy.id)

    xref_resolver = get_resolver()
    for match in _query_item(proxy):
        _suggest_match(collection, xref_resolver, match)


def xref_collection(collection: Collection):
    """Cross-reference all the entities and documents in a collection."""
    log.info(
        f"[{collection}] xref_collection scroll settings: scroll={SETTINGS.XREF_SCROLL}, "
        f"scroll_size={SETTINGS.XREF_SCROLL_SIZE}"
    )
    log.info(f"[{collection}] Running xref (upsert mode, no deletion)...")
    xref_resolver = get_resolver()

    _query_entities(collection, xref_resolver)
    _query_mentions(collection, xref_resolver)

    log.info(f"[{collection}] Xref done, re-indexing to reify mentions...")
    reindex_collection(
        collection,
        sync=False,
        model=False,
        mappings=False,
        origin=ORIGIN,
    )


def _format_date(proxy: EntityProxy) -> str:
    dates = proxy.get_type_values(registry.date)
    if not len(dates):
        return ""
    return min(dates)


def _format_country(proxy: EntityProxy) -> str:
    countries = [c.upper() for c in proxy.countries]
    return ", ".join(countries)


def _iter_match_batch(stub, sheet, batch):
    matchable = [s.name for s in model if s.matchable]
    entities = set()
    for match in batch:
        entities.add(match.get("source"))
        entities.add(match.get("target"))
        resolver.queue(stub, Collection, match.get("target_collection_id"))

    resolver.resolve(stub)
    entities = resolver.cached_entities_by_ids(list(entities), schemata=matchable)
    entities = {e.get("id"): e for e in entities}

    for obj in batch:
        entity = entities.get(str(obj.get("source")))
        match = entities.get(str(obj.get("target")))
        collection_id = obj.get("target_collection_id")
        collection = resolver.get(stub, Collection, collection_id)
        if entity is None or match is None or collection is None:
            continue
        eproxy = make_entity_proxy(entity)
        mproxy = make_entity_proxy(match)
        sheet.append(
            [
                obj.get("score"),
                eproxy.caption,
                _format_date(eproxy),
                _format_country(eproxy),
                collection.get("label"),
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
