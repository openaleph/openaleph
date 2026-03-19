"""
Canonical cluster API. Replaces profiles_api.py.

Provides endpoints for viewing merged entity clusters from the resolver.
"""

import logging

from flask import Blueprint, request

from aleph.logic.expand import entity_tags, expand_proxies
from aleph.logic.xref.canonical import get_canonical_cluster
from aleph.logic.xref.compare import compare_entities
from aleph.model import Judgement
from aleph.search import MatchQuery, QueryParser
from aleph.search.result import get_query_result
from aleph.settings import SETTINGS
from aleph.util import make_entity_proxy
from aleph.views.context import tag_request
from aleph.views.serializers import CanonicalSerializer, SimilarSerializer
from aleph.views.util import jsonify, obj_or_404

blueprint = Blueprint("canonical_api", __name__)
log = logging.getLogger(__name__)


@blueprint.route("/api/2/canonical/<canonical_id>", methods=["GET"])
def view(canonical_id):
    """
    ---
    get:
      summary: Retrieve a canonical cluster
      description: >-
        Get a canonical cluster with constituent entities and the merged pseudo entity.
      parameters:
      - in: path
        name: canonical_id
        required: true
        schema:
          type: string
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Canonical'
      tags:
      - Canonical
    """
    cluster = obj_or_404(get_canonical_cluster(canonical_id, request.authz.search_auth))
    return CanonicalSerializer.jsonify(cluster)


@blueprint.route("/api/2/canonical/<canonical_id>/tags", methods=["GET"])
def tags(canonical_id):
    """
    ---
    get:
      summary: Get canonical cluster tags
      parameters:
      - in: path
        name: canonical_id
        required: true
        schema:
          type: string
      responses:
        '200':
          description: OK
      tags:
      - Canonical
    """
    cluster = obj_or_404(get_canonical_cluster(canonical_id, request.authz.search_auth))
    tag_request()
    results = entity_tags(cluster["merged"], request.authz)
    return jsonify({"status": "ok", "total": len(results), "results": results})


@blueprint.route("/api/2/canonical/<canonical_id>/similar", methods=["GET"])
def similar(canonical_id):
    """
    ---
    get:
      summary: Get similar entities
      parameters:
      - in: path
        name: canonical_id
        required: true
        schema:
          type: string
      responses:
        '200':
          description: Returns a list of entities
      tags:
      - Canonical
    """
    cluster = obj_or_404(get_canonical_cluster(canonical_id, request.authz.search_auth))
    tag_request()
    entity = cluster["merged"]
    result = get_query_result(
        MatchQuery, request, entity=entity, exclude=entity.referents
    )
    entities = list(result.results)
    result.results = []
    for obj in entities:
        item = {
            "score": compare_entities(entity, make_entity_proxy(obj))[0],
            "judgement": Judgement.NO_JUDGEMENT,
            "collection_id": None,
            "entity": obj,
        }
        result.results.append(item)
    return SimilarSerializer.jsonify_result(result)


@blueprint.route("/api/2/canonical/<canonical_id>/expand", methods=["GET"])
def expand(canonical_id):
    """
    ---
    get:
      summary: Expand the canonical cluster to get its adjacent entities
      parameters:
      - in: path
        name: canonical_id
        required: true
        schema:
          type: string
      responses:
        '200':
          description: OK
      tags:
      - Canonical
    """
    cluster = obj_or_404(get_canonical_cluster(canonical_id, request.authz.search_auth))
    tag_request()
    parser = QueryParser(
        request.args, request.authz, max_limit=SETTINGS.MAX_EXPAND_ENTITIES
    )
    properties = parser.filters.get("property")
    results = expand_proxies(  # NEEDS FIX
        cluster["entities"],
        properties=properties,
        authz=request.authz,
        limit=parser.limit,
    )
    result = {
        "status": "ok",
        "total": sum(result["count"] for result in results),
        "results": results,
    }
    return jsonify(result)


@blueprint.route("/api/2/entities/<entity_id>/canonical", methods=["GET"])
def entity_canonical(entity_id):
    """
    ---
    get:
      summary: Get the canonical cluster for an entity
      description: >-
        Resolve any entity to its canonical cluster.
      parameters:
      - in: path
        name: entity_id
        required: true
        schema:
          type: string
      responses:
        '200':
          description: OK
      tags:
      - Canonical
    """
    cluster = obj_or_404(get_canonical_cluster(entity_id, request.authz.search_auth))
    return CanonicalSerializer.jsonify(cluster)
