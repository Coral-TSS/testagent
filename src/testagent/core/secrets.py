"""Local secret store (runtime/secrets.json). Windows: DPAPI; elsewhere: file mode 600."""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
from pathlib import Path


def _dpapi(data: bytes, protect: bool) -> bytes:  # pragma: no cover - Windows only
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = Blob(len(data), buffer)
    blob_out = Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise OSError("DPAPI operation failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


class SecretStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._windows = sys.platform == "win32"

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, self.path)
        if not self._windows:
            os.chmod(self.path, 0o600)

    def set(self, name: str, value: str) -> None:
        raw = value.encode("utf-8")
        stored = _dpapi(raw, True) if self._windows else raw
        with self._lock:
            data = self._read()
            data[name] = base64.b64encode(stored).decode("ascii")
            self._write(data)

    def get(self, name: str) -> str | None:
        with self._lock:
            encoded = self._read().get(name)
        if encoded is None:
            return None
        raw = base64.b64decode(encoded)
        return (_dpapi(raw, False) if self._windows else raw).decode("utf-8")

    def delete(self, name: str) -> None:
        with self._lock:
            data = self._read()
            data.pop(name, None)
            self._write(data)

    def values(self) -> tuple[str, ...]:
        with self._lock:
            names = list(self._read())
        return tuple(v for v in (self.get(n) for n in names) if v)

    @staticmethod
    def mask(value: str | None) -> str | None:
        if not value:
            return None
        return "****" + value[-4:] if len(value) > 8 else "****"
