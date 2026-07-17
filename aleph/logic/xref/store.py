"""
SQL store for the xref judgement graph (see xref-resolver-sql.md).

Postgres is the system of record: `xref_edge` holds decided edges
(positive/negative/unsure — suggestions stay in ES), `xref_cluster` the
materialized membership, both written in the same transaction under one
global advisory lock. Reads resolve an entity's cluster via a membership
point lookup and apply the per-edge auth contract (both collections
readable) over the cluster's edges — never over the whole graph.

This module is deliberately resolver-agnostic: it deals in rows, ids and
Judgements. ES projection and metadata semantics live in
aleph.logic.xref.resolver.
"""

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator

from nomenklatura.judgement import Judgement
from nomenklatura.resolver.edge import Edge
from nomenklatura.resolver.identifier import Identifier, StrIdent
from nomenklatura.resolver.linker import Linker
from openaleph_search.model import SearchAuth
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from aleph.core import db
from aleph.index.xref import bulk_index_edges, delete_xref
from aleph.model.collection import Collection
from aleph.model.xref import ESEdge, XrefCluster, XrefEdge

log = logging.getLogger(__name__)

# Single global advisory lock serializing all graph mutations. Correctness
# first: it is trivially deadlock-free and write rates are modest (UI
# decides are human-rate; imports amortize the lock over batches). If
# contention ever shows, per-cluster locking swaps in inside
# acquire_graph_lock() without touching callers.
XREF_GRAPH_LOCK = 0x616C6672  # "alfr"

