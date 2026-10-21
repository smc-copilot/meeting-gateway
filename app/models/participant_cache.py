from datetime import datetime
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import OrgRecord, UTCDateTime, active_unique


class MeetingParticipantSnapshot(OrgRecord):
    __tablename__ = "meeting_participant_snapshots"
    __table_args__ = (
        active_unique(
            "uq_meeting_participant_snapshot",
            "org_id",
            "connection_id",
            "external_meeting_id",
        ),
    )
    connection_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_connections.id"), index=True)
    external_meeting_id: Mapped[str] = mapped_column(String(128), index=True)
    meeting_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    total_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime)


class MeetingParticipantRow(OrgRecord):
    __tablename__ = "meeting_participant_rows"
    snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meeting_participant_snapshots.id"), index=True
    )
    connection_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_connections.id"), index=True)
    external_meeting_id: Mapped[str] = mapped_column(String(128), index=True)
    open_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    userid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ms_open_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_name_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    join_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_enterprise_user: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    sort_index: Mapped[int] = mapped_column(Integer, default=0)
