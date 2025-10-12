import time
from collections import defaultdict
from datetime import datetime

from anystore.logging import get_logger
from followthemoney.dataset.util import dataset_name_check
from openaleph_procrastinate.manage import cancel_jobs
from openaleph_procrastinate.settings import OPENALEPH_MANAGEMENT_QUEUE
from openaleph_search.index import entities as entities_index
from servicelayer.jobs import Job
from sqlalchemy import distinct, select

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
from aleph.procrastinate.queues import queue_cancel_collection, queue_ingest
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
    log.debug(
        f"[{collection.foreign_id}] Aggregating model...", dataset=collection.name
    )
    aggregator.delete(origin=MODEL_ORIGIN)
    writer = aggregator.bulk()
    for document in Document.by_collection(collection.id):
        proxy = document.to_proxy(ns=collection.ns)
        writer.put(proxy, fragment="db", origin=MODEL_ORIGIN)
    for entity in Entity.by_collection(collection.id):
        proxy = entity.to_proxy()
        aggregator.delete(entity_id=proxy.id)
        writer.put(proxy, fragment="db", origin=MODEL_ORIGIN)
    writer.flush()


def index_aggregator(
    collection: Collection, aggregator, entity_ids=None, skip_errors=False, sync=False
):
    def _generate():
        idx = 0
        entities = aggregator.iterate(entity_id=entity_ids, skip_errors=skip_errors)

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
        collection.name, _generate(), sync=sync, collection_id=collection.id
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


def reindex_collection(
    collection: Collection, skip_errors=True, sync=False, flush=False, diff_only=False
):
    """Re-index all entities from the model, mappings and aggregator cache.

    Args:
        collection: The collection to reindex
        skip_errors: Skip entities that fail to index
        sync: Wait for index operations to complete
        flush: Delete all existing entities from index before reindexing
        diff_only: Only reindex entities that are in aggregator but not in index
    """
    from aleph.logic.mapping import map_to_aggregator
    from aleph.logic.profiles import profile_fragments

    aggregator = get_aggregator(collection)
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
    aggregate_model(collection, aggregator)
    profile_fragments(collection, aggregator)

    if flush:
        log.debug(f"[{collection}] Flushing...", dataset=collection.name)
        index.delete_entities(collection.id, sync=True)

    # Determine which entities to index
    entity_ids = None
    if diff_only:
        diff = index_diff(collection)
        # If index is empty, just do a full reindex
        if not diff["index_ids"]:
            log.info(
                f"[{collection}] Diff-only mode: index is empty, doing full reindex",
                dataset=collection.name,
            )
        else:
            entity_ids = list(diff["only_in_aggregator"])
            if entity_ids:
                log.info(
                    f"[{collection}] Diff-only mode: reindexing {len(entity_ids)} "
                    f"entities missing from index",
                    dataset=collection.name,
                )
            else:
                log.info(
                    f"[{collection}] Diff-only mode: no entities to reindex",
                    dataset=collection.name,
                )
                compute_collection(collection, force=True)
                return

    # Batch entity_ids to avoid large SQL IN clauses (PostgreSQL best practice: ~10k items)
    if entity_ids and len(entity_ids) > 10000:
        batch_size = 10000
        total_batches = (len(entity_ids) + batch_size - 1) // batch_size
        log.info(
            f"[{collection}] Batching {len(entity_ids)} entities into "
            f"{total_batches} batches of {batch_size}",
            dataset=collection.name,
        )
        for i in range(0, len(entity_ids), batch_size):
            batch = entity_ids[i : i + batch_size]
            batch_num = (i // batch_size) + 1
            log.info(
                f"[{collection}] Processing batch {batch_num}/{total_batches} "
                f"({len(batch)} entities)",
                dataset=collection.name,
            )
            index_aggregator(
                collection,
                aggregator,
                entity_ids=batch,
                skip_errors=skip_errors,
                sync=sync,
            )
    else:
        index_aggregator(
            collection,
            aggregator,
            entity_ids=entity_ids,
            skip_errors=skip_errors,
            sync=sync,
        )
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


def index_diff(collection):
    """Compare entity IDs between aggregator and search index.

    Returns a dictionary with the following keys:
    - aggregator_ids: set of entity IDs in the aggregator
    - index_ids: set of entity IDs in the index
    - only_in_aggregator: set of entity IDs only in aggregator
    - only_in_index: set of entity IDs only in index
    - in_both: set of entity IDs in both
    """
    log.info(
        f"[{collection}] Fetching entity IDs from aggregator...",
        dataset=collection.name,
    )
    aggregator = get_aggregator(collection)
    # Use direct SQL query to fetch distinct entity IDs efficiently
    query = select(distinct(aggregator.table.c.id))
    with aggregator.store.engine.connect() as conn:
        result = conn.execute(query)
        aggregator_ids = {row[0] for row in result}
    log.info(
        f"[{collection}] Found {len(aggregator_ids)} entities in aggregator",
        dataset=collection.name,
    )

    log.info(
        f"[{collection}] Fetching entity IDs from search index...",
        dataset=collection.name,
    )
    index_ids = set(entities_index.iter_entity_ids(collection_id=collection.id))
    log.info(
        f"[{collection}] Found {len(index_ids)} entities in index",
        dataset=collection.name,
    )

    # Calculate differences
    only_in_aggregator = aggregator_ids - index_ids
    only_in_index = index_ids - aggregator_ids
    in_both = aggregator_ids & index_ids

    return {
        "aggregator_ids": aggregator_ids,
        "index_ids": index_ids,
        "only_in_aggregator": only_in_aggregator,
        "only_in_index": only_in_index,
        "in_both": in_both,
    }
