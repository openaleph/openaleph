import logging

from flask import Blueprint, request
from followthemoney import model
from nomenklatura.judgement import Judgement
from rigour.mime.types import XLSX
from werkzeug.exceptions import Forbidden

from aleph.logic.export import create_export
from aleph.logic.xref.resolver import get_resolver
from aleph.procrastinate.queues import OP_EXPORT_XREF, queue_export_xref, queue_xref
from aleph.search.query import XrefQuery
from aleph.search.result import get_query_result
from aleph.views.serializers import XrefSerializer
from aleph.views.util import (
    get_db_collection,
    get_index_collection,
    get_index_entity,
    jsonify,
    parse_request,
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
    get_index_collection(collection_id, request.authz.READ)
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
    collection = get_db_collection(collection_id, request.authz.WRITE)
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
    collection = get_db_collection(collection_id, request.authz.READ)
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
    entity = get_index_entity(data.get("entity_id"))
    collection = get_db_collection(entity["collection_id"], request.authz.READ)
    match = get_index_entity(data.get("match_id"))
    match_collection = get_db_collection(match["collection_id"], request.authz.READ)

    # FIXME the permission check currently is if the user can write to any of
    # the two collections:
    if not (
        request.authz.can(collection, request.authz.WRITE)
        or request.authz.can(match_collection, request.authz.WRITE)
    ):
        raise Forbidden("Sorry, you're not permitted to do this!")

    judgement_str = data.get("judgement")
    judgement = Judgement(judgement_str)

    # Validate schema compatibility for POSITIVE judgements
    if judgement == Judgement.POSITIVE:
        model.common_schema(entity.get("schema"), match.get("schema"))

    xref_resolver = get_resolver()
    canonical = xref_resolver.decide(
        entity["id"],
        match["id"],
        judgement,
        user=str(request.authz.role.foreign_id),
        source_collection_id=collection.id,
        target_collection_id=match_collection.id,
    )

    return jsonify(
        {"status": "ok", "canonical_id": canonical.id},
        status=200,
    )
