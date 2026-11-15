import logging

from flask import Blueprint, request
from flask_babel import gettext
from openaleph_search.query.queries import PercolatorQuery
from werkzeug.exceptions import BadRequest

from aleph.search import (
    SearchQueryParser,
)
from aleph.search.result import get_query_result
from aleph.settings import SETTINGS
from aleph.views.serializers import (
    EntitySerializer,
)
from aleph.views.util import (
    require,
)

log = logging.getLogger(__name__)
blueprint = Blueprint("beta_api", __name__)


@blueprint.route("/api/2/beta/percolate", methods=["POST"])
def percolate_text():
    """
    ---
    post:
      summary: Percolate caller-supplied text against stored queries
      description: >-
        The text-first counterpart to `GET /entities/<entity_id>/percolate`:
        rather than percolating a Document already ingested into the
        instance, accept arbitrary text in the request body and return
        the entities whose stored percolator queries it matches. This
        lets an external caller ask "which of your entities are
        mentioned in this text?" in a single call — without ingesting a
        throwaway document into a writeable collection first.

        The text goes in the JSON body; the standard entity search
        filters (`filter:schema`, `filter:dataset`, `filter:countries`,
        `filter:topics`, `highlight`, `limit`, `offset`, `dehydrate`,
        …) are taken from the query string exactly as the entity-scoped
        variant reads them. The response is the same `EntitiesResponse`
        shape, ranked by percolator `_score`.

        Login is required (as for `/screening`), and the body text is
        capped at `PERCOLATE_MAX_TEXT` characters (default 100 000) —
        the abuse budget analogous to screening's name budget, since a
        percolate document is matched against every stored query.
      parameters:
      - in: query
        name: "filter:{field}"
        description: Filter the percolated entity set by field.
        schema:
          type: string
      - in: query
        name: limit
        description: Max entities to return.
        schema:
          type: integer
      - in: query
        name: highlight
        description: Return surface-form fragments on each hit.
        schema:
          type: boolean
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [text]
              properties:
                text:
                  type: string
                  description: The text to percolate against stored queries.
      responses:
        '200':
          description: Entities whose stored queries match the supplied text
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/EntitiesResponse'
        '400':
          description: Missing/empty `text`, or text over the size cap
      tags:
      - Entity
    """
    require(request.authz.logged_in)
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        raise BadRequest(gettext("A non-empty `text` string is required."))
    if len(text) > SETTINGS.PERCOLATE_MAX_TEXT:
        raise BadRequest(
            gettext("Text exceeds the %(max)d-character percolation limit.")
            % {"max": SETTINGS.PERCOLATE_MAX_TEXT}
        )
    parser = SearchQueryParser(request.args, auth=request.authz.search_auth)
    try:
        result = get_query_result(PercolatorQuery, request, parser=parser, text=text)
    except ValueError as err:
        raise BadRequest(str(err))
    return EntitySerializer.jsonify_result(result)
