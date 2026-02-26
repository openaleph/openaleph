from typing import Any, TypedDict

import structlog
from banal import clean_dict
from followthemoney.proxy import EntityProxy
from openaleph_procrastinate import defer
from openaleph_procrastinate.app import make_app
from openaleph_procrastinate.model import DatasetJob
from openaleph_procrastinate.settings import DeferSettings
from openaleph_procrastinate.tasks import Priorities
from servicelayer import env

from aleph.logic.aggregator import get_aggregator_name
from aleph.model.collection import Collection
from aleph.settings import SETTINGS

log = structlog.get_logger(__name__)
app = make_app(SETTINGS.PROCRASTINATE_TASKS, sync=True)
settings = DeferSettings()

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

TRACER_URI = env.get("REDIS_URI")


class Context(TypedDict):
    languages: list[str]
    ftmstore: str
    namespace: str
    priority: int | None


def get_context(collection: Collection) -> Context:
    """Set some task context variables that configure the ingestors."""
    from aleph.logic.aggregator import get_aggregator_name

    return clean_dict(
        {
            "languages": [x for x in collection.languages if x],
            "ftmstore": get_aggregator_name(collection),
            "namespace": collection.foreign_id,
            "priority": Priorities.USER if collection.casefile else None,
        }
    )


def queue_ingest(collection: Collection, proxy: EntityProxy, **context: Any) -> None:
    context = {**context, **get_context(collection)}
    dataset = get_aggregator_name(collection)
    with app.open():
        defer.ingest(app, dataset, [proxy], dehydrate=False, **context)


def queue_analyze(collection: Collection, proxy: EntityProxy, **context: Any) -> None:
    context = {**context, **get_context(collection)}
    dataset = get_aggregator_name(collection)
    with app.open():
        defer.analyze(app, dataset, [proxy], **context)


def queue_transcribe(
    collection: Collection, proxy: EntityProxy, **context: Any
) -> None:
    context = {**context, **get_context(collection)}
    dataset = get_aggregator_name(collection)
    with app.open():
        defer.transcribe(app, dataset, [proxy], **context)


def queue_translate(collection: Collection, proxy: EntityProxy, **context: Any) -> None:
    context = {**context, **get_context(collection)}
    dataset = get_aggregator_name(collection)
    with app.open():
        defer.translate(app, dataset, [proxy], **context)
    # we want to trace the processing status for the UI:
    tracer = defer.tasks.translate.get_tracer(TRACER_URI)
    tracer.add(proxy.id)


def queue_index(
    collection: Collection, entities: list[EntityProxy], **context: Any
) -> None:
    context = {**context, **get_context(collection)}
    dataset = get_aggregator_name(collection)
    with app.open():
        defer.index(app, dataset, entities, **context)


def queue_index_batch(
    collection: Collection, entity_ids: list[str], **context: Any
) -> None:
    context = {**context, **get_context(collection)}
    payload = {"context": context, "entity_ids": entity_ids}
    dataset = get_aggregator_name(collection)
    task = "aleph.procrastinate.tasks.index_entities_by_ids"
    queue = settings.reindex.queue
    with app.open():
        job = DatasetJob(dataset=dataset, payload=payload, queue=queue, task=task)
        job.defer(app, priority=settings.reindex.min_priority)


def queue_reindex(collection: Collection, **context: Any) -> None:
    context = {**context, **get_context(collection)}
    dataset = get_aggregator_name(collection)
    with app.open():
        defer.reindex(app, dataset, **context)


def queue_xref(collection: Collection) -> None:
    dataset = get_aggregator_name(collection)
    with app.open():
        defer.xref(app, dataset)


def queue_export_xref(collection: Collection, export_id: str) -> None:
    dataset = get_aggregator_name(collection)
    with app.open():
        defer.export_xref(app, dataset, export_id=export_id)


def queue_load_mapping(collection: Collection, **context: Any) -> None:
    dataset = get_aggregator_name(collection)
    with app.open():
        defer.load_mapping(app, dataset, **context)


def queue_flush_mapping(collection: Collection, **context: Any) -> None:
    dataset = get_aggregator_name(collection)
    with app.open():
        defer.flush_mapping(app, dataset, **context)


def queue_update_entity(collection: Collection, **context: Any) -> None:
    dataset = get_aggregator_name(collection)
    with app.open():
        defer.update_entity(app, dataset, **context)


def queue_prune_entity(collection: Collection, **context: Any) -> None:
    dataset = get_aggregator_name(collection)
    with app.open():
        defer.prune_entity(app, dataset, **context)


def queue_export_search(**context: Any) -> None:
    with app.open():
        defer.export_search(app, **context)


def queue_cancel_collection(collection: Collection, **context: Any) -> None:
    dataset = get_aggregator_name(collection)
    with app.open():
        defer.cancel_dataset(app, dataset, **context)
