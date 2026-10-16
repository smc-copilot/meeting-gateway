"""Bounded maintenance batches. Business rows become tombstones; expired private bytes are removed."""
from datetime import timedelta
import logging
from sqlalchemy import select, or_
from app.core.types import utcnow
from app.core.errors import MeetingError
from app.models import (Connection,Application,Credential,STSCallback,AuthTransaction,AccessToken,Asset,
                        Meeting,Operation,OrganizationPolicy,EventInbox,AuditLog,DownloadTicket)

logger=logging.getLogger(__name__)


class MaintenanceService:
    def __init__(self,runtime):self.rt=runtime

    async def tokens(self):
        last=''
        while True:
            async with self.rt.db.session() as s:
                rows=list((await s.execute(select(Connection).where(Connection.deleted_at.is_(None),
                    Connection.status.in_(['ACTIVE','DEGRADED']),Connection.id>last).order_by(Connection.id).limit(100))).scalars())
            if not rows:return
            for c in rows:
                last=c.id
                try:
                    if c.kind=='ENTERPRISE_AKSK':await self.rt.connections.maintain_sts(c.id)
                    else:await self.rt.connections.oauth_credentials(c.id)
                except MeetingError as exc:
                    logger.warning('maintenance.token_failed connection_id=%s reason=%s',c.id,exc.reason)
            if len(rows)<100:return

    async def personal_sync(self):
        # Fifteen-minute compensation is persisted per app; multiple Worker processes share the lock.
        async with self.rt.db.lock('maintenance:personal-sync'):
            async with self.rt.db.session() as s:
                apps=list((await s.execute(select(Application).where(Application.enabled.is_(True),
                    Application.application_type=='THIRD_PARTY_OAUTH',Application.deleted_at.is_(None)))).scalars())
            for app in apps:
                due=float((app.settings_data or {}).get('personal_sync_after',0))
                if due>utcnow().timestamp():continue
                await self.rt.events._schedule_personal(app,'cadence-'+str(int(utcnow().timestamp())//900))
                async with self.rt.db.transaction() as s:
                    current=await s.get(Application,app.id)
                    current.settings_data={**(current.settings_data or {}),'personal_sync_after':utcnow().timestamp()+900}

    async def expire(self):
        now=utcnow()
        async with self.rt.db.lock('maintenance:retention'):
            # Remove objects before clearing their references so a filesystem failure is retryable.
            while True:
                async with self.rt.db.session() as s:
                    expired=list((await s.execute(select(Asset).where(Asset.object_key.is_not(None),
                        or_(Asset.expires_at<=now,Asset.state.in_(['SOURCE_REMOVED','EXPIRED'])),
                        Asset.deleted_at.is_(None)).limit(100))).scalars())
                if not expired:break
                for a in expired:
                    await self.rt.storage.remove(a.object_key)
                    async with self.rt.db.transaction() as s:
                        row=await s.get(Asset,a.id,with_for_update=True)
                        if row.object_key==a.object_key:
                            row.object_key=None;row.state='EXPIRED';row.is_complete=False
                            await self.rt.policy.bump(s,row.org_id)
                if len(expired)<100:break
            async with self.rt.db.transaction() as s:
                for op in (await s.execute(select(Operation).where(Operation.state=='AWAITING_CONFIRMATION',
                    Operation.confirm_deadline<=now,Operation.deleted_at.is_(None)).limit(1000))).scalars():
                    op.state='OPERATION_EXPIRED';op.last_reason='OPERATION_EXPIRED'
                for txn in (await s.execute(select(AuthTransaction).where(AuthTransaction.expires_at<=now,
                    AuthTransaction.encrypted_payload.is_not(None)).limit(1000))).scalars():
                    txn.encrypted_payload=None;txn.status='EXPIRED'
                for c in (await s.execute(select(Credential).where(Credential.active.is_(False),
                    Credential.ciphertext!='').limit(1000))).scalars():c.ciphertext=''
                for cb in (await s.execute(select(STSCallback).where(STSCallback.expires_at<=now,
                    STSCallback.token_ciphertext!='').limit(1000))).scalars():cb.token_ciphertext=''
                for inbox in (await s.execute(select(EventInbox).where(EventInbox.created_at<now-timedelta(days=self.rt.settings.diagnostic_retention_days),
                    EventInbox.encrypted_payload.is_not(None),EventInbox.state.in_(['PROCESSED','IGNORED'])).limit(1000))).scalars():
                    inbox.encrypted_payload=None
                for ticket in (await s.execute(select(DownloadTicket).where(DownloadTicket.session_expires_at<now,
                    DownloadTicket.deleted_at.is_(None)).limit(1000))).scalars():ticket.soft_delete()
                policies=list((await s.execute(select(OrganizationPolicy).where(OrganizationPolicy.deleted_at.is_(None)))).scalars())
                for policy in policies:
                    cutoff=now-timedelta(days=policy.metadata_days)
                    meetings=list((await s.execute(select(Meeting).where(Meeting.org_id==policy.org_id,Meeting.deleted_at.is_(None),
                        Meeting.end_at<cutoff).limit(1000))).scalars())
                    for m in meetings:
                        m.soft_delete()
                        for a in (await s.execute(select(Asset).where(Asset.meeting_id==m.id,Asset.deleted_at.is_(None)))).scalars():
                            a.expires_at=min(a.expires_at or now,now)
                    if meetings:await self.rt.policy.bump(s,policy.org_id)
                    for audit in (await s.execute(select(AuditLog).where(AuditLog.org_id==policy.org_id,
                        AuditLog.created_at<now-timedelta(days=policy.audit_days),AuditLog.deleted_at.is_(None)).limit(1000))).scalars():
                        audit.details={};audit.soft_delete()
        await self.rt.events.invalidate_delivery_access()
