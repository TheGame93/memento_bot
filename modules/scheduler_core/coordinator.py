"""Scheduler coordinator utilities split from scheduler.py."""

import asyncio
import logging
import time
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from modules import constants as C
from modules.backup_core.constants import (
    LOCAL_BACKUP_HOUR,
    LOCAL_BACKUP_MINUTE,
    EMAIL_BACKUP_DAY,
    EMAIL_BACKUP_HOUR,
    EMAIL_BACKUP_MINUTE,
    EMAIL_REMINDER_DAY,
    EMAIL_REMINDER_HOUR,
    EMAIL_REMINDER_MINUTE,
)
from modules.backup_core.local_backup import backup_all_users_local
from modules.backup_core.email_backup import (
    normalize_email_address,
    run_monthly_email_backups,
    send_backup_email,
    should_send_monthly_reminder,
    should_send_startup_backup,
    should_send_startup_reminder,
)
from modules.backup_core import system_backup
from modules.security.whitelist_store import list_whitelist_users
from modules.security.roles import normalize_role
from modules.scheduler_mathlogic import (
    is_due,
    is_pre_alert_due,
    resolve_pre_alert_fire_time,
)
from modules.repetition_utils import (
    is_repetition_supported,
    normalize_repetition_payload,
    parse_until_date_strict,
)
from modules.timezone_utils import (
    compute_next_occurrence,
    now_server_naive,
    resolve_fuzzy_next_scheduled,
    resolve_user_timezone,
    to_user_naive_from_server,
)
from modules.scheduler_messagelogic import send_alert
from modules.scheduler_core.actions import trigger_alert as _trigger_alert
from modules.scheduler_core.missed import handle_missed_alerts as _handle_missed_alerts
from modules.scheduler_core.postpone import (
    parse_iso_datetime,
    process_postpone_queue_for_user,
)
from modules.scheduler_core import state as scheduler_state
from modules.systemlog import log_system
from modules.security.whitelist_notifications import send_pending_requests_digest
from modules.handlers.base import (
    build_backup_email_sent_notification,
    build_mail_backup_reminder_message,
    build_mail_backup_reminder_keyboard,
)

logger = logging.getLogger(__name__)

# =============================================================================
# GLOBAL STATE
# =============================================================================

# The APScheduler instance
scheduler = None

# Reference to the bot application (set during init)
_app = None

# Reference to storage manager (set during init)
_storage = None


# =============================================================================
# ACCESSORS
# =============================================================================


def get_storage():
    """Return the scheduler-wide storage manager reference."""
    return _storage


def get_app():
    """Return the scheduler-wide application reference."""
    return _app


def get_scheduler():
    """Return the APScheduler instance managed by the coordinator."""
    return scheduler


# =============================================================================
# INTERNAL HELPERS
# =============================================================================


def _get_scheduled_time(alert, now, user_prefs):
    """
    Returns the scheduled datetime for the current occurrence.
    Falls back to calculated next occurrence if stored value is missing/invalid.
    """
    next_scheduled_str = alert.get('next_scheduled')
    if next_scheduled_str:
        scheduled_time = parse_iso_datetime(next_scheduled_str)
        if scheduled_time:
            return scheduled_time
        next_occ, _ = compute_next_occurrence(alert, now - timedelta(days=1), user_prefs)
        return next_occ
    next_occ, _ = compute_next_occurrence(alert, now - timedelta(days=1), user_prefs)
    return next_occ


def _resolve_local_now_date(now_server_dt, user_prefs):
    local_now = now_server_dt
    if isinstance(user_prefs, dict):
        mode = user_prefs.get("timezone_mode") or C.TIMEZONE_DEFAULT_MODE
        if mode == C.TIMEZONE_MODE_USER:
            try:
                user_tz = resolve_user_timezone(user_prefs)
                local_now = to_user_naive_from_server(now_server_dt, user_tz)
            except Exception:
                local_now = now_server_dt
    return local_now.date()


def _is_repetition_terminal(alert, now_server_dt, user_prefs, *, include_today=False):
    if not isinstance(alert, dict):
        return False
    alert_type = alert.get("type")
    if not is_repetition_supported(alert_type):
        return False
    repetition = normalize_repetition_payload(alert_type, alert.get("repetition"))
    if not isinstance(repetition, dict):
        return False

    mode = repetition.get("mode")
    if mode == C.REPETITION_MODE_COUNT:
        try:
            count_remaining = int(repetition.get("count_remaining") or 0)
        except Exception:
            count_remaining = 0
        return count_remaining <= 0

    if mode == C.REPETITION_MODE_UNTIL_DATE:
        until_date = parse_until_date_strict(repetition.get("until_date"))
        if until_date is None:
            return False
        local_today = _resolve_local_now_date(now_server_dt, user_prefs)
        if include_today:
            return local_today >= until_date
        return local_today > until_date

    return False


