from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.core.config import settings

is_sqlite = settings.DATABASE_URL.startswith("sqlite")

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args={} if is_sqlite else {"options": f"-csearch_path={settings.DB_SCHEMA},public"},
)


@event.listens_for(engine, "connect")
def set_search_path(dbapi_conn, connection_record):
    if not is_sqlite:
        cursor = dbapi_conn.cursor()
        cursor.execute(f'SET search_path TO "{settings.DB_SCHEMA}", public')
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
