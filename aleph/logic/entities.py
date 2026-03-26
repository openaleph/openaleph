import logging
from typing import Generator

from banal import ensure_dict, is_mapping
from flask_babel import gettext
from followthemoney import EntityProxy, model
from followthemoney.exc import InvalidData
from followthemoney.namespace import Namespace
from followthemoney.types import registry
from followthemoney.util import make_entity_id
from openaleph_procrastinate.defer import tasks
from openaleph_search.index import entities as index

from aleph.core import cache, db
from aleph.index import xref as xref_index
from aleph.logic.aggregator import get_aggregator
from aleph.logic.collections import MODEL_ORIGIN, refresh_collection
from aleph.logic.notifications import flush_notifications
from aleph.logic.util import latin_alt
from aleph.model import Bookmark, Document, Entity, EntitySetItem, Mapping
from aleph.procrastinate.queues import (
    queue_analyze,
    queue_prune_entity,
    queue_update_entity,
)
from aleph.util import make_entity_proxy

log = logging.getLogger(__name__)


def _deduce_page_ids(
    collection_id: int, foreign_id: str, e: EntityProxy
) -> Generator[str, None, None]:
    """This is an endless generator of child "Page" entity IDs. This doesn't
    mean they exist. Consumers are responsible to stop at one point."""
    if e.schema.name == "Pages":
        ns = Namespace(foreign_id)
        i = 1
        while True:
            id_ = make_entity_id(e.id, i, key_prefix=f"collection_{collection_id}")
            yield ns.sign(id_)
            i += 1


def upsert_entity(data, collection, authz=None, sync=False, sign=False, job_id=None):
    """Create or update an entity in the database. This has a side effect  of migrating
    entities created via the _bulk API or a mapper to a database entity in the event
    that it gets edited by the user.
    """
    from aleph.logic.profiles import profile_fragments

    entity = None
    entity_id = collection.ns.sign(data.get("id"))
    if entity_id is not None:
        entity = Entity.by_id(entity_id, collection=collection)
    if entity is None:
        role_id = authz.id if authz is not None else None
        entity = Entity.create(data, collection, sign=sign, role_id=role_id)
    else:
        entity.update(data, collection, sign=sign)
    collection.touch()

    proxy = entity.to_proxy()
    aggregator = get_aggregator(collection)
    aggregator.delete(entity_id=proxy.id)
    aggregator.put(proxy, origin=MODEL_ORIGIN)
    profile_fragments(collection, aggregator, entity_id=proxy.id)

    index.index_proxy(collection.name, proxy, sync=sync, collection_id=collection.id)
    refresh_entity(collection, proxy.id)
    queue_update_entity(collection, entity_id=proxy.id, batch=job_id)
    return entity.id


def update_entity(collection, entity_id=None, job_id=None):
    """Worker post-processing for entity changes. This action collects operations
    that should be done after each change to an entity but are too slow to run
    inside the request cycle.

    Update xref and aggregator, trigger NER and re-index."""
    from aleph.logic.profiles import profile_fragments
    from aleph.logic.xref import xref_entity

    log.info("[%s] Update entity: %s", collection, entity_id)
    entity = index.get_entity(entity_id)
    proxy = make_entity_proxy(entity)
    if collection.casefile:
        xref_entity(collection, proxy)

    aggregator = get_aggregator(collection, origin=MODEL_ORIGIN)
    profile_fragments(collection, aggregator, entity_id=entity_id)
    inline_names(aggregator, proxy)
    queue_analyze(collection, [proxy], batch=job_id)


def index_entity(collection, entity_id):
    """(Re-)index a given entity by it's ID from the aggregator"""
    aggregator = get_aggregator(collection)
    proxy = aggregator.get(entity_id)
    if proxy is None:
        log.warning(f"[{collection.name}] No Entity found for ID `{entity_id}`.")
    else:
        index.index_proxy(
            collection.name, proxy, sync=True, collection_id=collection.id
        )
        log.info(f"[{collection.name}] Indexed Entity `{entity_id}`.")


def inline_names(aggregator, proxy):
    """Attempt to solve a weird UI problem. Imagine, for example, we
    are showing a list of payments between a sender and a beneficiary to
    a user. They may now conduct a search for a term present in the sender
    or recipient name, but there will be no result, because the name is
    only indexed with the parties, but not in the payment. This is part of
    a partial work-around to that.

    This is really bad in theory, but really useful in practice. Shoot me.
    """
    prop = proxy.schema.get("namesMentioned")
    if prop is None:
        return
    entity_ids = proxy.get_type_values(registry.entity)
    names = set()
    for related in index.entities_by_ids(entity_ids):
        related = make_entity_proxy(related)
        names.update(related.get_type_values(registry.name))

    if len(names) > 0:
        name_proxy = model.make_entity(proxy.schema)
        name_proxy.id = proxy.id
        name_proxy.add(prop, names)
        aggregator.put(name_proxy, fragment="names")


