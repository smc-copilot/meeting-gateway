"""Encrypted private content objects; local filesystem is never exposed as a static route."""
import asyncio
import os
import tempfile
from pathlib import Path
from uuid import uuid4
from app.core.security import digest


class LocalEncryptedStorage:
    def __init__(self, root: Path, keyring):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.keyring = keyring

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("Invalid private object key")
        return path

    async def put(self, org_id: str, asset_id: str, value: bytes) -> str:
        key = digest(org_id)[:16] + "/" + str(uuid4()) + ".enc"
        path = self._path(key)
        encrypted = self.keyring.encrypt_bytes(value, "asset:" + org_id + ":" + asset_id)
        def write():
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(encrypted); handle.flush(); os.fsync(handle.fileno())
                os.replace(temp, path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        await asyncio.to_thread(write)
        return key

    async def get(self, key: str, org_id: str, asset_id: str) -> bytes:
        encrypted = await asyncio.to_thread(self._path(key).read_bytes)
        return self.keyring.decrypt_bytes(encrypted, "asset:" + org_id + ":" + asset_id)

    async def remove(self, key: str):
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)
