"""Flask serializer shims.

Each ``*Serializer`` wraps a pydantic schema + assembler behind the
``serialize`` / ``serialize_many`` / ``jsonify`` / ``jsonify_result``
interface that the Flask views expect.
"""

import logging
from typing import Any, Iterable

from banal import ensure_list
from flask import request
from flask_babel import gettext
from followthemoney.statement.util import get_prop_type
from pydantic import BaseModel

from aleph.api.assemblers.base import Assembler
from aleph.api.assemblers.collection import CollectionAssembler
from aleph.api.assemblers.entity import EntityAssembler
from aleph.authz import Authz
from aleph.core import url_for
from aleph.logic.entities import check_write_entity, transliterate_values
from aleph.logic.resolver import RequestResolver
from aleph.logic.util import archive_url
from aleph.model import (
    AlertSchema,
    Collection,
    CollectionSchema,
    EntitySchema,
    EntitySetItemSchema,
    EntitySetSchema,
    ExportSchema,
    MappingSchema,
    NotificationSchema,
    PermissionSchema,
    Role,
    RoleSchema,
)
from aleph.model.bookmark import BookmarkSchema
from aleph.model.canonical import (
    CanonicalSchema,
    StatementSchema,
)
from aleph.model.common import SDict, model_dump
from aleph.model.entity import SimilarSchema
from aleph.model.tag import TagSchema
from aleph.model.xref import XrefSchema
from aleph.views.util import jsonify

log = logging.getLogger(__name__)


# === Flask serializer base ===================================================


class Serializer:
    """Thin Flask shim: validates to pydantic, assembles, model_dump."""

    SCHEMA: type[BaseModel] | None = None
    ASSEMBLER: type[Assembler] = Assembler

    def __init__(self, nested: bool = False, detail_view: bool = False) -> None:
        self.nested = nested
        self.detail_view = detail_view

    def _to_schema(self, obj: Any) -> BaseModel | None:
        if obj is None:
            return None
        if isinstance(obj, BaseModel):
            return obj
        if self.SCHEMA:
            return self.SCHEMA.model_validate(obj)
        return None

    def _make_assembler(self, authz: Authz | None = None) -> Assembler:
        resolver = RequestResolver()
        authz = authz or request.authz
        return self.ASSEMBLER(resolver, authz, detail=self.detail_view)

    def serialize(self, obj: Any, authz: Authz | None = None) -> SDict | None:
        schema = self._to_schema(obj)
        if schema is None:
            return None
        assembled = self._make_assembler(authz).assemble(schema)
        return model_dump(assembled) if assembled else None

    def serialize_many(
        self, objs: Iterable[Any], authz: Authz | None = None
    ) -> list[SDict]:
        schemas = [
            s for o in ensure_list(objs) if (s := self._to_schema(o)) is not None
        ]
        assembled = self._make_assembler(authz).assemble_many(schemas)
        return [model_dump(s) for s in assembled]

    @classmethod
    def jsonify(
        cls, obj, authz: Authz | None = None, detail_view: bool = False, **kwargs
    ):
        data = cls(detail_view=detail_view).serialize(obj, authz=authz)
        return _jsonify(data, **kwargs)

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
                return _jsonify(data, status=500)
        return _jsonify(data, **kwargs)


def _jsonify(data, **kwargs):
    return jsonify(data, **kwargs)


# === Assembler subclasses ====================================================


class RoleAssembler(Assembler):
    def assemble(self, obj: RoleSchema) -> RoleSchema:
        obj = super().assemble(obj)
        obj.links = {"self": url_for("roles_api.view", id=obj.id)}
        obj.writeable = self.authz.can_write_role(obj.id)
        obj.shallow = not self.detail
        if obj.shallow or not obj.writeable:
            obj.email = None
            obj.api_key = None
            obj.locale = None
            obj.has_password = None
            obj.is_admin = None
            obj.is_muted = None
            obj.is_tester = None
            obj.is_blocked = None
            obj.created_at = None
            obj.updated_at = None
        if obj.type != Role.USER:
            obj.api_key = None
            obj.email = None
            obj.locale = None
        return obj