LIVE = XrefEdge.deleted_at.is_(None)
BLOCKERS = (Judgement.NEGATIVE.value, Judgement.UNSURE.value)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def xref_session() -> Iterator[Session]:
    """Dedicated unit-of-work session for the judgement graph.

    Isolated from the request-scoped ``db.session`` so a graph commit can
    never flush unrelated request state (and vice versa).

    ``expire_on_commit=False``: callers read committed rows after the
    session closes (ES projection, Edge conversion). XrefEdge/XrefCluster
    are relationship-free, so detached instances stay fully readable.
    """
    session = Session(db.engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def acquire_graph_lock(session: Session) -> None:
    """Serialize graph mutations; released at commit/rollback."""
    session.execute(select(func.pg_advisory_xact_lock(XREF_GRAPH_LOCK)))


def _auth_clause(auth: SearchAuth | None):
    """Per-edge auth contract: BOTH collections on an edge must be readable."""
    if auth is None or auth.is_admin:
        return None
    readable = sorted(auth.collection_ids)
    return and_(
        XrefEdge.source_collection_ids.overlap(readable),
        XrefEdge.target_collection_ids.overlap(readable),
    )


def row_doc(row: XrefEdge) -> ESEdge:
    """Convert a table row to its ES projection document."""
    meta = row.meta or {}
    return ESEdge(
        source=row.source,
        target=row.target,
        judgement=row.judgement,
        score=row.score,
        user=row.user,
        created_at=row.created_at,
        deleted_at=row.deleted_at,
        source_collection_id=set(row.source_collection_ids or ()),
        target_collection_id=set(row.target_collection_ids or ()),
        method=meta.get("method"),
        schema=meta.get("schema"),
        text=meta.get("text") or [],
        countries=meta.get("countries") or [],
    )


def row_to_edge(row: XrefEdge) -> Edge:
    """Convert a table row to a nomenklatura Edge."""
    edge = Edge(
        row.target,
        row.source,
        judgement=Judgement(row.judgement),
        score=row.score,
        user=row.user,
        created_at=row.created_at.isoformat() if row.created_at else None,
    )
    if row.deleted_at is not None:
        edge.deleted_at = row.deleted_at.isoformat()
    return edge


def _doc_meta(doc: ESEdge) -> dict:
    """The meta JSONB payload for an incoming decision document."""
    return {
        "method": doc.method,
        "schema": doc.schema_,
        "text": doc.text,
        "countries": doc.countries,
    }


# -- membership reads ---


def get_canonical_id(session: Session, entity_id: str) -> str | None:
    stmt = select(XrefCluster.canonical_id)
    stmt = stmt.where(XrefCluster.entity_id == entity_id)
    return session.scalar(stmt)


def cluster_members(session: Session, canonical_id: str) -> set[str]:
    stmt = select(XrefCluster.entity_id)
    stmt = stmt.where(XrefCluster.canonical_id == canonical_id)
    return set(session.scalars(stmt))


def memberships(session: Session, entity_ids: set[str]) -> dict[str, str]:
    stmt = select(XrefCluster.entity_id, XrefCluster.canonical_id)
    stmt = stmt.where(XrefCluster.entity_id.in_(sorted(entity_ids)))
    return dict(session.execute(stmt).all())


def iter_membership(session: Session) -> Iterator[tuple[str, str]]:
    stmt = select(XrefCluster.entity_id, XrefCluster.canonical_id)
    yield from session.execute(stmt.execution_options(yield_per=10_000))


def iter_canonicals(session: Session) -> Iterator[str]:
    stmt = select(XrefCluster.canonical_id).distinct()
    yield from session.scalars(stmt.execution_options(yield_per=10_000))


# -- cluster view (the hot read path) ---


@dataclass
class ClusterView:
    """One entity's cluster, restricted to the auth-visible subgraph.

    ``component`` is the set of nodes reachable from ``entity_id`` via
    visible positive edges (always contains ``entity_id``); without auth it
    equals the materialized membership.
    """

    entity_id: str
    canonical_id: str | None  # global membership pointer (None: singleton)
    members: set[str]
    component: set[str]

    @property
    def visible_canonical(self) -> str:
        best = max(Identifier.get(n) for n in self.component)
        if best.canonical:
            return best.id
        return self.entity_id


def _component(seed: str, edges: list[XrefEdge]) -> set[str]:
    """Connected component of seed within the given edge set."""
    adjacent: dict[str, set[str]] = {}
    for e in edges:
        adjacent.setdefault(e.source, set()).add(e.target)
        adjacent.setdefault(e.target, set()).add(e.source)
    seen = {seed}
    queue = [seed]
    while queue:
        node = queue.pop()
        for other in adjacent.get(node, ()):
            if other not in seen:
                seen.add(other)
                queue.append(other)
    return seen


def edges_among(
    session: Session,
    members: set[str],
    auth: SearchAuth | None = None,
    positive_only: bool = True,
) -> list[XrefEdge]:
    """Live edges among the given nodes, optionally auth-filtered."""
    ids = sorted(members)
    stmt = select(XrefEdge).where(
        LIVE, XrefEdge.source.in_(ids), XrefEdge.target.in_(ids)
    )
    if positive_only:
        stmt = stmt.where(XrefEdge.judgement == Judgement.POSITIVE.value)
    clause = _auth_clause(auth)
    if clause is not None:
        stmt = stmt.where(clause)
    return list(session.scalars(stmt))


def load_cluster(
    session: Session, entity_id: str, auth: SearchAuth | None = None
) -> ClusterView:
    canonical_id = get_canonical_id(session, entity_id)
    if canonical_id is None:
        return ClusterView(entity_id, None, {entity_id}, {entity_id})
    members = cluster_members(session, canonical_id)
    members.add(entity_id)
    if _auth_clause(auth) is None:
        # Unfiltered view: the materialized membership IS the component.
        return ClusterView(entity_id, canonical_id, members, set(members))
    edges = edges_among(session, members, auth=auth, positive_only=True)
    component = _component(entity_id, edges)
    return ClusterView(entity_id, canonical_id, members, component)


# -- edge reads ---


def live_pair_row(
    session: Session,
    left_id: StrIdent,
    right_id: StrIdent,
    auth: SearchAuth | None = None,
) -> XrefEdge | None:
    target, source = Identifier.pair(left_id, right_id)
    stmt = select(XrefEdge).where(
        LIVE, XrefEdge.source == source.id, XrefEdge.target == target.id
    )
    clause = _auth_clause(auth)
    if clause is not None:
        stmt = stmt.where(clause)
    return session.scalar(stmt.limit(1))


def live_node_edges(
    session: Session, node_id: str, positive_only: bool = False
) -> list[XrefEdge]:
    stmt = select(XrefEdge).where(
        LIVE, or_(XrefEdge.source == node_id, XrefEdge.target == node_id)
    )
    if positive_only:
        stmt = stmt.where(XrefEdge.judgement == Judgement.POSITIVE.value)
    return list(session.scalars(stmt))


def edge_between(
    session: Session,
    a_members: set[str],
    b_members: set[str],
    judgements: tuple[str, ...] | None = None,
    auth: SearchAuth | None = None,
) -> XrefEdge | None:
    """Most recent live edge spanning the two member sets."""
    a, b = sorted(a_members), sorted(b_members)
    stmt = select(XrefEdge).where(
        LIVE,
        or_(
            and_(XrefEdge.source.in_(a), XrefEdge.target.in_(b)),
            and_(XrefEdge.source.in_(b), XrefEdge.target.in_(a)),
        ),
    )
    if judgements is not None:
        stmt = stmt.where(XrefEdge.judgement.in_(judgements))
    clause = _auth_clause(auth)
    if clause is not None:
        stmt = stmt.where(clause)
    return session.scalar(stmt.order_by(XrefEdge.created_at.desc()).limit(1))


def iter_live_edges(session: Session) -> Iterator[XrefEdge]:
    """All live decided edges (dump / ES reprojection)."""
    stmt = select(XrefEdge).where(LIVE).order_by(XrefEdge.created_at.asc())
    yield from session.scalars(stmt.execution_options(yield_per=10_000))


def recent_edges(session: Session, limit: int | None = None) -> list[XrefEdge]:
    stmt = select(XrefEdge).where(LIVE).order_by(XrefEdge.created_at.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt))


