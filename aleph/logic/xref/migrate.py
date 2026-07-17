"""
Migration from xref-v1 + profiles to xref-v2 resolver edges.

This module handles:
1. Creating the xref-v2 index with the new mapping
2. Replaying Profile judgements as resolver edges
3. Migrating xref-v1 suggestions as resolver edges
"""

import logging

from elasticsearch.helpers import scan
from nomenklatura.judgement import Judgement
from openaleph_search.index.util import index_name, unpack_result

from aleph.core import es
from aleph.index.xref import configure_xref, xref_index
from aleph.logic.xref.resolver import XrefResolver, get_resolver
from aleph.model import EntitySet

log = logging.getLogger(__name__)


def _old_xref_index():
    """Return the old xref-v1 index name."""
    return index_name("xref", "v1")


def _migrate_profiles(resolver: XrefResolver) -> int:
    """Replay Profile judgements into resolver edges.

    For each Profile EntitySet:
    - POSITIVE items -> resolver.decide() for pairwise combinations
    - NEGATIVE/UNSURE items with compared_to_entity_id -> resolver.decide()
    - After the cluster is formed, attach the legacy entity_set.id as a
      POSITIVE referent of the new canonical NK-* so old profile IDs
      resolve transparently via resolver.get_canonical().

    Returns the number of profiles whose legacy ID was linked to a canonical.
    """
    migrated = 0
    profiles_count = 0
    profiles_linked = 0

    entity_sets = EntitySet.by_type([EntitySet.PROFILE])
    for entity_set in entity_sets:
        profiles_count += 1
        items = list(entity_set.items())
        if not items:
            continue

        positive_items = [i for i in items if i.judgement == Judgement.POSITIVE]
        other_items = [i for i in items if i.judgement != Judgement.POSITIVE]

        # For positive items, create pairwise POSITIVE edges
        canonical_id = None
        for i, item in enumerate(positive_items):
            for j in range(i + 1, len(positive_items)):
                other = positive_items[j]
                canonical = resolver.decide(
                    item.entity_id,
                    other.entity_id,
                    Judgement.POSITIVE,
                    user=str(item.added_by_id or "profiles-migration"),
                    source_collection_id={item.collection_id},
                    target_collection_id={other.collection_id},
                )
                canonical_id = (
                    canonical.id if hasattr(canonical, "id") else str(canonical)
                )
                migrated += 1

        # For negative/unsure items with compared_to_entity_id
        for item in other_items:
            if item.compared_to_entity_id and item.judgement in (
                Judgement.NEGATIVE,
                Judgement.UNSURE,
            ):
                resolver.decide(
                    item.entity_id,
                    item.compared_to_entity_id,
                    item.judgement,
                    user=str(item.added_by_id or "migration"),
                    source_collection_id={item.collection_id},
                    target_collection_id={entity_set.collection_id},
                )
                migrated += 1

        # Pin the legacy profile_id as a referent of the new canonical so
        # old references (URLs, notifications, DB rows) still resolve to
        # the merged cluster via resolver.get_canonical().
        if canonical_id:
            resolver.decide(
                str(entity_set.id),
                canonical_id,
                Judgement.POSITIVE,
                user="migration",
                source_collection_id={entity_set.collection_id},
                target_collection_id={entity_set.collection_id},
            )
            migrated += 1
            profiles_linked += 1

        if profiles_count % 100 == 0:
            log.info(
                "Profile migration progress: profiles=%d, linked=%d, edges=%d",
                profiles_count,
                profiles_linked,
                migrated,
            )

    log.info(
        "Profile migration complete: profiles=%d, linked=%d, edges=%d",
        profiles_count,
        profiles_linked,
        migrated,
    )
    return profiles_linked


def _migrate_xref_v1(resolver):
    """Migrate xref-v1 suggestions into resolver edges.

    suggest() won't overwrite existing human judgements from profile migration.
    """
    old_index = _old_xref_index()
    if not es.indices.exists(index=old_index):
        log.info("No xref-v1 index found, skipping v1 migration")
        return 0

    migrated = 0
    query = {"query": {"match_all": {}}}
    for hit in scan(es, index=old_index, query=query):
        doc = unpack_result(hit)
        if doc is None:
            continue

        src_cid = doc.get("collection_id")
        tgt_cid = doc.get("match_collection_id")
        resolver.suggest(
            left_id=doc.get("entity_id"),
            right_id=doc.get("match_id"),
            score=doc.get("score", 0.0),
            source_collection_id={src_cid} if src_cid else None,
            target_collection_id={tgt_cid} if tgt_cid else None,
            method=doc.get("method"),
            schema=doc.get("schema"),
            text=doc.get("text"),
            countries=doc.get("countries"),
        )
        migrated += 1
        if migrated % 10000 == 0:
            log.info("Xref-v1 migration progress: %d edges", migrated)

    log.info("Xref-v1 migration complete: %d edges", migrated)
    return migrated


def migrate_xref_index() -> None:
    """Main migration entry point.

    Steps:
    1. Create xref-v2 index with new mapping
    2. Replay Profile judgements as resolver edges, linking legacy
       entity_set.id values to their new canonical NK-* IDs via POSITIVE
       judgements (so old profile references resolve transparently).
    3. Migrate xref-v1 suggestions as resolver edges
    4. Log results
    """
    log.info("Starting xref migration...")

    # Step 1: Create xref-v2 index
    log.info("Creating xref-v2 index...")
    configure_xref()

    # Step 2: Get resolver
    resolver = get_resolver()

    # Step 3: Migrate profiles
    log.info("Migrating profiles to resolver edges...")
    profiles_linked = _migrate_profiles(resolver)
    log.info(
        "Profile migration: %d legacy profile IDs linked to canonical",
        profiles_linked,
    )

    # Step 4: Migrate xref-v1
    log.info("Migrating xref-v1 suggestions...")
    v1_count = _migrate_xref_v1(resolver)

    # Step 5: Summary
    log.info(
        "Migration complete: profiles_linked=%d, v1_suggestions=%d, new_index=%s",
        profiles_linked,
        v1_count,
        xref_index(),
    )
