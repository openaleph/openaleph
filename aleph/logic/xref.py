import logging
import shutil
import typing
from dataclasses import dataclass
from functools import cache
from tempfile import mkdtemp
from timeit import default_timer

import followthemoney
from followthemoney import E, compare, model
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
from aleph.index.collections import delete_entities
from aleph.index.xref import delete_xref, index_matches, iter_matches
from aleph.logic import resolver
from aleph.logic.aggregator import get_aggregator
from aleph.logic.collections import reindex_collection
from aleph.logic.export import complete_export
from aleph.logic.util import entity_url
from aleph.model import Collection, Entity, EntitySet, Export, Role, Status
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
    buckets=[
        # Listing 0 as a separate bucket size because it's interesting to know
        # what percentage of entities result in no matches at all
        0,
        5,
        10,
        25,
        50,
    ],
)

XREF_CANDIDATES_QUERY_DURATION = Histogram(
    "aleph_xref_candidates_query_duration_seconds",
    "Processing duration of the candidates query (excl. network, serialization etc.)",
)

XREF_CANDIDATES_QUERY_ROUNDTRIP_DURATION = Histogram(
    "aleph_xref_candidates_query_roundtrip_duration_seconds",
    "Roundtrip duration of the candidates query (incl. network, serialization etc.)",
)


@cache
def _get_nk_algorithm() -> type[ScoringAlgorithm] | None:
    if SETTINGS.XREF_ALGORITHM is not None:
        return get_algorithm(SETTINGS.XREF_ALGORITHM)


NK_SCORING_CONFIG = ScoringConfig.defaults()


@dataclass
class Match:
    score: float
    method: str
    entity: EntityProxy
    collection_id: str
    match: EntityProxy
    entityset_ids: typing.Sequence[str]
    doubt: typing.Optional[float] = None


def _bulk_compare_ftm(proxies):
    for left, right in proxies:
        score = compare.compare(left, right)
        yield score, None, FTM_VERSION_STR


def _bulk_compare_ftmc_model(proxies):
    for score, confidence in zip(*MODEL.predict_proba_std(proxies)):
        yield score, confidence, MODEL.version


def _bulk_compare_nomenklatura(
    proxies: list[tuple[E, E]],
) -> typing.Generator[tuple[float, None, str]]:
    algorithm = _get_nk_algorithm()
    if algorithm is not None:
        for entity, candidate in proxies:
            result = algorithm.compare(entity, candidate, NK_SCORING_CONFIG)
            yield result.score, None, algorithm.NAME


def _bulk_compare(proxies):
    if not proxies:
        return
    if _get_nk_algorithm() is not None:
        yield from _bulk_compare_nomenklatura(proxies)
        return
    if SETTINGS.XREF_MODEL is None:
        yield from _bulk_compare_ftm(proxies)
        return
    global MODEL
    if MODEL is None:
        try:
            with open(SETTINGS.XREF_MODEL, "rb") as fd:
                MODEL = GLMBernoulli2EEvaluator.from_pickles(fd.read())
        except FileNotFoundError:
            log.exception(f"Could not find model file: {SETTINGS.XREF_MODEL}")
            SETTINGS.XREF_MODEL = None
            yield from _bulk_compare_ftm(proxies)
            return
    yield from _bulk_compare_ftmc_model(proxies)


def _merge_schemata(proxy, schemata):
    for other in schemata:
        try:
            other = model.get(other)
            proxy.schema = model.common_schema(proxy.schema, other)
        except InvalidData:
            proxy.schema = model.get(Entity.LEGAL_ENTITY)


def _query_item(entity, entitysets=True):
    """Cross-reference an entity or document, given as an indexed document."""
    query = match_query(entity)
    if query == none_query():
        return

    entityset_ids = EntitySet.entity_entitysets(entity.id) if entitysets else []
    query = {"query": query, "size": 50, "_source": ENTITY_SOURCE}
    schemata = list(entity.schema.matchable_schemata)
    index = entities_read_index(schema=schemata, expand=False)

    start_time = default_timer()
    result = es.search(index=index, body=query)
    roundtrip_duration = max(0, default_timer() - start_time)
    query_duration = result.get("took")
    if query_duration is not None:
        # ES returns milliseconds, but we track query time in seconds
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

    results = _bulk_compare([(entity, c) for c in candidates])
    match_count = 0
    for match, (score, doubt, method) in zip(candidates, results):
        log.debug(
            "Match: %s: %s <[%.2f]@%0.2f> %s",
            method,
            entity.caption,
            score or 0.0,
            doubt or 0.0,
            match.caption,
        )
        if score > 0:
            yield Match(
                score=score,
                doubt=doubt,
                method=method,
                entity=entity,
                collection_id=match.context.get("collection_id"),
                match=match,
                entityset_ids=entityset_ids,
            )
        if score > SCORE_CUTOFF:
            # While we store all xref matches with a score > 0, we only count matches
            # with a score above a threshold. This is in line with the user-facing behavior
            # which also only shows matches above the threshold.
            match_count += 1

    XREF_ENTITIES.inc()
    XREF_MATCHES.observe(match_count)
    XREF_CANDIDATES_QUERY_ROUNDTRIP_DURATION.observe(roundtrip_duration)
    if query_duration:
        XREF_CANDIDATES_QUERY_DURATION.observe(query_duration)


