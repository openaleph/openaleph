# Bulk object resolver.
# The purpose of this module is to quickly load objects of different
# classes/types from the backend. It's typically used by the API serialiser to
# ensure that nested objects are loaded only once.
#
import logging
from collections import defaultdict

from banal import ensure_list
from normality import stringify
from openaleph_search.index.entities import entities_by_ids

from aleph.core import cache
from aleph.index.collections import get_collection
from aleph.logic.alerts import get_alert
from aleph.logic.entitysets import get_entityset
from aleph.logic.export import get_export
from aleph.logic.roles import get_role
from aleph.model import Alert, Collection, Entity, EntitySet, Export, Role

log = logging.getLogger(__name__)
LOADERS = {
    Role: get_role,
    Collection: get_collection,
    Alert: get_alert,
    EntitySet: get_entityset,
    Export: get_export,
}


def cached_entities_by_ids(ids, schemata=None):
    """Iterate over unpacked entities based on a search for the given
    entity IDs."""
    ids = ensure_list(ids)
    if not len(ids):
        return
    entities = {}
    keys = [cache.object_key(Entity, i) for i in ids]
    for _, entity in cache.get_many_complex(keys):
        if entity is not None:
            entities[entity.get("id")] = entity

    missing = [i for i in ids if entities.get(id) is None]
    for entity in entities_by_ids(missing, schemata):
        entities[entity["id"]] = entity
        key = cache.object_key(Entity, entity["id"])
        cache.set_complex(key, entity, expires=60 * 60 * 2)

    for i in ids:
        entity = entities.get(i)
        if entity is not None:
            yield entity


def _instrument_stub(stub):
    if not hasattr(stub, "_rx_queue"):
        stub._rx_queue = set()
    if not hasattr(stub, "_rx_cache"):
        stub._rx_cache = {}


def queue(stub, clazz, key, schema=None):
    """Notify the resolver associated with `stub` that the given object
    needs to be retrieved. Multiple calls with the same object signature
    will be merged."""
    _instrument_stub(stub)
    key = stringify(key)
    if key is None:
        return
    stub._rx_queue.add((clazz, key, schema))


def resolve(stub):
    _instrument_stub(stub)
    cache_keys = {}
    schemata = {}
    for clazz, key, schema in stub._rx_queue:
        if (clazz, key) in stub._rx_cache:
            continue

        cid = cache.object_key(clazz, key)
        cache_keys[cid] = (clazz, key)
        schemata[cid] = schema

    keys = list(cache_keys.keys())
    queries = defaultdict(list)
    for cid, value in cache.get_many_complex(keys):
        clazz, key = cache_keys.get(cid)
        if value is None:
            # log.info("MISS [%s]: %s", clazz.__name__, key)
            if clazz == Entity:
                queries[schemata.get(cid)].append(key)
            loader = LOADERS.get(clazz)
            if loader is not None:
                value = loader(key)
        stub._rx_cache[(clazz, key)] = value

    for schema, ids in queries.items():
        for entity in cached_entities_by_ids(ids, schemata=schema):
            stub._rx_cache[(Entity, entity.get("id"))] = entity


def get(stub, clazz, key):
    """Retrieve an object that has been loaded (or None)."""
    _instrument_stub(stub)
    key = stringify(key)
    if key is None:
        return
    return stub._rx_cache.get((clazz, key))
