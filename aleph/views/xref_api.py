import logging

from flask import Blueprint, request
from followthemoney import model
from nomenklatura.judgement import Judgement
from rigour.mime.types import XLSX
from werkzeug.exceptions import BadRequest, Forbidden, NotFound

from aleph.logic.export import create_export
from aleph.logic.xref.canonical import resolve_entity_or_canonical
from aleph.logic.xref.resolver import get_resolver
from aleph.procrastinate.queues import OP_EXPORT_XREF, queue_export_xref, queue_xref
from aleph.search.query import XrefQuery
from aleph.search.result import get_query_result
from aleph.views import resources
from aleph.views.serializers import XrefSerializer
from aleph.views.util import (
    jsonify,
    parse_request,
    require,
)

blueprint = Blueprint("xref_api", __name__)
log = logging.getLogger(__name__)


@blueprint.route("/api/2/collections/<int:collection_id>/xref", methods=["GET"])
def index(collection_id):
    """
    ---
    get:
      summary: Fetch cross-reference results
      description: >-
        Fetch cross-reference matches for entities in the collection
        with id `collection_id`. Now bidirectional: shows edges involving
        the collection on either side.
      parameters:
      - in: path
        name: collection_id
        required: true
        schema:
          type: integer
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                type: object
                allOf:
                - $ref: '#/components/schemas/QueryResponse'
                properties:
                  results:
                    type: array
                    items:
                      $ref: '#/components/schemas/XrefResponse'
      tags:
      - Xref
      - Collection
    """
    require(request.authz.can(collection_id, request.authz.READ))
    result = get_query_result(XrefQuery, request, collection_id=collection_id)
    # Judgement is directly on each edge document from ES
    return XrefSerializer.jsonify_result(result)


@blueprint.route("/api/2/collections/<int:collection_id>/xref", methods=["POST"])
def generate(collection_id):
    """
    ---
    post:
      summary: Generate cross-reference matches
      description: >
        Generate cross-reference matches for entities in a collection.
      parameters:
      - in: path
        name: collection_id
        required: true
        schema:
          type: integer
      responses:
        '202':
          content:
            application/json:
              schema:
                properties:
                  status:
                    description: accepted
                    type: string
                type: object
          description: Accepted
      tags:
      - Xref
      - Collection
    """
    collection = resources.get_db_collection(collection_id, request.authz.WRITE)
    queue_xref(collection)
    return jsonify({"status": "accepted"}, status=202)


@blueprint.route("/api/2/collections/<int:collection_id>/xref.xlsx", methods=["POST"])
def export(collection_id):
    """
    ---
    post:
      summary: Download cross-reference results
      description: Download results of cross-referencing as an Excel file
      parameters:
      - in: path
        name: collection_id
        required: true
        schema:
          type: integer
      responses:
        '202':
          description: Accepted
      tags:
      - Xref
      - Collection
    """
    collection = resources.get_db_collection(collection_id, request.authz.READ)
    label = "%s - Cross-reference results" % collection.label
    export = create_export(
        operation=OP_EXPORT_XREF,
        role_id=request.authz.id,
        label=label,
        collection=collection,
        mime_type=XLSX,
    )
    queue_export_xref(collection, export.id)
    return ("", 202)


@blueprint.route("/api/2/xref/_decide", methods=["POST"])
def decide():
    """
    ---
    post:
      summary: Make a pairwise judgement between an entity and a match.
      description: >
        This lets a user decide if they think a given xref match is a true or
        false match. Stores the decision as an edge in the resolver.
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Pairwise'
      responses:
        '200':
          content:
            application/json:
              schema:
                properties:
                  status:
                    description: ok
                    type: string
                  canonical_id:
                    description: canonical ID for the cluster
                    type: string
                type: object
          description: OK
      tags:
      - Xref
      - Collection
    """
    data = parse_request("Pairwise")
    entity_id = data["entity_id"]
    match_id = data["match_id"]
    if entity_id == match_id:
        raise BadRequest("entity_id and match_id must be different")
    judgement = Judgement(data["judgement"])
    log.info(
        "decide: entity_id=%s match_id=%s judgement=%s", entity_id, match_id, judgement
    )

    # Resolve each ID: real entity → index lookup; canonical → cluster lookup
    entity_info = resolve_entity_or_canonical(entity_id, request.authz.search_auth)
    if entity_info is None:
        raise NotFound("Entity not found: %s" % entity_id)
    match_info = resolve_entity_or_canonical(match_id, request.authz.search_auth)
    if match_info is None:
        raise NotFound("Entity not found: %s" % match_id)

    # Auth: user must have WRITE on at least one collection from either side
    all_cids = entity_info["collection_ids"] | match_info["collection_ids"]
    if not any(request.authz.can(c, request.authz.WRITE) for c in all_cids):
        raise Forbidden("Sorry, you're not permitted to do this!")

    # Validate schema compatibility for POSITIVE judgements
    if judgement == Judgement.POSITIVE:
        if entity_info["schema"] and match_info["schema"]:
            model.common_schema(entity_info["schema"], match_info["schema"])

    xref_resolver = get_resolver(sync=True)
    canonical = xref_resolver.decide(
        entity_id,
        match_id,
        judgement,
        user=str(request.authz.role.foreign_id),
        source_collection_id=entity_info["collection_ids"],
        target_collection_id=match_info["collection_ids"],
    )

    return jsonify(
        {"status": "ok", "canonical_id": canonical.id},
        status=200,
    )
