import logging
from datetime import datetime

from modules import constants as C
from modules.systemlog import log_system
from modules.scheduler_messagelogic import send_alert
from modules.timezone_utils import (
    compute_next_occurrence,
    now_server_naive,
    resolve_fuzzy_next_scheduled,
)

logger = logging.getLogger(__name__)


def _parse_iso_optional_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None
    return None


def _normalize_postpone_context(postpone_id=None, effective_fire_time=None, postpone_count=0):
    normalized_postpone_id = None
    if postpone_id is not None:
        text = str(postpone_id).strip()
        if text:
            normalized_postpone_id = text

    normalized_effective_fire_time = None
    if isinstance(effective_fire_time, datetime):
        normalized_effective_fire_time = effective_fire_time
    elif isinstance(effective_fire_time, str):
        try:
            normalized_effective_fire_time = datetime.fromisoformat(effective_fire_time)
        except Exception:
            normalized_effective_fire_time = None

    try:
        normalized_postpone_count = int(postpone_count or 0)
    except Exception:
        normalized_postpone_count = 0
    if normalized_postpone_count < 0:
        normalized_postpone_count = 0

    is_postponed = bool(
        normalized_postpone_id
        or normalized_effective_fire_time is not None
        or normalized_postpone_count > 0
    )

    return {
        "is_postponed": is_postponed,
        "postpone_id": normalized_postpone_id,
        "effective_fire_time": (
            normalized_effective_fire_time.isoformat()
            if normalized_effective_fire_time is not None
            else None
        ),
        "postpone_count": normalized_postpone_count,
    }


def _should_count_repetition_occurrence(alert_type, *, clear_snooze, postpone_context):
    if alert_type not in {C.ALERT_MSG_TYPE_MAIN, C.ALERT_MSG_TYPE_MISSED}:
        return False
    if clear_snooze:
        return False
    if isinstance(postpone_context, dict) and postpone_context.get("is_postponed"):
        return False
    return True


