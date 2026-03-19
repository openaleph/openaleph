"""
ElasticsearchResolver: A nomenklatura Resolver backed by Elasticsearch.

Architecture:
- Stateless: no in-memory edges/nodes. All graph traversal queries ES directly
  via ESEdgeProxy and ESNodeProxy, which let the parent Resolver's logic
  (get_edge, get_resolved_edge, _traverse, connected, get_judgement, etc.)
  operate against ES transparently.
- Inherited from Linker: apply(), apply_properties(), apply_stream().
"""

import logging
from collections import defaultdict
from contextlib import contextmanager
from datetime import timedelta
from typing import Generator, Optional, Set

from anystore.io import smart_stream_json_models, smart_write_models
from anystore.types import Uri
from followthemoney import SE
from nomenklatura.judgement import Judgement
from nomenklatura.resolver.edge import Edge
from nomenklatura.resolver.identifier import Identifier, Pair, StrIdent
from nomenklatura.resolver.linker import Linker
from nomenklatura.resolver.resolver import Resolver
from openaleph_search.index.mapping import Field
from openaleph_search.model import SearchAuth

from aleph.index.xref import (
    _now,
    auth_filters,
    bulk_index_edges,
    count_edges,
    entities_filter,
    exclude_no_judgement,
    index_edge,
    prune_edges,
    query_edges,
    remove_node,
    scan_edges,
    scan_node_ids,
    soft_delete_edge,
)
from aleph.model.xref import SYSTEM_USER, ESEdge
from aleph.settings import SETTINGS

log = logging.getLogger(__name__)


class ESEdgeProxy:
    """Dict-like proxy routing self.edges lookups to ES.

    Supports the read patterns used by the parent Resolver:
    - get_edge() -> self.edges.get(key)
    - get_resolved_edge() -> self.edges.get(Identifier.pair(e, o))
    """

    def __init__(self, auth: SearchAuth | None = None):
        self._auth = auth

    def get(self, key: Pair, default: Edge | None = None) -> Edge | None:
        target, source = key
        # Use a query instead of direct doc lookup to apply auth + soft-delete filters
        filters = [
            {"term": {Field.ENTITIES: source.id}},
            {"term": {Field.ENTITIES: target.id}},
        ]
        if self._auth:
            filters.extend(auth_filters(self._auth))
        docs = query_edges(filters, size=1)
        if not docs:
            return default
        return Edge.from_dict(docs[0])

    def __len__(self) -> int:
        return count_edges()

    def __contains__(self, item: Edge | Pair) -> bool:
        key = item.key if isinstance(item, Edge) else item
        return self.get(key) is not None

    # No-ops for parent compatibility (_update_edge writes)
    def pop(self, key: Pair, default: Edge | None = None) -> Edge | None:
        return default

    def __setitem__(self, key: Pair, value: Edge) -> None:
        pass

    def clear(self) -> None:
        pass


class ESNodeProxy:
    """Dict-like proxy routing self.nodes lookups to ES.

    Supports the read pattern used by the parent's _traverse():
        for edge in self.nodes.get(node, []):
            if edge.judgement == Judgement.POSITIVE: ...
    """

    def __init__(self, auth: SearchAuth | None = None):
        self._auth = auth

    def get(self, node: Identifier, default: list[Edge] | None = None) -> list[Edge]:
        filters = [entities_filter(node.id)]
        if self._auth:
            filters.extend(auth_filters(self._auth))
        docs = query_edges(filters, sort=[{"score": "desc"}], size=1000)
        return [Edge.from_dict(d) for d in docs] or (default or [])

    def __iter__(self):
        """Iterate all distinct node Identifiers from active edges."""
        filters = []
        if self._auth:
            filters.extend(auth_filters(self._auth))
        for node_id in scan_node_ids(filters):
            yield Identifier.get(node_id)

    def keys(self):
        return iter(self)

    # No-ops for parent compatibility (_update_edge writes)
    def __setitem__(self, key: Identifier, value: set[Edge]) -> None:
        pass

    def __delitem__(self, key: Identifier) -> None:
        pass

    def __contains__(self, key: Identifier) -> bool:
        return False

    def clear(self) -> None:
        pass


