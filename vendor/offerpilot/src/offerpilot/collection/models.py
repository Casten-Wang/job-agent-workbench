"""Data contracts shared by all job collection platforms."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Callable, Literal

from offerpilot.collection.text import clean_job_description
from offerpilot.ai.prefilter import _parse_salary_range_k  # shared salary-range parser


PlatformId = Literal["boss", "zhilian", "51job", "liepin"]


def classify_recruitment_type(title: str = "", experience: str = "", jd: str = "") -> str:
    """Classify explicit campus/social recruitment signals conservatively."""
    text = " ".join(str(value or "") for value in (title, experience, jd))
    if any(marker in text for marker in ("校招", "校园招聘", "应届", "毕业生", "管培生")):
        return "campus"
    if any(marker in text for marker in ("社招", "社会招聘")):
        return "experienced"
    if re.search(r"\d+\s*(?:[-–~至]\s*\d+\s*)?年(?:以上|及以上)?(?:工作)?经验", text):
        return "experienced"
    if re.fullmatch(r"\s*\d+\s*(?:[-–~至]\s*\d+\s*)?年(?:以上|及以上)?\s*", str(experience or "")):
        return "experienced"
    return "unknown"


@dataclass(frozen=True)
class PlatformCollectionRequest:
    platform: PlatformId
    keywords: list[str]
    cities: list[str]
    city_codes: dict[str, str]
    max_pages: int = 3
    sort: str = "default"
    filters: dict[str, Any] = field(default_factory=dict)
    city_yield_policy: dict[str, Any] | None = None
    keyword_start: dict[str, int] = field(default_factory=dict)


@dataclass
class JobCandidate:
    """A platform-neutral job candidate emitted by a collector."""

    platform: PlatformId
    source_job_id: str
    title: str
    company: str
    salary: str = ""
    city: str = ""
    city_code: str = ""
    experience: str = ""
    education: str = ""
    recruitment_type: str = "unknown"
    jd: str = ""
    hr_name: str = ""
    hr_title: str = ""
    hr_active: str = ""
    company_size: str = ""
    company_industry: str = ""
    url: str = ""
    source_keyword: str = ""

    @property
    def storage_id(self) -> str:
        if self.platform != "boss":
            return f"{self.platform}:{self.source_job_id}"
        return self.source_job_id

    def as_job_record(self) -> dict[str, Any]:
        return {
            "id": self.storage_id,
            "title": self.title,
            "company": self.company,
            "salary": self.salary,
            "city": self.city,
            "source_city_code": self.city_code,
            "experience": self.experience,
            "education": self.education,
            "recruitment_type": (
                self.recruitment_type
                if self.recruitment_type in {"campus", "experienced"}
                else classify_recruitment_type(self.title, self.experience, self.jd)
            ),
            "jd": clean_job_description(self.jd),
            "hr_name": self.hr_name,
            "hr_title": self.hr_title,
            "hr_active": self.hr_active,
            "company_size": self.company_size,
            "company_industry": self.company_industry,
            "url": self.url,
            "source_platform": self.platform,
            "source_job_id": self.source_job_id,
            "source_keyword": self.source_keyword,
        }


@dataclass
class CollectionProgress:
    run_id: str
    platform: PlatformId
    platform_index: int
    platform_total: int
    phase: str
    target: int | None
    seen: int = 0
    new: int = 0
    duplicate: int = 0
    filtered: int = 0
    parse_failed: int = 0
    save_failed: int = 0
    keyword: str = ""
    city: str = ""
    page: int = 0
    max_pages: int = 0
    reason_code: str = ""
    message: str = ""

    city_elapsed_ms: int = 0
    next_check_ms: int = 0
    last_window_new: int | None = None
    city_new_total: int = 0
    city_results: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def percent(self) -> int | None:
        if self.target is None or self.target <= 0:
            return None
        return min(100, int(self.new * 100 / self.target))


@dataclass
class PlatformCollectionResult:
    platform: PlatformId
    status: str
    reason_code: str = ""
    message: str = ""
    new_job_ids: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    error: str = ""
    city_results: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Per-platform collection filter pass-through (zhilian / 51job / liepin)
#
# BOSS applies its filters on the request side (search URL) and keeps its own
# vocabulary in ``platforms/boss.py``.  The three other platforms receive the
# filters in the request and apply them locally, per candidate, using the
# fields their list/detail pages expose.  A filter key is only reported as
# applied when the candidate actually carried the needed field; otherwise the
# reason is surfaced ("该平台未生效") and the candidate is kept — a missing
# field never silently drops a job and never pretends to have filtered it.
# ---------------------------------------------------------------------------

# Filter keys each platform declares it can reason about.  ``degree`` is an
# alias of ``education``.  Keys outside a platform's set are preserved at
# normalize time (never silently dropped) and reported to the run log.
PLATFORM_FILTER_KEYS: dict[str, frozenset[str]] = {
    "zhilian": frozenset({
        "education", "degree", "experience", "recruitment_type",
        "job_type", "salary", "scale", "industry",
    }),
    "51job": frozenset({
        "education", "degree", "experience", "recruitment_type",
        "job_type", "salary", "scale", "industry",
    }),
    "liepin": frozenset({
        "education", "degree", "experience", "recruitment_type",
        "job_type", "salary", "scale", "industry",
    }),
}

_FILTER_SEPARATOR = re.compile(r"[,，、\s]+")


def _filter_values(value: Any) -> list[str]:
    """Split a filter value (list or text) into cleaned, de-duplicated tokens."""
    if isinstance(value, list):
        raw = value
    else:
        raw = _FILTER_SEPARATOR.split(str(value or ""))
    result: list[str] = []
    for item in raw:
        cleaned = str(item or "").strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def normalize_collection_filters(
    filters: Any,
    platform: str,
    log: Callable[[str], None] | None = None,
) -> dict[str, list[str]]:
    """Per-platform filter pass-through for the non-BOSS platforms.

    Every key a platform declares is kept with its cleaned value list; keys
    outside that set are also kept (never silently dropped) and reported to
    ``log`` as unknown.  BOSS keeps its own request-side normalizer in
    ``platforms/boss.py``.
    """
    if not isinstance(filters, dict):
        return {}
    allowed = PLATFORM_FILTER_KEYS.get(platform)
    normalized: dict[str, list[str]] = {}
    for raw_key, value in filters.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        normalized[key] = _filter_values(value)
        if allowed is not None and key not in allowed:
            if log is not None:
                log(f"{platform} 未知过滤键：{key}（已保留但未应用）")
    return normalized


def _text_has(text: str, markers: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in markers)


def _education_match(candidate: JobCandidate, values: list[str]) -> tuple[bool | None, str | None]:
    if any("不限" in value for value in values):
        return True, None
    education = str(candidate.education or "").strip()
    if not education:
        return None, "候选缺少学历字段（列表未提供，留待详情页判定）"
    if "不限" in education:
        return True, None
    for value in values:
        if value in education or education in value:
            return True, None
    return False, None


def _experience_range(text: str) -> tuple[float, float] | None:
    """Parse 经验 texts (BOSS labels and platform list strings) to a year range."""
    text = str(text or "").strip()
    if "不限" in text:
        return None
    if "在校生" in text or "应届" in text:
        return (0.0, 0.0)
    if re.search(r"1\s*年以内|1\s*年以下|一年以内|一年以下", text):
        return (0.0, 1.0)
    match = re.search(r"(\d+(?:\.\d+)?)\s*[-~—至]\s*(\d+(?:\.\d+)?)\s*年", text)
    if match:
        return (float(match.group(1)), float(match.group(2)))
    match = re.search(r"(\d+(?:\.\d+)?)\s*年以上", text)
    if match:
        return (float(match.group(1)), float("inf"))
    match = re.search(r"(\d+(?:\.\d+)?)\s*年", text)
    if match:
        value = float(match.group(1))
        return (value, value)
    return None


def _ranges_overlap(left: tuple[float, float], right: tuple[float, float]) -> bool:
    # Bands are half-open ([1-3年) and [3-5年) do not overlap at the shared
    # boundary), but a zero-width value (应届生/在校生, or a single salary
    # point) matches its own point inclusively.
    if left[0] == left[1] or right[0] == right[1]:
        return left[0] <= right[1] and right[0] <= left[1]
    return left[0] < right[1] and right[0] < left[1]


def _experience_match(candidate: JobCandidate, values: list[str]) -> tuple[bool | None, str | None]:
    if any("不限" in value for value in values):
        return True, None
    experience = str(candidate.experience or "").strip()
    if not experience:
        return None, "候选缺少经验字段（列表未提供，留待详情页判定）"
    if "不限" in experience:
        return True, None
    candidate_range = _experience_range(experience)
    if candidate_range is None:
        return None, "经验文本无法解析为年限，未过滤"
    parseable: list[tuple[float, float]] = []
    for value in values:
        parsed = _experience_range(value)
        if parsed is not None:
            parseable.append(parsed)
    if not parseable:
        return None, "请求的经验档位无法解析为年限，未应用"
    for wanted in parseable:
        if _ranges_overlap(wanted, candidate_range):
            return True, None
    return False, None


def _recruitment_type_match(candidate: JobCandidate, values: list[str]) -> tuple[bool | None, str | None]:
    if any("不限" in value for value in values):
        return True, None
    wanted: set[str] = set()
    for value in values:
        if value in ("校招", "校园招聘", "应届", "campus"):
            wanted.add("campus")
        elif value in ("社招", "社会招聘", "experienced"):
            wanted.add("experienced")
    actual = classify_recruitment_type(candidate.title, candidate.experience, candidate.jd)
    if actual == "unknown":
        return None, "无法判定校招/社招，未过滤"
    return (actual in wanted), None


def _job_type_match(candidate: JobCandidate, values: list[str]) -> tuple[bool | None, str | None]:
    if any("不限" in value for value in values):
        return True, None
    text = " ".join((candidate.title, candidate.experience)).lower()
    if _text_has(text, ("实习", "intern", "internship", "管培")):
        actual = "实习"
    elif _text_has(text, ("兼职", "part-time", "parttime")):
        actual = "兼职"
    else:
        actual = "全职"
    return (actual in values), None


def _salary_match(candidate: JobCandidate, values: list[str]) -> tuple[bool | None, str | None]:
    if any(("不限" in value or "面议" in value) for value in values):
        return True, None
    salary = str(candidate.salary or "").strip()
    if not salary:
        return None, "候选缺少薪资字段"
    candidate_range = _parse_salary_range_k(salary)
    if candidate_range is None:
        return None, "薪资文本无法解析为范围，未过滤"
    parseable: list[tuple[float, float]] = []
    for value in values:
        parsed = _parse_salary_range_k(value)
        if parsed is not None:
            parseable.append(parsed)
    if not parseable:
        return None, "请求薪资档位无法解析（可能为 BOSS 档位编码），未映射"
    for wanted in parseable:
        if _ranges_overlap(wanted, candidate_range):
            return True, None
    return False, None


def _people_range(text: str) -> tuple[float, float] | None:
    """Parse company-size texts (BOSS labels and list strings) to a headcount range."""
    text = str(text or "").strip()
    if "不限" in text:
        return None
    match = re.search(r"(\d+)\s*[-~—至]\s*(\d+)\s*人", text)
    if match:
        return (float(match.group(1)), float(match.group(2)))
    match = re.search(r"(\d+)\s*人以上", text)
    if match:
        return (float(match.group(1)), float("inf"))
    match = re.search(r"(\d+)\s*人以下", text)
    if match:
        return (float("-inf"), float(match.group(1)))
    match = re.search(r"(\d+)\s*人", text)
    if match:
        value = float(match.group(1))
        return (value, value)
    return None


def _scale_match(candidate: JobCandidate, values: list[str]) -> tuple[bool | None, str | None]:
    if any("不限" in value for value in values):
        return True, None
    size = str(candidate.company_size or "").strip()
    if not size:
        return None, "候选缺少公司规模字段（平台未采集或当前阶段无数据）"
    candidate_range = _people_range(size)
    if candidate_range is None:
        return None, "公司规模文本无法解析，未过滤"
    parseable: list[tuple[float, float]] = []
    for value in values:
        parsed = _people_range(value)
        if parsed is not None:
            parseable.append(parsed)
    if not parseable:
        return None, "请求规模档位无法解析（可能为 BOSS 档位编码），未映射"
    for wanted in parseable:
        if _ranges_overlap(wanted, candidate_range):
            return True, None
    return False, None


def _industry_match(candidate: JobCandidate, values: list[str]) -> tuple[bool | None, str | None]:
    if any("不限" in value for value in values):
        return True, None
    industry = str(candidate.company_industry or "").strip()
    if not industry:
        return None, "候选缺少行业字段（平台未采集或当前阶段无数据）"
    label_values = [value for value in values if not value.isdigit()]
    if label_values:
        for value in label_values:
            if value in industry or industry in value:
                return True, None
        return False, None
    return None, "请求行业为 BOSS 数字编码，无法映射"


_FILTER_HANDLERS: dict[str, Callable[[JobCandidate, list[str]], tuple[bool | None, str | None]]] = {
    "education": _education_match,
    "degree": _education_match,
    "experience": _experience_match,
    "recruitment_type": _recruitment_type_match,
    "job_type": _job_type_match,
    "salary": _salary_match,
    "scale": _scale_match,
    "industry": _industry_match,
}


def apply_collection_filters(
    candidate: JobCandidate,
    filters: dict[str, Any],
    platform: str,
) -> tuple[bool, set[str], dict[str, str]]:
    """Apply candidate-level collection filters, key by key.

    Returns ``(keep, applied, not_applied)``:

    - ``keep`` is False when the candidate must be dropped;
    - ``applied`` is the set of filter keys that took effect for this
      candidate;
    - ``not_applied`` maps keys that could not be judged for this candidate
      to a reason (the platform lacks the field, or the requested value is
      not parseable).

    A candidate is kept when a key is not applied — a missing field never
    silently drops a job and never pretends to have filtered it.  ``platform``
    is accepted for contract symmetry; BOSS never goes through this path (it
    filters on the request side).
    """
    if not isinstance(filters, dict):
        return True, set(), {}
    keep = True
    applied: set[str] = set()
    not_applied: dict[str, str] = {}
    for key, raw_value in filters.items():
        handler = _FILTER_HANDLERS.get(str(key or ""))
        values = _filter_values(raw_value)
        if handler is None or not values:
            continue
        verdict, reason = handler(candidate, values)
        if verdict is None:
            not_applied[str(key)] = reason or "该平台未生效"
        elif verdict is True:
            applied.add(str(key))
        else:
            keep = False
    return keep, applied, not_applied
