from typing import Generator

from ftmq.store.fragments import get_fragments
from ftmq.store.fragments.dataset import Fragments
from openaleph_procrastinate.settings import OpenAlephSettings
from sqlalchemy import distinct, select

MODEL_ORIGIN = "model"
settings = OpenAlephSettings()


def get_aggregator_name(collection) -> str:
    return "collection_%s" % collection.id


def get_aggregator(collection, origin="aleph") -> Fragments:
    """Connect to a followthemoney dataset."""
    dataset = get_aggregator_name(collection)
    return get_fragments(dataset, origin=origin, database_uri=settings.fragments_uri)


def get_aggregator_ids(aggregator, batch_size=10000) -> Generator[str, None, None]:
    """Fetch all distinct entity IDs from aggregator using batched queries.

    This is more memory efficient for large tables than fetching all IDs at once.

    Args:
        aggregator: The aggregator instance
        batch_size: Number of IDs to fetch per batch

    Yields:
        Entity IDs from the aggregator
    """
    last_id = None
    while True:
        stmt = select(distinct(aggregator.table.c.id))
        if last_id is not None:
            stmt = stmt.where(aggregator.table.c.id > last_id)
        stmt = stmt.order_by(aggregator.table.c.id).limit(batch_size)

        with aggregator.store.engine.connect() as conn:
            result = conn.execute(stmt)
            entity_ids = [row[0] for row in result]

        if not entity_ids:
            return

        yield from entity_ids
        last_id = entity_ids[-1]
