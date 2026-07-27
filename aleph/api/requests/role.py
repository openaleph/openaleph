"""Request body schemas for the roles and sessions endpoints."""

from typing import Annotated

from pydantic import Field

from aleph.model.common import APIBaseModel


class RoleCodeCreate(APIBaseModel):
    """``POST /api/2/roles/code`` body – request a signup email."""

    email: str


class RoleCreate(APIBaseModel):
    """``POST /api/2/roles`` body – finish signup with the
    email-confirmation token."""

    name: Annotated[str, Field(min_length=4)] | None = None
    password: Annotated[str, Field(min_length=6)]
    code: str


class RoleUpdate(APIBaseModel):
    """``POST /api/2/roles/<id>`` body – partial role update.

    All fields optional; ``current_password`` is required when changing
    ``password``.
    """

    name: Annotated[str, Field(min_length=4)] | None = None
    is_muted: bool | None = None
    is_tester: bool | None = None
    password: Annotated[str, Field(min_length=6)] | None = None
    current_password: str | None = None
    locale: str | None = None


class RoleLogin(APIBaseModel):
    """``POST /api/2/sessions/login`` body – email + password login."""

    email: str
    password: str
