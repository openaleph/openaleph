import csv
import io
import logging
import string
from typing import TypeVar
from urllib.parse import urlparse

import orjson
from banal import as_bool
from flask import Response, render_template, request
from normality import stringify
from pydantic import BaseModel, ValidationError
from servicelayer.jobs import Job
from werkzeug.exceptions import BadRequest, Forbidden, NotFound

from aleph.util import json_default

T = TypeVar("T", bound=BaseModel)

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


def validate_request(schema_cls: type[T], data: dict | None = None) -> T:
    """Validate request data against a pydantic schema, raising 400 on failure.

    When *data* is ``None`` the function reads from the current Flask
    request, transparently handling both JSON and form-encoded bodies.
    """
    if data is None:
        data = (
            request.get_json() if request.is_json else request.form.to_dict(flat=True)
        )
    try:
        return schema_cls.model_validate(data)
    except ValidationError as e:
        errors = {}
        for err in e.errors():
            path = ".".join(str(loc) for loc in err["loc"])
            errors[path] = err["msg"]
        resp = jsonify(
            {
                "status": "error",
                "errors": errors,
                "message": "Error during data validation",
            },
            status=400,
        )
        raise BadRequest(response=resp)


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
