import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    clerk_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    plan: Mapped[str] = mapped_column(String(50), default="free")
    credits_remaining: Mapped[int] = mapped_column(default=50)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Cleaning/AI preferences (see app.schemas.settings.UserPreferences).
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )

    # Relationships
    datasets: Mapped[list["Dataset"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["Job"]] = relationship(back_populates="user")  # noqa: F821
