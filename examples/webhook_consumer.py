"""Internal event consumer example, not the Tencent callback receiver.

Run from this directory:
  uvicorn webhook_consumer:create_app --factory --host 127.0.0.1 --port 8001 --no-access-log
Configure MEETING_EVENT_SECRET (subscription secret, at least 32 characters),
MEETING_EVENT_DB (private durable SQLite path). Put HTTPS in front of it.

This single-host example demonstrates exact-byte authentication and durable
idempotent inbox acceptance. A production multi-instance consumer must use its
own shared database/queue. Persisting an event is not executing a business task.
"""
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

MAX_BYTES = 64 * 1024


def verify_signature(secret: str, timestamp: str, nonce: str, signature: str, body: bytes, *, now: int | None = None) -> None:
    now = int(time.time()) if now is None else now
    if len(secret) < 32 or len(body) > MAX_BYTES:
        raise ValueError('Invalid configuration or oversized body')
    if not re.fullmatch(r'[0-9]{1,12}', timestamp) or abs(now - int(timestamp)) > 300:
        raise ValueError('Expired event timestamp')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', nonce):
        raise ValueError('Invalid event nonce')
    signed = timestamp.encode() + b'.' + nonce.encode() + b'.' + body
    expected = 'sha256=' + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected.encode(), signature.encode()):
        raise ValueError('Invalid event signature')


def persist_event(path: Path, body: bytes, nonce: str, *, now: int | None = None) -> bool:
    now = int(time.time()) if now is None else now
    event = json.loads(body)
    required = {'event_id', 'event_type', 'resource_id', 'occurred_at'}
    if not isinstance(event, dict) or not required <= event.keys():
        raise ValueError('Invalid event envelope')
    if any(not isinstance(event[key], str) or not 1 <= len(event[key]) <= 256 for key in required):
        raise ValueError('Invalid event identifiers')
    if len(body) > MAX_BYTES:
        raise ValueError('Event too large')
    payload_hash = hashlib.sha256(body).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, isolation_level=None, timeout=10)
    try:
        os.chmod(path, 0o600)
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE IF NOT EXISTS inbox (event_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, payload BLOB NOT NULL, accepted_at INTEGER NOT NULL, status TEXT NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS nonces (nonce TEXT PRIMARY KEY, event_id TEXT NOT NULL, accepted_at INTEGER NOT NULL)')
        connection.execute('BEGIN IMMEDIATE')
        existing = connection.execute('SELECT payload_hash FROM inbox WHERE event_id=?', (event['event_id'],)).fetchone()
        if existing:
            if existing[0] != payload_hash:
                raise ValueError('Event ID reused with a different payload')
            connection.commit()
            return False
        if connection.execute('SELECT 1 FROM nonces WHERE nonce=?', (nonce,)).fetchone():
            raise ValueError('Nonce replay on a different event')
        connection.execute('INSERT INTO nonces VALUES (?,?,?)', (nonce, event['event_id'], now))
        connection.execute('INSERT INTO inbox VALUES (?,?,?,?,?)', (event['event_id'], payload_hash, body, now, 'PENDING'))
        connection.commit()
        return True
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


def create_app() -> FastAPI:
    secret = os.getenv('MEETING_EVENT_SECRET', '')
    if len(secret) < 32:
        raise RuntimeError('MEETING_EVENT_SECRET must be configured; no default key is accepted')
    path = Path(os.environ['MEETING_EVENT_DB']).resolve()
    application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @application.post('/meeting-events')
    async def receive(request: Request):
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > MAX_BYTES:
                return JSONResponse({'error':'body_too_large'}, status_code=413)
        body = bytes(chunks)
        nonce = request.headers.get('x-meeting-nonce', '')
        try:
            verify_signature(secret, request.headers.get('x-meeting-timestamp', ''), nonce,
                             request.headers.get('x-meeting-signature', ''), body)
            event = json.loads(body)
            if not isinstance(event, dict) or event.get('event_id') != request.headers.get('x-meeting-event-id'):
                raise ValueError('Event header/body mismatch')
            inserted = await asyncio.to_thread(persist_event, path, body, nonce)
        except (ValueError, UnicodeError):
            return JSONResponse({'error':'event_rejected'}, status_code=400)
        except (sqlite3.Error, OSError):
            # Do not acknowledge data that was not durably accepted.
            return JSONResponse({'error':'inbox_unavailable'}, status_code=503)
        return {'accepted':True, 'duplicate':not inserted}

    return application
