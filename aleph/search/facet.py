import logging

from followthemoney import model
from followthemoney.types import registry

from aleph.logic import resolver
from aleph.model import Collection, Entity, Events
from aleph.util import make_entity_proxy

log = logging.getLogger(__name__)


class Facet(object):
    def __init__(self, name, aggregations, parser):
        self.name = name
        self.parser = parser
        self.aggregations = aggregations
        self.data = self.extract(aggregations, name, "values")
        self.cardinality = self.extract(aggregations, name, "cardinality")
        self.intervals = self.extract(aggregations, name, "intervals")

    def extract(self, aggregations, name, sub):
        if aggregations is None:
            return {}
        aggregations = aggregations.get("%s.filtered" % name, aggregations)
        data = aggregations.get("scoped", {}).get(name, {}).get(name)
        field = "%s.%s" % (name, sub)
        return data or aggregations.get(field, {})

    def extract_significant_terms(self):
        """Extract significant terms aggregation data"""
        if self.aggregations is None:
            return {}

        # For significant terms, we need to access the aggregation directly
        # The name format is 'field.significant_terms'
        return self.aggregations.get(self.name, {})

    def expand(self, keys):
        pass

    def update(self, result, key):
        pass

    def get_key(self, bucket):
        return str(bucket.get("key"))

    def to_dict(self):
        active = list(self.parser.filters.get(self.name, []))
        data = {"filters": active}

        if self.name.endswith(".significant_terms"):
            return self._handle_significant_terms(data, active)

        self._add_total_if_needed(data)
        self._add_values_if_needed(data, active)
        self._add_intervals_if_needed(data, active)

        return data

    def _handle_significant_terms(self, data, active):
        significant_data = self.extract_significant_terms()
        if not significant_data:
            return data

        results = self._build_significant_terms_results(significant_data, active)
        self._expand_and_update_results(results)
        data["values"] = results
        return data

    def _build_significant_terms_results(self, significant_data, active):
        results = []
        for bucket in significant_data.get("buckets", []):
            key = self.get_key(bucket)
            results.append(
                {
                    "id": key,
                    "label": key,
                    "count": bucket.get("doc_count", 0),
                    "score": bucket.get("score", 0),
                    "active": key in active,
                }
            )
        return results

    def _add_total_if_needed(self, data):
        if self.parser.get_facet_total(self.name):
            data["total"] = self.cardinality.get("value")

    def _add_values_if_needed(self, data, active):
        if not self.parser.get_facet_values(self.name):
            return

        results = self._build_bucket_results(active)
        self._add_missing_active_filters(results, active)
        self._expand_and_update_results(results)
        data["values"] = results

    def _build_bucket_results(self, active):
        results = []
        for bucket in self.data.get("buckets", []):
            key = self.get_key(bucket)
            results.append(
                {
                    "id": key,
                    "label": key,
                    "count": bucket.pop("doc_count", 0),
                    "active": key in active,
                }
            )
            if key in active:
                active.remove(key)
        return results

    def _add_missing_active_filters(self, results, active):
        for key in active:
            results.insert(0, {"id": key, "label": key, "count": 0, "active": True})

    def _expand_and_update_results(self, results):
        self.expand([r.get("id") for r in results])
        for result in results:
            self.update(result, result.get("id"))

    def _add_intervals_if_needed(self, data, active):
        if not self.parser.get_facet_interval(self.name):
            return

        results = []
        for bucket in self.intervals.get("buckets", []):
            key = str(bucket.get("key_as_string"))
            count = bucket.pop("doc_count", 0)
            results.append(
                {"id": key, "label": key, "count": count, "active": key in active}
            )
        data["intervals"] = sorted(results, key=lambda k: k["id"])


class SchemaFacet(Facet):
    def update(self, result, key):
        try:
            result["label"] = model.get(key).plural
        except AttributeError:
            result["label"] = key


class CountryFacet(Facet):
    def update(self, result, key):
        result["label"] = registry.country.names.get(key, key)


class EventFacet(Facet):
    def update(self, result, key):
        event = Events.get(key)
        result["label"] = key if event is None else event.title


class EntityFacet(Facet):
    def expand(self, keys):
        for key in keys:
            resolver.queue(self.parser, Entity, key)
        resolver.resolve(self.parser)

    def update(self, result, key):
        entity = resolver.get(self.parser, Entity, key)
        if entity is not None:
            proxy = make_entity_proxy(entity)
            result["label"] = proxy.caption


class LanguageFacet(Facet):
    def update(self, result, key):
        result["label"] = registry.language.names.get(key, key)


class CategoryFacet(Facet):
    def update(self, result, key):
        result["label"] = Collection.CATEGORIES.get(key, key)


class CollectionFacet(Facet):
    def expand(self, keys):
        for key in keys:
            if int(key) in self.parser.auth.collection_ids:
                resolver.queue(self.parser, Collection, key)
        resolver.resolve(self.parser)

    def update(self, result, key):
        collection = resolver.get(self.parser, Collection, key)
        if collection is not None:
            result["label"] = collection.get("label")
            result["category"] = collection.get("category")


class NameFacet(Facet):
    def update(self, result, key):
        # make names look nicer
        result["label"] = key.title()