def _deactivate_repetition_terminal_alert(storage, user_id, alert_id, now_ref, *, source):
    storage.update_alert_schedule_state(
        user_id,
        alert_id,
        last_triggered=now_ref,
    )
    deactivated = storage.update_alert_fields(user_id, alert_id, {
        "active": False,
        "next_scheduled": None,
    })
    if not deactivated:
        log_system("scheduler", "repetition_exhaustion_deactivate_failed", {
            "user_id": str(user_id),
            "alert_id": alert_id,
            "source": source,
        }, level="WARNING")
        return False

    payload = {
        "alert_id": alert_id,
        "source": source,
        "deactivated": True,
    }
    storage.log_user_event(user_id, "repetition_exhausted", payload)
    log_system("scheduler", "repetition_exhausted", {
        "user_id": str(user_id),
        **payload,
    })
    return True


def _is_fuzzy_daily_alert(alert):
    if not isinstance(alert, dict):
        return False
    schedule = alert.get("schedule")
    if not isinstance(schedule, dict):
        return False
    return alert.get("type") == 7 and schedule.get("interval_mode") == "fuzzy"


def reschedule_user_alerts(user_id, reason=None, storage=None):
    """
    Recompute next_scheduled for all active alerts of a user using current prefs.
    Returns number of alerts updated.
    """
    target_storage = storage or _storage
    if not target_storage:
        return 0
    data = target_storage.get_all_alerts(user_id) or {}
    alerts = data.get("alerts", []) or []
    user_prefs = target_storage.get_user_prefs(user_id)
    now_ref = now_server_naive()
    updated = 0

    for alert in alerts:
        if not alert.get("active", True):
            continue
        alert_id = alert.get("id")
        if not alert_id:
            continue
        if _is_fuzzy_daily_alert(alert):
            _sampled_days, next_occ, shifted = resolve_fuzzy_next_scheduled(
                alert,
                now_ref,
                user_prefs,
                record_history=False,
                history_source=None,
            )
        else:
            next_occ, shifted = compute_next_occurrence(alert, now_ref, user_prefs)
        if not next_occ:
            if _is_repetition_terminal(alert, now_ref, user_prefs, include_today=True):
                if _deactivate_repetition_terminal_alert(
                    target_storage,
                    user_id,
                    alert_id,
                    now_ref,
                    source="reschedule_user_alerts",
                ):
                    updated += 1
            else:
                log_system("scheduler", "next_occurrence_missing", {
                    "user_id": str(user_id),
                    "alert_id": alert_id,
                    "alert_type": alert.get("type"),
                    "source": "reschedule_user_alerts",
                }, level="WARNING")
            continue
        target_storage.update_alert_schedule_state(user_id, alert_id, next_scheduled=next_occ)
        updated += 1
        if shifted:
            tz_name = None
            tz_block = user_prefs.get("timezone") if isinstance(user_prefs, dict) else None
            if isinstance(tz_block, dict):
                tz_name = tz_block.get("name")
            log_system("scheduler", "timezone_shift_forward", {
                "user_id": str(user_id),
                "alert_id": alert_id,
                "next_scheduled": next_occ.isoformat(),
                "tz_name": tz_name,
            })
            target_storage.log_user_event(user_id, "timezone_shift_forward", {
                "alert_id": alert_id,
                "next_scheduled": next_occ.isoformat(),
                "tz_name": tz_name,
            })

    log_system("scheduler", "timezone_reschedule", {
        "user_id": str(user_id),
        "updated_alerts": updated,
        "reason": reason,
    })
    return updated


def _run_local_backup_job():
    if not _storage:
        logger.warning("⚠️ Local backup skipped: storage not initialized")
        return
    try:
        backup_all_users_local(_storage)
    except Exception as exc:
        log_system("backup", "local_backup_job_failed", {
            "error": str(exc),
        }, level="ERROR")


def _run_system_backup_job():
    """Build and retain one system backup archive for the nightly backup slot."""
    try:
        built = system_backup.build_system_backup()
        retention_result = system_backup.enforce_system_retention()
        log_system("backup", "system_backup_created", {
            "path": built.get("path"),
            "file_count": int(built.get("file_count") or 0),
            "retention_drop": int((retention_result.get("stats") or {}).get("total_drop") or 0),
        })
    except Exception as exc:
        log_system("backup", "system_backup_job_failed", {"error": str(exc)}, level="ERROR")


async def _run_system_backup_email_job():
    """Send monthly system-backup archive emails to developer recipients."""
    if not _storage:
        return
    try:
        developer_ids = [
            str(item.get("id"))
            for item in list_whitelist_users()
            if item.get("id") is not None and normalize_role(item.get("role")) == "developer"
        ]
        await asyncio.to_thread(system_backup.send_system_backup_email, developer_ids, _storage)
    except Exception as exc:
        log_system("backup", "system_backup_email_job_failed", {"error": str(exc)}, level="ERROR")