async def trigger_alert(
    bot,
    user_id,
    alert,
    alert_type,
    storage,
    sent_pre_alerts,
    missed_time=None,
    scheduled_time=None,
    clear_snooze=False,
    postpone_count=0,
    postpone_id=None,
    effective_fire_time=None,
):
    """
    Triggers an alert: sends the notification and updates state.

    Args:
        bot: Telegram bot instance
        user_id: User ID
        alert: Alert dict
        alert_type: "main" or "missed"
        missed_time: For missed alerts, the original scheduled time
        postpone_id: Optional postpone queue item id for postponed due sends
        effective_fire_time: Optional datetime when postponed due send actually fired
    """
    if not storage:
        return False

    alert_id = alert.get('id')
    user_prefs = storage.get_user_prefs(user_id)
    tz_name = None
    if isinstance(user_prefs, dict):
        tz_block = user_prefs.get("timezone")
        if isinstance(tz_block, dict):
            tz_name = tz_block.get("name")

    # Send the notification
    attempt_time = now_server_naive()
    sent_msg = await send_alert(
        bot,
        user_id,
        alert,
        storage=storage,
        alert_type=alert_type,
        missed_time=missed_time,
        scheduled_time=scheduled_time,
        occurrence_time=scheduled_time,
        postpone_count=postpone_count,
    )
    if not sent_msg:
        logger.error(f"❌ Failed to send alert {alert_id}, will retry next tick")
        storage.log_user_event(user_id, "alert_send_failed", {
            "alert_id": alert_id,
            "alert_type": alert_type,
            "scheduled_time": scheduled_time.isoformat() if scheduled_time else None,
            "attempt_time": attempt_time.isoformat(),
            "missed_time": missed_time.isoformat() if missed_time else None,
            "type": alert.get("type"),
            "type_name": alert.get("type_name"),
        })
        log_system("scheduler", "alert_send_failed", {
            "user_id": str(user_id),
            "alert_id": alert_id,
            "alert_type": alert_type,
            "scheduled_time": scheduled_time.isoformat() if scheduled_time else None,
            "missed_time": missed_time.isoformat() if missed_time else None,
            "type": alert.get("type"),
        })
        return False

    # Clear snooze only after a successful send
    if clear_snooze:
        storage.clear_alert_snooze(user_id, alert_id)

    # Update state
    now = now_server_naive()
    reference_time = scheduled_time or now
    postpone_context = _normalize_postpone_context(
        postpone_id=postpone_id,
        effective_fire_time=effective_fire_time,
        postpone_count=postpone_count,
    )

    # For one-time alerts, mark inactive after triggering
    if alert.get('type') == 5:
        storage.mark_alert_done(user_id, alert_id)
        user_payload = {
            "alert_id": alert_id,
            "alert_type": alert_type,
            "scheduled_time": scheduled_time.isoformat() if scheduled_time else None,
            "sent_time": now.isoformat(),
            "missed_time": missed_time.isoformat() if missed_time else None,
            "type": alert.get("type"),
            "type_name": alert.get("type_name"),
            "next_occurrence": None,
        }
        user_payload.update(postpone_context)
        storage.log_user_event(user_id, "alert_sent", user_payload)

        system_payload = {
            "user_id": str(user_id),
            "alert_id": alert_id,
            "alert_type": alert_type,
            "scheduled_time": scheduled_time.isoformat() if scheduled_time else None,
            "sent_time": now.isoformat(),
            "missed_time": missed_time.isoformat() if missed_time else None,
            "type": alert.get("type"),
            "next_occurrence": None,
        }
        system_payload.update(postpone_context)
        log_system("scheduler", "alert_sent", system_payload)
        logger.info(f"✅ One-time alert {alert_id} completed and deactivated")
    else:
        should_count_occurrence = _should_count_repetition_occurrence(
            alert_type,
            clear_snooze=clear_snooze,
            postpone_context=postpone_context,
        )
        repetition_outcome = {
            "ok": True,
            "found": True,
            "changed": False,
            "alert_type": alert.get("type"),
            "repetition": alert.get("repetition"),
            "before": None,
            "after": None,
            "exhausted": False,
            "should_count": should_count_occurrence,
        }

        if alert.get("type") in C.REPETITION_SUPPORTED_TYPES:
            if hasattr(storage, "consume_repetition_occurrence"):
                consume_result = storage.consume_repetition_occurrence(
                    user_id,
                    alert_id,
                    should_count=should_count_occurrence,
                )
                if isinstance(consume_result, dict):
                    repetition_outcome = consume_result
                else:
                    repetition_outcome = dict(repetition_outcome)
                    repetition_outcome["ok"] = False
                    repetition_outcome["reason_code"] = "invalid_helper_response"
            else:
                repetition_outcome = dict(repetition_outcome)
                repetition_outcome["ok"] = False
                repetition_outcome["reason_code"] = "helper_missing"

            if not repetition_outcome.get("ok"):
                log_system("scheduler", "repetition_consume_failed", {
                    "user_id": str(user_id),
                    "alert_id": alert_id,
                    "alert_type": alert.get("type"),
                    "reason_code": repetition_outcome.get("reason_code", "storage_failure"),
                    "should_count": should_count_occurrence,
                }, level="WARNING")

        repetition_exhausted = bool(
            should_count_occurrence
            and repetition_outcome.get("ok")
            and repetition_outcome.get("exhausted")
        )
        next_occ = None
        effective_fire_dt = _parse_iso_optional_datetime(effective_fire_time)

        def _persist_schedule_state(*, next_scheduled=None, fuzzy_history=None):
            kwargs = {
                "user_id": user_id,
                "alert_id": alert_id,
                "last_triggered": now,
                "next_scheduled": next_scheduled,
            }
            if fuzzy_history is not None:
                kwargs["fuzzy_history"] = fuzzy_history
            try:
                storage.update_alert_schedule_state(**kwargs)
            except TypeError:
                kwargs.pop("fuzzy_history", None)
                storage.update_alert_schedule_state(**kwargs)

        def _deactivate_for_terminal_repetition():
            _persist_schedule_state(next_scheduled=None)
            deactivated = storage.update_alert_fields(user_id, alert_id, {
                "active": False,
                "next_scheduled": None,
            })
            if not deactivated:
                log_system("scheduler", "repetition_exhaustion_deactivate_failed", {
                    "user_id": str(user_id),
                    "alert_id": alert_id,
                    "alert_type": alert.get("type"),
                    "before": repetition_outcome.get("before"),
                    "after": repetition_outcome.get("after"),
                }, level="WARNING")

            exhaustion_payload = {
                "alert_id": alert_id,
                "alert_type": alert.get("type"),
                "before": repetition_outcome.get("before"),
                "after": repetition_outcome.get("after"),
                "deactivated": bool(deactivated),
            }
            storage.log_user_event(user_id, "repetition_exhausted", exhaustion_payload)
            log_system("scheduler", "repetition_exhausted", {
                "user_id": str(user_id),
                **exhaustion_payload,
            })
            return bool(deactivated)

        if repetition_exhausted:
            _deactivate_for_terminal_repetition()
        else:
            alert_for_next = dict(alert)
            normalized_repetition = repetition_outcome.get("repetition")
            if isinstance(normalized_repetition, dict):
                alert_for_next["repetition"] = normalized_repetition
            elif "repetition" in alert_for_next:
                alert_for_next.pop("repetition", None)

            schedule = alert_for_next.get("schedule") if isinstance(alert_for_next.get("schedule"), dict) else {}
            is_fuzzy_daily = (
                alert_for_next.get("type") == 7
                and schedule.get("interval_mode") == "fuzzy"
            )

            if is_fuzzy_daily and alert_type in {C.ALERT_MSG_TYPE_MAIN, C.ALERT_MSG_TYPE_MISSED}:
                fuzzy_reference = reference_time
                history_source = "due"
                if (
                    alert_type == C.ALERT_MSG_TYPE_MAIN
                    and postpone_context.get("is_postponed")
                    and effective_fire_dt is not None
                ):
                    fuzzy_reference = effective_fire_dt
                    history_source = "postpone"
                elif alert_type == C.ALERT_MSG_TYPE_MISSED:
                    history_source = "missed"

                last_fired_at = _parse_iso_optional_datetime(alert.get("last_triggered"))
                _sampled_days, next_occ, shifted = resolve_fuzzy_next_scheduled(
                    alert_for_next,
                    fuzzy_reference,
                    user_prefs,
                    last_fired_at=last_fired_at,
                    record_history=True,
                    history_source=history_source,
                )
                if next_occ:
                    _persist_schedule_state(
                        next_scheduled=next_occ,
                        fuzzy_history=alert_for_next.get("fuzzy_history"),
                    )
                    if shifted:
                        log_system("scheduler", "timezone_shift_forward", {
                            "user_id": str(user_id),
                            "alert_id": alert_id,
                            "next_scheduled": next_occ.isoformat(),
                            "tz_name": tz_name,
                        })
                        storage.log_user_event(user_id, "timezone_shift_forward", {
                            "alert_id": alert_id,
                            "next_scheduled": next_occ.isoformat(),
                            "tz_name": tz_name,
                        })
                else:
                    repetition_exhausted = True
                    _deactivate_for_terminal_repetition()
            elif is_fuzzy_daily and alert_type == C.ALERT_MSG_TYPE_PRE:
                # Pre-alert sends must not mutate fuzzy scheduling state.
                next_occ = _parse_iso_optional_datetime(alert.get("next_scheduled"))
            else:
                # Calculate next occurrence for recurring alerts
                next_occ, shifted = compute_next_occurrence(alert_for_next, reference_time, user_prefs)
                if next_occ:
                    _persist_schedule_state(next_scheduled=next_occ)
                    if shifted:
                        log_system("scheduler", "timezone_shift_forward", {
                            "user_id": str(user_id),
                            "alert_id": alert_id,
                            "next_scheduled": next_occ.isoformat(),
                            "tz_name": tz_name,
                        })
                        storage.log_user_event(user_id, "timezone_shift_forward", {
                            "alert_id": alert_id,
                            "next_scheduled": next_occ.isoformat(),
                            "tz_name": tz_name,
                        })
                else:
                    log_system("scheduler", "next_occurrence_missing", {
                        "user_id": str(user_id),
                        "alert_id": alert_id,
                        "alert_type": alert.get("type"),
                    }, level="WARNING")
        user_payload = {
            "alert_id": alert_id,
            "alert_type": alert_type,
            "scheduled_time": scheduled_time.isoformat() if scheduled_time else None,
            "sent_time": now.isoformat(),
            "missed_time": missed_time.isoformat() if missed_time else None,
            "type": alert.get("type"),
            "type_name": alert.get("type_name"),
            "next_occurrence": next_occ.isoformat() if next_occ else None,
            "repetition_counted": should_count_occurrence,
            "repetition_exhausted": repetition_exhausted,
        }
        user_payload.update(postpone_context)
        storage.log_user_event(user_id, "alert_sent", user_payload)

        system_payload = {
            "user_id": str(user_id),
            "alert_id": alert_id,
            "alert_type": alert_type,
            "scheduled_time": scheduled_time.isoformat() if scheduled_time else None,
            "sent_time": now.isoformat(),
            "missed_time": missed_time.isoformat() if missed_time else None,
            "type": alert.get("type"),
            "next_occurrence": next_occ.isoformat() if next_occ else None,
            "repetition_counted": should_count_occurrence,
            "repetition_exhausted": repetition_exhausted,
        }
        system_payload.update(postpone_context)
        log_system("scheduler", "alert_sent", system_payload)

        # Clear pre-alert tracking for the next cycle
        if sent_pre_alerts is not None:
            keys_to_clear = [
                k for k in sent_pre_alerts.keys()
                if str(k[0]) == str(user_id) and k[1] == alert_id
            ]
            if keys_to_clear:
                for key in keys_to_clear:
                    del sent_pre_alerts[key]
                from modules.scheduler_core import state as scheduler_state
                scheduler_state.mark_dirty()

        if next_occ:
            logger.info(f"✅ Alert {alert_id} triggered, next: {next_occ}")

    return True


