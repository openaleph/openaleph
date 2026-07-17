"""Request body schemas for the collections endpoints."""

from typing import Annotated

from pydantic import Field

from aleph.model.collection import Categories
from aleph.model.common import APIBaseModel
from aleph.model.role import RoleSchema


class CollectionCreate(APIBaseModel):
    """``POST /api/2/collections`` body."""

    label: Annotated[str, Field(min_length=2, max_length=500)]
    summary: str | None = None
    countries: list[str] = []
    languages: list[str] = []
    data_url: str | None = None
    foreign_id: str | None = None
    info_url: str | None = None
    publisher: str | None = None
    publisher_url: str | None = None
    category: Categories | None = None
    frequency: str | None = None
    restricted: bool | None = None
    xref: bool | None = None
    contains_ai: bool | None = None
    contains_ai_comment: str | None = None
    taggable: bool | None = None
    external: bool | None = None


class CollectionUpdate(CollectionCreate):
    """``POST /api/2/collections/<id>`` body."""

    creator_id: str | None = None
    creator: RoleSchema | None = None
