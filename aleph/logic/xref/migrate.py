"""
Migration from xref-v1 + profiles to xref-v2 resolver edges.

This module handles:
1. Creating the xref-v2 index with the new mapping
2. Replaying Profile judgements as resolver edges
3. Migrating xref-v1 suggestions as resolver edges
"""

import logging
from typing import Generator

from elasticsearch.helpers import scan
from nomenklatura.judgement import Judgement
from openaleph_search.index.util import index_name, unpack_result

from aleph.core import es
from aleph.index.xref import configure_xref, xref_index
from aleph.logic.xref.resolver import XrefResolver, get_resolver
from aleph.model import EntitySet
from aleph.model.xref import ESEdge

log = logging.getLogger(__name__)


def _old_xref_index():
    """Return the old xref-v1 index name."""
    return index_name("xref", "v1")


def _profile_decisions(counts: dict[str, int]) -> Generator[ESEdge, None, None]:
    """Yield decided edges replaying Profile judgements.

    For each Profile EntitySet:
    - POSITIVE items connect as a star over the first item — import
      canonicalization merges the component under one NK-* either way.
    - NEGATIVE/UNSURE items with compared_to_entity_id become blockers.
    - Pin the legacy profile_id as a referent of the new canonical so
      old references (URLs, notifications, DB rows) still resolve to
      the merged cluster via resolver.get_canonical(): the entity_set.id
      joins the positive component, and its membership row IS the
      profileId→NK-* mapping.
    """
    for entity_set in EntitySet.by_type([EntitySet.PROFILE]):
        counts["profiles"] += 1
        items = list(entity_set.items())
        if not items:
            continue

        positive_items = [i for i in items if i.judgement == Judgement.POSITIVE]
        other_items = [i for i in items if i.judgement != Judgement.POSITIVE]

        hub = positive_items[0] if positive_items else None
        for item in positive_items[1:]:
            if item.entity_id == hub.entity_id:
                continue  # legacy data may duplicate the same entity
            yield ESEdge(
                source=hub.entity_id,
                target=item.entity_id,
                judgement=Judgement.POSITIVE.value,
                user=str(item.added_by_id or "profiles-migration"),
                source_collection_id={hub.collection_id},
                target_collection_id={item.collection_id},
            )

        # For negative/unsure items with compared_to_entity_id
        for item in other_items:
            if item.compared_to_entity_id == item.entity_id:
                continue  # self-referencing legacy rows
            if item.compared_to_entity_id and item.judgement in (
                Judgement.NEGATIVE,
                Judgement.UNSURE,
            ):
                yield ESEdge(
                    source=item.entity_id,
                    target=item.compared_to_entity_id,
                    judgement=item.judgement.value,
                    user=str(item.added_by_id or "migration"),
                    source_collection_id={item.collection_id},
                    target_collection_id={entity_set.collection_id},
                )

        # A cluster only forms from at least one positive pair; only then
        # is there a canonical to pin the legacy profile_id to.
        if len(positive_items) >= 2:
            counts["linked"] += 1
            yield ESEdge(
                source=str(entity_set.id),
                target=hub.entity_id,
                judgement=Judgement.POSITIVE.value,
                user="migration",
                source_collection_id={entity_set.collection_id},
                target_collection_id={entity_set.collection_id},
            )

        if counts["profiles"] % 100 == 0:
            log.info(
                "Profile migration progress: profiles=%d, linked=%d",
                counts["profiles"],
                counts["linked"],
            )


def _migrate_profiles(resolver: XrefResolver) -> dict[str, int]:
    """Replay Profile judgements through the batch import.

    One transaction + one graph lock per batch instead of per decide.
    Uncapped (max_cluster_size=0): profiles are human decisions being
    replayed, not auto-merge output.
    """
    counts = {"profiles": 0, "linked": 0}
    stats = resolver.import_decisions(_profile_decisions(counts), max_cluster_size=0)
    log.info(
        "Profile migration complete: profiles=%d, linked=%d, edges=%d",
        counts["profiles"],
        counts["linked"],
        stats["applied"],
    )
    return {**counts, **stats}


def _migrate_xref_v1(resolver: XrefResolver) -> int:
    """Migrate xref-v1 suggestions into resolver edges.

    suggest() won't overwrite existing human judgements from profile
    migration. Suggestions are pure ES documents, buffered by the
    caller's bulk() context.
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
    2. Replay Profile judgements as resolver edges via the batch import,
       linking legacy entity_set.id values to their new canonical NK-*
       IDs via POSITIVE judgements (so old profile references resolve
       transparently).
    3. Migrate xref-v1 suggestions as resolver edges
    4. Log results

    bulk() buffers the ES side (suggestions + decided-edge projections);
    the SQL graph writes batch through import_decisions.
    """
    log.info("Starting xref migration...")

    # Step 1: Create xref-v2 index
    log.info("Creating xref-v2 index...")
    configure_xref()

    # Step 2: Get resolver
    resolver = get_resolver()

    with resolver.bulk():
        # Step 3: Migrate profiles
        log.info("Migrating profiles to resolver edges...")
        profile_stats = _migrate_profiles(resolver)

        # Step 4: Migrate xref-v1
        log.info("Migrating xref-v1 suggestions...")
        v1_count = _migrate_xref_v1(resolver)

    # Step 5: Summary
    log.info(
        "Migration complete: profiles_linked=%d, v1_suggestions=%d, new_index=%s",
        profile_stats["linked"],
        v1_count,
        xref_index(),
    )
