import json
import logging
from itertools import count
from pathlib import Path

import click
from flask.cli import FlaskGroup
from followthemoney.cli.util import write_object
from normality import slugify
from openaleph_search.index.admin import delete_index
from openaleph_search.index.entities import get_entity as _get_index_entity
from openaleph_search.index.entities import iter_proxies
from tabulate import tabulate

from aleph.authz import Authz
from aleph.core import cache, create_app, db
from aleph.index.collections import get_collection as _get_index_collection
from aleph.logic.aggregator import get_aggregator
from aleph.logic.archive import cleanup_archive
from aleph.logic.collections import (
    aggregate_model,
    compute_collection,
    create_collection,
    delete_collection,
)
from aleph.logic.collections import index_diff as _index_diff
from aleph.logic.collections import (
    reindex_collection,
    reingest_collection,
    update_collection,
    upgrade_collections,
    validate_collection_foreign_ids,
)
from aleph.logic.documents import crawl_directory
from aleph.logic.entities import index_entity
from aleph.logic.export import retry_exports
from aleph.logic.mapping import cleanup_mappings
from aleph.logic.permissions import update_permission
from aleph.logic.processing import bulk_write
from aleph.logic.roles import (
    create_group,
    create_user,
    delete_role,
    rename_user,
    update_roles,
    user_add,
    user_del,
)
from aleph.logic.xref import xref_collection
from aleph.migration import cleanup_deleted, destroy_db, upgrade_system
from aleph.model import Collection, EntitySet, Role
from aleph.model.document import Document
from aleph.procrastinate.queues import (
    queue_cancel_collection,
    queue_ingest,
    queue_reindex,
)
from aleph.procrastinate.status import get_collection_status, get_status
from aleph.util import JSONEncoder

log = logging.getLogger("aleph")


def get_expanded_entity(entity_id):
    if not entity_id:
        return None
    entity = _get_index_entity(entity_id)
    if entity is None:
        return None
    entity.pop("_index", None)
    entity["collection"] = _get_index_collection(entity["collection_id"])
    return entity


def get_collection(foreign_id):
    collection = Collection.by_foreign_id(foreign_id, deleted=True)
    if collection is None:
        raise click.BadParameter("No such collection: %r" % foreign_id)
    return collection


def ensure_collection(foreign_id, label):
    collection = Collection.by_foreign_id(foreign_id, deleted=True)
    if collection is None:
        authz = Authz.from_role(Role.load_cli_user())
        config = {
            "foreign_id": foreign_id,
            "label": label,
        }
        create_collection(config, authz)
        return Collection.by_foreign_id(foreign_id)
    return collection


@click.group(cls=FlaskGroup, create_app=create_app)
def cli():
    """Server-side command line for aleph."""


@cli.command()
@click.option(
    "--secret",
    type=bool,
    default=None,
    help="Whether to list secret collections (None means disregard the flag)",
)
@click.option(
    "--casefile",
    type=bool,
    default=None,
    help="Whether to list casefiles (None means disregard the flag)",
)
def collections(secret, casefile):
    """List all collections."""
    collections = []
    for coll in Collection.all():
        if secret is not None:
            if coll.secret != secret:
                continue
        if casefile is not None:
            if coll.casefile != casefile:
                continue
        collections.append((coll.foreign_id, coll.id, coll.label))
    print(tabulate(collections, headers=["Foreign ID", "ID", "Label"]))


