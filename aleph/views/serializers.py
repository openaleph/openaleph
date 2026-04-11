import logging
import re
from collections import defaultdict

from banal import ensure_list
from flask import request
from flask_babel import gettext
from followthemoney import model
from followthemoney.helpers import entity_filename
from followthemoney.statement.util import get_prop_type
from followthemoney.types import registry
from pydantic import BaseModel
from rigour.mime.types import CSV, PDF
from servicelayer import env

from aleph.core import url_for
from aleph.logic.entities import (
    check_write_entity,
    should_transcribe,
    should_translate,
    transliterate_values,
)
from aleph.logic.resolver import cache
from aleph.logic.util import archive_url, collection_url, entity_url
from aleph.logic.xref.canonical import get_canonical_cluster
from aleph.model import (
    AlertSchema,
    Collection,
    CollectionSchema,
    Document,
    EntitySchema,
    EntitySetSchema,
    Events,
    ExportSchema,
    Role,
    RoleSchema,
)
from aleph.model.common import model_dump
from aleph.procrastinate.queues import defer
from aleph.util import make_entity_proxy
from aleph.views.util import clean_object, jsonify

log = logging.getLogger(__name__)

TRACER_URI = env.get("REDIS_URL")
BASE64_ENCODED_PATTERN = re.compile(r"=\?{1}(.+)\?{1}([B|Q])\?{1}(.+)\?{1}=.*")


class Serializer(object):
    def __init__(self, nested=False, detail_view=False):
        self.nested = nested
        self.detail_view = detail_view

    def collect(self, obj):
        pass

    def _serialize(self, obj):
        return obj

    def _serialize_common(self, obj):
        id_ = obj.pop("id", None)
        if id_ is not None:
            obj["id"] = str(id_)
        obj.pop("_index", None)
        obj["writeable"] = False
        obj["links"] = {}
        obj = self._serialize(obj)
        return clean_object(obj)

    def queue(self, schema_cls, key):
        """Collect a (schema_cls, key) pair for batch pre-fetching."""
        if self.nested or not key:
            return
        if not hasattr(request, "_resolver_queue"):
            request._resolver_queue = defaultdict(set)
        request._resolver_queue[schema_cls].add(str(key))

    def _resolve_queued(self):
        """Batch-fetch all queued items via the resolver. Called once
        before _serialize runs."""
        queue = getattr(request, "_resolver_queue", None)
        if not queue:
            return
        for schema_cls, keys in queue.items():
            cache.get_many(schema_cls, list(keys))
        request._resolver_queue = defaultdict(set)

    def resolve(self, schema_cls, key, serializer=None):
        """Look up a single object from the resolver cache and
        optionally serialize it. Returns a dict (for backwards
        compat with existing _serialize methods that work on dicts)."""
        if not key:
            return None
        obj = cache.get(schema_cls, str(key))
        if obj is None:
            return None
        data = model_dump(obj)
        if data is not None and serializer is not None:
            serializer = serializer(nested=True)
            data = serializer.serialize(data)
        return data

    def serialize(self, obj):
        obj = self._to_dict(obj)
        if obj is not None:
            self.collect(obj)
            self._resolve_queued()
            return self._serialize_common(obj)

    def serialize_many(self, objs):
        collected = []
        for obj in ensure_list(objs):
            obj = self._to_dict(obj)
            if obj is not None:
                self.collect(obj)
                collected.append(obj)
        self._resolve_queued()
        serialized = []
        for obj in collected:
            obj = self._serialize_common(obj)
            if obj is not None:
                serialized.append(obj)
        return serialized

    def _to_dict(self, obj):
        if isinstance(obj, BaseModel):
            return model_dump(obj)
        if hasattr(obj, "to_dict"):
            obj = obj.to_dict()
        if hasattr(obj, "_asdict"):
            obj = obj._asdict()
        return obj

    @classmethod
    def jsonify(cls, obj, detail_view=False, **kwargs):
        data = cls(detail_view=detail_view).serialize(obj)
        return jsonify(data, **kwargs)

    @classmethod
    def jsonify_result(cls, result, extra=None, **kwargs):
        data = result.to_dict(serializer=cls)
        if extra is not None:
            data.update(extra)
        # Sometimes part of the result might be missing because of some
        # inconsistency (eg: a failed re-indexing, stale xref docs). We try
        # to spot those inconsistencies.
        total = data.get("total", 0)
        limit = data.get("limit", 0)
        offset = data.get("offset", 0)
        # Significant aggregation queries set ES size=0 (no hits) but still
        # have parser limit > 0 and facets present, so we skip when facets
        # are returned.
        if total > 0 and not data.get("results") and not data.get("facets"):
            if not (limit == 0 or offset >= total):
                log.error(f"Expected more results in the response: {data}")
                data = {
                    "status": "error",
                    "message": gettext(
                        "We found %(total)d results, but could not load them due "
                        "to a technical problem. Please check back later and if "
                        "the problem persists contact an Aleph administrator",
                        total=total,
                    ),
                }
                return jsonify(data, status=500)
        return jsonify(data, **kwargs)


