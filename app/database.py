"""
Database wiring for LoopLink.

Single SQLite file, single process — matches the exercise's scope (no
horizontal scaling, no multi-tenancy). `get_db` is a FastAPI dependency
that hands each request its own Session and always closes it, even on
error.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./looplink.db"

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
