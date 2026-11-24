import json
import re
import time
from unittest import mock

from werkzeug.exceptions import Unauthorized

from aleph import scoped_tokens
from aleph.authz import Authz
from aleph.core import cache, db
from aleph.index.util import index_entity
from aleph.logic import xref
from aleph.logic.collections import delete_collection, update_collection
from aleph.logic.roles import delete_role, rotate_api_key, update_role
from aleph.model import Permission
from aleph.settings import SETTINGS
from aleph.tests.util import JSON, TestCase
from aleph.views.base_api import _metadata_locale
from aleph.views.context import SCOPED_TOKEN_ENDPOINTS

TOKENS = "/api/2/tokens"

# The allowlist, repeated on purpose: widening what a scoped token may reach
# has to be a visible change in this file as well.
EXPECTED_ENDPOINTS = {
    "base_api.metadata",
    "collections_api.index",
    "collections_api.view",
    "collections_api.bulk",
    "ingest_api.ingest_upload",
    "entities_api.index",
    "entities_api.match",
    "entities_api.create",
    "entities_api.view",
    "entities_api.similar",
    "entities_api.tags",
    "entities_api.update",
    "entities_api.delete",
    "entities_api.entitysets",
    "entitysets_api.index",
    "entitysets_api.create",
    "entitysets_api.view",
    "entitysets_api.update",
    "entitysets_api.delete",
    "entitysets_api.entities_index",
    "entitysets_api.entities_update",
    "entitysets_api.item_index",
    "entitysets_api.item_update",
    "xref_api.index",
    "bulk_api.entities",
    "archive_api.resolve",
    "archive_api.retrieve",
}


class ScopedTokenTestCase(TestCase):
    """An owner who can write to collections A and B, read RO, and has no
    access to X. Most tests use a token limited to A and check B."""

    def setUp(self):
        super().setUp()
        xref.SCORE_CUTOFF = 0.01
        self.max_expire = SETTINGS.SCOPED_TOKEN_MAX_EXPIRE
        self.owner = self.create_user(foreign_id="owner", email="owner@example.org")
        self.other = self.create_user(foreign_id="other")
        self.headers = {"Authorization": self.owner.api_key}
        self.col_a = self.create_collection(
            creator=self.owner, foreign_id="scoped_a", label="Collection A"
        )
        self.col_b = self.create_collection(
            creator=self.owner, foreign_id="scoped_b", label="Collection B"
        )
        self.col_ro = self.create_collection(
            creator=self.other, foreign_id="scoped_ro", label="Collection RO"
        )
        self.col_x = self.create_collection(
            creator=self.other, foreign_id="scoped_x", label="Collection X"
        )
        self.grant(self.col_ro, self.owner, True, False)
        person = {"name": "Leeta", "email": "leeta@example.org"}
        self.ent_a = self.create_entity(
            {"schema": "Person", "properties": person}, self.col_a
        )
        self.ent_b = self.create_entity(
            {"schema": "Person", "properties": person}, self.col_b
        )
        self.ent_x = self.create_entity(
            {"schema": "Person", "properties": person}, self.col_x
        )
        db.session.commit()
        for entity in (self.ent_a, self.ent_b, self.ent_x):
            index_entity(entity)
        self.id_a = self.col_a.ns.sign(self.ent_a.id)
        self.id_b = self.col_b.ns.sign(self.ent_b.id)
        # Start without tokens or cached access lists, also when the cache
        # is a real Redis that outlives a single test.
        cache.flush(prefix=cache.key(scoped_tokens.STORE))
        Authz.flush()

    def tearDown(self):
        SETTINGS.SCOPED_TOKEN_MAX_EXPIRE = self.max_expire
        SETTINGS.MAINTENANCE = False
        _metadata_locale.cache_clear()
        super().tearDown()

    def create(self, readable, writeable=(), headers=None, **extra):
        data = {
            "label": "test token",
            "read": [c.id for c in readable],
            "write": [c.id for c in writeable],
            "expires_in": 3600,
        }
        data.update(extra)
        return self.client.post(TOKENS, json=data, headers=headers or self.headers)

    def token(self, readable, writeable=(), **kwargs):
        res = self.create(readable, writeable, **kwargs)
        assert res.status_code == 200, res.json
        return res.json

    def scoped(self, readable, writeable=(), **kwargs):
        token = self.token(readable, writeable, **kwargs)["token"]
        return {"Authorization": "ApiKey %s" % token}

    def record_key(self, token):
        return scoped_tokens._key(self.owner.id, token["id"])

    def assert_ok(self, headers):
        res = self.client.get("/api/2/collections/%s" % self.col_a.id, headers=headers)
        assert res.status_code == 200, res.json

    def assert_unauthorized(self, headers):
        res = self.client.get("/api/2/collections/%s" % self.col_a.id, headers=headers)
        assert res.status_code == 401, (res.status_code, res.data)