@cli.command("validate-foreign-ids")
@click.option(
    "-o",
    "--outfile",
    type=click.File("w"),
    default=None,
    help="Output invalid collections to JSON file",
)
def validate_foreign_ids(outfile=None):
    """Validate all collection foreign IDs using dataset_name_check."""
    invalid_collections = validate_collection_foreign_ids()

    if invalid_collections:
        print(f"Found {len(invalid_collections)} collections with invalid foreign IDs:")
        headers = ["ID", "Foreign ID", "Label", "Error"]
        rows = []
        for collection in invalid_collections:
            rows.append(
                [
                    collection["id"],
                    collection["foreign_id"],
                    collection["label"],
                    collection["error"],
                ]
            )
        print(tabulate(rows, headers=headers))

        if outfile:
            encoder = JSONEncoder(indent=2)
            outfile.write(encoder.encode(invalid_collections))
            print(f"\nInvalid collections exported to {outfile.name}")

        return 1  # Exit with error code
    else:
        print("All collection foreign IDs are valid.")
        return 0


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("-l", "--language", multiple=True, help="ISO language codes for OCR")
@click.option("-f", "--foreign_id", help="Foreign ID of the collection")
def crawldir(path, language=None, foreign_id=None):
    """Crawl the given directory."""
    path = Path(path)
    if foreign_id is None:
        foreign_id = "directory:%s" % slugify(path)
    collection = ensure_collection(foreign_id, path.name)
    log.info("Crawling %s to %s (%s)...", path, foreign_id, collection.id)
    crawl_directory(collection, path)
    log.info("Complete. Make sure a worker is running :)")
    update_collection(collection)


@cli.command()
@click.argument("foreign_id")
@click.option("--sync/--async", default=False)
def delete(foreign_id, sync=False):
    """Delete a given collection."""
    collection = get_collection(foreign_id)
    delete_collection(collection, sync=sync)


@cli.command()
@click.argument("foreign_id")
@click.option("--sync/--async", default=True)
def touch(foreign_id, sync=True):
    """Mark a collection as changed."""
    collection = get_collection(foreign_id)
    collection.touch()
    db.session.commit()
    compute_collection(collection, force=True, sync=True)


@cli.command()
@click.argument("foreign_id")
@click.option("--sync/--async", default=False)
def flush(foreign_id, sync=False):
    """Flush all the contents for a given collection."""
    collection = get_collection(foreign_id)
    delete_collection(collection, keep_metadata=True, sync=sync)


@cli.command("aggregate-model")
@click.argument("foreign_id")
def aggregate_model_command(foreign_id):
    """Aggregate model entities (Documents and Entities) to the FTM store.

    This syncs up the aggregator from the Aleph domain model by reading all
    Document and Entity records from the database and writing them to the
    collection's FTM store (aggregator).
    """
    collection = get_collection(foreign_id)
    aggregator = get_aggregator(collection)

    log.info("[%s] Aggregating model...", collection)
    aggregate_model(collection, aggregator)
    log.info("[%s] Model aggregation complete", collection)


def _reindex_collection(
    collection,
    flush=False,
    diff_only=False,
    model=True,
    mappings=True,
    queue_batches=False,
    batch_size=10_000,
    schema=None,
    since=None,
    until=None,
):
    log.info("[%s] Starting to re-index", collection)
    try:
        reindex_collection(
            collection,
            flush=flush,
            diff_only=diff_only,
            model=model,
            mappings=mappings,
            queue_batches=queue_batches,
            batch_size=batch_size,
            schema=schema,
            since=since,
            until=until,
        )
    except Exception:
        log.exception("Failed to re-index: %s", collection)


