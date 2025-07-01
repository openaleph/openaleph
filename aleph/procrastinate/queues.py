import structlog

from followthemoney.proxy import EntityProxy
from openaleph_procrastinate.app import make_app
from openaleph_procrastinate import defer

from aleph.logic.aggregator import get_aggregator_name

from aleph.model.collection import Collection

log = structlog.get_logger(__name__)
app = make_app(__loader__.name)


def queue_ingest(collection: Collection, proxy: EntityProxy, **context) -> None:
    dataset = get_aggregator_name(collection)
    job = defer.ingest(dataset, [proxy], **context)
    log.critical(f"[queue_ingest] Deferring job: {job}")
    with app.open():
        job.defer(app=app)


def queue_analyze(collection: Collection, proxy: EntityProxy, **context) -> None:
    dataset = get_aggregator_name(collection)
    job = defer.analyze(dataset, [proxy], **context)
    log.critical(f"[queue_analyze] Deferring job: {job}")
    with app.open():
        job.defer(app=app)
