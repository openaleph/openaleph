from ftmq.store.fragments import get_fragments
from ftmq.store.fragments.dataset import Fragments

MODEL_ORIGIN = "model"


def get_aggregator_name(collection) -> str:
    return "collection_%s" % collection.id


def get_aggregator(collection, origin="aleph") -> Fragments:
    """Connect to a followthemoney dataset."""
    dataset = get_aggregator_name(collection)
    return get_fragments(dataset, origin=origin)
