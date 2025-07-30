import logging
from typing import TypedDict

from servicelayer.jobs import Dataset, Job
from servicelayer.rate_limit import RateLimit

from aleph.core import kv
from aleph.model.collection import Collection

log = logging.getLogger(__name__)

OP_INGEST = "ingest"
OP_ANALYZE = "analyze"
OP_INDEX = "index"
OP_XREF = "xref"
OP_REINGEST = "reingest"
OP_REINDEX = "reindex"
OP_LOAD_MAPPING = "loadmapping"
OP_FLUSH_MAPPING = "flushmapping"
OP_EXPORT_SEARCH = "exportsearch"
OP_EXPORT_XREF = "exportxref"
OP_UPDATE_ENTITY = "updateentity"
OP_PRUNE_ENTITY = "pruneentity"

NO_COLLECTION = "null"


def dataset_from_collection(collection):
    """servicelayer dataset from a collection"""
    if collection is None:
        return NO_COLLECTION
    return str(collection.id)


def get_dataset_collection_id(dataset):
    """Invert the servicelayer dataset into a collection ID"""
    if dataset == NO_COLLECTION:
        return None
    return int(dataset)


def get_rate_limit(resource, limit=100, interval=60, unit=1):
    return RateLimit(kv, resource, limit=limit, interval=interval, unit=unit)


def get_stage(collection, stage, job_id=None):
    dataset = dataset_from_collection(collection)
    job_id = job_id or Job.random_id()
    job = Job(kv, dataset, job_id)
    return job.get_stage(stage)


def get_status(collection):
    dataset = dataset_from_collection(collection)
    return Dataset(kv, dataset).get_status()


def get_active_dataset_status():
    data = Dataset.get_active_dataset_status(kv)
    return data


class Context(TypedDict):
    languages: list[str]
    ftmstore: str
    namespace: str


def get_context(collection: Collection) -> Context:
    """Set some task context variables that configure the ingestors."""
    from aleph.logic.aggregator import get_aggregator_name

    return {
        "languages": [x for x in collection.languages if x],
        "ftmstore": get_aggregator_name(collection),
        "namespace": collection.foreign_id,
    }


def cancel_queue(collection):
    dataset = dataset_from_collection(collection)
    Dataset(kv, dataset).cancel()


def ingest_entity(collection, proxy, job_id=None, index=True):
    """Send the given entity proxy to the ingest-file service."""
    log.debug("Ingest entity [%s]: %s", proxy.id, proxy.caption)

    from aleph.procrastinate.queues import queue_ingest

    context = get_context(collection)
    queue_ingest(collection, proxy, job_id=job_id, **context)


def pipeline_entity(collection, proxy, job_id=None):
    """Send an entity through the ingestion pipeline, minus the ingestor itself."""
    log.debug("Pipeline entity [%s]: %s", proxy.id, proxy.caption)

    from aleph.procrastinate.queues import queue_analyze

    context = get_context(collection)
    queue_analyze(collection, proxy, job_id=job_id, **context)