def validate_entity(data):
    """Check that there is a valid schema and all FtM conform to it."""
    schema = model.get(data.get("schema"))
    if schema is None:
        raise InvalidData(gettext("No schema on entity"))
    # This isn't strictly required because the proxy will contain
    # only those values that can be inserted for each property,
    # making it valid -- all this does, therefore, is to raise an
    # exception that notifies the user.
    # FIXME the following seems a bit hacky/unnecessary, but `validate_entity` is
    # only called from the api if `?validate=true` only, which defaults to
    # `false`, and who knows how long we will have this user edits in this
    # stack anyways ;)
    # followthemoney 4.6.0: We need to turn entity references (nested payload)
    # to their IDs first:
    properties = {}
    _data = {k: v for k, v in data.items()}
    for prop, values in _data.pop("properties", {}).items():
        properties[prop] = []
        for value in values:
            if is_mapping(value):
                schema.validate(value)
                id_ = value.get("id")
                if id_:
                    properties[prop].append(id_)
            else:
                properties[prop].append(value)
    _data["properties"] = properties
    # FTM 4.6.0 only validates properties present in the dict, so missing
    # required properties would slip through. Check explicitly:
    for req in schema.required:
        if not properties.get(req):
            raise InvalidData(
                gettext("Entity validation failed"),
                errors={"properties": {req: gettext("Required")}},
            )
    schema.validate(_data)


def should_transcribe(proxy: EntityProxy) -> bool:
    """Check if an entity is eligible for transcription."""
    if not tasks.transcribe.defer:
        return False
    return proxy.schema.is_a("Video") or proxy.schema.is_a("Audio")


def should_translate(collection_id: int, foreign_id: str, proxy: EntityProxy) -> bool:
    """Check if an entity is eligible for translation. Should be used on 'detail
    views' and not in lists for many entities because of the costly call for
    Pages schemata."""
    if not tasks.translate.defer:
        return False
    if proxy.has(
        "translatedText", quiet=True
    ):  # already translated, don't allow user-side retrigger
        return False
    # this is hacky but the most efficient way to do this. For "Pages" schemata,
    # we deduce the first few child Page ids, try to get them from the index and
    # look if they have translated text. We test the first 3 possible pages.
    if proxy.schema.name == "Pages":
        for ix, page_id in enumerate(
            _deduce_page_ids(collection_id, foreign_id, proxy)
        ):
            if ix > 3:
                break
            page_entity = index.get_entity(page_id)
            if page_entity is None:
                continue
            if "translatedText" in page_entity.get("properties", {}):
                return False
    if proxy.schema.is_a("Document"):
        return True
    return False


def check_write_entity(entity, authz):
    """Implement the cross-effects of mutable flag and the authz
    system for serialisers and API."""
    if authz.is_admin:
        return True
    if not entity.get("mutable"):
        return False
    collection_id = ensure_dict(entity.get("collection")).get("id")
    collection_id = entity.get("collection_id", collection_id)
    return authz.can(collection_id, authz.WRITE)


def transliterate_values(entity):
    """Generate transliterated strings for the names and addresses
    linked to the given entity proxy."""
    transliterated = {entity.caption: latin_alt(entity.caption)}
    for type_ in (registry.name, registry.address):
        for value in entity.get_type_values(type_):
            transliterated[value] = latin_alt(value)
    return transliterated


def refresh_entity(collection, entity_id):
    cache.kv.delete(cache.object_key(Entity, entity_id))
    refresh_collection(collection.id)


def delete_entity(collection, entity, sync=False, job_id=None):
    """Delete entity from index and redis, queue full prune."""
    entity_id = collection.ns.sign(entity.get("id"))
    index.delete_entity(entity_id, sync=sync)
    refresh_entity(collection, entity_id)
    queue_prune_entity(collection, entity_id=entity_id, batch=job_id)


def prune_entity(collection, entity_id=None, job_id=None):
    """Prune handles the full deletion of an entity outside of the HTTP request
    cycle. This involves cleaning up adjacent entities like xref results, notifications
    and so on."""
    # This is recursive and will also delete any entities which
    # reference the given entity. Usually this is going to be child
    # documents, or directoships referencing a person. It's a pretty
    # dangerous operation, though.
    log.info("[%s] Prune entity: %s", collection, entity_id)
    for adjacent in index.iter_adjacent(collection.name, entity_id):
        log.warning("Recursive delete: %s", adjacent.get("id"))
        delete_entity(collection, adjacent, job_id=job_id)
    flush_notifications(entity_id, clazz=Entity)
    obj = Entity.by_id(entity_id, collection=collection)
    if obj is not None:
        obj.delete()
    doc = Document.by_id(entity_id, collection=collection)
    if doc is not None:
        doc.delete()
    EntitySetItem.delete_by_entity(entity_id)
    Bookmark.delete_by_entity(entity_id)
    Mapping.delete_by_table(entity_id)
    xref_index.delete_xref(collection, entity_id=entity_id)
    aggregator = get_aggregator(collection)
    aggregator.delete(entity_id=entity_id)
    refresh_entity(collection, entity_id)
    collection.touch()
    db.session.commit()