async def snooze_alert(user_id, alert_id, snooze_duration, storage):
    """
    Snoozes an alert for a specified duration.

    Args:
        user_id: User ID
        alert_id: Alert ID
        snooze_duration: Duration string like "1h", "1d", "1w"

    Returns:
        (success: bool, snoozed_until: datetime or None, error: str or None)
    """
    if not storage:
        return False, None, "Storage not available"

    from modules.scheduler_mathlogic import calculate_snooze_time, can_snooze_to

    alert = storage.get_alert_by_id(user_id, alert_id)
    if not alert:
        return False, None, "Alert not found"

    # Calculate snooze time
    snoozed_until = calculate_snooze_time(snooze_duration)
    if not snoozed_until:
        return False, None, "Invalid snooze duration"

    # Check if we can snooze to this time
    can_snooze, reason = can_snooze_to(alert, snoozed_until)
    if not can_snooze:
        return False, None, reason

    # Apply the snooze
    storage.update_alert_schedule_state(user_id, alert_id, snoozed_until=snoozed_until)

    logger.info(f"✅ Alert {alert_id} snoozed until {snoozed_until}")
    storage.log_user_event(user_id, "alert_snoozed", {
        "alert_id": alert_id,
        "snoozed_until": snoozed_until.isoformat(),
        "snooze_duration": snooze_duration,
    })
    log_system("scheduler", "alert_snoozed", {
        "user_id": str(user_id),
        "alert_id": alert_id,
        "snoozed_until": snoozed_until.isoformat(),
        "snooze_duration": snooze_duration,
    })
    return True, snoozed_until, None


