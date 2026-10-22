"""Deployment-scoped STS Token for the env enterprise self-built app.

Outbound: POST /v1/app/sts-token via env AK/SK.
Inbound: Tencent webhook common.sts-token verified with env webhook Token/EncodingAESKey.
"""
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.errors import MeetingError
from app.core.types import utcnow
from app.integrations.tencent_meeting.webhook import decrypt_message, verify_callback
from app.models import MeetingEnvStsToken

logger = logging.getLogger(__name__)


class EnvStsService:
    def __init__(self, runtime):
        self.rt = runtime

    def _webhook_credentials(self):
        if not self.rt.settings.tencent_app_webhook_complete():
            raise MeetingError('RESOURCE_NOT_ACCESSIBLE', 404)
        return (
            self.rt.settings.tencent_meeting_app_webhook_token.get_secret_value().strip(),
            self.rt.settings.tencent_meeting_app_webhook_encoding_key.get_secret_value().strip(),
        )

    def _verify_and_decrypt(self, encrypted, headers):
        if not isinstance(encrypted, str) or len(encrypted) > self.rt.settings.max_request_bytes:
            raise MeetingError('INVALID_REQUEST', 413)
        if any(not isinstance(headers.get(k), str) or not headers[k] or len(headers[k]) > 256
               for k in ('timestamp', 'nonce', 'signature')):
            raise MeetingError('AUTH_REQUIRED', 401)
        token, encoding_key = self._webhook_credentials()
        if not verify_callback(token, headers['timestamp'], headers['nonce'], encrypted, headers['signature']):
            raise MeetingError('AUTH_REQUIRED', 401)
        try:
            return decrypt_message(encrypted, encoding_key)
        except ValueError as exc:
            raise MeetingError('AUTH_REQUIRED', 401) from exc

    async def challenge(self, check_str, headers):
        return self._verify_and_decrypt(check_str, headers)

    async def receive(self, encrypted, headers):
        import json
        plain = self._verify_and_decrypt(encrypted, headers)
        try:
            payload = json.loads(plain)
        except (ValueError, UnicodeError) as exc:
            raise MeetingError('INVALID_REQUEST', 422) from exc
        if (not isinstance(payload, dict)
                or not isinstance(payload.get('event'), str)
                or len(payload['event']) > 64
                or not isinstance(payload.get('payload'), list)
                or len(payload['payload']) > 1000):
            raise MeetingError('INVALID_REQUEST', 422)
        if payload['event'] != 'common.sts-token':
            return None
        for entry in payload['payload']:
            if not isinstance(entry, dict):
                raise MeetingError('INVALID_REQUEST', 422)
            token_info = entry.get('token_info') or {}
            operator = entry.get('operator') or {}
            await self._upsert_token(
                token_info,
                operator_id=operator.get('userid') if isinstance(operator, dict) else None,
            )
        return None

    async def _upsert_token(self, token_info, *, operator_id):
        try:
            if not isinstance(token_info, dict):
                raise ValueError('fields')
            req_id = token_info['req_id']
            token = token_info['sts_token']
            expires = datetime.fromtimestamp(int(token_info['expire_ts']), UTC)
            if (not isinstance(req_id, str) or not req_id or len(req_id) > 128
                    or not isinstance(token, str) or not token or len(token) > 16384):
                raise ValueError('fields')
        except (KeyError, ValueError, TypeError, OverflowError) as exc:
            raise MeetingError('INVALID_REQUEST', 422) from exc
        op = operator_id if isinstance(operator_id, str) and 1 <= len(operator_id) <= 128 else ''
        async with self.rt.db.lock('env-sts-receive:' + req_id), self.rt.db.transaction() as s:
            row = await s.scalar(
                select(MeetingEnvStsToken).where(
                    MeetingEnvStsToken.req_id == req_id,
                    MeetingEnvStsToken.deleted_at.is_(None),
                ))
            ciphertext = self.rt.keys.encrypt(token, f'env-sts:{req_id}')
            now = utcnow()
            if row is None:
                s.add(MeetingEnvStsToken(
                    req_id=req_id,
                    state='ACTIVE',
                    token_ciphertext=ciphertext,
                    expires_at=expires,
                    valid_hours=self.rt.settings.tencent_meeting_sts_valid_hours,
                    requested_at=now,
                    received_at=now,
                    operator_id=op,
                ))
            else:
                row.state = 'ACTIVE'
                row.token_ciphertext = ciphertext
                row.expires_at = expires
                row.received_at = now
                if op:
                    row.operator_id = op
                row.version += 1

    async def current_token(self):
        async with self.rt.db.session() as s:
            row = await s.scalar(
                select(MeetingEnvStsToken).where(
                    MeetingEnvStsToken.state == 'ACTIVE',
                    MeetingEnvStsToken.deleted_at.is_(None),
                    MeetingEnvStsToken.expires_at.is_not(None),
                    MeetingEnvStsToken.expires_at > utcnow() + timedelta(seconds=30),
                    MeetingEnvStsToken.token_ciphertext.is_not(None),
                ).order_by(MeetingEnvStsToken.expires_at.desc()).limit(1))
            if row is None:
                return None
            return self.rt.keys.decrypt(row.token_ciphertext, f'env-sts:{row.req_id}')

    async def refresh_due(self):
        if self.rt.settings.tencent_enterprise_aksk() is None:
            return
        if not self.rt.settings.tencent_app_webhook_complete():
            return
        valid_hours = self.rt.settings.tencent_meeting_sts_valid_hours
        if valid_hours not in {6, 12, 24}:
            logger.warning('env_sts.refresh_failed reason=INVALID_VALID_HOURS hours=%s', valid_hours)
            return
        margin = timedelta(seconds=self.rt.settings.tencent_meeting_sts_refresh_margin_seconds)
        try:
            async with self.rt.db.lock('env-sts-refresh'):
                async with self.rt.db.session() as s:
                    fresh = await s.scalar(
                        select(MeetingEnvStsToken.id).where(
                            MeetingEnvStsToken.state == 'ACTIVE',
                            MeetingEnvStsToken.deleted_at.is_(None),
                            MeetingEnvStsToken.expires_at.is_not(None),
                            MeetingEnvStsToken.expires_at > utcnow() + margin,
                        ).limit(1))
                    if fresh:
                        return
                    pending = await s.scalar(
                        select(MeetingEnvStsToken.id).where(
                            MeetingEnvStsToken.state == 'WAITING',
                            MeetingEnvStsToken.deleted_at.is_(None),
                            MeetingEnvStsToken.requested_at > utcnow() - timedelta(minutes=10),
                        ).limit(1))
                    if pending:
                        return
                result = await self.rt.tencent.sts_request(valid_hours=valid_hours)
                req_id = result['req_id']
                material = self.rt.settings.tencent_enterprise_aksk() or {}
                async with self.rt.db.transaction() as s:
                    existing = await s.scalar(
                        select(MeetingEnvStsToken).where(
                            MeetingEnvStsToken.req_id == req_id,
                            MeetingEnvStsToken.deleted_at.is_(None),
                        ))
                    if existing is None:
                        s.add(MeetingEnvStsToken(
                            req_id=req_id,
                            state='WAITING',
                            token_ciphertext=None,
                            expires_at=None,
                            valid_hours=valid_hours,
                            requested_at=utcnow(),
                            received_at=None,
                            operator_id=material.get('operator_id') or '',
                        ))
        except MeetingError as exc:
            logger.warning('env_sts.refresh_failed reason=%s status=%s', exc.reason, exc.status)
        except Exception:
            logger.warning('env_sts.refresh_failed reason=INTERNAL_ERROR', exc_info=True)
