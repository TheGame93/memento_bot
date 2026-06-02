"""Implement notification-side postpone validation and custom-postpone parsing helpers."""

import uuid
from datetime import datetime

from modules.scheduler_mathlogic import get_next_occurrence
from modules.timezone_utils import parse_user_datetime_expression


def _validate_postpone(alert, kind, fire_at, occurrence_time):
    now = datetime.now()
    if not fire_at:
        return False, "Invalid postpone time"
    if fire_at <= now:
        return False, "Postpone time must be in the future"

    if kind == "pre":
        if not occurrence_time:
            return False, "Cannot resolve the alert due time"
        if occurrence_time <= now:
            return False, "This alert due time is already in the past"
        if fire_at >= occurrence_time:
            return False, "Pre-alert postpone must be before the due time"
        return True, None

    # kind == "due"
    if alert.get("type") != 5:
        base_time = occurrence_time if occurrence_time and occurrence_time >= now else now
        next_occ = get_next_occurrence(alert, base_time)
        if next_occ and fire_at >= next_occ:
            return False, "Postpone must be before the next occurrence"

    return True, None


def _upsert_postpone_instance(storage, user_id, alert, kind, fire_at, original_time, occurrence_time, prior_count=0):
    now = datetime.now()
    orig_iso = original_time.isoformat() if original_time else None
    occ_iso = occurrence_time.isoformat() if occurrence_time else None

    queue = storage.get_postpone_queue(user_id)
    for item in queue:
        if (
            item.get("status") == "pending"
            and item.get("alert_id") == alert.get("id")
            and item.get("kind") == kind
            and item.get("original_time") == orig_iso
            and item.get("occurrence_time") == occ_iso
        ):
            # Use the higher of prior_count (from callback) or stored count
            # to avoid losing count for pre-existing instances
            existing_count = item.get("postpone_count", 0) or 0
            new_count = max(prior_count, existing_count) + 1
            storage.update_postpone_instance(user_id, item.get("id"), {
                "fire_at": fire_at.isoformat(),
                "updated_at": now.isoformat(),
                "postpone_count": new_count,
            })
            return item.get("id"), True, new_count

    new_count = prior_count + 1
    instance_id = str(uuid.uuid4())
    instance = {
        "id": instance_id,
        "alert_id": alert.get("id"),
        "kind": kind,
        "status": "pending",
        "created_at": now.isoformat(),
        "fire_at": fire_at.isoformat(),
        "original_time": orig_iso,
        "occurrence_time": occ_iso,
        "postpone_count": new_count,
    }
    storage.add_postpone_instance(user_id, instance)
    return instance_id, False, new_count


def _clear_custom_postpone_context(user_data):
    user_data.pop("expecting_custom_postpone", None)
    user_data.pop("postpone_alert_id", None)
    user_data.pop("postpone_kind", None)
    user_data.pop("postpone_original_time", None)
    user_data.pop("postpone_occurrence_time", None)
    user_data.pop("postpone_message_id", None)
    user_data.pop("postpone_count", None)


def _resolve_custom_postpone_fire_at(
    raw_text: str,
    *,
    now_server_dt: datetime,
    user_prefs: dict | None,
    kind: str,
    occurrence_time: datetime | None,
) -> tuple[datetime | None, str | None, dict]:
    """Resolve custom postpone text into a fire datetime and normalized reason metadata."""
    text = (raw_text or "").strip()
    if not text:
        return None, "empty_input", {"reason_code": "empty_input"}

    boundary_mode = "future"
    boundary_server_dt = None
    if kind == "pre" and occurrence_time is not None:
        boundary_mode = "before_boundary"
        boundary_server_dt = occurrence_time

    status, candidate, meta = parse_user_datetime_expression(
        text,
        reference_server_dt=now_server_dt,
        user_prefs=user_prefs,
        default_time=now_server_dt.strftime("%H:%M"),
        allow_relative_tokens=True,
        allow_day_only=False,
        boundary_mode=boundary_mode,
        boundary_server_dt=boundary_server_dt,
        now_server_dt=now_server_dt,
    )
    if status == "ok" and candidate is not None:
        return candidate, None, meta

    parser_reason = (meta or {}).get("reason_code")
    reason_map = {
        "empty": "empty_input",
        "candidate_not_future": "not_future",
        "candidate_not_before_boundary": "not_before_due",
        "boundary_missing": "due_time_missing",
    }
    mapped_reason = reason_map.get(parser_reason, "invalid_format_or_date")
    out_meta = dict(meta or {})
    out_meta["parser_reason_code"] = parser_reason
    return None, mapped_reason, out_meta
