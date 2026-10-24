"""Database sessions and portable UUID-backed records."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, Uuid, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import settings


def now() -> datetime:
    """Return an aware UTC timestamp for provenance and ordering."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Common identity and creation timestamp for persisted records."""

    type_annotation_map = {datetime: DateTime(timezone=True)}

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(default=now)


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    """Give each request its own transactional session."""
    with SessionLocal() as session:
        yield session


def timestamp(value: datetime) -> float:
    """Interpret SQLite's naive timestamp results as the UTC values originally stored."""
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).timestamp()
