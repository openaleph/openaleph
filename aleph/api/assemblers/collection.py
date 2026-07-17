"""Collection assembler – request-time enrichment of CollectionSchema."""

from aleph.api.assemblers.base import Assembler
from aleph.core import url_for
from aleph.logic.util import collection_url
from aleph.model import CollectionSchema, RoleSchema
from aleph.model.common import SDict


class CollectionAssembler(Assembler):
    """Enrich a ``CollectionSchema`` with links, writeable flag,
    resolved creator and team roles."""

    def prefetch(self, objs: list[CollectionSchema]) -> None:
        role_ids: set[str] = set()
        for obj in objs:
            if obj.creator_id:
                role_ids.add(obj.creator_id)
            for rid in obj.team_id:
                role_ids.add(rid)
        if role_ids:
            self.resolver.get_many(RoleSchema, list(role_ids))

    def assemble(self, obj: CollectionSchema) -> CollectionSchema:
        self._resolve_nested(obj)
        obj.links = self._build_links(obj)
        # external collections appear read-only in the UI even for admins
        obj.writeable = not obj.external and self.authz.can(obj.id, self.authz.WRITE)
        obj.shallow = not self.detail
        obj.creator = (
            self.resolver.get(RoleSchema, obj.creator_id) if obj.creator_id else None
        )
        visible_ids = [rid for rid in obj.team_id if self.authz.can_read_role(rid)]
        obj.team = self.resolver.get_many(RoleSchema, visible_ids)
        return obj

    def _build_links(self, obj: CollectionSchema) -> SDict:
        authz_for_links = self.authz if obj.secret else None
        return {
            "self": url_for("collections_api.view", collection_id=obj.id),
            "xref_export": url_for(
                "xref_api.export", collection_id=obj.id, _authz=authz_for_links
            ),
            "reconcile": url_for("reconcile_api.reconcile", collection_id=obj.id),
            "ui": collection_url(obj.id),
        }