class ScopedTokenManageTestCase(ScopedTokenTestCase):
    def test_create_list_revoke(self):
        res = self.client.get(TOKENS, headers=self.headers)
        assert res.status_code == 200, res
        assert res.json["total"] == 0, res.json

        token = self.token([self.col_a, self.col_b], [self.col_a])
        assert token["token"].startswith("scoped.%s." % self.owner.id), token
        assert token["read"] == [self.col_a.id, self.col_b.id], token
        assert token["write"] == [self.col_a.id], token
        assert token["label"] == "test token", token
        headers = {"Authorization": "ApiKey %s" % token["token"]}
        self.assert_ok(headers)

        # The secret is shown once: listing never returns it.
        secret = token["token"].split(".")[-1]
        res = self.client.get(TOKENS, headers=self.headers)
        assert res.json["total"] == 1, res.json
        listed = res.json["results"][0]
        assert listed["id"] == token["id"], listed
        assert "token" not in listed and "secret_hash" not in listed, listed
        assert secret not in res.get_data(as_text=True)

        # Another user can neither see nor revoke it.
        _, other = self.login(foreign_id="other")
        res = self.client.get(TOKENS, headers=other)
        assert res.json["total"] == 0, res.json
        url = "%s/%s" % (TOKENS, token["id"])
        res = self.client.delete(url, headers=other)
        assert res.status_code == 404, res
        self.assert_ok(headers)

        res = self.client.delete(url, headers=self.headers)
        assert res.status_code == 204, res
        self.assert_unauthorized(headers)
        res = self.client.delete(url, headers=self.headers)
        assert res.status_code == 404, res
        res = self.client.get(TOKENS, headers=self.headers)
        assert res.json["total"] == 0, res.json

    def test_manage_requires_full_sign_in(self):
        res = self.client.get(TOKENS)
        assert res.status_code == 403, res
        res = self.client.post(TOKENS, json={})
        assert res.status_code == 403, res

        token = self.token([self.col_a], [self.col_a])
        scoped = {"Authorization": "ApiKey %s" % token["token"]}
        res = self.client.get(TOKENS, headers=scoped)
        assert res.status_code == 403, res
        res = self.create([self.col_a], headers=scoped)
        assert res.status_code == 403, res
        res = self.client.delete("%s/%s" % (TOKENS, token["id"]), headers=scoped)
        assert res.status_code == 403, res
        self.assert_ok(scoped)
        res = self.client.get(TOKENS, headers=self.headers)
        assert res.json["total"] == 1, res.json

        # A session works like the API key.
        session = Authz.from_role(self.owner).to_token()
        session = {"Authorization": "Token %s" % session}
        res = self.create([self.col_a], headers=session)
        assert res.status_code == 200, res.json

    def test_create_validation(self):
        res = self.create([], [])
        assert res.status_code == 400, res.json
        res = self.create([], [self.col_a])
        assert res.status_code == 400, res.json
        # Writing implies reading and has to say so.
        res = self.create([self.col_b], [self.col_a])
        assert res.status_code == 400, res.json
        # Owner can read RO but not write to it.
        res = self.create([self.col_ro], [self.col_ro])
        assert res.status_code == 400, res.json
        # No access, and a collection that does not exist: same answer.
        res = self.create([self.col_a, self.col_x])
        assert res.status_code == 400, res.json
        message = res.json["message"]
        res = self.create([self.col_a], read=[self.col_a.id, 999999])
        assert res.status_code == 400, res.json
        assert res.json["message"] == message, res.json

        for expires_in in (0, -1, 59, "3600", None, 1.5, True):
            res = self.create([self.col_a], expires_in=expires_in)
            assert res.status_code == 400, (expires_in, res.json)
        for label in ("", None, "x" * 101, 5):
            res = self.create([self.col_a], label=label)
            assert res.status_code == 400, (label, res.json)
        for read in ("1", [str(self.col_a.id)], [True], [0], [self.col_a.id] * 2):
            res = self.create([], read=read)
            assert res.status_code == 400, (read, res.json)
        # Unknown fields are refused rather than ignored.
        for extra in ({"is_admin": True}, {"role_id": 1}, {"roles": [1]}):
            res = self.create([self.col_a], **extra)
            assert res.status_code == 400, (extra, res.json)
        data = {"read": [self.col_a.id], "expires_in": 60}
        res = self.client.post(TOKENS, json=data, headers=self.headers)
        assert res.status_code == 400, res.json

        res = self.client.get(TOKENS, headers=self.headers)
        assert res.json["total"] == 0, res.json

    def test_lifetime_is_capped_not_shortened(self):
        res = self.create([self.col_a], expires_in=self.max_expire)
        assert res.status_code == 200, res.json
        res = self.create([self.col_a], expires_in=self.max_expire + 1)
        assert res.status_code == 400, res.json
        res = self.client.get(TOKENS, headers=self.headers)
        assert res.json["total"] == 1, res.json

        SETTINGS.SCOPED_TOKEN_MAX_EXPIRE = 120
        res = self.create([self.col_a], expires_in=121)
        assert res.status_code == 400, res.json
        token = self.token([self.col_a], expires_in=120)
        ttl = cache.kv.ttl(self.record_key(token))
        assert 0 < ttl <= 120, ttl

    def test_token_count_is_limited(self):
        with mock.patch.object(scoped_tokens, "MAX_TOKENS_PER_ROLE", 2):
            self.token([self.col_a])
            self.token([self.col_a])
            res = self.create([self.col_a])
            assert res.status_code == 400, res.json

    def test_maintenance_blocks_creation_but_not_revocation(self):
        token = self.token([self.col_a])
        SETTINGS.MAINTENANCE = True
        res = self.create([self.col_a])
        assert res.status_code == 403, res.json
        url = "%s/%s" % (TOKENS, token["id"])
        res = self.client.delete(url, headers=self.headers)
        assert res.status_code == 204, res

    def test_secret_is_not_stored_or_logged(self):
        with self.assertLogs(level="DEBUG") as logs:
            token = self.token([self.col_a])
            headers = {"Authorization": "ApiKey %s" % token["token"]}
            self.assert_ok(headers)
            self.assert_unauthorized({"Authorization": token["token"] + "x"})
            res = self.client.get("/api/2/roles/%s" % self.owner.id, headers=headers)
            assert res.status_code == 403, res
        secret = token["token"].split(".")[-1]
        assert len(secret) >= 43, len(secret)
        for record in logs.records:
            assert secret not in record.getMessage(), record.getMessage()
        for key in cache.kv.scan_iter():
            assert secret not in str(key), key
            if cache.kv.type(key) in ("string", b"string"):
                assert secret not in str(cache.kv.get(key)), key
        record = cache.get_complex(self.record_key(token))
        assert re.match("^[0-9a-f]{64}$", record["secret_hash"]), record

    def test_metadata_and_kill_switch(self):
        _metadata_locale.cache_clear()
        res = self.client.get("/api/2/metadata")
        auth = res.json["auth"]
        assert auth["scoped_tokens_uri"].endswith(TOKENS), auth
        assert auth["scoped_tokens_max_expire"] == self.max_expire, auth

        headers = self.scoped([self.col_a])
        self.assert_ok(headers)
        SETTINGS.SCOPED_TOKEN_MAX_EXPIRE = 0
        _metadata_locale.cache_clear()
        res = self.client.get("/api/2/metadata")
        assert "scoped_tokens_uri" not in res.json["auth"], res.json["auth"]
        self.assert_unauthorized(headers)
        res = self.create([self.col_a])
        assert res.status_code == 403, res.json
        res = self.client.get(TOKENS, headers=self.headers)
        assert res.status_code == 403, res.json


