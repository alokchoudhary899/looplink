"""
Database wiring for LoopLink.

Single SQLite file, single process — matches the exercise's scope (no
horizontal scaling, no multi-tenancy). `get_db` is a FastAPI dependency
that hands each request its own Session and always closes it, even on
error.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# LOOPLINK_DATA_DIR lets the DB file live somewhere a Docker volume can
# mount onto, so data survives a container restart. Unset (the local/
# non-Docker case) it defaults to the project root, same as before.
DATA_DIR = os.environ.get("LOOPLINK_DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)
DATABASE_URL = f"sqlite:///{DATA_DIR}/looplink.db"

# check_same_thread=False is required for SQLite + a multi-request server
# process; it's safe here because each request gets its own Session below.
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