async def _run_email_backup_job():
    if not _storage or not _app:
        logger.warning("⚠️ Email backup skipped: storage or app not initialized")
        return
    try:
        results = await asyncio.to_thread(run_monthly_email_backups, _storage)
    except Exception as exc:
        log_system("backup", "email_backup_job_failed", {
            "error": str(exc),
        }, level="ERROR")
        return
    for entry in (results or []):
        if not (entry.get("result") or {}).get("sent"):
            continue
        uid = entry["user_id"]
        r = entry["result"]
        try:
            notif = build_backup_email_sent_notification(
                from_email=r.get("from_email", ""),
                to_email=r.get("to_email", ""),
                size_bytes=r.get("bytes"),
                reason="monthly",
                sent_at_iso=r.get("sent_at", datetime.now().isoformat()),
            )
            await _app.bot.send_message(chat_id=uid, text=notif, parse_mode="HTML")
        except Exception as notif_exc:
            log_system("backup", "email_backup_notification_failed", {
                "user_id": str(uid),
                "reason_code": "notification_send_failed",
                "error_class": type(notif_exc).__name__,
                "source": "monthly",
            }, level="WARNING")


async def _run_email_backup_reminder_job():
    if not _storage or not _app:
        logger.warning("⚠️ Email backup reminder skipped: storage or app not initialized")
        return
    now = datetime.now()
    counts = {
        "checked": 0,
        "sent": 0,
        "skipped_not_whitelisted": 0,
        "skipped_not_day": 0,
        "skipped_backup_enabled": 0,
        "skipped_has_email": 0,
        "skipped_disabled": 0,
        "skipped_snoozed": 0,
        "skipped_already_sent": 0,
        "errors": 0,
    }
    for user_id in _storage.get_all_users():
        counts["checked"] += 1
        if not _storage.is_user_whitelisted(user_id):
            counts["skipped_not_whitelisted"] += 1
            continue
        prefs = _storage.get_backup_prefs(user_id)
        ok, reason = should_send_monthly_reminder(now, prefs)
        if not ok:
            key = f"skipped_{reason}"
            if key not in counts:
                key = "skipped_not_day"
            counts[key] += 1
            continue
        message = build_mail_backup_reminder_message(prefs)
        keyboard = build_mail_backup_reminder_keyboard(prefs)
        try:
            await _app.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            _storage.update_backup_prefs(user_id, {
                "last_email_reminder_sent": now.isoformat(),
            })
            _storage.log_user_event(user_id, "backup_email_reminder_sent", {
                "source": "scheduler",
            })
            counts["sent"] += 1
        except Exception as exc:
            counts["errors"] += 1
            log_system("backup", "email_backup_reminder_send_failed", {
                "user_id": str(user_id),
                "error": str(exc),
            }, level="ERROR")
    log_system("backup", "email_backup_reminder_job", counts)


def _normalize_email_error_code(value):
    known = {
        "email_missing",
        "smtp_port_invalid",
        "smtp_host_missing",
        "attachment_too_large",
        "manifest_invalid",
    }
    if not value:
        return "unknown_error"
    text = str(value)
    if text in known:
        return text
    return "send_failed"


