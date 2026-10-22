from datetime import datetime
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Record, UTCDateTime, active_unique


class MeetingEnvStsToken(Record):
    __tablename__ = "meeting_env_sts_tokens"
    __table_args__ = (active_unique("uq_meeting_env_sts_token_req", "req_id"),)
    req_id: Mapped[str] = mapped_column(String(128), index=True)
    state: Mapped[str] = mapped_column(String(32), default="WAITING")
    token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    valid_hours: Mapped[int] = mapped_column(Integer, default=24)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime)
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    operator_id: Mapped[str] = mapped_column(String(128), default="")
