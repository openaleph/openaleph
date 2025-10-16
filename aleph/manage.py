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
from aleph.logic.archive import cleanup_archive
from aleph.logic.collections import (
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
from aleph.procrastinate.queues import queue_cancel_collection, queue_reindex
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


def _reindex_collection(collection, flush=False, diff_only=False, model=True):
    log.info("[%s] Starting to re-index", collection)
    try:
        reindex_collection(collection, flush=flush, diff_only=diff_only, model=model)
    except Exception:
        log.exception("Failed to re-index: %s", collection)


@cli.command()
@click.argument("foreign_id")
@click.option("--flush", is_flag=True, default=False)
@click.option("--model/--no-model", is_flag=True, default=True)
@click.option(
    "--diff-only",
    is_flag=True,
    default=False,
    help="Only reindex entities that are in aggregator but not in index",
)
def reindex(foreign_id, flush=False, diff_only=False, model=True):
    """Index all the aggregator contents for a collection."""
    collection = get_collection(foreign_id)
    _reindex_collection(collection, flush=flush, diff_only=diff_only, model=model)


def _write_entity_ids(entity_ids, output_file, description):
    """Write entity IDs to file, sorted one per line."""
    sorted_ids = sorted(entity_ids)
    for entity_id in sorted_ids:
        output_file.write(f"{entity_id}\n")
    log.info("Wrote %d %s to %s", len(sorted_ids), description, output_file.name)


@cli.command("index-diff")
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
def index_diff(
    foreign_id,
    aggregator_ids=None,
    index_ids=None,
    only_aggregator=None,
    only_index=None,
):
    """Compare entity IDs between aggregator and search index."""
    collection = get_collection(foreign_id)
    diff = _index_diff(collection)

    # Write outputs if requested
    outputs = [
        (aggregator_ids, diff["aggregator_ids"], "aggregator IDs"),
        (index_ids, diff["index_ids"], "index IDs"),
        (only_aggregator, diff["only_in_aggregator"], "only-in-aggregator IDs"),
        (only_index, diff["only_in_index"], "only-in-index IDs"),
    ]
    for output_file, entity_ids, description in outputs:
        if output_file:
            _write_entity_ids(entity_ids, output_file, description)

    # Display results
    print("\n" + "=" * 60)
    print(f"Index Diff Report for: {collection.label} ({foreign_id})")
    print("=" * 60)
    print(f"Total in aggregator:        {len(diff['aggregator_ids']):>10}")
    print(f"Total in index:             {len(diff['index_ids']):>10}")
    print(f"In both:                    {len(diff['in_both']):>10}")
    print(f"Only in aggregator:         {len(diff['only_in_aggregator']):>10}")
    print(f"Only in index:              {len(diff['only_in_index']):>10}")
    print("=" * 60)

    if diff["only_in_aggregator"]:
        print("\nFirst 10 entities only in aggregator:")
        for entity_id in list(diff["only_in_aggregator"])[:10]:
            print(f"  - {entity_id}")
        if len(diff["only_in_aggregator"]) > 10:
            print(f"  ... and {len(diff['only_in_aggregator']) - 10} more")

    if diff["only_in_index"]:
        print("\nFirst 10 entities only in index:")
        for entity_id in list(diff["only_in_index"])[:10]:
            print(f"  - {entity_id}")
        if len(diff["only_in_index"]) > 10:
            print(f"  ... and {len(diff['only_in_index']) - 10} more")


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
            diff = _index_diff(collection)
            collections_list.append(
                {
                    "foreign_id": collection.foreign_id,
                    "label": collection.label,
                    "aggregator": len(diff["aggregator_ids"]),
                    "index": len(diff["index_ids"]),
                    "in_both": len(diff["in_both"]),
                    "only_aggregator": len(diff["only_in_aggregator"]),
                    "only_index": len(diff["only_in_index"]),
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
    print("\n" + "=" * 100)
    print("Index Diff Summary for All Collections")
    print("=" * 100)

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

    print(tabulate(rows, headers=headers, tablefmt="simple"))
    print("=" * 100)

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

    print(f"\nTotals across {len(collections_list)} collections:")
    print(f"  Total entities in aggregator:      {total_aggregator:>10}")
    print(f"  Total entities in index:           {total_index:>10}")
    print(f"  Total missing from index:          {total_only_aggregator:>10}")
    print(f"  Total orphaned in index:           {total_only_index:>10}")


@cli.command("reindex-full")
@click.option("--flush", is_flag=True, default=False)
@click.option("--model/--no-model", is_flag=True, default=True)
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
def reindex_full(flush=False, diff_only=False, queue=False, model=True):
    """Re-index all collections."""
    for collection in Collection.all():
        if queue:
            queue_reindex(collection, flush=flush, diff_only=diff_only)
        else:
            _reindex_collection(
                collection, flush=flush, diff_only=diff_only, model=model
            )


@cli.command("reindex-casefiles")
@click.option("--flush", is_flag=True, default=False)
@click.option("--model/--no-model", is_flag=True, default=True)
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
def reindex_casefiles(flush=False, diff_only=False, queue=False, model=True):
    """Re-index all the casefile collections."""
    for collection in Collection.all_casefiles():
        if queue:
            queue_reindex(collection, flush=flush, diff_only=diff_only)
        else:
            _reindex_collection(
                collection, flush=flush, diff_only=diff_only, model=model
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
