import time
from collections import defaultdict
from datetime import datetime
from typing import Generator

from anystore.logging import get_logger
from followthemoney.dataset.util import dataset_name_check
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


def index_aggregator(
    collection: Collection,
    aggregator,
    entity_ids=None,
    skip_errors=False,
    sync=False,
    schema=None,
):
    def _generate():
        idx = 0
        entities = aggregator.iterate(
            entity_id=entity_ids, skip_errors=skip_errors, schema=schema
        )

        # Batch fetch all tags for all entities at once
        tags_map = defaultdict(set)
        if entity_ids:
            tags_query = db.session.query(Tag).filter(
                Tag.entity_id.in_(entity_ids), Tag.collection_id == collection.id
            )
            for tag in tags_query.all():
                tags_map[tag.entity_id].add(tag.tag)
        else:
            # If no specific entity_ids, prefetch all tags for the collection
            tags_query = db.session.query(Tag).filter(
                Tag.collection_id == collection.id
            )
            for tag in tags_query.all():
                tags_map[tag.entity_id].add(tag.tag)

        # Now iterate through entities and add tags
        for idx, proxy in enumerate(entities, 1):
            if idx > 0 and idx % 1000 == 0:
                log.debug(
                    f"[{collection}] Index: {idx}...",
                    dataset=collection.name,
                )

            # Add tags to entity context if any exist
            if proxy.id in tags_map:
                proxy.context["tags"] = list(tags_map[proxy.id])

            yield proxy
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


def _get_diff_reindex_batches(
    collection: Collection, batch_size: int = 10_000
) -> Generator[list[str], None, None]:
    """Get batches of entity IDs that need reindexing in diff-only mode.

    Yields batches of entity IDs that exist in the aggregator but not in the index.

    Args:
        collection: The collection to check
        batch_size: Size of each batch (default: 10,000)

    Yields:
        Lists of entity IDs to reindex, up to batch_size per list
    """
    batch = []
    total_missing = 0

    for aggregator_id, index_id in index_diff(collection):
        # Entity is in aggregator but not in index - needs reindexing
        if index_id is None and aggregator_id is not None:
            batch.append(aggregator_id)
            total_missing += 1

            if len(batch) >= batch_size:
                log.info(
                    f"[{collection}] Diff-only mode: found batch of {len(batch)} "
                    f"entities missing from index (total so far: {total_missing})",
                    dataset=collection.name,
                )
                yield batch
                batch = []

    # Yield remaining items in the last partial batch
    if batch:
        log.info(
            f"[{collection}] Diff-only mode: found {total_missing} entities "
            f"total missing from index",
            dataset=collection.name,
        )
        yield batch
    elif total_missing == 0:
        log.info(
            f"[{collection}] Diff-only mode: no entities missing from index",
            dataset=collection.name,
        )


def _index_batch(
    collection: Collection,
    entity_ids: list[str],
    queue_batches: bool | None = False,
    skip_errors: bool | None = True,
    sync: bool | None = False,
    schema: str | None = None,
) -> None:
    aggregator = get_aggregator(collection)
    if queue_batches:
        log.info(
            f"[{collection}] Queuing batch ({len(entity_ids)} entities)",
            dataset=collection.name,
        )
        queue_index_batch(collection, entity_ids)
    else:
        log.info(
            f"[{collection}] Processing batch ({len(entity_ids)} entities)",
            dataset=collection.name,
        )
        index_aggregator(
            collection,
            aggregator,
            entity_ids=entity_ids,
            skip_errors=bool(skip_errors),
            sync=bool(sync),
            schema=schema,
        )


def _process_batches(
    collection: Collection,
    entity_ids: list[str] | None,
    batch_size: int,
    queue_batches: bool,
    skip_errors: bool,
    sync: bool,
    schema: str | None = None,
):
    """Process entities in batches."""
    aggregator = get_aggregator(collection)
    if entity_ids:
        batches = (
            entity_ids[i : i + batch_size]
            for i in range(0, len(entity_ids), batch_size)
        )
    else:
        batches = aggregator.get_sorted_id_batches(batch_size, schema=schema)

    for batch in batches:
        _index_batch(collection, batch, queue_batches, skip_errors, sync, schema)


