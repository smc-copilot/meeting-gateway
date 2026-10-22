"""Env enterprise-app STS Token callback + worker refresh."""
import base64
from datetime import timedelta

import httpx
from pydantic import SecretStr
from sqlalchemy import select

from app.core.security import canonical
from app.core.types import utcnow
from app.integrations.tencent_meeting.webhook import callback_signature, encrypt_fixture
from app.main import create_app
from app.models import MeetingEnvStsToken

TOKEN = 'env-sts-callback-token'
AES_KEY = base64.b64encode(b'e' * 32).decode()


def arm_app_webhook(rt, *, token=TOKEN, encoding_key=AES_KEY):
    rt.settings.tencent_meeting_app_webhook_token = SecretStr(token)
    rt.settings.tencent_meeting_app_webhook_encoding_key = SecretStr(encoding_key)
    return encoding_key


def enable_env_aksk(rt):
    rt.settings.tencent_meeting_corp_id = '210022394'
    rt.settings.tencent_meeting_app_secret_id = SecretStr('secret-id')
    rt.settings.tencent_meeting_app_secret_key = SecretStr('secret-key')
    rt.settings.tencent_meeting_app_sdk_id = '33580129027'
    rt.settings.tencent_meeting_app_operator_id = 'operator-userid'
    rt.settings.tencent_meeting_sts_valid_hours = 24
    rt.settings.tencent_meeting_sts_refresh_margin_seconds = 3600


def signed_callback(body, *, key=AES_KEY, token=TOKEN):
    encrypted = encrypt_fixture(canonical(body), key)
    timestamp = '1750000000000'
    nonce = 'nonce'
    return encrypted, {
        'timestamp': timestamp,
        'nonce': nonce,
        'signature': callback_signature(token, timestamp, nonce, encrypted),
    }


async def test_app_challenge_success(rt):
    key = arm_app_webhook(rt)
    plain = b'raw-verification-value'
    text = encrypt_fixture(plain, key)
    headers = {
        'timestamp': '1750000000000',
        'nonce': 'n',
        'signature': callback_signature(TOKEN, '1750000000000', 'n', text),
    }
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime=rt)),
            base_url='https://meeting.example.org') as http:
        response = await http.get('/callbacks/tencent/app/events', params={'check_str': text}, headers=headers)
        assert response.status_code == 200 and response.content == plain


async def test_app_receive_success_and_idempotent(rt):
    arm_app_webhook(rt)
    expire_ts = int((utcnow() + timedelta(hours=6)).timestamp())
    body = {
        'event': 'common.sts-token',
        'trace_id': 'sts-1',
        'payload': [{
            'operate_time': 1750000000000,
            'operator': {'userid': 'operator-userid'},
            'token_info': {
                'req_id': 'req-abc',
                'sts_token': 'sensitive-sts-token',
                'expire_ts': expire_ts,
            },
        }],
    }
    data, headers = signed_callback(body)
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime=rt)),
            base_url='https://meeting.example.org') as http:
        first = await http.post('/callbacks/tencent/app/events', json={'data': data}, headers=headers)
        second = await http.post('/callbacks/tencent/app/events', json={'data': data}, headers=headers)
        assert first.status_code == 200 and first.text == 'successfully received callback'
        assert second.status_code == 200
    async with rt.db.session() as s:
        rows = list((await s.execute(select(MeetingEnvStsToken))).scalars())
        assert len(rows) == 1
        assert rows[0].state == 'ACTIVE' and rows[0].req_id == 'req-abc'
        assert rows[0].token_ciphertext is not None
        assert rows[0].operator_id == 'operator-userid'
    assert await rt.env_sts.current_token() == 'sensitive-sts-token'


