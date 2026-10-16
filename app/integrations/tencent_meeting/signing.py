"""Tencent Meeting AK/SK signature; not the generic Tencent Cloud SDK signer.
Reference: https://cloud.tencent.com/document/api/1095/42413
"""
import base64
import hashlib
import hmac


def sign_request(secret_id: str, secret_key: str, method: str, uri: str, body: bytes,
                 nonce: str, timestamp: str) -> str:
    header = f"X-TC-Key={secret_id}&X-TC-Nonce={nonce}&X-TC-Timestamp={timestamp}"
    material = method.upper().encode() + b"\n" + header.encode() + b"\n" + uri.encode() + b"\n" + body
    signature = hmac.new(secret_key.encode(), material, hashlib.sha256).hexdigest().encode()
    return base64.b64encode(signature).decode("ascii")
