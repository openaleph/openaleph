import logging

from flask import Blueprint, request
from flask_babel import gettext
from werkzeug.exceptions import BadRequest

from aleph import scoped_tokens
from aleph.settings import SETTINGS
from aleph.views.util import jsonify, obj_or_404, parse_request, require

blueprint = Blueprint("tokens_api", __name__)
log = logging.getLogger(__name__)


def _require_full_sign_in():
    """Token management is closed to scoped tokens. The endpoints are also
    left out of `SCOPED_TOKEN_ENDPOINTS`; this is the second lock."""
    require(scoped_tokens.is_enabled())
    require(request.authz.can_manage_tokens())


def _bad_request(message):
    resp = jsonify({"status": "error", "message": message}, status=400)
    return BadRequest(response=resp)


@blueprint.route("/api/2/tokens", methods=["GET"])
def index():
    """Returns the scoped API tokens of the user, without their secrets.
    ---
    get:
      summary: List scoped API tokens
      description: >-
        Lists the scoped API tokens of the current user. Requires a full
        sign-in (API key or session); a scoped token is refused.
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  total:
                    type: integer
                  results:
                    type: array
                    items:
                      $ref: '#/components/schemas/ScopedToken'
          description: OK
      tags:
        - Role
    """
    _require_full_sign_in()
    results = scoped_tokens.list_scoped_tokens(request.authz.id)
    return jsonify({"status": "ok", "total": len(results), "results": results})


@blueprint.route("/api/2/tokens", methods=["POST"])
def create():
    """Creates a scoped API token for the user.
    ---
    post:
      summary: Create a scoped API token
      description: >-
        Creates a credential limited to the listed collections and to a
        lifetime. It can read and write data in those collections as far as
        the user can at the time of each request, and nothing else: it is
        never an administrator and cannot manage the account, permissions
        or other tokens. Send it as `Authorization: ApiKey <token>`; it is
        not accepted as a URL parameter. The `token` is returned once and
        cannot be retrieved later. Requires a full sign-in (API key or
        session); a scoped token is refused.
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ScopedTokenCreate'
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ScopedToken'
          description: OK
        '400':
          description: >-
            Invalid request, e.g. a lifetime above the maximum or a
            collection the user cannot access.
      tags:
        - Role
    """
    _require_full_sign_in()
    require(request.authz.session_write)
    data = parse_request("ScopedTokenCreate")
    read = set(data["read"])
    write = set(data.get("write", []))
    if data["expires_in"] > SETTINGS.SCOPED_TOKEN_MAX_EXPIRE:
        raise _bad_request(
            gettext(
                "The longest lifetime allowed for a token is %(max)d seconds.",
                max=SETTINGS.SCOPED_TOKEN_MAX_EXPIRE,
            )
        )
    if not write <= read:
        raise _bad_request(
            gettext("Collections in `write` must also be listed in `read`.")
        )
    # Same answer for a collection that does not exist and one the user
    # cannot access.
    readable = set(request.authz.collections(request.authz.READ))
    writeable = set(request.authz.collections(request.authz.WRITE))
    if not read <= readable or not write <= writeable:
        raise _bad_request(
            gettext("You cannot grant access to a collection you cannot access.")
        )
    existing = scoped_tokens.list_scoped_tokens(request.authz.id)
    if len(existing) >= scoped_tokens.MAX_TOKENS_PER_ROLE:
        raise _bad_request(
            gettext("Too many tokens. Revoke one before creating another.")
        )
    token = scoped_tokens.create_scoped_token(
        request.authz.id,
        label=data["label"],
        read=sorted(read),
        write=sorted(write),
        expires_in=data["expires_in"],
    )
    return jsonify(token, headers={"Cache-Control": "no-store"})


@blueprint.route("/api/2/tokens/<token_id>", methods=["DELETE"])
def delete(token_id):
    """Revokes a scoped API token of the user.
    ---
    delete:
      summary: Revoke a scoped API token
      description: >-
        Ends the token at once. Requires a full sign-in (API key or
        session); a scoped token is refused.
      parameters:
      - description: The `id` of the token, as returned when listing.
        in: path
        name: token_id
        required: true
        schema:
          type: string
      responses:
        '204':
          description: No Content
        '404':
          description: No such token.
      tags:
        - Role
    """
    _require_full_sign_in()
    obj_or_404(scoped_tokens.revoke_scoped_token(request.authz.id, token_id) or None)
    return ("", 204)
