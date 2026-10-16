"""Security primitives: tests precede implementation."""
import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest


def test_keyring_roundtrip_and_tenant_binding():
    from app.core.security import KeyRing
    key = base64.urlsafe_b64encode(bytes(range(32))).decode()
    ring = KeyRing({"k1": key}, "k1")
    value = ring.encrypt({"secret": "not-in-plaintext"}, "org-a:app-a")
    assert "not-in-plaintext" not in value
    assert ring.decrypt(value, "org-a:app-a") == {"secret": "not-in-plaintext"}
    with pytest.raises(ValueError):
        ring.decrypt(value, "org-b:app-a")


def test_keyring_rotation_reads_old_key():
    from app.core.security import KeyRing
    old = base64.urlsafe_b64encode(b"a" * 32).decode()
    new = base64.urlsafe_b64encode(b"b" * 32).decode()
    value = KeyRing({"old": old}, "old").encrypt({"a": 1}, "owner")
    assert KeyRing({"old": old, "new": new}, "new").decrypt(value, "owner") == {"a": 1}


def test_pkce_rfc7636_vector():
    from app.core.security import pkce_challenge, verify_pkce
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert pkce_challenge(verifier) == challenge
    assert verify_pkce(verifier, challenge)
    assert not verify_pkce("short", challenge)


def test_tokens_are_random_and_digest_only():
    from app.core.security import digest, random_token
    a, b = random_token("mt"), random_token("mt")
    assert a.startswith("mt_") and a != b and len(a) > 40
    assert digest(a) != a and len(digest(a)) == 64


def test_cursor_is_bound_and_expires():
    from app.core.security import CursorCodec
    from app.core.errors import MeetingError
    codec = CursorCodec(b"x" * 32)
    cursor = codec.encode({"after": "a"}, binding="member-a", now=100, lifetime=60)
    assert codec.decode(cursor, binding="member-a", now=101)["after"] == "a"
    with pytest.raises(MeetingError):
        codec.decode(cursor, binding="member-b", now=101)
    with pytest.raises(MeetingError):
        codec.decode(cursor, binding="member-a", now=161)
    with pytest.raises(MeetingError):
        codec.decode(cursor + "x", binding="member-a", now=101)


def test_tencent_signs_exact_body_bytes_and_query():
    from app.integrations.tencent_meeting.signing import sign_request
    body = '{"subject":"会议"}'.encode()
    uri = "/v1/meetings?userid=a%20b&instanceid=1"
    material = b"POST\nX-TC-Key=id&X-TC-Nonce=123&X-TC-Timestamp=456\n" + uri.encode() + b"\n" + body
    expected = base64.b64encode(hmac.new(b"key", material, hashlib.sha256).hexdigest().encode()).decode()
    assert sign_request("id", "key", "POST", uri, body, "123", "456") == expected


def test_webhook_crypto_and_signature_reject_tamper():
    from app.integrations.tencent_meeting.webhook import encrypt_fixture, decrypt_message, callback_signature, verify_callback
    key = base64.b64encode(b"k" * 32).decode().rstrip("=")
    encrypted = encrypt_fixture(b'{"event":"smart.minutes"}', key)
    signature = callback_signature("token", "100", "nonce", encrypted)
    assert verify_callback("token", "100", "nonce", encrypted, signature)
    assert not verify_callback("token", "100", "nonce", encrypted + "a", signature)
    assert decrypt_message(encrypted, key) == b'{"event":"smart.minutes"}'
    with pytest.raises(ValueError):
        decrypt_message("not base64!", key)


def test_normalize_minutes_preserves_empty_todo():
    from app.integrations.tencent_meeting.mapper import normalize_minutes
    value = normalize_minutes({"meeting_minute": {"minute": "## 原生纪要\n待办", "todo": ""}}, llm=3)
    assert value["minute"] == "## 原生纪要\n待办"
    assert value["todo"] == ""
    assert value["provider"] == "tencent_meeting"
    assert value["minute_type_effective"] == 2


def test_inclusive_transcript_pagination_requires_progress():
    from app.integrations.tencent_meeting.mapper import TranscriptCollector
    from app.core.errors import MeetingError
    collector = TranscriptCollector()
    first = {"minutes": {"paragraphs": [{"pid": "0", "sentences": []}, {"pid": "1", "sentences": []}]}, "more": True}
    assert collector.add(first) == "1"
    second = {"minutes": {"paragraphs": [{"pid": "1", "sentences": []}, {"pid": "2", "sentences": []}]}, "more": False}
    assert collector.add(second) is None
    assert [x["pid"] for x in collector.finish()["paragraphs"]] == ["0", "1", "2"]
    stalled = TranscriptCollector()
    stalled.add(first)
    with pytest.raises(MeetingError):
        stalled.add(first)


def test_partial_transcript_cannot_finish():
    from app.integrations.tencent_meeting.mapper import TranscriptCollector
    from app.core.errors import MeetingError
    c = TranscriptCollector()
    c.add({"minutes": {"paragraphs": [{"pid": "a"}]}, "more": True})
    with pytest.raises(MeetingError):
        c.finish()


def test_unknown_parameters_and_naive_times_rejected():
    from app.schemas.requests import MeetingCreate
    from pydantic import ValidationError
    now = datetime.now(UTC)
    fields = dict(subject="demo", start_at=now+timedelta(hours=1), end_at=now+timedelta(hours=2), host_member_id="m", connection_ref="c")
    assert MeetingCreate(**fields).subject == "demo"
    with pytest.raises(ValidationError):
        MeetingCreate(**fields, confirmed=True)
    fields["start_at"] = datetime(2027, 1, 1)
    with pytest.raises(ValidationError):
        MeetingCreate(**fields)


def test_download_url_validation_blocks_ssrf():
    from app.storage.safe_http import validate_url, validate_ips
    from app.core.errors import MeetingError
    assert validate_url("https://cdn.example.org/file", ["cdn.example.org"]).hostname == "cdn.example.org"
    for url in ["http://cdn.example.org/x", "https://evil.example/x", "https://user:pass@cdn.example.org/x", "https://cdn.example.org:99/x", "https://cdn.example.org/x#fragment"]:
        with pytest.raises(MeetingError):
            validate_url(url, ["cdn.example.org"])
    for address in ["127.0.0.1", "169.254.169.254", "::1", "10.1.2.3", "0.0.0.0", "::ffff:127.0.0.1"]:
        with pytest.raises(MeetingError):
            validate_ips([address])


def test_production_refuses_sqlite_and_insecure_urls():
    from app.core.config import Settings
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Settings(environment="production", database_url="sqlite://", public_base_url="http://example.org")


def test_error_payload_never_echoes_input_secret():
    from app.core.errors import MeetingError
    value = MeetingError("RESOURCE_NOT_ACCESSIBLE", 404).payload("trace")
    assert value["reason"] == "RESOURCE_NOT_ACCESSIBLE"
    assert value["trace_id"] == "trace" and value["data"] is None
