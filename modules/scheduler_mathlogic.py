"""
scheduler_mathlogic.py - THE CALCULATOR

Pure Python date math functions for alert scheduling.
No Telegram API, no file I/O, no side effects.
All functions are stateless and easily unit-testable.
"""

import logging
import calendar
import re
import math
import random
from datetime import datetime, time, timedelta
from dateutil.relativedelta import relativedelta, MO, TU, WE, TH, FR, SA, SU
from modules import constants as C
from modules.repetition_utils import (
    candidate_allowed_by_repetition,
    normalize_repetition_payload,
)

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

WEEKDAY_MAP = {
    "Mon": MO, "Tue": TU, "Wed": WE, 
    "Thu": TH, "Fri": FR, "Sat": SA, "Sun": SU
}
WEEKDAY_INDEX = {
    "Mon": 0, "Tue": 1, "Wed": 2,
    "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6,
}

ORDINAL_MAP = {
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "Last": -1
}

# Pre-alert time units (matches format from add_alert.py)
PRE_ALERT_UNITS = {
    'm': 'minutes',
    'h': 'hours',
    'd': 'days',
    'w': 'weeks',
    'mo': 'months',
}

# Tolerance window for "is_due" checks (in seconds)
# An alert is considered "due" if it's within this window of its scheduled time
DUE_TOLERANCE_SECONDS = 90  # 1.5 minutes to account for scheduler tick timing


def get_constants_compatibility_issues():
    """
    Returns a list of compatibility issues between constants.py and this module.
    Empty list means mappings are aligned.
    """
    issues = []
    if set(C.WEEKDAYS) != set(WEEKDAY_MAP.keys()):
        issues.append({
            "kind": "weekday_mismatch",
            "constants": sorted(set(C.WEEKDAYS)),
            "mathlogic": sorted(set(WEEKDAY_MAP.keys())),
        })
    if set(C.ORDINALS) != set(ORDINAL_MAP.keys()):
        issues.append({
            "kind": "ordinal_mismatch",
            "constants": sorted(set(C.ORDINALS)),
            "mathlogic": sorted(set(ORDINAL_MAP.keys())),
        })
    if set(C.PRE_ALERT_UNITS.keys()) != set(PRE_ALERT_UNITS.keys()):
        issues.append({
            "kind": "pre_alert_unit_mismatch",
            "constants": sorted(set(C.PRE_ALERT_UNITS.keys())),
            "mathlogic": sorted(set(PRE_ALERT_UNITS.keys())),
        })
    return issues


def _safe_interval(raw_interval):
    try:
        value = int(raw_interval)
    except Exception:
        return 1
    return value if value >= 1 else 1


def _parse_start_marker(raw_value):
    if not raw_value or not isinstance(raw_value, str):
        return None
    try:
        return datetime.strptime(raw_value.strip(), "%d/%m/%Y")
    except Exception:
        return None


def _resolve_interval_anchor(alert, alert_time, reference_date):
    """
    Stable anchor for interval-based recurring alerts.
    Priority: schedule.start_marker -> created_at -> reference_date.
    """
    schedule = alert.get("schedule", {}) or {}
    marker = _parse_start_marker(schedule.get("start_marker"))
    if marker:
        return marker.replace(
            hour=alert_time.hour,
            minute=alert_time.minute,
            second=0,
            microsecond=0,
        )

    created_raw = alert.get("created_at")
    if isinstance(created_raw, str):
        try:
            created_dt = datetime.fromisoformat(created_raw)
            if created_dt.tzinfo is not None:
                created_dt = created_dt.astimezone().replace(tzinfo=None)
            return created_dt.replace(second=0, microsecond=0)
        except Exception:
            pass

    return reference_date.replace(second=0, microsecond=0)


def _month_diff(start_dt, end_dt):
    return (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)


def _is_allowed_month(month_dt, anchor_dt, interval):
    if interval <= 1:
        return True
    diff = _month_diff(anchor_dt, month_dt)
    return diff >= 0 and (diff % interval == 0)


