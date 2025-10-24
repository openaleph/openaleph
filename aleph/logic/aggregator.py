from ftmq.store.fragments import get_fragments
from ftmq.store.fragments.dataset import Fragments
from openaleph_procrastinate.settings import OpenAlephSettings

MODEL_ORIGIN = "model"
settings = OpenAlephSettings()


def get_aggregator_name(collection) -> str:
    return "collection_%s" % collection.id


def get_aggregator(collection, origin="aleph") -> Fragments:
    """Connect to a followthemoney dataset."""
    dataset = get_aggregator_name(collection)
    return get_fragments(dataset, origin=origin, database_uri=settings.fragments_uri)
