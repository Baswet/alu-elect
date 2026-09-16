"""One SQLAlchemy session per request, closed on teardown."""

from flask import current_app, g
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

_engine = None
_factory = None


def init_engine(database_url: str):
    global _engine, _factory
    _engine = create_engine(database_url, pool_pre_ping=True, future=True)
    _factory = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


def get_engine():
    return _engine


def get_session():
    if "db" not in g:
        g.db = _factory()
    return g.db


def close_session(exc=None):
    db = g.pop("db", None)
    if db is not None:
        try:
            if exc is not None:
                db.rollback()
        finally:
            db.close()
