"""
Canonical cluster logic. Replaces get_profile() from profiles.py.

Provides merged entity views for clusters of deduplicated entities.
"""

import logging

from anystore.types import SDict
from followthemoney import StatementEntity
from ftmq.util import get_dehydrated_entity
from nomenklatura.resolver.identifier import Identifier
from openaleph_search.model import SearchAuth

from aleph.logic.resolver import cache
from aleph.logic.xref.resolver import get_resolver
from aleph.model import EntitySchema
from aleph.model.common import model_dump

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
        # Batch-fetch via resolver
        entities = cache.get_many(EntitySchema, entity_ids)
        collection_ids = {e.collection_id for e in entities if e.collection_id}
        if not collection_ids:
            return None
        return {
            "collection_ids": collection_ids,
            "schema": None,
        }
    else:
        # Single entity lookup
        entity = cache.get(EntitySchema, id_)
        if entity is None:
            return None
        return {
            "collection_ids": {entity.collection_id},
            "schema": entity.schema_,
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

    # Batch-fetch entities from ES via resolver
    fetched = cache.get_many(EntitySchema, entity_ids)

    # Merge via EntityModel.to_proxy() — gives us an EntityProxy
    # directly without a dict round-trip through make_entity.
    merged = None
    for entity_schema in fetched:
        proxy = entity_schema.to_proxy(StatementEntity, entity_schema.dataset)
        if entity_schema.collection_id:
            collection_ids.add(entity_schema.collection_id)
        if merged is None:
            merged = proxy.clone()
        else:
            merged.merge(proxy)
        entity_data = model_dump(entity_schema)
        entity_data.update(**get_dehydrated_entity(proxy).to_dict())
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
