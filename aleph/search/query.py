import logging

from banal import ensure_list
from openaleph_search import EntitiesQuery, Query
from openaleph_search.index.indexes import entities_read_index

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

    def get_filters(self, **kwargs):
        filters = super(XrefQuery, self).get_filters(**kwargs)
        filters.append({"term": {"collection_id": self.collection_id}})
        sorts = [f for (f, _) in self.parser.sorts]
        if "random" not in sorts and "doubt" not in sorts:
            filters.append({"range": {"score": {"gt": self.SCORE_CUTOFF}}})
        return filters

    def get_index(self):
        return xref_index()
