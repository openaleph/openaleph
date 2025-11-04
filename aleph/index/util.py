from openaleph_search.index.entities import index_proxy

from aleph.model.entity import Entity


def index_entity(entity: Entity):
    index_proxy(
        entity.collection.name,
        entity.to_proxy(),
        collection_id=entity.collection.id,
        namespace=entity.collection.name,
    )