def _iter_mentions(collection):
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


def _query_mentions(collection):
    aggregator = get_aggregator(collection, origin=ORIGIN)
    aggregator.delete(origin=ORIGIN)
    writer = aggregator.bulk()
    for proxy in _iter_mentions(collection):
        schemata = set()
        countries = set()
        for match in _query_item(proxy, entitysets=False):
            schemata.add(match.match.schema)
            countries.update(match.match.get_type_values(registry.country))
            match.entityset_ids = []
            yield match
        if len(schemata):
            # Assign only those countries that are backed by one of
            # the matches:
            countries = countries.intersection(proxy.get("country"))
            proxy.set("country", countries)
            # Try to be more specific about schema:
            _merge_schemata(proxy, schemata)
            # Pick a principal name:
            proxy = name_entity(proxy)
            proxy.context["mutable"] = True
            log.debug("Reifying [%s]: %s", proxy.schema.name, proxy)
            writer.put(proxy, fragment="mention")
            # pprint(proxy.to_dict())
    writer.flush()


def _query_entities(collection):
    """Generate matches for indexing."""
    log.info("[%s] Generating entity-based xref...", collection)
    matchable = [s.name for s in model if s.matchable]
    for proxy in iter_proxies(
        collection_id=collection.id,
        schemata=matchable,
        es_scroll=SETTINGS.XREF_SCROLL,
        es_scroll_size=SETTINGS.XREF_SCROLL_SIZE,
    ):
        yield from _query_item(proxy)


def xref_entity(collection, proxy):
    """Cross-reference a single proxy in the context of a collection."""
    if not proxy.schema.matchable:
        return
    log.info("[%s] Generating xref: %s...", collection, proxy.id)
    delete_xref(collection, entity_id=proxy.id, sync=True)
    index_matches(collection, _query_item(proxy))


def xref_collection(collection):
    """Cross-reference all the entities and documents in a collection."""
    log.info(
        f"[{collection}] xref_collection scroll settings: scroll={SETTINGS.XREF_SCROLL}, "
        f"scroll_size={SETTINGS.XREF_SCROLL_SIZE}"
    )
    log.info(f"[{collection}] Clearing previous xref state....")
    delete_xref(collection, sync=True)
    delete_entities(collection.id, origin=ORIGIN, sync=True)
    index_matches(collection, _query_entities(collection))
    index_matches(collection, _query_mentions(collection))
    log.info(f"[{collection}] Xref done, re-indexing to reify mentions...")
    reindex_collection(collection, sync=False, model=False)


def _format_date(proxy):
    dates = proxy.get_type_values(registry.date)
    if not len(dates):
        return ""
    return min(dates)


def _format_country(proxy):
    countries = [c.upper() for c in proxy.countries]
    return ", ".join(countries)


def _iter_match_batch(stub, sheet, batch):
    matchable = [s.name for s in model if s.matchable]
    entities = set()
    for match in batch:
        entities.add(match.get("entity_id"))
        entities.add(match.get("match_id"))
        resolver.queue(stub, Collection, match.get("match_collection_id"))

    resolver.resolve(stub)
    entities = resolver.cached_entities_by_ids(list(entities), schemata=matchable)
    entities = {e.get("id"): e for e in entities}

    for obj in batch:
        entity = entities.get(str(obj.get("entity_id")))
        match = entities.get(str(obj.get("match_id")))
        collection_id = obj.get("match_collection_id")
        collection = resolver.get(stub, Collection, collection_id)
        if entity is None or match is None or collection is None:
            continue
        eproxy = make_entity_proxy(entity)
        mproxy = make_entity_proxy(match)
        sheet.append(
            [
                obj.get("score"),
                obj.get("doubt"),
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
            "Doubt",
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

        for match in iter_matches(collection.name, authz.search_auth):
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