async def _run_startup_email_backup_catchup():
    if not _storage or not _app:
        logger.warning("⚠️ Email backup catchup skipped: storage or app not initialized")
        return
    now = datetime.now()
    counts = {
        "checked": 0,
        "backup_sent": 0,
        "backup_errors": 0,
        "backup_skipped_disabled": 0,
        "backup_skipped_schedule_invalid": 0,
        "backup_skipped_not_due": 0,
        "backup_skipped_already_sent": 0,
        "backup_skipped_missing_email": 0,
        "reminder_sent": 0,
        "reminder_errors": 0,
        "reminder_skipped_schedule_invalid": 0,
        "reminder_skipped_not_due": 0,
        "reminder_skipped_backup_enabled": 0,
        "reminder_skipped_snoozed": 0,
        "reminder_skipped_has_email": 0,
        "reminder_skipped_disabled": 0,
        "reminder_skipped_already_sent": 0,
        "skipped_not_whitelisted": 0,
        "errors": 0,
    }
    for user_id in _storage.get_all_users():
        counts["checked"] += 1
        try:
            if not _storage.is_user_whitelisted(user_id):
                counts["skipped_not_whitelisted"] += 1
                continue
            prefs = _storage.get_backup_prefs(user_id)

            rem_ok, rem_reason, _rem_expected = should_send_startup_reminder(now, prefs)
            if rem_ok:
                message = build_mail_backup_reminder_message(prefs)
                keyboard = build_mail_backup_reminder_keyboard(prefs)
                try:
                    await _app.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode="HTML",
                        reply_markup=keyboard,
                    )
                    _storage.update_backup_prefs(user_id, {
                        "last_email_reminder_sent": now.isoformat(),
                    })
                    _storage.log_user_event(user_id, "backup_email_reminder_sent", {
                        "source": "startup",
                    })
                    counts["reminder_sent"] += 1
                except Exception as exc:
                    counts["reminder_errors"] += 1
                    log_system("backup", "email_backup_reminder_send_failed", {
                        "user_id": str(user_id),
                        "error": str(exc),
                        "source": "startup",
                    }, level="ERROR")
            else:
                key = f"reminder_skipped_{rem_reason}"
                if key not in counts:
                    key = "reminder_skipped_not_due"
                counts[key] += 1

            ok, reason, expected = should_send_startup_backup(now, prefs)
            if not ok:
                key = f"backup_skipped_{reason}"
                if key not in counts:
                    key = "backup_skipped_not_due"
                counts[key] += 1
                continue
            to_email = normalize_email_address(prefs.get("email_address"))
            if not to_email:
                counts["backup_skipped_missing_email"] += 1
                continue
            result = await asyncio.to_thread(
                send_backup_email,
                _storage,
                user_id,
                to_email,
                now=now,
                reason="startup_catchup",
                history_slot_dt=expected,
            )
            if result.get("sent"):
                _storage.log_user_event(user_id, "backup_email_send_result", {
                    "source": "startup",
                    "sent": True,
                })
                counts["backup_sent"] += 1
                try:
                    notif = build_backup_email_sent_notification(
                        from_email=result.get("from_email", ""),
                        to_email=result.get("to_email", to_email),
                        size_bytes=result.get("bytes"),
                        reason="startup_catchup",
                        sent_at_iso=result.get("sent_at", now.isoformat()),
                    )
                    await _app.bot.send_message(chat_id=user_id, text=notif, parse_mode="HTML")
                except Exception as notif_exc:
                    log_system("backup", "email_backup_notification_failed", {
                        "user_id": str(user_id),
                        "reason_code": "notification_send_failed",
                        "error_class": type(notif_exc).__name__,
                        "source": "startup",
                    }, level="WARNING")
            else:
                error_code = _normalize_email_error_code(result.get("error"))
                _storage.log_user_event(user_id, "backup_email_send_result", {
                    "source": "startup",
                    "sent": False,
                    "error": error_code,
                })
                counts["backup_errors"] += 1
        except Exception as exc:
            counts["errors"] += 1
            log_system("backup", "email_backup_startup_catchup_failed", {
                "user_id": str(user_id),
                "error": str(exc),
            }, level="ERROR")
    log_system("backup", "email_backup_startup_catchup", counts)


def _should_send_system_backup(now):
    """Return whether system-backup monthly email should run at startup catch-up."""
    if int(now.day) != int(EMAIL_BACKUP_DAY):
        return False
    state = system_backup._load_system_state()  # noqa: SLF001
    slot_key = f"{now.year}-{now.month:02d}"
    slot_bucket = (state.get("monthly_send_slots") or {}).get(slot_key) or {}
    return not any(bool(item.get("sent")) for item in slot_bucket.values() if isinstance(item, dict))


async def _run_startup_system_backup_catchup():
    """Run startup catch-up for monthly system-backup emails when slot is unsent."""
    if not _storage:
        return
    now = datetime.now()
    if not _should_send_system_backup(now):
        return
    await _run_system_backup_email_job()


async def _run_pending_request_digest_job():
    if not _storage or not _app:
        logger.warning("Pending request digest skipped: storage or app not initialized")
        return
    try:
        await send_pending_requests_digest(_app.bot, _storage)
    except Exception as exc:
        log_system("security", "whitelist_pending_digest_failed", {
            "error": str(exc),
        }, level="ERROR")


# =============================================================================
# INITIALIZATION
# =============================================================================


def init_scheduler(app, storage):
    """
    Initializes the scheduler system.
    Call this from mainbot.py after creating the Application.

    Args:
        app: The python-telegram-bot Application instance
        storage: The StorageManager instance
    """
    global scheduler, _app, _storage

    _app = app
    _storage = storage

    # Create the APScheduler instance
    scheduler = AsyncIOScheduler()

    # Add the main check job
    scheduler.add_job(
        check_due_alerts,
        trigger=IntervalTrigger(seconds=C.SCHEDULER_INTERVAL_SECONDS),
        id='alert_checker',
        name='Check for due alerts',
        replace_existing=True
    )

    scheduler.add_job(
        _run_local_backup_job,
        trigger=CronTrigger(hour=LOCAL_BACKUP_HOUR, minute=LOCAL_BACKUP_MINUTE),
        id='local_backup',
        name='Local user backups',
        replace_existing=True
    )

    scheduler.add_job(
        _run_system_backup_job,
        trigger=CronTrigger(hour=LOCAL_BACKUP_HOUR, minute=(LOCAL_BACKUP_MINUTE + 5) % 60),
        id='system_backup_local',
        name='Local system backups',
        replace_existing=True
    )

    scheduler.add_job(
        _run_email_backup_job,
        trigger=CronTrigger(day=EMAIL_BACKUP_DAY, hour=EMAIL_BACKUP_HOUR, minute=EMAIL_BACKUP_MINUTE),
        id='email_backup',
        name='Monthly email backups',
        replace_existing=True
    )

    scheduler.add_job(
        _run_system_backup_email_job,
        trigger=CronTrigger(day=EMAIL_BACKUP_DAY, hour=EMAIL_BACKUP_HOUR, minute=EMAIL_BACKUP_MINUTE),
        id='system_backup_email',
        name='Monthly system backup email',
        replace_existing=True
    )

    scheduler.add_job(
        _run_email_backup_reminder_job,
        trigger=CronTrigger(day=EMAIL_REMINDER_DAY, hour=EMAIL_REMINDER_HOUR, minute=EMAIL_REMINDER_MINUTE),
        id='email_backup_reminder',
        name='Monthly email backup reminders',
        replace_existing=True
    )

    scheduler.add_job(
        _run_pending_request_digest_job,
        trigger=CronTrigger(hour=9, minute=0),
        id='whitelist_pending_digest',
        name='Whitelist pending request digest',
        replace_existing=True
    )

    logger.info(f"✅ Scheduler initialized (interval: {C.SCHEDULER_INTERVAL_SECONDS}s)")
    log_system("lifecycle", "scheduler_initialized", {
        "interval_seconds": C.SCHEDULER_INTERVAL_SECONDS,
    })


