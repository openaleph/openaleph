import flask_migrate
from openaleph_procrastinate.app import init_db
from sqlalchemy import MetaData, inspect
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.exc import InternalError

from aleph.core import archive, db
from aleph.index.admin import upgrade_search
from aleph.logic.roles import create_system_roles


def upgrade_system():
    flask_migrate.upgrade()
    archive.upgrade()
    create_system_roles()
    upgrade_search()
    init_db()


def cleanup_deleted():
    from aleph.model import Collection, EntitySet, EntitySetItem, Role

    EntitySetItem.cleanup_deleted()
    EntitySet.cleanup_deleted()
    Collection.cleanup_deleted()
    Role.cleanup_deleted()
    db.session.commit()


def destroy_db():
    metadata = MetaData()
    metadata.bind = db.engine
    metadata.reflect(db.engine)
    tables = list(metadata.sorted_tables)
    while len(tables):
        for table in tables:
            try:
                table.drop(bind=db.engine, checkfirst=True)
                tables.remove(table)
            except InternalError:
                pass
    for enum in inspect(db.engine).get_enums():
        enum = ENUM(name=enum["name"])
        enum.drop(bind=db.engine, checkfirst=True)