class AlertAssembler(Assembler):
    def assemble(self, obj: AlertSchema) -> AlertSchema:
        obj = super().assemble(obj)
        obj.links = {"self": url_for("alerts_api.view", alert_id=obj.id)}
        obj.writeable = self.authz.can_write_role(obj.role_id)
        return obj


class ExportAssembler(Assembler):
    def assemble(self, obj: ExportSchema) -> ExportSchema:
        obj = super().assemble(obj)
        if obj.content_hash and not obj.deleted:
            obj.links = {
                "download": archive_url(
                    obj.content_hash,
                    file_name=obj.file_name,
                    mime_type=obj.mime_type,
                    role_id=self.authz.id,
                )
            }
        return obj


class PermissionAssembler(Assembler):
    def assemble(self, obj: PermissionSchema) -> PermissionSchema:
        obj = super().assemble(obj)
        obj.writeable = self.authz.can_read_role(obj.role_id)
        return obj


class EntitySetAssembler(Assembler):
    def assemble(self, obj: EntitySetSchema) -> EntitySetSchema:
        obj = super().assemble(obj)
        obj.writeable = self.authz.can(obj.collection_id, self.authz.WRITE)
        obj.shallow = not self.detail
        return obj


class EntitySetItemAssembler(Assembler):
    def assemble(self, obj: EntitySetItemSchema) -> EntitySetItemSchema | None:
        if not self.authz.can(obj.collection_id, self.authz.READ):
            return None
        obj = super().assemble(obj)
        obj.writeable = self.authz.can(obj.entityset_collection_id, self.authz.WRITE)
        return obj


class XrefAssembler(Assembler):
    """Resolves entity/match, orients by perspective collection, resolves
    the collection list."""

    def __init__(
        self,
        resolver,
        authz,
        detail=False,
        perspective_collection_id: int | None = None,
    ):
        super().__init__(resolver, authz, detail=detail)
        self.perspective_collection_id = perspective_collection_id

    def assemble(self, obj: XrefSchema) -> XrefSchema | None:
        obj = super().assemble(obj)

        # Orient: ensure the perspective collection's entity is "entity" (left).
        # The edge's source/target is determined by Identifier.pair ordering,
        # not by which collection the entity belongs to. Swap when the
        # perspective collection's entity ended up as target.
        if self.perspective_collection_id is not None:
            source_cids = set(obj.source_collection_id)
            target_cids = set(obj.target_collection_id)
            if (
                self.perspective_collection_id not in source_cids
                and self.perspective_collection_id in target_cids
            ):
                obj.entity, obj.match = obj.match, obj.entity

        # Resolve collection list
        coll_ids = [str(i) for i in obj.collection_id]
        obj.collections = self.resolver.get_many(CollectionSchema, coll_ids)

        if obj.entity and obj.match:
            # check if request can write judgement if any of the edge entities
            # are writeable to the user
            obj.writeable = check_write_entity(
                obj.entity, self.authz
            ) or check_write_entity(obj.match, self.authz)
            return obj
        log.warning(
            "Dropping xref result: entity=%s match=%s",
            bool(obj.entity),
            bool(obj.match),
        )
        return None


class SimilarAssembler(Assembler):
    def assemble_entity(self, e: EntitySchema) -> EntitySchema:
        assembler = EntityAssembler(self.resolver, self.authz, self.detail)
        return assembler.assemble(e) or e

    def assemble(self, obj: SimilarSchema) -> Any:
        obj = super().assemble(obj)
        obj.entity = self.assemble_entity(obj.entity)
        obj.writeable = check_write_entity(obj.entity, self.authz)
        return obj


class MappingAssembler(Assembler):
    pass


class BookmarkAssembler(Assembler):
    def assemble(self, obj: BookmarkSchema) -> BookmarkSchema | None:
        obj = super().assemble(obj)
        entity = self.resolver.get(EntitySchema, obj.entity_id)
        if entity is None:
            return None
        obj.entity = entity
        return obj


class TagAssembler(Assembler):
    pass


class NotificationAssembler(Assembler):
    def assemble(self, obj: NotificationSchema) -> NotificationSchema:
        obj = super().assemble(obj)
        actor = self.resolver.get(RoleSchema, obj.actor_id)
        params: SDict = {"actor": model_dump(actor) if actor else None}
        event = obj.event
        if event is not None:
            for name, schema_cls in event.param_types.items():
                key = obj.params.get(name)
                if key:
                    resolved = self.resolver.get(schema_cls, str(key))
                    params[name] = model_dump(resolved) if resolved else None
                else:
                    params[name] = None
        obj.params = params
        return obj