@cli.command()
@click.argument("foreign_id")
@click.option("--flush", is_flag=True, default=False)
@click.option("--model/--no-model", is_flag=True, default=True)
@click.option("--mappings/--no-mappings", is_flag=True, default=True)
@click.option(
    "--diff-only",
    is_flag=True,
    default=False,
    help="Only reindex entities that are in aggregator but not in index",
)
@click.option(
    "--queue-batches",
    is_flag=True,
    default=False,
    help="Queue batches for parallel processing",
)
@click.option(
    "--batch-size",
    type=int,
    default=10_000,
    help="Batch size for processing entities (default: 10000)",
)
@click.option(
    "-s",
    "--schema",
    type=str,
    default=None,
    help="Filter entities by schema (e.g., Person, Company)",
)
@click.option(
    "--since",
    type=str,
    default=None,
    help=(
        "Filter entities modified since this time. "
        "Accepts: ISO dates, Unix timestamps, relative dates (e.g., '1d', '2 weeks ago')"
    ),
)
@click.option(
    "--until",
    type=str,
    default=None,
    help=(
        "Filter entities modified until this time. "
        "Accepts: ISO dates, Unix timestamps, relative dates (e.g., '1d', '2 weeks ago')"
    ),
)
def reindex(
    foreign_id,
    flush=False,
    diff_only=False,
    model=True,
    mappings=True,
    queue_batches=False,
    batch_size=10_000,
    schema=None,
    since=None,
    until=None,
):
    """Index all the aggregator contents for a collection."""
    collection = get_collection(foreign_id)
    _reindex_collection(
        collection,
        flush=flush,
        diff_only=diff_only,
        model=model,
        mappings=mappings,
        queue_batches=queue_batches,
        batch_size=batch_size,
        schema=schema,
        since=since,
        until=until,
    )


def _write_entity_ids(entity_ids, output_file, description):
    """Write entity IDs to file, sorted one per line."""
    sorted_ids = sorted(entity_ids)
    for entity_id in sorted_ids:
        output_file.write(f"{entity_id}\n")
    log.info("Wrote %d %s to %s", len(sorted_ids), description, output_file.name)


def _compute_diff_stats(collection) -> dict[str, int]:
    """Compute diff statistics from the streaming index_diff generator.

    Returns a dict with counts and lists of entity IDs.
    """
    aggregator_ids = 0
    index_ids = 0
    in_both = 0
    only_in_aggregator = 0
    only_in_index = 0

    for aggregator_id, index_id in _index_diff(collection):
        if aggregator_id is not None and index_id is not None:
            aggregator_ids += 1
            index_ids += 1
            in_both += 1
        elif aggregator_id is not None:
            # Only in aggregator
            aggregator_ids += 1
            only_in_aggregator += 1
        elif index_id is not None:
            # Only in index
            index_ids += 1
            only_in_index += 1

    return {
        "aggregator_ids": aggregator_ids,
        "index_ids": index_ids,
        "in_both": in_both,
        "only_in_aggregator": only_in_aggregator,
        "only_in_index": only_in_index,
    }


def _collect_diff_ids(collection) -> dict[str, list[str]]:
    """Collect entity IDs from diff for file output.

    Returns lists of entity IDs categorized by their location.
    """
    aggregator_ids = []
    index_ids = []
    only_in_aggregator = []
    only_in_index = []

    for aggregator_id, index_id in _index_diff(collection):
        if aggregator_id is not None:
            aggregator_ids.append(aggregator_id)
        if index_id is not None:
            index_ids.append(index_id)

        if aggregator_id is not None and index_id is None:
            only_in_aggregator.append(aggregator_id)
        elif index_id is not None and aggregator_id is None:
            only_in_index.append(index_id)

    return {
        "aggregator_ids": aggregator_ids,
        "index_ids": index_ids,
        "only_in_aggregator": only_in_aggregator,
        "only_in_index": only_in_index,
    }


@cli.command("index-diff")
@click.argument("foreign_id")
def index_diff(foreign_id):
    """Compare entity IDs between aggregator and search index (streaming stats only).

    For exporting IDs to files, use the 'export-index-diff' command instead.
    """
    collection = get_collection(foreign_id)

    log.info("[%s] Computing diff counts...", collection)
    diff = _compute_diff_stats(collection)

    # Display results
    log.info(
        "[%s] Index Diff Report:\n"
        "  Total in aggregator:        %10d\n"
        "  Total in index:             %10d\n"
        "  In both:                    %10d\n"
        "  Only in aggregator:         %10d\n"
        "  Only in index:              %10d",
        collection,
        diff["aggregator_ids"],
        diff["index_ids"],
        diff["in_both"],
        diff["only_in_aggregator"],
        diff["only_in_index"],
    )


