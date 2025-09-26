import datetime
import json

from aleph.core import db
from aleph.logic.entities import upsert_entity
from aleph.model.tag import Tag
from aleph.tests.util import JSON, TestCase


class TagsApiTestCase(TestCase):
    def setUp(self):
        super(TagsApiTestCase, self).setUp()

        self.role, self.headers = self.login()
        self.collection = self.create_collection(
            self.role, label="Politicians", taggable=True
        )

        data = {"schema": "Person", "properties": {"name": "Angela Merkel"}}
        self.entity = self.create_entity(data=data, collection=self.collection)
        upsert_entity(self.entity.to_proxy().to_dict(), self.collection)

        data2 = {"schema": "Person", "properties": {"name": "Barack Obama"}}
        self.entity2 = self.create_entity(data=data2, collection=self.collection)
        upsert_entity(self.entity2.to_proxy().to_dict(), self.collection)

    def test_tags_index_auth(self):
        # Test without authentication
        res = self.client.get("/api/2/tags")
        assert res.status_code == 403, res

        # Test without collection_id parameter
        res = self.client.get("/api/2/tags", headers=self.headers)
        assert res.status_code == 400, res
        assert "collection_id parameter is required" in res.json["message"]

        # Test with valid collection_id
        res = self.client.get(
            f"/api/2/tags?collection_id={self.collection.id}", headers=self.headers
        )
        assert res.status_code == 200, res
        assert res.json["total"] == 0, res.json

    def test_tags_index_by_collection(self):
        other_role, _ = self.login("tester2")

        # Create tags for different entities and users
        tags = [
            Tag(
                entity_id=self.entity.id,
                collection_id=self.collection.id,
                role_id=self.role.id,
                tag="politician",
            ),
            Tag(
                entity_id=self.entity.id,
                collection_id=self.collection.id,
                role_id=other_role.id,
                tag="politician",
            ),
            Tag(
                entity_id=self.entity2.id,
                collection_id=self.collection.id,
                role_id=self.role.id,
                tag="politician",
            ),
            Tag(
                entity_id=self.entity.id,
                collection_id=self.collection.id,
                role_id=self.role.id,
                tag="german",
            ),
        ]
        db.session.add_all(tags)
        db.session.commit()

        # Test collection-level query (should group by tag and count)
        res = self.client.get(
            f"/api/2/tags?collection_id={self.collection.id}", headers=self.headers
        )
        assert res.status_code == 200, res
        assert res.json["total"] == 2, res.json  # 2 unique tags: politician, german

        # Check ordering by count (politician appears 3 times, german 1 time)
        results = res.json["results"]
        assert len(results) == 2
        assert results[0]["tag"] == "politician"
        assert results[0]["count"] == 3
        assert results[1]["tag"] == "german"
        assert results[1]["count"] == 1

    def test_tags_index_by_collection_and_entity(self):
        # Create tags for the entity
        tags = [
            Tag(
                entity_id=self.entity.id,
                collection_id=self.collection.id,
                role_id=self.role.id,
                tag="politician",
                created_at=datetime.datetime(2020, 1, 1),
            ),
            Tag(
                entity_id=self.entity.id,
                collection_id=self.collection.id,
                role_id=self.role.id,
                tag="german",
                created_at=datetime.datetime(2020, 1, 2),
            ),
        ]
        db.session.add_all(tags)
        db.session.commit()

        # Test collection + entity filter
        res = self.client.get(
            f"/api/2/tags?collection_id={self.collection.id}&entity_id={self.entity.id}",
            headers=self.headers,
        )
        assert res.status_code == 200, res
        assert res.json["total"] == 2, res.json

        # Should be ordered by creation date (newest first)
        results = res.json["results"]
        assert results[0]["tag"] == "german"
        assert results[1]["tag"] == "politician"

        # includes resolved role and entity
        tag = results[0]
        assert tag["role"]["id"] == "4"

    def test_tags_index_access_control(self):
        other_role = self.create_user(foreign_id="other")
        secret_collection = self.create_collection(other_role, label="Top Secret")

        # Test access to collection user doesn't have permission for
        res = self.client.get(
            f"/api/2/tags?collection_id={secret_collection.id}", headers=self.headers
        )
        assert res.status_code == 403, res

    def test_tags_get_by_entity_auth(self):
        # Test without authentication
        res = self.client.get(f"/api/2/tags/{self.entity.id}")
        assert res.status_code == 400, res

        # Test with authentication
        res = self.client.get(f"/api/2/tags/{self.entity.id}", headers=self.headers)
        assert res.status_code == 200, res
        assert res.json["total"] == 0, res.json

    def test_tags_get_by_entity_results(self):
        other_role, _ = self.login("tester2")

        # Create tags for the entity from different users
        tags = [
            Tag(
                entity_id=self.entity.id,
                collection_id=self.collection.id,
                role_id=self.role.id,
                tag="politician",
                created_at=datetime.datetime(2020, 1, 1),
            ),
            Tag(
                entity_id=self.entity.id,
                collection_id=self.collection.id,
                role_id=other_role.id,
                tag="leader",
                created_at=datetime.datetime(2020, 1, 2),
            ),
            Tag(
                entity_id=self.entity2.id,  # Different entity
                collection_id=self.collection.id,
                role_id=self.role.id,
                tag="american",
            ),
        ]
        db.session.add_all(tags)
        db.session.commit()

        res = self.client.get(f"/api/2/tags/{self.entity.id}", headers=self.headers)
        assert res.status_code == 200, res
        assert res.json["total"] == 2, res.json  # Only tags for this entity

        # Should be ordered by creation date (newest first)
        results = res.json["results"]
        assert results[0]["tag"] == "leader"
        assert results[1]["tag"] == "politician"

    def test_tags_get_by_entity_access_control(self):
        other_role = self.create_user(foreign_id="other")
        secret_collection = self.create_collection(other_role, label="Top Secret")

        data = {"schema": "Person", "properties": {"name": ["Mister X"]}}
        secret_entity = self.create_entity(data, secret_collection)
        upsert_entity(secret_entity.to_proxy().to_dict(), secret_collection)

        # Test access to entity user doesn't have permission for
        res = self.client.get(f"/api/2/tags/{secret_entity.id}", headers=self.headers)
        assert res.status_code == 400, res
        assert "Could not tag the given entity" in res.json["message"]

    def test_tags_create(self):
        count = Tag.query.count()
        assert count == 0, count

        res = self.client.post(
            "/api/2/tags",
            headers=self.headers,
            data=json.dumps({"entity_id": self.entity.id, "tag": "politician"}),
            content_type=JSON,
        )
        assert res.status_code == 201, res
        assert res.json["tag"] == "politician"
        assert res.json["entity_id"] == self.entity.id

        count = Tag.query.count()
        assert count == 1, count
        tag = Tag.query.first()
        assert tag.entity_id == self.entity.id, tag.entity_id
        assert tag.role_id == self.role.id, tag.role_id
        assert tag.tag == "politician", tag.tag

    def test_tags_create_missing_tag(self):
        res = self.client.post(
            "/api/2/tags",
            headers=self.headers,
            data=json.dumps({"entity_id": self.entity.id}),
            content_type=JSON,
        )
        assert res.status_code == 400, res
        assert "Error during data validation" in res.json["message"]

        count = Tag.query.count()
        assert count == 0, count

    def test_tags_create_validate_access(self):
        other_role = self.create_user(foreign_id="other")
        secret_collection = self.create_collection(other_role, label="Top Secret")

        data = {"schema": "Person", "properties": {"name": ["Mister X"]}}
        secret_entity = self.create_entity(data, secret_collection)
        upsert_entity(secret_entity.to_proxy().to_dict(), secret_collection)

        res = self.client.post(
            "/api/2/tags",
            headers=self.headers,
            data=json.dumps({"entity_id": secret_entity.id, "tag": "secret"}),
            content_type=JSON,
        )
        assert res.status_code == 400, res
        message = res.json["message"]
        assert message.startswith("Could not tag the given entity"), message

        count = Tag.query.count()
        assert count == 0, count

    def test_tags_create_validate_exists(self):
        invalid_entity_id = self.create_entity(
            {"schema": "Company"}, self.collection
        ).id

        res = self.client.post(
            "/api/2/tags",
            headers=self.headers,
            data=json.dumps({"entity_id": invalid_entity_id, "tag": "company"}),
            content_type=JSON,
        )
        assert res.status_code == 400, res
        message = res.json["message"]
        assert message.startswith("Could not tag the given entity"), message

        count = Tag.query.count()
        assert count == 0, count

    def test_tags_create_idempotent(self):
        count = Tag.query.count()
        assert count == 0, count

        # Create the same tag twice
        tag_data = {"entity_id": self.entity.id, "tag": "politician"}

        res = self.client.post(
            "/api/2/tags",
            headers=self.headers,
            data=json.dumps(tag_data),
            content_type=JSON,
        )
        assert res.status_code == 201, res

        count = Tag.query.count()
        assert count == 1, count

        # Second creation should return existing tag
        res = self.client.post(
            "/api/2/tags",
            headers=self.headers,
            data=json.dumps(tag_data),
            content_type=JSON,
        )
        assert res.status_code == 200, res  # 200, not 201

        count = Tag.query.count()
        assert count == 1, count  # Still only one tag

    def test_tags_delete_by_entity_and_tag(self):
        other_role, _ = self.login("tester2")

        # Create tags
        tags = [
            Tag(
                entity_id=self.entity.id,
                collection_id=self.collection.id,
                role_id=self.role.id,
                tag="politician",
            ),
            Tag(
                entity_id=self.entity.id,
                collection_id=self.collection.id,
                role_id=other_role.id,
                tag="politician",
            ),
            Tag(
                entity_id=self.entity.id,
                collection_id=self.collection.id,
                role_id=self.role.id,
                tag="german",
            ),
        ]
        db.session.add_all(tags)
        db.session.commit()

        count = Tag.query.count()
        assert count == 3, count

        # Delete all "politician" tags for this entity
        res = self.client.delete(
            f"/api/2/tags/{self.entity.id}/politician", headers=self.headers
        )
        assert res.status_code == 204, res

        count = Tag.query.count()
        assert count == 1, count  # Only "german" tag should remain

        remaining_tag = Tag.query.first()
        assert remaining_tag.tag == "german"

    def test_tags_delete_by_entity(self):
        other_role, _ = self.login("tester2")

        # Create tags for multiple entities
        tags = [
            Tag(
                entity_id=self.entity.id,
                collection_id=self.collection.id,
                role_id=self.role.id,
                tag="politician",
            ),
            Tag(
                entity_id=self.entity.id,
                collection_id=self.collection.id,
                role_id=other_role.id,
                tag="leader",
            ),
            Tag(
                entity_id=self.entity2.id,  # Different entity
                collection_id=self.collection.id,
                role_id=self.role.id,
                tag="american",
            ),
        ]
        db.session.add_all(tags)
        db.session.commit()

        count = Tag.query.count()
        assert count == 3, count

        # Delete all tags for entity1
        res = self.client.delete(f"/api/2/tags/{self.entity.id}", headers=self.headers)
        assert res.status_code == 204, res

        count = Tag.query.count()
        assert count == 1, count  # Only entity2 tag should remain

        remaining_tag = Tag.query.first()
        assert remaining_tag.entity_id == self.entity2.id
        assert remaining_tag.tag == "american"

    def test_tags_delete_idempotent(self):
        count = Tag.query.count()
        assert count == 0, count

        # Delete non-existent tag
        res = self.client.delete(
            f"/api/2/tags/{self.entity.id}/nonexistent", headers=self.headers
        )
        assert res.status_code == 204, res

        # Delete all tags for non-existent or tagless entity
        res = self.client.delete(f"/api/2/tags/{self.entity.id}", headers=self.headers)
        assert res.status_code == 204, res

        count = Tag.query.count()
        assert count == 0, count

    def test_tags_different_users_same_tag(self):
        other_role, other_headers = self.login("tester2")
        self.grant(self.collection, other_role, True, False)

        # Both users tag the same entity with the same tag
        tag_data = {"entity_id": self.entity.id, "tag": "politician"}

        # First user creates tag
        res = self.client.post(
            "/api/2/tags",
            headers=self.headers,
            data=json.dumps(tag_data),
            content_type=JSON,
        )
        assert res.status_code == 201, res

        # Second user creates same tag
        res = self.client.post(
            "/api/2/tags",
            headers=other_headers,
            data=json.dumps(tag_data),
            content_type=JSON,
        )
        assert res.status_code == 201, res

        count = Tag.query.count()
        assert count == 2, count  # Two separate tag instances

        # Both should see the tag when querying by entity
        res = self.client.get(f"/api/2/tags/{self.entity.id}", headers=self.headers)
        assert res.status_code == 200, res
        assert res.json["total"] == 2, res.json

    def test_tags_collection_ordering_by_count(self):
        # Create tags with different frequencies
        tags = [
            # "popular" tag appears 3 times
            Tag(
                entity_id=self.entity.id,
                collection_id=self.collection.id,
                role_id=self.role.id,
                tag="popular",
            ),
            Tag(
                entity_id=self.entity2.id,
                collection_id=self.collection.id,
                role_id=self.role.id,
                tag="popular",
            ),
            Tag(
                entity_id=self.entity.id,
                collection_id=self.collection.id,
                role_id=self.role.id,
                tag="rare",
            ),
        ]

        # Add a third entity for more popular tags
        data3 = {"schema": "Person", "properties": {"name": "Test Person"}}
        entity3 = self.create_entity(data=data3, collection=self.collection)
        upsert_entity(entity3.to_proxy().to_dict(), self.collection)

        tags.append(
            Tag(
                entity_id=entity3.id,
                collection_id=self.collection.id,
                role_id=self.role.id,
                tag="popular",
            )
        )

        db.session.add_all(tags)
        db.session.commit()

        res = self.client.get(
            f"/api/2/tags?collection_id={self.collection.id}", headers=self.headers
        )
        assert res.status_code == 200, res
        assert res.json["total"] == 2, res.json

        results = res.json["results"]
        # Should be ordered by count desc, then alphabetically
        assert results[0]["tag"] == "popular"
        assert results[0]["count"] == 3
        assert results[1]["tag"] == "rare"
        assert results[1]["count"] == 1

    def test_taggable_validation_all_endpoints(self):
        """Test that all tagging operations respect the collection's taggable flag"""
        # Setup: Make collection non-taggable (default is False)
        from aleph.core import db

        self.collection.taggable = False
        db.session.add(self.collection)
        db.session.commit()

        # Test 1: GET /api/2/tags should fail on non-taggable collection
        res = self.client.get(
            f"/api/2/tags?collection_id={self.collection.id}", headers=self.headers
        )
        assert res.status_code == 400, res
        assert "Tagging is disabled" in res.json["message"]

        # Test 2: POST /api/2/tags should fail on non-taggable collection
        tag_data = {"entity_id": self.entity.id, "tag": "test-tag"}
        res = self.client.post(
            "/api/2/tags",
            headers=self.headers,
            data=json.dumps(tag_data),
            content_type=JSON,
        )
        assert res.status_code == 400, res
        assert "tagging is disabled" in res.json["message"]

        # Test 3: GET /api/2/tags/{entity_id} should fail on non-taggable collection
        res = self.client.get(f"/api/2/tags/{self.entity.id}", headers=self.headers)
        assert res.status_code == 400, res
        assert "tagging is disabled" in res.json["message"]

        # Test 4: DELETE operations should also fail on non-taggable collection
        res = self.client.delete(
            f"/api/2/tags/{self.entity.id}/test-tag", headers=self.headers
        )
        assert res.status_code == 400, res
        assert "tagging is disabled" in res.json["message"]

        res = self.client.delete(f"/api/2/tags/{self.entity.id}", headers=self.headers)
        assert res.status_code == 400, res
        assert "tagging is disabled" in res.json["message"]

        # Now enable tagging on the collection
        self.collection.taggable = True
        db.session.add(self.collection)
        db.session.commit()

        # Test 5: All operations should now work on taggable collection
        # GET /api/2/tags should work
        res = self.client.get(
            f"/api/2/tags?collection_id={self.collection.id}", headers=self.headers
        )
        assert res.status_code == 200, res

        # POST /api/2/tags should work
        res = self.client.post(
            "/api/2/tags",
            headers=self.headers,
            data=json.dumps(tag_data),
            content_type=JSON,
        )
        assert res.status_code == 201, res
        assert res.json["tag"] == "test-tag"

        # GET /api/2/tags/{entity_id} should work
        res = self.client.get(f"/api/2/tags/{self.entity.id}", headers=self.headers)
        assert res.status_code == 200, res
        assert res.json["total"] == 1

        # DELETE operations should work
        res = self.client.delete(
            f"/api/2/tags/{self.entity.id}/test-tag", headers=self.headers
        )
        assert res.status_code == 204, res

        # Verify tag was deleted
        res = self.client.get(f"/api/2/tags/{self.entity.id}", headers=self.headers)
        assert res.status_code == 200, res
        assert res.json["total"] == 0

    def test_filter_entities_by_tags(self):
        """Test filtering entities using the tags filter in entities API"""
        # Create tags for different entities using the tags API
        # Tag entity1 with "politician"
        res = self.client.post(
            "/api/2/tags",
            headers=self.headers,
            data=json.dumps({"entity_id": self.entity.id, "tag": "politician"}),
            content_type=JSON,
        )
        assert res.status_code == 201, res

        # Tag entity1 with "german"
        res = self.client.post(
            "/api/2/tags",
            headers=self.headers,
            data=json.dumps({"entity_id": self.entity.id, "tag": "german"}),
            content_type=JSON,
        )
        assert res.status_code == 201, res

        # Tag entity2 with "politician"
        res = self.client.post(
            "/api/2/tags",
            headers=self.headers,
            data=json.dumps({"entity_id": self.entity2.id, "tag": "politician"}),
            content_type=JSON,
        )
        assert res.status_code == 201, res

        # Test filtering by specific tag using entities API
        res = self.client.get(
            f"/api/2/entities?filter:tags=politician&filter:collection_id={self.collection.id}",
            headers=self.headers,
        )
        assert res.status_code == 200, res
        # Should return both entities tagged with "politician"
        assert res.json["total"] == 2, res.json

        entity_ids = [entity["id"] for entity in res.json["results"]]
        assert self.entity.id in entity_ids
        assert self.entity2.id in entity_ids

        # Test filtering by tag that only applies to one entity
        res = self.client.get(
            f"/api/2/entities?filter:tags=german&filter:collection_id={self.collection.id}",
            headers=self.headers,
        )
        assert res.status_code == 200, res
        # Should return only one entity tagged with "german"
        assert res.json["total"] == 1, res.json
        assert res.json["results"][0]["id"] == self.entity.id

        # Test filtering by non-existent tag
        res = self.client.get(
            f"/api/2/entities?filter:tags=nonexistent&filter:collection_id={self.collection.id}",
            headers=self.headers,
        )
        assert res.status_code == 200, res
        # Should return no entities
        assert res.json["total"] == 0, res.json

        # Test combining tag filter with text search
        res = self.client.get(
            f"/api/2/entities?q=Angela&filter:tags=politician&filter:collection_id={self.collection.id}",
            headers=self.headers,
        )
        assert res.status_code == 200, res
        # Should return only Angela Merkel (entity with "politician" tag and matching name)
        assert res.json["total"] == 1, res.json
        assert res.json["results"][0]["id"] == self.entity.id
