from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import JSON_TYPE, OrgRecord, active_unique


class MeetingDirectoryUser(OrgRecord):
    __tablename__ = "meeting_directory_users"
    __table_args__ = (active_unique("uq_meeting_directory_user", "org_id", "userid"),)
    userid: Mapped[str] = mapped_column(String(128), index=True)
    uuid: Mapped[str] = mapped_column(String(128), default="")
    username: Mapped[str] = mapped_column(String(256), default="")
    area: Mapped[str] = mapped_column(String(16), default="")
    update_time: Mapped[str] = mapped_column(String(32), default="")
    avatar_url: Mapped[str] = mapped_column(String(1024), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(32), default="")
    job_title: Mapped[str] = mapped_column(String(128), default="")
    staff_id: Mapped[str] = mapped_column(String(128), default="")
    entry_time: Mapped[str] = mapped_column(String(32), default="")
    role_name: Mapped[str] = mapped_column(String(64), default="")
    role_code: Mapped[str] = mapped_column(String(64), default="")
    department_list: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    user_account_type: Mapped[int | None] = mapped_column(Integer, nullable=True)
    account_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enable_ai_account: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ai_account_type: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phone_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    add_on_largemeeting: Mapped[int | None] = mapped_column(Integer, nullable=True)
    add_on_webinar: Mapped[int | None] = mapped_column(Integer, nullable=True)
    email_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_voov: Mapped[int | None] = mapped_column(Integer, nullable=True)
    allow_login_terminal: Mapped[list] = mapped_column(JSON_TYPE, default=list)


class MeetingDirectorySyncState(OrgRecord):
    __tablename__ = "meeting_directory_sync_states"
    __table_args__ = (active_unique("uq_meeting_directory_sync_state", "org_id"),)
    last_page: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page_size: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