@cli.command("export-index-diff")
@click.argument("foreign_id")
@click.option(
    "--aggregator-ids",
    type=click.File("w"),
    default=None,
    help="Output file for all aggregator IDs (sorted, one per line)",
)
@click.option(
    "--index-ids",
    type=click.File("w"),
    default=None,
    help="Output file for all index IDs (sorted, one per line)",
)
@click.option(
    "--only-aggregator",
    type=click.File("w"),
    default=None,
    help="Output file for IDs only in aggregator (sorted, one per line)",
)
@click.option(
    "--only-index",
    type=click.File("w"),
    default=None,
    help="Output file for IDs only in index (sorted, one per line)",
)
def export_index_diff(
    foreign_id,
    aggregator_ids=None,
    index_ids=None,
    only_aggregator=None,
    only_index=None,
):
    """Export entity IDs from index diff to files.

    This command collects all entity IDs in memory and writes them to the
    requested output files. For quick stats without file output, use 'index-diff'.
    """
    collection = get_collection(foreign_id)

    if not any([aggregator_ids, index_ids, only_aggregator, only_index]):
        log.error(
            "At least one output file must be specified. "
            "Available options: --aggregator-ids, --index-ids, --only-aggregator, --only-index"
        )
        return

    log.info("[%s] Collecting entity IDs...", collection)
    id_lists = _collect_diff_ids(collection)

    outputs = [
        (aggregator_ids, id_lists["aggregator_ids"], "aggregator IDs"),
        (index_ids, id_lists["index_ids"], "index IDs"),
        (only_aggregator, id_lists["only_in_aggregator"], "only-in-aggregator IDs"),
        (only_index, id_lists["only_in_index"], "only-in-index IDs"),
    ]
    for output_file, entity_ids, description in outputs:
        if output_file:
            _write_entity_ids(entity_ids, output_file, description)

    # Display summary
    log.info(
        "[%s] Export Summary:\n"
        "  Total in aggregator:        %10d\n"
        "  Total in index:             %10d\n"
        "  Only in aggregator:         %10d\n"
        "  Only in index:              %10d",
        collection,
        len(id_lists["aggregator_ids"]),
        len(id_lists["index_ids"]),
        len(id_lists["only_in_aggregator"]),
        len(id_lists["only_in_index"]),
    )


@cli.command("index-diff-all")
@click.option(
    "--casefile",
    type=bool,
    default=None,
    help="Filter by casefiles (None means all)",
)
def index_diff_all(casefile=None):
    """Compare entity IDs between aggregator and search index for all collections."""
    collections_list = []

    for collection in Collection.all():
        if casefile is not None and collection.casefile != casefile:
            continue

        try:
            log.info("Processing %s...", collection.foreign_id)
            diff = _compute_diff_stats(collection)
            collections_list.append(
                {
                    "foreign_id": collection.foreign_id,
                    "label": collection.label,
                    "aggregator": diff["aggregator_ids"],
                    "index": diff["index_ids"],
                    "in_both": diff["in_both"],
                    "only_aggregator": diff["only_in_aggregator"],
                    "only_index": diff["only_in_index"],
                }
            )
        except Exception as e:
            log.error("[%s] Failed to compute diff: %s", collection, e)
            collections_list.append(
                {
                    "foreign_id": collection.foreign_id,
                    "label": collection.label,
                    "aggregator": "ERROR",
                    "index": "ERROR",
                    "in_both": "ERROR",
                    "only_aggregator": "ERROR",
                    "only_index": "ERROR",
                }
            )

    # Display summary table
    headers = [
        "Foreign ID",
        "Label",
        "Aggregator",
        "Index",
        "In Both",
        "Missing from Index",
        "Orphaned in Index",
    ]
    rows = []
    for coll in collections_list:
        rows.append(
            [
                coll["foreign_id"],
                coll["label"][:30],  # Truncate long labels
                coll["aggregator"],
                coll["index"],
                coll["in_both"],
                coll["only_aggregator"],
                coll["only_index"],
            ]
        )

    table = tabulate(rows, headers=headers, tablefmt="simple")

    # Show totals
    total_aggregator = sum(
        c["aggregator"] for c in collections_list if isinstance(c["aggregator"], int)
    )
    total_index = sum(
        c["index"] for c in collections_list if isinstance(c["index"], int)
    )
    total_only_aggregator = sum(
        c["only_aggregator"]
        for c in collections_list
        if isinstance(c["only_aggregator"], int)
    )
    total_only_index = sum(
        c["only_index"] for c in collections_list if isinstance(c["only_index"], int)
    )

    log.info(
        "Index Diff Summary for All Collections:\n\n%s\n\n"
        "Totals across %d collections:\n"
        "  Total entities in aggregator:      %10d\n"
        "  Total entities in index:           %10d\n"
        "  Total missing from index:          %10d\n"
        "  Total orphaned in index:           %10d",
        table,
        len(collections_list),
        total_aggregator,
        total_index,
        total_only_aggregator,
        total_only_index,
    )


