from typing import Any, Generator, Iterable

from banal import ensure_list
from followthemoney.exc import InvalidData
from followthemoney.helpers import remove_checksums
from followthemoney.proxy import EntityProxy
from followthemoney.types import registry
from openaleph_search.index import entities as entities_index

from aleph.logic.aggregator import get_aggregator
from aleph.model.collection import Collection
from aleph.util import make_entity_proxy


def _massage_entities(
    collection: Collection,
    entities: Iterable[dict[str, Any]],
    safe: bool = False,
    role_id: int | None = None,
    mutable: bool = True,
    clean: bool = True,
) -> Generator[EntityProxy, None, None]:
    """Prepare entities for bulk write"""
    for data in entities:
        entity = make_entity_proxy(data, cleaned=(not clean))
        if entity.id is None:
            raise InvalidData("No ID for entity", errors=entity.to_dict())
        entity = collection.ns.apply(entity)
        if safe:
            entity = remove_checksums(entity)
        entity.context = {"role_id": role_id, "mutable": mutable}
        for field, func in (("created_at", min), ("updated_at", max)):
            ts = func(ensure_list(data.get(field)), default=None)
            dt = registry.date.to_datetime(ts)
            if dt is not None:
                entity.context[field] = dt.isoformat()
        yield entity


def bulk_write(
    collection: Collection,
    entities: Iterable[dict[str, Any]],
    safe: bool = False,
    role_id: int | None = None,
    mutable: bool = True,
    clean: bool = True,
) -> Generator[EntityProxy, None, None]:
    """Write a set of entities - given as dicts - to the followthemoney db store
    (internal, default) or directly to the index (external collections)."""
    # This is called mainly by the /api/2/collections/X/_bulk API.

    _entities = _massage_entities(collection, entities, safe, role_id, mutable, clean)

    if not collection.external:  # default path, write to DB
        aggregator = get_aggregator(collection)
        writer = aggregator.bulk()
        for entity in _entities:
            writer.put(entity, origin="bulk")
            yield entity
        writer.flush()
    else:  # "external" collection, straight to the index without DB
        entities_index.index_bulk(
            collection.name,
            _entities,
            collection_id=collection.id,
        )
