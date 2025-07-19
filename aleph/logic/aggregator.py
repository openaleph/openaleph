from ftmq.store.fragments import get_dataset
from ftmq.store.fragments.dataset import Dataset

MODEL_ORIGIN = "model"


def get_aggregator_name(collection) -> str:
    return "collection_%s" % collection.id


def get_aggregator(collection, origin="aleph") -> Dataset:
    """Connect to a followthemoney dataset."""
    dataset = get_aggregator_name(collection)
    return get_dataset(dataset, origin=origin)