def _months_horizon(interval):
    # 60 interval cycles with a hard cap to avoid pathological loops.
    return min(2400, max(240, interval * 60))


def _weeks_horizon(interval):
    # 60 interval cycles with a hard cap to avoid pathological loops.
    return min(5200, max(520, interval * 60))


def _years_horizon(interval):
    # 60 interval cycles with a hard cap to avoid pathological loops.
    return min(600, max(120, interval * 60))


def _parse_yearly_dates(raw_dates):
    if isinstance(raw_dates, (list, tuple, set)):
        tokens = [str(x).strip() for x in raw_dates]
    elif isinstance(raw_dates, str):
        tokens = [part.strip() for part in raw_dates.split(",")]
    else:
        return []

    parsed = []
    for token in tokens:
        if not token:
            continue
        try:
            day_str, month_str = token.split("/")
            day = int(day_str)
            month = int(month_str)
        except Exception:
            continue

        if month < 1 or month > 12 or day < 1:
            continue

        if month == 2:
            max_day = 29
        else:
            max_day = calendar.monthrange(2025, month)[1]
        if day > max_day:
            continue

        parsed.append((day, month))

    return sorted(set(parsed), key=lambda item: (item[1], item[0]))


def _is_repetition_count_exhausted(alert):
    if not isinstance(alert, dict):
        return False
    alert_type = alert.get("type")
    if alert_type not in C.REPETITION_SUPPORTED_TYPES:
        return False
    normalized = normalize_repetition_payload(alert_type, alert.get("repetition"))
    if not isinstance(normalized, dict):
        return False
    if normalized.get("mode") != C.REPETITION_MODE_COUNT:
        return False
    try:
        count_remaining = int(normalized.get("count_remaining") or 0)
    except Exception:
        count_remaining = 0
    return count_remaining <= 0


def _repetition_allows_candidate(alert, candidate_dt):
    if not isinstance(alert, dict):
        return True
    return candidate_allowed_by_repetition(
        alert.get("type"),
        alert.get("repetition"),
        candidate_dt,
    )


def sample_fuzzy_interval(mean: float, std: float) -> int:
    """Return a positive integer day interval sampled from the fuzzy daily distribution."""
    min_days = int(getattr(C, "FUZZY_INTERVAL_MIN_DAYS", 1) or 1)
    if min_days < 1:
        min_days = 1

    try:
        mean_val = float(mean)
    except Exception:
        mean_val = float(min_days)
    if not math.isfinite(mean_val):
        mean_val = float(min_days)

    try:
        std_val = float(std)
    except Exception:
        std_val = 0.0
    if not math.isfinite(std_val) or std_val < 0:
        std_val = 0.0

    for _ in range(1000):
        sampled = mean_val if std_val == 0 else random.gauss(mean_val, std_val)
        try:
            sampled_days = int(round(float(sampled)))
        except Exception:
            sampled_days = 0
        if sampled_days >= min_days:
            return sampled_days

    return max(min_days, int(round(mean_val)))

# =============================================================================
# CORE CALCULATION: NEXT OCCURRENCE
# =============================================================================

