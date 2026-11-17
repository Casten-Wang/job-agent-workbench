#!/usr/bin/env python3
"""Structured adapter boundary for optional local faster-whisper ASR.

This offline build never installs a package, downloads a model, opens an audio
file, or fabricates a transcript. When faster-whisper is importable it still
requires an explicit ``enabled=True`` call from the user; otherwise it returns
``unavailable`` with the documented install command.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
sys.dont_write_bytecode = True

CONFIG_PATH = _TOOLS_DIR / "config_task05.json"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def transcribe(
    audio_path: str | Path,
    model_size: str | None = None,
    language: str | None = None,
    enabled: bool = False,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    asr = cfg["asr"]
    model_size = model_size or asr["default_model_size"]
    language = language or asr["default_language"]
    result: dict[str, Any] = {
        "ok": False,
        "status": "unavailable",
        "engine": "faster-whisper-adapter",
        "audio_path": str(audio_path),
        "model_size": model_size,
        "language": language,
        "transcript": None,
        "install_command": asr["install_command"],
    }
    if not enabled:
        result["reason"] = "not-enabled; this offline build does not process audio"
        return result
    if importlib.util.find_spec("faster_whisper") is None:
        result["reason"] = "faster_whisper is not installed; no transcript was invented"
        return result
    result["reason"] = "faster_whisper is importable; a user-supplied local runner must load the model and audio explicitly"
    result["next_step"] = "A user-supplied local runner must call faster_whisper.WhisperModel with explicit user confirmation; no runner is implemented in this build."
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline ASR adapter status (no audio processing)")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--model-size")
    parser.add_argument("--language")
    args = parser.parse_args(argv)
    result = transcribe(args.audio, args.model_size, args.language)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
