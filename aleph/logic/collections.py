import itertools
import time
from collections import defaultdict
from datetime import datetime
from typing import Generator, Iterable

from anystore.logging import get_logger
from followthemoney.dataset.util import dataset_name_check
from ftmq.aggregate import EntityDict, aggregate_fragments_unsafe
from ftmq.store.fragments.dataset import Fragments, IdRange
from openaleph_procrastinate.manage import cancel_jobs
from openaleph_procrastinate.settings import OPENALEPH_MANAGEMENT_QUEUE
from openaleph_search.index import entities as entities_index
from servicelayer.jobs import Job

from aleph.authz import Authz
from aleph.core import cache, db
from aleph.index import collections as index
from aleph.index import xref as xref_index
from aleph.logic.aggregator import get_aggregator, get_aggregator_name
from aleph.logic.discover import update_collection_discovery
from aleph.logic.documents import (
    MODEL_ORIGIN,
)
from aleph.logic.documents import index_flush as _index_flush
from aleph.logic.documents import ingest_flush as _ingest_flush
from aleph.logic.notifications import flush_notifications, publish
from aleph.model import (
    Collection,
    Document,
    Entity,
    EntitySet,
    Events,
    Mapping,
    Permission,
    Tag,
)
from aleph.procrastinate.queues import (
    queue_cancel_collection,
    queue_index_batch,
    queue_ingest,
)
from aleph.procrastinate.status import get_collection_status

log = get_logger(__name__)


def create_collection(data, authz, sync=False):
    now = datetime.utcnow()
    collection = Collection.create(data, authz, created_at=now)
    if collection.created_at == now:
        publish(
            Events.CREATE_COLLECTION,
            params={"collection": collection},
            channels=[collection, authz.role],
            actor_id=authz.id,
        )
    db.session.commit()
    return update_collection(collection, sync=sync)


def update_collection(collection, sync=False):
    """Update a collection and re-index."""
    Authz.flush()
    refresh_collection(collection.id)
    return index.index_collection(collection, sync=sync)


def refresh_collection(collection_id):
    """Operations to execute after updating a collection-related
    domain object. This will refresh stats and flush cache."""
    cache.kv.delete(
        cache.object_key(Collection, collection_id),
        cache.object_key(Collection, collection_id, "stats"),
        cache.object_key(Collection, collection_id, "discovery"),
    )


def get_deep_collection(collection):
    mappings = Mapping.by_collection(collection.id).count()
    entitysets = EntitySet.type_counts(collection_id=collection.id)
    status = get_collection_status(collection)
    if status is not None:
        status = status.model_dump(mode="json")
    return {
        "statistics": index.get_collection_stats(collection.id),
        "counts": {"mappings": mappings, "entitysets": entitysets},
        "status": status,
        "shallow": False,
    }


def compute_collections():
    """Update collection caches, including the global stats cache."""
    authz = Authz.from_role(None)
    schemata = defaultdict(int)
    countries = defaultdict(int)
    categories = defaultdict(int)

    for collection in Collection.all():
        compute_collection(collection)

        if authz.can(collection.id, authz.READ):
            categories[collection.category] += 1
            things = index.get_collection_things(collection.id)
            for schema, count in things.items():
                schemata[schema] += count
            for country in collection.countries:
                countries[country] += 1

    log.info("Updating global statistics cache...")
    data = {
        "collections": sum(categories.values()),
        "schemata": dict(schemata),
        "countries": dict(countries),
        "categories": dict(categories),
        "things": sum(schemata.values()),
    }
    key = cache.key(cache.STATISTICS)
    cache.set_complex(key, data, expires=cache.EXPIRE)


def compute_collection(collection: Collection, force=False, sync=False):
    key = cache.object_key(Collection, collection.id, "stats")
    if cache.get(key) is not None and not force:
        return
    refresh_collection(collection.id)
    log.info(
        f"[{collection.foreign_id}] Computing statistics...",
        dataset=collection.name,
    )
    index.update_collection_stats(collection.id)
    update_collection_discovery(collection.id, collection.name)

    cache.set(key, datetime.utcnow().isoformat())
    index.index_collection(collection, sync=sync)


def aggregate_model(collection: Collection, aggregator):
    """Sync up the aggregator from the Aleph domain model."""
    log.info(f"[{collection.foreign_id}] Aggregating model...", dataset=collection.name)
    aggregator.delete(origin=MODEL_ORIGIN)
    writer = aggregator.bulk()
    for ix, document in enumerate(Document.by_collection(collection.id), 1):
        if ix % 10_000 == 0:
            log.info(f"[model aggregate] Document {ix} ...")
        proxy = document.to_proxy(ns=collection.ns)
        writer.put(proxy, fragment="db", origin=MODEL_ORIGIN)
    for ix, entity in enumerate(Entity.by_collection(collection.id), 1):
        if ix % 10_000 == 0:
            log.info(f"[model aggregate] Entity {ix} ...")
        proxy = entity.to_proxy()
        aggregator.delete(entity_id=proxy.id)
        writer.put(proxy, fragment="db", origin=MODEL_ORIGIN)
    writer.flush()