@cli.command("reindex-full")
@click.option("--flush", is_flag=True, default=False)
@click.option("--model/--no-model", is_flag=True, default=True)
@click.option("--mappings/--no-mappings", is_flag=True, default=True)
@click.option(
    "--diff-only",
    is_flag=True,
    default=False,
    help="Only reindex entities that are in aggregator but not in index",
)
@click.option(
    "--queue",
    is_flag=True,
    default=False,
    help="Queue the reindexing task for each collection, distribute them across workers.",
)
@click.option(
    "--queue-batches",
    is_flag=True,
    default=False,
    help="Queue batches for parallel processing",
)
@click.option(
    "--batch-size",
    type=int,
    default=10_000,
    help="Batch size for processing entities (default: 10000)",
)
@click.option(
    "-s",
    "--schema",
    type=str,
    default=None,
    help="Filter entities by schema (e.g., Person, Company)",
)
@click.option(
    "--since",
    type=str,
    default=None,
    help=(
        "Filter entities modified since this time. "
        "Accepts: ISO dates, Unix timestamps, relative dates (e.g., '1d', '2 weeks ago')"
    ),
)
@click.option(
    "--until",
    type=str,
    default=None,
    help=(
        "Filter entities modified until this time. "
        "Accepts: ISO dates, Unix timestamps, relative dates (e.g., '1d', '2 weeks ago')"
    ),
)
def reindex_full(
    flush=False,
    diff_only=False,
    queue=False,
    model=True,
    mappings=True,
    queue_batches=False,
    batch_size=10_000,
    schema=None,
    since=None,
    until=None,
):
    """Re-index all collections."""
    for collection in Collection.all():
        if queue:
            queue_reindex(
                collection,
                flush=flush,
                diff_only=diff_only,
                schema=schema,
                since=since,
                until=until,
            )
        else:
            _reindex_collection(
                collection,
                flush=flush,
                diff_only=diff_only,
                model=model,
                mappings=mappings,
                queue_batches=queue_batches,
                batch_size=batch_size,
                schema=schema,
                since=since,
                until=until,
            )


