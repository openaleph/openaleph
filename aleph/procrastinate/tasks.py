"""
Tasks handled by procrastinate that can be triggered from other programs
"""

import functools
import structlog

from openaleph_procrastinate.app import make_app
from openaleph_procrastinate.model import DatasetJob, Defers
from openaleph_procrastinate.tasks import task

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


@aleph_task(retry=True)
def index(job: DatasetJob, collection: Collection) -> Defers:
    log.info(
        f"[{job.queue}] [dataset: {job.dataset}] [collection: {collection}] task started"
    )
    entity_ids = set(e.id for e in job.get_entities())
    log.info(f"{len(entity_ids)} entities queued for {job.queue}")
    sync = job.payload.get("context", {}).get("sync", False)
    aggregator = get_aggregator(collection)
    index_aggregator(collection, aggregator, entity_ids=entity_ids, sync=sync)
    refresh_collection(collection.id)


# every 5 minutes
# @app.periodic(cron="*/5 * * * *")
# @task(app=app)
# def periodic_compute_collections():
#     compute_collections()


# every 24 hours
# @app.periodic(cron="0 0 * * *")
# @task(app=app)
# def periodic_daily():
#     update_roles()
#     check_alerts()
#     generate_digest()
#     delete_expired_exports()
#     delete_old_notifications()