class ScopedTokenCredentialTestCase(ScopedTokenTestCase):
    def test_header_only_never_url(self):
        token = self.token([self.col_a])["token"]
        self.assert_ok({"Authorization": token})
        self.assert_ok({"Authorization": "ApiKey %s" % token})
        url = "/api/2/collections/%s" % self.col_a.id
        for value in (token, "ApiKey %s" % token):
            res = self.client.get(url, query_string={"api_key": value})
            assert res.status_code == 401, (value, res.status_code)
        # Not a session either.
        self.assert_unauthorized({"Authorization": "Token %s" % token})
        # The owner's API key is still accepted in the URL, as before.
        res = self.client.get(url, query_string={"api_key": self.owner.api_key})
        assert res.status_code == 200, res

    def test_malformed_credentials(self):
        token = self.token([self.col_a])
        prefix, role_id, key_id, secret = token["token"].split(".")
        theirs = self.token([self.col_x], headers={"Authorization": self.other.api_key})
        _, their_role, their_key, their_secret = theirs["token"].split(".")
        bad = [
            "scoped.",
            "scoped...",
            "scoped.%s.%s" % (role_id, key_id),
            "scoped.%s.%s." % (role_id, key_id),
            "scoped.%s.%s.%s" % (role_id, key_id, secret[:-1]),
            "scoped.%s.%s.%sA" % (role_id, key_id, secret[:-1].rstrip("A")),
            "scoped.%s.%s.%s.x" % (role_id, key_id, secret),
            "scoped.%s.%s.%s" % (role_id, key_id.upper(), secret),
            "scoped.0%s.%s.%s" % (role_id, key_id, secret),
            "scoped.%s.%s.%s" % (role_id, "*", secret),
            "scoped.%s.%s.%s" % ("*", key_id, secret),
            "scoped.%s.%s.%s" % (role_id, key_id, "*" * 43),
            "scoped.%s.%s.%s" % (role_id, key_id, "a" * 5000),
            # Mixing the parts of two valid tokens.
            "scoped.%s.%s.%s" % (their_role, key_id, secret),
            "scoped.%s.%s.%s" % (role_id, their_key, secret),
            "scoped.%s.%s.%s" % (role_id, key_id, their_secret),
            "scoped.%s.%s.%s" % (their_role, their_key, secret),
            "Scoped.%s.%s.%s" % (role_id, key_id, secret),
        ]
        for credential in bad:
            for value in (credential, "ApiKey %s" % credential):
                res = self.client.get(
                    "/api/2/metadata", headers={"Authorization": value}
                )
                assert res.status_code == 401, (credential, res.status_code)
        self.assert_ok({"Authorization": token["token"]})

    def test_broken_records_fail_closed(self):
        token = self.token([self.col_a, self.col_b], [self.col_a])
        headers = {"Authorization": token["token"]}
        key = self.record_key(token)
        good = cache.get_complex(key)
        theirs = self.token([self.col_x], headers={"Authorization": self.other.api_key})
        their_record = cache.get_complex(
            scoped_tokens._key(self.other.id, theirs["id"])
        )
        now = int(time.time())

        def changed(**changes):
            record = dict(good)
            record.update(changes)
            return record

        def without(field):
            record = dict(good)
            record.pop(field)
            return record

        broken = [
            changed(v=2),
            changed(v="1"),
            changed(v=True),
            changed(is_admin=True),
            changed(roles=[1]),
            without("v"),
            without("write"),
            without("expires_at"),
            without("secret_hash"),
            changed(read=[]),
            changed(read=None),
            changed(read="*"),
            changed(read=[str(self.col_a.id)]),
            changed(read=[self.col_a.id, None]),
            changed(read=[True]),
            changed(read={"a": 1}),
            changed(write=[self.col_x.id]),
            changed(write=None),
            changed(role_id=self.other.id),
            changed(role_id=str(self.owner.id)),
            changed(key_id="0" * 16),
            changed(secret_hash=""),
            changed(expires_at=now - 1),
            changed(expires_at=None),
            changed(expires_at=str(now + 60)),
            changed(expires_at=good["created_at"] + self.max_expire + 1),
            changed(created_at=now + 7200),
            changed(label=None),
            # Somebody else's valid record under this key.
            their_record,
            [good],
            "admin",
            None,
            42,
        ]
        for record in broken:
            cache.set_complex(key, record)
            self.assert_unauthorized(headers)
        for raw in ("", "{", "not json", "\x00"):
            cache.kv.set(key, raw)
            self.assert_unauthorized(headers)
        cache.kv.delete(key)
        self.assert_unauthorized(headers)
        with mock.patch.object(cache, "get_complex", side_effect=RuntimeError("down")):
            self.assert_unauthorized(headers)

        cache.set_complex(key, good)
        self.assert_ok(headers)

    def test_listing_skips_broken_records(self):
        token = self.token([self.col_a])
        cache.set_complex(self.record_key(token), {"v": 99})
        res = self.client.get(TOKENS, headers=self.headers)
        assert res.status_code == 200, res
        assert res.json["total"] == 0, res.json

    def test_expiry(self):
        token = self.token([self.col_a], expires_in=60)
        headers = {"Authorization": token["token"]}
        self.assert_ok(headers)
        assert 0 < cache.kv.ttl(self.record_key(token)) <= 60
        # Even if the store kept the record, it is refused once expired.
        cache.kv.persist(self.record_key(token))
        later = mock.Mock(time=mock.Mock(return_value=time.time() + 61))
        with mock.patch.object(scoped_tokens, "time", later):
            self.assert_unauthorized(headers)
            res = self.client.get(TOKENS, headers=self.headers)
            assert res.json["total"] == 0, res.json
        self.assert_ok(headers)

    def test_deleted_collection_ends_token(self):
        headers = self.scoped([self.col_a, self.col_b])
        self.assert_ok(headers)
        delete_collection(self.col_b, sync=True)
        self.assert_unauthorized(headers)

    def test_blocked_owner(self):
        token = self.token([self.col_a])
        headers = {"Authorization": token["token"]}
        self.owner.is_blocked = True
        db.session.commit()
        # Refused at once, before any cache is flushed ...
        self.assert_unauthorized(headers)
        # ... and the record is gone after the usual role update,
        update_role(self.owner)
        assert cache.kv.get(self.record_key(token)) is None
        # so that unblocking does not bring it back.
        self.owner.is_blocked = False
        db.session.commit()
        update_role(self.owner)
        self.assert_unauthorized(headers)

    def test_deleted_owner(self):
        token = self.token([self.col_a])
        headers = {"Authorization": token["token"]}
        key = self.record_key(token)
        delete_role(self.owner)
        self.assert_unauthorized(headers)
        assert cache.kv.get(key) is None

    def test_token_sent_in_a_url_is_revoked(self):
        token = self.token([self.col_a])
        headers = {"Authorization": token["token"]}
        url = "/api/2/collections/%s" % self.col_a.id
        # A wrong secret in a URL revokes nothing ...
        wrong = token["token"][:-1] + ("A" if token["token"][-1] != "A" else "B")
        res = self.client.get(url, query_string={"api_key": wrong})
        assert res.status_code == 401, res
        self.assert_ok(headers)
        # ... the real one is refused and is dead from then on.
        res = self.client.get(url, query_string={"api_key": token["token"]})
        assert res.status_code == 401, res
        self.assert_unauthorized(headers)

    def test_near_miss_credentials_are_not_tried_as_api_keys(self):
        token = self.token([self.col_a])["token"]
        self.grant_publish(self.col_a)
        url = "/api/2/collections/%s" % self.col_a.id
        assert self.client.get(url).status_code == 200
        for value in (
            "ApiKey  %s" % token,
            "ApiKey %s " % token,
            "ApiKey \t%s" % token,
            "ApiKey %s" % token.upper(),
            "ApiKey S%s" % token[1:],
        ):
            res = self.client.get(url, headers={"Authorization": value})
            assert res.status_code == 401, (value, res.status_code)
            # No falling back to a key in the URL either.
            res = self.client.get(
                url,
                headers={"Authorization": value},
                query_string={"api_key": self.owner.api_key},
            )
            assert res.status_code == 401, (value, res.status_code)

    def test_group_role_cannot_own_a_token(self):
        token = self.token([self.col_a])
        headers = {"Authorization": token["token"]}
        self.owner.type = "group"
        db.session.commit()
        self.assert_unauthorized(headers)

    def test_rotating_the_api_key_revokes_tokens(self):
        token = self.token([self.col_a])
        headers = {"Authorization": token["token"]}
        theirs = self.scoped(
            [self.col_x], headers={"Authorization": self.other.api_key}
        )
        assert rotate_api_key("owner@example.org") is not None
        self.assert_unauthorized(headers)
        assert cache.kv.get(self.record_key(token)) is None
        # Other users keep theirs.
        res = self.client.get("/api/2/collections/%s" % self.col_x.id, headers=theirs)
        assert res.status_code == 200, res

    def test_revoking_one_role_keeps_similar_role_ids(self):
        # Role ids 1 and 1x share a string prefix; revocation must not.
        token = self.token([self.col_a])
        key = scoped_tokens._key("%s0" % self.owner.id, "0" * 16)
        cache.kv.set(key, "x")
        scoped_tokens.revoke_scoped_tokens(self.owner.id)
        assert cache.kv.get(self.record_key(token)) is None
        assert cache.kv.get(key) is not None