def get_next_occurrence(alert, reference_date=None):
    """
    Return the next datetime when an alert should fire.
    
    Args:
        alert: Alert dict with 'type', 'schedule', etc.
        reference_date: datetime to calculate from (default: now)
    
    Returns:
        datetime of next occurrence, or None if not calculable
    """
    if reference_date is None:
        reference_date = datetime.now()

    sch = alert.get('schedule', {})
    default_time_str = sch.get('time', '10:00')
    
    try:
        alert_time = datetime.strptime(default_time_str, "%H:%M").time()
    except ValueError:
        alert_time = time(10, 0)

    a_type = alert.get('type')
    if a_type == 7 and sch.get("interval_mode") == "fuzzy":
        raw_next = alert.get("next_scheduled")
        if not isinstance(raw_next, str) or not raw_next.strip():
            return None
        try:
            parsed_next = datetime.fromisoformat(raw_next)
        except Exception:
            return None
        if parsed_next.tzinfo is not None:
            parsed_next = parsed_next.astimezone().replace(tzinfo=None)
        return parsed_next

    interval = _safe_interval(sch.get('interval', 1))
    if _is_repetition_count_exhausted(alert):
        return None

    try:
        # --- TYPE 1: Monthly (Fixed Day) ---
        if a_type == 1:
            days = []
            for raw_day in sch.get('days', []):
                try:
                    day = int(raw_day)
                except Exception:
                    continue
                if 1 <= day <= 31:
                    days.append(day)
            days = sorted(set(days))
            if not days:
                return None

            anchor = _resolve_interval_anchor(alert, alert_time, reference_date)
            search_start = max(reference_date, anchor) if interval > 1 else reference_date
            month_cursor = search_start.replace(
                day=1,
                hour=alert_time.hour,
                minute=alert_time.minute,
                second=0,
                microsecond=0
            )

            possible_dates = []
            for i in range(_months_horizon(interval)):
                base_month = month_cursor + relativedelta(months=i)
                if interval > 1 and not _is_allowed_month(base_month, anchor, interval):
                    continue

                for day in days:
                    last_day = calendar.monthrange(base_month.year, base_month.month)[1]
                    target_day = min(day, last_day)  # Auto-adjust 29/30/31 on short months.
                    candidate = base_month.replace(
                        day=target_day,
                        hour=alert_time.hour,
                        minute=alert_time.minute,
                        second=0,
                        microsecond=0
                    )
                    if interval > 1 and candidate < anchor:
                        continue
                    if candidate > reference_date and _repetition_allows_candidate(alert, candidate):
                        possible_dates.append(candidate)
            return min(possible_dates) if possible_dates else None

        # --- TYPE 2: Monthly (Relative) ---
        elif a_type == 2:
            ordinals = [ORDINAL_MAP.get(o) for o in sch.get('ordinals', []) if o in ORDINAL_MAP]
            weekdays = [wd for wd in sch.get('weekdays', []) if wd in WEEKDAY_MAP]
            if not ordinals or not weekdays:
                return None

            fifth_policy = sch.get("fifth_policy", "skip")
            anchor = _resolve_interval_anchor(alert, alert_time, reference_date)
            search_start = max(reference_date, anchor) if interval > 1 else reference_date
            month_cursor = search_start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            possible_dates = []

            for i in range(_months_horizon(interval)):
                base_month = month_cursor + relativedelta(months=i, day=1)
                if interval > 1 and not _is_allowed_month(base_month, anchor, interval):
                    continue

                for ord_val in ordinals:
                    for wd in weekdays:
                        if ord_val < 0:
                            candidate = base_month + relativedelta(
                                day=31,
                                weekday=WEEKDAY_MAP[wd](ord_val),
                            )
                        else:
                            candidate = base_month + relativedelta(
                                weekday=WEEKDAY_MAP[wd](ord_val)
                            )
                        candidate = candidate.replace(
                            hour=alert_time.hour,
                            minute=alert_time.minute,
                            second=0,
                            microsecond=0
                        )
                        # "5th weekday" may spill into next month.
                        if candidate.year != base_month.year or candidate.month != base_month.month:
                            # Apply fifth_policy fallback: use 4th occurrence instead.
                            if ord_val == 5 and fifth_policy == "fallback_4th":
                                fallback = base_month + relativedelta(weekday=WEEKDAY_MAP[wd](4))
                                fallback = fallback.replace(
                                    hour=alert_time.hour,
                                    minute=alert_time.minute,
                                    second=0,
                                    microsecond=0,
                                )
                                if fallback.year == base_month.year and fallback.month == base_month.month:
                                    if interval > 1 and fallback < anchor:
                                        continue
                                    if fallback > reference_date and _repetition_allows_candidate(alert, fallback):
                                        possible_dates.append(fallback)
                            continue
                        if interval > 1 and candidate < anchor:
                            continue
                        if candidate > reference_date and _repetition_allows_candidate(alert, candidate):
                            possible_dates.append(candidate)
            return min(possible_dates) if possible_dates else None

        # --- TYPE 3: Weekly ---
        elif a_type == 3:
            weekdays = sorted({WEEKDAY_INDEX[wd] for wd in sch.get('weekdays', []) if wd in WEEKDAY_INDEX})
            if not weekdays:
                return None

            anchor = _resolve_interval_anchor(alert, alert_time, reference_date)
            search_start = max(reference_date, anchor) if interval > 1 else reference_date
            week_start = (search_start - timedelta(days=search_start.weekday())).date()
            anchor_week_start = (anchor - timedelta(days=anchor.weekday())).date()
            possible_dates = []

            for week_offset in range(_weeks_horizon(interval)):
                current_week_start = week_start + timedelta(weeks=week_offset)
                if interval > 1:
                    diff_weeks = (current_week_start - anchor_week_start).days // 7
                    if diff_weeks < 0 or diff_weeks % interval != 0:
                        continue

                for weekday_idx in weekdays:
                    candidate_date = current_week_start + timedelta(days=weekday_idx)
                    candidate = datetime.combine(candidate_date, alert_time)
                    if interval > 1 and candidate < anchor:
                        continue
                    if candidate > reference_date and _repetition_allows_candidate(alert, candidate):
                        possible_dates.append(candidate)
            return min(possible_dates) if possible_dates else None

        # --- TYPE 7: Daily ---
        elif a_type == 7:
            if interval <= 1:
                candidate = reference_date.replace(
                    hour=alert_time.hour,
                    minute=alert_time.minute,
                    second=0,
                    microsecond=0,
                )
                if candidate <= reference_date:
                    candidate += timedelta(days=1)
                if _repetition_allows_candidate(alert, candidate):
                    return candidate
                return None

            anchor = _resolve_interval_anchor(alert, alert_time, reference_date)
            anchor_candidate = datetime.combine(anchor.date(), alert_time)
            if anchor_candidate > reference_date:
                if _repetition_allows_candidate(alert, anchor_candidate):
                    return anchor_candidate
                return None

            step_seconds = interval * 24 * 60 * 60
            elapsed_seconds = (reference_date - anchor_candidate).total_seconds()
            steps = int(elapsed_seconds // step_seconds) + 1
            candidate = anchor_candidate + timedelta(days=steps * interval)
            if _repetition_allows_candidate(alert, candidate):
                return candidate
            return None

        # --- TYPE 4: Yearly ---
        elif a_type == 4:
            date_pairs = _parse_yearly_dates(sch.get('dates'))
            if not date_pairs:
                logger.error(f"Invalid yearly date format: {sch.get('dates')}")
                return None

            anchor = _resolve_interval_anchor(alert, alert_time, reference_date)
            search_start = max(reference_date, anchor) if interval > 1 else reference_date
            possible_dates = []

            for year_offset in range(_years_horizon(interval)):
                year = search_start.year + year_offset
                if interval > 1:
                    year_diff = year - anchor.year
                    if year_diff < 0 or year_diff % interval != 0:
                        continue

                for day, month in date_pairs:
                    cand_day = day
                    if day == 29 and month == 2 and not calendar.isleap(year):
                        cand_day = 28
                    try:
                        candidate = datetime(
                            year,
                            month,
                            cand_day,
                            alert_time.hour,
                            alert_time.minute,
                            0,
                            0,
                        )
                    except ValueError:
                        continue

                    if interval > 1 and candidate < anchor:
                        continue
                    if candidate > reference_date and _repetition_allows_candidate(alert, candidate):
                        possible_dates.append(candidate)

            return min(possible_dates) if possible_dates else None

        # --- TYPE 5: One-time ---
        elif a_type == 5:
            try:
                date_str = sch.get('date', '')
                # Format: "D/M/Y" e.g., "23/4/2027"
                date_part = datetime.strptime(date_str, "%d/%m/%Y")
                candidate = date_part.replace(
                    hour=alert_time.hour, 
                    minute=alert_time.minute, 
                    second=0, 
                    microsecond=0
                )
                return candidate if candidate > reference_date else None
            except (ValueError, TypeError):
                logger.error(f"Invalid one-time date format: {sch.get('date')}")
                return None

        # --- TYPE 6: Birthday (Yearly, fixed time) ---
        elif a_type == 6:
            try:
                date_str = sch.get('date', '')
                # Format: "D/M" e.g., "23/4"
                d, m = map(int, date_str.split('/'))
            except (ValueError, AttributeError):
                logger.error(f"Invalid birthday date format: {sch.get('date')}")
                return None

            policy = (C.BIRTHDAY_FEB29_POLICY or "mar1").lower()

            def candidate_for_year(year):
                if d == 29 and m == 2 and not calendar.isleap(year):
                    if policy == "mar1":
                        cand_day, cand_month = 1, 3
                    else:
                        cand_day, cand_month = 28, 2
                else:
                    cand_day, cand_month = d, m

                return datetime(
                    year, cand_month, cand_day,
                    alert_time.hour, alert_time.minute, 0, 0
                )

            try:
                candidate = candidate_for_year(reference_date.year)
            except ValueError:
                logger.error(f"Invalid birthday date: {sch.get('date')}")
                return None

            if candidate <= reference_date:
                candidate = candidate_for_year(reference_date.year + 1)
            return candidate

    except Exception as e:
        logger.error(f"Calculation error for alert {alert.get('id', 'unknown')}: {e}")
        return None
    
    return None


# =============================================================================
# PRE-ALERT CALCULATIONS
# =============================================================================

def parse_pre_alert_string(pre_alert_str):
    """
    Parses a pre-alert string like "2d", "1w", "30m", "4h", "1mo" into a timedelta/relativedelta.
    
    Args:
        pre_alert_str: String like "2d", "1w", "30m", "4h", "1mo"
    
    Returns:
        timedelta object, or None if invalid format
    """
    if not pre_alert_str:
        return None
    
    pre_alert_str = pre_alert_str.strip().lower().replace(" ", "")
    match = re.match(r'^(\d+)(mo|[mhdw])$', pre_alert_str)
    
    if not match:
        logger.warning(f"Invalid pre-alert format: {pre_alert_str}")
        return None
    
    value = int(match.group(1))
    unit = match.group(2)
    
    unit_map = {
        'm': timedelta(minutes=value),
        'h': timedelta(hours=value),
        'd': timedelta(days=value),
        'w': timedelta(weeks=value),
        'mo': relativedelta(months=value),
    }
    
    return unit_map.get(unit)


def _normalize_hhmm(value, fallback):
    raw = (value or "").strip()
    try:
        parsed = datetime.strptime(raw, "%H:%M").time()
        return parsed.hour, parsed.minute
    except Exception:
        parsed = datetime.strptime(fallback, "%H:%M").time()
        return parsed.hour, parsed.minute


def resolve_pre_alert_fire_time(alert, pre_alert_str, main_trigger_time, user_prefs=None):
    """
    Resolves a pre-alert token to an absolute fire datetime.

    Returns:
        tuple(datetime | None, str | None): (fire_time, kind)
        kind values: "duration", "birthday_evening_before"
    """
    if not pre_alert_str or not main_trigger_time:
        return None, None

    token = str(pre_alert_str).strip().lower()
    if token == C.BIRTHDAY_PREALERT_EVENING_BEFORE_TOKEN:
        # Birthday-only token: previous-day fixed evening time.
        if not isinstance(alert, dict) or alert.get("type") != 6:
            return None, None

        hour, minute = _normalize_hhmm(
            (user_prefs or {}).get("birthday_evening_before_time")
            if isinstance(user_prefs, dict)
            else None,
            C.BIRTHDAY_EVENING_BEFORE_DEFAULT_TIME,
        )

        main_dt = main_trigger_time
        if isinstance(main_dt, datetime) and main_dt.tzinfo is not None:
            from modules.timezone_utils import get_server_tz
            main_dt = main_dt.astimezone(get_server_tz()).replace(tzinfo=None)

        if isinstance(user_prefs, dict) and user_prefs.get("timezone_mode") == C.TIMEZONE_MODE_USER:
            from modules.timezone_utils import (
                get_server_tz,
                resolve_user_timezone,
                to_server_naive_from_user,
                to_user_naive_from_server,
            )
            server_tz = get_server_tz()
            user_tz = resolve_user_timezone(user_prefs)
            main_local = to_user_naive_from_server(main_dt, user_tz, server_tz)
            pre_local = datetime(
                main_local.year,
                main_local.month,
                main_local.day,
                hour,
                minute,
                0,
                0,
            ) - timedelta(days=1)
            pre_server, _ = to_server_naive_from_user(pre_local, user_tz, server_tz)
            return pre_server, "birthday_evening_before"

        pre_server = (main_dt - timedelta(days=1)).replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        return pre_server, "birthday_evening_before"

    delta = parse_pre_alert_string(pre_alert_str)
    if not delta:
        return None, None
    try:
        return main_trigger_time - delta, "duration"
    except Exception:
        return None, None


def calculate_pre_alert_times(alert, main_trigger_time, user_prefs=None, reference_now=None):
    """
    Calculates pre-alert notification times based on the main trigger time.
    
    Args:
        alert: Alert dict containing 'pre_alerts' list
        main_trigger_time: datetime of the main alert trigger
    
    Returns:
        List of (datetime, pre_alert_str) tuples, sorted by time (earliest first)
    """
    pre_alerts = alert.get('pre_alerts', [])
    if not pre_alerts or not main_trigger_time:
        return []
    
    now_ref = reference_now or datetime.now()
    result = []
    for pa_str in pre_alerts:
        pre_time, _kind = resolve_pre_alert_fire_time(
            alert,
            pa_str,
            main_trigger_time,
            user_prefs=user_prefs,
        )
        if not pre_time:
            continue
        # Only include if the pre-alert time is in the future
        if pre_time > now_ref:
            result.append((pre_time, pa_str))
    
    # Sort by time (earliest first)
    result.sort(key=lambda x: x[0])
    return result


# =============================================================================
# DUE / OVERDUE CHECKS
# =============================================================================

def is_due(alert, current_time=None, tolerance_seconds=None):
    """
    Checks if an alert should fire now (within tolerance window).
    Also considers snooze state.
    
    Args:
        alert: Alert dict
        current_time: datetime to check against (default: now)
        tolerance_seconds: How many seconds of "fuzziness" to allow
    
    Returns:
        bool - True if alert is due now
    """
    if current_time is None:
        current_time = datetime.now()
    if tolerance_seconds is None:
        tolerance_seconds = DUE_TOLERANCE_SECONDS
    # Ensure tolerance isn't shorter than the scheduler tick interval
    if getattr(C, "SCHEDULER_INTERVAL_SECONDS", None) is not None:
        tolerance_seconds = max(tolerance_seconds, C.SCHEDULER_INTERVAL_SECONDS + 5)
    
    # Check if alert is active
    if not alert.get('active', True):
        return False
    
    # Check if snoozed
    snoozed_until_str = alert.get('snoozed_until')
    if snoozed_until_str:
        try:
            snoozed_until = datetime.fromisoformat(snoozed_until_str)
            if current_time < snoozed_until:
                return False  # Still snoozed
        except ValueError:
            pass  # Invalid snooze time, ignore
    
    # Get scheduled time
    next_scheduled_str = alert.get('next_scheduled')
    if next_scheduled_str:
        try:
            next_scheduled = datetime.fromisoformat(next_scheduled_str)
        except ValueError:
            next_scheduled = get_next_occurrence(alert, current_time - timedelta(days=1))
    else:
        next_scheduled = get_next_occurrence(alert, current_time - timedelta(days=1))
    
    if not next_scheduled:
        return False
    
    # Check if within tolerance window (late-only)
    time_diff = (current_time - next_scheduled).total_seconds()
    return 0 <= time_diff <= tolerance_seconds


def is_overdue(alert, current_time=None):
    """
    Checks if an alert was missed (scheduled time has passed but wasn't triggered).
    
    Args:
        alert: Alert dict
        current_time: datetime to check against (default: now)
    
    Returns:
        (bool, datetime or None) - (is_overdue, missed_scheduled_time)
    """
    if current_time is None:
        current_time = datetime.now()
    
    # Check if alert is active
    if not alert.get('active', True):
        return False, None
    
    next_scheduled_str = alert.get('next_scheduled')
    last_triggered_str = alert.get('last_triggered')
    
    if not next_scheduled_str:
        return False, None
    
    try:
        next_scheduled = datetime.fromisoformat(next_scheduled_str)
    except ValueError:
        return False, None
    
    # If next_scheduled is in the past
    if next_scheduled < current_time:
        # Check if we already triggered for this time
        if last_triggered_str:
            try:
                last_triggered = datetime.fromisoformat(last_triggered_str)
                # If last trigger was after or at the scheduled time, not overdue
                if last_triggered >= next_scheduled - timedelta(minutes=2):
                    return False, None
            except ValueError:
                pass
        
        return True, next_scheduled
    
    return False, None


def is_pre_alert_due(alert, pre_alert_str, current_time=None, tolerance_seconds=None, user_prefs=None):
    """
    Checks if a specific pre-alert should fire now.
    
    Args:
        alert: Alert dict
        pre_alert_str: The pre-alert string (e.g., "2d")
        current_time: datetime to check against
        tolerance_seconds: Tolerance window
    
    Returns:
        bool - True if this pre-alert is due
    """
    if current_time is None:
        current_time = datetime.now()
    if tolerance_seconds is None:
        tolerance_seconds = DUE_TOLERANCE_SECONDS
    
    # Get main trigger time
    next_scheduled_str = alert.get('next_scheduled')
    if next_scheduled_str:
        try:
            main_time = datetime.fromisoformat(next_scheduled_str)
        except ValueError:
            return False
    else:
        main_time = get_next_occurrence(alert)
    
    if not main_time:
        return False
    
    # Calculate pre-alert time
    pre_alert_time, _kind = resolve_pre_alert_fire_time(
        alert,
        pre_alert_str,
        main_time,
        user_prefs=user_prefs,
    )
    if not pre_alert_time:
        return False

    # Check if within tolerance window
    time_diff = abs((current_time - pre_alert_time).total_seconds())
    return time_diff <= tolerance_seconds


# =============================================================================
# SNOOZE CALCULATIONS
# =============================================================================

def get_snooze_limit(alert):
    """
    For recurring alerts, returns the maximum datetime an alert can be snoozed to.
    This is the next trigger date after the current one.
    
    For one-time alerts, returns None (no limit).
    
    Args:
        alert: Alert dict
    
    Returns:
        datetime limit, or None for one-time alerts
    """
    if alert.get('type') == 5:  # One-time
        return None
    
    # Get current next_scheduled
    next_scheduled_str = alert.get('next_scheduled')
    if next_scheduled_str:
        try:
            current_next = datetime.fromisoformat(next_scheduled_str)
        except ValueError:
            current_next = datetime.now()
    else:
        current_next = datetime.now()
    
    # Calculate the occurrence after that
    future_next = get_next_occurrence(alert, current_next + timedelta(minutes=1))
    return future_next


def calculate_snooze_time(snooze_option, from_time=None):
    """
    Calculates the snooze-until datetime.
    
    Args:
        snooze_option: "1h", "1d", "1w", or custom string like "2h", "30m"
        from_time: datetime to snooze from (default: now)
    
    Returns:
        datetime to snooze until, or None if invalid
    """
    if from_time is None:
        from_time = datetime.now()
    
    delta = parse_pre_alert_string(snooze_option)
    if delta:
        return from_time + delta
    
    return None


def can_snooze_to(alert, snooze_until):
    """
    Checks if an alert can be snoozed to a specific time.
    
    Args:
        alert: Alert dict
        snooze_until: datetime to snooze to
    
    Returns:
        (bool, str) - (can_snooze, reason if not)
    """
    if snooze_until <= datetime.now():
        return False, "Snooze time must be in the future"
    
    limit = get_snooze_limit(alert)
    if limit and snooze_until >= limit:
        return False, f"Cannot snooze past next occurrence ({limit.strftime('%d/%m/%Y %H:%M')})"
    
    return True, None


# =============================================================================
# FORMATTING HELPERS
# =============================================================================

def format_datetime_human(dt):
    """Formats a datetime for human display."""
    if not dt:
        return "Unknown"
    
    now = datetime.now()
    
    if dt.date() == now.date():
        return f"Today at {dt.strftime('%H:%M')}"
    elif dt.date() == (now + timedelta(days=1)).date():
        return f"Tomorrow at {dt.strftime('%H:%M')}"
    elif dt.date() == (now - timedelta(days=1)).date():
        return f"Yesterday at {dt.strftime('%H:%M')}"
    else:
        return dt.strftime('%d/%m/%Y at %H:%M')


def format_pre_alert_human(pre_alert_str):
    """
    Converts "2d" to "2 days", etc.
    """
    if not pre_alert_str:
        return ""

    token = pre_alert_str.strip().lower()
    if token == C.BIRTHDAY_PREALERT_EVENING_BEFORE_TOKEN:
        return "evening before"
    
    pre_alert_str = token.replace(" ", "")
    match = re.match(r'^(\d+)(mo|[mhdw])$', pre_alert_str)
    if not match:
        return pre_alert_str
    
    value = int(match.group(1))
    unit = match.group(2)
    
    unit_names = {
        'm': ('minute', 'minutes'),
        'h': ('hour', 'hours'),
        'd': ('day', 'days'),
        'w': ('week', 'weeks'),
        'mo': ('month', 'months'),
    }
    
    singular, plural = unit_names.get(unit, ('unit', 'units'))
    return f"{value} {singular if value == 1 else plural}"


def _format_pre_alert_absolute(pre_dt):
    if not isinstance(pre_dt, datetime):
        return ""
    now = datetime.now()
    if pre_dt.year == now.year:
        return pre_dt.strftime("%d/%m %H:%M")
    return pre_dt.strftime("%d/%m/%Y %H:%M")


def format_pre_alert_display(alert: dict, pre_alert_str: str, *, due_dt: datetime | None = None, user_prefs: dict | None = None) -> str:
    """Render a pre-alert as resolved datetime text when possible, otherwise fallback to stable token wording."""
    if not pre_alert_str:
        return ""

    resolved_due = due_dt
    if resolved_due is None:
        try:
            resolved_due = get_next_occurrence(alert)
        except Exception:
            resolved_due = None

    if resolved_due is None:
        return format_pre_alert_human(pre_alert_str)

    pre_dt, _kind = resolve_pre_alert_fire_time(
        alert,
        pre_alert_str,
        resolved_due,
        user_prefs=user_prefs,
    )
    if not isinstance(pre_dt, datetime):
        return format_pre_alert_human(pre_alert_str)

    display_dt = pre_dt
    if isinstance(user_prefs, dict) and user_prefs.get("timezone_mode") == C.TIMEZONE_MODE_USER:
        try:
            from modules.timezone_utils import resolve_user_timezone, to_user_naive_from_server

            user_tz = resolve_user_timezone(user_prefs)
            display_dt = to_user_naive_from_server(pre_dt, user_tz)
        except Exception:
            display_dt = pre_dt

    return _format_pre_alert_absolute(display_dt)