def _iter_entity_data(
    aggregator: Fragments,
    entity_ids: Iterable[str] | None = None,
    skip_errors: bool = False,
    id_range: IdRange | None = None,
) -> Generator[EntityDict, None, None]:
    """Merge the trusted fragments of the aggregator into entity dicts, as
    `Fragments.iterate` but without the `EntityProxy` roundtrip."""
    if entity_ids is not None:
        fragments = aggregator.fragments(entity_ids=entity_ids)
        yield from aggregate_fragments_unsafe(fragments, skip_errors=skip_errors)
        return
    # sorted id ranges as `Fragments.iterate_batched`: a full sort is too slow
    ranges = [id_range] if id_range is not None else aggregator.get_id_ranges()
    for range_ in ranges:
        fragments = aggregator.fragments(id_range=range_)
        yield from aggregate_fragments_unsafe(fragments, skip_errors=skip_errors)


def index_aggregator(
    collection: Collection,
    aggregator: Fragments,
    entity_ids: Iterable[str] | None = None,
    skip_errors: bool = False,
    sync: bool = False,
    id_range: IdRange | None = None,
) -> None:
    # no schema filter: entities are always merged from all their fragments
    def _generate() -> Generator[EntityDict, None, None]:
        idx = 0
        entities = _iter_entity_data(aggregator, entity_ids, skip_errors, id_range)
        # tags by the ids seen: the aleph database may sort ids differently
        # than the aggregator, so an id range can't select them
        for chunk in itertools.batched(entities, 1000):
            tags_map = defaultdict(set)
            tags_query = db.session.query(Tag).filter(
                Tag.entity_id.in_([data["id"] for data in chunk]),
                Tag.collection_id == collection.id,
            )
            for tag in tags_query.all():
                tags_map[tag.entity_id].add(tag.tag)

            for data in chunk:
                # Add tags to entity context if any exist
                if data["id"] in tags_map:
                    data["tags"] = list(tags_map[data["id"]])
                yield data
            idx += len(chunk)
            log.debug(
                f"[{collection}] Index: {idx}...",
                dataset=collection.name,
            )
        log.debug(
            f"[{collection}] Indexed {idx} entities",
            dataset=collection.name,
        )

    entities_index.index_bulk(
        collection.name,
        _generate(),
        sync=sync,
        collection_id=collection.id,
    )


def reingest_collection(collection, job_id=None, index_flush=True, ingest_flush=True):
    """Trigger a re-ingest for all documents in the collection. By default, this
    flushes ingested entities from ftm store, flushes the index (with origin
    "ingest,analyze") and (always) indexes the new ingested entities."""
    job_id = job_id or Job.random_id()
    if ingest_flush:
        _ingest_flush(collection)
    if index_flush:
        _index_flush(collection)
    for document in Document.by_collection(collection.id):
        proxy = document.to_proxy(ns=collection.ns)
        queue_ingest(collection, proxy, batch=job_id, namespace=collection.foreign_id)


def _process_mappings(collection: Collection, aggregator):
    """Process collection mappings and aggregate to the aggregator."""
    from aleph.logic.mapping import map_to_aggregator

    for mapping in collection.mappings:
        if mapping.disabled:
            log.debug(
                f"[{collection}] Skip mapping: {mapping!r}",
                dataset=collection.name,
            )
            continue
        try:
            map_to_aggregator(collection, mapping, aggregator)
        except Exception:
            # More or less ignore broken models.
            log.exception(f"Failed mapping: {mapping!r}", dataset=collection.name)


def _index_batch(
    collection: Collection,
    entity_ids: list[str] | None = None,
    id_range: IdRange | None = None,
    queue_batches: bool | None = False,
    skip_errors: bool | None = True,
    sync: bool | None = False,
) -> None:
    aggregator = get_aggregator(collection)
    if id_range is not None:
        batch = f"ids {id_range.after} - {id_range.last}"
    else:
        batch = f"{len(entity_ids or [])} entities"
    if queue_batches:
        log.info(
            f"[{collection}] Queuing batch ({batch})",
            dataset=collection.name,
        )
        queue_index_batch(collection, entity_ids=entity_ids, id_range=id_range)
    else:
        log.info(
            f"[{collection}] Processing batch ({batch})",
            dataset=collection.name,
        )
        index_aggregator(
            collection,
            aggregator,
            entity_ids=entity_ids,
            skip_errors=bool(skip_errors),
            sync=bool(sync),
            id_range=id_range,
        )


