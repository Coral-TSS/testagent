"""Content-addressed artifact store (sha256), atomic writes, verified reads."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

from testagent.core.errors import AppError

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class ArtifactStore:
    def __init__(self, root: Path, max_bytes: int = 50 * 1024 * 1024):
        self.root = Path(root)
        self.max_bytes = max_bytes

    def _path(self, digest: str) -> Path:
        if not _DIGEST.match(digest):
            raise AppError("VALIDATION", "Invalid artifact digest")
        return self.root / "sha256" / digest[:2] / digest

    def put(self, data: bytes) -> str:
        if len(data) > self.max_bytes:
            raise AppError("ARTIFACT_TOO_LARGE", "Artifact exceeds the size limit")
        digest = hashlib.sha256(data).hexdigest()
        target = self._path(digest)
        if target.exists():
            return digest
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return digest

    def get(self, digest: str) -> bytes:
        path = self._path(digest)
        if not path.exists():
            raise AppError("NOT_FOUND", "Artifact not found")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise AppError("ARTIFACT_CORRUPT", "Artifact content does not match its digest")
        return data