class StatementAssembler(Assembler):
    def assemble(self, obj: StatementSchema) -> StatementSchema:
        obj = super().assemble(obj)
        if isinstance(obj.dataset, str):
            coll = Collection.by_foreign_id(obj.dataset)
            if coll:
                resolved = self.resolver.get(CollectionSchema, str(coll.id))
                if resolved:
                    obj.dataset = resolved
        prop_type = get_prop_type(obj.schema_, obj.prop)
        if prop_type == "entity" and isinstance(obj.value, str):
            entity = self.resolver.get(EntitySchema, obj.value)
            if entity is not None:
                entity.shallow = True
                obj.value = entity
        return obj


class CanonicalAssembler(Assembler):
    def assemble_entities(self, obj: CanonicalSchema) -> list[EntitySchema]:
        # EntityAssembler.assemble returns None for entities the requester
        # may not read – drop those from the cluster listing.
        a = EntityAssembler(self.resolver, self.authz, self.detail)
        return [ent for e in obj.entities if (ent := a.assemble(e)) is not None]

    def assemble(self, obj: CanonicalSchema) -> CanonicalSchema:
        obj = super().assemble(obj)
        obj.writeable = any(
            self.authz.can(c, self.authz.WRITE) for c in obj.collection_ids
        )
        obj.shallow = False
        if obj.merged:
            obj.merged.latinized = transliterate_values(obj.merged.to_proxy())
        obj.entities = self.assemble_entities(obj)
        return obj


# === Serializer classes (Flask shims) ========================================


class RoleSerializer(Serializer):
    SCHEMA = RoleSchema
    ASSEMBLER = RoleAssembler


class AlertSerializer(Serializer):
    SCHEMA = AlertSchema
    ASSEMBLER = AlertAssembler


class CollectionSerializer(Serializer):
    SCHEMA = CollectionSchema
    ASSEMBLER = CollectionAssembler


class PermissionSerializer(Serializer):
    SCHEMA = PermissionSchema
    ASSEMBLER = PermissionAssembler


class EntitySerializer(Serializer):
    SCHEMA = EntitySchema
    ASSEMBLER = EntityAssembler


class XrefSerializer(Serializer):
    SCHEMA = XrefSchema
    ASSEMBLER = XrefAssembler

    def _make_assembler(self, authz: Authz | None = None) -> XrefAssembler:
        resolver = RequestResolver()
        authz = authz or request.authz
        perspective_cid = (request.view_args or {}).get("collection_id")
        if perspective_cid is not None:
            perspective_cid = int(perspective_cid)
        return XrefAssembler(
            resolver,
            authz,
            detail=self.detail_view,
            perspective_collection_id=perspective_cid,
        )


class SimilarSerializer(Serializer):
    SCHEMA = SimilarSchema
    ASSEMBLER = SimilarAssembler


class ExportSerializer(Serializer):
    SCHEMA = ExportSchema
    ASSEMBLER = ExportAssembler


class EntitySetSerializer(Serializer):
    SCHEMA = EntitySetSchema
    ASSEMBLER = EntitySetAssembler


class EntitySetItemSerializer(Serializer):
    SCHEMA = EntitySetItemSchema
    ASSEMBLER = EntitySetItemAssembler


class CanonicalSerializer(Serializer):
    SCHEMA = CanonicalSchema
    ASSEMBLER = CanonicalAssembler


class StatementSerializer(Serializer):
    SCHEMA = StatementSchema
    ASSEMBLER = StatementAssembler


class NotificationSerializer(Serializer):
    SCHEMA = NotificationSchema
    ASSEMBLER = NotificationAssembler


class MappingSerializer(Serializer):
    SCHEMA = MappingSchema
    ASSEMBLER = MappingAssembler


class BookmarkSerializer(Serializer):
    SCHEMA = BookmarkSchema
    ASSEMBLER = BookmarkAssembler


class TagSerializer(Serializer):
    SCHEMA = TagSchema
    ASSEMBLER = TagAssembler