class RoleSerializer(Serializer):
    def _serialize(self, obj):
        obj["links"] = {"self": url_for("roles_api.view", id=obj.get("id"))}
        obj["writeable"] = request.authz.can_write_role(obj.get("id"))
        obj["shallow"] = obj.get("shallow", True)
        if self.nested or not obj["writeable"]:
            obj.pop("has_password", None)
            obj.pop("is_admin", None)
            obj.pop("is_muted", None)
            obj.pop("is_tester", None)
            obj.pop("is_blocked", None)
            obj.pop("api_key", None)
            obj.pop("email", None)
            obj.pop("locale", None)
            obj.pop("created_at", None)
            obj.pop("updated_at", None)
        if obj["type"] != Role.USER:
            obj.pop("api_key", None)
            obj.pop("email", None)
            obj.pop("locale", None)
        obj.pop("password", None)
        return obj


class AlertSerializer(Serializer):
    def _serialize(self, obj):
        obj["links"] = {"self": url_for("alerts_api.view", alert_id=obj.get("id"))}
        role_id = obj.pop("role_id", None)
        obj["writeable"] = request.authz.can_write_role(role_id)
        return obj


class CollectionSerializer(Serializer):
    def collect(self, obj):
        self.queue(RoleSchema, obj.get("creator_id"))
        for role_id in ensure_list(obj.get("team_id")):
            if request.authz.can_read_role(role_id):
                self.queue(RoleSchema, role_id)

    def _serialize(self, obj):
        pk = obj.get("id")
        authz = request.authz if obj.get("secret") else None
        obj["links"] = {
            "self": url_for("collections_api.view", collection_id=pk),
            "xref_export": url_for("xref_api.export", collection_id=pk, _authz=authz),
            "reconcile": url_for("reconcile_api.reconcile", collection_id=pk),
            "ui": collection_url(pk),
        }
        obj["shallow"] = obj.get("shallow", True)
        obj["writeable"] = not obj.get("external") and request.authz.can(
            pk, request.authz.WRITE
        )
        creator_id = obj.pop("creator_id", None)
        obj["creator"] = self.resolve(RoleSchema, creator_id, RoleSerializer)
        obj["team"] = []
        for role_id in ensure_list(obj.pop("team_id", [])):
            if request.authz.can_read_role(role_id):
                role = self.resolve(RoleSchema, role_id, RoleSerializer)
                obj["team"].append(role)
        return obj


class PermissionSerializer(Serializer):
    def collect(self, obj):
        self.queue(RoleSchema, obj.get("role_id"))

    def _serialize(self, obj):
        obj.pop("collection_id", None)
        role_id = obj.pop("role_id", None)
        obj["writeable"] = request.authz.can_read_role(role_id)  # wat
        obj["role"] = self.resolve(RoleSchema, role_id, RoleSerializer)
        return obj


