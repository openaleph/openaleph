"""Entity assembler – request-time enrichment of EntitySchema."""

import logging
import re

from banal import ensure_list
from followthemoney import EntityProxy, model
from followthemoney.types import registry

from aleph.api.assemblers.base import Assembler
from aleph.api.assemblers.collection import CollectionAssembler
from aleph.core import url_for
from aleph.logic.entities import (
    check_write_entity,
    should_transcribe,
    should_translate,
    transliterate_values,
)
from aleph.logic.util import entity_url
from aleph.logic.xref.canonical import get_canonical_cluster
from aleph.model import CollectionSchema, Document, EntitySchema, RoleSchema
from aleph.model.common import SDict
from aleph.procrastinate.queues import defer
from aleph.settings import SETTINGS

log = logging.getLogger(__name__)
TRACER_URI = SETTINGS.REDIS_URL
BASE64_ENCODED_PATTERN = re.compile(r"=\?{1}(.+)\?{1}([B|Q])\?{1}(.+)\?{1}=.*")


class EntityAssembler(Assembler):
    """Enrich an ``EntitySchema`` with links, resolved nested entities,
    collection, role, latinized values, and detail-view extras."""

    def prefetch(self, objs: list[EntitySchema]) -> None:
        coll_ids: set[str] = set()
        role_ids: set[str] = set()
        entity_ids: set[str] = set()

        for obj in objs:
            coll_ids.add(str(obj.collection_id))
            if obj.role_id:
                role_ids.add(obj.role_id)
            schema = model.get(obj.schema_)
            if schema is None:
                continue
            for name, values in obj.properties.items():
                prop = schema.get(name)
                if prop is not None and prop.type == registry.entity:
                    for v in ensure_list(values):
                        if isinstance(v, str):
                            entity_ids.add(v)

        if coll_ids:
            self.resolver.get_many(CollectionSchema, list(coll_ids))
        if role_ids:
            self.resolver.get_many(RoleSchema, list(role_ids))
        if entity_ids:
            self.resolver.get_many(EntitySchema, list(entity_ids))

    def assemble(self, obj: EntitySchema) -> EntitySchema | None:
        # Authz gate – nested entities may be resolved without authz
        if not self.authz.can(obj.collection_id, self.authz.READ):
            return None

        proxy = obj.to_proxy()
        obj.properties = self._resolve_properties(proxy)
        obj.links = self._build_links(obj, proxy)
        obj.latinized = transliterate_values(proxy)
        obj.writeable = check_write_entity(obj, self.authz)
        obj.shallow = not self.detail
        obj.collection = self._resolve_collection(obj.collection_id)
        obj.role = self.resolver.get(RoleSchema, obj.role_id) if obj.role_id else None

        if self.detail:
            self._enrich_detail(obj, proxy)

        return obj

    # --- Internal helpers ----------------------------------------------------

    def _resolve_properties(self, proxy: EntityProxy) -> SDict:
        """Resolve entity-typed property values to nested EntitySchema."""
        properties: SDict = {}
        for prop, value in proxy.itervalues():
            properties.setdefault(prop.name, [])
            if prop.type == registry.entity:
                nested = self.resolver.get(EntitySchema, value)
                if nested is not None:
                    nested.shallow = True
                    value = nested
            if value is not None:
                if type(value) is str and BASE64_ENCODED_PATTERN.search(value):
                    continue
                properties[prop.name].append(value)
        return properties

    def _build_links(self, obj: EntitySchema, proxy: EntityProxy) -> SDict:
        links: SDict = {
            "self": url_for("entities_api.view", entity_id=obj.id),
            "expand": url_for("entities_api.expand", entity_id=obj.id),
            "tags": url_for("entities_api.tags", entity_id=obj.id),
            "ui": entity_url(obj.id),
        }
        if self.detail and proxy.schema.is_a(Document.SCHEMA):
            self._add_document_links(links, proxy)
        return links

    def _add_document_links(self, links: SDict, proxy: EntityProxy) -> None:
        # Don't embed short-lived signed archive URLs into the payload,
        # as browsers cache it and the links go stale. Instead, link to
        # the resolve endpoint which checks permissions at request time
        # and redirects to a freshly signed archive URL.
        for link, prop in (
            ("file", "contentHash"),
            ("pdf", "pdfHash"),
            ("csv", "csvHash"),
        ):
            if proxy.first(prop, quiet=True):
                links[link] = url_for(
                    "archive_api.resolve",
                    _query=[("entity", proxy.id), ("prop", prop)],
                )

    def _resolve_collection(self, collection_id: int) -> CollectionSchema:
        coll = self.resolver.get_or_404(CollectionSchema, str(collection_id))
        coll_assembler = CollectionAssembler(self.resolver, self.authz)
        return coll_assembler.assemble(coll)

    def _enrich_detail(self, obj: EntitySchema, proxy: EntityProxy) -> None:
        """Add detail-view-only fields."""
        try:
            cluster = get_canonical_cluster(proxy.id, self.authz.search_auth)
            if cluster is not None:
                obj.canonical_id = cluster["id"]
        except Exception:
            pass

        if proxy.schema.is_a(Document.SCHEMA):
            if should_transcribe(proxy):
                obj.links["transcribe"] = url_for(
                    "entities_api.transcribe", entity_id=proxy.id
                )
            if obj.collection and should_translate(
                int(obj.collection.id), obj.collection.foreign_id, proxy
            ):
                obj.links["translate"] = url_for(
                    "entities_api.translate", entity_id=proxy.id
                )
            tracer = defer.tasks.translate.get_tracer(TRACER_URI)
            obj.processing_status = {"translate": tracer.is_processing(obj.id)}
