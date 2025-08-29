import logging
from tempfile import NamedTemporaryFile
from uuid import uuid4

from flask import render_template
from rigour.mime.types import HTML

from aleph import settings
from aleph.core import archive
from aleph.logic.resolver import cached_entities_by_ids

log = logging.getLogger(__name__)
FIELDS = ["id", "schema", "properties"]


def publish_diagram(entityset):
    embed = render_diagram(entityset)
    with NamedTemporaryFile("w") as fh:
        fh.write(embed)
        fh.flush()
        publish_id = uuid4().hex
        embed_path = f"embeds/{entityset.id}/{publish_id}.html"
        url = archive.publish_file(fh.name, embed_path, mime_type=HTML)
    return {"embed": embed, "url": url}


def render_diagram(entityset):
    """Generate an HTML snippet from a diagram object."""
    entity_ids = entityset.entities
    entities = []
    for entity in cached_entities_by_ids(entity_ids):
        for field in list(entity.keys()):
            if field not in FIELDS:
                entity.pop(field)
        entities.append(entity)

    # TODO: add viewport
    return render_template(
        "diagram.html",
        data={
            "entities": entities,
            "layout": entityset.layout,
            "viewport": {"center": {"x": 0, "y": 0}},
        },
        entityset=entityset,
        settings=settings,
    )
