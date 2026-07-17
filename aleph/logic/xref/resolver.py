"""
XrefResolver: ACID judgement graph on Postgres, suggestions and result
listings on Elasticsearch (see xref-resolver-sql.md).

Architecture:
- Postgres is the system of record for decided edges (positive/negative/
  unsure) and the materialized cluster membership, written in ONE
  transaction under a global advisory lock (aleph.logic.xref.store).
- Graph reads resolve an entity's cluster via a membership point lookup;
  the per-edge auth contract (both collections readable) is applied over
  the cluster's edges in SQL — O(cluster), independent of graph size.
- Suggestions (NO_JUDGEMENT) never touch SQL: they live in the ES xref
  index exactly as before, powering the XrefQuery results UI.
- Decided edges are *projected* to the same ES index after commit (same
  ESEdge docs, deterministic per-pair ids) so listings, export and
  entity filters keep working. Listings are the only eventually-consistent
  surface; the graph never is. Repair: `aleph xref-reproject`.
- The class keeps nomenklatura Resolver API parity (guarded by
  aleph/tests/test_xref_parity.py) but does not subclass it: since 4.11
  upstream inlines SQL statements into every method, so there is no
  storage seam to override.
"""

import logging
from contextlib import contextmanager
from typing import Generator, Iterable, Iterator

from anystore.io import smart_stream_json_models, smart_write_models
from anystore.types import Uri
from followthemoney import SE, Statement, registry
from nomenklatura.judgement import Judgement
from nomenklatura.resolver.edge import Edge
from nomenklatura.resolver.identifier import Identifier, StrIdent
from nomenklatura.resolver.linker import Linker
from openaleph_search.index.mapping import Field
from openaleph_search.model import SearchAuth
from rigour.ids.wikidata import is_qid
from sqlalchemy.orm import Session

from aleph.index.xref import (
    _now,
    auth_filters,
    bulk_index_edges,
    index_edge,
    prune_edges,
    query_edges,
    remove_nodes,
    soft_delete_edge,
)
from aleph.logic.xref import store
from aleph.model.xref import SYSTEM_USER, ESEdge, XrefEdge
from aleph.settings import SETTINGS

log = logging.getLogger(__name__)


def _edge_metadata(
    left_id: StrIdent,
    right_id: StrIdent,
    left_collection_ids: set[int] | None = None,
    right_collection_ids: set[int] | None = None,
    method: str | None = None,
    schema: str | None = None,
    text: list[str] | None = None,
    countries: list[str] | None = None,
) -> dict:
    """Store kwargs (collections + meta) for the pair's edge row.

    Aligns the caller's left/right collection IDs with the edge's
    source/target ordering: Identifier.pair determines which entity
    becomes edge.source; the caller's left/right order may differ.
    """
    _, pair_source = Identifier.pair(left_id, right_id)
    left_is_source = Identifier.get(left_id) == pair_source
    source_cids = left_collection_ids if left_is_source else right_collection_ids
    target_cids = right_collection_ids if left_is_source else left_collection_ids
    meta = {"method": method, "schema": schema, "text": text, "countries": countries}
    return {
        "source_collection_ids": set(source_cids or ()),
        "target_collection_ids": set(target_cids or ()),
        "meta": {k: v for k, v in meta.items() if v},
    }


