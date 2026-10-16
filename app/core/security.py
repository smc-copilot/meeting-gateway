"""Authenticated encryption and purpose-bound high entropy tokens."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.core.errors import MeetingError


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def random_token(prefix: str = "mt") -> str:
    return prefix + "_" + secrets.token_urlsafe(32)


def pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode().rstrip("=")


def verify_pkce(verifier: str, challenge: str) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
        return False
    return hmac.compare_digest(pkce_challenge(verifier), challenge)


class KeyRing:
    def __init__(self, keys: dict[str, str], active: str):
        self.keys = {name: base64.urlsafe_b64decode(value) for name, value in keys.items()}
        if active not in self.keys or any(len(value) != 32 for value in self.keys.values()):
            raise ValueError("Valid 256-bit encryption keyring required")
        self.active = active

    def encrypt_bytes(self, value: bytes, aad: str) -> bytes:
        nonce = secrets.token_bytes(12)
        payload = AESGCM(self.keys[self.active]).encrypt(nonce, value, aad.encode())
        return (self.active + "." + base64.urlsafe_b64encode(nonce + payload).decode()).encode()

    def decrypt_bytes(self, value: bytes, aad: str) -> bytes:
        try:
            key, encoded = value.decode().split(".", 1)
            raw = base64.urlsafe_b64decode(encoded)
            return AESGCM(self.keys[key]).decrypt(raw[:12], raw[12:], aad.encode())
        except Exception as exc:
            raise ValueError("Encrypted material failed authentication") from exc

    def encrypt(self, value, aad: str) -> str:
        return self.encrypt_bytes(canonical(value), aad).decode()

    def decrypt(self, value: str, aad: str):
        return json.loads(self.decrypt_bytes(value.encode(), aad))

    def purpose_key(self, purpose: str) -> bytes:
        return hmac.new(self.keys[self.active], b"meeting-v1:" + purpose.encode(), hashlib.sha256).digest()


class CursorCodec:
    def __init__(self, key: bytes):
        self.key = key

    def encode(self, payload: dict, *, binding: str, now: float | None = None, lifetime: int = 900) -> str:
        raw = canonical({"payload": payload, "binding": digest(binding), "exp": (time.time() if now is None else now) + lifetime})
        encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        signature = hmac.new(self.key, encoded.encode(), hashlib.sha256).hexdigest()
        return encoded + "." + signature

    def decode(self, value: str, *, binding: str, now: float | None = None) -> dict:
        try:
            if len(value) > 8192:
                raise ValueError("oversize")
            encoded, signature = value.split(".", 1)
            expected = hmac.new(self.key, encoded.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("signature")
            data = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            if data["binding"] != digest(binding) or data["exp"] <= (time.time() if now is None else now):
                raise ValueError("binding or expiry")
            return data["payload"]
        except Exception as exc:
            raise MeetingError("CURSOR_INVALID", 400) from exc