async def start_scheduler():
    """
    Starts the scheduler and performs initial load.
    Call this after the bot has started (e.g., in post_init).
    """
    global scheduler

    if scheduler is None:
        logger.error("❌ Scheduler not initialized. Call init_scheduler first.")
        return

    # Load all alerts and compute next occurrences
    await load_all_alerts()

    # Restore pre-alert tracking state from disk before missed recovery.
    # Missed pre-alert classification needs this state to avoid startup false-positives.
    scheduler_state.load_pre_alert_state()

    # Load missed-alert tracking state (must happen before handle_missed_alerts)
    if C.MISSED_ALERTS_NOTIFY_MODE == "once":
        scheduler_state.load_notified_missed_pre()
    elif C.MISSED_ALERTS_NOTIFY_MODE == "always":
        scheduler_state.load_pending_missed()

    # Check for missed alerts while bot was offline
    await handle_missed_alerts()

    # Start the scheduler
    if not scheduler.running:
        scheduler_state.last_tick_time = None
        scheduler.start()
        logger.info("✅ Scheduler started")
        log_system("lifecycle", "scheduler_started", {})
        try:
            asyncio.create_task(_run_startup_email_backup_catchup())
            asyncio.create_task(_run_startup_system_backup_catchup())
        except Exception as exc:
            log_system("backup", "email_backup_startup_catchup_failed", {
                "error": str(exc),
            }, level="ERROR")


def stop_scheduler():
    """Stops the scheduler gracefully."""
    global scheduler

    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("✅ Scheduler stopped")
        log_system("lifecycle", "scheduler_stopped", {})
    scheduler_state.save_pre_alert_state()
    if C.MISSED_ALERTS_NOTIFY_MODE == "once":
        scheduler_state.save_notified_missed_pre()
        scheduler_state.notified_missed_pre.clear()
    elif C.MISSED_ALERTS_NOTIFY_MODE == "always":
        scheduler_state.save_pending_missed()
        scheduler_state.pending_missed_notifications.clear()
    scheduler_state.sent_pre_alerts.clear()
    scheduler_state.last_tick_time = None


# =============================================================================
# ALERT LOADING
# =============================================================================


