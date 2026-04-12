"""Generic auto-resolving assembler for pydantic models.

Introspects model fields for ``ResolveFrom`` metadata markers and
auto-resolves nested schema objects via the resolver cache.

Assemblers are instantiated with ``resolver``, ``authz``, and ``detail``
bound for the request lifetime::

    assembler = FooAssembler(resolver, authz, detail=True)
    result = assembler.assemble(obj)
    results = assembler.assemble_many(objs)

Subclasses override ``assemble`` for per-resource logic, calling
``super().assemble(obj)`` first for the generic resolution.
"""

from collections import defaultdict
from typing import Any

from pydantic.fields import FieldInfo

from aleph.authz import Authz
from aleph.logic.resolver import RequestResolver
from aleph.logic.resolver.registry import _REGISTRY
from aleph.model.common import ResolveFrom


def _get_resolve_meta(field_info: FieldInfo) -> ResolveFrom | None:
    """Read the ``ResolveFrom`` marker from ``Annotated`` metadata."""
    for entry in field_info.metadata:
        if isinstance(entry, ResolveFrom):
            return entry
    return None


class Assembler:
    """Generic assembler with auto-resolution of ``ResolveFrom`` fields.

    Subclasses override ``assemble`` for custom logic::

        class FooAssembler(Assembler):
            def assemble(self, obj):
                obj = super().assemble(obj)
                obj.writeable = self.authz.can(obj.id, self.authz.WRITE)
                return obj
    """

    def __init__(
        self,
        resolver: RequestResolver,
        authz: Authz | None = None,
        detail: bool = False,
    ) -> None:
        self.resolver = resolver
        self.authz = authz
        self.detail = detail

    def assemble(self, obj: Any) -> Any:
        self._resolve_nested(obj)
        return obj

    def assemble_many(self, objs: list) -> list:
        self.prefetch(objs)
        return [r for o in objs if (r := self.assemble(o)) is not None]

    def prefetch(self, objs: list) -> None:
        """Batch pre-load: collect keys from ``ResolveFrom`` metadata."""
        keys_by_schema: dict[type, set[str]] = defaultdict(set)
        for obj in objs:
            for field_info in obj.__class__.model_fields.values():
                meta = _get_resolve_meta(field_info)
                if meta is None or meta.schema_cls is None:
                    continue
                if meta.schema_cls not in _REGISTRY:
                    continue
                key = getattr(obj, meta.id_field, None)
                if key is not None:
                    keys_by_schema[meta.schema_cls].add(str(key))
        for schema_cls, keys in keys_by_schema.items():
            self.resolver.get_many(schema_cls, keys)

    def _resolve_nested(self, obj: Any) -> None:
        """Auto-resolve fields marked with ``ResolveFrom``, recursively."""
        for field_name, field_info in obj.__class__.model_fields.items():
            meta = _get_resolve_meta(field_info)
            if meta is None or meta.schema_cls is None:
                continue
            if meta.schema_cls not in _REGISTRY:
                continue
            key = getattr(obj, meta.id_field, None)
            if key is not None:
                resolved = self.resolver.get(meta.schema_cls, str(key))
                if resolved is not None:
                    self._resolve_nested(resolved)
                setattr(obj, field_name, resolved)
