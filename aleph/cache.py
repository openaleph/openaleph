"""Minimal Redis cache retained for auth/OAuth session state.

All model-level caching (entities, collections, roles, stats, etc.)
has moved to the typed resolver in ``aleph.logic.resolver``. This
module stays only because the auth layer (``aleph/authz.py``) and
OAuth session management (``aleph/views/sessions_api.py``) use
Redis-specific operations (hash maps, prefix scan) that don't fit
the resolver's key-value-per-model pattern.

Once auth moves to its own store (or to Django sessions), this
module can be deleted.
"""

import logging

import orjson
from servicelayer import settings
from servicelayer.cache import make_key

from aleph.util import json_default

log = logging.getLogger(__name__)


class Cache(object):
    def __init__(self, kv, expires=None, prefix=None):
        self.kv = kv
        self.expires = expires or settings.REDIS_LONG
        self.prefix = prefix

    def key(self, *parts):
        return make_key(self.prefix, *parts)

    def set(self, key, value, expires=None):
        expires = expires or self.expires
        self.kv.set(key, value, ex=expires)

    def set_complex(self, key, value, expires=None):
        value = orjson.dumps(value, default=json_default)
        return self.set(key, value, expires=expires)

    def get(self, key):
        return self.kv.get(key)

    def get_complex(self, key):
        value = self.get(key)
        if value is not None:
            return orjson.loads(value)

    def delete(self, key):
        self.kv.delete(key)

    def flush(self, prefix=None):
        prefix = prefix or self.prefix
        keys = []
        for key in self.kv.scan_iter(match="%s*" % prefix):
            log.info("Flush: %s", key)
            keys.append(key)
            if len(keys) > 0 and len(keys) % 1000 == 0:
                self.kv.delete(*keys)
                keys = []
        if len(keys) > 0:
            self.kv.delete(*keys)
