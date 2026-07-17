"""API request body schemas.

One module per resource. Each module defines pydantic models for the
``POST``/``PUT`` bodies that the API accepts. They are kept separate
from the canonical resource schemas in ``aleph.model`` because:

- their lifetime is tied to the API contract, not to the persisted
  state shape;
- they may add per-action validators (min/max length, required fields)
  that don't make sense on the canonical model;
- the data layer must not import from the API layer.

Re-exported here for convenience so callers can do
``from aleph.api.requests import RoleCreate``.
"""

from aleph.api.requests.alert import AlertCreate
from aleph.api.requests.bookmark import BookmarkCreate
from aleph.api.requests.collection import CollectionCreate, CollectionUpdate
from aleph.api.requests.entity import EntityCreate, EntityUpdate
from aleph.api.requests.mapping import MappingCreate, MappingUpdate
from aleph.api.requests.permission import PermissionUpdate
from aleph.api.requests.role import (
    RoleCodeCreate,
    RoleCreate,
    RoleLogin,
    RoleUpdate,
)
from aleph.api.requests.tag import TagCreate

__all__ = [
    "AlertCreate",
    "BookmarkCreate",
    "CollectionCreate",
    "CollectionUpdate",
    "EntityCreate",
    "EntityUpdate",
    "MappingCreate",
    "MappingUpdate",
    "PermissionUpdate",
    "RoleCodeCreate",
    "RoleCreate",
    "RoleLogin",
    "RoleUpdate",
    "TagCreate",
]
