"""Request body schemas for the tags endpoints."""

from typing import Annotated

from pydantic import Field

from aleph.model.common import APIBaseModel


class TagCreate(APIBaseModel):
    """``POST /api/2/tags`` body."""

    entity_id: str
    tag: Annotated[str, Field(min_length=1, max_length=128)]
