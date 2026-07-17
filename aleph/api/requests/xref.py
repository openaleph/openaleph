"""Request body schemas for the xref endpoints."""

from aleph.model.common import APIBaseModel


class Pairwise(APIBaseModel):
    """``POST /api/2/xref/_decide`` body."""

    entity_id: str
    match_id: str
    judgement: str
