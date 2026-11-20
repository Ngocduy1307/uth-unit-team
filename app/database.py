from functools import lru_cache
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import settings

class Base(DeclarativeBase):
    pass

@lru_cache(maxsize=1)
def get_engine():
    # Lazy initialization keeps API schema/docs importable even before DB driver/network is ready.
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)

def get_session_factory():
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)

def get_db():
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()
