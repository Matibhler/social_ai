"""
Configuración de SQLAlchemy y utilidades de sesión.
"""

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.config import settings
from core.models import Base

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Crea todas las tablas si no existen."""
    settings.DB_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session():
    """Context manager para sesiones de DB."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Dependency para FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
