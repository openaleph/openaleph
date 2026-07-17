"""Map procrastinate job status to collection IDs.

Thin wrapper around ``openaleph_procrastinate`` status queries –
extracts the collection_id from the aggregator dataset name and
filters out system/non-collection datasets.
"""

from typing import Generator

from openaleph_procrastinate.manage.status import get_dataset_status, get_status

from aleph.model.collection import CollectionStatus


def get_active_collections_status() -> Generator[CollectionStatus, None, None]:
    """Yield job states for all active, non-system collections."""
    for dataset in get_status():
        if not dataset.is_active():
            continue
        if dataset.is_system():
            continue
        yield CollectionStatus(**dataset.model_dump())


def get_collection_status(collection_id: str | int) -> CollectionStatus:
    """Get job state for a single collection."""
    dataset = f"collection_{collection_id}"
    dataset_status = get_dataset_status(dataset)
    if dataset_status is None:
        return CollectionStatus(name=dataset)
    return CollectionStatus(**dataset_status.model_dump())
