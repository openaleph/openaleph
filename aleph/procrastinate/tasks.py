"""
Tasks handled by procrastinate that can be triggered from other programs
"""

import functools

from anystore.logging import get_logger
from openaleph_procrastinate import defer
from openaleph_procrastinate.app import make_app
from openaleph_procrastinate.exceptions import InvalidJob
from openaleph_procrastinate.model import DatasetJob, Job
from openaleph_procrastinate.settings import OPENALEPH_MANAGEMENT_QUEUE
from openaleph_procrastinate.tasks import task
from procrastinate import builtin_tasks

from aleph.core import create_app
from aleph.logic import (
    alerts,
    collections,
    entities,
    export,
    mapping,
    notifications,
    roles,
    xref,
)
from aleph.logic.aggregator import get_aggregator
from aleph.model.collection import Collection
from aleph.procrastinate.util import ensure_collection

app = make_app(__loader__.name)
aleph_flask_app = create_app()
log = get_logger(__name__)


def aleph_task(original_func=None, **kwargs):
    """
    extend @openaleph_procrastinate.tasks.task decorator to ensure aleph app
    context for task runtime and getting the collection_id from the dataset
    foreign_id
    """

    def wrap(func):
        def new_func(*job_args, **job_kwargs):
            with aleph_flask_app.app_context():
                job = job_args[0]
                if isinstance(job, DatasetJob):
                    job_kwargs["collection"] = ensure_collection(job.dataset)
                return func(*job_args, **job_kwargs)

        wrapped_func = functools.update_wrapper(new_func, func, updated=())
        # @openaleph_procrastinate.tasks.task
        return task(app=app, **kwargs)(wrapped_func)

    if not original_func:
        return wrap

    return wrap(original_func)


@aleph_task(retry=defer.tasks.index.max_retries)
def index_entities(job: DatasetJob, collection: Collection) -> None:
    entity_ids = set(e.id for e in job.get_entities())
    aggregator = get_aggregator(collection)
    collections.index_aggregator(collection, aggregator, entity_ids)
    collections.refresh_collection(collection.id)


@aleph_task(retry=defer.tasks.reindex.max_retries)
def reindex_collection(job: DatasetJob, collection: Collection) -> None:
    flush = job.payload.get("context", {}).get("flush", False)
    collections.reindex_collection(collection, bool(flush))
    collections.refresh_collection(collection.id)


@aleph_task(retry=defer.tasks.xref.max_retries)
def xref_collection(job: DatasetJob, collection: Collection) -> None:
    xref.xref_collection(collection)
    collections.refresh_collection(collection.id)


@aleph_task(retry=defer.tasks.cancel_dataset.max_retries)
def cancel_dataset(job: DatasetJob, collection: Collection) -> None:
    collections.cancel_collection(collection)
    collections.refresh_collection(collection.id)


@aleph_task(retry=defer.tasks.load_mapping.max_retries)
def load_mapping(job: DatasetJob, collection: Collection) -> None:
    mapping_id = job.payload.get("context", {}).get("mapping_id", None)
    sync = job.payload.get("context", {}).get("sync", False)
    if not mapping_id:
        job.log.error("No mapping ID provided for load_mapping")
        raise InvalidJob
    mapping.load_mapping(collection, mapping_id, bool(sync))
    collections.refresh_collection(collection.id)


@aleph_task(retry=defer.tasks.flush_mapping.max_retries)
def flush_mapping(job: DatasetJob, collection: Collection) -> None:
    mapping_id = job.payload.get("context", {}).get("mapping_id", None)
    sync = job.payload.get("context", {}).get("sync", True)
    if not mapping_id:
        job.log.error("No mapping ID provided for flush_mapping")
        raise InvalidJob
    mapping.flush_mapping(collection, mapping_id, bool(sync))
    collections.refresh_collection(collection.id)


@aleph_task(retry=defer.tasks.update_entity.max_retries)
def update_entity(job: DatasetJob, collection: Collection) -> None:
    entity_id = job.payload.get("context", {}).get("entity_id", None)
    if not entity_id:
        job.log.error("No entity ID provided for update_entity")
        raise InvalidJob
    entities.update_entity(collection, entity_id)
    collections.refresh_collection(collection.id)


@aleph_task(retry=defer.tasks.prune_entity.max_retries)
def prune_entity(job: DatasetJob, collection: Collection) -> None:
    entity_id = job.payload.get("context", {}).get("entity_id", None)
    if not entity_id:
        job.log.error("No entity ID provided for prune_entity")
        raise InvalidJob
    entities.prune_entity(collection, entity_id)
    collections.refresh_collection(collection.id)


@aleph_task(retry=defer.tasks.export_search.max_retries)
def export_search(job: Job) -> None:
    export_id = job.payload.get("context", {}).get("export_id", None)
    if not export_id:
        job.log.error("No export ID provided for export_search")
        raise InvalidJob
    export.export_entities(export_id)


@aleph_task(retry=defer.tasks.export_xref.max_retries)
def export_xref(job: DatasetJob, collection: Collection) -> None:
    export_id = job.payload.get("context", {}).get("export_id", None)
    if not export_id:
        job.log.error("No export ID provided for Export XREF")
        raise InvalidJob
    xref.export_matches(export_id)
    collections.refresh_collection(collection.id)


# every 5 minutes
@app.periodic(cron="*/5 * * * *")
@app.task(queue=OPENALEPH_MANAGEMENT_QUEUE, queueing_lock="periodic-clean-compute")
def periodic_clean_and_compute(timestamp: int):
    with aleph_flask_app.app_context():
        collections.compute_collections()


# every 15 minutes
@app.periodic(cron="*/15 * * * *")
@app.task(queue=OPENALEPH_MANAGEMENT_QUEUE, queueing_lock="periodic-retry-stalled")
async def periodic_retry_stalled(timestamp: int):
    # https://procrastinate.readthedocs.io/en/stable/howto/production/retry_stalled_jobs.html
    stalled_jobs = await app.job_manager.get_stalled_jobs()
    jobs = 0
    for job in stalled_jobs:
        jobs += 1
        await app.job_manager.retry_job(job)
    log.info(f"Retried {jobs} stalled jobs.")


# every 24 hours
@app.periodic(cron="0 0 * * *")
@app.task(queue=OPENALEPH_MANAGEMENT_QUEUE, queueing_lock="periodic-daily")
def periodic_daily(timestamp: int):
    with aleph_flask_app.app_context():
        roles.update_roles()
        alerts.check_alerts()
        notifications.generate_digest()
        notifications.delete_old_notifications()
        export.delete_expired_exports()


# every 24 hours
@app.periodic(cron="0 1 * * *")
@app.task(
    queue=OPENALEPH_MANAGEMENT_QUEUE, queueing_lock="remove_old_jobs", pass_context=True
)
async def remove_old_jobs(context, timestamp):
    return await builtin_tasks.remove_old_jobs(
        context,
        max_hours=24,
        remove_failed=True,
        remove_cancelled=True,
        remove_aborted=True,
    )
