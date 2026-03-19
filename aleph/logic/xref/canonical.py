"""
Canonical cluster logic. Replaces get_profile() from profiles.py.

Provides merged entity views for clusters of deduplicated entities.
"""

import logging

from anystore.types import SDict
from followthemoney import EntityProxy, StatementEntity
from ftmq.util import make_entity
from openaleph_search.model import SearchAuth

from aleph.logic import resolver
from aleph.logic.xref.resolver import get_resolver
from aleph.model import Entity
from aleph.util import Stub

log = logging.getLogger(__name__)


def get_canonical_cluster(
    entity_id: str, auth: SearchAuth | None = None
) -> SDict | None:
    """Get the canonical cluster for an entity, with merged proxy.

    This replaces get_profile() — instead of loading from EntitySet items,
    it uses the resolver's POSITIVE edges to find cluster members.
    """
    xref_resolver = get_resolver(auth)

    canonical_id = xref_resolver.get_canonical(entity_id)
    referents = xref_resolver.get_referents(canonical_id, canonicals=False)
    referents.add(entity_id)

    # Only namespaced IDs (<id>.<namespace_hash>) are real entities;
    # NK-*/Q* are intermediate/canonical identifiers, not fetchable.
    entity_ids = [rid for rid in referents if "." in rid]
    if len(entity_ids) < 2:
        return None

    collection_ids: set[int] = set()
    entities: list[EntityProxy] = []

    # Fetch entities from ES
    stub = Stub()
    for rid in entity_ids:
        resolver.queue(stub, Entity, rid)
    resolver.resolve(stub)

    # Merge
    merged = None
    for rid in entity_ids:
        entity_data = resolver.get(stub, Entity, rid)
        if entity_data is None:
            continue
        entity = make_entity(entity_data, StatementEntity, entity_data["dataset"])
        collection_ids.add(entity_data["collection_id"])
        entities.append(entity)
        if merged is None:
            merged = entity.clone()
        else:
            merged.merge(entity)

    if merged is None:
        return None

    merged.id = canonical_id
    # merged.caption = pick_name(merged.get_type_values(registry.name))
    return {"merged": merged, "entities": entities, "collection_ids": collection_ids}
