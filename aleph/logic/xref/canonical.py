"""
Canonical cluster logic. Replaces get_profile() from profiles.py.

Provides merged entity views for clusters of deduplicated entities.
"""

import logging

from anystore.types import SDict
from followthemoney import StatementEntity
from ftmq.util import get_dehydrated_entity, make_entity
from nomenklatura.resolver.identifier import Identifier
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

    Unlike get_canonical_cluster(), this does NOT require ≥2 entities.
    A canonical with a single remaining referent is still valid for
    operations like re-deciding an undecided edge.
    """
    if Identifier.get(id_).canonical:
        xref_resolver = get_resolver(auth)
        referents = xref_resolver.get_referents(id_, canonicals=False)
        # Only namespaced IDs (<id>.<namespace_hash>) are real entities
        entity_ids = [rid for rid in referents if "." in rid]
        if not entity_ids:
            return None
        # Batch-fetch via resolver queue/resolve/get
        stub = Stub()
        for rid in entity_ids:
            resolver.queue(stub, Entity, rid)
        resolver.resolve(stub)
        collection_ids: set[int] = set()
        for rid in entity_ids:
            entity_data = resolver.get(stub, Entity, rid)
            if entity_data is not None:
                collection_ids.add(entity_data["collection_id"])
        if not collection_ids:
            return None
        return {
            "collection_ids": collection_ids,
            "schema": None,
        }
    else:
        # Single entity — batch not needed, but use same resolver pattern
        stub = Stub()
        resolver.queue(stub, Entity, id_)
        resolver.resolve(stub)
        entity_data = resolver.get(stub, Entity, id_)
        if entity_data is None:
            return None
        return {
            "collection_ids": {entity_data["collection_id"]},
            "schema": entity_data.get("schema"),
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
