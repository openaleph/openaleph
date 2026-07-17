"""Request body schemas for the collection permission endpoints."""

from aleph.model.common import APIBaseModel
from aleph.model.role import RoleSchema


class PermissionUpdate(APIBaseModel):
    """``POST /api/2/collections/<id>/permissions`` body – single update."""

    read: bool
    write: bool
    role_id: str | None = None
    role: RoleSchema | None = None
