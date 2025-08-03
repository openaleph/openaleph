import flask_migrate
from sqlalchemy import MetaData, inspect, text
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
    aleph_tables = [x for x in tables if "procrastinate" not in x.name]
    while len(aleph_tables):
        for table in aleph_tables:
            try:
                table.drop(bind=db.engine, checkfirst=True)
                aleph_tables.remove(table)
            except InternalError:
                pass
    for enum in inspect(db.engine).get_enums():
        enum = ENUM(name=enum["name"])
        if "procrastinate" not in enum.name:
            enum.drop(bind=db.engine, checkfirst=True)
    procrastinate_tables = [x for x in tables if "procrastinate" in x.name]
    for table in procrastinate_tables:
        q = f"TRUNCATE {table.name} RESTART IDENTITY CASCADE;"
        with db.engine.connect() as conn:
            conn.execute(text(q))
            conn.commit()
