"""
Tasks handled by procrastinate that can be triggered from other programs
"""

import functools
import structlog

from openaleph_procrastinate.app import make_app
from openaleph_procrastinate.model import DatasetJob, Job
from openaleph_procrastinate.tasks import task
from openaleph_procrastinate.exceptions import InvalidJob

from aleph.core import create_app
from aleph.model.collection import Collection
from aleph.procrastinate.util import ensure_collection
from aleph.logic.collections import compute_collections
from aleph.logic.roles import update_roles
from aleph.logic.alerts import check_alerts
from aleph.logic.notifications import generate_digest, delete_old_notifications
from aleph.logic.export import delete_expired_exports
from aleph.logic.aggregator import get_aggregator
from aleph.logic.collections import index_aggregator, refresh_collection
from aleph.logic.collections import reindex_collection
from aleph.logic.xref import xref_collection, export_matches
from aleph.logic.mapping import load_mapping as load_mapping_from_id
from aleph.logic.mapping import flush_mapping as flush_mapping_from_id
from aleph.logic.entities import update_entity as update_entity_from_id
from aleph.logic.entities import prune_entity as prune_entity_from_id
from aleph.logic.export import export_entities

log = structlog.get_logger(__name__)

app = make_app(__loader__.name)
aleph_flask_app = create_app()


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


def _after_task():
    compute_collections()


@aleph_task(retry=True)
def index(job: DatasetJob, collection: Collection) -> None:
    entity_ids = set(e.id for e in job.get_entities())
    log.info(f"{len(entity_ids)} entities queued for {job.queue}")
    sync = job.payload.get("context", {}).get("sync", False)
    aggregator = get_aggregator(collection)
    index_aggregator(collection, aggregator, entity_ids=entity_ids, sync=sync)
    refresh_collection(collection.id)
    compute_collections()
    _after_task()


@aleph_task(retry=True)
def reindex(job: DatasetJob, collection: Collection) -> None:
    flush = job.payload.get("context", {}).get("flush", False)
    reindex_collection(collection, flush=flush)
    compute_collections()
    _after_task()


@aleph_task(retry=True)
def xref(job: DatasetJob, collection: Collection) -> None:
    xref_collection(collection)
    _after_task()


@aleph_task(retry=True)
def export_xref(job: DatasetJob, collection: Collection) -> None:
    export_id = job.payload.get("context", {}).get("export_id", None)
    if not export_id:
        log.error("No export ID provided for Export XREF")
        raise InvalidJob
    export_matches(export_id)
    _after_task()


@aleph_task(retry=True)
def load_mapping(job: DatasetJob, collection: Collection) -> None:
    mapping_id = job.payload.get("context", {}).get("mapping_id", None)
    if not mapping_id:
        log.error("No mapping ID provided for load_mapping")
        raise InvalidJob
    load_mapping_from_id(collection, mapping_id)
    _after_task()


@aleph_task(retry=True)
def flush_mapping(job: DatasetJob, collection: Collection) -> None:
    mapping_id = job.payload.get("context", {}).get("mapping_id", None)
    if not mapping_id:
        log.error("No mapping ID provided for flush_mapping")
        raise InvalidJob
    flush_mapping_from_id(collection, mapping_id)
    _after_task()


@aleph_task(retry=True)
def update_entity(job: DatasetJob, collection: Collection) -> None:
    entity_id = job.payload.get("context", {}).get("entity_id", None)
    if not entity_id:
        log.error("No entity ID provided for update_entity")
        raise InvalidJob
    update_entity_from_id(collection, entity_id)
    _after_task()


@aleph_task(retry=True)
def prune_entity(job: DatasetJob, collection: Collection) -> None:
    entity_id = job.payload.get("context", {}).get("entity_id", None)
    if not entity_id:
        log.error("No entity ID provided for prune_entity")
        raise InvalidJob
    prune_entity_from_id(collection, entity_id)
    _after_task()


@aleph_task(retry=True)
def export_search(job: Job) -> None:
    export_id = job.payload.get("context", {}).get("export_id", None)
    export_entities(export_id)
    _after_task()


# every 5 minutes
# @app.periodic(cron="*/5 * * * *")
@app.task(queue="openaleph-periodic")
def periodic_clean_and_compute(timestamp: int):
    with aleph_flask_app.app_context():
        _after_task()


# every 24 hours
# @app.periodic(cron="0 0 * * *")
@app.task(queue="openaleph-periodic")
def periodic_daily(timestamp: int):
    with aleph_flask_app.app_context():
        update_roles()
        check_alerts()
        generate_digest()
        delete_expired_exports()
        delete_old_notifications()