@cli.command("reindex-casefiles")
@click.option("--flush", is_flag=True, default=False)
@click.option("--model/--no-model", is_flag=True, default=True)
@click.option("--mappings/--no-mappings", is_flag=True, default=True)
@click.option(
    "--diff-only",
    is_flag=True,
    default=False,
    help="Only reindex entities that are in aggregator but not in index",
)
@click.option(
    "--queue",
    is_flag=True,
    default=False,
    help="Queue the reindexing task for each collection, distribute them across workers.",
)
@click.option(
    "--queue-batches",
    is_flag=True,
    default=False,
    help="Queue batches for parallel processing",
)
@click.option(
    "--batch-size",
    type=int,
    default=10_000,
    help="Batch size for processing entities (default: 10000)",
)
@click.option(
    "-s",
    "--schema",
    type=str,
    default=None,
    help="Filter entities by schema (e.g., Person, Company)",
)
@click.option(
    "--since",
    type=str,
    default=None,
    help=(
        "Filter entities modified since this time. "
        "Accepts: ISO dates, Unix timestamps, relative dates (e.g., '1d', '2 weeks ago')"
    ),
)
@click.option(
    "--until",
    type=str,
    default=None,
    help=(
        "Filter entities modified until this time. "
        "Accepts: ISO dates, Unix timestamps, relative dates (e.g., '1d', '2 weeks ago')"
    ),
)
def reindex_casefiles(
    flush=False,
    diff_only=False,
    queue=False,
    model=True,
    mappings=True,
    queue_batches=False,
    batch_size=10_000,
    schema=None,
    since=None,
    until=None,
):
    """Re-index all the casefile collections."""
    for collection in Collection.all_casefiles():
        if queue:
            queue_reindex(
                collection,
                flush=flush,
                diff_only=diff_only,
                schema=schema,
                since=since,
                until=until,
            )
        else:
            _reindex_collection(
                collection,
                flush=flush,
                diff_only=diff_only,
                model=model,
                mappings=mappings,
                queue_batches=queue_batches,
                batch_size=batch_size,
                schema=schema,
                since=since,
                until=until,
            )


@cli.command()
@click.argument("foreign_id")
@click.option("--index-flush/--no-index-flush", is_flag=True, default=True)
@click.option("--ingest-flush/--no-ingest-flush", is_flag=True, default=True)
def reingest(foreign_id, index_flush=True, ingest_flush=True):
    """Process documents and database entities and index them."""
    collection = get_collection(foreign_id)
    reingest_collection(
        collection,
        index_flush=index_flush,
        ingest_flush=ingest_flush,
    )


@cli.command()
@click.argument("document_id")
def reingest_document(document_id):
    """Re-process a specific document and re-index it (useful for debugging)."""
    document = Document.by_id(document_id)
    if document is None:
        log.error(f"Can't find document with id `{document_id}`")
        return
    queue_ingest(document.collection, document.to_proxy(), priority=1000)
    log.info(
        f"[{document.collection.name}] Queued document `{document.foreign_id}` for reingest."
    )


@cli.command("reindex-entity")
@click.argument("entity_id")
@click.option("-f", "--foreign_id", required=True, help="Foreign ID of the collection")
def reindex_entity_command(entity_id, foreign_id):
    """Re-index a specific entity by ID from the aggregator (useful for debugging)."""
    collection = get_collection(foreign_id)
    index_entity(collection, entity_id)


@cli.command("reingest-casefiles")
@click.option("--index-flush/--no-index-flush", is_flag=True, default=True)
@click.option("--ingest-flush/--no-ingest-flush", is_flag=True, default=True)
def reingest_casefiles(index_flush=True, ingest_flush=True):
    """Re-ingest all the casefile collections."""
    for collection in Collection.all_casefiles():
        log.info("[%s] Starting to re-ingest", collection)
        reingest_collection(
            collection,
            index_flush=index_flush,
            ingest_flush=ingest_flush,
        )


@cli.command()
def flushdeleted():
    """Remove soft-deleted database objects."""
    cleanup_deleted()


@cli.command()
def update():
    """Re-index all collections and clear some caches."""
    update_roles()
    upgrade_collections()
    cleanup_mappings()


@cli.command()
@click.argument("foreign_id")
def xref(foreign_id):
    """Cross-reference all entities and documents in a collection."""
    collection = get_collection(foreign_id)
    xref_collection(collection)


