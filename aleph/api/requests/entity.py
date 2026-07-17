"""Request body schemas for the entities endpoints."""

from typing import Any

from pydantic import Field, model_validator

from aleph.model.common import APIBaseModel, SDict


class EntityUpdate(APIBaseModel):
    """``PUT /api/2/entities/<id>`` body – partial update.

    ``schema`` is required; ``properties`` is the FTM property bag.
    The python attribute is named ``schema_`` because pydantic reserves
    ``schema`` for the model's own JSON-Schema method; the JSON wire
    name is ``schema``.
    """

    id: str | None = None
    collection_id: str | None = None
    schema_: str = Field(alias="schema")
    properties: SDict = {}


class EntityCreate(EntityUpdate):
    """``POST /api/2/entities`` body – extends ``EntityUpdate`` with the
    create-only ``foreign_id`` and the option to pass the parent
    collection inline rather than by id."""

    collection: SDict | None = None
    foreign_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _extract_collection_id(cls, data: Any) -> Any:
        """Pull ``collection_id`` from a nested ``collection`` when not
        provided directly."""
        if isinstance(data, dict) and not data.get("collection_id"):
            collection = data.get("collection")
            if isinstance(collection, dict) and "id" in collection:
                data["collection_id"] = collection["id"]
        return data
