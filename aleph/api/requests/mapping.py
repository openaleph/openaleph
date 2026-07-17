"""Request body schemas for the mapping endpoints."""

from aleph.model.common import APIBaseModel, SDict


class MappingCreate(APIBaseModel):
    """``POST /api/2/collections/<id>/mappings`` body."""

    table_id: str
    mapping_query: SDict
    entityset_id: str | None = None


class MappingUpdate(MappingCreate):
    """``PUT /api/2/collections/<id>/mappings/<id>`` body — same shape
    as :class:`MappingCreate`."""