# -- edge writes (call under acquire_graph_lock) ---


def supersede_pair(
    session: Session, left_id: StrIdent, right_id: StrIdent
) -> XrefEdge | None:
    """Soft-delete the live row for the pair, returning it."""
    row = live_pair_row(session, left_id, right_id)
    if row is None:
        return None
    row.deleted_at = utcnow()
    return row


def insert_edge(
    session: Session,
    left_id: StrIdent,
    right_id: StrIdent,
    judgement: Judgement,
    user: str,
    score: float | None = None,
    source_collection_ids: set[int] | None = None,
    target_collection_ids: set[int] | None = None,
    meta: dict | None = None,
) -> XrefEdge:
    target, source = Identifier.pair(left_id, right_id)
    row = XrefEdge(
        target=target.id,
        source=source.id,
        judgement=judgement.value,
        score=score,
        user=user,
        created_at=utcnow(),
        source_collection_ids=sorted(source_collection_ids or ()),
        target_collection_ids=sorted(target_collection_ids or ()),
        meta={k: v for k, v in (meta or {}).items() if v},
    )
    session.add(row)
    return row


def ensure_positive_edge(
    session: Session,
    left_id: StrIdent,
    right_id: StrIdent,
    user: str,
    source_collection_ids: set[int] | None = None,
    target_collection_ids: set[int] | None = None,
    meta: dict | None = None,
) -> XrefEdge | None:
    """Register a POSITIVE edge unless an identical live one exists.

    Keeping the existing row preserves the original decision's provenance
    (user, timestamp) and its NK-side collection metadata — the documented
    auth semantics bind an entity→NK-* edge to the entity it was paired
    with in the *original* decision. It also makes re-imports idempotent.
    Returns the new row, or None when the existing edge was kept (nothing
    to project).
    """
    row = live_pair_row(session, left_id, right_id)
    if row is not None:
        if row.judgement == Judgement.POSITIVE.value:
            return None
        row.deleted_at = utcnow()
    return insert_edge(
        session,
        left_id,
        right_id,
        Judgement.POSITIVE,
        user,
        source_collection_ids=source_collection_ids,
        target_collection_ids=target_collection_ids,
        meta=meta,
    )


def soft_delete_node_edges(session: Session, node_ids: set[str]) -> list[XrefEdge]:
    """Soft-delete every live edge touching any of the nodes, returning them."""
    ids = sorted(node_ids)
    stmt = select(XrefEdge).where(
        LIVE, or_(XrefEdge.source.in_(ids), XrefEdge.target.in_(ids))
    )
    rows = list(session.scalars(stmt))
    now = utcnow()
    for row in rows:
        row.deleted_at = now
    return rows


# -- membership writes (call under acquire_graph_lock) ---


def set_membership(session: Session, node_ids: set[str], canonical_id: str) -> None:
    """Point all nodes — and the canonical itself — at canonical_id."""
    ids = sorted(set(node_ids) | {canonical_id})
    stmt = pg_insert(XrefCluster).values(
        [{"entity_id": n, "canonical_id": canonical_id} for n in ids]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["entity_id"],
        set_={"canonical_id": stmt.excluded.canonical_id},
    )
    session.execute(stmt)


