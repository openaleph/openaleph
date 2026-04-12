import csv
import io
import logging
import string
from urllib.parse import urlparse

import orjson
from banal import as_bool
from flask import Response, render_template, request
from normality import stringify
from servicelayer.jobs import Job
from werkzeug.exceptions import Forbidden, NotFound

from aleph.util import json_default

log = logging.getLogger(__name__)
CALLBACK_VALID = string.ascii_letters + string.digits + "_"


def require(*predicates):
    """Check if a user is allowed a set of predicates."""
    for predicate in predicates:
        if not predicate:
            raise Forbidden("Sorry, you're not permitted to do this!")


def obj_or_404(obj):
    """Raise a 404 error if the given object is None."""
    if obj is None:
        raise NotFound()
    return obj


def get_flag(name, default=False):
    return as_bool(request.args.get(name), default=default)


def get_session_id():
    role_id = stringify(request.authz.id) or "anonymous"
    session_id = stringify(request._session_id)
    session_id = session_id or Job.random_id()
    return "%s:%s" % (role_id, session_id)


def get_url_path(url):
    try:
        return urlparse(url)._replace(netloc="", scheme="").geturl() or "/"
    except Exception:
        return "/"


def jsonify(obj, status=200, headers=None):
    """Serialize to JSON and also dump from the given schema."""
    data = orjson.dumps(obj, default=json_default)
    mimetype = "application/json"
    if "callback" in request.args:
        cb = request.args.get("callback")
        cb = "".join((c for c in cb if c in CALLBACK_VALID))
        data = b"%s && %s(%s)" % (cb.encode(), cb.encode(), data)
        mimetype = "application/javascript"
    return Response(data, headers=headers, status=status, mimetype=mimetype)


def stream_ijson(iterable):
    """Stream JSON line-based data."""

    def _generate_stream():
        for row in iterable:
            row.pop("_index", None)
            yield orjson.dumps(row, default=json_default)
            yield b"\n"

    return Response(_generate_stream(), mimetype="application/json+stream")


def stream_csv(iterable):
    """Stream JSON line-based data."""

    def _generate_stream():
        for row in iterable:
            values = []
            for value in row:
                values.append(stringify(value) or "")
            buffer = io.StringIO()
            writer = csv.writer(buffer, dialect="excel", delimiter=",")
            writer.writerow(values)
            yield buffer.getvalue()

    return Response(_generate_stream(), mimetype="text_csv")


def render_xml(template, **kwargs):
    data = render_template(template, **kwargs)
    return Response(data, mimetype="text/xml")
