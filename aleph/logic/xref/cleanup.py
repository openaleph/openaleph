"""
Cleanup orphaned xref edges that reference entities which no longer exist.

FIXME / WARNING: Currently, the CLI `migrate-xref` command adds NK edges for old
profile IDs pointing to their new NK-* canonical ID. Running this script here
would delete these, as the profile ID doesn't point to any existing entity in
the index. Instead, the `migrate-xref` should output a profileId->NK-* mapping
that an operator could use for a reverse proxy to rewrite these paths instead.
"""

import logging

from openaleph_search.index.entities import get_entity

from aleph.index.xref import scan_edges
from aleph.logic.xref.resolver import get_resolver

log = logging.getLogger(__name__)

NK_PREFIX = "NK-"


def cleanup_orphaned_edges(dry_run=False):
    """Scan all active edges and remove those referencing non-existing entities.

    NK-* synthetic canonical IDs are excluded from existence checks since they
    don't correspond to real entities in the entity index.

    Removal goes through the resolver so the SQL judgement graph, the cluster
    membership and the ES index (decided projections AND suggestions) stay in
    sync — soft-deleting the ES doc alone would desync from the graph.
    """
    scanned = 0
    orphaned = 0
    entity_cache = {}
    orphan_ids: set[str] = set()

    def entity_exists(entity_id):
        if entity_id.startswith(NK_PREFIX):
            return True
        if entity_id in entity_cache:
            return entity_cache[entity_id]
        exists = get_entity(entity_id) is not None
        entity_cache[entity_id] = exists
        return exists

    for doc in scan_edges([], include_deleted=False):
        scanned += 1
        source = doc.source
        target = doc.target

        for node in (source, target):
            if not entity_exists(node):
                orphan_ids.add(node)

        if source in orphan_ids or target in orphan_ids:
            orphaned += 1
            if orphaned % 100 == 0:
                log.info(
                    "Cleanup progress: scanned=%d, orphaned=%d",
                    scanned,
                    orphaned,
                )

        if scanned % 10000 == 0:
            log.info(
                "Cleanup progress: scanned=%d, orphaned=%d",
                scanned,
                orphaned,
            )

    if not dry_run and orphan_ids:
        resolver = get_resolver()
        for node in sorted(orphan_ids):
            resolver.remove(node)

    log.info(
        "Cleanup complete: scanned=%d, orphaned=%d, dry_run=%s",
        scanned,
        orphaned,
        dry_run,
    )
    return {"scanned": scanned, "orphaned": orphaned}
