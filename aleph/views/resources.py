"""Authz-checked resource accessors for view functions.

Usage in views::

    from aleph.views import resources

    entity = resources.get_entity(entity_id)
    collection = resources.get_collection(collection_id)
    entityset = resources.get_entityset(entityset_id, request.authz.WRITE)
"""

from typing import Type, TypeVar

from flask import request
from openaleph_procrastinate.manage.status import get_dataset_status

from aleph.authz import Authz
from aleph.logic.resolver import cache
from aleph.model import (
    Collection,
    CollectionDetailSchema,
    CollectionSchema,
    EntitySchema,
    EntitySet,
    EntitySetSchema,
)
from aleph.model.collection import CollectionStatus
from aleph.model.common import APIBaseModel, SDict, model_dump
from aleph.views.util import obj_or_404, require

T = TypeVar("T", bound=APIBaseModel)


def get_resource(schema_cls: Type[T], identifier: str) -> T:
    """Resolver lookup + 404. No authz — callers handle their own
    permission check when the pattern differs per resource."""
    return cache.get_or_404(schema_cls, str(identifier))


def get_collection(
    collection_id: int | str, action: str = Authz.READ
) -> CollectionSchema:
    """Resolver lookup + 404 + authz for a Collection read path."""
    coll = cache.get_or_404(CollectionSchema, str(collection_id))
    require(request.authz.can(coll.id, action))
    return coll


def get_collection_resource(
    schema_cls: Type[T], identifier: str, action: str = Authz.READ
) -> T:
    """Resolver lookup + 404 + collection-scoped authz. Works for
    any resource that carries a ``collection_id`` (Entity, EntitySet,
    EntitySetItem, Mapping, etc.)."""
    # First check if collection exists and has action rights
    obj = cache.get_or_404(schema_cls, str(identifier))
    # This will raise if invalid:
    get_collection(obj.collection_id, action)
    return obj


def get_detail_collection(
    collection_id: int | str, action: str = Authz.READ
) -> CollectionDetailSchema:
    """Resolver lookup + 404 + authz for a Collection detail view.

    Returns the cached ``CollectionDetailSchema`` with live procrastinate
    job status patched in (status is never cached — it's live data).
    """
    detail = cache.get_or_404(CollectionDetailSchema, str(collection_id))
    require(request.authz.can(detail.id, action))
    # Patch live job status — not cached because it changes continuously.
    dataset_name = f"collection_{collection_id}"
    ds = get_dataset_status(dataset_name)
    if ds is not None:
        detail.status = CollectionStatus(**ds.model_dump())
    return detail


def get_entity(entity_id: str, action: str = Authz.READ) -> EntitySchema:
    """Resolver lookup + 404 + collection-scoped authz for an entity."""
    return get_collection_resource(EntitySchema, entity_id, action)


def get_entityset(entityset_id: str, action: str = Authz.READ) -> EntitySetSchema:
    """Resolver lookup + 404 + collection-scoped authz for an entity set."""
    return get_collection_resource(EntitySetSchema, entityset_id, action)


# --- Legacy / write-path helpers -------------------------------------------


def get_index_entity(entity_id: str, action: str = Authz.READ) -> SDict:
    """Legacy helper — returns a dict. Prefer ``get_entity`` for new code."""
    return model_dump(get_entity(entity_id, action))


def get_db_collection(collection_id: int | str, action: str = Authz.READ) -> Collection:
    """SQLA lookup + 404 + authz. Use for write paths that need
    the ORM instance. For read paths prefer ``get_collection``."""
    collection = obj_or_404(Collection.by_id(collection_id))
    require(request.authz.can(collection.id, action))
    return collection


def get_db_entityset(entityset_id: str, action: str = Authz.READ) -> EntitySet:
    """SQLA lookup + 404 + authz. Use for write paths that need
    the ORM instance."""
    eset = obj_or_404(EntitySet.by_id(entityset_id))
    require(request.authz.can(eset.collection_id, action))
    return eset
