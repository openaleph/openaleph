"""End-to-end resolver tests against a real DB + ES index.

Verifies the full roundtrip: create data → fetch via Resolver →
check ETag → mutate → invalidation fires → re-fetch → ETag changes.
Uses the standard TestCase infrastructure from ``aleph.tests.util``.
"""

import time

from aleph.core import db
from aleph.logic.resolver.core import RequestResolver
from aleph.model import (
    Alert,
    AlertSchema,
    CollectionSchema,
    EntitySchema,
    EntitySet,
    EntitySetSchema,
    Export,
    ExportSchema,
    RoleSchema,
    Status,
)
from aleph.tests.util import TestCase


class ResolverE2ETestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.init_app()
        self.load_fixtures()
        # Force re-registration — module-level @register decorators
        # only run once at import time, so if the unit test fixture
        # cleared the registry after those imports, we need to reload.
        import importlib

        import aleph.index.collections
        import aleph.logic.alerts
        import aleph.logic.entities
        import aleph.logic.entitysets
        import aleph.logic.export
        import aleph.logic.roles

        for mod in [
            aleph.logic.roles,
            aleph.logic.alerts,
            aleph.logic.export,
            aleph.logic.entitysets,
            aleph.index.collections,
            aleph.logic.entities,
        ]:
            importlib.reload(mod)

        # Wipe the resolver store so tests start clean.
        RequestResolver().flushall()

    # --- Role -----------------------------------------------------------------

    def test_role_resolve_and_etag(self):
        r = RequestResolver()
        role = r.get(RoleSchema, str(self.admin.id))
        self.assertIsNotNone(role)
        self.assertEqual(role.name, "admin")

        etag = r.get_etag(RoleSchema, str(self.admin.id))
        self.assertIsNotNone(etag)
        self.assertTrue(etag.startswith('"') and etag.endswith('"'))

        # Same content → same ETag.
        r2 = RequestResolver()
        self.assertEqual(r2.get_etag(RoleSchema, str(self.admin.id)), etag)

    def test_role_invalidation_rotates_etag(self):
        r = RequestResolver()
        etag_before = r.get_etag(RoleSchema, str(self.admin.id))

        # Mutate the role — Role.update calls touch() which bumps
        # updated_at. The SQLA after_update event fires invalidation.
        self.admin.update({"name": "Admin Renamed"})
        db.session.commit()

        r2 = RequestResolver()
        etag_after = r2.get_etag(RoleSchema, str(self.admin.id))
        self.assertNotEqual(etag_before, etag_after)

        # The fetched data should reflect the mutation.
        role = r2.get(RoleSchema, str(self.admin.id))
        self.assertEqual(role.name, "Admin Renamed")

    def test_refresh_updates_cached_role(self):
        """cache.refresh() re-fetches from upstream and updates the
        store so subsequent reads get the fresh value."""
        r = RequestResolver()
        role = r.get(RoleSchema, str(self.admin.id))
        self.assertEqual(role.name, "admin")

        # Mutate the role in the DB.
        self.admin.update({"name": "Admin Refreshed"})
        db.session.commit()

        # refresh() fetches fresh from the DB and writes to the store.
        r.refresh(RoleSchema, str(self.admin.id))

        # New resolver reads the refreshed value from the store.
        r2 = RequestResolver()
        role2 = r2.get(RoleSchema, str(self.admin.id))
        self.assertEqual(role2.name, "Admin Refreshed")

    # --- Alert ----------------------------------------------------------------

    def test_alert_resolve_and_etag(self):
        alert = Alert.create({"query": "test-query"}, self.admin.id)
        db.session.commit()

        r = RequestResolver()
        fetched = r.get(AlertSchema, str(alert.id))
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.query, "test-query")

        etag = r.get_etag(AlertSchema, str(alert.id))
        self.assertIsNotNone(etag)
        self.assertEqual(len(etag), 13)

    def test_alert_invalidation_on_delete(self):
        alert = Alert.create({"query": "delete-me"}, self.admin.id)
        db.session.commit()

        r = RequestResolver()
        self.assertIsNotNone(r.get(AlertSchema, str(alert.id)))

        # Delete — SQLA after_delete event fires invalidation.
        alert.delete()
        db.session.commit()

        r2 = RequestResolver()
        self.assertIsNone(r2.get(AlertSchema, str(alert.id)))

    # --- Export ---------------------------------------------------------------

    def test_export_resolve_and_invalidation(self):
        export = Export.create(
            "exportsearch",
            self.admin.id,
            "Test Export",
            mime_type="application/zip",
            meta={},
        )
        db.session.commit()

        r = RequestResolver()
        fetched = r.get(ExportSchema, str(export.id))
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.label, "Test Export")

        etag_before = r.get_etag(ExportSchema, str(export.id))
        self.assertIsNotNone(etag_before)

        # Mutate — status change triggers after_update event.
        export.set_status(status=Status.SUCCESS)
        db.session.commit()

        r2 = RequestResolver()
        etag_after = r2.get_etag(ExportSchema, str(export.id))
        self.assertNotEqual(etag_before, etag_after)

    # --- EntitySet ------------------------------------------------------------

    def test_entityset_resolve_and_invalidation(self):
        from aleph.authz import Authz

        authz = Authz.from_role(self.admin)
        entityset = EntitySet.create(
            {"label": "Test Diagram", "type": "diagram"},
            self.private_coll,
            authz,
        )
        db.session.commit()

        r = RequestResolver()
        fetched = r.get(EntitySetSchema, str(entityset.id))
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.label, "Test Diagram")

        etag_before = r.get_etag(EntitySetSchema, str(entityset.id))

        # Mutate — SQLA after_update event fires invalidation.
        from datetime import datetime

        entityset.label = "Renamed Diagram"
        entityset.updated_at = datetime.utcnow()
        db.session.add(entityset)
        db.session.commit()

        r2 = RequestResolver()
        etag_after = r2.get_etag(EntitySetSchema, str(entityset.id))
        self.assertNotEqual(etag_before, etag_after)

        fetched2 = r2.get(EntitySetSchema, str(entityset.id))
        self.assertEqual(fetched2.label, "Renamed Diagram")

    # --- Collection -----------------------------------------------------------

    def test_collection_invalidation(self):
        r = RequestResolver()
        etag_before = r.get_etag(CollectionSchema, self.public_coll.id)

        # Mutate — touch() bumps updated_at, SQLA after_update fires.
        self.public_coll.label = "Renamed Public"
        self.public_coll.touch()
        db.session.commit()

        r2 = RequestResolver()
        etag_after = r2.get_etag(CollectionSchema, self.public_coll.id)
        self.assertNotEqual(etag_before, etag_after)

    # --- Entity ---------------------------------------------------------------

    def test_entity_resolve_and_batch(self):
        """Fetch entities via the resolver — both single and batch."""
        from openaleph_search.index.entities import get_entity

        raw = get_entity(self._kwazulu.id)
        self.assertIsNotNone(raw, "Fixture entity not in ES index")

        r = RequestResolver()
        entity = r.get(EntitySchema, self._kwazulu.id)
        self.assertIsNotNone(entity)
        self.assertEqual(entity.id, self._kwazulu.id)
        self.assertIsInstance(entity.latinized, dict)

        # Batch fetch.
        entities = r.get_many(EntitySchema, [self._kwazulu.id, self._banana.id])
        ids = [e.id for e in entities]
        self.assertIn(self._kwazulu.id, ids)

    def test_entity_etag_from_es_version(self):
        r = RequestResolver()
        etag = r.get_etag(EntitySchema, self._kwazulu.id)
        self.assertIsNotNone(etag)
        self.assertTrue(etag.startswith('"') and etag.endswith('"'))

        # Stable on re-fetch.
        r2 = RequestResolver()
        self.assertEqual(r2.get_etag(EntitySchema, self._kwazulu.id), etag)

    def test_entity_invalidation(self):
        r = RequestResolver()
        etag_before = r.get_etag(EntitySchema, self._kwazulu.id)
        self.assertIsNotNone(etag_before)

        # Re-index the entity — bumps ES _seq_no, calls
        # refresh_entity → Resolver.invalidate(EntitySchema, ...).
        from aleph.logic.entities import upsert_entity

        upsert_entity(
            {
                "id": self._kwazulu.id,
                "schema": "Company",
                "properties": {"name": ["KwaZulu Updated"]},
            },
            self.public_coll,
            sync=True,
        )
        time.sleep(1)  # ES refresh

        r2 = RequestResolver()
        entity = r2.get(EntitySchema, self._kwazulu.id)
        self.assertIsNotNone(entity)
        etag_after = r2.get_etag(EntitySchema, self._kwazulu.id)
        self.assertNotEqual(etag_before, etag_after)

    # --- Deletion invalidation ------------------------------------------------

    def test_collection_deletion_invalidates_cache(self):
        """DB path: deleting a collection via the ORM fires the SQLA
        after_update event (soft-delete sets deleted_at), which
        invalidates the resolver cache. The next fetch returns None."""
        cid = self.public_coll.id
        r = RequestResolver()
        self.assertIsNotNone(r.get(CollectionSchema, cid))

        from aleph.logic.collections import delete_collection

        delete_collection(self.public_coll, sync=True)

        r2 = RequestResolver()
        self.assertIsNone(r2.get(CollectionSchema, cid))

    def test_entity_deletion_invalidates_cache(self):
        """ES path: deleting an entity removes it from the index and
        calls refresh_entity → resolver_cache.invalidate. The next
        fetch returns None."""
        entity_id = self._kwazulu.id
        r = RequestResolver()
        self.assertIsNotNone(r.get(EntitySchema, entity_id))

        from openaleph_search.index.entities import get_entity

        from aleph.logic.entities import delete_entity

        raw = get_entity(entity_id)
        delete_entity(self.public_coll, raw["id"], sync=True)
        time.sleep(1)  # ES refresh

        r2 = RequestResolver()
        self.assertIsNone(r2.get(EntitySchema, entity_id))

    # --- ETag opacity ---------------------------------------------------------

    def test_etags_are_opaque(self):
        """No raw identifiers or timestamps should leak in ETags."""
        alert = Alert.create({"query": "opacity-test"}, self.admin.id)
        db.session.commit()

        r = RequestResolver()
        for cls, identifier in [
            (RoleSchema, str(self.admin.id)),
            (CollectionSchema, self.public_coll.id),
            (AlertSchema, str(alert.id)),
        ]:
            etag = r.get_etag(cls, identifier)
            self.assertIsNotNone(etag, f"{cls.__name__} etag is None")
            inner = etag[1:-1]  # strip quotes
            self.assertEqual(len(inner), 11, f"{cls.__name__} etag wrong length")
            # numeric IDs can be part of the hash by coincidence
            if len(str(identifier)) > 1:
                self.assertNotIn(identifier, inner)

    # --- get_many_etag --------------------------------------------------------

    def test_get_many_etag_stable_and_discriminated(self):
        r = RequestResolver()
        r.get(RoleSchema, str(self.admin.id))

        combined = r.get_many_etag(RoleSchema, [str(self.admin.id)])
        self.assertIsNotNone(combined)

        # Same input → same ETag.
        r2 = RequestResolver()
        self.assertEqual(r2.get_many_etag(RoleSchema, [str(self.admin.id)]), combined)

        # Different extra discriminator → different ETag.
        filtered = r.get_many_etag(RoleSchema, [str(self.admin.id)], extra="?q=foo")
        self.assertNotEqual(combined, filtered)
