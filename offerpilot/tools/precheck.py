#!/usr/bin/env python3
"""Read-only, local 30-day application deduplication precheck.

The tool reads a Markdown application tracker in the local workspace and answers one
question: should this application be blocked because the same company, title,
and city already appear within the 30 days before the supplied check date?

It never writes the tracker, never calls a network service, and never submits
an application.  It only reads the file named by --tracker.

Canonical tracker layout:

    | # | Date | Company | Role | Score | Status | PDF | Report | Notes |

The tracker also supports optional Via, Location, and URL columns.  A City or
Location column supplies the city used by the fingerprint.  Because the stock
nine-column tracker has neither, this tool warns when no city column is found
rather than silently treating every row as having a blank city.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
SEPARATOR_CELL_RE = re.compile(r":?-{3,}:?")
ZERO_WIDTH_RE = re.compile(r"[​‌‍﻿]")
MARKDOWN_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
WHITESPACE_RE = re.compile(r"\s+")

# These are the canonical status labels used by the local tracker template,
# plus the aliases for the two states that must not block a duplicate check.
# Status matching is case-insensitive and whitespace-normalized, but remains
# exact: no fuzzy status matching.
EXCLUDED_STATUSES = frozenset(
    {
        "discarded",
        "descartado",
        "descartada",
        "cerrada",
        "cancelada",
        "iptal edildi",
        "ıptal edildi",
        "lapsed",
        "已放弃",
        "放弃",
        "已关闭",
        "已放棄",
        "放棄",
        "已關閉",
        "skip",
        "no aplicar",
        "monitor",
        "geo blocker",
        "uygun değil",
        "uygun degil",
        "不投",
        "跳过",
        "跳過",
    }
)

# The shared tracker alias vocabulary, reduced to the fields this tool needs
# (and Chinese labels used by the local operator).  The header is resolved by
# name, case- and separator-insensitively.
HEADER_ALIASES = {
    "#": "num",
    "num": "num",
    "id": "num",
    "编号": "num",
    "date": "date",
    "fecha": "date",
    "datum": "date",
    "data": "date",
    "dato": "date",
    "tanggal": "date",
    "tarih": "date",
    "日期": "date",
    "company": "company",
    "empresa": "company",
    "firma": "company",
    "virksomhed": "company",
    "virksomhet": "company",
    "perusahaan": "company",
    "entreprise": "company",
    "azienda": "company",
    "şirket": "company",
    "公司": "company",
    "公司名称": "company",
    "企业": "company",
    "雇主": "company",
    "role": "role",
    "puesto": "role",
    "rolle": "role",
    "rola": "role",
    "vaga": "role",
    "ruolo": "role",
    "rol": "role",
    "岗位": "role",
    "职位": "role",
    "岗位名称": "role",
    "location": "city",
    "city": "city",
    "ort": "city",
    "城市": "city",
    "地点": "city",
    "工作地点": "city",
    "工作城市": "city",
    "score": "score",
    "punteggio": "score",
    "puan": "score",
    "评分": "score",
    "status": "status",
    "statut": "status",
    "stato": "status",
    "durum": "status",
    "状态": "status",
    "notes": "notes",
    "notlar": "notes",
    "备注": "notes",
    "url": "url",
    "链接": "url",
}
REQUIRED_HEADER_FIELDS = frozenset({"num", "company", "role", "score", "status"})
LEGACY_COLUMNS = {
    "num": 0,
    "date": 1,
    "company": 2,
    "role": 3,
    "score": 4,
    "status": 5,
    "pdf": 6,
    "report": 7,
    "notes": 8,
}

# Legal-entity suffixes used when comparing company names
# LEGAL_SUFFIXES.  Only legal forms are stripped; generic words such as
# "Technologies" or "Group" are deliberately kept because removing them would
# merge genuinely different employers.
LEGAL_SUFFIXES = (
    "incorporated",
    "corporation",
    "company",
    "limited",
    "gmbh",
    "kgaa",
    "sarl",
    "eurl",
    "llc",
    "llp",
    "plc",
    "apc",
    "inc",
    "corp",
    "ltd",
    "llp",
    "lp",
    "pc",
    "ag",
    "mbh",
    "ug",
    "sas",
    "snc",
    "scs",
    "sca",
    "sa",
    "spa",
    "srl",
    "ltda",
    "saa",
    "sl",
    "sll",
    "slu",
    "bv",
    "nv",
    "cv",
    "ab",
    "as",
    "oy",
    "oyj",
    "kf",
    "sf",
    "aps",
    "se",
    "jsc",
    "pjsc",
    "zao",
    "ooo",
    "doo",
    "kft",
    "rt",
    "zrt",
    "pty",
    "pte",
    "pvt",
    "sdn",
    "bhd",
    "co",
)
CJK_LEGAL_SUFFIXES = tuple(
    sorted(
        ("股份有限公司", "有限责任公司", "有限公司", "公司", "株式会社", "有限会社"),
        key=len,
        reverse=True,
    )
)

_LATIN_SUFFIX_PATTERNS = sorted(
    {
        *(re.escape(suffix) for suffix in LEGAL_SUFFIXES),
        r"co\.?,?\s*ltd\.?",
        r"pty\.?\s*ltd\.?",
        r"pte\.?\s*ltd\.?",
        r"pvt\.?\s*ltd\.?",
        r"s\.a\.r\.l\.?",
        r"s\.a\.s\.?",
        r"s\.a\.?",
        r"b\.v\.?",
        r"n\.v\.?",
        r"k\.k\.?",
    },
    key=len,
    reverse=True,
)
_LATIN_SUFFIX_RE = re.compile(
    r"(?:[,\s，]+(?:" + "|".join(_LATIN_SUFFIX_PATTERNS) + r")\.?\s*[.,;:]*)$",
    re.IGNORECASE,
)


def _base_text(value: Any) -> str:
    """Normalize width and strip harmless Markdown decoration from one cell."""

    text = unicodedata.normalize("NFKC", str(value if value is not None else ""))
    text = MARKDOWN_LINK_RE.sub(r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return ZERO_WIDTH_RE.sub("", text).strip()


def _collapse_whitespace(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value).strip()


def normalize_title(value: Any) -> str:
    """Case-fold, width-normalize, and collapse whitespace in a title."""

    return _collapse_whitespace(_base_text(value).casefold())


def normalize_city(value: Any) -> str:
    """Case-fold, width-normalize, and collapse whitespace in a city."""

    return _collapse_whitespace(_base_text(value).casefold())


def _strip_cjk_legal_suffixes(value: str) -> str:
    text = value.strip(" \t\r\n,，.。;；:：")
    while True:
        for suffix in CJK_LEGAL_SUFFIXES:
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)].strip(" \t\r\n,，.。;；:：")
                break
        else:
            return text


def normalize_company(value: Any) -> str:
    """Remove common legal suffixes, case-fold, and remove whitespace."""

    text = _collapse_whitespace(_base_text(value).casefold())
    text = _strip_cjk_legal_suffixes(text)
    previous = None
    while text and text != previous:
        previous = text
        text = _LATIN_SUFFIX_RE.sub("", text)
        text = text.strip(" \t\r\n,，.。;；:：")
    return WHITESPACE_RE.sub("", text).strip(" \t\r\n,，.。;；:：")


def normalize_status(value: Any) -> str:
    """Normalize a status label for the exact Discarded/SKIP exclusion test."""

    text = _collapse_whitespace(_base_text(value).casefold())
    return text.replace("_", " ")


def compute_fingerprint(company: Any, title: Any, city: Any) -> str:
    """SHA-256 of normalize(company)|normalize(title)|normalize(city)."""

    key = "|".join(
        (normalize_company(company), normalize_title(title), normalize_city(city))
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _split_table_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    cells = re.split(r"(?<!\\)\|", stripped)
    if cells and cells[0].strip() == "":
        cells = cells[1:]
    if cells and cells[-1].strip() == "":
        cells = cells[:-1]
    return [cell.replace("\\|", "|").strip() for cell in cells]


def _header_key(cell: str) -> str:
    return _collapse_whitespace(_base_text(cell).casefold()).replace("_", " ").strip(" :")


def _header_map(cells: list[str]) -> dict[str, int] | None:
    field_map: dict[str, int] = {}
    for index, cell in enumerate(cells):
        field = HEADER_ALIASES.get(_header_key(cell))
        if field is not None and field not in field_map:
            field_map[field] = index
    if REQUIRED_HEADER_FIELDS.issubset(field_map):
        return field_map
    return None


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(
        SEPARATOR_CELL_RE.fullmatch(cell.replace(" ", "")) for cell in cells
    )


def _cell(cells: list[str], field_map: dict[str, int], field: str) -> str:
    index = field_map.get(field)
    if index is None or index >= len(cells):
        return ""
    return cells[index]


def _parse_date_cell(value: Any) -> tuple[dt.date | None, str | None]:
    text = _collapse_whitespace(_base_text(value))
    if not text:
        return None, "missing-date"
    if not DATE_RE.fullmatch(text):
        return None, "unparsable-date"
    try:
        return dt.date.fromisoformat(text), None
    except ValueError:
        return None, "unparsable-date"


def _warning(
    line_number: int, reason: str, raw_line: str, date_text: str = ""
) -> dict[str, Any]:
    return {
        "line": line_number,
        "reason": reason,
        "date": date_text,
        "raw_line": raw_line.strip(),
    }


def evaluate_tracker_text(
    tracker_text: str,
    company: str,
    title: str,
    city: str,
    check_date: dt.date,
) -> dict[str, Any]:
    """Evaluate tracker text and return the required JSON-compatible result."""

    lines = tracker_text.splitlines()
    wanted_fingerprint = compute_fingerprint(company, title, city)
    matches: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    header_index = None
    field_map = None
    for index, line in enumerate(lines):
        cells = _split_table_row(line)
        if not cells:
            continue
        candidate_map = _header_map(cells)
        if candidate_map is not None:
            header_index = index
            field_map = candidate_map
            break

    if field_map is None:
        field_map = dict(LEGACY_COLUMNS)
        warnings.append(_warning(0, "no-tracker-table-header", ""))
    elif "city" not in field_map:
        warnings.append(
            _warning(
                header_index + 1,
                "no-city-column",
                lines[header_index],
            )
        )

    start_index = header_index + 1 if header_index is not None else 0
    seen_data_row = False
    for index in range(start_index, len(lines)):
        line_number = index + 1
        raw_line = lines[index]
        cells = _split_table_row(raw_line)
        if not cells:
            if seen_data_row:
                break
            continue
        if _is_separator(cells):
            continue
        if _header_map(cells) is not None:
            continue
        if not any(cell for cell in cells):
            continue
        seen_data_row = True

        if max(field_map.values()) >= len(cells):
            warnings.append(_warning(line_number, "malformed-row", raw_line))
            continue

        row_company = _cell(cells, field_map, "company")
        row_title = _cell(cells, field_map, "role")
        row_city = _cell(cells, field_map, "city")
        row_status = _cell(cells, field_map, "status")
        row_date_text = _cell(cells, field_map, "date")

        if "city" in field_map and not _base_text(row_city):
            warnings.append(_warning(line_number, "missing-city", raw_line))

        parsed_date, date_error = _parse_date_cell(row_date_text)
        if date_error is not None:
            warnings.append(
                _warning(line_number, date_error, raw_line, _base_text(row_date_text))
            )
            continue

        row_fingerprint = compute_fingerprint(row_company, row_title, row_city)
        if row_fingerprint != wanted_fingerprint:
            continue
        if normalize_status(row_status) in EXCLUDED_STATUSES:
            continue

        window_start = check_date - dt.timedelta(days=30)
        if not (window_start <= parsed_date <= check_date):
            continue

        matches.append(
            {
                "company": _base_text(row_company),
                "title": _base_text(row_title),
                "role": _base_text(row_title),
                "date": parsed_date.isoformat(),
                "status": _base_text(row_status),
                "line": line_number,
                "raw_line": raw_line.strip(),
            }
        )

    matches.sort(key=lambda item: item["line"])
    warnings.sort(key=lambda item: (item["line"], item["reason"]))
    return {
        "block": bool(matches),
        "fingerprint": wanted_fingerprint,
        "matches": matches,
        "warnings": warnings,
    }


def _parse_cli_date(value: str) -> dt.date:
    if not DATE_RE.fullmatch(value or ""):
        raise argparse.ArgumentTypeError("expected a date in YYYY-MM-DD form")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "expected a real date in YYYY-MM-DD form"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only local pre-application duplicate check. Blocks when the "
            "same company/title/city fingerprint was recorded in the 30 days "
            "before --date. Never writes, never submits, never uses the network."
        )
    )
    parser.add_argument("--tracker", required=True, help="path to applications.md")
    parser.add_argument("--company", required=True, help="company name to check")
    parser.add_argument("--title", required=True, help="role title to check")
    parser.add_argument("--city", required=True, help="city to check")
    parser.add_argument(
        "--date",
        required=True,
        type=_parse_cli_date,
        help="check date in YYYY-MM-DD form",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not normalize_company(args.company):
        parser.error("--company must not be empty after normalization")
    if not normalize_title(args.title):
        parser.error("--title must not be empty after normalization")
    if not normalize_city(args.city):
        parser.error("--city must not be empty after normalization")

    try:
        tracker_text = Path(args.tracker).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        parser.error(f"cannot read tracker {args.tracker!r}: {exc}")

    result = evaluate_tracker_text(
        tracker_text=tracker_text,
        company=args.company,
        title=args.title,
        city=args.city,
        check_date=args.date,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"fingerprint: {result['fingerprint']}")
    print(f"block: {'true' if result['block'] else 'false'}")
    for match in result["matches"]:
        print(
            f"- line {match['line']}: {match['company']} | {match['title']} | "
            f"{match['date']} | {match['status']}"
        )
    for warning in result["warnings"]:
        print(
            f"! line {warning['line']}: {warning['reason']} | {warning['raw_line']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
