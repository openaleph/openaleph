"""
Canonical cluster logic. Replaces get_profile() from profiles.py.

Provides merged entity views for clusters of deduplicated entities.
"""

import logging

from anystore.types import SDict
from followthemoney import StatementEntity
from ftmq.util import get_dehydrated_entity, make_entity
from nomenklatura.resolver.identifier import Identifier
from openaleph_search.index.entities import get_entity
from openaleph_search.model import SearchAuth

from aleph.logic import resolver
from aleph.logic.xref.resolver import get_resolver
from aleph.model import Entity
from aleph.util import Stub

log = logging.getLogger(__name__)


def resolve_entity_or_canonical(
    id_: str, auth: SearchAuth | None = None
) -> SDict | None:
    """Resolve an entity or canonical ID to its collection info.

    Returns dict with:
      - collection_ids: set[int] — all collections the ID belongs to
      - schema: str | None — schema name (None for canonicals)

    Returns None if the entity/cluster is not found.
    """
    if Identifier.get(id_).canonical:
        cluster = get_canonical_cluster(id_, auth)
        if cluster is None:
            return None
        return {
            "collection_ids": cluster["collection_ids"],
            "schema": None,
        }
    else:
        entity = get_entity(id_)
        if entity is None:
            return None
        return {
            "collection_ids": {entity["collection_id"]},
            "schema": entity.get("schema"),
        }


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
    entities: list[SDict] = []

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
        if merged is None:
            merged = entity.clone()
        else:
            merged.merge(entity)
        entity_data.update(**get_dehydrated_entity(entity).to_dict())
        entities.append(entity_data)

    if merged is None:
        return None

    merged.id = canonical_id
    return {
        "id": canonical_id,
        "label": merged.caption,
        "merged": merged,
        "entities": entities,
        "collection_ids": collection_ids,
    }
