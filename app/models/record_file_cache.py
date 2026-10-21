from datetime import datetime
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import OrgRecord, UTCDateTime, active_unique


class MeetingRecordFileSnapshot(OrgRecord):
    __tablename__ = "meeting_record_file_snapshots"
    __table_args__ = (
        active_unique(
            "uq_meeting_record_file_snapshot",
            "org_id",
            "connection_id",
            "external_meeting_id",
        ),
    )
    connection_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_connections.id"), index=True)
    external_meeting_id: Mapped[str] = mapped_column(String(128), index=True)
    meeting_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    meeting_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime)


class MeetingRecordFileRow(OrgRecord):
    __tablename__ = "meeting_record_file_rows"
    __table_args__ = (
        active_unique(
            "uq_meeting_record_file_row",
            "org_id",
            "connection_id",
            "external_meeting_id",
            "record_file_id",
        ),
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meeting_record_file_snapshots.id"), index=True
    )
    connection_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_connections.id"), index=True)
    external_meeting_id: Mapped[str] = mapped_column(String(128), index=True)
    record_file_id: Mapped[str] = mapped_column(String(128), index=True)
    record_start_time_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    record_end_time_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    record_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sharing_state: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sharing_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_same_corp: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    required_participant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    password: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sharing_expire: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    allow_download: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    sort_index: Mapped[int] = mapped_column(Integer, default=0)
