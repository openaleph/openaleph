import logging
from typing import Any, Iterator

from banal import ensure_list
from followthemoney import EntityProxy
from openaleph_search import EntitiesQuery, Query, SearchQueryParser
from openaleph_search.core import get_es
from openaleph_search.index.entities import PROXY_INCLUDES
from openaleph_search.index.indexes import entities_read_index
from openaleph_search.index.mapping import Field
from openaleph_search.index.util import unpack_result
from openaleph_search.query.queries import EXCLUDE_DEHYDRATE, expand_include_fields

from aleph.index.collections import collections_index
from aleph.index.notifications import notifications_index
from aleph.index.xref import XREF_SOURCE, xref_index
from aleph.logic.notifications import get_role_channels
from aleph.logic.xref import SCORE_CUTOFF

log = logging.getLogger(__name__)


class CollectionsQuery(Query):
    TEXT_FIELDS = ["label^3", "text"]
    SORT_DEFAULT = ["_score", {"label.kw": "asc"}]
    SKIP_FILTERS = ["writeable"]
    PREFIX_FIELD = "label"
    SOURCE = {"excludes": ["text"]}

    def get_filters(self, **kwargs):
        filters = super(CollectionsQuery, self).get_filters(**kwargs)
        if self.parser.getbool("filter:writeable"):
            ids = self.parser.authz.collections(self.parser.authz.WRITE)
            filters.append({"ids": {"values": ids}})
        return filters

    def get_text_query(self):
        query = super().get_text_query()

        # By default, queries use the Elasticsearch `query_string` query which
        # considers only exact matches. Users expect the collection search to
        # match variations of the same word by default (e.g. Russia/Russian,
        # owner/owners, leaks/leaked), without using explicit advanced query
        # syntax to enable fuzzy matching.
        # As the `query_string` query does not support enabling fuzzy matching
        # by default, we add a second subquery to handle this. This allows users
        # to still use the advanced query syntax in cases that aren’t covered by
        # the default fuzziness (e.g.  prefixes/wildcard searches).
        if self.parser.text:
            query.append(
                {
                    "multi_match": {
                        "query": self.parser.text,
                        "fields": ensure_list(self.TEXT_FIELDS),
                        "operator": "AND",
                        "fuzziness": "AUTO:3,4",
                    }
                }
            )

        return query

    def get_index(self):
        return collections_index()


class NotificationsQuery(Query):
    AUTHZ_FIELD = None
    TEXT_FIELDS = ["text"]
    SORT_DEFAULT = [{"created_at": {"order": "desc"}}]

    def get_sort(self):
        return self.SORT_DEFAULT

    def get_text_query(self):
        return [{"match_all": {}}]

    def get_filters(self, **kwargs):
        channels = get_role_channels(self.parser.auth.role)
        filters = super(NotificationsQuery, self).get_filters(**kwargs)
        filters.append({"terms": {"channels": channels}})
        return filters

    def get_negative_filters(self):
        return [{"term": {"actor_id": self.parser.auth.role}}]

    def get_index(self):
        return notifications_index()


class EntitySetItemsQuery(EntitiesQuery):
    SKIP_FILTERS = []

    def __init__(self, *args, **kwargs):
        self.entityset = kwargs.pop("entityset")
        super(EntitySetItemsQuery, self).__init__(*args, **kwargs)

    def get_filters(self, **kwargs):
        filters = super(EntitySetItemsQuery, self).get_filters(**kwargs)
        filters.append({"ids": {"values": self.entityset.entities}})
        return filters

    def get_index(self):
        return entities_read_index()


class XrefQuery(Query):
    TEXT_FIELDS = ["text"]
    SORT_DEFAULT = [{"score": "desc"}]
    SORT_FIELDS = {
        "random": "random",
        "doubt": "doubt",
        "score": "_score",
    }
    AUTHZ_FIELD = "match_collection_id"
    SCORE_CUTOFF = SCORE_CUTOFF
    SOURCE = XREF_SOURCE

    def __init__(self, parser, collection_id=None):
        self.collection_id = collection_id
        parser.highlight = False
        super(XrefQuery, self).__init__(parser)

    def get_sort(self):
        if not len(self.parser.sorts):
            return self.SORT_DEFAULT
        return super().get_sort()

    def get_filters(self, **kwargs):
        filters = super(XrefQuery, self).get_filters(**kwargs)
        filters.append({"term": {"collection_id": self.collection_id}})
        sorts = [f for (f, _) in self.parser.sorts]
        if "random" not in sorts and "doubt" not in sorts:
            filters.append({"range": {"score": {"gt": self.SCORE_CUTOFF}}})
        return filters

    def get_index(self):
        return xref_index()


