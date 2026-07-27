"""Request body schemas for the bookmarks endpoints."""

from aleph.model.common import APIBaseModel


class BookmarkCreate(APIBaseModel):
    """``POST /api/2/bookmarks`` body."""

    entity_id: str
