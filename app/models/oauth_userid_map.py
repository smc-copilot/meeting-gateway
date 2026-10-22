from datetime import datetime
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import OrgRecord, UTCDateTime, active_unique


class MeetingOAuthUseridMap(OrgRecord):
    __tablename__ = "meeting_oauth_userid_maps"
    __table_args__ = (active_unique("uq_meeting_oauth_userid_map", "org_id", "open_id"),)
    open_id: Mapped[str] = mapped_column(String(128), index=True)
    userid: Mapped[str] = mapped_column(String(128), index=True)
    oauth_sdk_id: Mapped[str] = mapped_column(String(128), default="")
    resolved_at: Mapped[datetime] = mapped_column(UTCDateTime)