def split_recompute(session: Session, seed_ids: set[str]) -> None:
    """Recompute membership for the clusters containing the seeds.

    Bounded to the affected clusters: their live positive edges are
    re-partitioned into components in-app; membership rows are rewritten
    atomically with the edge changes. Singleton components lose their rows
    (get_canonical falls back to the entity id).
    """
    canonical_ids = set(memberships(session, seed_ids).values())
    members = set(seed_ids)
    for canonical_id in canonical_ids:
        members |= cluster_members(session, canonical_id)
    if not members:
        return
    edges = edges_among(session, members, auth=None, positive_only=True)
    session.execute(
        delete(XrefCluster).where(XrefCluster.entity_id.in_(sorted(members)))
    )
    remaining = set(members)
    for edge in edges:
        if edge.source not in remaining:
            continue
        component = _component(edge.source, edges)
        remaining -= component
        if len(component) > 1:
            canonical = max(Identifier.get(n) for n in component)
            set_membership(session, component, canonical.id)


# -- bulk import (decision imports, auto-merge) ---


@dataclass
class ImportBatchResult:
    applied: list[XrefEdge] = field(default_factory=list)
    diverted: list[ESEdge] = field(default_factory=list)
    split_seeds: set[str] = field(default_factory=set)


def _seed_linker(session: Session, docs: list[ESEdge]) -> Linker:
    """Union-find over the incoming positive pairs' existing clusters.

    Existing clusters enter with their full membership (NK-* ids included,
    matching how the membership table counts them), so the size cap
    accounts for what is already merged.
    """
    touched: set[str] = set()
    for doc in docs:
        touched.update((doc.source, doc.target))
    linker: Linker = Linker({})
    for canonical_id in set(memberships(session, touched).values()):
        for member in cluster_members(session, canonical_id):
            linker.add(member, canonical_id)
    return linker


def import_batch(
    session: Session, docs: list[ESEdge], max_cluster_size: int | None = None
) -> ImportBatchResult:
    """Apply one batch of decisions. Imports supersede existing judgements;
    identical live POSITIVE edges are kept untouched (idempotent re-import).

    POSITIVE edges that would grow a cluster past max_cluster_size are not
    applied; they are returned as ``diverted`` for the caller to queue as
    ES suggestions instead.
    """
    acquire_graph_lock(session)
    result = ImportBatchResult()
    positives = [d for d in docs if Judgement(d.judgement) == Judgement.POSITIVE]
    blockers = [d for d in docs if Judgement(d.judgement) != Judgement.POSITIVE]

    linker = _seed_linker(session, positives)
    accepted: list[ESEdge] = []
    for doc in positives:
        merged = set(linker.connected_ids(doc.source))
        merged.update(linker.connected_ids(doc.target))
        if max_cluster_size is not None and len(merged) > max_cluster_size:
            result.diverted.append(doc)
            continue
        linker.add(doc.source, doc.target)
        accepted.append(doc)

    result.applied.extend(_apply_positive_components(session, linker, accepted))

    for doc in blockers:
        prior = supersede_pair(session, doc.source, doc.target)
        if prior is not None and prior.judgement == Judgement.POSITIVE.value:
            result.split_seeds.update((doc.source, doc.target))
        result.applied.append(
            insert_edge(
                session,
                doc.source,
                doc.target,
                Judgement(doc.judgement),
                doc.user,
                source_collection_ids=doc.source_collection_id,
                target_collection_ids=doc.target_collection_id,
                meta=_doc_meta(doc),
            )
        )
    if result.split_seeds:
        split_recompute(session, result.split_seeds)
    return result