async def load_all_alerts():
    """
    Load active alerts on startup and refresh cached schedules when needed.

    Cached timestamps are parsed through scheduler-core normalization so startup
    comparisons stay safe even when legacy payloads contain timezone offsets.
    """
    global _storage

    if not _storage:
        logger.error("❌ Storage not available")
        return

    all_users_alerts = _storage.get_all_active_alerts_all_users()
    total_alerts = 0
    updated_alerts = 0

    for user_id, alerts in all_users_alerts.items():
        user_prefs = _storage.get_user_prefs(user_id) if _storage else None
        now_ref = now_server_naive()
        revalidation_ref = now_ref - timedelta(days=1)
        for alert in alerts:
            total_alerts += 1
            is_fuzzy_daily = _is_fuzzy_daily_alert(alert)

            # Calculate next occurrence if not already set or in the past
            next_scheduled_str = alert.get('next_scheduled')
            needs_update = False
            revalidated_next_occ = None
            shifted = False
            
            if next_scheduled_str:
                # parse_iso_datetime normalizes aware payloads to server-naive.
                next_scheduled = parse_iso_datetime(next_scheduled_str)
                if not next_scheduled:
                    needs_update = True
                else:
                    schedule = alert.get("schedule") if isinstance(alert, dict) else {}
                    ordinals = schedule.get("ordinals") if isinstance(schedule, dict) else []
                    # Monthly-relative alerts with negative ordinals are revalidated
                    # against a startup-safe reference to repair stale cached values.
                    is_type2_negative_ordinal = (
                        alert.get("type") == 2
                        and isinstance(ordinals, list)
                        and any(isinstance(item, str) and item.strip() == "Last" for item in ordinals)
                    )
                    if is_type2_negative_ordinal:
                        revalidated_next_occ, _ = compute_next_occurrence(
                            alert,
                            revalidation_ref,
                            user_prefs,
                        )
                        if revalidated_next_occ is None or revalidated_next_occ != next_scheduled:
                            needs_update = True
                    # Fuzzy schedules are sampled for strict-future startup safety whenever
                    # the stored timestamp is already past now.
                    if is_fuzzy_daily and next_scheduled < now_ref:
                        needs_update = True
                    # Non-fuzzy schedules keep the startup-safe stale threshold behavior.
                    if not is_fuzzy_daily and next_scheduled < revalidation_ref:
                        needs_update = True
            else:
                needs_update = True

            if not needs_update and _is_repetition_terminal(alert, now_ref, user_prefs, include_today=False):
                if _deactivate_repetition_terminal_alert(
                    _storage,
                    user_id,
                    alert['id'],
                    now_ref,
                    source="load_all_alerts_cached_schedule",
                ):
                    updated_alerts += 1
                continue

            if needs_update:
                next_occ = revalidated_next_occ
                if next_occ is None:
                    if is_fuzzy_daily:
                        _sampled_days, next_occ, shifted = resolve_fuzzy_next_scheduled(
                            alert,
                            now_ref,
                            user_prefs,
                            record_history=False,
                            history_source=None,
                        )
                    else:
                        next_occ, _ = compute_next_occurrence(alert, now_ref, user_prefs)
                if next_occ:
                    _storage.update_alert_schedule_state(
                        user_id,
                        alert['id'],
                        next_scheduled=next_occ
                    )
                    updated_alerts += 1
                    if shifted:
                        tz_name = None
                        tz_block = user_prefs.get("timezone") if isinstance(user_prefs, dict) else None
                        if isinstance(tz_block, dict):
                            tz_name = tz_block.get("name")
                        log_system("scheduler", "timezone_shift_forward", {
                            "user_id": str(user_id),
                            "alert_id": alert.get("id"),
                            "next_scheduled": next_occ.isoformat(),
                            "tz_name": tz_name,
                        })
                        _storage.log_user_event(user_id, "timezone_shift_forward", {
                            "alert_id": alert.get("id"),
                            "next_scheduled": next_occ.isoformat(),
                            "tz_name": tz_name,
                        })
                else:
                    if _is_repetition_terminal(alert, now_ref, user_prefs, include_today=True):
                        if _deactivate_repetition_terminal_alert(
                            _storage,
                            user_id,
                            alert['id'],
                            now_ref,
                            source="load_all_alerts_recompute",
                        ):
                            updated_alerts += 1
                    else:
                        log_system("scheduler", "next_occurrence_missing", {
                            "user_id": str(user_id),
                            "alert_id": alert.get("id"),
                            "alert_type": alert.get("type"),
                            "source": "load_all_alerts",
                        }, level="WARNING")

    logger.info(f"✅ Loaded {total_alerts} active alerts, updated {updated_alerts} schedules")


async def queue_single_alert(user_id, alert_id):
    """
    Updates the schedule state for a single alert.
    Call this after creating or modifying an alert.

    Args:
        user_id: User ID
        alert_id: Alert ID
    """
    global _storage

    if not _storage:
        return

    alert = _storage.get_alert_by_id(user_id, alert_id)
    if not alert or not alert.get('active', True):
        return

    user_prefs = _storage.get_user_prefs(user_id)
    now_ref = now_server_naive()
    if _is_fuzzy_daily_alert(alert):
        _sampled_days, next_occ, shifted = resolve_fuzzy_next_scheduled(
            alert,
            now_ref,
            user_prefs,
            record_history=False,
            history_source=None,
        )
    else:
        next_occ, shifted = compute_next_occurrence(alert, now_ref, user_prefs)
    if next_occ:
        _storage.update_alert_schedule_state(user_id, alert_id, next_scheduled=next_occ)
        if shifted:
            tz_name = None
            tz_block = user_prefs.get("timezone") if isinstance(user_prefs, dict) else None
            if isinstance(tz_block, dict):
                tz_name = tz_block.get("name")
            log_system("scheduler", "timezone_shift_forward", {
                "user_id": str(user_id),
                "alert_id": alert_id,
                "next_scheduled": next_occ.isoformat(),
                "tz_name": tz_name,
            })
            _storage.log_user_event(user_id, "timezone_shift_forward", {
                "alert_id": alert_id,
                "next_scheduled": next_occ.isoformat(),
                "tz_name": tz_name,
            })
        logger.info(f"✅ Alert {alert_id} scheduled for {next_occ}")
        return
    if _is_repetition_terminal(alert, now_ref, user_prefs, include_today=True):
        _deactivate_repetition_terminal_alert(
            _storage,
            user_id,
            alert_id,
            now_ref,
            source="queue_single_alert",
        )
    else:
        log_system("scheduler", "next_occurrence_missing", {
            "user_id": str(user_id),
            "alert_id": alert_id,
            "alert_type": alert.get("type"),
            "source": "queue_single_alert",
        }, level="WARNING")


