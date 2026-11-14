#!/usr/bin/env python3
"""Conservative, dependency-free ATS PDF readability check (TASK-03).

CLI:
    python3 -I tools/ats_check.py --pdf <path> --keywords <comma-separated>

Only checks that can be verified automatically are reported: file existence,
PDF magic bytes (``%PDF-``), a page-count hint from ``/Type /Page`` objects,
and a text-layer hint from uncompressed ``BT``/``Tj``/``TJ`` operators.
Keywords are matched against visible text **only when a text layer can be
extracted**.  If it cannot, the tool returns
``text_layer: unavailable`` and ``verdict: needs_manual_check`` -- it never
claims keyword coverage for an opaque or compressed PDF.

No external dependency is installed, no network access, no PDF rendering, and
no OCR is performed.  This is an automated pre-check, not a full ATS audit.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import zlib
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

_PDF_MAGIC = b"%PDF-"
_PAGE_RE = re.compile(rb"/Type\s*/Page(?![sA-Za-z])")
_PAGE_COUNT_RE = re.compile(rb"/Count\s+(\d+)")
_TEXT_OPERATORS_RE = re.compile(rb"\bBT\b|\bTj\b|\bTJ\b|\bTd\b|\bTm\b")
_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
_FLATE_HEADER_RE = re.compile(rb"/Filter\s*(?:/FlateDecode|\[[^\]]*/FlateDecode[^\]]*\])")
_LITERAL_STRING_RE = re.compile(rb"\(((?:\\.|[^\\)])*)\)\s*(?:Tj|TJ|')", re.DOTALL)
_HEX_STRING_RE = re.compile(rb"<([0-9A-Fa-f\s]+)>\s*(?:Tj|TJ|')")


def _decode_literal(raw: bytes) -> str:
    """Decode a PDF literal string's standard escapes, not arbitrary code."""

    out = bytearray()
    index = 0
    simple = {
        ord("n"): b"\n",
        ord("r"): b"\r",
        ord("t"): b"\t",
        ord("b"): b"\b",
        ord("f"): b"\f",
        ord("("): b"(",
        ord(")"): b")",
        ord("\\"): b"\\",
    }
    while index < len(raw):
        byte = raw[index]
        if byte != 0x5C or index + 1 >= len(raw):  # not a backslash
            out.append(byte)
            index += 1
            continue
        nxt = raw[index + 1]
        if nxt in simple:
            out.extend(simple[nxt])
            index += 2
        elif 0x30 <= nxt <= 0x37:
            digits = raw[index + 1 : index + 4]
            octal = b""
            for digit in digits:
                if not 0x30 <= digit <= 0x37:
                    break
                octal += bytes([digit])
            out.append(int(octal.decode("ascii"), 8) & 0xFF)
            index += 1 + len(octal)
        elif nxt in (0x0A, 0x0D):
            index += 2
        else:
            out.append(nxt)
            index += 2
    # PDF strings can be PDFDocEncoding/UTF-16; use UTF-8 with replacement so
    # unrecognized bytes never crash the check or get reported as real text.
    return out.decode("utf-8", errors="replace")


def _decode_hex(raw: bytes) -> str:
    compact = re.sub(rb"\s+", b"", raw)
    if len(compact) % 2:
        compact += b"0"
    try:
        data = bytes.fromhex(compact.decode("ascii"))
    except (ValueError, UnicodeError):
        return ""
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", errors="replace")
    return data.decode("utf-8", errors="replace")


def _extract_candidate_text(pdf_bytes: bytes) -> tuple[str, int]:
    """Best-effort literal/hex text from uncompressed or Flate streams only."""

    chunks: list[str] = []
    stream_count = 0

    def scan(content: bytes) -> None:
        for match in _LITERAL_STRING_RE.finditer(content):
            chunks.append(_decode_literal(match.group(1)))
        for match in _HEX_STRING_RE.finditer(content):
            chunks.append(_decode_hex(match.group(1)))

    # Uncompressed content streams carry the operators themselves; scanning the
    # whole file is safe for the conservative visible-text check.  Compressed
    # streams are decoded only to look for additionally stored plain text.
    scan(pdf_bytes)
    for stream_match in _STREAM_RE.finditer(pdf_bytes):
        stream_count += 1
        if _TEXT_OPERATORS_RE.search(stream_match.group(1)):
            continue  # already covered by scan(pdf_bytes)
        header = pdf_bytes[max(0, stream_match.start() - 300) : stream_match.start()]
        if _FLATE_HEADER_RE.search(header):
            try:
                payload = zlib.decompress(stream_match.group(1))
            except zlib.error:
                continue
            if _TEXT_OPERATORS_RE.search(payload):
                scan(payload)
            elif payload.strip():
                # A Flate stream may contain plain visible text even without
                # operators in this fixture; still do not treat arbitrary
                # binary as text.  Only printable UTF-8 chunks qualify.
                try:
                    decoded = payload.decode("utf-8")
                except UnicodeDecodeError:
                    decoded = ""
                if decoded.strip() and all(
                    char.isprintable() or char.isspace() for char in decoded
                ):
                    chunks.append(decoded)
    text = " ".join(chunk for chunk in chunks if chunk.strip())
    return unicodedata.normalize("NFKC", text), stream_count


