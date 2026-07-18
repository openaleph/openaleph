"""Request body schemas for the alerts endpoints."""

from typing import Annotated

from pydantic import Field

from aleph.model.common import APIBaseModel


class AlertCreate(APIBaseModel):
    """``POST /api/2/alerts`` body."""

    query: Annotated[str, Field(min_length=3, max_length=100)]
