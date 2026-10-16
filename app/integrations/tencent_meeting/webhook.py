"""Tencent callbacks: SHA1(sorted values), AES-CBC and strict PKCS7 unpadding.
References: Tencent 51612 / 54658. No WeChat random16/length/corp suffix stripping.
"""
import base64
import hashlib
import hmac
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def callback_signature(token: str, timestamp: str, nonce: str, data: str) -> str:
    return hashlib.sha1("".join(sorted([token, timestamp, nonce, data])).encode()).hexdigest()


def verify_callback(token: str, timestamp: str, nonce: str, data: str, signature: str) -> bool:
    return hmac.compare_digest(callback_signature(token, timestamp, nonce, data), signature)


def _key(value: str) -> bytes:
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), validate=True)
        if len(raw) != 32:
            raise ValueError("size")
        return raw
    except Exception as exc:
        raise ValueError("Invalid callback encryption key") from exc


def decrypt_message(value: str, encoding_key: str) -> bytes:
    try:
        key = _key(encoding_key)
        ciphertext = base64.b64decode(value, validate=True)
        if not ciphertext or len(ciphertext) % 16:
            raise ValueError("ciphertext length")
        decryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return unpadder.update(padded) + unpadder.finalize()
    except Exception as exc:
        raise ValueError("Callback decryption failed") from exc


def encrypt_fixture(value: bytes, encoding_key: str) -> str:
    """Deterministic IV is mandated by Tencent; used only to make callback test fixtures."""
    key = _key(encoding_key)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(value) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()