class EntitySerializer(Serializer):
    def collect(self, obj):
        self.queue(CollectionSchema, obj.get("collection_id"))
        self.queue(RoleSchema, obj.get("role_id"))
        schema = model.get(obj.get("schema"))
        if schema is None or self.nested:  # FIXME what does that
            return
        properties = obj.get("properties", {})
        for name, values in properties.items():
            prop = schema.get(name)
            if prop is None or prop.type != registry.entity:
                continue
            for value in ensure_list(values):
                self.queue(EntitySchema, value)

    def _serialize(self, obj):  # noqa: C901
        proxy = make_entity_proxy(dict(obj))
        properties = {}
        for prop, value in proxy.itervalues():
            properties.setdefault(prop.name, [])
            if prop.type == registry.entity and not self.nested:
                entity = self.resolve(EntitySchema, value, EntitySerializer)
                if entity is not None:
                    entity["shallow"] = True
                    value = entity
            if value is not None:
                if type(value) is str and BASE64_ENCODED_PATTERN.search(value):
                    continue
                properties[prop.name].append(value)
        obj["properties"] = properties
        links = {
            "self": url_for("entities_api.view", entity_id=proxy.id),
            "expand": url_for("entities_api.expand", entity_id=proxy.id),
            "tags": url_for("entities_api.tags", entity_id=proxy.id),
            "ui": entity_url(proxy.id),
        }

        if self.detail_view and proxy.schema.is_a(Document.SCHEMA):
            content_hash = proxy.first("contentHash", quiet=True)
            if content_hash:
                name = entity_filename(proxy)
                mime = proxy.first("mimeType", quiet=True)
                links["file"] = archive_url(
                    content_hash,
                    file_name=name,
                    mime_type=mime,
                    role_id=request.authz.id,
                )

            pdf_hash = proxy.first("pdfHash", quiet=True)
            if pdf_hash:
                name = entity_filename(proxy, extension="pdf")
                links["pdf"] = archive_url(
                    pdf_hash, file_name=name, mime_type=PDF, role_id=request.authz.id
                )

            csv_hash = proxy.first("csvHash", quiet=True)
            if csv_hash:
                name = entity_filename(proxy, extension="csv")
                links["csv"] = archive_url(
                    csv_hash, file_name=name, mime_type=CSV, role_id=request.authz.id
                )

        collection = obj.get("collection") or {}
        coll_id = obj.pop("collection_id", collection.get("id"))
        # This is a last resort catcher for entities nested in other
        # entities that get resolved without regard for authz.
        if not request.authz.can(coll_id, request.authz.READ):
            return None
        obj["collection"] = self.resolve(
            CollectionSchema, coll_id, CollectionSerializer
        )
        role_id = obj.pop("role_id", None)
        # FIXME: some real world ES docs have an array here, we don't know why
        # currently. If there is ever a bug, this _could_ solve it:
        # if is_listish(role_id):
        #     if len(ensure_list(role_id)) == 1:
        #         role_id = role_id[0]
        obj["role"] = self.resolve(RoleSchema, role_id, RoleSerializer)
        obj["links"] = links
        obj["latinized"] = transliterate_values(proxy)
        obj["writeable"] = check_write_entity(obj, request.authz)
        obj["shallow"] = obj.get("shallow", True)
        # Phasing out multi-values here (2021-01):
        obj["created_at"] = min(ensure_list(obj.get("created_at")), default=None)
        obj["updated_at"] = max(ensure_list(obj.get("updated_at")), default=None)

        if self.detail_view:
            try:
                cluster = get_canonical_cluster(proxy.id, request.authz.search_auth)
                if cluster is not None:
                    obj["canonical_id"] = cluster["id"]
            except Exception:
                pass

        # Adding processing triggers and status for documents only (detail view)
        if self.detail_view and proxy.schema.is_a(Document.SCHEMA):
            if should_transcribe(proxy):
                links["transcribe"] = url_for(
                    "entities_api.transcribe", entity_id=proxy.id
                )
            if should_translate(
                obj["collection"]["id"], obj["collection"]["foreign_id"], proxy
            ):
                links["translate"] = url_for(
                    "entities_api.translate", entity_id=proxy.id
                )

            tracer = defer.tasks.translate.get_tracer(TRACER_URI)
            obj["processing_status"] = {"translate": tracer.is_processing(obj["id"])}

        return obj


