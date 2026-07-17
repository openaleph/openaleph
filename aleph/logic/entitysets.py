import logging

from aleph.logic.entities import upsert_entity
from aleph.logic.notifications import publish
from aleph.logic.resolver.registry import register, register_etag
from aleph.logic.resolver.ttl import TTL_RESOURCE
from aleph.model import EntitySet, EntitySetItem, EntitySetSchema, Events
from aleph.model.common import iso_text

log = logging.getLogger(__name__)


def get_entityset(entityset_id):
    return EntitySet.by_id(entityset_id)


@register(EntitySetSchema, ttl=TTL_RESOURCE)
def _fetch_entityset(entityset_id: str) -> EntitySetSchema | None:
    entityset = EntitySet.by_id(entityset_id)
    if entityset is None:
        return None
    return EntitySetSchema.model_validate(entityset.to_dict())


@register_etag(EntitySetSchema)
def _entityset_etag(entityset: EntitySetSchema) -> str:
    return f"{entityset.id}:{iso_text(entityset.updated_at) or 0}"


def refresh_entityset(entityset_id):
    pass  # SQLA event handles resolver invalidation


def create_entityset(collection, data, authz):
    """Create an entity set. This will create or update any entities
    that already exist in the entityset and sign their IDs into the collection.
    """
    old_to_new_id_map = {}
    entity_ids = []
    for entity in data.pop("entities", []):
        old_id = entity.get("id")
        new_id = upsert_entity(entity, collection, sign=True, sync=True)
        old_to_new_id_map[old_id] = new_id
        entity_ids.append(new_id)
    layout = data.get("layout", {})
    data["layout"] = replace_layout_ids(layout, old_to_new_id_map)
    entityset = EntitySet.create(data, collection, authz)
    for entity_id in entity_ids:
        save_entityset_item(entityset, collection, entity_id)
    publish(
        Events.CREATE_ENTITYSET,
        params={"collection": collection, "entityset": entityset},
        channels=[collection, authz.role],
        actor_id=authz.id,
    )
    return entityset


def save_entityset_item(entityset, collection, entity_id, **data):
    """Change the association between an entity and an entityset."""
    item = EntitySetItem.save(entityset, entity_id, collection_id=collection.id, **data)
    collection.touch()
    refresh_entityset(entityset.id)
    return item


def replace_layout_ids(layout, old_to_new_id_map):
    # Replace ids in vertices
    for vtx in layout.get("vertices", []):
        ent_id = vtx.get("entityId")
        if ent_id in old_to_new_id_map:
            new_id = old_to_new_id_map[ent_id]
            vtx["entityId"] = new_id
            vtx["id"] = vtx["id"].replace(ent_id, new_id)
    # Replaces ids in edges
    for edge in layout.get("edges", []):
        for key in ("sourceId", "targetId"):
            if edge[key].startswith("entity"):
                old_id = edge[key].split("entity:")[-1]
                if old_id in old_to_new_id_map:
                    new_id = old_to_new_id_map[old_id]
                    edge[key] = "entity:%s" % new_id
                    edge["id"] = edge["id"].replace(old_id, new_id)
        ent_id = edge.get("entityId")
        if ent_id in old_to_new_id_map:
            new_id = old_to_new_id_map[ent_id]
            edge["entityId"] = new_id
            edge["id"] = edge["id"].replace(ent_id, new_id)
    # Replace ids in groupings
    for group in layout.get("groupings", []):
        vertices = []
        for vtx in group.get("vertices", []):
            if vtx.startswith("entity"):
                old_id = vtx.split("entity:")[-1]
                if old_id in old_to_new_id_map:
                    new_id = old_to_new_id_map[old_id]
                    group["id"] = group["id"].replace(old_id, new_id)
                    vtx = "entity:%s" % new_id
            vertices.append(vtx)
        group["vertices"] = vertices
    return layout
