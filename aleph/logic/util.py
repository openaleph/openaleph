from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urljoin

import jwt
from followthemoney import EntityProxy, model
from followthemoney.compare import _normalize_names
from normality import ascii_text

from aleph.core import url_for
from aleph.settings import SETTINGS

ALGORITHM = "HS256"
DECODE = [ALGORITHM]

# content hash, file name, mime type, expiration, role id, collection id
ArchiveToken = tuple[
    str | None, str | None, str | None, datetime, int | None, int | None
]


def latin_alt(value):
    """Make a latin version of a string and return if it differs
    from the input."""
    trans_value = ascii_text(value)
    if trans_value.lower() != value.lower():
        return trans_value


def ui_url(resource, id=None, _relative=False, **query):
    """Make a UI link."""
    if id is not None:
        resource = "%s/%s" % (resource, id)
    url = "/" if _relative else SETTINGS.APP_UI_URL
    url = urljoin(url, resource)
    query = [(q, v) for q, v in query.items() if v is not None]
    query_string = urlencode(query, doseq=True)
    if len(query_string):
        url = f"{url}?{query_string}"
    return url


def collection_url(collection_id=None, **query):
    return ui_url("datasets", id=collection_id, **query)


def entityset_url(entityset_id=None, **query):
    return ui_url("sets", id=entityset_id, **query)


def entity_url(entity_id=None, **query):
    return ui_url("entities", id=entity_id, **query)


def archive_url(
    content_hash: str | None,
    file_name: str | None = None,
    mime_type: str | None = None,
    expire: datetime | None = None,
    role_id: int | None = None,
    collection_id: int | None = None,
) -> str | None:
    """Create an access authorization link for an archive blob."""
    if content_hash is None:
        return None
    if expire is None:
        expire = datetime.utcnow() + timedelta(days=1)
    payload: dict[str, Any] = {
        "c": content_hash,
        "f": file_name,
        "m": mime_type,
        "exp": expire,
    }
    if role_id is not None:
        payload["r"] = role_id
    if collection_id is not None:
        # the collection decides which archive backend serves the blob
        payload["k"] = collection_id
    token = jwt.encode(payload, SETTINGS.SECRET_KEY, algorithm=ALGORITHM)
    return url_for("archive_api.retrieve", _query=[("token", token)])


def archive_token(token: str) -> ArchiveToken:
    token = jwt.decode(token, key=SETTINGS.SECRET_KEY, algorithms=DECODE, verify=True)
    expire = datetime.utcfromtimestamp(token["exp"])
    return (
        token.get("c"),
        token.get("f"),
        token.get("m"),
        expire,
        token.get("r"),
        token.get("k"),
    )


def entity_fingerprints(entity: EntityProxy) -> set[str]:
    """Get the set of entity name fingerprints"""
    # FIXME
    return set(_normalize_names(entity.schema, entity.names))


def make_fingerprint(value: str) -> str | None:
    """Mimic `fingerprints.generate`"""
    # FIXME
    for fp in _normalize_names(model["LegalEntity"], [value]):
        return fp