class XrefSerializer(Serializer):
    @classmethod
    def _collection_ids(cls, obj) -> set[int]:
        return set(map(int, ensure_list(obj.get("collection_id"))))

    def collect(self, obj):
        self.queue(EntitySchema, obj.get("source"))
        self.queue(EntitySchema, obj.get("target"))
        for coll_id in self._collection_ids(obj):
            self.queue(CollectionSchema, coll_id)

    def _serialize(self, obj):
        source_id = obj.pop("source", None)
        target_id = obj.pop("target", None)

        # Orient: ensure the perspective collection's entity is "entity" (left).
        # The edge's source/target is determined by Identifier.pair ordering,
        # not by which collection the entity belongs to. Swap when the
        # perspective collection's entity ended up as target.
        perspective_cid = (request.view_args or {}).get("collection_id")
        if perspective_cid is not None:
            perspective_cid = int(perspective_cid)
            source_cids = set(map(int, ensure_list(obj.get("source_collection_id"))))
            target_cids = set(map(int, ensure_list(obj.get("target_collection_id"))))
            if perspective_cid not in source_cids and perspective_cid in target_cids:
                source_id, target_id = target_id, source_id

        obj["entity"] = self.resolve(EntitySchema, source_id, EntitySerializer)
        obj["match"] = self.resolve(EntitySchema, target_id, EntitySerializer)
        coll_ids = self._collection_ids(obj)
        obj["collections"] = [
            self.resolve(CollectionSchema, cid, CollectionSerializer)
            for cid in coll_ids
        ]
        if obj["entity"] and obj["match"]:
            obj["writeable"] = obj["entity"].get("writeable") or obj["match"].get(
                "writeable"
            )
            return obj
        log.warning(
            "Dropping xref result: source=%s (resolved=%s) target=%s (resolved=%s)",
            source_id,
            bool(obj["entity"]),
            target_id,
            bool(obj["match"]),
        )


class SimilarSerializer(Serializer):
    def collect(self, obj):
        EntitySerializer().collect(obj.get("entity", {}))

    def _serialize(self, obj):
        entity = obj.get("entity", {})
        obj["entity"] = EntitySerializer().serialize(entity)
        collection_id = obj.pop("collection_id")
        obj["writeable"] = request.authz.can(collection_id, request.authz.WRITE)
        return obj


class ExportSerializer(Serializer):
    def _serialize(self, obj):
        if obj.get("content_hash") and not obj.get("deleted"):
            url = archive_url(
                obj.get("content_hash"),
                file_name=obj.get("file_name"),
                mime_type=obj.get("mime_type"),
                role_id=request.authz.id,
            )
            obj["links"] = {"download": url}
        return obj


class EntitySetSerializer(Serializer):
    def collect(self, obj):
        self.queue(CollectionSchema, obj.get("collection_id"))
        self.queue(RoleSchema, obj.get("role_id"))

    def _serialize(self, obj):
        collection_id = obj.pop("collection_id", None)
        obj["shallow"] = obj.get("shallow", True)
        obj["writeable"] = request.authz.can(collection_id, request.authz.WRITE)
        obj["collection"] = self.resolve(
            CollectionSchema, collection_id, CollectionSerializer
        )
        role_id = obj.get("role_id", None)
        obj["role"] = self.resolve(RoleSchema, role_id, RoleSerializer)
        return obj


class EntitySetItemSerializer(Serializer):
    def collect(self, obj):
        self.queue(CollectionSchema, obj.get("collection_id"))
        self.queue(EntitySchema, obj.get("entity_id"))

    def _serialize(self, obj):
        coll_id = obj.pop("collection_id", None)
        # Should never come into effect:
        if not request.authz.can(coll_id, request.authz.READ):
            return None
        entity_id = obj.pop("entity_id", None)
        obj["entity"] = self.resolve(EntitySchema, entity_id, EntitySerializer)
        obj["collection"] = self.resolve(
            CollectionSchema, coll_id, CollectionSerializer
        )
        esi_coll_id = obj.get("entityset_collection_id")
        obj["writeable"] = request.authz.can(esi_coll_id, request.authz.WRITE)
        return obj


class CanonicalSerializer(Serializer):
    """Serializer for canonical clusters (replaces ProfileSerializer)."""

    def collect(self, obj):
        for coll_id in obj.get("collection_ids", set()):
            self.queue(CollectionSchema, coll_id)
        entity_serializer = EntitySerializer(nested=True)
        for entity in obj.get("entities", []):
            entity_serializer.collect(entity)

    def _serialize(self, obj):
        cids = obj.pop("collection_ids", set())
        obj["writeable"] = any(request.authz.can(c, request.authz.WRITE) for c in cids)
        obj["shallow"] = False
        # merged.to_dict() already includes `referents` (constituent entity IDs)
        proxy = obj.pop("merged")
        data = proxy.to_dict()
        data["latinized"] = transliterate_values(proxy)
        obj["merged"] = data
        # Serialize constituent entities (nested/shallow)
        entity_serializer = EntitySerializer(nested=True)
        obj["entities"] = [
            entity_serializer._serialize_common(entity)
            for entity in obj.get("entities", [])
        ]
        return obj


