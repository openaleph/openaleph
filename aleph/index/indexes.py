import logging
from copy import deepcopy

from banal import ensure_list
from followthemoney import model
from followthemoney.exc import InvalidData
from followthemoney.schema import Schema
from followthemoney.types import registry

from aleph.index.util import (
    GEOPOINT,
    KEYWORD,
    LATIN_TEXT,
    NUMERIC,
    NUMERIC_TYPES,
    PARTIAL_DATE,
    configure_index,
    get_shard_weight,
    index_name,
    index_settings,
)
from aleph.settings import SETTINGS

log = logging.getLogger(__name__)

TYPE_MAPPINGS = {
    registry.text: {"type": "text", "index": False},
    registry.html: {"type": "text", "index": False},
    registry.json: {"type": "text", "index": False},
    registry.date: PARTIAL_DATE,
}


def schema_index(schema, version):
    """Convert a schema object to an index name."""
    if schema.abstract:
        raise InvalidData("Cannot index abstract schema: %s" % schema)
    name = "entity-%s" % schema.name.lower()
    return index_name(name, version=version)


def schema_scope(schema, expand=True):
    schemata = set()
    names = ensure_list(schema) or model.schemata.values()
    for schema in names:
        schema = model.get(schema)
        if schema is not None:
            schemata.add(schema)
            if expand:
                schemata.update(schema.descendants)
    for schema in schemata:
        if not schema.abstract:
            yield schema


def entities_index_list(schema=None, expand=True):
    """Combined index to run all queries against."""
    for schema_ in schema_scope(schema, expand=expand):
        for version in SETTINGS.INDEX_READ:
            yield schema_index(schema_, version)


def entities_read_index(schema=None, expand=True):
    indexes = entities_index_list(schema=schema, expand=expand)
    return ",".join(indexes)


def entities_write_index(schema):
    """Index that us currently written by new queries."""
    schema = model.get(schema)
    return schema_index(schema, SETTINGS.INDEX_WRITE)


def configure_entities():
    for schema in model.schemata.values():
        if not schema.abstract:
            for version in SETTINGS.INDEX_READ:
                configure_schema(schema, version)


def configure_schema(schema: Schema, version):
    # Generate relevant type mappings for entity properties so that
    # we can do correct searches on each.
    schema_mapping = {}
    numeric_mapping = {registry.date.group: NUMERIC}
    for prop in schema.properties.values():
        config = deepcopy(TYPE_MAPPINGS.get(prop.type, KEYWORD))
        config["copy_to"] = ["text"]
        schema_mapping[prop.name] = config
        if prop.type in NUMERIC_TYPES:
            numeric_mapping[prop.name] = deepcopy(NUMERIC)

    mapping = {
        "date_detection": False,
        "dynamic": False,
        "_source": {"excludes": ["text", "fingerprints"]},
        "properties": {
            "caption": KEYWORD,
            "schema": KEYWORD,
            "schemata": KEYWORD,
            registry.entity.group: KEYWORD,
            registry.language.group: KEYWORD,
            registry.country.group: KEYWORD,
            registry.checksum.group: KEYWORD,
            registry.ip.group: KEYWORD,
            registry.url.group: KEYWORD,
            registry.email.group: KEYWORD,
            registry.phone.group: KEYWORD,
            registry.mimetype.group: KEYWORD,
            registry.identifier.group: KEYWORD,
            registry.date.group: PARTIAL_DATE,
            registry.address.group: KEYWORD,
            registry.name.group: KEYWORD,
            "fingerprints": {
                "type": "keyword",
                "normalizer": "latin_index",
                "copy_to": "text",
                "fields": {"text": LATIN_TEXT},
            },
            "text": {
                "type": "text",
                "analyzer": "latin_index",
                "search_analyzer": "latin_query",
                "search_quote_analyzer": "latin_index",
                "term_vector": "with_positions_offsets",
            },
            "properties": {"type": "object", "properties": schema_mapping},
            "numeric": {"type": "object", "properties": numeric_mapping},
            "role_id": KEYWORD,
            "profile_id": KEYWORD,
            "collection_id": KEYWORD,
            "origin": KEYWORD,
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        },
    }

    # Add geopoint field for Address or RealEstate schema
    if "longitude" in schema.properties:
        mapping["properties"]["geo_point"] = GEOPOINT

    index = schema_index(model.get(schema), version)
    settings = index_settings(shards=get_shard_weight(schema))
    return configure_index(index, mapping, settings)
