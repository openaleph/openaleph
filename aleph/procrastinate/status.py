"""
Map procrastinate status to collection logic
"""

from typing import Any, Generator

from openaleph_procrastinate.manage.status import get_dataset_status, get_status
from openaleph_procrastinate.model import DatasetStatus

from aleph.logic.aggregator import get_aggregator_name
from aleph.model.collection import Collection


class CollectionStatus(DatasetStatus):
    collection: dict[str, Any] = {}

    @property
    def collection_id(self) -> int | None:
        try:
            return int(self.name.split("_")[-1])
        except ValueError:
            pass


def inline_collection_data(status: CollectionStatus) -> None:
    if status.collection_id is None:
        return

    from aleph.views.serializers import CollectionSerializer

    serializer = CollectionSerializer(nested=True)

    collection_obj = Collection.by_id(status.collection_id, deleted=True)
    if collection_obj is not None:
        status.collection = serializer.serialize(collection_obj.to_dict())


def get_active_collections_status(
    include_collection_data: bool | None = True,
) -> Generator[CollectionStatus, None, None]:

    for dataset in get_status():
        # only include active collections
        if not dataset.is_active():
            continue
        # periodic tasks don't have a collection_id
        if dataset.is_system():
            continue

        collection_status = CollectionStatus(**dataset.model_dump())
        if include_collection_data:  # used for api, not for prometheus
            inline_collection_data(collection_status)

        yield collection_status


def get_collection_status(
    collection: Collection, include_collection_data: bool | None = True
) -> CollectionStatus | None:
    dataset = get_aggregator_name(collection)
    dataset_status = get_dataset_status(dataset)
    if dataset_status is None:
        return
    collection_status = CollectionStatus(**dataset_status.model_dump())
    if include_collection_data:
        inline_collection_data(collection_status)
    return collection_status