class StatementSerializer(Serializer):
    """Serializer for FtM statements — resolves dataset and entity references."""

    @staticmethod
    def _fid_to_collection_id(foreign_id: str) -> str | None:
        """Look up a collection by foreign_id and return str(int PK)."""
        if not foreign_id:
            return None
        coll = Collection.by_foreign_id(foreign_id)
        return str(coll.id) if coll else None

    def collect(self, obj):
        # Statement dataset is a foreign_id — convert to int PK for queue.
        coll_id = self._fid_to_collection_id(obj.get("dataset"))
        if coll_id:
            self.queue(CollectionSchema, coll_id)
        prop_type = get_prop_type(obj.get("schema"), obj.get("prop"))
        if prop_type == "entity":
            self.queue(EntitySchema, obj.get("value"))

    def _serialize(self, obj):
        dataset_fid = obj.pop("dataset", None)
        coll_id = self._fid_to_collection_id(dataset_fid)
        obj["dataset"] = self.resolve(CollectionSchema, coll_id, CollectionSerializer)
        prop_type = get_prop_type(obj.get("schema"), obj.get("prop"))
        if prop_type == "entity":
            entity = self.resolve(EntitySchema, obj.get("value"), EntitySerializer)
            if entity is not None:
                entity["shallow"] = True
                obj["value"] = entity
        return obj


class NotificationSerializer(Serializer):
    # Schema → Serializer for rendering resolved param objects.
    SERIALIZERS = {
        AlertSchema: AlertSerializer,
        EntitySchema: EntitySerializer,
        CollectionSchema: CollectionSerializer,
        EntitySetSchema: EntitySetSerializer,
        RoleSchema: RoleSerializer,
        ExportSchema: ExportSerializer,
    }

    def collect(self, obj):
        self.queue(RoleSchema, obj.get("actor_id"))
        event = Events.get(obj.get("event"))
        if event is not None:
            for name, schema_cls in event.param_types.items():
                key = obj.get("params", {}).get(name)
                self.queue(schema_cls, key)

    def _serialize(self, obj):
        event = Events.get(obj.get("event"))
        if event is None:
            return None
        params = {
            "actor": self.resolve(RoleSchema, obj.get("actor_id"), RoleSerializer)
        }
        for name, schema_cls in event.param_types.items():
            key = obj.get("params", {}).get(name)
            serializer = self.SERIALIZERS.get(schema_cls)
            params[name] = self.resolve(schema_cls, key, serializer)
        obj["params"] = params
        obj["event"] = model_dump(event)
        return obj


class MappingSerializer(Serializer):
    def collect(self, obj):
        self.queue(EntitySetSchema, obj.get("entityset_id"))
        self.queue(EntitySchema, obj.get("table_id"))

    def _serialize(self, obj):
        obj["links"] = {}
        entityset_id = obj.pop("entityset_id", None)
        obj["entityset"] = self.resolve(
            EntitySetSchema, entityset_id, EntitySetSerializer
        )
        obj["table"] = self.resolve(
            EntitySchema, obj.get("table_id", None), EntitySerializer
        )
        return obj


class BookmarkSerializer(Serializer):
    def collect(self, obj):
        self.queue(EntitySchema, obj.get("entity_id"))

    def _serialize(self, obj):
        obj["entity"] = self.resolve(
            EntitySchema, obj.get("entity_id"), EntitySerializer
        )

        # Entity could not be resolved, for example because it has been
        # removed or permissions have changed.
        if not obj["entity"]:
            return None

        obj["id"] = obj["entity"]["id"]
        obj.pop("entity_id", None)
        obj.pop("collection_id", None)
        obj.pop("writeable", None)
        return obj


class TagSerializer(Serializer):
    def collect(self, obj):
        self.queue(EntitySchema, obj.get("entity_id"))
        self.queue(RoleSchema, obj.get("role_id"))

    def _serialize(self, obj):
        obj["entity"] = self.resolve(
            EntitySchema, obj.get("entity_id"), EntitySerializer
        )
        obj["role"] = self.resolve(RoleSchema, obj.get("role_id"), RoleSerializer)

        return obj
