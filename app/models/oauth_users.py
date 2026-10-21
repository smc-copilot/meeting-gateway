from datetime import datetime
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import OrgRecord, UTCDateTime, active_unique


class MeetingOAuthUser(OrgRecord):
    __tablename__ = "meeting_oauth_users"
    __table_args__ = (active_unique("uq_meeting_oauth_user_open_id", "org_id", "open_id"),)
    open_id: Mapped[str] = mapped_column(String(128), index=True)
    open_corp_id: Mapped[str] = mapped_column(String(128), default="")
    username: Mapped[str | None] = mapped_column(String(256), nullable=True)
    open_corp_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    connection_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
