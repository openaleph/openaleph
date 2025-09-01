import time
from collections import defaultdict
from datetime import datetime

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
from aleph.logic.documents import MODEL_ORIGIN, ingest_flush
from aleph.logic.notifications import flush_notifications, publish
from aleph.model import (
    Collection,
    Document,
    Entity,
    EntitySet,
    Events,
    Mapping,
    Permission,
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
        dataset=collection.foreign_id,
    )
    index.update_collection_stats(collection.id)
    update_collection_discovery(collection.id, collection.name)

    cache.set(key, datetime.utcnow().isoformat())
    index.index_collection(collection, sync=sync)


def aggregate_model(collection: Collection, aggregator):
    """Sync up the aggregator from the Aleph domain model."""
    log.debug(
        f"[{collection.foreign_id}] Aggregating model...", dataset=collection.foreign_id
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
        for idx, proxy in enumerate(entities, 1):
            if idx > 0 and idx % 1000 == 0:
                log.debug(
                    "[%s] Index: %s..." % (collection, idx),
                    dataset=collection.name,
                )
            yield proxy
        log.debug(
            "[%s] Indexed %s entities" % (collection, idx),
            dataset=collection.name,
        )

    entities_index.index_bulk(
        collection.name, _generate(), sync=sync, collection_id=collection.id
    )


def reingest_collection(
    collection, job_id=None, index=False, flush=True, include_ingest=False
):
    """Trigger a re-ingest for all documents in the collection. This always indexes."""
    job_id = job_id or Job.random_id()
    if flush:
        ingest_flush(collection, include_ingest=include_ingest)
    for document in Document.by_collection(collection.id):
        proxy = document.to_proxy(ns=collection.ns)
        queue_ingest(collection, proxy, batch=job_id, namespace=collection.foreign_id)


def reindex_collection(
    collection: Collection, skip_errors=True, sync=False, flush=False
):
    """Re-index all entities from the model, mappings and aggregator cache."""
    from aleph.logic.mapping import map_to_aggregator
    from aleph.logic.profiles import profile_fragments

    aggregator = get_aggregator(collection)
    for mapping in collection.mappings:
        if mapping.disabled:
            log.debug(
                "[%s] Skip mapping: %r" % (collection, mapping),
                dataset=collection.foreign_id,
            )
            continue
        try:
            map_to_aggregator(collection, mapping, aggregator)
        except Exception:
            # More or less ignore broken models.
            log.exception("Failed mapping: %r" % mapping, dataset=collection.foreign_id)
    aggregate_model(collection, aggregator)
    profile_fragments(collection, aggregator)
    if flush:
        log.debug("[%s] Flushing..." % collection, dataset=collection.foreign_id)
        index.delete_entities(collection.id, sync=True)
    index_aggregator(collection, aggregator, skip_errors=skip_errors, sync=sync)
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
                dataset=collection.foreign_id,
            )
            return
        log.info(
            f"[{dataset}] Waiting for collection tasks to finish ...",
            dataset=collection.foreign_id,
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
