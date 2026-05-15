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

from aleph.index.xref import scan_edges, soft_delete_edge

log = logging.getLogger(__name__)

NK_PREFIX = "NK-"


def cleanup_orphaned_edges(dry_run=False):
    """Scan all active edges and soft-delete those referencing non-existing entities.

    NK-* synthetic canonical IDs are excluded from existence checks since they
    don't correspond to real entities in the entity index.
    """
    scanned = 0
    orphaned = 0
    entity_cache = {}

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
        source = doc.get("source")
        target = doc.get("target")

        if not entity_exists(source) or not entity_exists(target):
            orphaned += 1
            if not dry_run:
                soft_delete_edge(source, target)
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

    log.info(
        "Cleanup complete: scanned=%d, orphaned=%d, dry_run=%s",
        scanned,
        orphaned,
        dry_run,
    )
    return {"scanned": scanned, "orphaned": orphaned}