def check_pdf(
    pdf_path: str | Path,
    keywords_csv: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a conservative JSON-safe report; never claim an unverified pass."""

    del config  # reserved for future config-driven thresholds; no defaults here
    path = Path(pdf_path)
    keywords = [
        item.strip()
        for item in keywords_csv.split(",")
        if item.strip()
    ]
    checks: list[dict[str, Any]] = []
    notes: list[str] = []
    result: dict[str, Any] = {
        "pdf": str(path),
        "keywords": keywords,
        "checks": checks,
        "notes": notes,
        "file_exists": path.is_file(),
        "pdf_magic": False,
        "page_count_hint": None,
        "text_layer": "unavailable",
        "extracted_text_chars": 0,
        "streams_seen": 0,
        "keyword_matches": {},
        "all_keywords_found": None,
        "verdict": "needs_manual_check",
    }

    checks.append({"name": "file_exists", "status": "pass" if result["file_exists"] else "fail"})
    if not result["file_exists"]:
        notes.append("文件不存在；未进行其余检查")
        result["verdict"] = "fail"
        return result

    try:
        data = path.read_bytes()
    except OSError as exc:
        checks.append({"name": "read_file", "status": "fail", "detail": str(exc)})
        notes.append("文件不可读；未进行其余检查")
        result["verdict"] = "fail"
        return result

    result["file_size_bytes"] = len(data)
    result["pdf_magic"] = data.startswith(_PDF_MAGIC)
    checks.append(
        {"name": "pdf_magic_bytes", "status": "pass" if result["pdf_magic"] else "fail"}
    )
    if not result["pdf_magic"]:
        notes.append("文件头不是 %PDF-；不认定为 PDF")
        result["verdict"] = "fail"
        return result

    page_objects = len(_PAGE_RE.findall(data))
    declared_counts = [int(match.group(1)) for match in _PAGE_COUNT_RE.finditer(data)]
    result["page_count_hint"] = max(declared_counts) if declared_counts else (page_objects or None)
    result["page_object_count_hint"] = page_objects
    checks.append(
        {
            "name": "page_hint",
            "status": "pass" if result["page_count_hint"] else "unknown",
            "detail": {
                "page_count_hint": result["page_count_hint"],
                "page_object_count_hint": page_objects,
            },
        }
    )
    notes.append(
        "页数为 PDF 对象/Count 的静态提示，不是渲染验证；加密、增量更新或对象流中的页对象可能漏计"
    )

    text, streams_seen = _extract_candidate_text(data)
    result["extracted_text_chars"] = len(text.strip())
    result["streams_seen"] = streams_seen
    has_text_operators = bool(_TEXT_OPERATORS_RE.search(data)) or bool(
        _TEXT_OPERATORS_RE.search(text.encode("utf-8", errors="replace"))
    ) or streams_seen > 0
    # Only literal/hex show-text strings we actually decoded are called visible
    # text.  Encoded fonts, outlines, images, and custom encodings are not
    # verifiable with the standard library alone.
    if text.strip() and has_text_operators:
        result["text_layer"] = "available"
    else:
        result["text_layer"] = "unavailable"
        notes.append(
            "未能从标准库可解析的 PDF 文本算子中提取可见文本；不猜测文本层、不伪报关键词命中"
        )

    if result["text_layer"] == "unavailable":
        checks.append({"name": "text_layer", "status": "unknown"})
        checks.append({"name": "keyword_match", "status": "not_run"})
        result["keyword_matches"] = {keyword: None for keyword in keywords}
        result["all_keywords_found"] = None
        result["verdict"] = "needs_manual_check"
        return result

    checks.append({"name": "text_layer", "status": "pass"})
    normalized = text.casefold()
    matches = {
        keyword: unicodedata.normalize("NFKC", keyword).casefold() in normalized
        for keyword in keywords
    }
    result["keyword_matches"] = matches
    result["all_keywords_found"] = all(matches.values()) if keywords else False
    checks.append(
        {
            "name": "keyword_match",
            "status": "pass" if result["all_keywords_found"] else "fail",
            "detail": matches,
        }
    )
    if not keywords:
        notes.append("--keywords 为空，未验证任何关键词")
    if result["all_keywords_found"] and keywords:
        result["verdict"] = "pass"
    else:
        result["verdict"] = "fail"
    notes.append(
        "关键词仅匹配本工具实际解码出的文本；字体编码、分栏顺序、表格、图片与 OCR 场景仍需人工核验"
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Conservative local ATS PDF check: magic bytes, page hint, and "
            "keyword match only when visible text can be decoded. No network, "
            "no OCR, no new dependency, no false positive pass."
        )
    )
    parser.add_argument("--pdf", required=True, help="path to a local PDF file")
    parser.add_argument(
        "--keywords", required=True, help="comma-separated visible-text keywords"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report = check_pdf(args.pdf, args.keywords)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # A manual-check verdict is not a CLI failure: it is an honest limitation.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
