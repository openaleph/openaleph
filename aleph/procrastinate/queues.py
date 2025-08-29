from typing import Any, TypedDict

import structlog
from followthemoney.proxy import EntityProxy
from openaleph_procrastinate import defer
from openaleph_procrastinate.app import make_app
from openaleph_procrastinate.tasks import Priorities

from aleph.logic.aggregator import get_aggregator_name
from aleph.model.collection import Collection
from aleph.settings import SETTINGS

log = structlog.get_logger(__name__)
app = make_app(SETTINGS.PROCRASTINATE_TASKS, sync=True)

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


class Context(TypedDict):
    languages: list[str]
    ftmstore: str
    namespace: str
    priority: int | None


def get_context(collection: Collection) -> Context:
    """Set some task context variables that configure the ingestors."""
    from aleph.logic.aggregator import get_aggregator_name

    return {
        "languages": [x for x in collection.languages if x],
        "ftmstore": get_aggregator_name(collection),
        "namespace": collection.foreign_id,
        "priority": Priorities.USER if collection.casefile else None,
    }


def queue_ingest(collection: Collection, proxy: EntityProxy, **context: Any) -> None:
    context = {**context, **get_context(collection)}
    dataset = get_aggregator_name(collection)
    with app.open():
        defer.ingest(app, dataset, [proxy], **context)


def queue_analyze(collection: Collection, proxy: EntityProxy, **context: Any) -> None:
    context = {**context, **get_context(collection)}
    dataset = get_aggregator_name(collection)
    with app.open():
        defer.analyze(app, dataset, [proxy], **context)


def queue_index(
    collection: Collection, entities: list[EntityProxy], **context: Any
) -> None:
    context = {**context, **get_context(collection)}
    dataset = get_aggregator_name(collection)
    with app.open():
        defer.index(app, dataset, entities, **context)


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
