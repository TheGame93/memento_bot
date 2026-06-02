from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from modules import constants as C
from modules.repetition_utils import candidate_allowed_by_repetition


def validate_tz_name(name: str | None) -> bool:
    """Return whether the provided timezone name resolves in the current tz database."""
    if not name or not isinstance(name, str):
        return False
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return False
    return True


def get_server_tz_name() -> str:
    """Return the configured server timezone name with a safe default."""
    return getattr(C, "SERVER_TZ", "Europe/Rome")


def get_server_tz() -> ZoneInfo:
    """Return the server timezone object, falling back to UTC when unavailable."""
    tz_name = get_server_tz_name()
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def resolve_user_timezone(user_prefs: dict | None) -> ZoneInfo:
    """Resolve the effective timezone for user-facing scheduling and parsing."""
    if not isinstance(user_prefs, dict):
        return get_server_tz()
    mode = user_prefs.get("timezone_mode") or C.TIMEZONE_DEFAULT_MODE
    if mode != C.TIMEZONE_MODE_USER:
        return get_server_tz()
    tz_name = None
    tz_block = user_prefs.get("timezone")
    if isinstance(tz_block, dict):
        tz_name = tz_block.get("name")
    if validate_tz_name(tz_name):
        return ZoneInfo(tz_name)
    return get_server_tz()


def now_server_naive() -> datetime:
    """Return the current server-local time as a naive datetime."""
    return datetime.now(get_server_tz()).replace(tzinfo=None)


def to_user_naive_from_server(server_dt: datetime, user_tz: ZoneInfo, server_tz: ZoneInfo | None = None) -> datetime:
    """Convert a server timestamp into user-local naive wall time."""
    server_tz = server_tz or get_server_tz()
    if server_dt.tzinfo is None:
        server_aware = server_dt.replace(tzinfo=server_tz)
    else:
        server_aware = server_dt.astimezone(server_tz)
    return server_aware.astimezone(user_tz).replace(tzinfo=None)


def to_server_naive_from_user(local_dt: datetime, user_tz: ZoneInfo, server_tz: ZoneInfo | None = None) -> tuple[datetime, bool]:
    """Convert user-local wall time to server-local naive time with DST-gap handling.

    Returns `(server_dt, shifted)` where `shifted` is `True` when the input
    local time had to be moved forward to a valid instant (for example across
    a DST spring-forward gap).
    """
    server_tz = server_tz or get_server_tz()
    local_aware, shifted = localize_with_shift(local_dt, user_tz)
    server_aware = local_aware.astimezone(server_tz)
    return server_aware.replace(tzinfo=None), shifted


def localize_with_shift(local_dt: datetime, tz: ZoneInfo) -> tuple[datetime, bool]:
    """
    Attach timezone to naive datetime. If local time is invalid (DST gap),
    shift forward to the next valid time.
    Returns (aware_dt, shifted).
    """
    if local_dt.tzinfo is not None:
        return local_dt.astimezone(tz), False

    candidate = local_dt.replace(tzinfo=tz)
    back = candidate.astimezone(timezone.utc).astimezone(tz)
    if back.replace(tzinfo=None) != local_dt:
        return back, True
    return candidate, False