async def test_app_forged_signature_rejected(rt):
    arm_app_webhook(rt)
    data, headers = signed_callback({
        'event': 'common.sts-token',
        'payload': [{
            'operator': {'userid': 'x'},
            'token_info': {
                'req_id': 'req-forged',
                'sts_token': 'tok',
                'expire_ts': int((utcnow() + timedelta(hours=1)).timestamp()),
            },
        }],
    })
    headers = dict(headers)
    headers['signature'] = 'bad'
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime=rt)),
            base_url='https://meeting.example.org') as http:
        rejected = await http.post('/callbacks/tencent/app/events', json={'data': data}, headers=headers)
        assert rejected.status_code == 401
    async with rt.db.session() as s:
        assert list((await s.execute(select(MeetingEnvStsToken))).scalars()) == []


async def test_app_unknown_event_ignored(rt):
    arm_app_webhook(rt)
    data, headers = signed_callback({'event': 'recording.completed', 'payload': []})
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime=rt)),
            base_url='https://meeting.example.org') as http:
        response = await http.post('/callbacks/tencent/app/events', json={'data': data}, headers=headers)
        assert response.status_code == 200
    async with rt.db.session() as s:
        assert list((await s.execute(select(MeetingEnvStsToken))).scalars()) == []


async def test_app_webhook_unconfigured_404(rt):
    plain = b'raw'
    text = encrypt_fixture(plain, AES_KEY)
    headers = {
        'timestamp': '1750000000000',
        'nonce': 'n',
        'signature': callback_signature(TOKEN, '1750000000000', 'n', text),
    }
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime=rt)),
            base_url='https://meeting.example.org') as http:
        response = await http.get('/callbacks/tencent/app/events', params={'check_str': text}, headers=headers)
        assert response.status_code == 404


async def test_refresh_due_requests_and_callback_activates(rt):
    enable_env_aksk(rt)
    arm_app_webhook(rt)
    rt._provider.response = {'sts_request': {'req_id': 'req-from-refresh'}}
    await rt.env_sts.refresh_due()
    async with rt.db.session() as s:
        row = await s.scalar(select(MeetingEnvStsToken).where(MeetingEnvStsToken.req_id == 'req-from-refresh'))
        assert row is not None and row.state == 'WAITING'
    assert [('env-aksk', 'sts_request', None, {'valid_hours': 24})] == [
        (c[0], c[1], c[2], c[3]) for c in rt.tencent.calls if c[1] == 'sts_request'
    ]
    expire_ts = int((utcnow() + timedelta(hours=24)).timestamp())
    data, headers = signed_callback({
        'event': 'common.sts-token',
        'payload': [{
            'operator': {'userid': 'operator-userid'},
            'token_info': {
                'req_id': 'req-from-refresh',
                'sts_token': 'refreshed-token',
                'expire_ts': expire_ts,
            },
        }],
    })
    await rt.env_sts.receive(data, headers)
    assert await rt.env_sts.current_token() == 'refreshed-token'
    calls_before = len([c for c in rt.tencent.calls if c[1] == 'sts_request'])
    await rt.env_sts.refresh_due()
    calls_after = len([c for c in rt.tencent.calls if c[1] == 'sts_request'])
    assert calls_after == calls_before


async def test_current_token_expired_returns_none(rt):
    arm_app_webhook(rt)
    past = int((utcnow() - timedelta(hours=1)).timestamp())
    data, headers = signed_callback({
        'event': 'common.sts-token',
        'payload': [{
            'operator': {'userid': 'operator-userid'},
            'token_info': {
                'req_id': 'req-expired',
                'sts_token': 'old-token',
                'expire_ts': past,
            },
        }],
    })
    await rt.env_sts.receive(data, headers)
    assert await rt.env_sts.current_token() is None


async def test_refresh_due_skips_without_credentials(rt):
    arm_app_webhook(rt)
    await rt.env_sts.refresh_due()
    assert [c for c in rt.tencent.calls if c[1] == 'sts_request'] == []
    enable_env_aksk(rt)
    rt.settings.tencent_meeting_app_webhook_token = SecretStr('')
    await rt.env_sts.refresh_due()
    assert [c for c in rt.tencent.calls if c[1] == 'sts_request'] == []