@cli.command("load-entities")
@click.argument("foreign_id")
@click.option("-i", "--infile", type=click.File("r"), default="-")
@click.option(
    "--safe/--unsafe",
    default=True,
    help="Allow references to archive hashes.",
)
@click.option(
    "--mutable/--immutable",
    default=False,
    help="Mark entities mutable.",
)
@click.option(
    "--clean/--unclean",
    default=False,
    help="Allow to disable (if --clean) server-side values validation for all types.",
)
def load_entities(foreign_id, infile, safe=True, mutable=False, clean=True):
    """Load FtM entities from the specified iJSON file."""
    collection = ensure_collection(foreign_id, foreign_id)

    def read_entities():
        for idx in count(1):
            line = infile.readline()
            if not line:
                return
            if idx % 1000 == 0:
                log.info(
                    "[%s] Loaded %s entities from: %s", collection, idx, infile.name
                )
            yield json.loads(line)

    role = Role.load_cli_user()
    for _ in bulk_write(
        collection,
        read_entities(),
        safe=safe,
        mutable=mutable,
        clean=clean,
        role_id=role.id,
    ):
        pass
    reindex_collection(collection)


@cli.command("dump-entities")
@click.argument("foreign_id")
@click.option("-o", "--outfile", type=click.File("w"), default="-")
def dump_entities(foreign_id, outfile):
    """Export FtM entities for the given collection."""
    collection = get_collection(foreign_id)
    for entity in iter_proxies(collection_id=collection.id):
        write_object(outfile, entity)


@cli.command("dump-profiles")
@click.option("-o", "--outfile", type=click.File("w"), default="-")
@click.option("-f", "--foreign_id", help="Foreign ID of the collection")
def dump_profiles(outfile, foreign_id=None):
    """Export profile entityset items for the given collection."""
    entitysets = EntitySet.by_type(EntitySet.PROFILE)
    if foreign_id is not None:
        collection = get_collection(foreign_id)
        entitysets = entitysets.filter(EntitySet.collection_id == collection.id)
    encoder = JSONEncoder(sort_keys=True)
    for entityset in entitysets:
        for item in entityset.items():
            data = item.to_dict(entityset=entityset)
            data["entity"] = get_expanded_entity(data.get("entity_id"))
            data["compared_to_entity"] = get_expanded_entity(
                data.get("compared_to_entity_id")
            )
            outfile.write(encoder.encode(data) + "\n")


@cli.command()
@click.argument("foreign_id", required=False)
def status(foreign_id=None):
    """Get the queue status (pending and finished tasks.)"""
    if foreign_id is not None:
        collection = get_collection(foreign_id)
        status = get_collection_status(collection)
        status = {"datasets": {foreign_id: status}}
    else:
        status = get_status()
    headers = ["Collection", "Job", "Stage", "Pending", "Running", "Finished"]
    rows = []
    for foreign_id, dataset in status.get("datasets").items():
        rows.append(
            [
                foreign_id,
                "",
                "",
                dataset["pending"],
                dataset["running"],
                dataset["finished"],
            ]
        )
        for job in dataset.get("jobs"):
            for stage in job.get("stages"):
                rows.append(
                    [
                        foreign_id,
                        stage["job_id"],
                        stage["stage"],
                        stage["pending"],
                        stage["running"],
                        stage["finished"],
                    ]
                )
    print(tabulate(rows, headers))


@cli.command()
@click.argument("foreign_id")
def cancel(foreign_id):
    """Cancel all queued tasks for the dataset."""
    collection = get_collection(foreign_id)
    queue_cancel_collection(collection)
    update_collection(collection)


@cli.command()
def cancel_all():
    """Cancel all queued tasks for all dataset."""
    for collection in Collection.all():
        queue_cancel_collection(collection)
        update_collection(collection)


@cli.command("retry-exports")
def retry_exports_():
    """Cancel all queued tasks not related to a dataset."""
    retry_exports()