def compute_next_occurrence(alert: dict, reference_server_dt: datetime | None, user_prefs: dict | None) -> tuple[datetime | None, bool]:
    """Compute the next alert occurrence in server-naive time for scheduler storage.

    Returns `(next_server_dt, shifted)` where `shifted` reports DST-gap
    adjustment applied during user-local to server conversion.
    """
    from modules.scheduler_mathlogic import get_next_occurrence

    server_tz = get_server_tz()
    if reference_server_dt is None:
        reference_server_dt = now_server_naive()
    elif reference_server_dt.tzinfo is not None:
        reference_server_dt = reference_server_dt.astimezone(server_tz).replace(tzinfo=None)

    if isinstance(alert, dict):
        schedule = alert.get("schedule") if isinstance(alert.get("schedule"), dict) else {}
        if alert.get("type") == 7 and schedule.get("interval_mode") == "fuzzy":
            raw_next = alert.get("next_scheduled")
            if not isinstance(raw_next, str) or not raw_next.strip():
                return None, False
            try:
                parsed_next = datetime.fromisoformat(raw_next)
            except Exception:
                return None, False
            if parsed_next.tzinfo is not None:
                parsed_next = parsed_next.astimezone(server_tz).replace(tzinfo=None)
            return parsed_next, False

    mode = None
    if isinstance(user_prefs, dict):
        mode = user_prefs.get("timezone_mode")
    if mode != C.TIMEZONE_MODE_USER:
        return get_next_occurrence(alert, reference_server_dt), False

    user_tz = resolve_user_timezone(user_prefs)
    user_ref = to_user_naive_from_server(reference_server_dt, user_tz, server_tz)
    next_local = get_next_occurrence(alert, user_ref)
    if not next_local:
        return None, False
    return to_server_naive_from_user(next_local, user_tz, server_tz)


def resolve_fuzzy_next_scheduled(
    alert: dict,
    reference_server_dt: datetime,
    user_prefs: dict | None,
    *,
    last_fired_at: datetime | None = None,
    record_history: bool = False,
    history_source: str | None = None,
) -> tuple[int | None, datetime | None, bool]:
    """Resolve the next fuzzy daily occurrence in server-naive time while preserving user-local repetition semantics."""
    from modules.scheduler_mathlogic import sample_fuzzy_interval

    server_tz = get_server_tz()
    if reference_server_dt is None:
        reference_server_dt = now_server_naive()
    elif reference_server_dt.tzinfo is not None:
        reference_server_dt = reference_server_dt.astimezone(server_tz).replace(tzinfo=None)

    if not isinstance(alert, dict):
        return None, None, False

    schedule = alert.get("schedule") if isinstance(alert.get("schedule"), dict) else {}
    hour, minute = _parse_time_fallback(schedule.get("time"))
    mean_raw = schedule.get("fuzzy_mean", schedule.get("interval", 1))
    std_raw = schedule.get("fuzzy_std", 0)
    sampled_days = sample_fuzzy_interval(mean_raw, std_raw)
    shifted = False

    mode = None
    if isinstance(user_prefs, dict):
        mode = user_prefs.get("timezone_mode")

    if mode == C.TIMEZONE_MODE_USER:
        user_tz = resolve_user_timezone(user_prefs)
        user_ref = to_user_naive_from_server(reference_server_dt, user_tz, server_tz)
        candidate_local = datetime.combine(
            (user_ref + timedelta(days=sampled_days)).date(),
            datetime.min.replace(hour=hour, minute=minute).time(),
        )
        if candidate_local <= user_ref:
            candidate_local += timedelta(days=1)

        if not candidate_allowed_by_repetition(alert.get("type"), alert.get("repetition"), candidate_local):
            return None, None, False

        candidate_server, shifted = to_server_naive_from_user(candidate_local, user_tz, server_tz)
    else:
        candidate_server = datetime.combine(
            (reference_server_dt + timedelta(days=sampled_days)).date(),
            datetime.min.replace(hour=hour, minute=minute).time(),
        )
        if candidate_server <= reference_server_dt:
            candidate_server += timedelta(days=1)
        if not candidate_allowed_by_repetition(alert.get("type"), alert.get("repetition"), candidate_server):
            return None, None, False

    valid_sources = {"due", "postpone", "missed"}
    if record_history and history_source in valid_sources:
        history = alert.get("fuzzy_history")
        if not isinstance(history, list):
            history = []
            alert["fuzzy_history"] = history

        mean_value = None
        try:
            mean_value = float(mean_raw)
        except Exception:
            mean_value = None
        std_value = None
        try:
            std_value = float(std_raw)
        except Exception:
            std_value = None

        actual_delta_days = None
        if isinstance(last_fired_at, datetime):
            if last_fired_at.tzinfo is not None:
                last_fired_at = last_fired_at.astimezone(server_tz).replace(tzinfo=None)
            delta_days = (reference_server_dt - last_fired_at).total_seconds() / 86400.0
            actual_delta_days = round(delta_days, 6)

        history.append({
            "recorded_at": reference_server_dt.isoformat(),
            "sampled_interval_days": sampled_days,
            "actual_delta_days": actual_delta_days,
            "mean": mean_value,
            "std": std_value,
            "source": history_source,
        })

    return sampled_days, candidate_server, shifted