async def remove_alert_from_queue(user_id, alert_id):
    """
    Called when an alert is deleted or deactivated.
    Clears any pending pre-alert tracking.

    Args:
        user_id: User ID
        alert_id: Alert ID
    """
    # Clear pre-alert tracking for this alert
    keys_to_remove = [
        k for k in scheduler_state.sent_pre_alerts.keys()
        if k[0] == user_id and k[1] == alert_id
    ]
    for key in keys_to_remove:
        del scheduler_state.sent_pre_alerts[key]

    # "always" mode: also clear the pending missed entry so a deleted alert
    # is not re-reported on the next restart (cleanup would happen in
    # handle_missed_alerts Step 4d anyway, but clearing here is immediate).
    if C.MISSED_ALERTS_NOTIFY_MODE == "always":
        scheduler_state.clear_pending_missed_alert(str(user_id), alert_id)

    logger.info(f"✅ Alert {alert_id} removed from queue")


# =============================================================================
# MAIN CHECK LOOP
# =============================================================================


async def check_due_alerts():
    """
    Main scheduled job that runs every SCHEDULER_INTERVAL_SECONDS.
    Checks all active alerts to see if any are due or have pre-alerts due.
    """
    global _app, _storage

    if not _app or not _storage:
        logger.warning("⚠️ Scheduler check skipped: not fully initialized")
        return

    bot = _app.bot
    now = now_server_naive()
    start_tick = time.monotonic()
    drift_seconds = None
    if scheduler_state.last_tick_time:
        drift_seconds = (
            (now - scheduler_state.last_tick_time).total_seconds()
            - C.SCHEDULER_INTERVAL_SECONDS
        )
    scheduler_state.last_tick_time = now

    all_users = _storage.get_all_users()
    users_checked = len(all_users)
    alerts_checked = 0
    due_sent = 0
    pre_sent = 0
    errors = 0

    for user_id in all_users:
        data = _storage.get_all_alerts(user_id) or {}
        user_prefs = _storage.get_user_prefs(user_id) if _storage else None
        alerts_all = data.get('alerts', []) or []
        alerts = [a for a in alerts_all if a.get('active', True)]
        alert_map = {a.get('id'): a for a in alerts_all if a.get('id')}
        postpone_items = data.get('postpone_queue', []) or []

        # Process postponed instances (ghost alerts)
        pp_pre, pp_due = await process_postpone_queue_for_user(
            bot, user_id, alert_map, postpone_items, now, _storage, scheduler_state.sent_pre_alerts
        )
        pre_sent += pp_pre
        due_sent += pp_due

        for alert in alerts:
            alert_id = alert.get('id', 'unknown')
            alerts_checked += 1

            try:
                # Check if snoozed
                snoozed_until_str = alert.get('snoozed_until')
                if snoozed_until_str:
                    try:
                        snoozed_until = datetime.fromisoformat(snoozed_until_str)
                        if now >= snoozed_until:
                            # Snooze expired, trigger (clear only on success)
                            sent = await _trigger_alert(
                                bot,
                                user_id,
                                alert,
                                C.ALERT_MSG_TYPE_MAIN,
                                _storage,
                                scheduler_state.sent_pre_alerts,
                                scheduled_time=snoozed_until,
                                clear_snooze=True,
                            )
                            if sent and C.MISSED_ALERTS_NOTIFY_MODE == "always":
                                scheduler_state.clear_pending_missed_alert(str(user_id), alert_id)
                            continue
                        # Still snoozed, skip
                        continue
                    except ValueError:
                        pass

                # Check for pre-alerts
                pre_sent += await check_pre_alerts(bot, user_id, alert, now, user_prefs=user_prefs)

                # Check if main alert is due
                if is_due(alert, now):
                    scheduled_time = _get_scheduled_time(alert, now, user_prefs)
                    sent = await _trigger_alert(
                        bot,
                        user_id,
                        alert,
                        C.ALERT_MSG_TYPE_MAIN,
                        _storage,
                        scheduler_state.sent_pre_alerts,
                        scheduled_time=scheduled_time,
                    )
                    if sent and C.MISSED_ALERTS_NOTIFY_MODE == "always":
                        scheduler_state.clear_pending_missed_alert(str(user_id), alert_id)
                    due_sent += 1

            except Exception as e:
                logger.error(f"❌ Error checking alert {alert_id}: {e}")
                errors += 1
                log_system("errors", "scheduler_alert_check_failed", {
                    "user_id": str(user_id),
                    "alert_id": alert_id,
                    "error": str(e),
                }, level="ERROR")

    # Persist pre-alert tracking changes from trigger_alert clearing
    scheduler_state.save_pre_alert_state()
    if C.MISSED_ALERTS_NOTIFY_MODE == "always":
        scheduler_state.save_pending_missed()

    duration_ms = int((time.monotonic() - start_tick) * 1000)
    log_system("scheduler", "tick", {
        "users": users_checked,
        "alerts_checked": alerts_checked,
        "due_sent": due_sent,
        "pre_alerts_sent": pre_sent,
        "duration_ms": duration_ms,
        "interval_seconds": C.SCHEDULER_INTERVAL_SECONDS,
        "drift_seconds": drift_seconds,
        "errors": errors,
    })
    threshold_ms = max(0, int(getattr(C, "SCHEDULER_TICK_SLOW_THRESHOLD_MS", 1000)))
    if duration_ms >= threshold_ms:
        log_system("scheduler", "scheduler_tick_slow", {
            "duration_ms": duration_ms,
            "threshold_ms": threshold_ms,
            "users": users_checked,
            "alerts_checked": alerts_checked,
            "due_sent": due_sent,
            "pre_alerts_sent": pre_sent,
            "errors": errors,
            "drift_seconds": drift_seconds,
        }, level="WARNING")