def _entity_sort_date(entity: dict[str, Any]) -> str:
    """Sort key for chronological ordering of thread entities."""
    props = entity.get("properties", {})
    for field in ("date", "createdAt", "authoredAt"):
        vals = props.get(field, [])
        if vals:
            return vals[0]
    return entity.get("updated_at", entity.get("created_at", ""))


class MessageThreadQuery:
    """Full-tree walker for threaded messages (schema: Email or Message).

    Given any entity in a thread, reconstructs the complete thread tree:
    walks up to the root, then down from the root to collect all branches.
    Results are sorted by date ascending and include the source entity.

    Threading cannot be expressed as a single Elasticsearch query: the
    frontier at hop N is only known once hop N-1 returns. This walker does
    one ES search per level, unioning the two parallel link paths per hop:

      1. entity-ref path:  properties.inReplyTo{Schema} -> entity id
      2. message-id path:  properties.inReplyTo -> other entity's messageId

    Bounded by MAX_DEPTH and MAX_RESULTS; tracks seen ids/messageIds to
    avoid cycles. Every hop is hard-filtered to a single collection_id, so
    callers must verify read access on that collection up front."""

    DIRECTION_PREVIOUS = "previous"
    DIRECTION_FOLLOWING = "following"

    SCHEMATA = ("Email", "Message")

    # Hard backend caps — callers can request a lower limit via the parser
    # but cannot exceed these.
    MAX_DEPTH = 25
    MAX_RESULTS = 200
    PAGE_SIZE = 250

    def __init__(
        self,
        parser: SearchQueryParser,
        entity: EntityProxy,
        collection_id: int,
    ) -> None:
        schema = entity.schema.name
        if schema not in self.SCHEMATA:
            raise ValueError(f"Message threading not supported for schema {schema!r}")
        if entity.id is None:
            raise ValueError("Entity has no ID")
        self.parser = parser
        self.entity = entity
        self.collection_id = collection_id
        self.schema: str = schema
        # Source shaping comes from the shared SearchQueryParser knobs.
        self.dehydrate: bool = parser.dehydrate
        self.include_fields: set[str] = set(parser.include_fields)
        # Cap the caller-provided limit with the hard backend max.
        self.limit: int = min(parser.limit, self.MAX_RESULTS)
        # e.g. "properties.inReplyToEmail" / "properties.inReplyToMessage"
        self.reply_entity_field = f"{Field.PROPERTIES}.inReplyTo{self.schema}"
        self.in_reply_to_field = f"{Field.PROPERTIES}.inReplyTo"
        self.message_id_field = f"{Field.PROPERTIES}.messageId"
        # Walk-state: ids/messageIds already yielded or already queued into a
        # frontier, so we never search for or yield them twice.
        self.seen_ids: set[str] = {entity.id}
        self.seen_mids: set[str] = set(entity.get("messageId"))
        self.produced: int = 0
        # Set by walk() when the thread extends past what we returned —
        # either ES reported more hits at a level than we fetched, or the
        # one-hop tail probe found residual frontier content. Consumed by
        # the caller to set `total_type = "gte"` on the response envelope.
        self.truncated: bool = False
        # Internal direction — set per walk phase, not by the caller.
        self._direction: str = self.DIRECTION_PREVIOUS

    def _source_spec(self) -> dict[str, list[str]]:
        """_source includes for every hop.

        When `dehydrate` is set we drop the full `properties` payload
        (bodyHtml/bodyText/indexText/etc., which thread list views don't
        need) but keep the threading-critical property fields — without
        them the BFS can't compute the next frontier. Caller-supplied
        include_fields (group names or property paths) are folded in."""
        if not self.dehydrate:
            return {"includes": list(PROXY_INCLUDES)}
        includes = [k for k in PROXY_INCLUDES if k not in EXCLUDE_DEHYDRATE]
        # Threading pointers the walk itself needs on every hit.
        includes.append(self.message_id_field)
        includes.append(self.in_reply_to_field)
        includes.append(self.reply_entity_field)
        if self.include_fields:
            includes.extend(expand_include_fields(self.include_fields))
        return {"includes": includes}

    def _scope_filters(self) -> list[dict[str, Any]]:
        """Scope every hop to the single collection and schema. Threads
        don't cross datasets; callers are expected to verify read access on
        this collection before constructing the query."""
        return [
            {"term": {Field.SCHEMA: self.schema}},
            {"term": {"collection_id": self.collection_id}},
        ]

    def _frontier_query(
        self, ids: set[str], message_ids: set[str]
    ) -> dict[str, Any] | None:
        """Union query matching the next hop in the current direction."""
        should: list[dict[str, Any]] = []
        if self._direction == self.DIRECTION_FOLLOWING:
            # find entities that reply to anyone in the frontier
            if ids:
                should.append({"terms": {self.reply_entity_field: list(ids)}})
            if message_ids:
                should.append({"terms": {self.in_reply_to_field: list(message_ids)}})
        else:
            # find entities referenced (by id) or whose messageId is referenced
            if ids:
                should.append({"ids": {"values": list(ids)}})
            if message_ids:
                should.append({"terms": {self.message_id_field: list(message_ids)}})
        if not should:
            return None
        return {
            "bool": {
                "filter": self._scope_filters(),
                "should": should,
                "minimum_should_match": 1,
            }
        }

    def _fresh_ids(self, ids: Any) -> set[str]:
        """Filter `ids` down to ones not yet seen, and mark them seen."""
        fresh = {i for i in (ids or []) if i and i not in self.seen_ids}
        self.seen_ids |= fresh
        return fresh

    def _fresh_mids(self, mids: Any) -> set[str]:
        """Filter `mids` down to ones not yet seen, and mark them seen."""
        fresh = {m for m in (mids or []) if m and m not in self.seen_mids}
        self.seen_mids |= fresh
        return fresh

    def _initial_frontier(self) -> tuple[set[str], set[str]]:
        """Starting (ids, messageIds) derived from the source entity."""
        if self._direction == self.DIRECTION_FOLLOWING:
            # children point back at the root entity's id or messageId; both
            # are already in `seen_*` (added in __init__), so re-pass them
            # directly rather than through _fresh_*.
            return {self.entity.id}, set(self.entity.get("messageId"))
        parent_prop = f"inReplyTo{self.schema}"
        return (
            self._fresh_ids(self.entity.get(parent_prop)),
            self._fresh_mids(self.entity.get("inReplyTo")),
        )

    def _next_frontier_from_hit(
        self, entity: dict[str, Any]
    ) -> tuple[set[str], set[str]]:
        """Frontier additions contributed by a newly yielded hit.

        Updates self.seen_ids / self.seen_mids as a side-effect."""
        props = entity.get("properties") or {}
        if self._direction == self.DIRECTION_FOLLOWING:
            # grandchildren will reference this hit's id or messageId
            return (
                self._fresh_ids([entity["id"]]),
                self._fresh_mids(props.get("messageId")),
            )
        # previous: one hop further back
        return (
            self._fresh_ids(props.get(f"inReplyTo{self.schema}")),
            self._fresh_mids(props.get("inReplyTo")),
        )

    def _probe_more(self, ids: set[str], message_ids: set[str]) -> None:
        """One extra size=1 search to decide truncation precisely when the
        main walk terminated on a non-empty residual frontier."""
        query = self._frontier_query(ids, message_ids)
        if query is None:
            return
        result = get_es().search(
            index=entities_read_index(self.schema),
            body={"query": query, "size": 1, "_source": False},
        )
        if result.get("hits", {}).get("hits"):
            self.truncated = True

    def _process_hits(
        self, hits: list[dict], collected: list[dict[str, Any]]
    ) -> tuple[set[str], set[str]]:
        """Process ES hits from one BFS level: deduplicate, collect entities,
        and compute the next frontier.

        Returns the (next_ids, next_mids) frontier for the following hop."""
        next_ids: set[str] = set()
        next_mids: set[str] = set()
        for hit in hits:
            entity = unpack_result(hit)
            if entity is None:
                continue
            hit_id = entity["id"]
            if hit_id in self.seen_ids:
                # For following direction, seen_ids accumulates from
                # _next_frontier_from_hit, so duplicates are skipped.
                if self._direction == self.DIRECTION_FOLLOWING:
                    continue
            self.seen_ids.add(hit_id)
            collected.append(entity)
            self.produced += 1
            add_ids, add_mids = self._next_frontier_from_hit(entity)
            next_ids |= add_ids
            next_mids |= add_mids
            if self.produced >= self.limit:
                break
        return next_ids, next_mids

    def _walk_bfs(
        self, start_ids: set[str], start_mids: set[str]
    ) -> list[dict[str, Any]]:
        """BFS walk in the current ``_direction`` from an explicit frontier.

        Collects and returns entities. Updates ``seen_ids``, ``seen_mids``,
        ``produced``, and ``truncated`` as side-effects."""
        es = get_es()
        index = entities_read_index(self.schema)
        ids, message_ids = start_ids, start_mids
        collected: list[dict[str, Any]] = []
        stopped_early = False

        for _ in range(self.MAX_DEPTH):
            if not ids and not message_ids:
                break
            remaining = self.limit - self.produced
            if remaining <= 0:
                stopped_early = True
                break
            query = self._frontier_query(ids, message_ids)
            if query is None:
                break
            body = {
                "query": query,
                "size": min(self.PAGE_SIZE, remaining),
                "_source": self._source_spec(),
                "track_total_hits": True,
            }
            result = es.search(index=index, body=body)
            hits_obj = result.get("hits", {})
            hits = hits_obj.get("hits", [])
            total_level = hits_obj.get("total", {}).get("value", 0)
            if not hits:
                break
            if total_level > len(hits):
                # We only asked for `remaining` hits but this level has
                # more matches — definitely more to return.
                self.truncated = True

            ids, message_ids = self._process_hits(hits, collected)
        else:
            # Ran out of depth without naturally emptying the frontier.
            stopped_early = True

        # Tail probe: only when we stopped early on a non-empty frontier
        # and don't already know about same-level overflow.
        if stopped_early and not self.truncated and (ids or message_ids):
            self._probe_more(ids, message_ids)

        return collected

    def walk(self) -> Iterator[dict[str, Any]]:
        """Reconstruct the full thread tree, sorted by date ascending.

        Phase 1: walk PREVIOUS from the source entity up to the root.
        Phase 2: walk FOLLOWING from the ROOT to get all descendants
                 (including sibling branches the source isn't part of).
        Phase 3: insert the source entity itself.
        Phase 4: sort everything chronologically."""
        all_entities: list[dict[str, Any]] = []

        # Phase 1: walk up to root
        self._direction = self.DIRECTION_PREVIOUS
        start_ids, start_mids = self._initial_frontier()
        ancestors = self._walk_bfs(start_ids, start_mids)
        all_entities.extend(ancestors)

        # Phase 2: walk down from the root (last ancestor = furthest from
        # source in BFS order). If no ancestors, the source IS the root.
        if ancestors:
            root = ancestors[-1]
            root_id = root["id"]
            root_mids = set((root.get("properties") or {}).get("messageId", []))
        else:
            root_id = self.entity.id
            root_mids = set(self.entity.get("messageId"))

        self._direction = self.DIRECTION_FOLLOWING
        # seen_ids already contains source + all ancestors — descendants
        # that overlap won't be re-collected.
        descendants = self._walk_bfs({root_id}, root_mids)
        all_entities.extend(descendants)

        # Phase 3: include the source entity
        all_entities.append(self.entity.to_full_dict())

        # Phase 4: sort by date ascending
        all_entities.sort(key=_entity_sort_date)

        yield from all_entities

    def to_list(self) -> list[dict[str, Any]]:
        return list(self.walk())