def format_tz_offset(dt: datetime, tz: ZoneInfo) -> str:
    """Format the UTC offset for a datetime in the target timezone."""
    aware = dt.astimezone(tz) if dt.tzinfo else dt.replace(tzinfo=tz)
    offset = aware.utcoffset()
    if offset is None:
        return "UTC"
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


_ONE_TIME_FULL_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_ONE_TIME_SHORT_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2})$")
_ONE_TIME_PARTIAL_RE = re.compile(r"^(\d{1,2})/(\d{1,2})$")
_RELATIVE_EXPR_RE = re.compile(r"^(\d+)\s*(m|h|d|w|mo)$", re.IGNORECASE)
_NATURAL_EXPR_RE = re.compile(
    r"^(today|tomorrow|yesterday)(?:\s+(?:at\s+)?(\d{1,2})(?::(\d{1,2}))?)?$",
    re.IGNORECASE,
)
_ABSOLUTE_EXPR_RE = re.compile(
    r"^(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?(?:\s+(?:at\s+)?(\d{1,2})(?::(\d{1,2}))?)?$",
    re.IGNORECASE,
)
_DAY_ONLY_EXPR_RE = re.compile(
    r"^(\d{1,2})(?:\s+(?:at\s+)?(\d{1,2})(?::(\d{1,2}))?)?$",
    re.IGNORECASE,
)


def _parse_time_fallback(value: str | None) -> tuple[int, int]:
    raw = (value or "").strip()
    try:
        parsed = datetime.strptime(raw, "%H:%M").time()
        return parsed.hour, parsed.minute
    except Exception:
        return 10, 0


def _coerce_reference_dt(reference_server_dt: datetime | None) -> datetime:
    server_tz = get_server_tz()
    if reference_server_dt is None:
        return now_server_naive()
    if reference_server_dt.tzinfo is None:
        return reference_server_dt
    return reference_server_dt.astimezone(server_tz).replace(tzinfo=None)


def _user_reference_dt(reference_server_dt: datetime | None, user_prefs: dict | None) -> datetime:
    server_ref = _coerce_reference_dt(reference_server_dt)
    if not isinstance(user_prefs, dict):
        return server_ref
    mode = user_prefs.get("timezone_mode") or C.TIMEZONE_DEFAULT_MODE
    if mode != C.TIMEZONE_MODE_USER:
        return server_ref
    user_tz = resolve_user_timezone(user_prefs)
    return to_user_naive_from_server(server_ref, user_tz)


def _next_valid_year(day: int, month: int, start_year: int) -> int | None:
    for year in range(start_year, start_year + 12):
        try:
            datetime(year, month, day)
            return year
        except ValueError:
            continue
    return None


