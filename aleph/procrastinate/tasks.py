"""
Tasks handled by procrastinate that can be triggered from other programs
"""

import functools

from followthemoney.proxy import EntityProxy
from openaleph_procrastinate import defer
from openaleph_procrastinate.app import make_app
from openaleph_procrastinate.model import DatasetJob, Defers
from openaleph_procrastinate.tasks import task

from aleph.core import create_app
from aleph.logic.aggregator import get_aggregator_name
from aleph.model.collection import Collection
from aleph.procrastinate.util import ensure_collection
from aleph.queues import OP_INDEX, get_context, get_stage

app = make_app(__loader__.name)
aleph_app = create_app()


def aleph_task(original_func=None, **kwargs):
    """
    extend @openaleph_procrastinate.tasks.task decorator to ensure aleph app
    context for task runtime and getting the collection_id from the dataset
    foreign_id
    """

    def wrap(func):
        def new_func(*job_args, **job_kwargs):
            with aleph_app.app_context():
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


@aleph_task
def index(job: DatasetJob, collection: Collection) -> Defers:
    """
    Index entities into Aleph. This is received from external procrastinate
    services. For now this index task queues the entities into the Aleph index
    task queue.
    """
    entity_ids = set(e.id for e in job.get_entities())
    stage = get_stage(collection, OP_INDEX, job.context.get("job_id"))
    context = get_context(collection, [])
    stage.queue({"entity_ids": entity_ids}, context)


def queue_ingest(collection: Collection, proxy: EntityProxy, **context) -> None:
    dataset = get_aggregator_name(collection)
    job = defer.ingest(dataset, [proxy], **context)
    with app.open():
        job.defer(app=app)


def queue_analyze(collection: Collection, proxy: EntityProxy, **context) -> None:
    dataset = get_aggregator_name(collection)
    job = defer.analyze(dataset, [proxy], **context)
    with app.open():
        job.defer(app=app)
