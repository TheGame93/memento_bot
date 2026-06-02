import logging
import inspect
from datetime import timedelta

from modules import constants as C
from modules.ghost_utils import is_ghost_alert
from modules.scheduler_core.postpone import parse_iso_datetime
from modules.scheduler_mathlogic import is_overdue, resolve_pre_alert_fire_time
from modules.scheduler_messagelogic import send_missed_alerts_batch
from modules.systemlog import log_system, derive_startup_downtime_window
from modules.timezone_utils import (
    compute_next_occurrence,
    get_server_tz,
    now_server_naive,
    resolve_fuzzy_next_scheduled,
)
import modules.scheduler_core.state as scheduler_state

logger = logging.getLogger(__name__)


async def _call_send_missed_func(send_missed_func, bot, user_id, missed_list, storage):
    """Call missed-summary sender with backward-compatible storage kwarg handling."""
    try:
        signature = inspect.signature(send_missed_func)
        parameters = signature.parameters
        accepts_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()
        )
        if "storage" in parameters or accepts_kwargs:
            return await send_missed_func(bot, user_id, missed_list, storage=storage)
    except Exception:
        pass
    return await send_missed_func(bot, user_id, missed_list)


async def handle_missed_alerts(bot, storage, now=None, send_missed_func=None):
    """
    Scan all users for alerts and pre-alerts missed during the offline window and send batch summaries on startup.

    Pre-alert classification is bounded by derive_startup_downtime_window; candidates outside
    the window or with an unreliable window are logged as skipped, not notified.
    Missed due alerts advance the schedule: type-5 alerts are marked done; recurring types
    compute the next occurrence and consume one repetition count.
    Past-due postpone instances for inactive (snoozed) alerts are also included in the summary
    batch — their deadlines were missed during downtime, so they appear alongside normally-missed
    alerts. Ghost alerts and postpones for deleted alerts are excluded.
    Notifications are batched per user via send_missed_func (defaults to send_missed_alerts_batch).
    Post-send state is persisted according to MISSED_ALERTS_NOTIFY_MODE:
    'once' marks each pre-alert notified to suppress re-reporting on subsequent restarts;
    'always' records pending entries so missed alerts are re-reported until normally fired.
    """
    if not bot or not storage:
        return

    if now is None:
        now = now_server_naive()
    elif now.tzinfo is not None:
        now = now.astimezone(get_server_tz()).replace(tzinfo=None)

    offline_window = derive_startup_downtime_window(now_dt=now)
    offline_start = offline_window.get("window_start")
    offline_end = offline_window.get("window_end")
    offline_source = offline_window.get("source", "none")
    offline_reliable = bool(offline_window.get("is_reliable"))
    offline_reason_code = offline_window.get("reason_code", "unknown")
    offline_window_available = bool(offline_start and offline_end and offline_reliable)

    log_system("scheduler", "missed_pre_offline_window", {
        "window_start": offline_start.isoformat() if offline_start else None,
        "window_end": offline_end.isoformat() if offline_end else None,
        "source": offline_source,
        "is_reliable": offline_reliable,
        "reason_code": offline_reason_code,
        "instance_tag_current": offline_window.get("instance_tag_current"),
        "instance_tag_state": offline_window.get("instance_tag_state"),
        "identity_match": offline_window.get("identity_match"),
        "last_pid_alive": offline_window.get("last_pid_alive"),
    })

    # Collect missed alerts per user for batch notification
    # {user_id: [ {alert, missed_pre, missed_due, upcoming_pre, upcoming_due} ] }
    missed_by_user = {}

    all_users = storage.get_all_users()

    # ---------------------------------------------------------------------------
    # Step 4a: Build maps for stale-entry cleanup (once mode).
    # Fix: also build known_alert_ids_by_user so cleanup_notified_missed_pre
    # can activate condition 2 (detect deleted alerts — fringe case fix).
    # ---------------------------------------------------------------------------
    alert_last_triggered_map = {}
    known_alert_ids_by_user = {}
    for _uid in all_users:
        _uid_str = str(_uid)
        _data = storage.get_all_alerts(_uid) or {}
        _all_alerts = _data.get("alerts", [])
        known_alert_ids_by_user[_uid_str] = {
            a.get("id") for a in _all_alerts if a.get("id")
        }
        for _a in _all_alerts:
            lt_str = _a.get("last_triggered")
            if lt_str:
                lt_dt = parse_iso_datetime(lt_str)
                if lt_dt:
                    alert_last_triggered_map[(_uid_str, _a.get("id"))] = lt_dt

    if C.MISSED_ALERTS_NOTIFY_MODE == "once":
        scheduler_state.cleanup_notified_missed_pre(
            alert_last_triggered_map, known_alert_ids_by_user
        )

    for user_id in all_users:
        data = storage.get_all_alerts(user_id) or {}
        user_prefs = storage.get_user_prefs(user_id)
        alerts_all = data.get("alerts", []) or []
        alerts = [a for a in alerts_all if a.get("active", True)]
        if not alerts and not data.get("postpone_queue"):
            continue

        alerts_all_map = {a.get("id"): a for a in alerts_all if a.get("id")}
        alert_map = {a.get("id"): a for a in alerts if a.get("id")}
        postpone_items = data.get("postpone_queue", []) or []
        updates_made = False

        inactive_postpone_misses = {}  # alert_id -> missed entry dict

        # Expire postponed items for missing/inactive alerts
        for item in postpone_items:
            if item.get("status") != "pending":
                continue
            if item.get("alert_id") not in alert_map:
                storage.update_postpone_instance(user_id, item.get("id"), {
                    "status": "expired",
                    "expired_at": now.isoformat(),
                    "reason": "alert_inactive_or_missing",
                })
                storage.log_user_event(user_id, "postpone_expired", {
                    "postpone_id": item.get("id"),
                    "alert_id": item.get("alert_id"),
                    "reason": "alert_inactive_or_missing",
                })
                updates_made = True
                # Collect past-due postpones for inactive (not deleted, not ghost) alerts
                _pp_alert_id = item.get("alert_id")
                if _pp_alert_id in alerts_all_map:
                    _inactive_alert = alerts_all_map[_pp_alert_id]
                    _fire_at_dt = parse_iso_datetime(item.get("fire_at"))
                    if _fire_at_dt and _fire_at_dt <= now and not is_ghost_alert(_inactive_alert):
                        _pp_entry = inactive_postpone_misses.setdefault(_pp_alert_id, {
                            "alert": _inactive_alert,
                            "missed_pre": [],
                            "missed_due": [],
                            "upcoming_pre": [],
                            "upcoming_due": [],
                            "_missed_pre_keys": [],
                            "_occ_iso": None,
                        })
                        if item.get("kind") == "pre":
                            _pp_entry["missed_pre"].append(_fire_at_dt)
                        else:
                            _pp_entry["missed_due"].append(_fire_at_dt)

        # Index postponed items by alert_id
        postpone_by_alert = {}
        for item in postpone_items:
            if item.get("status") != "pending":
                continue
            alert_id = item.get("alert_id")
            if alert_id not in alert_map:
                continue
            postpone_by_alert.setdefault(alert_id, []).append(item)

        for alert in alerts:
            if is_ghost_alert(alert):
                for item in postpone_by_alert.get(alert.get("id"), []):
                    fire_at = parse_iso_datetime(item.get("fire_at"))
                    if fire_at and fire_at <= now:
                        storage.update_postpone_instance(user_id, item.get("id"), {
                            "status": "expired",
                            "expired_at": now.isoformat(),
                            "reason": "ghost_recovery_cleanup",
                        })
                        storage.log_user_event(user_id, "postpone_expired", {
                            "postpone_id": item.get("id"),
                            "alert_id": item.get("alert_id"),
                            "reason": "ghost_recovery_cleanup",
                        })
                        updates_made = True
                storage.mark_alert_done(user_id, alert["id"])
                continue

            overdue, missed_time = is_overdue(alert, now)

            # Determine the current scheduled occurrence
            current_occ = None
            next_scheduled_str = alert.get('next_scheduled')
            if next_scheduled_str:
                current_occ = parse_iso_datetime(next_scheduled_str)
                if not current_occ:
                    current_occ, _ = compute_next_occurrence(alert, now - timedelta(days=1), user_prefs)
            else:
                current_occ, _ = compute_next_occurrence(alert, now - timedelta(days=1), user_prefs)

            missed_pre = []
            upcoming_pre = []
            missed_due = []
            upcoming_due = []
            missed_pre_to_record = []  # [(pa_str, occ_iso)] — for "once" mode tracking
            occ_iso = None

            # Missed pre-alerts tied to the current scheduled occurrence
            if current_occ:
                occ_iso = current_occ.isoformat()
                created_at_str = alert.get("created_at")
                created_at_dt = parse_iso_datetime(created_at_str) if created_at_str else None
                for pa_str in alert.get('pre_alerts', []) or []:
                    pre_time, _pre_kind = resolve_pre_alert_fire_time(
                        alert,
                        pa_str,
                        current_occ,
                        user_prefs=user_prefs,
                    )
                    if not pre_time:
                        continue
                    if pre_time >= now:
                        upcoming_pre.append(pre_time)
                        continue

                    _uid_str = str(user_id)
                    _alert_id = alert.get("id")

                    if created_at_dt is not None and pre_time <= created_at_dt:
                        log_system("scheduler", "missed_pre_candidate_skipped", {
                            "user_id": _uid_str,
                            "alert_id": _alert_id,
                            "pre_alert": pa_str,
                            "occurrence": occ_iso,
                            "pre_time": pre_time.isoformat(),
                            "reason_code": "created_after_pre_time",
                        })
                        continue

                    if not offline_window_available:
                        log_system("scheduler", "missed_pre_candidate_skipped", {
                            "user_id": _uid_str,
                            "alert_id": _alert_id,
                            "pre_alert": pa_str,
                            "occurrence": occ_iso,
                            "pre_time": pre_time.isoformat(),
                            "reason_code": "missing_offline_window",
                            "window_source": offline_source,
                            "window_reason_code": offline_reason_code,
                            "window_reliable": offline_reliable,
                        })
                        continue

                    if pre_time < offline_start or pre_time > offline_end:
                        log_system("scheduler", "missed_pre_candidate_skipped", {
                            "user_id": _uid_str,
                            "alert_id": _alert_id,
                            "pre_alert": pa_str,
                            "occurrence": occ_iso,
                            "pre_time": pre_time.isoformat(),
                            "reason_code": "outside_offline_window",
                            "window_start": offline_start.isoformat(),
                            "window_end": offline_end.isoformat(),
                        })
                        continue

                    tracking_key = (_uid_str, _alert_id, pa_str)
                    if tracking_key in scheduler_state.sent_pre_alerts:
                        log_system("scheduler", "missed_pre_candidate_skipped", {
                            "user_id": _uid_str,
                            "alert_id": _alert_id,
                            "pre_alert": pa_str,
                            "occurrence": occ_iso,
                            "pre_time": pre_time.isoformat(),
                            "reason_code": "already_sent_pre_alert_state",
                        })
                        continue

                    # "once" mode: skip if already reported on a previous restart
                    if C.MISSED_ALERTS_NOTIFY_MODE == "once":
                        if scheduler_state.is_missed_pre_notified(
                                _uid_str, _alert_id, pa_str, occ_iso):
                            continue  # already reported — skip

                    missed_pre.append(pre_time)
                    missed_pre_to_record.append((pa_str, occ_iso))
                if not overdue:
                    upcoming_due.append(current_occ)

            # If due is missed, update schedule and compute next occurrence for recurring
            if overdue and missed_time:
                missed_due.append(missed_time)
                if alert.get('type') == 5:
                    storage.mark_alert_done(user_id, alert['id'])
                    upcoming_due = []
                    upcoming_pre = []
                else:
                    repetition_outcome = {
                        "ok": True,
                        "repetition": alert.get("repetition"),
                        "before": None,
                        "after": None,
                        "exhausted": False,
                    }
                    if alert.get("type") in C.REPETITION_SUPPORTED_TYPES:
                        if hasattr(storage, "consume_repetition_occurrence"):
                            consume_result = storage.consume_repetition_occurrence(
                                user_id,
                                alert.get("id"),
                                should_count=True,
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
                                "alert_id": alert.get("id"),
                                "alert_type": alert.get("type"),
                                "reason_code": repetition_outcome.get("reason_code", "storage_failure"),
                                "source": "missed_overdue",
                            }, level="WARNING")

                    repetition_exhausted = bool(
                        repetition_outcome.get("ok")
                        and repetition_outcome.get("exhausted")
                    )
                    if repetition_exhausted:
                        storage.update_alert_schedule_state(
                            user_id,
                            alert['id'],
                            last_triggered=now,
                        )
                        deactivated = storage.update_alert_fields(user_id, alert["id"], {
                            "active": False,
                            "next_scheduled": None,
                        })
                        if not deactivated:
                            log_system("scheduler", "repetition_exhaustion_deactivate_failed", {
                                "user_id": str(user_id),
                                "alert_id": alert.get("id"),
                                "source": "missed_overdue",
                            }, level="WARNING")
                        payload = {
                            "alert_id": alert.get("id"),
                            "alert_type": alert.get("type"),
                            "before": repetition_outcome.get("before"),
                            "after": repetition_outcome.get("after"),
                            "deactivated": bool(deactivated),
                            "source": "missed_overdue",
                        }
                        storage.log_user_event(user_id, "repetition_exhausted", payload)
                        log_system("scheduler", "repetition_exhausted", {
                            "user_id": str(user_id),
                            **payload,
                        })
                        upcoming_due = []
                        upcoming_pre = []
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
                        if is_fuzzy_daily:
                            last_fired_at = parse_iso_datetime(alert.get("last_triggered"))
                            _sampled_days, next_occ, shifted = resolve_fuzzy_next_scheduled(
                                alert_for_next,
                                now,
                                user_prefs,
                                last_fired_at=last_fired_at,
                                record_history=True,
                                history_source="missed",
                            )
                        else:
                            next_occ, shifted = compute_next_occurrence(alert_for_next, now, user_prefs)
                        if next_occ:
                            state_update_kwargs = {
                                "user_id": user_id,
                                "alert_id": alert['id'],
                                "last_triggered": now,
                                "next_scheduled": next_occ,
                            }
                            if is_fuzzy_daily:
                                state_update_kwargs["fuzzy_history"] = alert_for_next.get("fuzzy_history")
                            try:
                                storage.update_alert_schedule_state(**state_update_kwargs)
                            except TypeError:
                                state_update_kwargs.pop("fuzzy_history", None)
                                storage.update_alert_schedule_state(**state_update_kwargs)
                            if shifted:
                                tz_name = None
                                if isinstance(user_prefs, dict):
                                    tz_block = user_prefs.get("timezone")
                                    if isinstance(tz_block, dict):
                                        tz_name = tz_block.get("name")
                                log_system("scheduler", "timezone_shift_forward", {
                                    "user_id": str(user_id),
                                    "alert_id": alert.get("id"),
                                    "next_scheduled": next_occ.isoformat(),
                                    "tz_name": tz_name,
                                })
                                storage.log_user_event(user_id, "timezone_shift_forward", {
                                    "alert_id": alert.get("id"),
                                    "next_scheduled": next_occ.isoformat(),
                                    "tz_name": tz_name,
                                })
                        else:
                            log_system("scheduler", "next_occurrence_missing", {
                                "user_id": str(user_id),
                                "alert_id": alert.get("id"),
                                "alert_type": alert.get("type"),
                                "source": "missed_overdue",
                            }, level="WARNING")
                        upcoming_due = [next_occ] if next_occ else []
                        upcoming_pre = []
                        if next_occ:
                            for pa_str in alert.get('pre_alerts', []) or []:
                                pre_time, _pre_kind = resolve_pre_alert_fire_time(
                                    alert_for_next,
                                    pa_str,
                                    next_occ,
                                    user_prefs=user_prefs,
                                )
                                if not pre_time:
                                    continue
                                if pre_time >= now:
                                    upcoming_pre.append(pre_time)

            # Merge postponed instances for this alert
            for item in postpone_by_alert.get(alert.get("id"), []):
                fire_at = parse_iso_datetime(item.get("fire_at"))
                if not fire_at:
                    continue

                if fire_at < now:
                    if item.get("kind") == "pre":
                        missed_pre.append(fire_at)
                    else:
                        missed_due.append(fire_at)
                    storage.update_postpone_instance(user_id, item.get("id"), {
                        "status": "expired",
                        "expired_at": now.isoformat(),
                        "reason": "missed_offline",
                    })
                    updates_made = True
                else:
                    if item.get("kind") == "pre":
                        upcoming_pre.append(fire_at)
                    else:
                        upcoming_due.append(fire_at)

            # Include if any missed pre-alerts or missed due
            if missed_pre or missed_due:
                if user_id not in missed_by_user:
                    missed_by_user[user_id] = []
                missed_by_user[user_id].append({
                    "alert": alert,
                    "missed_pre": sorted(missed_pre),
                    "missed_due": sorted(missed_due),
                    "upcoming_pre": sorted(upcoming_pre),
                    "upcoming_due": sorted(upcoming_due),
                    "_missed_pre_keys": missed_pre_to_record,  # [(pa_str, occ_iso)] — internal
                    "_occ_iso": occ_iso,                        # str | None — internal
                })

        # Flush inactive-alert postpone misses into the summary batch
        for _pp_alert_id, _pp_entry in inactive_postpone_misses.items():
            _pp_entry["missed_pre"] = sorted(_pp_entry["missed_pre"])
            _pp_entry["missed_due"] = sorted(_pp_entry["missed_due"])
            if _pp_entry["missed_pre"] or _pp_entry["missed_due"]:
                missed_by_user.setdefault(user_id, []).append(_pp_entry)

        if updates_made:
            storage.cleanup_postpone_queue(user_id, now.isoformat())

    # ---------------------------------------------------------------------------
    # Step 4d: "always" mode — merge pending missed notifications from previous
    # restarts so they are re-reported until the alert fires normally.
    # ---------------------------------------------------------------------------
    if C.MISSED_ALERTS_NOTIFY_MODE == "always":
        for _uid in all_users:
            _uid_str = str(_uid)
            pending = scheduler_state.get_pending_missed_for_user(_uid_str)
            if not pending:
                continue
            _data = storage.get_all_alerts(_uid) or {}
            active_alert_ids = {
                a['id'] for a in _data.get('alerts', []) if a.get('active')
            }
            for alert_id, pentry in list(pending.items()):
                if alert_id not in active_alert_ids:
                    # Alert deleted or deactivated — remove stale pending entry
                    scheduler_state.clear_pending_missed_alert(_uid_str, alert_id)
                    continue
                # Skip if already freshly detected this startup (fresh detection takes priority)
                already_in = any(
                    item['alert']['id'] == alert_id
                    for item in missed_by_user.get(_uid, [])
                )
                if already_in:
                    continue
                # Re-add from pending for re-notification
                alert_dict = next(
                    (a for a in _data.get('alerts', []) if a['id'] == alert_id), None
                )
                if not alert_dict:
                    continue
                missed_pre_times = [
                    parse_iso_datetime(t)
                    for t in pentry.get("missed_pre_times", [])
                    if t
                ]
                missed_due_time = parse_iso_datetime(pentry.get("missed_due_time") or "")
                missed_by_user.setdefault(_uid, []).append({
                    "alert": alert_dict,
                    "missed_pre": [t for t in missed_pre_times if t],
                    "missed_due": [missed_due_time] if missed_due_time else [],
                    "upcoming_pre": [],
                    "upcoming_due": [],
                    "_missed_pre_keys": [],
                    "_occ_iso": pentry.get("occurrence"),
                })

    if send_missed_func is None:
        send_missed_func = send_missed_alerts_batch

    # Send batch notifications to each user
    total_missed = 0
    for user_id, missed_list in missed_by_user.items():
        total_missed += len(missed_list)
        msg = await _call_send_missed_func(
            send_missed_func,
            bot,
            int(user_id),
            missed_list,
            storage,
        )
        if msg:
            sent_time = now_server_naive()
            storage.log_user_event(user_id, "missed_alerts_summary_sent", {
                "count": len(missed_list),
                "alert_ids": [item.get("alert", {}).get("id") for item in missed_list],
                "sent_time": sent_time.isoformat(),
            })
            log_system("scheduler", "missed_alerts_summary_sent", {
                "user_id": str(user_id),
                "count": len(missed_list),
                "sent_time": sent_time.isoformat(),
            })

    # ---------------------------------------------------------------------------
    # Step 4e: Record state for future restarts (simplified — no double-rename;
    # send_missed_alerts_batch ignores unknown keys so _missed_pre_keys/_occ_iso
    # are safe to leave in the items during send, and popped here after).
    # ---------------------------------------------------------------------------
    for _uid, missed_list in missed_by_user.items():
        _uid_str = str(_uid)
        for item in missed_list:
            _alert_id = item['alert'].get('id')
            if not _alert_id:
                continue
            _pre_keys = item.pop("_missed_pre_keys", [])
            _occ_iso = item.pop("_occ_iso", None)

            if C.MISSED_ALERTS_NOTIFY_MODE == "once":
                for _pa_str, _key_occ_iso in _pre_keys:
                    scheduler_state.mark_missed_pre_notified(
                        _uid_str, _alert_id, _pa_str, _key_occ_iso, now
                    )

            elif C.MISSED_ALERTS_NOTIFY_MODE == "always":
                # Read existing pentry BEFORE overwriting it, to preserve data
                # for pending-sourced items (where _pre_keys is [] because
                # Step 4d sets _missed_pre_keys=[] for re-notified entries).
                _existing_pentry = scheduler_state.get_pending_missed_for_user(_uid_str).get(_alert_id, {})
                # Preserve missed_pre_strs from original pentry when freshly
                # detected set is empty (pending-sourced re-notification).
                _missed_pre_strs = [k[0] for k in _pre_keys] or _existing_pentry.get("missed_pre_strs", [])
                _missed_pre_times = [t.isoformat() for t in item.get("missed_pre", [])]
                _missed_due = item.get("missed_due", [])
                _missed_due_time_iso = _missed_due[0].isoformat() if _missed_due else None
                # Preserve first_notified from original pentry (not overwritten each restart).
                _first_notified = _existing_pentry.get("first_notified") or now.isoformat()
                scheduler_state.record_pending_missed(
                    _uid_str, _alert_id, _occ_iso,
                    _missed_pre_strs, _missed_pre_times, _missed_due_time_iso,
                    first_notified_iso=_first_notified,
                )

    if C.MISSED_ALERTS_NOTIFY_MODE == "once":
        scheduler_state.save_notified_missed_pre()
    elif C.MISSED_ALERTS_NOTIFY_MODE == "always":
        scheduler_state.save_pending_missed()

    if total_missed > 0:
        logger.info(f"⚠️ Handled {total_missed} missed alerts across {len(missed_by_user)} users")
    else:
        logger.info("✅ No missed alerts found")
