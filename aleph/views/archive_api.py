import logging
from datetime import datetime, timedelta

from flask import Blueprint, redirect, request, send_file
from flask.wrappers import Response
from followthemoney.helpers import entity_filename
from rigour.mime.types import CSV, PDF
from werkzeug.exceptions import BadRequest
from werkzeug.wrappers import Response as WerkzeugResponse

from aleph.core import archive
from aleph.logic.util import archive_token, archive_url
from aleph.util import make_entity_proxy
from aleph.views.context import tag_request
from aleph.views.util import get_flag, get_index_entity, jsonify

log = logging.getLogger(__name__)
blueprint = Blueprint("archive_api", __name__)

# Entity hash properties that can be resolved to an archive blob, mapped to
# the file name extension and mime type used for the download. `None` means
# the value is derived from the entity itself.
RESOLVE_PROPS: dict[str, tuple[str | None, str | None]] = {
    "contentHash": (None, None),
    "pdfHash": ("pdf", PDF),
    "csvHash": ("csv", CSV),
}


@blueprint.route("/api/2/archive/resolve")
def resolve() -> WerkzeugResponse:
    """Resolve an entity hash property to a fresh archive download URL.

    Unlike the signed URLs embedded directly into (browser-cached) entity
    payloads in the past, this endpoint checks the requesting user's read
    permission on the entity at request time and redirects to a freshly
    signed archive URL that never arrives stale at the client. For storage
    backends that support signing (S3, Google Cloud Storage), this is the
    storage URL directly; otherwise a token-authorized link to the retrieve
    endpoint below.
    ---
    get:
      summary: Resolve an entity property to an archive download URL
      parameters:
      - description: The id of the entity to resolve
        in: query
        name: entity
        required: true
        schema:
          type: string
      - description: The hash property to resolve
        in: query
        name: prop
        schema:
          type: string
          enum: [contentHash, pdfHash, csvHash]
          default: contentHash
      - description: >-
          Set to false to receive the signed archive URL as a JSON object
          instead of a redirect. Useful for clients that cannot intercept
          redirects (e.g. XHR) and need to hand the URL to a component that
          sends no Authorization header.
        in: query
        name: redirect
        schema:
          type: boolean
          default: true
      responses:
        '200':
          description: The signed archive URL (with `redirect=false`)
          content:
            application/json:
              schema:
                type: object
                properties:
                  url:
                    type: string
        '302':
          description: Redirect to a signed archive URL
        '400':
          description: Invalid query parameters
        '403':
          description: Access denied
        '404':
          description: Entity or blob does not exist.
      tags:
      - Archive
    """
    entity_id = request.args.get("entity")
    if entity_id is None:
        raise BadRequest("Missing `entity` query parameter.")
    prop = request.args.get("prop", "contentHash")
    if prop not in RESOLVE_PROPS:
        raise BadRequest("Invalid `prop` query parameter.")
    entity = get_index_entity(entity_id, request.authz.READ)
    proxy = make_entity_proxy(entity)
    content_hash = proxy.first(prop, quiet=True)
    if content_hash is None:
        return Response(status=404)
    tag_request(
        entity_id=entity_id, content_hash=content_hash, role_id=request.authz.id
    )
    extension, mime_type = RESOLVE_PROPS[prop]
    file_name = entity_filename(proxy, extension=extension)
    if mime_type is None:
        mime_type = proxy.first("mimeType", quiet=True)
    expire = datetime.utcnow() + timedelta(days=1)
    # For storage backends that support signing (S3, GCS), hand out the
    # signed storage URL directly and save clients the extra hop through
    # the retrieve endpoint below.
    url = archive.generate_url(
        content_hash,
        file_name=file_name,
        mime_type=mime_type,
        expire=expire,
    )
    if url is None:
        # The storage backend cannot sign URLs (e.g. local file archive),
        # so hand out a token-authorized link to the retrieve endpoint.
        url = archive_url(
            content_hash,
            file_name=file_name,
            mime_type=mime_type,
            expire=expire,
            role_id=request.authz.id,
        )
    if not get_flag("redirect", default=True):
        return jsonify({"url": url})
    return redirect(url)


@blueprint.route("/api/2/archive")
def retrieve():
    """Downloads a binary blob from the blob storage archive.
    ---
    get:
      summary: Download a blob from the archive
      parameters:
      - description: Authorization token for an archive blob
        in: query
        name: claim
        schema:
          type: string
          description: A signed JWT with the object hash.
      responses:
        '200':
          description: OK
          content:
            '*/*': {}
        '404':
          description: Object does not exist.
      tags:
      - Archive
    """
    token = request.args.get("token")
    content_hash, file_name, mime_type, expire, role_id = archive_token(token)
    tag_request(content_hash=content_hash, file_name=file_name, role_id=role_id)
    url = archive.generate_url(
        content_hash,
        file_name=file_name,
        mime_type=mime_type,
        expire=expire,
    )
    if url is not None:
        return redirect(url)
    try:
        local_path = archive.load_file(content_hash)
        if local_path is None:
            return Response(status=404)
        return send_file(
            str(local_path),
            as_attachment=True,
            conditional=True,
            download_name=file_name,
            mimetype=mime_type,
        )
    finally:
        archive.cleanup_file(content_hash)
