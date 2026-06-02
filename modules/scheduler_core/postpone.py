import logging
from datetime import datetime, timedelta

from modules import constants as C
from modules.scheduler_core.actions import trigger_alert
from modules.scheduler_mathlogic import DUE_TOLERANCE_SECONDS
from modules.scheduler_messagelogic import send_alert
from modules.timezone_utils import get_server_tz

logger = logging.getLogger(__name__)


def parse_iso_datetime(value):
    """
    Parse an ISO datetime value and return a server-naive datetime.

    Scheduler core compares timestamps using server-naive datetimes; timezone-aware
    payloads are normalized to server timezone and stripped of tzinfo.
    """
    if not value:
        return None
    parsed = value
    if not isinstance(parsed, datetime):
        try:
            parsed = datetime.fromisoformat(value)
        except Exception:
            return None
    try:
        if parsed.tzinfo is not None:
            return parsed.astimezone(get_server_tz()).replace(tzinfo=None)
        return parsed
    except Exception:
        return None


async def process_postpone_queue_for_user(
    bot, user_id, alert_map, postpone_items, now, storage, sent_pre_alerts=None
):
    """
    Sends any due postponed instances and marks their status.
    Returns (pre_sent, due_sent).
    """
    if not postpone_items:
        return 0, 0

    pre_sent = 0
    due_sent = 0
    updates_made = False

    for item in postpone_items:
        if item.get("status") != "pending":
            continue

        alert_id = item.get("alert_id")
        alert = alert_map.get(alert_id)
        if not alert:
            if storage:
                storage.update_postpone_instance(user_id, item.get("id"), {
                    "status": "expired",
                    "expired_at": now.isoformat(),
                    "reason": "alert_inactive_or_missing",
                })
                storage.log_user_event(user_id, "postpone_expired", {
                    "postpone_id": item.get("id"),
                    "alert_id": alert_id,
                    "reason": "alert_inactive_or_missing",
                })
            updates_made = True
            continue

        if not alert.get("active", True):
            kind_peek = item.get("kind")
            fire_at_peek = parse_iso_datetime(item.get("fire_at"))
            allow_inactive_type5_due = (
                alert.get("type") == 5
                and kind_peek == "due"
                and fire_at_peek is not None
            )
            if not allow_inactive_type5_due:
                if storage:
                    storage.update_postpone_instance(user_id, item.get("id"), {
                        "status": "expired",
                        "expired_at": now.isoformat(),
                        "reason": "alert_inactive_or_missing",
                    })
                    storage.log_user_event(user_id, "postpone_expired", {
                        "postpone_id": item.get("id"),
                        "alert_id": alert_id,
                        "reason": "alert_inactive_or_missing",
                    })
                updates_made = True
                continue

        fire_at = parse_iso_datetime(item.get("fire_at"))
        if not fire_at:
            if storage:
                storage.update_postpone_instance(user_id, item.get("id"), {
                    "status": "expired",
                    "expired_at": now.isoformat(),
                    "reason": "invalid_fire_at",
                })
                storage.log_user_event(user_id, "postpone_expired", {
                    "postpone_id": item.get("id"),
                    "alert_id": alert_id,
                    "reason": "invalid_fire_at",
                })
            updates_made = True
            continue

        kind = item.get("kind")
        if kind not in ("pre", "due"):
            if storage:
                storage.update_postpone_instance(user_id, item.get("id"), {
                    "status": "expired",
                    "expired_at": now.isoformat(),
                    "reason": "invalid_kind",
                })
                storage.log_user_event(user_id, "postpone_expired", {
                    "postpone_id": item.get("id"),
                    "alert_id": alert_id,
                    "reason": "invalid_kind",
                    "kind": kind,
                })
            updates_made = True
            continue

        # Expire items that are too old to fire
        if fire_at < now - timedelta(seconds=DUE_TOLERANCE_SECONDS):
            if storage:
                storage.update_postpone_instance(user_id, item.get("id"), {
                    "status": "expired",
                    "expired_at": now.isoformat(),
                    "reason": "missed_live",
                })
                storage.log_user_event(user_id, "postpone_expired", {
                    "postpone_id": item.get("id"),
                    "alert_id": alert_id,
                    "reason": "missed_live",
                })
            updates_made = True
            continue

        # Due now?
        if fire_at <= now:
            if kind == "pre":
                occurrence_time = (
                    parse_iso_datetime(item.get("occurrence_time"))
                    or parse_iso_datetime(item.get("original_time"))
                    or fire_at
                )
                sent_msg = await send_alert(
                    bot,
                    user_id,
                    alert,
                    storage=storage,
                    alert_type=C.ALERT_MSG_TYPE_PRE,
                    main_trigger_time=occurrence_time,
                    scheduled_time=fire_at,
                    occurrence_time=occurrence_time,
                    postpone_count=item.get("postpone_count", 0),
                )
                if sent_msg:
                    pre_sent += 1
            else:
                occurrence_time = (
                    parse_iso_datetime(item.get("occurrence_time"))
                    or parse_iso_datetime(item.get("original_time"))
                    or parse_iso_datetime(alert.get("next_scheduled"))
                    or fire_at
                )
                sent_msg = await trigger_alert(
                    bot,
                    user_id,
                    alert,
                    C.ALERT_MSG_TYPE_MAIN,
                    storage,
                    sent_pre_alerts,
                    scheduled_time=occurrence_time,
                    postpone_count=item.get("postpone_count", 0),
                    postpone_id=item.get("id"),
                    effective_fire_time=fire_at,
                )
                if sent_msg:
                    due_sent += 1

            if sent_msg:
                if storage:
                    storage.update_postpone_instance(user_id, item.get("id"), {
                        "status": "fired",
                        "fired_at": now.isoformat(),
                    })
                    storage.log_user_event(user_id, "postpone_fired", {
                        "postpone_id": item.get("id"),
                        "alert_id": alert_id,
                        "kind": kind,
                        "fire_at": fire_at.isoformat(),
                    })
                updates_made = True
            else:
                if storage:
                    storage.log_user_event(user_id, "postpone_send_failed", {
                        "postpone_id": item.get("id"),
                        "alert_id": alert_id,
                        "kind": kind,
                        "fire_at": fire_at.isoformat(),
                    })

    if updates_made and storage:
        storage.cleanup_postpone_queue(user_id, now.isoformat())

    return pre_sent, due_sent
