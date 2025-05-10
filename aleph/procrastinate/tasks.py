"""
Tasks handled by procrastinate that can be triggered from other programs
"""

import functools

from openaleph_procrastinate.app import make_app
from openaleph_procrastinate.helpers import OPAL_ORIGIN
from openaleph_procrastinate.model import DatasetJob
from openaleph_procrastinate.tasks import task

from aleph.core import create_app
from aleph.index.entities import index_proxy
from aleph.logic.aggregator import get_aggregator
from aleph.logic.entities import refresh_entity
from aleph.logic.profiles import profile_fragments
from aleph.model.collection import Collection
from aleph.procrastinate.util import ensure_collection, sign_entity

app = make_app(__loader__.name)
aleph_app = create_app()


def aleph_task(original_func=None, **kwargs):
    # extend @openaleph_procrastinate.tasks.task decorator to ensure aleph app
    # context for task runtime
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
def load_entity(job: DatasetJob, collection: Collection) -> DatasetJob:
    """
    Load an entity into Aleph:
    - write to ftm store
    - index
    - refresh cache
    """
    sign_entity(job.entity, collection)
    aggregator = get_aggregator(collection)
    aggregator.delete(entity_id=job.entity.id)
    aggregator.put(job.entity, origin=OPAL_ORIGIN)
    profile_fragments(collection, aggregator, entity_id=job.entity.id)
    index_proxy(collection, job.entity)
    refresh_entity(collection, job.entity.id)
    return job


@aleph_task
def index_entity(job: DatasetJob, collection: Collection) -> DatasetJob:
    """Index an entity into the aleph index"""
    index_proxy(collection, job.entity)
    return job
