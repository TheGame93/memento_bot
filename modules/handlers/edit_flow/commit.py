"""Provide edit-flow commit planning helpers and schedule recomputation logic."""

import copy
from datetime import datetime, timedelta

from modules import constants as C
from modules.handlers.add_flow.summary_flow import ensure_default_settings
from modules.timezone_utils import (
    compute_next_occurrence,
    now_server_naive,
    resolve_fuzzy_next_scheduled,
    resolve_user_timezone,
    to_server_naive_from_user,
    to_user_naive_from_server,
)

from .origin import _parse_iso_datetime

_EDITABLE_FIELDS = (
    "title",
    "tags",
    "pre_alerts",
    "repetition",
    "additional_info",
    "image_id",
    "local_image_path",
    "schedule",
    "type",
    "type_name",
    "birth_year",
)


def _prepare_edit_snapshot(alert):
    """Return a normalized snapshot dict of editable alert fields, including active state and ensure_default_settings initialization."""
    payload = alert if isinstance(alert, dict) else {}
    alert_type = payload.get("type")
    type_name = payload.get("type_name")
    if not isinstance(type_name, str):
        type_name = C.ALERT_TYPES.get(alert_type, "Unknown")

    snapshot = {
        "title": payload.get("title") or "",
        "type": alert_type,
        "type_name": type_name,
        "tags": list(payload.get("tags") or []),
        "pre_alerts": list(payload.get("pre_alerts") or []),
        "repetition": copy.deepcopy(payload.get("repetition")),
        "additional_info": payload.get("additional_info") or "",
        "image_id": payload.get("image_id"),
        "local_image_path": payload.get("local_image_path"),
        "schedule": copy.deepcopy(payload.get("schedule") or {}),
        "birth_year": payload.get("birth_year"),
        "active": bool(payload.get("active", True)),
    }
    ensure_default_settings(snapshot)
    return snapshot


def _extract_changed_fields(temp_alert, original_alert):
    changed = []
    for field in _EDITABLE_FIELDS:
        if temp_alert.get(field) != original_alert.get(field):
            changed.append(field)
    return changed


def _build_updates_from_changed_fields(temp_alert, changed_fields):
    updates = {}
    for field in changed_fields:
        value = temp_alert.get(field)
        if field in {"tags", "pre_alerts", "repetition", "schedule"}:
            updates[field] = copy.deepcopy(value)
        else:
            updates[field] = value
    return updates


def _is_valid_one_time_schedule(alert_payload):
    schedule = (alert_payload or {}).get("schedule") or {}
    raw_date = schedule.get("date")
    raw_time = schedule.get("time") or "10:00"
    try:
        datetime.strptime(raw_date, "%d/%m/%Y")
        datetime.strptime(raw_time, "%H:%M")
        return True
    except Exception:
        return False


def _is_fuzzy_daily_payload(alert_payload):
    if not isinstance(alert_payload, dict):
        return False
    schedule = alert_payload.get("schedule")
    if not isinstance(schedule, dict):
        return False
    return alert_payload.get("type") == 7 and schedule.get("interval_mode") == "fuzzy"


def _normalize_fuzzy_param(value):
    try:
        return float(value)
    except Exception:
        return None


def _parse_hhmm_or_default(raw_time):
    text = str(raw_time or "10:00").strip()
    try:
        parsed = datetime.strptime(text, "%H:%M")
    except Exception:
        parsed = datetime.strptime("10:00", "%H:%M")
    return parsed.hour, parsed.minute


def _adjust_fuzzy_time_component(existing_next, target_time, now_ref, user_prefs):
    """Return a server-naive datetime with the time component replaced by target_time, advancing one day when the result is not strictly future; returns None on parse or timezone resolution failure."""
    base_dt = _parse_iso_datetime(existing_next)
    if base_dt is None:
        return None
    if base_dt.tzinfo is not None:
        base_dt = base_dt.astimezone().replace(tzinfo=None)

    reference_now = now_ref if isinstance(now_ref, datetime) else now_server_naive()
    if reference_now.tzinfo is not None:
        reference_now = reference_now.astimezone().replace(tzinfo=None)

    hour, minute = _parse_hhmm_or_default(target_time)
    mode = C.TIMEZONE_DEFAULT_MODE
    if isinstance(user_prefs, dict):
        mode = user_prefs.get("timezone_mode") or C.TIMEZONE_DEFAULT_MODE

    if mode == C.TIMEZONE_MODE_USER:
        try:
            user_tz = resolve_user_timezone(user_prefs)
            local_base = to_user_naive_from_server(base_dt, user_tz)
            local_now = to_user_naive_from_server(reference_now, user_tz)
            adjusted_local = local_base.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if adjusted_local <= local_now:
                adjusted_local += timedelta(days=1)
            adjusted_server, _shifted = to_server_naive_from_user(adjusted_local, user_tz)
            return adjusted_server
        except Exception:
            return None

    adjusted_server = base_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if adjusted_server <= reference_now:
        adjusted_server += timedelta(days=1)
    return adjusted_server