class ScopedTokenAuthzTestCase(ScopedTokenTestCase):
    def test_authz_object(self):
        token = self.token([self.col_a, self.col_b, self.col_ro], [self.col_a])
        authz = Authz.from_scoped_token(token["token"])
        assert authz.id == self.owner.id
        assert authz.logged_in
        assert authz.scope is not None
        assert authz.roles == set(), authz.roles
        assert authz.private_roles == set(), authz.private_roles
        assert not authz.is_admin
        assert not authz.is_investigator
        assert not authz.can_read_role(self.owner.id)
        assert not authz.can_write_role(self.owner.id)
        assert not authz.can_create_investigation()
        assert not authz.can_manage_tokens()
        assert not authz.can_register()
        assert authz.token_id is None
        with self.assertRaises(Unauthorized):
            authz.to_token()
        ids = {self.col_a.id, self.col_b.id, self.col_ro.id}
        assert set(authz.collections(authz.READ)) == ids
        assert authz.collections(authz.WRITE) == [self.col_a.id]
        assert authz.collections("delete") == []
        assert authz.collections(None) == []
        assert authz.can(self.col_a, authz.WRITE)
        assert not authz.can(self.col_b, authz.WRITE)
        assert not authz.can(self.col_x, authz.READ)
        assert authz.search_auth.is_admin is False
        assert authz.search_auth.collection_ids == ids

        owner = Authz.from_role(self.owner)
        assert owner.can_manage_tokens()
        assert not Authz.from_role(None).can_manage_tokens()

    def test_constructor_cannot_make_a_privileged_scoped_authz(self):
        token = self.token([self.col_a])
        scope = scoped_tokens.load_scope(token["token"])
        owner = Authz.from_role(self.owner)
        authz = Authz(
            self.owner.id,
            owner.roles,
            is_admin=True,
            is_investigator=True,
            token_id="x",
            scope=scope,
            owner=owner,
        )
        assert not authz.is_admin
        assert not authz.is_investigator
        assert authz.roles == set()
        assert authz.token_id is None
        assert authz.collections(authz.READ) == [self.col_a.id]
        # Without the owner there is nothing to intersect with.
        with self.assertRaises(Unauthorized):
            Authz(self.owner.id, owner.roles, scope=scope)
        with self.assertRaises(Unauthorized):
            Authz(self.owner.id, (), scope=scope, owner=authz)
        with self.assertRaises(Unauthorized):
            Authz(self.owner.id, (), scope=scope, owner=Authz.from_role(self.other))

    def test_admin_token_is_not_admin(self):
        admin = self.create_user(foreign_id="admin", is_admin=True)
        headers = {"Authorization": admin.api_key}
        res = self.client.get("/api/2/entities/_stream", headers=headers)
        assert res.status_code == 200, res
        # An admin may scope a token to any collection ...
        scoped = self.scoped([self.col_a, self.col_x], [self.col_a], headers=headers)
        authz = Authz.from_scoped_token(scoped["Authorization"].split(" ")[1])
        assert not authz.is_admin
        assert set(authz.collections(authz.READ)) == {self.col_a.id, self.col_x.id}
        # ... but the token is held to its list like any other.
        res = self.client.get("/api/2/collections/%s" % self.col_x.id, headers=scoped)
        assert res.status_code == 200, res
        res = self.client.get("/api/2/collections/%s" % self.col_b.id, headers=scoped)
        assert res.status_code == 403, res
        res = self.client.get("/api/2/entities/_stream", headers=scoped)
        assert res.status_code == 403, res
        res = self.client.get("/api/2/collections", headers=scoped)
        ids = {int(c["id"]) for c in res.json["results"]}
        assert ids == {self.col_a.id, self.col_x.id}, ids
        url = "/api/2/collections/%s" % self.col_a.id
        data = {"label": "Renamed", "category": "leak", "external": True}
        res = self.client.post(url, json=data, headers=scoped)
        assert res.status_code == 403, res
        url = "/api/2/collections/%s/_bulk?clean=false" % self.col_x.id
        res = self.client.post(url, data="[]", headers=scoped)
        assert res.status_code == 403, res

    def test_role_cache_never_holds_the_narrowed_list(self):
        headers = self.scoped([self.col_a], [self.col_a])
        Authz.flush()
        assert not cache.kv.hkeys(Authz.ACCESS)
        # The scoped request is the one that fills the cache.
        self.assert_ok(headers)
        res = self.client.get("/api/2/entities", headers=headers)
        assert res.status_code == 200, res
        fields = [
            f.decode() if isinstance(f, bytes) else f
            for f in cache.kv.hkeys(Authz.ACCESS)
        ]
        assert fields == [str(self.owner.id)], fields
        cached = json.loads(cache.kv.hget(Authz.ACCESS, self.owner.id))
        ids = {self.col_a.id, self.col_b.id, self.col_ro.id}
        assert set(cached[Authz.READ]) == ids, cached
        assert set(cached[Authz.WRITE]) == {self.col_a.id, self.col_b.id}, cached
        # And the owner is not narrowed by it.
        res = self.client.get(
            "/api/2/collections/%s" % self.col_b.id, headers=self.headers
        )
        assert res.status_code == 200, res

    def test_access_shrinks_with_the_owner(self):
        headers = self.scoped([self.col_a, self.col_b, self.col_ro], [self.col_a])
        url_b = "/api/2/collections/%s" % self.col_b.id
        url_ro = "/api/2/collections/%s" % self.col_ro.id
        bulk_a = "/api/2/collections/%s/_bulk" % self.col_a.id
        assert self.client.get(url_b, headers=headers).status_code == 200
        assert self.client.get(url_ro, headers=headers).status_code == 200
        assert self.client.post(bulk_a, data="[]", headers=headers).status_code == 204

        self.grant(self.col_ro, self.owner, False, False)
        assert self.client.get(url_ro, headers=headers).status_code == 403
        assert self.client.get(url_b, headers=headers).status_code == 200

        # Demoted to read-only on A: the token's write list no longer helps.
        self.grant(self.col_a, self.owner, True, False)
        assert self.client.post(bulk_a, data="[]", headers=headers).status_code == 403
        self.assert_ok(headers)

        # Access the owner gains later is not added to the token.
        self.grant(self.col_x, self.owner, True, True)
        url_x = "/api/2/collections/%s" % self.col_x.id
        assert self.client.get(url_x, headers=self.headers).status_code == 200
        assert self.client.get(url_x, headers=headers).status_code == 403

    def test_group_access_shrinks_with_membership(self):
        group = self.create_group("scoped_group", self.owner)
        self.grant(self.col_x, group, True, False)
        headers = self.scoped([self.col_x])
        url = "/api/2/collections/%s" % self.col_x.id
        assert self.client.get(url, headers=headers).status_code == 200
        self.owner.roles.remove(group)
        db.session.commit()
        update_role(self.owner)
        assert self.client.get(url, headers=headers).status_code == 403

    def test_public_collections_are_not_implied(self):
        self.grant_publish(self.col_x)
        url = "/api/2/collections/%s" % self.col_x.id
        assert self.client.get(url).status_code == 200
        headers = self.scoped([self.col_a])
        assert self.client.get(url, headers=headers).status_code == 403

    def test_nothing_in_the_request_widens_the_scope(self):
        headers = self.scoped([self.col_a])
        url = "/api/2/collections/%s" % self.col_b.id
        attempts = [
            dict(query_string={"api_key": self.owner.api_key}),
            dict(query_string={"collection_id": self.col_b.id, "read": self.col_b.id}),
            dict(headers={"X-Aleph-Session": "1", "X-Scope": str(self.col_b.id)}),
        ]
        for attempt in attempts:
            extra = attempt.pop("headers", {})
            extra.update(headers)
            res = self.client.get(url, headers=extra, **attempt)
            assert res.status_code == 403, (attempt, res.status_code)
        # No session, no further token.
        res = self.client.post("/api/2/sessions/login", headers=headers, data={})
        assert res.status_code == 403, res
        data = {"read": [self.col_a.id, self.col_b.id], "expires_in": 10**9}
        res = self.client.post(TOKENS, json=dict(data, label="x"), headers=headers)
        assert res.status_code == 403, res
        res = self.client.get("/api/2/metadata", headers=headers)
        assert res.status_code == 200, res
        assert res.json["token"] is None, res.json["token"]