class ElasticsearchResolver(Resolver[SE]):
    """Resolver backed by Elasticsearch instead of SQL.

    Stateless: graph traversal inherited from the parent Resolver operates
    against ES via ESEdgeProxy (self.edges) and ESNodeProxy (self.nodes).

    Methods inherited from parent (no override needed):
    - get_edge, get_resolved_edge, _pair_judgement
    - _traverse, connected
    - get_judgement, get_referents
    """

    def __init__(self, auth: SearchAuth | None = None, sync: bool = False):
        # Skip Resolver.__init__ which expects (engine, metadata, ...).
        self._auth = auth
        self._sync = sync or SETTINGS.TESTING
        self._metadata: dict[Pair, dict] = {}
        # Maps entity_id -> collection_ids for propagating collection metadata
        # during recursive canonical creation (decide -> entity->NK-* edges)
        self._entity_collections: defaultdict[str, set[int]] = defaultdict(set)
        self.edges = ESEdgeProxy(auth)
        self.nodes = ESNodeProxy(auth)
        self._edge_buffer: list[ESEdge] = []
        self._bulk_mode = False
        self._bulk_size = 10_000

    # -- bulk mode ---

    @contextmanager
    def bulk(self, size: int = 10_000):
        """Buffer edge writes and flush in batches."""
        self._bulk_mode = True
        self._bulk_size = size
        try:
            yield self
            self.flush()
        finally:
            self._bulk_mode = False
            self._edge_buffer.clear()

    def flush(self):
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

    # -- cache / invalidation ---

    def _invalidate(self) -> None:
        pass  # No lru_cache to clear

    def _update_edge(self, edge: Edge) -> None:
        pass  # Stateless: no in-memory state to update

    # -- lifecycle (no-ops for stateless resolver) ---

    def begin(self, load_edges: bool = True) -> None:
        pass  # No SQL transaction needed

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self._metadata.clear()
        self._entity_collections.clear()

    def _get_connection(self):
        raise RuntimeError("ElasticsearchResolver does not use SQL connections.")

    # -- edge write (override SQL -> ES) ---

    def _register(self, edge: Edge) -> None:
        if edge.judgement != Judgement.NO_JUDGEMENT:
            edge.score = None
        metadata = self._metadata.get(edge.key, {})
        self._index_edge(ESEdge.from_edge(edge, **metadata))

    def _remove_edge(self, edge: Edge) -> None:
        soft_delete_edge(edge.source.id, edge.target.id, sync=self._sync)

    def _remove_node(self, node: Identifier) -> None:
        remove_node(node, sync=self._sync)

    # -- get_canonical (override to remove @lru_cache) ---

    def get_canonical(self, entity_id: StrIdent) -> str:
        node = Identifier.get(entity_id)
        best = max(self.connected(node))
        if best.canonical:
            return best.id
        return node.id

    # -- suggest / decide (override to add metadata) ---

    def suggest(
        self,
        left_id: StrIdent,
        right_id: StrIdent,
        score: float,
        user: str = SYSTEM_USER,
        source_collection_id: int | None = None,
        target_collection_id: int | None = None,
        method: str | None = None,
        schema: str | None = None,
        text: list[str] | None = None,
        countries: list[str] | None = None,
    ) -> Identifier:
        """Extended suggest with metadata fields.

        Won't overwrite existing judgements - only creates new
        NO_JUDGEMENT edges or updates scores on existing NO_JUDGEMENT edges.
        """
        # Align collection IDs with the edge's source/target ordering.
        # Identifier.pair determines which entity becomes edge.source;
        # the caller's left/right order may differ.
        key = Identifier.pair(left_id, right_id)
        _, pair_source = key
        left_is_source = Identifier.get(left_id) == pair_source
        src_cid = source_collection_id if left_is_source else target_collection_id
        tgt_cid = target_collection_id if left_is_source else source_collection_id

        metadata = {
            "source_collection_id": {src_cid} if src_cid else set(),
            "target_collection_id": {tgt_cid} if tgt_cid else set(),
            "method": method,
            "schema": schema,
            "text": text or [],
            "countries": countries or [],
        }
        edge = self.get_edge(left_id, right_id)
        if edge is not None:
            if edge.judgement == Judgement.NO_JUDGEMENT:
                edge_ = ESEdge.from_edge(edge, **metadata)
                edge_.score = score
                self._index_edge(edge_)
            return edge.target

        self._metadata[key] = metadata

        return self.decide(
            left_id,
            right_id,
            Judgement.NO_JUDGEMENT,
            score=score,
            user=user,
            source_collection_id=source_collection_id,
            target_collection_id=target_collection_id,
        )

    def _update_collection_metadata(
        self,
        left_id: StrIdent,
        right_id: StrIdent,
        source_collection_id: int | None = None,
        target_collection_id: int | None = None,
    ) -> None:
        """Track collection_ids for entities and build edge metadata."""
        if source_collection_id is not None:
            self._entity_collections[str(left_id)].add(source_collection_id)
        if target_collection_id is not None:
            self._entity_collections[str(right_id)].add(target_collection_id)

        key = Identifier.pair(left_id, right_id)
        metadata = self._metadata.get(key, {})
        left_colls = self._entity_collections[str(left_id)]
        right_colls = self._entity_collections[str(right_id)]
        _, pair_source = key
        if left_colls:
            left_ident = Identifier.get(left_id)
            if left_ident == pair_source:
                metadata["source_collection_id"] = left_colls
            else:
                metadata["target_collection_id"] = left_colls
        if right_colls:
            right_ident = Identifier.get(right_id)
            if right_ident == pair_source:
                metadata["source_collection_id"] = right_colls
            else:
                metadata["target_collection_id"] = right_colls
        if metadata:
            self._metadata[key] = metadata

    def decide(
        self,
        left_id: StrIdent,
        right_id: StrIdent,
        judgement: Judgement,
        user: str = SYSTEM_USER,
        score: float | None = None,
        source_collection_id: int | None = None,
        target_collection_id: int | None = None,
    ) -> Identifier:
        """Make a decision, with optional collection metadata.

        For POSITIVE judgements, the parent creates NK-* canonical IDs and
        makes recursive calls to decide(entity, NK-*). We propagate
        collection_id metadata via _entity_collections so the entity side
        of entity->NK-* edges gets the correct collection_id.
        """
        self._update_collection_metadata(
            left_id, right_id, source_collection_id, target_collection_id
        )

        edge = self.get_edge(left_id, right_id)
        if edge is None:
            edge = Edge(left_id, right_id, judgement=judgement)

        if judgement == Judgement.POSITIVE:
            connected = set(self.connected(edge.target))
            connected.update(self.connected(edge.source))
            target = max(connected)
            if not target.canonical:
                canonical = Identifier.make()
                # Register NK-* with all collection_ids from the cluster
                for node in connected:
                    self._entity_collections[str(canonical)].update(
                        self._entity_collections[node.id]
                    )
                self._remove_edge(edge)
                self.decide(edge.source, canonical, judgement=judgement, user=user)
                self.decide(edge.target, canonical, judgement=judgement, user=user)
                return canonical

        edge.judgement = judgement
        edge.created_at = _now()
        edge.user = user or SYSTEM_USER
        edge.score = score or edge.score
        self._register(edge)
        if judgement != Judgement.NO_JUDGEMENT:
            self._invalidate()
        return edge.target

    # -- query methods (ES-backed) ---

    def get_judgements(self, limit: int | None = None) -> Generator[Edge, None, None]:
        """Get most recently updated edges other than NO_JUDGEMENT."""
        filters = [exclude_no_judgement()]
        sort = [{"created_at": "desc"}]
        docs = query_edges(filters, sort=sort, size=limit or 1000)
        for d in docs:
            yield Edge.from_dict(d)

    def _get_suggested(self) -> list[Edge]:
        """Get all NO_JUDGEMENT edges in descending order of score."""
        docs = query_edges(
            [{"term": {"judgement": "no_judgement"}}],
            sort=[{"score": "desc"}],
            size=1000,
        )
        return [Edge.from_dict(d) for d in docs]

    _DEFAULT_CLEANUP_AFTER = timedelta(days=6 * 30)

    def prune(
        self,
        cleanup_after: timedelta = _DEFAULT_CLEANUP_AFTER,
        user: Optional[str] = None,
    ) -> None:
        """Remove suggested (i.e. NO_JUDGEMENT) edges."""
        prune_edges(user=user, sync=self._sync)

    # -- canonicals (override: parent iterates self.nodes.keys()) ---

    def canonicals(self) -> Generator[Identifier, None, None]:
        """Return all the canonical cluster identifiers."""
        for node in self.nodes.keys():
            if not node.canonical:
                continue
            canonical = self.get_canonical(node)
            if canonical == node.id:
                yield node

    # -- get_linker (override: parent uses SQL) ---

    def get_linker(self) -> Linker[SE]:
        """Build a Linker from POSITIVE edges in ES."""
        entities: dict[Identifier, Set[Identifier]] = {}
        filters = [{"term": {"judgement": "positive"}}]
        if self._auth:
            filters.extend(auth_filters(self._auth))
        for es_edge in scan_edges(filters):
            source = Identifier.get(str(es_edge.source))
            target = Identifier.get(str(es_edge.target))
            cluster = entities.get(source)
            if cluster is None:
                cluster = set([source])
            other = entities.get(target)
            if other is None:
                other = set([target])
            cluster.update(other)
            for node in cluster:
                entities[node] = cluster
        return Linker(entities)

    # -- dump / load ---

    def dump(self, uri: Uri):
        """Dump non-NO_JUDGEMENT edges to file. Other than original NK Resolver
        we don't include soft-delete here."""
        smart_write_models(uri, scan_edges([exclude_no_judgement()]))

    def load(self, uri: Uri):
        bulk_index_edges(smart_stream_json_models(uri, ESEdge), sync=self._sync)

    def save(self) -> None:
        pass

    def __repr__(self) -> str:
        return "<ElasticsearchResolver(stateless)>"


def get_resolver(
    auth: SearchAuth | None = None, sync: bool = False
) -> ElasticsearchResolver:
    return ElasticsearchResolver(auth, sync=sync)