async def mark_alert_done(user_id, alert_id, storage):
    """
    Marks an alert as done for this occurrence.

    Args:
        user_id: User ID
        alert_id: Alert ID

    Returns:
        (success: bool, was_one_time: bool, next_occurrence: datetime or None)
    """
    if not storage:
        return False, False, None

    alert = storage.get_alert_by_id(user_id, alert_id)
    if not alert:
        return False, False, None

    success, was_one_time = storage.mark_alert_done(user_id, alert_id)

    if success and not was_one_time:
        # Get the new next occurrence
        updated_alert = storage.get_alert_by_id(user_id, alert_id)
        if updated_alert:
            user_prefs = storage.get_user_prefs(user_id)
            reference_now = now_server_naive()
            schedule = updated_alert.get("schedule") if isinstance(updated_alert.get("schedule"), dict) else {}
            is_fuzzy_daily = (
                updated_alert.get("type") == 7
                and schedule.get("interval_mode") == "fuzzy"
            )
            if is_fuzzy_daily:
                _sampled_days, next_occ, shifted = resolve_fuzzy_next_scheduled(
                    updated_alert,
                    reference_now,
                    user_prefs,
                    record_history=False,
                    history_source=None,
                )
            else:
                next_occ, shifted = compute_next_occurrence(updated_alert, reference_now, user_prefs)
            if next_occ:
                storage.update_alert_schedule_state(user_id, alert_id, next_scheduled=next_occ)
                if shifted:
                    tz_name = None
                    if isinstance(user_prefs, dict):
                        tz_block = user_prefs.get("timezone")
                        if isinstance(tz_block, dict):
                            tz_name = tz_block.get("name")
                    log_system("scheduler", "timezone_shift_forward", {
                        "user_id": str(user_id),
                        "alert_id": alert_id,
                        "next_scheduled": next_occ.isoformat(),
                        "tz_name": tz_name,
                    })
                    storage.log_user_event(user_id, "timezone_shift_forward", {
                        "alert_id": alert_id,
                        "next_scheduled": next_occ.isoformat(),
                        "tz_name": tz_name,
                    })
            else:
                log_system("scheduler", "next_occurrence_missing", {
                    "user_id": str(user_id),
                    "alert_id": alert_id,
                    "alert_type": updated_alert.get("type"),
                }, level="WARNING")
            log_system("scheduler", "alert_marked_done", {
                "user_id": str(user_id),
                "alert_id": alert_id,
                "was_one_time": False,
                "next_occurrence": next_occ.isoformat() if next_occ else None,
            })
            return True, False, next_occ

    if success:
        log_system("scheduler", "alert_marked_done", {
            "user_id": str(user_id),
            "alert_id": alert_id,
            "was_one_time": bool(was_one_time),
            "next_occurrence": None,
        })
    return success, was_one_time, None