def _apply_positive_components(
    session: Session, linker: Linker, accepted: list[ESEdge]
) -> list[XrefEdge]:
    """Write accepted positive edges canonicalized per component.

    Raw pairs (neither side canonical) are redirected through the
    component's canonical, mirroring decide(); edges that already point at
    the canonical are registered as-is (dump/load round-trips preserve
    NK-* ids this way).
    """
    by_cluster: dict[tuple[str, ...], list[ESEdge]] = {}
    for doc in accepted:
        by_cluster.setdefault(linker.connected_ids(doc.source), []).append(doc)

    rows: list[XrefEdge] = []
    for cluster, group in by_cluster.items():
        component = set(cluster)
        best = max(Identifier.get(n) for n in component)
        canonical = best if best.canonical else Identifier.make()
        seen_pairs: set[tuple[str, str]] = set()
        for doc in group:
            for node in (doc.source, doc.target):
                if node == canonical.id:
                    continue
                target, source = Identifier.pair(node, canonical)
                if (source.id, target.id) in seen_pairs:
                    continue
                seen_pairs.add((source.id, target.id))
                row = ensure_positive_edge(
                    session,
                    node,
                    canonical,
                    user=doc.user,
                    source_collection_ids=doc.source_collection_id,
                    target_collection_ids=doc.target_collection_id,
                    meta=_doc_meta(doc),
                )
                if row is not None:
                    rows.append(row)
        set_membership(session, component | {canonical.id}, canonical.id)
    return rows


# -- purge (collection/entity deletion, full wipe) ---


def purge(
    session: Session,
    collection_id: int | None = None,
    entity_id: str | None = None,
) -> None:
    """Remove judgement-graph data for a collection/entity, or everything.

    Filtered purges soft-delete edges and recompute the affected clusters;
    the unfiltered variant hard-wipes both tables (test/reset semantics).
    """
    acquire_graph_lock(session)
    if collection_id is None and entity_id is None:
        session.execute(delete(XrefEdge))
        session.execute(delete(XrefCluster))
        return
    stmt = select(XrefEdge).where(LIVE)
    if collection_id is not None:
        stmt = stmt.where(
            or_(
                XrefEdge.source_collection_ids.contains([collection_id]),
                XrefEdge.target_collection_ids.contains([collection_id]),
            )
        )
    if entity_id is not None:
        stmt = stmt.where(
            or_(XrefEdge.source == entity_id, XrefEdge.target == entity_id)
        )
    rows = list(session.scalars(stmt))
    now = utcnow()
    seeds: set[str] = set()
    for row in rows:
        row.deleted_at = now
        seeds.update((row.source, row.target))
    if seeds:
        split_recompute(session, seeds)


def purge_xref(
    collection: Collection | None = None,
    entity_id: str | None = None,
    sync: bool = False,
) -> None:
    """Purge the judgement graph (SQL) and the xref index (ES) for a
    collection or entity — or everything, when called without filters."""
    with xref_session() as session:
        collection_id = collection.id if collection is not None else None
        purge(session, collection_id=collection_id, entity_id=entity_id)
    delete_xref(collection=collection, entity_id=entity_id, sync=sync)


# -- repair (CLI: xref-reproject / xref-rebuild-clusters) ---


def iter_latest_pair_rows(session: Session) -> Iterator[XrefEdge]:
    """The most recent row per pair, live or soft-deleted.

    Soft-deleted latest rows must be projected too, so a missed tombstone
    in ES gets repaired — the per-pair document id makes this idempotent.
    """
    stmt = (
        select(XrefEdge)
        .distinct(XrefEdge.source, XrefEdge.target)
        .order_by(XrefEdge.source, XrefEdge.target, XrefEdge.created_at.desc())
    )
    yield from session.scalars(stmt.execution_options(yield_per=10_000))


def reproject(sync: bool = False) -> int:
    """Rebuild the ES projection of decided edges from the SQL graph."""
    count = 0

    def _docs(session: Session) -> Iterator[ESEdge]:
        nonlocal count
        for row in iter_latest_pair_rows(session):
            count += 1
            yield row_doc(row)

    with xref_session() as session:
        bulk_index_edges(_docs(session), sync=sync)
    return count


def rebuild_clusters() -> int:
    """Recompute the membership table from live positive edges.

    Offline verify/repair — the only full-graph union-find anywhere.
    """
    with xref_session() as session:
        acquire_graph_lock(session)
        linker: Linker = Linker({})
        stmt = select(XrefEdge.source, XrefEdge.target).where(
            LIVE, XrefEdge.judgement == Judgement.POSITIVE.value
        )
        for source, target in session.execute(stmt.execution_options(yield_per=10_000)):
            linker.add(source, target)
        session.execute(delete(XrefCluster))
        seen: set[int] = set()
        count = 0
        for cluster in linker._mapping.values():
            if id(cluster) in seen:
                continue
            seen.add(id(cluster))
            set_membership(session, set(cluster), cluster[0])
            count += len(cluster)
    return count
