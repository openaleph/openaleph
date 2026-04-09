"""Content-aware ETag computation for the object resolver.

Each cached object has a content ETag derived either from a custom
function (registered via :func:`register_etag`) or from a default
content hash of the pydantic model's JSON dump. The ETag is used by
HTTP cache validators on the API side — when an ETag changes the
browser revalidates with ``If-None-Match`` and gets fresh content;
when it doesn't change the server returns 304.

The default content hash is correct for every schema but expensive on
the hot path. Heavy resources (``EntitySchema``, ``CollectionSchema``,
the ``Dated*`` family) should register custom ETag functions sourced
from their backing-store version metadata (ES ``_seq_no`` /
``_primary_term``, SQLA ``updated_at``).
"""

import base64
from hashlib import blake2b
from typing import Type

from pydantic import BaseModel

from aleph.logic.resolver.registry import get_etag_fn

# 8 bytes = 64 bits of collision space — plenty for an ETag whose only
# job is to change when the content changes. The url-safe base64
# encoding (with padding stripped) packs that into 11 characters,
# vs 16 for hex, so the wire format stays compact.
ETAG_DIGEST_SIZE = 8


def _short_hash(data: bytes) -> str:
    """Compact content hash: 8-byte blake2b → 11-char url-safe base64."""
    digest = blake2b(data, digest_size=ETAG_DIGEST_SIZE).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def compute_etag(cls: Type[BaseModel], obj: BaseModel) -> str:
    """Compute a content ETag for a fetched object.

    Returns an HTTP-quoted ETag string (per RFC 7232) so the value can
    be passed straight into a ``Response.set_etag()`` call without
    further processing.

    If the registry has a custom ETag function for ``cls`` (registered
    via :func:`register_etag`), use it. Otherwise hash the model's
    JSON dump and pack the result into 11 base64 chars (see
    :func:`_short_hash`).
    """
    custom = get_etag_fn(cls)
    if custom is not None:
        return custom(obj)
    return f'"{_short_hash(obj.model_dump_json().encode())}"'
