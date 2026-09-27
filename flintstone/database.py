"""Database setup and session management."""

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _default_sql(column) -> str:
    default = column.server_default
    if default is None:
        return ""
    arg = default.arg
    if isinstance(arg, str):
        return " DEFAULT '" + arg.replace("'", "''") + "'"
    return f" DEFAULT {arg.text}"


def upgrade_schema(bind) -> list[str]:
    """Bring an existing SQLite database up to date with the models.

    ``create_all`` only creates missing tables, so columns added in newer
    Flintstone versions are appended here with ``ALTER TABLE ... ADD COLUMN``.
    Returns the list of columns that were added.
    """
    inspector = inspect(bind)
    added = []
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl = (
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" '
                    f"{column.type.compile(dialect=conn.dialect)}{_default_sql(column)}"
                )
                conn.exec_driver_sql(ddl)
                added.append(f"{table.name}.{column.name}")
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            index.create(bind, checkfirst=True)
    return added


def init_db():
    from . import models  # noqa: F401
    from .native import backfill_tokens

    Base.metadata.create_all(bind=engine)
    upgrade_schema(engine)
    with SessionLocal() as db:
        backfill_tokens(db)
