import logging

from followthemoney.graph import Graph as FtMGraph

from aleph.logic.resolver import cache
from aleph.model import EntitySchema

log = logging.getLogger(__name__)


class Graph(FtMGraph):
    """A subclass of `followthemoney.graph:Graph` that can resolve
    entities against the aleph search index and entity cache."""

    def resolve(self):
        entities = cache.get_many(EntitySchema, list(self.queued))
        for entity in entities:
            self.add(entity.to_proxy())