def reindex_collection(
    collection: Collection,
    skip_errors: bool = True,
    sync: bool = False,
    flush: bool = False,
    model: bool = True,
    mappings: bool = True,
    profiles: bool = True,
    queue_batches: bool = False,
    batch_size: int = 10_000,
    origin: str | None = None,
) -> None:
    """Re-index all entities from the model, mappings and aggregator cache.

    Args:
        collection: The collection to reindex
        skip_errors: Skip entities that fail to index
        sync: Wait for index operations to complete
        flush: Delete all existing entities from index before reindexing
        model: Aggregate model from database (Entities, Documents) before indexing
        mappings: Process collection mappings and aggregate to the aggregator
        profiles: Process profile fragments and aggregate to the aggregator
        queue_batches: Queue batches for parallelization
        origin: Filter entities by aggregator origin (e.g., 'xref', 'aleph')
    """
    from aleph.logic.profiles import profile_fragments

    aggregator = get_aggregator(collection)
    if mappings:
        _process_mappings(collection, aggregator)
    if model:
        aggregate_model(collection, aggregator)
    if profiles:
        profile_fragments(collection, aggregator)

    if flush:
        log.debug(f"[{collection}] Flushing...", dataset=collection.name)
        index.delete_entities(collection.id, sync=True)

    options = {"queue_batches": queue_batches, "skip_errors": skip_errors, "sync": sync}
    if origin is None:
        for id_range in aggregator.get_id_ranges(batch_size):
            _index_batch(collection, id_range=id_range, **options)
    else:
        # only the ids with fragments of `origin`, a range holds every id
        for batch in aggregator.get_sorted_id_batches(batch_size, origin=origin):
            _index_batch(collection, entity_ids=batch, **options)
    if not queue_batches:
        compute_collection(collection, force=True)


def delete_collection(collection, keep_metadata=False, sync=False):
    deleted_at = collection.deleted_at or datetime.utcnow()
    queue_cancel_collection(collection)
    aggregator = get_aggregator(collection)
    aggregator.delete()
    flush_notifications(collection, sync=sync)
    index.delete_entities(collection.id, sync=sync)
    xref_index.delete_xref(collection, sync=sync)
    Mapping.delete_by_collection(collection.id)
    EntitySet.delete_by_collection(collection.id, deleted_at)
    Entity.delete_by_collection(collection.id)
    Document.delete_by_collection(collection.id)
    if not keep_metadata:
        Permission.delete_by_collection(collection.id)
        collection.delete(deleted_at=deleted_at)
    db.session.commit()
    if not keep_metadata:
        index.delete_collection(collection.id, sync=True)
        aggregator.drop()
    refresh_collection(collection.id)
    Authz.flush()


def upgrade_collections(cleanup_external: bool = False):
    for collection in Collection.all(deleted=True):
        if collection.deleted_at is not None:
            delete_collection(collection, keep_metadata=True, sync=True)
        else:
            compute_collection(collection, force=True)
        # destroy local ftm store for external collections
        if cleanup_external and collection.external:
            aggregator = get_aggregator(collection)
            aggregator.drop()
    # update global cache:
    compute_collections()


def collection_is_active(collection: Collection) -> bool:
    status = get_collection_status(collection, include_collection_data=False)
    if status is None:
        return False
    for batch in status.batches:
        for queue in batch.queues:
            if queue.name != OPENALEPH_MANAGEMENT_QUEUE and queue.active:
                return True
    return False


def cancel_collection(collection: Collection):
    """Cancel current collection processing and wait for all running tasks to
    finish."""
    dataset = get_aggregator_name(collection)
    cancel_jobs(dataset=dataset)
    start = time.time()
    while collection_is_active(collection):
        if time.time() - start > 3600:
            log.warn(
                f"[{dataset}] Giving up waiting for finish after 1 hour.",
                dataset=collection.name,
            )
            return
        log.info(
            f"[{dataset}] Waiting for collection tasks to finish ...",
            dataset=collection.name,
        )
        time.sleep(30)


def validate_collection_foreign_ids():
    """Validate that all Collection foreign_ids are valid dataset names using
    dataset_name_check from followthemoney.dataset.util. This is used during
    transition phase from OpenAleph 4/5 to 6."""

    invalid_collections = []

    for collection in Collection.all(deleted=True):
        try:
            dataset_name_check(collection.foreign_id)
        except Exception as e:
            invalid_collections.append(
                {
                    "id": collection.id,
                    "foreign_id": collection.foreign_id,
                    "label": collection.label,
                    "error": str(e),
                    "deleted_at": collection.deleted_at,
                }
            )
            log.warning(
                f"Invalid foreign_id for collection {collection.id}: {collection.foreign_id} - {e}",  # noqa: B950
                dataset=collection.foreign_id,
            )

    if invalid_collections:
        log.error(
            f"Found {len(invalid_collections)} collections with invalid foreign_ids"
        )
        return invalid_collections
    else:
        log.info("All collection foreign_ids are valid")
        return []