async def check_pre_alerts(bot, user_id, alert, now, user_prefs=None):
    """
    Checks if any pre-alerts for this alert should fire.

    Args:
        bot: Telegram bot instance
        user_id: User ID
        alert: Alert dict
        now: Current datetime
    """
    alert_id = alert.get('id')
    pre_alerts = alert.get('pre_alerts', [])

    if not pre_alerts:
        return 0

    # Get main trigger time
    next_scheduled_str = alert.get('next_scheduled')
    if not next_scheduled_str:
        return 0

    main_time = parse_iso_datetime(next_scheduled_str)
    if not main_time:
        return 0
    sent_count = 0

    for pa_str in pre_alerts:
        tracking_key = (str(user_id), alert_id, pa_str)

        # Skip if already sent for this occurrence
        if tracking_key in scheduler_state.sent_pre_alerts:
            sent_time = scheduler_state.sent_pre_alerts[tracking_key]
            # Clear old tracking if we're past the main trigger
            if now > main_time:
                del scheduler_state.sent_pre_alerts[tracking_key]
                scheduler_state.mark_dirty()
            continue

        pre_time, pre_alert_kind = resolve_pre_alert_fire_time(
            alert,
            pa_str,
            main_time,
            user_prefs=user_prefs,
        )
        if not pre_time:
            continue

        # Check if this pre-alert is due
        if is_pre_alert_due(alert, pa_str, now, user_prefs=user_prefs):
            sent_msg = await send_alert(
                bot, user_id, alert,
                storage=_storage,
                alert_type=C.ALERT_MSG_TYPE_PRE,
                pre_alert_str=pa_str,
                main_trigger_time=main_time,
                scheduled_time=pre_time,
                occurrence_time=main_time,
            )
            if sent_msg:
                scheduler_state.sent_pre_alerts[tracking_key] = now
                scheduler_state.mark_dirty()
                sent_count += 1
                if _storage:
                    _storage.log_user_event(user_id, "pre_alert_sent", {
                        "alert_id": alert_id,
                        "pre_alert": pa_str,
                        "pre_alert_kind": pre_alert_kind or "duration",
                        "main_time": main_time.isoformat(),
                        "sent_time": now.isoformat(),
                        "type": alert.get("type"),
                        "type_name": alert.get("type_name"),
                    })
                    log_system("scheduler", "pre_alert_sent", {
                        "user_id": str(user_id),
                        "alert_id": alert_id,
                        "pre_alert": pa_str,
                        "pre_alert_kind": pre_alert_kind or "duration",
                        "main_time": main_time.isoformat(),
                        "sent_time": now.isoformat(),
                        "type": alert.get("type"),
                    })
                logger.info(f"✅ Pre-alert ({pa_str}) sent for {alert_id}")
            else:
                logger.error(f"❌ Failed to send pre-alert ({pa_str}) for {alert_id}")
                if _storage:
                    _storage.log_user_event(user_id, "pre_alert_send_failed", {
                        "alert_id": alert_id,
                        "pre_alert": pa_str,
                        "pre_alert_kind": pre_alert_kind or "duration",
                        "main_time": main_time.isoformat(),
                        "attempt_time": now.isoformat(),
                        "type": alert.get("type"),
                        "type_name": alert.get("type_name"),
                    })
                    log_system("scheduler", "pre_alert_send_failed", {
                        "user_id": str(user_id),
                        "alert_id": alert_id,
                        "pre_alert": pa_str,
                        "pre_alert_kind": pre_alert_kind or "duration",
                        "main_time": main_time.isoformat(),
                        "attempt_time": now.isoformat(),
                        "type": alert.get("type"),
                    })
    scheduler_state.save_pre_alert_state()
    return sent_count


# =============================================================================
# MISSED ALERTS HANDLING (wrapper)
# =============================================================================


async def handle_missed_alerts():
    """Run missed-alert recovery through the coordinator-owned app and storage."""
    if not _app or not _storage:
        return

    await _handle_missed_alerts(_app.bot, _storage)
