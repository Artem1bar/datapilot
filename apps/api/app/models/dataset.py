import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(500))
    r2_key: Mapped[str] = mapped_column(Text)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sheet_names: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    row_count: Mapped[int | None]
    col_count: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(50), default="uploaded")
    profile_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Relationships
    user: Mapped["User"] = relationship(back_populates="datasets")  # noqa: F821
    jobs: Mapped[list["Job"]] = relationship(back_populates="dataset")  # noqa: F821
    chat_sessions: Mapped[list["ChatSession"]] = relationship(  # noqa: F821
        back_populates="dataset", cascade="all, delete-orphan"
    )