class XrefResolver:
    """nomenklatura-style resolver over Postgres (graph) and ES (queue).

    Same public API as ``nomenklatura.resolver.Resolver`` plus aleph's
    metadata-aware ``suggest``/``decide`` signatures, ``bulk()`` and
    ``import_decisions()``. Stateless apart from the ES write buffer.
    """

    def __init__(self, auth: SearchAuth | None = None, sync: bool = False):
        self._auth = auth
        self._sync = sync or SETTINGS.TESTING
        self._edge_buffer: list[ESEdge] = []
        self._bulk_mode = False
        self._bulk_size = 10_000

    # -- bulk mode (ES writes: suggestions + projection) ---

    @contextmanager
    def bulk(self, size: int = 10_000):
        """Buffer ES edge writes and flush in batches."""
        self._bulk_mode = True
        self._bulk_size = size
        try:
            yield self
            self.flush()
        finally:
            self._bulk_mode = False
            self._edge_buffer.clear()

    def flush(self) -> None:
        if self._edge_buffer:
            bulk_index_edges(self._edge_buffer, sync=self._sync)
            self._edge_buffer.clear()

    def _index_edge(self, es_edge: ESEdge) -> None:
        """Index or buffer a single ES edge document."""
        if self._bulk_mode:
            self._edge_buffer.append(es_edge)
            if len(self._edge_buffer) >= self._bulk_size:
                self.flush()
        else:
            index_edge(es_edge, sync=self._sync)

    # -- lifecycle ---

    def commit(self) -> None:
        pass  # graph writes are transactional per call; kept for API parity

    def close(self) -> None:
        pass  # stateless apart from the ES buffer; kept for API parity

    # -- ES projection of committed rows ---

    def _project(self, rows: list[XrefEdge]) -> None:
        """Mirror committed rows into the ES xref index (listings only).

        Superseded rows come before their replacement in ``rows``, so the
        shared per-pair document id converges on the live row.
        """
        for row in rows:
            self._index_edge(store.row_doc(row))

    # -- suggest / decide (extended with aleph metadata) ---

    def suggest(
        self,
        left_id: StrIdent,
        right_id: StrIdent,
        score: float,
        user: str = SYSTEM_USER,
        source_collection_id: set[int] | None = None,
        target_collection_id: set[int] | None = None,
        method: str | None = None,
        schema: str | None = None,
        text: list[str] | None = None,
        countries: list[str] | None = None,
    ) -> Identifier:
        """Extended suggest with metadata fields.

        Won't overwrite existing judgements - only creates new
        NO_JUDGEMENT edges or updates scores on existing NO_JUDGEMENT edges.
        Suggestions are pure ES documents; SQL is only consulted (via
        get_edge) to protect existing decisions.
        """
        kwargs = _edge_metadata(
            left_id,
            right_id,
            source_collection_id,
            target_collection_id,
            method=method,
            schema=schema,
            text=text,
            countries=countries,
        )
        metadata = {
            "source_collection_id": kwargs["source_collection_ids"],
            "target_collection_id": kwargs["target_collection_ids"],
            **kwargs["meta"],
        }
        edge = self.get_edge(left_id, right_id)
        if edge is not None:
            if edge.judgement == Judgement.NO_JUDGEMENT:
                edge_ = ESEdge.from_edge(edge, **metadata)
                edge_.score = score
                self._index_edge(edge_)
            return edge.target

        edge = Edge(
            left_id,
            right_id,
            judgement=Judgement.NO_JUDGEMENT,
            score=score,
            user=user or SYSTEM_USER,
            created_at=_now(),
        )
        self._index_edge(ESEdge.from_edge(edge, **metadata))
        return edge.target

    def decide(
        self,
        left_id: StrIdent,
        right_id: StrIdent,
        judgement: Judgement,
        user: str = SYSTEM_USER,
        score: float | None = None,
        source_collection_id: set[int] | None = None,
        target_collection_id: set[int] | None = None,
    ) -> Identifier:
        """Make a decision, with optional collection metadata.

        ``source_collection_id`` belongs to ``left_id``,
        ``target_collection_id`` to ``right_id``. For POSITIVE judgements,
        entities are redirected through NK-* canonical IDs; the entity side
        of each entity→NK-* edge carries the entity's own collection_ids,
        the NK-* side the counterpart's.
        """
        if judgement == Judgement.POSITIVE:
            return self._decide_positive(
                left_id, right_id, user, source_collection_id, target_collection_id
            )
        return self._decide_blocker(
            left_id,
            right_id,
            judgement,
            user,
            score,
            source_collection_id,
            target_collection_id,
        )

    def _decide_positive(
        self,
        left_id: StrIdent,
        right_id: StrIdent,
        user: str,
        source_collection_id: set[int] | None,
        target_collection_id: set[int] | None,
    ) -> Identifier:
        pair_target, pair_source = Identifier.pair(left_id, right_id)
        # Align the caller's left/right collections with the pair ordering.
        left_is_source = Identifier.get(left_id) == pair_source
        source_colls = (
            source_collection_id if left_is_source else target_collection_id
        ) or set()
        target_colls = (
            target_collection_id if left_is_source else source_collection_id
        ) or set()
        rows: list[XrefEdge] = []
        redirected = False
        with store.xref_session() as session:
            store.acquire_graph_lock(session)
            source_view = store.load_cluster(session, pair_source.id)
            target_view = store.load_cluster(session, pair_target.id)
            members = source_view.members | target_view.members
            target = max(Identifier.get(n) for n in members)
            # When one side of the edge is already the cluster canonical
            # (or two canonicals merge), register the edge directly.
            # Otherwise, redirect both sides through a canonical — either
            # a new NK-* or an existing one.
            if target in (pair_source, pair_target) and target.canonical:
                row = store.ensure_positive_edge(
                    session,
                    pair_source,
                    pair_target,
                    user=user or SYSTEM_USER,
                    **_edge_metadata(
                        pair_source, pair_target, source_colls, target_colls
                    ),
                )
                if row is not None:
                    rows.append(row)
                store.set_membership(session, members, target.id)
                result = pair_target
            else:
                canonical = target if target.canonical else Identifier.make()
                superseded = store.supersede_pair(session, pair_source, pair_target)
                if superseded is not None:
                    rows.append(superseded)
                # Create entity→NK-* edges. Each edge carries:
                #   entity side: the entity's own collection_ids
                #   NK-* side:   the OTHER entity's collection_ids
                # This preserves auth chain semantics: to traverse an
                # entity→NK-* edge, the user must have access to both
                # the entity's collection AND the collection of the entity
                # it was paired with in the original decision. An identical
                # live positive edge is kept as-is (original provenance).
                for node, own, other in (
                    (pair_source, source_colls, target_colls),
                    (pair_target, target_colls, source_colls),
                ):
                    row = store.ensure_positive_edge(
                        session,
                        node,
                        canonical,
                        user=user or SYSTEM_USER,
                        **_edge_metadata(node, canonical, own, other),
                    )
                    if row is not None:
                        rows.append(row)
                store.set_membership(session, members | {canonical.id}, canonical.id)
                result = canonical
                redirected = True
        if redirected:
            # The direct pair edge may exist as an ES-only suggestion doc,
            # which SQL superseding cannot see — tombstone it explicitly.
            soft_delete_edge(pair_source.id, pair_target.id, sync=self._sync)
        self._project(rows)
        return result

    def _decide_blocker(
        self,
        left_id: StrIdent,
        right_id: StrIdent,
        judgement: Judgement,
        user: str,
        score: float | None,
        source_collection_id: set[int] | None,
        target_collection_id: set[int] | None,
    ) -> Identifier:
        pair_target, pair_source = Identifier.pair(left_id, right_id)
        kwargs = _edge_metadata(
            left_id, right_id, source_collection_id, target_collection_id
        )
        rows: list[XrefEdge] = []
        with store.xref_session() as session:
            store.acquire_graph_lock(session)
            seeds: set[str] = set()
            prior = store.supersede_pair(session, pair_source, pair_target)
            if prior is not None:
                rows.append(prior)
                if prior.judgement == Judgement.POSITIVE.value:
                    # Demoting a POSITIVE edge can split its cluster.
                    seeds.update((pair_source.id, pair_target.id))
            if judgement != Judgement.NO_JUDGEMENT:
                rows.append(
                    store.insert_edge(
                        session,
                        pair_source,
                        pair_target,
                        judgement,
                        user or SYSTEM_USER,
                        **kwargs,
                    )
                )
            stale = self._stale_positive_rows(session, pair_source, pair_target)
            for row in stale:
                seeds.update((row.source, row.target))
            rows.extend(stale)
            if seeds:
                store.split_recompute(session, seeds)
        self._project(rows)
        if judgement == Judgement.NO_JUDGEMENT:
            # The pair reverts to a suggestion — ES-only, keeping the score.
            edge = Edge(
                pair_source,
                pair_target,
                judgement=Judgement.NO_JUDGEMENT,
                score=score,
                user=user or SYSTEM_USER,
                created_at=_now(),
            )
            self._index_edge(
                ESEdge.from_edge(
                    edge,
                    source_collection_id=kwargs["source_collection_ids"],
                    target_collection_id=kwargs["target_collection_ids"],
                    **kwargs["meta"],
                )
            )
        return pair_target

    def _stale_positive_rows(
        self, session: Session, left: Identifier, right: Identifier
    ) -> list[XrefEdge]:
        """Drop stale positive edges after a non-positive decision.

        When removing an entity from a cluster (undecide/negative on an
        entity→NK-* edge), also soft-delete any other positive edges
        this entity has to other NK-* identifiers in the same cluster.
        These stale edges arise when clusters merge: the old NK-* edges
        are never cleaned up, so the entity remains transitively connected.
        """
        entity_node = None
        if right.canonical and not left.canonical:
            entity_node = left
        elif left.canonical and not right.canonical:
            entity_node = right
        if entity_node is None:
            return []
        stale: list[XrefEdge] = []
        now = store.utcnow()
        for row in store.live_node_edges(session, entity_node.id, positive_only=True):
            other = row.target if row.source == entity_node.id else row.source
            if Identifier.get(other).canonical and other not in (left.id, right.id):
                row.deleted_at = now
                stale.append(row)
        return stale

    # -- node removal ---

    def remove(self, node_id: StrIdent) -> None:
        """Remove all edges linking to the given node from the graph."""
        node = Identifier.get(node_id)
        with store.xref_session() as session:
            store.acquire_graph_lock(session)
            rows = store.soft_delete_node_edges(session, {node.id})
            if rows:
                seeds = {node.id}
                for row in rows:
                    seeds.update((row.source, row.target))
                store.split_recompute(session, seeds)
        # ES side covers decided docs AND suggestions touching the node
        remove_nodes([node.id], sync=self._sync)

    def explode(self, node_id: StrIdent) -> set[str]:
        """Dissolve all edges linked to the cluster to which the node belongs.
        This is the hard way to make sure we re-do context once we realise
        there's been a mistake."""
        node = Identifier.get(node_id)
        with store.xref_session() as session:
            store.acquire_graph_lock(session)
            view = store.load_cluster(session, node.id, auth=self._auth)
            affected = {str(part) for part in view.component}
            seeds = set(affected)
            for row in store.soft_delete_node_edges(session, affected):
                seeds.update((row.source, row.target))
            store.split_recompute(session, seeds)
        remove_nodes(sorted(affected), sync=self._sync)
        return affected

    # -- graph reads (SQL) ---

    def connected(self, node: Identifier) -> set[Identifier]:
        with store.xref_session() as session:
            view = store.load_cluster(session, str(node), auth=self._auth)
        return {Identifier.get(n) for n in view.component}

    def get_canonical(self, entity_id: StrIdent) -> str:
        node = Identifier.get(entity_id)
        with store.xref_session() as session:
            if self._auth is None or self._auth.is_admin:
                canonical_id = store.get_canonical_id(session, node.id)
                if canonical_id is not None:
                    if Identifier.get(canonical_id).canonical:
                        return canonical_id
                return node.id
            view = store.load_cluster(session, node.id, auth=self._auth)
        return view.visible_canonical

    def canonicals(self) -> Generator[Identifier, None, None]:
        """Return all the canonical cluster identifiers."""
        with store.xref_session() as session:
            for canonical_id in store.iter_canonicals(session):
                ident = Identifier.get(canonical_id)
                if ident.canonical:
                    yield ident

    def get_referents(
        self, canonical_id: StrIdent, canonicals: bool = True
    ) -> set[str]:
        """Get all the non-canonical entity identifiers which refer to a given
        canonical identifier."""
        node = Identifier.get(canonical_id)
        with store.xref_session() as session:
            view = store.load_cluster(session, node.id, auth=self._auth)
        referents: set[str] = set()
        for member in view.component:
            ident = Identifier.get(member)
            if not canonicals and ident.canonical:
                continue
            if ident == node:
                continue
            referents.add(member)
        return referents

    def get_judgement(self, entity_id: StrIdent, other_id: StrIdent) -> Judgement:
        """Get the existing decision between two entities with dedupe factored in."""
        entity = str(entity_id)
        other = str(other_id)
        if entity == other:
            return Judgement.POSITIVE
        with store.xref_session() as session:
            entity_view = store.load_cluster(session, entity, auth=self._auth)
            if other in entity_view.component:
                return Judgement.POSITIVE
            # Check QIDs after connected because we sometimes insert an edge
            # to say one QID is canonical for another. Not common but important.
            if is_qid(entity) and is_qid(other):
                return Judgement.NEGATIVE
            other_view = store.load_cluster(session, other, auth=self._auth)
            # Any blocking (negative/unsure) edge spanning the two clusters
            # decides the pair. A positive edge can't span them — it would
            # have merged the clusters above.
            row = store.edge_between(
                session,
                entity_view.component,
                other_view.component,
                judgements=store.BLOCKERS,
                auth=self._auth,
            )
        if row is None:
            return Judgement.NO_JUDGEMENT
        return Judgement(row.judgement)

    def check_candidate(self, left: StrIdent, right: StrIdent) -> bool:
        """Check if the two IDs could be merged, i.e. if there's no existing
        judgement."""
        judgement = self.get_judgement(left, right)
        return judgement == Judgement.NO_JUDGEMENT

    # -- edge reads ---

    def get_edge(self, left_id: StrIdent, right_id: StrIdent) -> Edge | None:
        """The live decided edge for the pair (SQL), else its ES suggestion."""
        with store.xref_session() as session:
            row = store.live_pair_row(session, left_id, right_id, auth=self._auth)
        if row is not None:
            return store.row_to_edge(row)
        target, source = Identifier.pair(left_id, right_id)
        # Use a query instead of direct doc lookup to apply auth + soft-delete filters
        filters = [
            {"term": {Field.ENTITIES: source.id}},
            {"term": {Field.ENTITIES: target.id}},
            {"term": {"judgement": Judgement.NO_JUDGEMENT.value}},
        ]
        if self._auth:
            filters.extend(auth_filters(self._auth))
        docs = query_edges(filters, size=1)
        if not docs:
            return None
        return Edge.from_dict(docs[0])

    def get_resolved_edge(self, left_id: StrIdent, right_id: StrIdent) -> Edge | None:
        """
        Return _some_ decided edge that connects the two entities, if it exists.
        """
        with store.xref_session() as session:
            left_view = store.load_cluster(session, str(left_id), auth=self._auth)
            right_view = store.load_cluster(session, str(right_id), auth=self._auth)
            row = store.edge_between(
                session, left_view.component, right_view.component, auth=self._auth
            )
        if row is None:
            return None
        return store.row_to_edge(row)

    def get_judgements(self, limit: int | None = None) -> Generator[Edge, None, None]:
        """Get most recently updated edges other than NO_JUDGEMENT."""
        with store.xref_session() as session:
            rows = store.recent_edges(session, limit=limit)
        for row in rows:
            yield store.row_to_edge(row)

    # -- suggestion queue (ES) ---

    def _get_suggested(self) -> list[Edge]:
        """Get all NO_JUDGEMENT edges in descending order of score."""
        docs = query_edges(
            [{"term": {"judgement": "no_judgement"}}],
            sort=[{"score": "desc"}],
            size=1000,
        )
        return [Edge.from_dict(d) for d in docs]

    def get_candidates(
        self, limit: int | None = None
    ) -> Iterator[tuple[str, str, float | None]]:
        returned = 0
        for edge in self._get_suggested():
            if not self.check_candidate(edge.source, edge.target):
                continue
            yield edge.target.id, edge.source.id, edge.score
            returned += 1
            if limit is not None and returned >= limit:
                break

    def prune(self, user: str | None = None) -> None:
        """Remove suggested (i.e. NO_JUDGEMENT) edges."""
        prune_edges(user=user, sync=self._sync)

    # -- bulk import (decision imports, auto-merge) ---

    def import_decisions(
        self,
        decisions: Iterable[ESEdge],
        max_cluster_size: int | None = None,
        batch_size: int = 5000,
    ) -> dict[str, int]:
        """Bulk-apply decided edges. Imports supersede existing judgements
        (identical live POSITIVE edges are kept — idempotent re-import).

        POSITIVE edges that would grow a cluster past max_cluster_size
        (None: SETTINGS.XREF_MAX_CLUSTER_SIZE; 0: uncapped, e.g. for
        replaying human decisions) are queued as ES suggestions for human
        review instead of applied.
        """
        cap = (
            SETTINGS.XREF_MAX_CLUSTER_SIZE
            if max_cluster_size is None
            else max_cluster_size or None
        )
        stats = {"applied": 0, "diverted": 0, "skipped": 0}
        batch: list[ESEdge] = []
        for doc in decisions:
            if Judgement(doc.judgement) == Judgement.NO_JUDGEMENT:
                stats["skipped"] += 1
                continue
            batch.append(doc)
            if len(batch) >= batch_size:
                self._import_batch(batch, cap, stats)
                batch = []
        if batch:
            self._import_batch(batch, cap, stats)
        return stats

    def _import_batch(
        self, batch: list[ESEdge], cap: int | None, stats: dict[str, int]
    ) -> None:
        with store.xref_session() as session:
            result = store.import_batch(session, batch, max_cluster_size=cap)
        self._project(result.applied)
        for doc in result.diverted:
            # Capped merge: queue as a suggestion for human review.
            self._index_edge(
                doc.model_copy(
                    update={
                        "judgement": Judgement.NO_JUDGEMENT.value,
                        "created_at": store.utcnow(),
                    }
                )
            )
        stats["applied"] += len(result.applied)
        stats["diverted"] += len(result.diverted)
        if result.diverted:
            log.info(
                "Import: %d merges over cluster cap queued as suggestions",
                len(result.diverted),
            )

    # -- linker / statements ---

    def get_linker(self) -> Linker[SE]:
        """Return a linker object that can be used to resolve entities.
        This is less memory-consuming than the full resolver object.

        Built from the materialized membership (system-level, no auth).
        """
        clusters: dict[str, list[str]] = {}
        with store.xref_session() as session:
            for entity_id, canonical_id in store.iter_membership(session):
                clusters.setdefault(canonical_id, []).append(entity_id)
        mapping: dict[str, tuple[str, ...]] = {}
        for members in clusters.values():
            idents = sorted((Identifier.get(m) for m in members), reverse=True)
            cluster = tuple(i.id for i in idents)
            for node in cluster:
                mapping[node] = cluster
        return Linker(mapping)

    def apply_statement(self, stmt: Statement) -> Statement:
        """Canonicalise Statement Entity IDs and ID values"""
        if stmt.entity_id is not None:
            stmt.canonical_id = self.get_canonical(stmt.entity_id)
        if stmt.prop_type == registry.entity.name:
            canon_value = self.get_canonical(stmt.value)
            if canon_value != stmt.value:
                if stmt.original_value is None:
                    stmt.original_value = stmt.value
                stmt = stmt.clone(value=canon_value)
        return stmt

    # -- dump / load ---

    def dump(self, uri: Uri) -> None:
        """Dump non-NO_JUDGEMENT edges to file. Other than original NK Resolver
        we don't include soft-delete here."""
        with store.xref_session() as session:
            docs = (store.row_doc(row) for row in store.iter_live_edges(session))
            smart_write_models(uri, docs)

    def load(self, uri: Uri) -> None:
        """Load dumped edges into the graph (NK-* ids are preserved)."""
        self.import_decisions(smart_stream_json_models(uri, ESEdge))

    def __repr__(self) -> str:
        return "<XrefResolver>"


def get_resolver(auth: SearchAuth | None = None, sync: bool = False) -> XrefResolver:
    return XrefResolver(auth, sync=sync)
