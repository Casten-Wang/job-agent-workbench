"""Shared collection pacing and safety limits, calibrated to BOSS.

BOSS is the reference (user-confirmed):

- between-page delay ``2.0–5.0`` seconds × ``collection.collection_delay_multiplier``
  (1.5 by default, i.e. 3.0–7.5 s);
- 60 search pages and 900 detail pages per day;
- 3 consecutive page failures;
- a 5–10 minute risk cooldown after a captcha / rate-limit / block signal.

The other platforms may be slower, never faster: this module only *raises*
delays to BOSS's floor and never scales an existing delay down.  The send-side
``throttle`` section (interval_min / interval_max / daily_limit) is not read
here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

DEFAULT_MULTIPLIER = 1.5
MIN_MULTIPLIER = 1.0
MAX_MULTIPLIER = 5.0

# BOSS PageThrottle: (2.0 * multiplier, 5.0 * multiplier).
BASE_PAGE_DELAY_MIN = 2.0
BASE_PAGE_DELAY_MAX = 5.0
# BOSS waits around opening pages: 3 * multiplier and 2 * multiplier.
BASE_PAGE_OPEN_WAIT = 3.0
BASE_DETAIL_OPEN_WAIT = 2.0

DEFAULT_DAILY_SEARCH_PAGES = 60
DEFAULT_DAILY_DETAIL_PAGES = 900
DEFAULT_MAX_CONSECUTIVE_FAILURES = 3
DEFAULT_RISK_PAUSE_MIN_MINUTES = 5
DEFAULT_RISK_PAUSE_MAX_MINUTES = 10


def _bounded(value: Any, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
        return default
    return max(low, min(high, number))


def _positive_int(value: Any, default: int) -> int:
    try:
        return max(int(value), 1)
    except (TypeError, ValueError):
        return default


def delay_multiplier(config: dict[str, Any] | None) -> float:
    """Return the pace multiplier BOSS uses for this run (default 1.5)."""
    collection = config.get("collection") if isinstance(config, dict) else None
    if not isinstance(collection, dict):
        collection = {}
    return _bounded(
        collection.get("collection_delay_multiplier", DEFAULT_MULTIPLIER),
        DEFAULT_MULTIPLIER,
        MIN_MULTIPLIER,
        MAX_MULTIPLIER,
    )


def page_delay_range(config: dict[str, Any] | None) -> tuple[float, float]:
    """BOSS's between-page delay range, e.g. (3.0, 7.5) at the default pace."""
    multiplier = delay_multiplier(config)
    return (BASE_PAGE_DELAY_MIN * multiplier, BASE_PAGE_DELAY_MAX * multiplier)


def page_open_wait(config: dict[str, Any] | None) -> float:
    return BASE_PAGE_OPEN_WAIT * delay_multiplier(config)


def detail_open_wait(config: dict[str, Any] | None) -> float:
    return BASE_DETAIL_OPEN_WAIT * delay_multiplier(config)


def per_minute_limit(config: dict[str, Any] | None) -> int:
    """Requests per minute implied by BOSS's minimum page delay."""
    low, _high = page_delay_range(config)
    return max(1, int(60.0 // low))


def floor_range(
    base_range: Iterable[float],
    config: dict[str, Any] | None,
) -> tuple[float, float]:
    """Raise a platform range to BOSS's floor; never lower it.

    Each bound is compared with BOSS's bound for the same run and the larger
    one wins, so an existing (slower) platform range is left untouched.
    """
    values = list(base_range)
    low = float(values[0])
    high = float(values[1]) if len(values) > 1 else low
    boss_low, boss_high = page_delay_range(config)
    raised_low = max(low, boss_low)
    raised_high = max(high, boss_high)
    if raised_high < raised_low:
        raised_high = raised_low
    return (raised_low, raised_high)


def floor_seconds(seconds: float, config: dict[str, Any] | None) -> float:
    """Never wait less than BOSS's minimum between-page delay."""
    return max(float(seconds), page_delay_range(config)[0])


@dataclass(frozen=True)
class CollectionLimits:
    daily_search_pages: int = DEFAULT_DAILY_SEARCH_PAGES
    daily_detail_pages: int = DEFAULT_DAILY_DETAIL_PAGES
    max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES
    risk_pause_min_minutes: int = DEFAULT_RISK_PAUSE_MIN_MINUTES
    risk_pause_max_minutes: int = DEFAULT_RISK_PAUSE_MAX_MINUTES

    def pause_minutes(self, randint: Callable[[int, int], int]) -> int:
        return int(randint(self.risk_pause_min_minutes, self.risk_pause_max_minutes))


def collection_guard(
    safety_conn: Any | None,
    config: dict[str, Any] | None,
    platform: str,
) -> Any | None:
    """Build BOSS's persistent page-budget guard, or None without a DB."""
    if safety_conn is None:
        return None
    from offerpilot.platform_safety import PlatformAccessGuard

    return PlatformAccessGuard(safety_conn, config or {}, "collection", platform)


def collection_limits(config: dict[str, Any] | None) -> CollectionLimits:
    """Read BOSS's daily page budgets, failure cap and risk cooldown."""
    collection = config.get("collection") if isinstance(config, dict) else None
    if not isinstance(collection, dict):
        collection = {}
    pause_min = _positive_int(
        collection.get("risk_pause_min_minutes", DEFAULT_RISK_PAUSE_MIN_MINUTES),
        DEFAULT_RISK_PAUSE_MIN_MINUTES,
    )
    pause_max = max(
        pause_min,
        _positive_int(
            collection.get("risk_pause_max_minutes", DEFAULT_RISK_PAUSE_MAX_MINUTES),
            DEFAULT_RISK_PAUSE_MAX_MINUTES,
        ),
    )
    return CollectionLimits(
        daily_search_pages=_positive_int(
            collection.get("daily_search_page_limit", DEFAULT_DAILY_SEARCH_PAGES),
            DEFAULT_DAILY_SEARCH_PAGES,
        ),
        daily_detail_pages=_positive_int(
            collection.get("daily_detail_page_limit", DEFAULT_DAILY_DETAIL_PAGES),
            DEFAULT_DAILY_DETAIL_PAGES,
        ),
        max_consecutive_failures=_positive_int(
            collection.get("max_consecutive_page_failures", DEFAULT_MAX_CONSECUTIVE_FAILURES),
            DEFAULT_MAX_CONSECUTIVE_FAILURES,
        ),
        risk_pause_min_minutes=pause_min,
        risk_pause_max_minutes=pause_max,
    )