@cli.command()
@click.argument("email")
@click.option("-p", "--password", help="Set a user password")
@click.option("-n", "--name", help="Set a label")
@click.option(
    "-a", "--admin", is_flag=True, default=False, help="Make the user an admin."
)
def createuser(email, password=None, name=None, admin=False):
    """Create a user and show their API key."""
    role = create_user(email, name, password, is_admin=admin)
    print("User created. ID: %s, API Key: %s" % (role.id, role.api_key))


@cli.command()
@click.argument("email")
@click.argument("name")
def renameuser(email, name):
    """Rename an already-existing user."""
    role = rename_user(email, name)
    if role:
        print(f"User renamed. ID: {role.id}, new name: {role.name}")
    else:
        print(f"The e-mail address {email} belongs to no user.")


@cli.command()
@click.argument("name")
def creategroup(name):
    """Create a user group."""
    create_group(name)
    print(f"Group {name} created.")


@cli.command()
@click.argument("group")
@click.argument("user")
def useradd(group, user):
    """Add user to group.

    GROUP and USER are both foreign IDs."""
    user_role, group_role = user_add(group, user)
    if user_role is not None and group_role is not None:
        print(f"Added user {user} to group {group}")
    if user_role is None:
        raise click.BadParameter(f"No such role: {user}")
    if group_role is None:
        raise click.BadParameter(f"No such role: {group}")


@cli.command()
@click.argument("group")
@click.argument("user")
def userdel(group, user):
    """Remove user from group.

    GROUP and USER are both foreign IDs.
    """
    user_role, group_role = user_del(group, user)
    if user_role is not None and group_role is not None:
        print(f"Removed user {user} from group {group}")
    if user_role is None:
        raise click.BadParameter(f"No such role: {user}")
    if group_role is None:
        raise click.BadParameter(f"No such role: {group}")


@cli.command()
def users():
    """List all users and their groups."""
    all_users = [
        (
            u.foreign_id,
            u.id,
            u.email,
            u.name,
            u.is_admin,
            ", ".join(sorted(u.name for u in u.roles)),
        )
        for u in Role.all_users()
    ]
    print(
        tabulate(
            all_users,
            headers=["Foreign ID", "ID", "E-Mail", "Name", "is admin", "groups"],
        )
    )


@cli.command()
def groups():
    """List all groups."""
    authz = Authz.from_role(Role.load_cli_user())
    all_groups = [(g.foreign_id, g.id, g.name) for g in Role.all_groups(authz)]
    print(tabulate(all_groups, headers=["Foreign ID", "ID", "Name"]))


@cli.command()
@click.argument("foreign_id")
def deleterole(foreign_id):
    """Hard-delete a role (user, or group) from the database."""
    role = Role.by_foreign_id(foreign_id, deleted=True)
    if role is None:
        raise click.BadParameter("No such role: %r" % foreign_id)
    delete_role(role)


@cli.command()
@click.argument("foreign_id")
def publish(foreign_id):
    """Make a collection visible to all users."""
    collection = get_collection(foreign_id)
    role = Role.by_foreign_id(Role.SYSTEM_GUEST)
    editor = Role.load_cli_user()
    update_permission(role, collection, True, False, editor_id=editor.id)
    update_collection(collection)
    db.session.commit()


@cli.command()
def upgrade():
    """Create or upgrade the search index and database."""
    upgrade_system()
    # update_roles()
    # upgrade_collections()


@cli.command()
def resetindex():
    """Re-create the ES index configuration, dropping all data."""
    delete_index()
    upgrade_system()


@cli.command()
def resetcache():
    """Clear the redis cache."""
    cache.flush()


@cli.command("cleanup-archive")
@click.option("-p", "--prefix", help="Scan a subset with a prefix")
def cleanuparchive(prefix):
    cleanup_archive(prefix=prefix)


@cli.command()
def evilshit():
    """EVIL: Delete all data and recreate the database."""
    delete_index()
    destroy_db()
    upgrade()