class ScopedTokenDataTestCase(ScopedTokenTestCase):
    """The owner can see B in all of these places; a token for A cannot."""

    def setUp(self):
        super().setUp()
        self.scoped_a = self.scoped([self.col_a], [self.col_a])

    def assert_only_a(self, res):
        assert res.status_code == 200, res.json
        text = res.get_data(as_text=True)
        assert self.id_b not in text, text
        assert "Collection B" not in text, text
        assert self.col_ns_x not in text, text

    @property
    def col_ns_x(self):
        return self.col_x.ns.sign(self.ent_x.id)

    def test_collections(self):
        res = self.client.get("/api/2/collections", headers=self.headers)
        assert res.json["total"] == 3, res.json
        res = self.client.get("/api/2/collections", headers=self.scoped_a)
        assert res.json["total"] == 1, res.json
        assert int(res.json["results"][0]["id"]) == self.col_a.id, res.json
        url = "/api/2/collections?filter:writeable=true"
        res = self.client.get(url, headers=self.scoped([self.col_a]))
        assert res.json["total"] == 0, res.json
        for collection in (self.col_b, self.col_ro, self.col_x):
            url = "/api/2/collections/%s" % collection.id
            res = self.client.get(url, headers=self.scoped_a)
            assert res.status_code == 403, res
        self.assert_ok(self.scoped_a)

    def test_owner_details_are_not_exposed(self):
        res = self.client.get(
            "/api/2/collections/%s" % self.col_a.id, headers=self.headers
        )
        assert res.json["creator"]["email"] == "owner@example.org", res.json
        for url in (
            "/api/2/collections/%s" % self.col_a.id,
            "/api/2/collections",
            "/api/2/entities/%s" % self.id_a,
            "/api/2/roles/%s" % self.owner.id,
            "/api/freebase/reconcile",
            "/api/2/collections/%s/reconcile" % self.col_a.id,
        ):
            res = self.client.get(url, headers=self.scoped_a)
            text = res.get_data(as_text=True)
            assert self.owner.api_key not in text, url
            assert "owner@example.org" not in text, url
        res = self.client.get("/api/2/roles/%s" % self.owner.id, headers=self.scoped_a)
        assert res.status_code == 403, res
        # The error does not list the owner's groups either.
        assert not res.json.get("roles"), res.json

    def test_bookmarks_are_not_exposed(self):
        data = {"entity_id": self.id_a}
        res = self.client.post("/api/2/bookmarks", json=data, headers=self.headers)
        assert res.status_code in (200, 201), res
        url = "/api/2/entities/%s" % self.id_a
        res = self.client.get(url, headers=self.headers)
        assert res.json["bookmarked"] is True, res.json
        res = self.client.get(url, headers=self.scoped_a)
        assert res.status_code == 200, res
        assert "bookmarked" not in res.json, res.json

    def test_http_cache_is_per_token(self):
        self.grant_publish(self.col_a)
        url = "/api/2/entities/%s" % self.id_a
        etags = set()
        for headers in (self.headers, self.scoped_a, self.scoped([self.col_a]), {}):
            res = self.client.get(url, headers=headers)
            assert res.status_code == 200, res
            etags.add(res.headers["ETag"])
        assert len(etags) == 4, etags
        # Another credential's ETag does not short-cut a token's request.
        other = self.scoped([self.col_b])
        for etag in etags:
            headers = dict(other, **{"If-None-Match": etag})
            res = self.client.get(url, headers=headers)
            assert res.status_code == 403, res.status_code

    def test_search(self):
        url = "/api/2/entities?filter:schema=Person&facet=collection_id"
        res = self.client.get(url, headers=self.headers)
        assert res.json["total"] == 2, res.json
        assert self.id_b in res.get_data(as_text=True)

        res = self.client.get(url, headers=self.scoped_a)
        self.assert_only_a(res)
        assert res.json["total"] == 1, res.json
        facet = res.json["facets"]["collection_id"]["values"]
        assert [int(v["id"]) for v in facet] == [self.col_a.id], facet

        for query in (
            "filter:collection_id=%s" % self.col_b.id,
            "filter:collection_id=%s&filter:collection_id=%s"
            % (self.col_a.id, self.col_b.id),
            "q=Leeta",
            "q=collection_id:%s" % self.col_b.id,
            "filter:dataset=scoped_b",
        ):
            res = self.client.get("/api/2/entities?%s" % query, headers=self.scoped_a)
            self.assert_only_a(res)
        url = "/api/2/entities?filter:collection_id=%s" % self.col_b.id
        res = self.client.get(url, headers=self.scoped_a)
        assert res.json["total"] == 0, res.json
        res = self.client.post(
            "/api/2/search", headers=self.scoped_a, data={"q": "Leeta"}
        )
        self.assert_only_a(res)
        assert res.json["total"] == 1, res.json

    def test_entity_views(self):
        for path in ("", "/similar", "/tags", "/entitysets"):
            url = "/api/2/entities/%s%s" % (self.id_b, path)
            assert self.client.get(url, headers=self.headers).status_code == 200, url
            res = self.client.get(url, headers=self.scoped_a)
            assert res.status_code == 403, (url, res.status_code)
        res = self.client.get("/api/2/entities/%s" % self.id_a, headers=self.scoped_a)
        self.assert_only_a(res)
        url = "/api/2/archive/resolve?entity=%s" % self.id_b
        res = self.client.get(url, headers=self.scoped_a)
        assert res.status_code == 403, res

    def test_similar_and_match(self):
        url = "/api/2/entities/%s/similar" % self.id_a
        res = self.client.get(url, headers=self.headers)
        assert self.id_b in res.get_data(as_text=True), res.json
        res = self.client.get(url, headers=self.scoped_a)
        self.assert_only_a(res)
        assert res.json["total"] == 0, res.json

        data = {"schema": "Person", "properties": {"name": ["Leeta"]}}
        for url in (
            "/api/2/match",
            "/api/2/match?collection_ids=%s" % self.col_b.id,
        ):
            res = self.client.post(url, json=data, headers=self.headers)
            assert self.id_b in res.get_data(as_text=True), res.json
            res = self.client.post(url, json=data, headers=self.scoped_a)
            self.assert_only_a(res)

    def test_tags(self):
        url = "/api/2/entities/%s/tags" % self.id_a
        res = self.client.get(url, headers=self.headers)
        assert res.json["total"] > 0, res.json
        res = self.client.get(url, headers=self.scoped_a)
        assert res.status_code == 200, res
        assert res.json["total"] == 0, res.json
        # Expanding resolves referenced entities by id: not for scoped tokens.
        url = "/api/2/entities/%s/expand" % self.id_a
        assert self.client.get(url, headers=self.headers).status_code == 200
        assert self.client.get(url, headers=self.scoped_a).status_code == 403

    def test_stream(self):
        stream_a = "/api/2/collections/%s/_stream" % self.col_a.id
        stream_b = "/api/2/collections/%s/_stream" % self.col_b.id
        res = self.client.get(stream_b, headers=self.headers)
        assert res.status_code == 200, res
        res = self.client.get(stream_a, headers=self.scoped_a)
        assert res.status_code == 200, res
        text = res.get_data(as_text=True)
        assert self.id_a in text and self.id_b not in text, text
        res = self.client.get(stream_b, headers=self.scoped_a)
        assert res.status_code == 403, res
        res = self.client.get("/api/2/entities/_stream", headers=self.scoped_a)
        assert res.status_code == 403, res
        # Streaming takes write access; a read-only token has none.
        res = self.client.get(stream_a, headers=self.scoped([self.col_a, self.col_b]))
        assert res.status_code == 403, res

    def test_xref(self):
        xref.xref_collection(self.col_a)
        url = "/api/2/collections/%s/xref" % self.col_a.id
        res = self.client.get(url, headers=self.headers)
        assert res.json["total"] == 1, res.json
        assert self.id_b in res.get_data(as_text=True)
        # Reading A's matches does not reveal what they matched in B,
        res = self.client.get(url, headers=self.scoped_a)
        self.assert_only_a(res)
        assert res.json["total"] == 0, res.json
        # and B's matches are closed altogether.
        url_b = "/api/2/collections/%s/xref" % self.col_b.id
        res = self.client.get(url_b, headers=self.scoped_a)
        assert res.status_code == 403, res
        both = self.scoped([self.col_a, self.col_b])
        res = self.client.get(url, headers=both)
        assert res.json["total"] == 1, res.json
        # Running and exporting cross-references is not for scoped tokens.
        for url in (url, url + ".xlsx"):
            res = self.client.post(url, headers=self.scoped_a)
            assert res.status_code == 403, res

    def test_entitysets(self):
        def make(collection, label):
            data = {"collection_id": str(collection.id), "label": label, "type": "list"}
            res = self.client.post("/api/2/entitysets", json=data, headers=self.headers)
            assert res.status_code == 200, res.json
            return res.json["id"]

        set_a = make(self.col_a, "List in A")
        set_b = make(self.col_b, "List in B")
        # The owner puts an entity of B on the list in A.
        for entity_id in (self.id_a, self.id_b):
            url = "/api/2/entitysets/%s/items" % set_a
            res = self.client.post(
                url, json={"entity_id": entity_id}, headers=self.headers
            )
            assert res.status_code == 200, res.json
        url = "/api/2/entitysets/%s/items" % set_b
        res = self.client.post(url, json={"entity_id": self.id_b}, headers=self.headers)
        assert res.status_code == 200, res.json

        res = self.client.get("/api/2/entitysets", headers=self.headers)
        assert res.json["total"] == 2, res.json
        for url in (
            "/api/2/entitysets",
            "/api/2/entitysets?filter:collection_id=%s" % self.col_b.id,
        ):
            res = self.client.get(url, headers=self.scoped_a)
            self.assert_only_a(res)
            assert "List in B" not in res.get_data(as_text=True)
        res = self.client.get("/api/2/entitysets", headers=self.scoped_a)
        assert res.json["total"] == 1, res.json

        for path in ("", "/items", "/entities"):
            url = "/api/2/entitysets/%s%s" % (set_b, path)
            res = self.client.get(url, headers=self.scoped_a)
            assert res.status_code == 403, (url, res.status_code)
        for method in (self.client.post, self.client.delete):
            res = method("/api/2/entitysets/%s" % set_b, headers=self.scoped_a, json={})
            assert res.status_code == 403, res

        # The list in A is readable, minus the member that lives in B.
        for path in ("/items", "/entities"):
            url = "/api/2/entitysets/%s%s" % (set_a, path)
            res = self.client.get(url, headers=self.headers)
            assert self.id_b in res.get_data(as_text=True), url
            res = self.client.get(url, headers=self.scoped_a)
            self.assert_only_a(res)
            assert self.id_a in res.get_data(as_text=True), url

        # Lists an entity is on, across collections.
        url = "/api/2/entities/%s/entitysets" % self.id_a
        for url in (url, url + "?filter:collection_id=%s" % self.col_b.id):
            res = self.client.get(url, headers=self.scoped_a)
            self.assert_only_a(res)

        # An entity the token cannot read cannot be put on a list.
        url = "/api/2/entitysets/%s/items" % set_a
        res = self.client.post(
            url, json={"entity_id": self.id_b}, headers=self.scoped_a
        )
        assert res.status_code == 403, res
        data = {"collection_id": str(self.col_b.id), "label": "x", "type": "list"}
        res = self.client.post("/api/2/entitysets", json=data, headers=self.scoped_a)
        assert res.status_code == 403, res
        url = "/api/2/entitysets/%s/entities" % set_a
        data = {"id": self.id_b, "schema": "Person", "properties": {"name": "Mine"}}
        res = self.client.post(url, json=data, headers=self.scoped_a)
        assert res.status_code == 403, res
        # Nor can a bulk import into A feed a list that lives in B.
        url = "/api/2/collections/%s/_bulk?entityset_id=%s" % (self.col_a.id, set_b)
        bulk = [{"id": "q", "schema": "Person", "properties": {"name": "Q"}}]
        res = self.client.post(url, data=json.dumps(bulk), headers=self.scoped_a)
        assert res.status_code == 403, res
        url = "/api/2/entitysets/%s/items" % set_b
        res = self.client.get(url, headers=self.headers)
        assert res.json["total"] == 1, res.json

    def test_writes_stay_inside_the_write_list(self):
        headers = self.scoped([self.col_a, self.col_b, self.col_ro], [self.col_a])
        entity = {"schema": "Person", "properties": {"name": "Quark"}}
        bulk = json.dumps([dict(entity, id="quark")])

        def create(collection):
            data = dict(entity, collection_id=str(collection.id))
            return self.client.post("/api/2/entities", json=data, headers=headers)

        res = create(self.col_a)
        assert res.status_code == 200, res.json
        new_id = res.json["id"]
        for collection in (self.col_b, self.col_ro, self.col_x):
            assert create(collection).status_code == 403, collection.label
            url = "/api/2/collections/%s/_bulk" % collection.id
            res = self.client.post(url, data=bulk, headers=headers)
            assert res.status_code == 403, collection.label
            url = "/api/2/collections/%s/ingest" % collection.id
            data = {"meta": json.dumps({"foreign_id": "dir"})}
            res = self.client.post(url, data=data, headers=headers)
            assert res.status_code == 403, collection.label
        url = "/api/2/collections/%s/_bulk" % self.col_a.id
        res = self.client.post(url, data=bulk, headers=headers)
        assert res.status_code == 204, res

        # The collection named in the body does not override the entity's.
        url = "/api/2/entities/%s" % self.id_b
        data = dict(entity, collection_id=str(self.col_a.id))
        res = self.client.post(url, json=data, headers=headers)
        assert res.status_code == 403, res
        res = self.client.delete(url, headers=headers)
        assert res.status_code == 403, res
        res = self.client.get(url, headers=headers)
        assert res.status_code == 200, res
        assert "Leeta" in res.get_data(as_text=True)

        res = self.client.post(
            "/api/2/entities/%s" % new_id, json=entity, headers=headers
        )
        assert res.status_code == 200, res.json
        res = self.client.delete("/api/2/entities/%s" % new_id, headers=headers)
        assert res.status_code == 204, res

        # A token without a write list cannot write anywhere.
        headers = self.scoped([self.col_a])
        assert self.client.post(url, json=data, headers=headers).status_code == 403
        url = "/api/2/collections/%s/_bulk" % self.col_a.id
        assert self.client.post(url, data=bulk, headers=headers).status_code == 403
        data = dict(entity, collection_id=str(self.col_a.id))
        res = self.client.post("/api/2/entities", json=data, headers=headers)
        assert res.status_code == 403, res

    def test_maintenance_and_external_still_block_writes(self):
        url = "/api/2/collections/%s/_bulk" % self.col_a.id
        assert (
            self.client.post(url, data="[]", headers=self.scoped_a).status_code == 204
        )

        self.col_a.maintenance = True
        db.session.commit()
        assert (
            self.client.post(url, data="[]", headers=self.scoped_a).status_code == 403
        )
        self.assert_ok(self.scoped_a)
        self.col_a.maintenance = False
        self.col_a.external = True
        db.session.commit()
        update_collection(self.col_a, sync=True)
        assert (
            self.client.post(url, data="[]", headers=self.scoped_a).status_code == 403
        )
        self.assert_ok(self.scoped_a)
        self.col_a.external = False
        db.session.commit()
        update_collection(self.col_a, sync=True)
        assert (
            self.client.post(url, data="[]", headers=self.scoped_a).status_code == 204
        )

        SETTINGS.MAINTENANCE = True
        assert (
            self.client.post(url, data="[]", headers=self.scoped_a).status_code == 403
        )
        self.assert_ok(self.scoped_a)


