"""Windows-user DPAPI storage for local development credentials."""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
from pathlib import Path


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _crypt(data: bytes, protect: bool) -> bytes:
    if not hasattr(ctypes, "windll"):
        raise RuntimeError("DPAPI is only available on Windows")
    source = ctypes.create_string_buffer(data)
    input_blob = _Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)))
    output_blob = _Blob()
    function = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not function(ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)


def load(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != 1:
            return {}
        result = {}
        for name, value in payload.get("values", {}).items():
            if isinstance(name, str) and isinstance(value, str):
                result[name] = _crypt(base64.b64decode(value), False).decode("utf-8")
        return result
    except (OSError, ValueError, TypeError, UnicodeError, json.JSONDecodeError):
        return {}


def save(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "values": {name: base64.b64encode(_crypt(value.encode("utf-8"), True)).decode("ascii")
                   for name, value in values.items() if isinstance(value, str) and value},
    }
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