def _add_months(local_dt: datetime, months: int) -> datetime:
    month_idx = (local_dt.month - 1) + months
    year = local_dt.year + (month_idx // 12)
    month = (month_idx % 12) + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(local_dt.day, max_day)
    return local_dt.replace(year=year, month=month, day=day)


def _parse_optional_time_components(
    hour_text: str | None,
    minute_text: str | None,
    *,
    default_time: str | None,
) -> tuple[int | None, int | None, bool, bool, str | None]:
    if hour_text is None:
        hour, minute = _parse_time_fallback(default_time)
        return hour, minute, True, False, None
    try:
        hour = int(hour_text)
    except Exception:
        return None, None, False, False, "invalid_time"
    if hour < 0 or hour > 23:
        return None, None, False, False, "invalid_time"
    if minute_text is None:
        return hour, 0, False, True, None
    try:
        minute = int(minute_text)
    except Exception:
        return None, None, False, False, "invalid_time"
    if minute < 0 or minute > 59:
        return None, None, False, False, "invalid_time"
    return hour, minute, False, False, None


def _resolve_next_future_day_month(
    day: int,
    month: int,
    *,
    hour: int,
    minute: int,
    reference_local_dt: datetime,
) -> datetime | None:
    for year in range(reference_local_dt.year, reference_local_dt.year + 24):
        try:
            candidate = datetime(year, month, day, hour, minute, 0, 0)
        except ValueError:
            continue
        if candidate > reference_local_dt:
            return candidate
    return None


def _resolve_next_future_day_only(
    day: int,
    *,
    hour: int,
    minute: int,
    reference_local_dt: datetime,
) -> datetime | None:
    base_month_start = reference_local_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for month_offset in range(0, 24):
        cursor = _add_months(base_month_start, month_offset)
        max_day = calendar.monthrange(cursor.year, cursor.month)[1]
        if day > max_day:
            continue
        candidate = datetime(cursor.year, cursor.month, day, hour, minute, 0, 0)
        if candidate > reference_local_dt:
            return candidate
    return None


def _parse_relative_expression(
    text: str,
    *,
    reference_local_dt: datetime,
    allow_relative_tokens: bool,
) -> tuple[datetime | None, dict | None]:
    match = _RELATIVE_EXPR_RE.match(text)
    if not match:
        return None, None

    if not allow_relative_tokens:
        return None, {
            "input_kind": "relative_token",
            "reason_code": "relative_tokens_disabled",
        }

    value = int(match.group(1))
    unit = match.group(2).lower()
    if value <= 0:
        return None, {
            "input_kind": "relative_token",
            "reason_code": "relative_non_positive",
        }

    if unit == "m":
        return reference_local_dt + timedelta(minutes=value), {
            "input_kind": "relative_token",
            "token_unit": "m",
        }
    if unit == "h":
        return reference_local_dt + timedelta(hours=value), {
            "input_kind": "relative_token",
            "token_unit": "h",
        }
    if unit == "d":
        return reference_local_dt + timedelta(days=value), {
            "input_kind": "relative_token",
            "token_unit": "d",
        }
    if unit == "w":
        return reference_local_dt + timedelta(weeks=value), {
            "input_kind": "relative_token",
            "token_unit": "w",
        }
    if unit == "mo":
        return _add_months(reference_local_dt, value), {
            "input_kind": "relative_token",
            "token_unit": "mo",
        }

    return None, {
        "input_kind": "relative_token",
        "reason_code": "invalid_format",
    }


def _parse_natural_expression(
    text: str,
    *,
    reference_local_dt: datetime,
    default_time: str | None,
) -> tuple[datetime | None, dict | None]:
    match = _NATURAL_EXPR_RE.match(text)
    if not match:
        return None, None

    keyword = (match.group(1) or "").lower()
    hour, minute, used_default_time, minute_defaulted, time_error = _parse_optional_time_components(
        match.group(2),
        match.group(3),
        default_time=default_time,
    )
    if time_error is not None or hour is None or minute is None:
        return None, {
            "input_kind": "natural_keyword",
            "reason_code": "invalid_time",
            "natural_keyword": keyword,
        }

    day_offset = 0
    if keyword == "tomorrow":
        day_offset = 1
    elif keyword == "yesterday":
        day_offset = -1
    base_day = (reference_local_dt + timedelta(days=day_offset)).date()
    candidate = datetime(base_day.year, base_day.month, base_day.day, hour, minute, 0, 0)
    return candidate, {
        "input_kind": "natural_keyword",
        "natural_keyword": keyword,
        "used_default_time": used_default_time,
        "minute_defaulted": minute_defaulted,
    }


def _parse_absolute_expression(
    text: str,
    *,
    reference_local_dt: datetime,
    default_time: str | None,
    assume_year_policy: str,
    allow_day_only: bool,
) -> tuple[datetime | None, dict | None]:
    match = _ABSOLUTE_EXPR_RE.match(text)
    if match:
        try:
            day = int(match.group(1))
            month = int(match.group(2))
        except Exception:
            return None, {
                "input_kind": "absolute_date",
                "reason_code": "invalid_date",
            }

        hour, minute, used_default_time, minute_defaulted, time_error = _parse_optional_time_components(
            match.group(4),
            match.group(5),
            default_time=default_time,
        )
        if time_error is not None or hour is None or minute is None:
            return None, {
                "input_kind": "absolute_date",
                "reason_code": "invalid_time",
            }

        year_text = match.group(3)
        if year_text:
            try:
                year = int(year_text) if len(year_text) == 4 else (2000 + int(year_text))
                candidate = datetime(year, month, day, hour, minute, 0, 0)
            except Exception:
                return None, {
                    "input_kind": "absolute_date",
                    "reason_code": "invalid_date",
                }
            assumption_kind = "two_digit_year" if len(year_text) == 2 else None
            return candidate, {
                "input_kind": "absolute_date",
                "used_default_time": used_default_time,
                "minute_defaulted": minute_defaulted,
                "assumed_year": assumption_kind == "two_digit_year",
                "assumption_kind": assumption_kind,
            }

        if assume_year_policy != "next_future":
            return None, {
                "input_kind": "absolute_date",
                "reason_code": "unsupported_assume_year_policy",
            }
        candidate = _resolve_next_future_day_month(
            day,
            month,
            hour=hour,
            minute=minute,
            reference_local_dt=reference_local_dt,
        )
        if candidate is None:
            return None, {
                "input_kind": "absolute_date",
                "reason_code": "invalid_date",
            }
        return candidate, {
            "input_kind": "absolute_date",
            "used_default_time": used_default_time,
            "minute_defaulted": minute_defaulted,
            "assumed_year": True,
            "assumption_kind": "missing_year",
        }

    if not allow_day_only:
        return None, None

    day_only_match = _DAY_ONLY_EXPR_RE.match(text)
    if not day_only_match:
        return None, None
    try:
        day = int(day_only_match.group(1))
    except Exception:
        return None, {
            "input_kind": "day_only",
            "reason_code": "invalid_date",
        }

    hour, minute, used_default_time, minute_defaulted, time_error = _parse_optional_time_components(
        day_only_match.group(2),
        day_only_match.group(3),
        default_time=default_time,
    )
    if time_error is not None or hour is None or minute is None:
        return None, {
            "input_kind": "day_only",
            "reason_code": "invalid_time",
        }

    if assume_year_policy != "next_future":
        return None, {
            "input_kind": "day_only",
            "reason_code": "unsupported_assume_year_policy",
        }

    candidate = _resolve_next_future_day_only(
        day,
        hour=hour,
        minute=minute,
        reference_local_dt=reference_local_dt,
    )
    if candidate is None:
        return None, {
            "input_kind": "day_only",
            "reason_code": "invalid_date",
        }
    return candidate, {
        "input_kind": "day_only",
        "used_default_time": used_default_time,
        "minute_defaulted": minute_defaulted,
        "assumed_year": True,
        "assumption_kind": "day_only",
    }


def _build_datetime_expression_meta(
    *,
    raw_text: str | None,
    status: str,
    parse_payload: dict | None = None,
    reference_server_dt: datetime | None = None,
    candidate_local_dt: datetime | None = None,
    candidate_server_dt: datetime | None = None,
    timezone_mode: str | None = None,
    shifted: bool = False,
) -> dict:
    payload = dict(parse_payload or {})
    meta = {
        "status": status,
        "input_text": (raw_text or ""),
        "input_kind": payload.pop("input_kind", None),
        "reason_code": payload.pop("reason_code", None),
        "timezone_mode": timezone_mode or C.TIMEZONE_DEFAULT_MODE,
        "used_default_time": bool(payload.pop("used_default_time", False)),
        "minute_defaulted": bool(payload.pop("minute_defaulted", False)),
        "assumed_year": bool(payload.pop("assumed_year", False)),
        "assumption_kind": payload.pop("assumption_kind", None),
        "shifted": bool(shifted),
        "reference_server_iso": reference_server_dt.isoformat(sep=" ") if reference_server_dt else None,
        "candidate_local_iso": candidate_local_dt.isoformat(sep=" ") if candidate_local_dt else None,
        "candidate_server_iso": candidate_server_dt.isoformat(sep=" ") if candidate_server_dt else None,
    }
    if payload:
        meta["details"] = payload
    return meta


def _validate_expression_boundary(
    candidate_server_dt: datetime,
    *,
    now_server_dt: datetime,
    boundary_mode: str | None,
    boundary_server_dt: datetime | None = None,
) -> tuple[bool, str | None]:
    """Apply strict boundary checks for parsed datetime expressions and return reason codes."""
    mode = (boundary_mode or "").strip().lower()
    if not mode or mode in {"none", "off"}:
        return True, None

    if candidate_server_dt <= now_server_dt:
        return False, "candidate_not_future"

    if mode in {"future", "strict_future"}:
        return True, None

    if mode in {"before_boundary", "before_due", "future_before_boundary"}:
        if boundary_server_dt is None:
            return False, "boundary_missing"
        if candidate_server_dt >= boundary_server_dt:
            return False, "candidate_not_before_boundary"
        return True, None

    return False, "boundary_mode_unknown"


def parse_user_datetime_expression(
    raw_text: str | None,
    *,
    reference_server_dt: datetime | None = None,
    user_prefs: dict | None = None,
    default_time: str | None = None,
    assume_year_policy: str = "next_future",
    allow_relative_tokens: bool = True,
    allow_day_only: bool = False,
    boundary_mode: str | None = None,
    boundary_server_dt: datetime | None = None,
    now_server_dt: datetime | None = None,
) -> tuple[str, datetime | None, dict]:
    """Parse datetime expressions into a server-naive candidate and enforce optional boundary policies."""
    raw = (raw_text or "").strip()
    reference_server = _coerce_reference_dt(reference_server_dt)
    boundary_now = _coerce_reference_dt(now_server_dt) if now_server_dt is not None else reference_server
    boundary_dt = None
    if boundary_server_dt is not None:
        boundary_dt = _coerce_reference_dt(boundary_server_dt)

    if not raw:
        return "invalid", None, _build_datetime_expression_meta(
            raw_text=raw_text,
            status="invalid",
            parse_payload={"reason_code": "empty"},
            reference_server_dt=reference_server,
        )

    timezone_mode = C.TIMEZONE_DEFAULT_MODE
    parse_reference = reference_server
    user_tz = None
    if isinstance(user_prefs, dict):
        timezone_mode = user_prefs.get("timezone_mode") or C.TIMEZONE_DEFAULT_MODE
    if timezone_mode == C.TIMEZONE_MODE_USER:
        user_tz = resolve_user_timezone(user_prefs)
        parse_reference = to_user_naive_from_server(reference_server, user_tz)

    parser_chain = (
        lambda text: _parse_relative_expression(
            text,
            reference_local_dt=parse_reference,
            allow_relative_tokens=allow_relative_tokens,
        ),
        lambda text: _parse_natural_expression(
            text,
            reference_local_dt=parse_reference,
            default_time=default_time,
        ),
        lambda text: _parse_absolute_expression(
            text,
            reference_local_dt=parse_reference,
            default_time=default_time,
            assume_year_policy=assume_year_policy,
            allow_day_only=allow_day_only,
        ),
    )

    candidate_local = None
    parse_payload = None
    for parser in parser_chain:
        candidate_local, parse_payload = parser(raw)
        if parse_payload is not None:
            break

    if parse_payload is None:
        return "invalid", None, _build_datetime_expression_meta(
            raw_text=raw_text,
            status="invalid",
            parse_payload={"reason_code": "invalid_format"},
            reference_server_dt=reference_server,
            timezone_mode=timezone_mode,
        )

    if candidate_local is None:
        return "invalid", None, _build_datetime_expression_meta(
            raw_text=raw_text,
            status="invalid",
            parse_payload=parse_payload,
            reference_server_dt=reference_server,
            timezone_mode=timezone_mode,
        )

    shifted = False
    if user_tz is None:
        candidate_server = candidate_local
    else:
        candidate_server, shifted = to_server_naive_from_user(candidate_local, user_tz)

    boundary_ok, boundary_reason = _validate_expression_boundary(
        candidate_server,
        now_server_dt=boundary_now,
        boundary_mode=boundary_mode,
        boundary_server_dt=boundary_dt,
    )
    if not boundary_ok:
        return "invalid", None, _build_datetime_expression_meta(
            raw_text=raw_text,
            status="invalid",
            parse_payload={
                **(parse_payload or {}),
                "reason_code": boundary_reason or "boundary_rejected",
                "boundary_mode": boundary_mode,
                "boundary_server_iso": boundary_dt.isoformat(sep=" ") if boundary_dt else None,
                "boundary_now_iso": boundary_now.isoformat(sep=" "),
            },
            reference_server_dt=reference_server,
            candidate_local_dt=candidate_local,
            candidate_server_dt=candidate_server,
            timezone_mode=timezone_mode,
            shifted=shifted,
        )

    meta = _build_datetime_expression_meta(
        raw_text=raw_text,
        status="ok",
        parse_payload={
            **(parse_payload or {}),
            "boundary_mode": boundary_mode,
            "boundary_server_iso": boundary_dt.isoformat(sep=" ") if boundary_dt else None,
            "boundary_now_iso": boundary_now.isoformat(sep=" "),
        },
        reference_server_dt=reference_server,
        candidate_local_dt=candidate_local,
        candidate_server_dt=candidate_server,
        timezone_mode=timezone_mode,
        shifted=shifted,
    )
    return "ok", candidate_server, meta


def normalize_one_time_date(
    raw_date: str | None,
    *,
    reference_server_dt: datetime | None = None,
    user_prefs: dict | None = None,
    require_year_if_today: bool = False,
    time_str: str | None = None,
) -> tuple[str, str | None, bool, str | None]:
    """
    Normalize a one-time date string.
    Returns (status, normalized_date, assumed_year, reason).
    status: "ok" | "needs_year" | "invalid"
    """
    text = (raw_date or "").strip()
    if not text:
        return "invalid", None, False, "empty"

    full_match = _ONE_TIME_FULL_RE.match(text)
    if full_match:
        try:
            dt = datetime.strptime(text, "%d/%m/%Y")
        except ValueError:
            return "invalid", None, False, "invalid_date"
        return "ok", dt.strftime("%d/%m/%Y"), False, None

    short_match = _ONE_TIME_SHORT_RE.match(text)
    if short_match:
        try:
            day = int(short_match.group(1))
            month = int(short_match.group(2))
            year = 2000 + int(short_match.group(3))
            dt = datetime(year, month, day)
        except Exception:
            return "invalid", None, False, "invalid_date"
        return "ok", dt.strftime("%d/%m/%Y"), True, "two_digit_year"

    partial_match = _ONE_TIME_PARTIAL_RE.match(text)
    if not partial_match:
        return "invalid", None, False, "invalid_format"

    try:
        day = int(partial_match.group(1))
        month = int(partial_match.group(2))
        datetime(2000, month, day)
    except Exception:
        return "invalid", None, False, "invalid_date"

    user_ref = _user_reference_dt(reference_server_dt, user_prefs)
    today = user_ref.date()

    if require_year_if_today and (day, month) == (today.day, today.month):
        return "needs_year", None, False, "today_requires_year"

    base_year = today.year
    candidate_year = _next_valid_year(day, month, base_year)
    if candidate_year is None:
        return "invalid", None, False, "invalid_date"

    if (day, month) == (today.day, today.month):
        hour, minute = _parse_time_fallback(time_str)
        candidate_dt = datetime(candidate_year, month, day, hour, minute, 0, 0)
        if candidate_dt <= user_ref:
            candidate_year = _next_valid_year(day, month, base_year + 1)
    else:
        candidate_date = datetime(candidate_year, month, day).date()
        if candidate_date < today:
            candidate_year = _next_valid_year(day, month, base_year + 1)

    if candidate_year is None:
        return "invalid", None, False, "invalid_date"

    normalized = f"{day:02d}/{month:02d}/{candidate_year}"
    return "ok", normalized, True, "missing_year"