class ScopedTokenEndpointTestCase(ScopedTokenTestCase):
    def test_allowlist_is_pinned(self):
        assert set(SCOPED_TOKEN_ENDPOINTS) == EXPECTED_ENDPOINTS
        missing = EXPECTED_ENDPOINTS - set(self.app.view_functions)
        assert not missing, missing

    def test_every_other_endpoint_refuses_a_scoped_token(self):
        """Walk the whole URL map. Whatever is not on the allowlist answers
        403 to a token whose owner is an admin and could do it all."""
        admin = self.create_user(foreign_id="admin", is_admin=True)
        scoped = self.scoped(
            [self.col_a, self.col_b],
            [self.col_a, self.col_b],
            headers={"Authorization": admin.api_key},
        )
        values = {
            "collection_id": self.col_a.id,
            "entity_id": self.id_a,
            "id": admin.id,
        }
        checked = set()
        for rule in self.app.url_map.iter_rules():
            if rule.endpoint in SCOPED_TOKEN_ENDPOINTS:
                continue
            args = {arg: values.get(arg, "1") for arg in rule.arguments}
            if rule.endpoint == "static":
                args = {"filename": "x.js"}
            url = rule.build(args)[1]
            for method in rule.methods - {"HEAD", "OPTIONS"}:
                res = self.client.open(url, method=method, headers=scoped)
                assert res.status_code == 403, (rule.endpoint, method, res.status_code)
                checked.add(rule.endpoint)
        # The account, token and administration endpoints were among them.
        for endpoint in (
            "tokens_api.index",
            "tokens_api.create",
            "tokens_api.delete",
            "roles_api.view",
            "roles_api.update",
            "sessions_api.logout",
            "permissions_api.index",
            "permissions_api.update",
            "collections_api.create",
            "collections_api.update",
            "collections_api.delete",
            "entities_api.export",
            "xref_api.export",
            "exports_api.index",
            "alerts_api.create",
            "notifications_api.index",
            "profiles_api.pairwise",
            "reconcile_api.reconcile",
            "mappings_api.create",
        ):
            assert endpoint in checked, endpoint
        res = self.client.get("/api/2/does-not-exist", headers=scoped)
        assert res.status_code == 403, res
        # The token survived all of it, including the logout.
        self.assert_ok(scoped)
        res = self.client.get("/api/2/collections", headers=scoped)
        assert res.json["total"] == 2, res.json

    def test_other_credentials_are_not_restricted(self):
        """The allowlist only applies to scoped tokens."""
        url = "/api/2/roles/%s" % self.owner.id
        res = self.client.get(url, headers=self.headers)
        assert res.status_code == 200, res
        assert res.json["api_key"] == self.owner.api_key, res.json
        res = self.client.get(
            url, headers={"Authorization": "ApiKey " + self.owner.api_key}
        )
        assert res.status_code == 200, res
        session = {"Authorization": "Token %s" % Authz.from_role(self.owner).to_token()}
        res = self.client.get(url, headers=session)
        assert res.status_code == 200, res
        res = self.client.get("/api/2/alerts", headers=session)
        assert res.status_code == 200, res
        res = self.client.get("/api/2/statistics")
        assert res.status_code == 200, res
        assert Authz.from_role(self.owner).scope is None
        assert Authz.from_token(session["Authorization"][6:]).scope is None
        res = self.client.get("/api/2/metadata", content_type=JSON)
        assert res.status_code == 200, res

    def test_permissions_cannot_be_changed_with_a_write_token(self):
        headers = self.scoped([self.col_a], [self.col_a])
        url = "/api/2/collections/%s/permissions" % self.col_a.id
        assert self.client.get(url, headers=self.headers).status_code == 200
        assert self.client.get(url, headers=headers).status_code == 403
        data = [{"role_id": str(self.other.id), "read": True, "write": True}]
        res = self.client.post(url, json=data, headers=headers)
        assert res.status_code == 403, res
        q = Permission.all().filter(Permission.collection_id == self.col_a.id)
        assert {p.role_id for p in q} == {self.owner.id}
