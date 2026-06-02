"""Ghost-reminder helpers for missed-alert follow-up flows."""

from __future__ import annotations

from datetime import datetime

from modules import constants as C
from modules.timezone_utils import resolve_user_timezone, to_user_naive_from_server


def is_ghost_alert(alert: dict) -> bool:
    """Return whether the alert was created as a ghost reminder copy."""
    if not isinstance(alert, dict):
        return False
    return bool(alert.get("ghost_source_id"))


def create_ghost_alert(
    storage,
    user_id: int,
    source_alert: dict,
    fire_at: datetime,
    missed_date_str: str,
) -> str | None:
    """Create and persist a one-time ghost copy and return its alert ID when saved.

    Returns None when source_alert is not a dict, when source_alert has no 'id',
    or when storage.save_alert fails.

    Ghost fields written:
    - type=5, type_name=C.ALERT_TYPES[5], active=True
    - title: '👻 ' prefix prepended to source title
    - additional_info: provenance string with 'Ghost of:', 'Expected:', and offline note
    - ghost_source_id: source_alert['id']
    - schedule.date: 'DD/MM/YYYY' format; schedule.time: 'HH:MM' format
    - No tags, pre_alerts, media, or repetition.

    When timezone_mode is TIMEZONE_MODE_USER, fire_at (server-naive) is converted
    to the user's wall-clock time before formatting the stored schedule, so save_alert
    recomputes next_scheduled at the correct local instant.
    """
    if not isinstance(source_alert, dict):
        return None

    source_id = source_alert.get("id")
    if not source_id:
        return None

    schedule_dt = fire_at
    user_prefs = storage.get_user_prefs(user_id) or {}
    mode = user_prefs.get("timezone_mode") or C.TIMEZONE_DEFAULT_MODE
    if mode == C.TIMEZONE_MODE_USER:
        user_tz = resolve_user_timezone(user_prefs)
        schedule_dt = to_user_naive_from_server(fire_at, user_tz)

    ghost_payload = {
        "type": 5,
        "type_name": C.ALERT_TYPES[5],
        "title": f"👻 {source_alert.get('title') or 'Untitled'}",
        "additional_info": (
            f"Ghost of: {source_id}\n"
            f"Expected: {missed_date_str}\n"
            "Not delivered - bot was offline"
        ),
        "ghost_source_id": source_id,
        "active": True,
        "schedule": {
            "date": schedule_dt.strftime("%d/%m/%Y"),
            "time": schedule_dt.strftime("%H:%M"),
        },
        "tags": [],
        "pre_alerts": [],
    }

    return storage.save_alert(user_id, ghost_payload)


def get_pending_ghost_alerts(storage, user_id: int) -> list[dict]:
    """Return active one-time alerts that carry a ghost source reference."""
    active_alerts = storage.get_active_alerts(user_id) or []
    return [alert for alert in active_alerts if alert.get("type") == 5 and is_ghost_alert(alert)]


def find_existing_ghost(storage, user_id: int, source_alert_id: str) -> dict | None:
    """Return the first active ghost alert that points to the provided source alert ID."""
    for alert in get_pending_ghost_alerts(storage, user_id):
        if str(alert.get("ghost_source_id")) == str(source_alert_id):
            return alert
    return None