def _build_commit_plan(
    temp_alert,
    original_alert,
    now_ref,
    user_prefs,
    *,
    compute_next_occurrence_fn=compute_next_occurrence,
    resolve_fuzzy_next_scheduled_fn=resolve_fuzzy_next_scheduled,
):
    """Return a commit-plan dict with changed_fields, updates, schedule_changed, next_scheduled, schedule_compute_error, apply_schedule_side_effects, and reactivate_one_time derived by diffing temp vs original alert."""
    changed_fields = _extract_changed_fields(temp_alert, original_alert)
    schedule_changed = any(field in {"type", "schedule"} for field in changed_fields)
    next_occurrence = None
    next_scheduled = None
    schedule_compute_error = False
    apply_schedule_side_effects = False

    if schedule_changed:
        temp_is_fuzzy = _is_fuzzy_daily_payload(temp_alert)
        original_is_fuzzy = _is_fuzzy_daily_payload(original_alert)

        if temp_is_fuzzy:
            temp_schedule = temp_alert.get("schedule") if isinstance(temp_alert.get("schedule"), dict) else {}
            original_schedule = original_alert.get("schedule") if isinstance(original_alert.get("schedule"), dict) else {}
            fuzzy_params_changed = (
                temp_schedule.get("interval_mode") != original_schedule.get("interval_mode")
                or _normalize_fuzzy_param(temp_schedule.get("fuzzy_mean")) != _normalize_fuzzy_param(original_schedule.get("fuzzy_mean"))
                or _normalize_fuzzy_param(temp_schedule.get("fuzzy_std")) != _normalize_fuzzy_param(original_schedule.get("fuzzy_std"))
            )
            fuzzy_time_changed = temp_schedule.get("time") != original_schedule.get("time")

            if not original_is_fuzzy or fuzzy_params_changed:
                _sampled_days, next_occurrence, _shifted = resolve_fuzzy_next_scheduled_fn(
                    temp_alert,
                    now_ref,
                    user_prefs,
                    record_history=False,
                    history_source=None,
                )
                if next_occurrence is not None:
                    next_scheduled = next_occurrence
                    apply_schedule_side_effects = True
                else:
                    schedule_compute_error = True
            elif fuzzy_time_changed:
                next_scheduled = _adjust_fuzzy_time_component(
                    original_alert.get("next_scheduled"),
                    temp_schedule.get("time"),
                    now_ref,
                    user_prefs,
                )
                if next_scheduled is None:
                    _sampled_days, next_occurrence, _shifted = resolve_fuzzy_next_scheduled_fn(
                        temp_alert,
                        now_ref,
                        user_prefs,
                        record_history=False,
                        history_source=None,
                    )
                    if next_occurrence is not None:
                        next_scheduled = next_occurrence
                    else:
                        schedule_compute_error = True
                if next_scheduled is not None:
                    apply_schedule_side_effects = True
            else:
                next_scheduled = _parse_iso_datetime(original_alert.get("next_scheduled"))
                if next_scheduled is None:
                    _sampled_days, next_occurrence, _shifted = resolve_fuzzy_next_scheduled_fn(
                        temp_alert,
                        now_ref,
                        user_prefs,
                        record_history=False,
                        history_source=None,
                    )
                    if next_occurrence is not None:
                        next_scheduled = next_occurrence
                    else:
                        schedule_compute_error = True
                apply_schedule_side_effects = False
        else:
            next_occurrence, _shifted = compute_next_occurrence_fn(temp_alert, now_ref, user_prefs)
            if next_occurrence is not None:
                next_scheduled = next_occurrence
                apply_schedule_side_effects = True
            elif temp_alert.get("type") == 5 and _is_valid_one_time_schedule(temp_alert):
                next_scheduled = now_ref
                apply_schedule_side_effects = True
            else:
                schedule_compute_error = True

    original_type = original_alert.get("type")
    original_active = bool(original_alert.get("active", True))
    reactivate_one_time = (
        schedule_changed
        and original_type == 5
        and temp_alert.get("type") == 5
        and not original_active
        and next_occurrence is not None
        and next_occurrence > now_ref
    )

    updates = _build_updates_from_changed_fields(temp_alert, changed_fields)
    if reactivate_one_time:
        updates["active"] = True
        if "active" not in changed_fields:
            changed_fields.append("active")

    return {
        "changed_fields": changed_fields,
        "updates": updates,
        "schedule_changed": schedule_changed,
        "next_scheduled": next_scheduled,
        "schedule_compute_error": schedule_compute_error,
        "apply_schedule_side_effects": apply_schedule_side_effects,
        "reactivate_one_time": reactivate_one_time,
    }
