"""
Utilities to map (legacy) Aleph logic to new procrastinate logic
"""

from aleph.authz import Authz
from aleph.logic.collections import create_collection
from aleph.model.collection import Collection
from aleph.model.role import Role


def ensure_collection(dataset: str) -> Collection:
    if dataset.startswith("collection_"):
        collection_id = int(dataset.split("_")[-1])
        collection = Collection.by_id(collection_id)
        assert collection is not None, f"Invalid collection: `{dataset}`"
        return collection
    collection = Collection.by_foreign_id(dataset, deleted=True)
    if collection is None:
        authz = Authz.from_role(Role.load_cli_user())
        config = {
            "foreign_id": dataset,
            "label": dataset,
        }
        create_collection(config, authz)
        return Collection.by_foreign_id(dataset)
    return collection