def reindex_collection(
    collection: Collection,
    skip_errors=True,
    sync=False,
    flush=False,
    diff_only=False,
    model=True,
    mappings=True,
    queue_batches=False,
    batch_size=10_000,
    schema=None,
):
    """Re-index all entities from the model, mappings and aggregator cache.

    Args:
        collection: The collection to reindex
        skip_errors: Skip entities that fail to index
        sync: Wait for index operations to complete
        flush: Delete all existing entities from index before reindexing
        diff_only: Only reindex entities that are in aggregator but not in index
        model: Aggregate model from database (Entities, Documents) before indexing
        mappings: Process collection mappings and aggregate to the aggregator
        queue_batches: Queue batches for parallelization
        schema: Filter entities by schema (e.g., Person, Company)
    """
    from aleph.logic.profiles import profile_fragments

    aggregator = get_aggregator(collection)
    if mappings:
        _process_mappings(collection, aggregator)
    if model:
        aggregate_model(collection, aggregator)
    profile_fragments(collection, aggregator)

    if flush:
        log.debug(f"[{collection}] Flushing...", dataset=collection.name)
        index.delete_entities(collection.id, sync=True)

    # Handle diff-only mode separately - it yields batches directly
    if diff_only:
        batches = _get_diff_reindex_batches(collection, batch_size=batch_size)
        has_batches = False
        for batch in batches:
            has_batches = True
            _index_batch(collection, batch, queue_batches, skip_errors, sync, schema)

        if not has_batches:
            log.info(
                f"[{collection}] Diff-only mode: no entities to reindex",
                dataset=collection.name,
            )

        if not queue_batches:
            compute_collection(collection, force=True)
        return

    # Regular reindex mode
    _process_batches(
        collection, None, batch_size, queue_batches, skip_errors, sync, schema
    )
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


def upgrade_collections():
    for collection in Collection.all(deleted=True):
        if collection.deleted_at is not None:
            delete_collection(collection, keep_metadata=True, sync=True)
        else:
            compute_collection(collection, force=True)
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
                dataset=collection.name,
            )

    if invalid_collections:
        log.error(
            f"Found {len(invalid_collections)} collections with invalid foreign_ids"
        )
        return invalid_collections
    else:
        log.info("All collection foreign_ids are valid")
        return []


def index_diff(  # noqa: C901
    collection,
) -> Generator[tuple[str | None, str | None], None, None]:
    """Compare entity IDs between aggregator and search index.

    This returns a tuple generator with (aggregator_id, index_id) (which are the
    same) or if 1 of the values is None, it means the entity is missing either
    in the aggregator or in the index.
    """
    log.info(
        f"[{collection.name}] Streaming sorted entity ID tuples from aggregator and index...",
        dataset=collection.name,
    )
    aggregator = get_aggregator(collection)
    aggregator_ids = aggregator.get_sorted_ids()
    index_ids = entities_index.iter_entity_ids(collection_id=collection.id, sort="_id")

    while True:
        aggregator_id = next(aggregator_ids, None)
        index_id = next(index_ids, None)

        # we have nothing
        if aggregator_id is None and index_id is None:
            return
        # end of aggregator ids
        elif aggregator_id is None:
            yield None, index_id
            # yield remaining index ids
            while True:
                try:
                    yield None, next(index_ids)
                except StopIteration:
                    return

        # end of index ids:
        elif index_id is None:
            yield aggregator_id, None
            # yield remaining aggregator ids
            while True:
                try:
                    yield next(aggregator_ids), None
                except StopIteration:
                    return

        # same id in both stores
        elif aggregator_id == index_id:
            yield aggregator_id, index_id

        else:
            # id in aggregator but not in index
            if aggregator_id < index_id:
                # catch up with missing ids
                while aggregator_id != index_id:
                    yield aggregator_id, None
                    aggregator_id = next(aggregator_ids, None)
                    if aggregator_id is None:
                        break
            # id in index but not in aggregator
            elif aggregator_id > index_id:
                # catch up with missing ids
                while aggregator_id != index_id:
                    yield None, index_id
                    index_id = next(index_ids, None)
                    if index_id is None:
                        break
