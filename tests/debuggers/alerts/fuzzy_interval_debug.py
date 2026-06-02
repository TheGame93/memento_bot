#!/usr/bin/env python3
import asyncio
import copy
import importlib
import json
import os
import sys
import tempfile
from datetime import datetime


def _find_debuggers_root(start_path):
    current = os.path.abspath(os.path.dirname(start_path))
    while True:
        if os.path.basename(current) == "debuggers" and os.path.isdir(os.path.join(current, "_lib")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.abspath(os.path.join(os.path.dirname(start_path), ".."))
        current = parent


DEBUGGERS_ROOT = _find_debuggers_root(__file__)
if DEBUGGERS_ROOT not in sys.path:
    sys.path.insert(0, DEBUGGERS_ROOT)

from _lib.harness import DebugHarness
from _lib.root import add_project_root_to_path
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "fuzzy_interval_debug"
FEATURE_TITLE = "Fuzzy Daily Interval"


def _parse_cli_args(args):
    """Return unknown CLI args so harness runs can flag unexpected tokens."""
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _check_defaults_and_schema(dbg, C, summary_flow):
    daily_payload = {
        "type": 7,
        "schedule": {"interval": 3, "time": "09:30"},
        "pre_alerts": [],
        "additional_info": "",
        "keep_me": "ok",
    }
    summary_flow.ensure_default_settings(daily_payload)

    fuzzy_payload = {
        "type": 7,
        "schedule": {
            "interval": 5,
            "time": "08:00",
            "interval_mode": "fuzzy",
            "fuzzy_mean": 20.0,
            "fuzzy_std": 3.0,
        },
        "pre_alerts": [],
        "additional_info": "",
    }
    summary_flow.ensure_default_settings(fuzzy_payload)

    weekly_payload = {
        "type": 3,
        "schedule": {"interval": 2, "time": "10:00"},
        "pre_alerts": [],
        "additional_info": "",
    }
    summary_flow.ensure_default_settings(weekly_payload)

    checks = {
        "constant_min_days": getattr(C, "FUZZY_INTERVAL_MIN_DAYS", None) == 1,
        "daily_missing_mode_defaults_fixed": daily_payload["schedule"].get("interval_mode") == "fixed",
        "daily_interval_kept": daily_payload["schedule"].get("interval") == 3,
        "daily_unrelated_field_untouched": daily_payload.get("keep_me") == "ok",
        "fuzzy_mode_preserved": fuzzy_payload["schedule"].get("interval_mode") == "fuzzy",
        "fuzzy_params_preserved": (
            fuzzy_payload["schedule"].get("fuzzy_mean") == 20.0
            and fuzzy_payload["schedule"].get("fuzzy_std") == 3.0
        ),
        "non_daily_no_interval_mode_injected": "interval_mode" not in weekly_payload["schedule"],
    }

    dbg.section("schema_defaults", {
        "checks": checks,
        "daily_schedule": dict(daily_payload.get("schedule") or {}),
        "fuzzy_schedule": dict(fuzzy_payload.get("schedule") or {}),
        "weekly_schedule": dict(weekly_payload.get("schedule") or {}),
    })
    if not all(checks.values()):
        dbg.problem("schema_defaults_failed", {"checks": checks})


def _check_atomic_schedule_state_update(dbg, StorageManager):
    with tempfile.TemporaryDirectory() as tmpdir:
        cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            storage = StorageManager(base_data_dir=os.path.join(tmpdir, "data"), admin_id=1)
            user_id = 1
            storage.setup_user_space(user_id)

            alert_id = storage.save_alert(user_id, {
                "title": "Fuzzy storage contract",
                "type": 7,
                "type_name": "Daily",
                "schedule": {
                    "interval": 1,
                    "interval_mode": "fuzzy",
                    "fuzzy_mean": 20.0,
                    "fuzzy_std": 3.0,
                    "time": "10:00",
                },
                "pre_alerts": [],
                "tags": [],
            })

            last_triggered = datetime(2026, 4, 10, 9, 0, 0)
            next_scheduled = datetime(2026, 4, 30, 10, 0, 0)
            history_entry = [{
                "recorded_at": "2026-04-10T09:00:00",
                "sampled_interval_days": 20,
                "actual_delta_days": 20,
                "mean": 20.0,
                "std": 3.0,
                "source": "due",
            }]

            updated = storage.update_alert_schedule_state(
                user_id,
                alert_id,
                last_triggered=last_triggered,
                next_scheduled=next_scheduled,
                fuzzy_history=history_entry,
            )
            stored = storage.get_alert_by_id(user_id, alert_id) or {}

            cleared = storage.update_alert_schedule_state(
                user_id,
                alert_id,
                fuzzy_history=None,
            )
            stored_after_clear = storage.get_alert_by_id(user_id, alert_id) or {}

            checks = {
                "alert_saved": bool(alert_id),
                "update_success": updated is True,
                "last_triggered_set": stored.get("last_triggered") == last_triggered.isoformat(),
                "next_scheduled_set": stored.get("next_scheduled") == next_scheduled.isoformat(),
                "history_set": stored.get("fuzzy_history") == history_entry,
                "clear_success": cleared is True,
                "history_cleared": "fuzzy_history" not in stored_after_clear,
                "schedule_untouched": (stored_after_clear.get("schedule") or {}).get("interval_mode") == "fuzzy",
            }

            dbg.section("atomic_schedule_state", {
                "checks": checks,
                "stored_before_clear": stored,
                "stored_after_clear": stored_after_clear,
            })
            if not all(checks.values()):
                dbg.problem("atomic_schedule_state_failed", {"checks": checks})
        finally:
            os.chdir(cwd)


def _check_save_alert_fuzzy_initial_persistence(dbg, StorageManager, storage_module):
    original_resolver = storage_module.resolve_fuzzy_next_scheduled
    resolver_calls = []

    def _fake_resolver(alert, reference_server_dt, _user_prefs, *, last_fired_at=None, record_history=False, history_source=None):
        resolver_calls.append({
            "title": alert.get("title"),
            "reference_server_dt": reference_server_dt,
            "last_fired_at": last_fired_at,
            "record_history": bool(record_history),
            "history_source": history_source,
        })
        title = alert.get("title")
        if title == "fuzzy-missing-next":
            return 9, datetime(2026, 5, 9, 10, 0, 0), False
        if title == "fuzzy-invalid-next":
            return 7, datetime(2026, 5, 7, 10, 0, 0), True
        return None, None, False

    with tempfile.TemporaryDirectory() as tmpdir:
        cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            storage_module.resolve_fuzzy_next_scheduled = _fake_resolver
            storage = StorageManager(base_data_dir=os.path.join(tmpdir, "data"), admin_id=1)
            user_id = 1
            storage.setup_user_space(user_id)

            sampled_payload = {
                "title": "fuzzy-preserve-next",
                "type": 7,
                "type_name": "Daily",
                "schedule": {
                    "interval_mode": "fuzzy",
                    "fuzzy_mean": 20.0,
                    "fuzzy_std": 3.0,
                    "interval": 1,
                    "time": "10:00",
                },
                "next_scheduled": "2026-05-15T10:00:00",
                "pre_alerts": [],
                "tags": [],
            }
            missing_payload = {
                "title": "fuzzy-missing-next",
                "type": 7,
                "type_name": "Daily",
                "schedule": {
                    "interval_mode": "fuzzy",
                    "fuzzy_mean": 20.0,
                    "fuzzy_std": 3.0,
                    "interval": 1,
                    "time": "10:00",
                },
                "_fuzzy_first_next": "2026-06-01T10:00:00",
                "pre_alerts": [],
                "tags": [],
            }
            invalid_payload = {
                "title": "fuzzy-invalid-next",
                "type": 7,
                "type_name": "Daily",
                "schedule": {
                    "interval_mode": "fuzzy",
                    "fuzzy_mean": 20.0,
                    "fuzzy_std": 3.0,
                    "interval": 1,
                    "time": "10:00",
                },
                "next_scheduled": "bad-iso",
                "pre_alerts": [],
                "tags": [],
            }

            sampled_id = storage.save_alert(user_id, sampled_payload)
            missing_id = storage.save_alert(user_id, missing_payload)
            invalid_id = storage.save_alert(user_id, invalid_payload)

            sampled_stored = storage.get_alert_by_id(user_id, sampled_id) or {}
            missing_stored = storage.get_alert_by_id(user_id, missing_id) or {}
            invalid_stored = storage.get_alert_by_id(user_id, invalid_id) or {}

            checks = {
                "sampled_preserved_without_resample": sampled_stored.get("next_scheduled") == "2026-05-15T10:00:00",
                "missing_next_resampled_once": missing_stored.get("next_scheduled") == "2026-05-09T10:00:00",
                "invalid_next_resampled_once": invalid_stored.get("next_scheduled") == "2026-05-07T10:00:00",
                "resolver_called_only_when_needed": sorted(call.get("title") for call in resolver_calls) == [
                    "fuzzy-invalid-next",
                    "fuzzy-missing-next",
                ],
                "resolver_history_disabled": all(
                    call.get("record_history") is False and call.get("history_source") is None
                    for call in resolver_calls
                ),
                "creation_does_not_append_history": (
                    "fuzzy_history" not in sampled_stored
                    and "fuzzy_history" not in missing_stored
                    and "fuzzy_history" not in invalid_stored
                ),
                "draft_helper_not_persisted": (
                    "_fuzzy_first_next" not in missing_payload
                    and "_fuzzy_first_next" not in missing_stored
                ),
                "draft_missing_payload_backfilled": missing_payload.get("next_scheduled") == "2026-05-09T10:00:00",
                "draft_invalid_payload_backfilled": invalid_payload.get("next_scheduled") == "2026-05-07T10:00:00",
            }
            dbg.section("save_alert_fuzzy_initial_persistence", {
                "checks": checks,
                "resolver_calls": resolver_calls,
                "sampled_stored": sampled_stored,
                "missing_stored": missing_stored,
                "invalid_stored": invalid_stored,
                "missing_payload_after_save": missing_payload,
                "invalid_payload_after_save": invalid_payload,
            })
            if not all(checks.values()):
                dbg.problem("save_alert_fuzzy_initial_persistence_failed", {"checks": checks})
        finally:
            storage_module.resolve_fuzzy_next_scheduled = original_resolver
            os.chdir(cwd)


def _check_sampler_behavior(dbg, scheduler_mathlogic):
    original_gauss = scheduler_mathlogic.random.gauss
    try:
        zero_std = scheduler_mathlogic.sample_fuzzy_interval(3.6, 0)

        sequence = iter([-2.2, 0.4, 2.49])
        scheduler_mathlogic.random.gauss = lambda _m, _s: next(sequence)
        retry_accept = scheduler_mathlogic.sample_fuzzy_interval(20, 3)

        scheduler_mathlogic.random.gauss = lambda _m, _s: -5.0
        fallback = scheduler_mathlogic.sample_fuzzy_interval(4.4, 1.0)

        invalid_floor = scheduler_mathlogic.sample_fuzzy_interval(-9, -2)

        checks = {
            "zero_std_deterministic_round": zero_std == 4,
            "reject_until_positive_accept": retry_accept == 2,
            "hard_fallback_after_rejections": fallback == 4,
            "invalid_inputs_floor_to_min": invalid_floor == 1,
        }
        dbg.section("sampler_behavior", {
            "checks": checks,
            "results": {
                "zero_std": zero_std,
                "retry_accept": retry_accept,
                "fallback": fallback,
                "invalid_floor": invalid_floor,
            },
        })
        if not all(checks.values()):
            dbg.problem("sampler_behavior_failed", {"checks": checks})
    finally:
        scheduler_mathlogic.random.gauss = original_gauss


def _check_resolver_behavior(dbg, timezone_utils, scheduler_mathlogic):
    original_sampler = scheduler_mathlogic.sample_fuzzy_interval
    try:
        # Server-mode candidate uses server-naive date/time and preserves sampled days.
        scheduler_mathlogic.sample_fuzzy_interval = lambda _mean, _std: 3
        server_alert = {
            "type": 7,
            "schedule": {"time": "10:00", "interval_mode": "fuzzy", "fuzzy_mean": 20, "fuzzy_std": 3},
            "repetition": {"mode": "forever"},
        }
        server_ref = datetime(2026, 4, 10, 12, 0, 0)
        sampled, next_dt, shifted = timezone_utils.resolve_fuzzy_next_scheduled(
            server_alert,
            server_ref,
            {"timezone_mode": "server"},
        )

        # User-mode DST-gap conversion should surface shifted=True.
        scheduler_mathlogic.sample_fuzzy_interval = lambda _mean, _std: 1
        user_alert = {
            "type": 7,
            "schedule": {"time": "02:30", "interval_mode": "fuzzy", "fuzzy_mean": 20, "fuzzy_std": 3},
            "repetition": {"mode": "forever"},
        }
        user_ref = datetime(2026, 3, 28, 12, 0, 0)
        user_prefs = {"timezone_mode": "user", "timezone": {"name": "Europe/Rome"}}
        sampled_user, next_user, shifted_user = timezone_utils.resolve_fuzzy_next_scheduled(
            user_alert,
            user_ref,
            user_prefs,
        )

        # Repetition rejection returns (None, None, shifted=False).
        scheduler_mathlogic.sample_fuzzy_interval = lambda _mean, _std: 1
        rejected_alert = {
            "type": 7,
            "schedule": {"time": "10:00", "interval_mode": "fuzzy", "fuzzy_mean": 20, "fuzzy_std": 3},
            "repetition": {"mode": "until_date", "until_date": "10/04/2026"},
        }
        rejected = timezone_utils.resolve_fuzzy_next_scheduled(
            rejected_alert,
            datetime(2026, 4, 10, 12, 0, 0),
            {"timezone_mode": "user", "timezone": {"name": "Europe/Rome"}},
        )

        # History append uses reference-last_fired delta (not future candidate delta).
        scheduler_mathlogic.sample_fuzzy_interval = lambda _mean, _std: 5
        history_alert = {
            "type": 7,
            "schedule": {"time": "10:00", "interval_mode": "fuzzy", "fuzzy_mean": 20, "fuzzy_std": 3},
            "repetition": {"mode": "forever"},
            "fuzzy_history": [],
        }
        history_ref = datetime(2026, 4, 20, 18, 0, 0)
        last_fired = datetime(2026, 4, 19, 6, 0, 0)
        sampled_hist, next_hist, shifted_hist = timezone_utils.resolve_fuzzy_next_scheduled(
            history_alert,
            history_ref,
            {"timezone_mode": "server"},
            last_fired_at=last_fired,
            record_history=True,
            history_source="due",
        )
        history_entry = (history_alert.get("fuzzy_history") or [{}])[-1]
        actual_delta = history_entry.get("actual_delta_days")
        future_delta = round((next_hist - history_ref).total_seconds() / 86400.0, 6) if next_hist else None

        checks = {
            "server_sampled_days": sampled == 3,
            "server_candidate": next_dt == datetime(2026, 4, 13, 10, 0, 0),
            "server_shift_false": shifted is False,
            "user_sampled_days": sampled_user == 1,
            "user_shifted_true": shifted_user is True,
            "user_candidate_exists": isinstance(next_user, datetime),
            "repetition_rejected_tuple": rejected == (None, None, False),
            "history_sampled_days": sampled_hist == 5,
            "history_shift_false": shifted_hist is False,
            "history_appended": len(history_alert.get("fuzzy_history") or []) == 1,
            "history_source_due": history_entry.get("source") == "due",
            "history_delta_from_last_fired": actual_delta == 1.5,
            "history_delta_not_from_candidate": actual_delta != future_delta,
        }
        dbg.section("resolver_behavior", {
            "checks": checks,
            "server_next": next_dt.isoformat(sep=" ") if isinstance(next_dt, datetime) else None,
            "user_next": next_user.isoformat(sep=" ") if isinstance(next_user, datetime) else None,
            "rejected": rejected,
            "history_entry": history_entry,
            "history_future_delta_days": future_delta,
        })
        if not all(checks.values()):
            dbg.problem("resolver_behavior_failed", {"checks": checks})
    finally:
        scheduler_mathlogic.sample_fuzzy_interval = original_sampler


def _check_stored_read_paths(dbg, timezone_utils, scheduler_mathlogic):
    fuzzy_alert = {
        "type": 7,
        "schedule": {"time": "10:00", "interval_mode": "fuzzy", "fuzzy_mean": 20, "fuzzy_std": 3},
        "next_scheduled": "2026-04-01T10:00:00",
    }
    ref = datetime(2026, 4, 10, 12, 0, 0)
    direct_next = scheduler_mathlogic.get_next_occurrence(fuzzy_alert, ref)
    compute_server_next, compute_server_shifted = timezone_utils.compute_next_occurrence(
        fuzzy_alert,
        ref,
        {"timezone_mode": "server"},
    )
    compute_user_next, compute_user_shifted = timezone_utils.compute_next_occurrence(
        fuzzy_alert,
        ref,
        {"timezone_mode": "user", "timezone": {"name": "Europe/Rome"}},
    )

    invalid_alert = {
        "type": 7,
        "schedule": {"time": "10:00", "interval_mode": "fuzzy"},
        "next_scheduled": "not-an-iso",
    }
    missing_alert = {
        "type": 7,
        "schedule": {"time": "10:00", "interval_mode": "fuzzy"},
    }

    invalid_direct = scheduler_mathlogic.get_next_occurrence(invalid_alert, ref)
    invalid_compute, invalid_shifted = timezone_utils.compute_next_occurrence(
        invalid_alert,
        ref,
        {"timezone_mode": "server"},
    )
    missing_direct = scheduler_mathlogic.get_next_occurrence(missing_alert, ref)
    missing_compute, missing_shifted = timezone_utils.compute_next_occurrence(
        missing_alert,
        ref,
        {"timezone_mode": "server"},
    )

    fixed_daily = {
        "type": 7,
        "schedule": {"time": "10:00", "interval": 1, "interval_mode": "fixed"},
    }
    fixed_next = scheduler_mathlogic.get_next_occurrence(fixed_daily, datetime(2026, 4, 10, 10, 5, 0))

    checks = {
        "direct_stored_past_visible": direct_next == datetime(2026, 4, 1, 10, 0, 0),
        "compute_server_stored_passthrough": compute_server_next == datetime(2026, 4, 1, 10, 0, 0),
        "compute_user_no_double_convert": compute_user_next == datetime(2026, 4, 1, 10, 0, 0),
        "stored_shift_flags_false": compute_server_shifted is False and compute_user_shifted is False,
        "invalid_stored_returns_none": invalid_direct is None and invalid_compute is None and invalid_shifted is False,
        "missing_stored_returns_none": missing_direct is None and missing_compute is None and missing_shifted is False,
        "fixed_daily_regression_strict_future": fixed_next == datetime(2026, 4, 11, 10, 0, 0),
    }
    dbg.section("stored_read_paths", {
        "checks": checks,
        "direct_next": direct_next.isoformat(sep=" ") if isinstance(direct_next, datetime) else None,
        "compute_server_next": compute_server_next.isoformat(sep=" ") if isinstance(compute_server_next, datetime) else None,
        "compute_user_next": compute_user_next.isoformat(sep=" ") if isinstance(compute_user_next, datetime) else None,
        "fixed_next": fixed_next.isoformat(sep=" ") if isinstance(fixed_next, datetime) else None,
    })
    if not all(checks.values()):
        dbg.problem("stored_read_paths_failed", {"checks": checks})


def _check_state_callback_routing(dbg, C, add_alert_handler, edit_alert_handler):
    def _state_handlers(conv_handler, state):
        try:
            return list((conv_handler.states or {}).get(state, []))
        except Exception:
            return []

    def _has_message_handler(conv_handler, state):
        for handler in _state_handlers(conv_handler, state):
            if handler.__class__.__name__ == "MessageHandler":
                return True
        return False

    def _has_callback_pattern(conv_handler, state, token):
        for handler in _state_handlers(conv_handler, state):
            if handler.__class__.__name__ != "CallbackQueryHandler":
                continue
            pattern_obj = getattr(handler, "pattern", None)
            if pattern_obj is None:
                continue
            pattern_text = getattr(pattern_obj, "pattern", str(pattern_obj))
            if token in str(pattern_text):
                return True
        return False

    checks = {
        "state_constants_present": (
            hasattr(C, "FUZZY_INTERVAL_MODE_CHOICE")
            and hasattr(C, "FUZZY_MEAN_STD_INPUT")
        ),
        "callback_constants_present": (
            isinstance(getattr(C, "CB_INTERVAL_FIXED", None), str)
            and isinstance(getattr(C, "CB_INTERVAL_FUZZY", None), str)
        ),
        "callback_constants_distinct": getattr(C, "CB_INTERVAL_FIXED", None) != getattr(C, "CB_INTERVAL_FUZZY", None),
        "add_has_mode_choice_state": bool(_state_handlers(add_alert_handler, C.FUZZY_INTERVAL_MODE_CHOICE)),
        "add_has_mean_std_state": bool(_state_handlers(add_alert_handler, C.FUZZY_MEAN_STD_INPUT)),
        "edit_has_mode_choice_state": bool(_state_handlers(edit_alert_handler, C.FUZZY_INTERVAL_MODE_CHOICE)),
        "edit_has_mean_std_state": bool(_state_handlers(edit_alert_handler, C.FUZZY_MEAN_STD_INPUT)),
        "add_mode_choice_fixed_pattern": _has_callback_pattern(add_alert_handler, C.FUZZY_INTERVAL_MODE_CHOICE, C.CB_INTERVAL_FIXED),
        "add_mode_choice_fuzzy_pattern": _has_callback_pattern(add_alert_handler, C.FUZZY_INTERVAL_MODE_CHOICE, C.CB_INTERVAL_FUZZY),
        "edit_mode_choice_fixed_pattern": _has_callback_pattern(edit_alert_handler, C.FUZZY_INTERVAL_MODE_CHOICE, C.CB_INTERVAL_FIXED),
        "edit_mode_choice_fuzzy_pattern": _has_callback_pattern(edit_alert_handler, C.FUZZY_INTERVAL_MODE_CHOICE, C.CB_INTERVAL_FUZZY),
        "add_mean_std_message_handler": _has_message_handler(add_alert_handler, C.FUZZY_MEAN_STD_INPUT),
        "edit_mean_std_message_handler": _has_message_handler(edit_alert_handler, C.FUZZY_MEAN_STD_INPUT),
    }
    dbg.section("state_callback_routing", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("state_callback_routing_failed", {"checks": checks})


def _check_display_preview_surfaces(dbg, summary_flow, info_text):
    original_compute = summary_flow.compute_next_occurrence
    try:
        summary_flow.compute_next_occurrence = (
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("compute_next_occurrence should not be used for fuzzy draft preview"))
        )

        fuzzy_payload = {
            "type": 7,
            "type_name": "Daily",
            "title": "Fuzzy preview",
            "schedule": {
                "interval_mode": "fuzzy",
                "fuzzy_mean": 19.6,
                "fuzzy_std": 2.4,
                "time": "10:00",
            },
            "next_scheduled": "2026-05-01T10:00:00",
            "pre_alerts": ["1d"],
            "tags": [],
            "additional_info": "",
        }

        interval_label = summary_flow.format_interval(fuzzy_payload)
        pre_alerts_label = summary_flow.format_pre_alerts(fuzzy_payload, user_prefs={"timezone_mode": "server"})
        summary_text = summary_flow.format_alert_summary(fuzzy_payload, user_prefs={"timezone_mode": "server"})
        detail_text = info_text.format_ia(fuzzy_payload, user_prefs={"timezone_mode": "server"})

        checks = {
            "summary_interval_fuzzy_label": interval_label == "Fuzzy (20±2) days",
            "summary_pre_alert_resolved": isinstance(pre_alerts_label, str) and pre_alerts_label.strip() != "None",
            "summary_contains_fuzzy_label": "Fuzzy (20±2) days" in summary_text,
            "detail_contains_fuzzy_label": "Fuzzy (20±2) days" in detail_text,
        }
        dbg.section("display_preview_surfaces", {
            "checks": checks,
            "interval_label": interval_label,
            "pre_alerts_label": pre_alerts_label,
            "summary_text": summary_text,
            "detail_text": detail_text,
        })
        if not all(checks.values()):
            dbg.problem("display_preview_surfaces_failed", {"checks": checks})
    except Exception as exc:
        dbg.problem("display_preview_surfaces_failed", {"error": str(exc)})
    finally:
        summary_flow.compute_next_occurrence = original_compute


def _check_trigger_alert_due_postpone_paths(dbg, C, scheduler_actions):
    class _TriggerStorageStub:
        def __init__(self):
            self.schedule_updates = []
            self.field_updates = []
            self.user_events = []
            self.consume_calls = []
            self.clear_snooze_calls = []

        def get_user_prefs(self, _user_id):
            return {"timezone_mode": "server"}

        def consume_repetition_occurrence(self, user_id, alert_id, should_count):
            self.consume_calls.append({
                "user_id": str(user_id),
                "alert_id": alert_id,
                "should_count": bool(should_count),
            })
            return {
                "ok": True,
                "found": True,
                "changed": False,
                "alert_type": 7,
                "repetition": {"mode": C.REPETITION_MODE_FOREVER},
                "before": None,
                "after": None,
                "exhausted": False,
                "should_count": bool(should_count),
            }

        def update_alert_schedule_state(
            self,
            user_id,
            alert_id,
            last_triggered=None,
            next_scheduled=None,
            snoozed_until=None,
            fuzzy_history=None,
        ):
            self.schedule_updates.append({
                "user_id": str(user_id),
                "alert_id": alert_id,
                "last_triggered": last_triggered,
                "next_scheduled": next_scheduled,
                "snoozed_until": snoozed_until,
                "fuzzy_history": fuzzy_history,
            })
            return True

        def update_alert_fields(self, user_id, alert_id, updates):
            self.field_updates.append({
                "user_id": str(user_id),
                "alert_id": alert_id,
                "updates": dict(updates or {}),
            })
            return True

        def clear_alert_snooze(self, user_id, alert_id):
            self.clear_snooze_calls.append({"user_id": str(user_id), "alert_id": alert_id})
            return True

        def log_user_event(self, user_id, event_type, payload=None):
            self.user_events.append({
                "user_id": str(user_id),
                "event_type": event_type,
                "payload": dict(payload or {}),
            })
            return True

    original_send_alert = scheduler_actions.send_alert
    original_resolver = scheduler_actions.resolve_fuzzy_next_scheduled
    original_compute = scheduler_actions.compute_next_occurrence
    original_log_system = scheduler_actions.log_system
    original_now = scheduler_actions.now_server_naive

    system_events = []
    resolver_calls = []
    due_next = datetime(2026, 4, 30, 10, 0, 0)
    postpone_next = datetime(2026, 5, 5, 10, 0, 0)

    async def _fake_send_alert(*_args, **_kwargs):
        return {"ok": True}

    def _fake_log_system(category, event_type, payload=None, level="INFO"):
        system_events.append({
            "category": category,
            "event_type": event_type,
            "payload": dict(payload or {}),
            "level": level,
        })

    def _fake_resolver(alert, reference_server_dt, _user_prefs, *, last_fired_at=None, record_history=False, history_source=None):
        resolver_calls.append({
            "alert_id": alert.get("id"),
            "reference_server_dt": reference_server_dt,
            "last_fired_at": last_fired_at,
            "record_history": bool(record_history),
            "history_source": history_source,
        })
        if history_source == "due":
            alert["fuzzy_history"] = [{"source": "due"}]
            return 21, due_next, False
        if history_source == "postpone":
            alert["fuzzy_history"] = [{"source": "postpone"}]
            return 14, postpone_next, True
        return None, None, False

    def _fail_compute(*_args, **_kwargs):
        raise AssertionError("compute_next_occurrence must not run for fuzzy due/postpone send path")

    try:
        scheduler_actions.send_alert = _fake_send_alert
        scheduler_actions.resolve_fuzzy_next_scheduled = _fake_resolver
        scheduler_actions.compute_next_occurrence = _fail_compute
        scheduler_actions.log_system = _fake_log_system
        scheduler_actions.now_server_naive = lambda: datetime(2026, 4, 20, 12, 0, 0)

        storage_due = _TriggerStorageStub()
        due_alert = {
            "id": "fuzzy_due",
            "type": 7,
            "type_name": "Daily",
            "schedule": {"interval_mode": "fuzzy", "fuzzy_mean": 20.0, "fuzzy_std": 3.0, "time": "10:00"},
            "repetition": {"mode": "forever"},
            "last_triggered": "2026-04-10T10:00:00",
            "active": True,
        }
        due_sent = asyncio.run(scheduler_actions.trigger_alert(
            object(),
            "1001",
            due_alert,
            C.ALERT_MSG_TYPE_MAIN,
            storage_due,
            {},
            scheduled_time=datetime(2026, 4, 20, 10, 0, 0),
        ))

        storage_postpone = _TriggerStorageStub()
        postponed_alert = {
            "id": "fuzzy_postpone",
            "type": 7,
            "type_name": "Daily",
            "schedule": {"interval_mode": "fuzzy", "fuzzy_mean": 20.0, "fuzzy_std": 3.0, "time": "10:00"},
            "repetition": {"mode": "forever"},
            "last_triggered": "2026-04-15T10:00:00",
            "active": True,
        }
        effective_fire = datetime(2026, 4, 22, 14, 30, 0)
        postponed_sent = asyncio.run(scheduler_actions.trigger_alert(
            object(),
            "1002",
            postponed_alert,
            C.ALERT_MSG_TYPE_MAIN,
            storage_postpone,
            {},
            scheduled_time=datetime(2026, 4, 21, 10, 0, 0),
            postpone_count=1,
            postpone_id="pp_fuzzy_1",
            effective_fire_time=effective_fire,
        ))

        due_call = next((x for x in resolver_calls if x.get("alert_id") == "fuzzy_due"), {})
        postponed_call = next((x for x in resolver_calls if x.get("alert_id") == "fuzzy_postpone"), {})
        due_update = storage_due.schedule_updates[-1] if storage_due.schedule_updates else {}
        postpone_update = storage_postpone.schedule_updates[-1] if storage_postpone.schedule_updates else {}
        due_alert_sent = next((e for e in storage_due.user_events if e.get("event_type") == "alert_sent"), {})
        postponed_alert_sent = next((e for e in storage_postpone.user_events if e.get("event_type") == "alert_sent"), {})
        postponed_shift_event = next((e for e in storage_postpone.user_events if e.get("event_type") == "timezone_shift_forward"), {})
        postponed_shift_system = next(
            (e for e in system_events if e.get("event_type") == "timezone_shift_forward" and e.get("payload", {}).get("alert_id") == "fuzzy_postpone"),
            {},
        )

        checks = {
            "due_sent_true": due_sent is True,
            "due_history_source": due_call.get("history_source") == "due",
            "due_reference_uses_scheduled_time": due_call.get("reference_server_dt") == datetime(2026, 4, 20, 10, 0, 0),
            "due_atomic_update_contains_history": due_update.get("fuzzy_history") == [{"source": "due"}],
            "due_next_scheduled_updated": due_update.get("next_scheduled") == due_next,
            "due_postpone_defaults_logged": (
                due_alert_sent.get("payload", {}).get("postpone_id") is None
                and due_alert_sent.get("payload", {}).get("effective_fire_time") is None
                and due_alert_sent.get("payload", {}).get("is_postponed") is False
            ),
            "postponed_sent_true": postponed_sent is True,
            "postponed_history_source": postponed_call.get("history_source") == "postpone",
            "postponed_reference_uses_effective_fire": postponed_call.get("reference_server_dt") == effective_fire,
            "postponed_atomic_update_contains_history": postpone_update.get("fuzzy_history") == [{"source": "postpone"}],
            "postponed_next_scheduled_updated": postpone_update.get("next_scheduled") == postpone_next,
            "postponed_shift_logged_user": postponed_shift_event.get("payload", {}).get("next_scheduled") == postpone_next.isoformat(),
            "postponed_shift_logged_system": postponed_shift_system.get("payload", {}).get("next_scheduled") == postpone_next.isoformat(),
            "postponed_payload_includes_context": (
                postponed_alert_sent.get("payload", {}).get("postpone_id") == "pp_fuzzy_1"
                and postponed_alert_sent.get("payload", {}).get("effective_fire_time") == effective_fire.isoformat()
                and postponed_alert_sent.get("payload", {}).get("is_postponed") is True
            ),
        }
        dbg.section("trigger_alert_due_postpone_paths", {
            "checks": checks,
            "resolver_calls": resolver_calls,
            "due_update": due_update,
            "postpone_update": postpone_update,
            "due_alert_sent": due_alert_sent,
            "postponed_alert_sent": postponed_alert_sent,
            "postponed_shift_event": postponed_shift_event,
            "postponed_shift_system": postponed_shift_system,
        })
        if not all(checks.values()):
            dbg.problem("trigger_alert_due_postpone_paths_failed", {"checks": checks})
    except Exception as exc:
        dbg.problem("trigger_alert_due_postpone_paths_failed", {"error": str(exc)})
    finally:
        scheduler_actions.send_alert = original_send_alert
        scheduler_actions.resolve_fuzzy_next_scheduled = original_resolver
        scheduler_actions.compute_next_occurrence = original_compute
        scheduler_actions.log_system = original_log_system
        scheduler_actions.now_server_naive = original_now


def _check_mark_alert_done_legacy_path(dbg, scheduler_actions):
    class _DoneStorageStub:
        def __init__(self, alert):
            self._alert = dict(alert)
            self.schedule_updates = []
            self.user_events = []
            self.consume_calls = 0

        def get_alert_by_id(self, _user_id, _alert_id):
            return dict(self._alert)

        def mark_alert_done(self, _user_id, _alert_id):
            return True, False

        def get_user_prefs(self, _user_id):
            return {"timezone_mode": "server"}

        def update_alert_schedule_state(self, user_id, alert_id, next_scheduled=None, fuzzy_history=None):
            self.schedule_updates.append({
                "user_id": str(user_id),
                "alert_id": alert_id,
                "next_scheduled": next_scheduled,
                "fuzzy_history": fuzzy_history,
            })
            return True

        def log_user_event(self, user_id, event_type, payload=None):
            self.user_events.append({
                "user_id": str(user_id),
                "event_type": event_type,
                "payload": dict(payload or {}),
            })
            return True

        def consume_repetition_occurrence(self, *_args, **_kwargs):
            self.consume_calls += 1
            return {"ok": False}

    original_resolver = scheduler_actions.resolve_fuzzy_next_scheduled
    original_compute = scheduler_actions.compute_next_occurrence
    original_log_system = scheduler_actions.log_system
    original_now = scheduler_actions.now_server_naive

    resolver_calls = []
    compute_calls = []
    system_events = []
    now_ref = datetime(2026, 4, 23, 9, 45, 0)
    fuzzy_next = datetime(2026, 5, 2, 10, 0, 0)
    fixed_next = datetime(2026, 4, 24, 10, 0, 0)

    def _fake_resolver(alert, reference_server_dt, _user_prefs, *, last_fired_at=None, record_history=False, history_source=None):
        resolver_calls.append({
            "alert_id": alert.get("id"),
            "reference_server_dt": reference_server_dt,
            "last_fired_at": last_fired_at,
            "record_history": bool(record_history),
            "history_source": history_source,
        })
        return 9, fuzzy_next, True

    def _fake_compute(alert, reference_server_dt, _user_prefs):
        compute_calls.append({
            "alert_id": alert.get("id"),
            "reference_server_dt": reference_server_dt,
        })
        return fixed_next, False

    def _fake_log_system(category, event_type, payload=None, level="INFO"):
        system_events.append({
            "category": category,
            "event_type": event_type,
            "payload": dict(payload or {}),
            "level": level,
        })

    try:
        scheduler_actions.resolve_fuzzy_next_scheduled = _fake_resolver
        scheduler_actions.compute_next_occurrence = _fake_compute
        scheduler_actions.log_system = _fake_log_system
        scheduler_actions.now_server_naive = lambda: now_ref

        fuzzy_storage = _DoneStorageStub({
            "id": "done_fuzzy",
            "type": 7,
            "schedule": {"interval_mode": "fuzzy", "fuzzy_mean": 20.0, "fuzzy_std": 3.0, "time": "10:00"},
            "repetition": {"mode": "count", "remaining": 2},
            "last_triggered": "2026-04-20T10:00:00",
        })
        fixed_storage = _DoneStorageStub({
            "id": "done_fixed",
            "type": 7,
            "schedule": {"interval_mode": "fixed", "interval": 1, "time": "10:00"},
            "repetition": {"mode": "forever"},
        })

        fuzzy_result = asyncio.run(scheduler_actions.mark_alert_done("2001", "done_fuzzy", fuzzy_storage))
        fixed_result = asyncio.run(scheduler_actions.mark_alert_done("2002", "done_fixed", fixed_storage))

        fuzzy_call = next((c for c in resolver_calls if c.get("alert_id") == "done_fuzzy"), {})
        fixed_call = next((c for c in compute_calls if c.get("alert_id") == "done_fixed"), {})
        fuzzy_update = fuzzy_storage.schedule_updates[-1] if fuzzy_storage.schedule_updates else {}
        fixed_update = fixed_storage.schedule_updates[-1] if fixed_storage.schedule_updates else {}
        fuzzy_shift_user = next((e for e in fuzzy_storage.user_events if e.get("event_type") == "timezone_shift_forward"), {})
        fuzzy_shift_system = next(
            (
                e for e in system_events
                if e.get("event_type") == "timezone_shift_forward"
                and e.get("payload", {}).get("alert_id") == "done_fuzzy"
            ),
            {},
        )

        checks = {
            "fuzzy_returns_next_occurrence": fuzzy_result == (True, False, fuzzy_next),
            "fuzzy_uses_resolver": fuzzy_call.get("reference_server_dt") == now_ref,
            "fuzzy_no_history_append": fuzzy_call.get("record_history") is False and fuzzy_call.get("history_source") is None,
            "fuzzy_does_not_use_compute": all(call.get("alert_id") != "done_fuzzy" for call in compute_calls),
            "fuzzy_schedule_update_without_history": fuzzy_update.get("next_scheduled") == fuzzy_next and fuzzy_update.get("fuzzy_history") is None,
            "fuzzy_shift_logged_user": fuzzy_shift_user.get("payload", {}).get("next_scheduled") == fuzzy_next.isoformat(),
            "fuzzy_shift_logged_system": fuzzy_shift_system.get("payload", {}).get("next_scheduled") == fuzzy_next.isoformat(),
            "fixed_still_uses_compute": fixed_call.get("reference_server_dt") == now_ref,
            "fixed_returns_next_occurrence": fixed_result == (True, False, fixed_next),
            "fixed_schedule_update": fixed_update.get("next_scheduled") == fixed_next,
            "no_repetition_consumed": fuzzy_storage.consume_calls == 0 and fixed_storage.consume_calls == 0,
        }
        dbg.section("mark_alert_done_legacy_path", {
            "checks": checks,
            "resolver_calls": resolver_calls,
            "compute_calls": compute_calls,
            "fuzzy_update": fuzzy_update,
            "fixed_update": fixed_update,
            "fuzzy_result": fuzzy_result,
            "fixed_result": fixed_result,
        })
        if not all(checks.values()):
            dbg.problem("mark_alert_done_legacy_path_failed", {"checks": checks})
    except Exception as exc:
        dbg.problem("mark_alert_done_legacy_path_failed", {"error": str(exc)})
    finally:
        scheduler_actions.resolve_fuzzy_next_scheduled = original_resolver
        scheduler_actions.compute_next_occurrence = original_compute
        scheduler_actions.log_system = original_log_system
        scheduler_actions.now_server_naive = original_now


def _check_activation_requeue_paths(dbg, C, scheduler_coordinator, scheduler_handlers, list_alerts):
    class _CoordinatorStorageStub:
        def __init__(self, alerts, alert_lookup, user_prefs):
            self.alerts = [dict(item) for item in alerts]
            self.alert_lookup = {str(k): dict(v) for k, v in (alert_lookup or {}).items()}
            self.user_prefs = dict(user_prefs or {})
            self.schedule_updates = []
            self.user_events = []
            self.field_updates = []

        def get_all_alerts(self, _user_id):
            return {"alerts": [dict(item) for item in self.alerts]}

        def get_user_prefs(self, _user_id):
            return dict(self.user_prefs)

        def update_alert_schedule_state(self, user_id, alert_id, next_scheduled=None, last_triggered=None, fuzzy_history=None):
            self.schedule_updates.append({
                "user_id": str(user_id),
                "alert_id": alert_id,
                "next_scheduled": next_scheduled,
                "last_triggered": last_triggered,
                "fuzzy_history": fuzzy_history,
            })
            if str(alert_id) in self.alert_lookup:
                current = dict(self.alert_lookup[str(alert_id)])
                if next_scheduled is not None:
                    current["next_scheduled"] = next_scheduled.isoformat()
                self.alert_lookup[str(alert_id)] = current
            return True

        def update_alert_fields(self, user_id, alert_id, updates):
            self.field_updates.append({
                "user_id": str(user_id),
                "alert_id": alert_id,
                "updates": dict(updates or {}),
            })
            return True

        def log_user_event(self, user_id, event_type, payload=None):
            self.user_events.append({
                "user_id": str(user_id),
                "event_type": event_type,
                "payload": dict(payload or {}),
            })
            return True

        def get_alert_by_id(self, _user_id, alert_id):
            return dict(self.alert_lookup.get(str(alert_id)) or {})

    class _ToggleStorageStub:
        def __init__(self, alert_states):
            self.alert_states = {
                str(alert_id): dict(payload or {})
                for alert_id, payload in (alert_states or {}).items()
            }
            self.toggle_calls = []
            self.user_events = []

        def toggle_alert(self, user_id, alert_id):
            key = str(alert_id)
            self.toggle_calls.append({"user_id": str(user_id), "alert_id": key})
            alert = self.alert_states.get(key)
            if not isinstance(alert, dict):
                return None
            new_status = not bool(alert.get("active", True))
            alert["active"] = new_status
            self.user_events.append({
                "user_id": str(user_id),
                "event_type": "alert_toggled",
                "payload": {"alert_id": key, "active": new_status},
            })
            if new_status and "snoozed_until" in alert:
                alert.pop("snoozed_until", None)
                self.user_events.append({
                    "user_id": str(user_id),
                    "event_type": "alert_snooze_cleared",
                    "payload": {
                        "alert_id": key,
                        "type": alert.get("type"),
                        "type_name": alert.get("type_name"),
                    },
                })
            return new_status

        def get_alert_by_id(self, _user_id, alert_id):
            alert = self.alert_states.get(str(alert_id))
            if not isinstance(alert, dict):
                return None
            payload = dict(alert)
            payload.setdefault("id", str(alert_id))
            return payload

        def get_user_prefs(self, _user_id):
            return {"timezone_mode": "server"}

    class _FakeMessage:
        def __init__(self):
            self.photo = []
            self.reply_markup = None

    class _FakeQuery:
        def __init__(self, data):
            self.data = data
            self.message = _FakeMessage()
            self.answer_calls = []

        async def answer(self, text=None, show_alert=False):
            self.answer_calls.append({"text": text, "show_alert": bool(show_alert)})

        async def edit_message_reply_markup(self, reply_markup=None):
            self.last_reply_markup = reply_markup

    class _FakeBot:
        def __init__(self):
            self.messages = []

        async def send_message(self, chat_id, text, parse_mode=None):
            self.messages.append({
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
            })

    class _FakeUpdate:
        def __init__(self, user_id, query):
            self.effective_user = type("User", (), {"id": user_id})()
            self.callback_query = query

    class _FakeContext:
        def __init__(self):
            self.user_data = {}
            self.bot = _FakeBot()
            self.bot_data = {}

    def _seed_runtime(context, storage):
        """Install runtime storage in context bot_data for handler-edge DI lookups."""

        from modules.shared.runtime_context import BotRuntime, set_bot_runtime

        set_bot_runtime(
            context.bot_data,
            BotRuntime(storage=storage, api_failure_tracker=None),
        )

    list_manage_handlers = list_alerts
    try:
        split_manage = importlib.import_module("modules.handlers.list_alerts.manage_actions")
        if getattr(list_alerts.handle_management, "__module__", "") == split_manage.__name__:
            list_manage_handlers = split_manage
    except Exception:
        pass

    original_now = scheduler_coordinator.now_server_naive
    original_resolver = scheduler_coordinator.resolve_fuzzy_next_scheduled
    original_compute = scheduler_coordinator.compute_next_occurrence
    original_log_system = scheduler_coordinator.log_system
    original_storage_global = getattr(scheduler_coordinator, "_storage", None)
    original_scheduler_queue_single = scheduler_handlers.queue_single_alert
    original_list_queue_single = list_manage_handlers.queue_single_alert
    original_list_resolve_ids = list_manage_handlers._resolve_ids
    original_list_is_detail = list_manage_handlers._message_is_detail_view
    original_list_refresh_alert_message = list_manage_handlers.refresh_alert_message
    original_mainbot = sys.modules.get("mainbot")

    now_ref = datetime(2026, 4, 24, 8, 0, 0)
    coordinator_events = []
    resolver_calls = []
    compute_calls = []
    scheduler_toggle_queue_calls = []
    list_toggle_queue_calls = []
    list_refresh_calls = []

    def _fake_log_system(category, event_type, payload=None, level="INFO"):
        coordinator_events.append({
            "category": category,
            "event_type": event_type,
            "payload": dict(payload or {}),
            "level": level,
        })

    def _fake_resolver(alert, reference_server_dt, _user_prefs, *, last_fired_at=None, record_history=False, history_source=None):
        resolver_calls.append({
            "alert_id": alert.get("id"),
            "reference_server_dt": reference_server_dt,
            "record_history": bool(record_history),
            "history_source": history_source,
            "last_fired_at": last_fired_at,
        })
        if alert.get("id") == "fuzzy_active":
            return 11, datetime(2026, 5, 5, 10, 0, 0), True
        if alert.get("id") == "q_fuzzy":
            return 7, datetime(2026, 5, 1, 10, 0, 0), True
        return 5, datetime(2026, 5, 2, 10, 0, 0), False

    def _fake_compute(alert, reference_server_dt, _user_prefs):
        compute_calls.append({
            "alert_id": alert.get("id"),
            "reference_server_dt": reference_server_dt,
        })
        if alert.get("id") == "fixed_active":
            return datetime(2026, 4, 25, 9, 0, 0), False
        if alert.get("id") == "q_fixed":
            return datetime(2026, 4, 26, 9, 0, 0), False
        return datetime(2026, 4, 27, 9, 0, 0), False

    async def _fake_scheduler_queue_single(user_id, alert_id):
        scheduler_toggle_queue_calls.append((str(user_id), str(alert_id)))

    async def _fake_list_queue_single(user_id, alert_id):
        list_toggle_queue_calls.append((str(user_id), str(alert_id)))

    async def _fake_refresh_alert_message(_query, user_id, alert_id, **_kwargs):
        list_refresh_calls.append((str(user_id), str(alert_id)))

    toggle_storage = _ToggleStorageStub({
        "shon": {
            "id": "shon",
            "type": 7,
            "type_name": "Daily",
            "active": False,
            "snoozed_until": "2026-04-25T09:30:00",
        },
        "shoff": {
            "id": "shoff",
            "type": 7,
            "type_name": "Daily",
            "active": True,
        },
        "lgon": {
            "id": "lgon",
            "type": 7,
            "type_name": "Daily",
            "active": False,
            "snoozed_until": "2026-04-25T10:30:00",
        },
        "lgoff": {
            "id": "lgoff",
            "type": 7,
            "type_name": "Daily",
            "active": True,
            "snoozed_until": "2026-04-26T07:45:00",
        },
    })
    fake_mainbot = type("MainbotStub", (), {"storage": toggle_storage})()

    try:
        scheduler_coordinator.now_server_naive = lambda: now_ref
        scheduler_coordinator.resolve_fuzzy_next_scheduled = _fake_resolver
        scheduler_coordinator.compute_next_occurrence = _fake_compute
        scheduler_coordinator.log_system = _fake_log_system

        reschedule_storage = _CoordinatorStorageStub(
            alerts=[
                {
                    "id": "fuzzy_active",
                    "type": 7,
                    "active": True,
                    "schedule": {"interval_mode": "fuzzy", "time": "10:00", "fuzzy_mean": 20.0, "fuzzy_std": 3.0},
                },
                {
                    "id": "fixed_active",
                    "type": 7,
                    "active": True,
                    "schedule": {"interval_mode": "fixed", "interval": 1, "time": "09:00"},
                },
                {
                    "id": "fuzzy_inactive",
                    "type": 7,
                    "active": False,
                    "schedule": {"interval_mode": "fuzzy", "time": "12:00", "fuzzy_mean": 20.0, "fuzzy_std": 3.0},
                },
            ],
            alert_lookup={
                "q_fuzzy": {
                    "id": "q_fuzzy",
                    "type": 7,
                    "active": True,
                    "schedule": {"interval_mode": "fuzzy", "time": "10:00", "fuzzy_mean": 20.0, "fuzzy_std": 3.0},
                    "next_scheduled": "2026-04-01T10:00:00",
                },
                "q_fixed": {
                    "id": "q_fixed",
                    "type": 7,
                    "active": True,
                    "schedule": {"interval_mode": "fixed", "interval": 1, "time": "09:00"},
                },
            },
            user_prefs={"timezone_mode": "server", "timezone": {"name": "Europe/Rome"}},
        )

        updated_count = scheduler_coordinator.reschedule_user_alerts("3001", reason="tz_change", storage=reschedule_storage)
        scheduler_coordinator._storage = reschedule_storage
        asyncio.run(scheduler_coordinator.queue_single_alert("3001", "q_fuzzy"))
        asyncio.run(scheduler_coordinator.queue_single_alert("3001", "q_fixed"))

        scheduler_handlers.queue_single_alert = _fake_scheduler_queue_single
        list_manage_handlers.queue_single_alert = _fake_list_queue_single
        list_manage_handlers._resolve_ids = lambda _update, _context: ("5001", "3001", {})
        list_manage_handlers._message_is_detail_view = lambda _message: False
        list_manage_handlers.refresh_alert_message = _fake_refresh_alert_message
        sys.modules["mainbot"] = fake_mainbot

        sh_context = _FakeContext()
        _seed_runtime(sh_context, toggle_storage)
        sh_query_on = _FakeQuery(f"{C.CB_ALERT_TOGGLE}shon")
        sh_query_on.message = None
        sh_update_on = _FakeUpdate(5001, sh_query_on)
        asyncio.run(scheduler_handlers.handle_alert_toggle(sh_update_on, sh_context))

        sh_query_off = _FakeQuery(f"{C.CB_ALERT_TOGGLE}shoff")
        sh_query_off.message = None
        sh_update_off = _FakeUpdate(5001, sh_query_off)
        asyncio.run(scheduler_handlers.handle_alert_toggle(sh_update_off, sh_context))

        list_context = _FakeContext()
        _seed_runtime(list_context, toggle_storage)
        list_update_on = _FakeUpdate(5001, _FakeQuery("manage_toggle_lgon"))
        asyncio.run(list_alerts.handle_management(list_update_on, list_context))
        list_update_off = _FakeUpdate(5001, _FakeQuery("manage_toggle_lgoff"))
        asyncio.run(list_alerts.handle_management(list_update_off, list_context))

        reschedule_updates = {item.get("alert_id"): item for item in reschedule_storage.schedule_updates}
        shift_events = [
            event for event in coordinator_events
            if event.get("event_type") == "timezone_shift_forward"
        ]

        checks = {
            "reschedule_updates_active_only": updated_count == 2,
            "reschedule_fuzzy_uses_resolver": any(
                call.get("alert_id") == "fuzzy_active"
                and call.get("reference_server_dt") == now_ref
                and call.get("record_history") is False
                and call.get("history_source") is None
                for call in resolver_calls
            ),
            "reschedule_fixed_uses_compute": any(
                call.get("alert_id") == "fixed_active"
                and call.get("reference_server_dt") == now_ref
                for call in compute_calls
            ),
            "reschedule_fuzzy_persisted": reschedule_updates.get("fuzzy_active", {}).get("next_scheduled") == datetime(2026, 5, 5, 10, 0, 0),
            "reschedule_shift_logged": any(
                event.get("payload", {}).get("alert_id") == "fuzzy_active"
                for event in shift_events
            ),
            "queue_single_fuzzy_uses_resolver": any(
                call.get("alert_id") == "q_fuzzy"
                and call.get("reference_server_dt") == now_ref
                and call.get("record_history") is False
                and call.get("history_source") is None
                for call in resolver_calls
            ),
            "queue_single_fixed_uses_compute": any(
                call.get("alert_id") == "q_fixed"
                and call.get("reference_server_dt") == now_ref
                for call in compute_calls
            ),
            "queue_single_fuzzy_persisted": reschedule_updates.get("q_fuzzy", {}).get("next_scheduled") == datetime(2026, 5, 1, 10, 0, 0),
            "queue_single_shift_logged": any(
                event.get("payload", {}).get("alert_id") == "q_fuzzy"
                for event in shift_events
            ),
            "scheduler_toggle_requeues_on_activation": scheduler_toggle_queue_calls == [("5001", "shon")],
            "scheduler_toggle_activation_clears_snooze": "snoozed_until" not in (toggle_storage.get_alert_by_id("5001", "shon") or {}),
            "list_toggle_requeues_on_activation": list_toggle_queue_calls == [("3001", "lgon")],
            "list_toggle_activation_clears_snooze": "snoozed_until" not in (toggle_storage.get_alert_by_id("3001", "lgon") or {}),
            "deactivation_keeps_existing_snooze": (toggle_storage.get_alert_by_id("3001", "lgoff") or {}).get("snoozed_until") == "2026-04-26T07:45:00",
            "snooze_clear_event_logged_for_activation": sum(
                1 for event in toggle_storage.user_events
                if event.get("event_type") == "alert_snooze_cleared"
                and event.get("payload", {}).get("alert_id") in {"shon", "lgon"}
            ) == 2,
            "list_toggle_refresh_runs": list_refresh_calls == [("3001", "lgon"), ("3001", "lgoff")],
        }
        dbg.section("activation_requeue_paths", {
            "checks": checks,
            "updated_count": updated_count,
            "resolver_calls": resolver_calls,
            "compute_calls": compute_calls,
            "schedule_updates": reschedule_storage.schedule_updates,
            "shift_events": shift_events,
            "scheduler_toggle_queue_calls": scheduler_toggle_queue_calls,
            "list_toggle_queue_calls": list_toggle_queue_calls,
            "list_refresh_calls": list_refresh_calls,
            "toggle_user_events": toggle_storage.user_events,
            "toggle_alert_states": toggle_storage.alert_states,
        })
        if not all(checks.values()):
            dbg.problem("activation_requeue_paths_failed", {"checks": checks})
    except Exception as exc:
        dbg.problem("activation_requeue_paths_failed", {"error": str(exc)})
    finally:
        scheduler_coordinator.now_server_naive = original_now
        scheduler_coordinator.resolve_fuzzy_next_scheduled = original_resolver
        scheduler_coordinator.compute_next_occurrence = original_compute
        scheduler_coordinator.log_system = original_log_system
        scheduler_coordinator._storage = original_storage_global
        scheduler_handlers.queue_single_alert = original_scheduler_queue_single
        list_manage_handlers.queue_single_alert = original_list_queue_single
        list_manage_handlers._resolve_ids = original_list_resolve_ids
        list_manage_handlers._message_is_detail_view = original_list_is_detail
        list_manage_handlers.refresh_alert_message = original_list_refresh_alert_message
        if original_mainbot is None:
            sys.modules.pop("mainbot", None)
        else:
            sys.modules["mainbot"] = original_mainbot


def _check_missed_recovery_fuzzy_branch(dbg, scheduler_missed):
    class _MissedStorageStub:
        def __init__(self):
            self.schedule_updates = []
            self.field_updates = []
            self.consume_calls = []
            self.user_events = []

        def get_all_users(self):
            return ["4001"]

        def get_all_alerts(self, _user_id):
            return {
                "alerts": [
                    {
                        "id": "fuzzy_due",
                        "type": 7,
                        "type_name": "Daily",
                        "active": True,
                        "schedule": {
                            "interval_mode": "fuzzy",
                            "fuzzy_mean": 20.0,
                            "fuzzy_std": 3.0,
                            "time": "10:00",
                        },
                        "repetition": {"mode": "forever"},
                        "next_scheduled": "2026-04-20T10:00:00",
                        "last_triggered": "2026-04-10T10:00:00",
                        "pre_alerts": [],
                    },
                    {
                        "id": "fuzzy_terminal",
                        "type": 7,
                        "type_name": "Daily",
                        "active": True,
                        "schedule": {
                            "interval_mode": "fuzzy",
                            "fuzzy_mean": 20.0,
                            "fuzzy_std": 3.0,
                            "time": "10:00",
                        },
                        "repetition": {"mode": "count", "count_remaining": 1},
                        "next_scheduled": "2026-04-19T10:00:00",
                        "last_triggered": "2026-04-08T10:00:00",
                        "pre_alerts": [],
                    },
                ],
                "postpone_queue": [],
            }

        def get_user_prefs(self, _user_id):
            return {"timezone_mode": "server", "timezone": {"name": "Europe/Rome"}}

        def consume_repetition_occurrence(self, user_id, alert_id, should_count):
            self.consume_calls.append({
                "user_id": str(user_id),
                "alert_id": str(alert_id),
                "should_count": bool(should_count),
            })
            if str(alert_id) == "fuzzy_terminal":
                return {
                    "ok": True,
                    "found": True,
                    "changed": True,
                    "alert_type": 7,
                    "repetition": {"mode": "count", "count_remaining": 0},
                    "before": {"mode": "count", "count_remaining": 1},
                    "after": {"mode": "count", "count_remaining": 0},
                    "exhausted": True,
                    "should_count": bool(should_count),
                }
            return {
                "ok": True,
                "found": True,
                "changed": False,
                "alert_type": 7,
                "repetition": {"mode": "forever"},
                "before": None,
                "after": None,
                "exhausted": False,
                "should_count": bool(should_count),
            }

        def update_alert_schedule_state(self, user_id, alert_id, last_triggered=None, next_scheduled=None, fuzzy_history=None):
            self.schedule_updates.append({
                "user_id": str(user_id),
                "alert_id": str(alert_id),
                "last_triggered": last_triggered,
                "next_scheduled": next_scheduled,
                "fuzzy_history": fuzzy_history,
            })
            return True

        def update_alert_fields(self, user_id, alert_id, updates):
            self.field_updates.append({
                "user_id": str(user_id),
                "alert_id": str(alert_id),
                "updates": dict(updates or {}),
            })
            return True

        def log_user_event(self, user_id, event_type, payload=None):
            self.user_events.append({
                "user_id": str(user_id),
                "event_type": event_type,
                "payload": dict(payload or {}),
            })
            return True

        def update_postpone_instance(self, *_args, **_kwargs):
            return True

        def cleanup_postpone_queue(self, *_args, **_kwargs):
            return True

        def mark_alert_done(self, *_args, **_kwargs):
            return True

    original_is_overdue = scheduler_missed.is_overdue
    original_resolver = scheduler_missed.resolve_fuzzy_next_scheduled
    original_compute = scheduler_missed.compute_next_occurrence
    original_log_system = scheduler_missed.log_system
    original_window = scheduler_missed.derive_startup_downtime_window
    original_now = scheduler_missed.now_server_naive

    resolver_calls = []
    compute_calls = []
    system_events = []
    now_ref = datetime(2026, 4, 21, 12, 0, 0)
    next_due = datetime(2026, 5, 3, 10, 0, 0)

    def _fake_is_overdue(alert, _now):
        if alert.get("id") == "fuzzy_due":
            return True, datetime(2026, 4, 20, 10, 0, 0)
        if alert.get("id") == "fuzzy_terminal":
            return True, datetime(2026, 4, 19, 10, 0, 0)
        return False, None

    def _fake_resolver(alert, reference_server_dt, _user_prefs, *, last_fired_at=None, record_history=False, history_source=None):
        resolver_calls.append({
            "alert_id": alert.get("id"),
            "reference_server_dt": reference_server_dt,
            "last_fired_at": last_fired_at,
            "record_history": bool(record_history),
            "history_source": history_source,
        })
        alert["fuzzy_history"] = [{"source": "missed"}]
        return 13, next_due, True

    def _fake_compute(alert, reference_server_dt, _user_prefs):
        compute_calls.append({
            "alert_id": alert.get("id"),
            "reference_server_dt": reference_server_dt,
        })
        return datetime(2026, 4, 22, 10, 0, 0), False

    def _fake_log_system(category, event_type, payload=None, level="INFO"):
        system_events.append({
            "category": category,
            "event_type": event_type,
            "payload": dict(payload or {}),
            "level": level,
        })

    async def _fake_send_missed(_bot, _user_id, _missed_list):
        return None

    try:
        scheduler_missed.is_overdue = _fake_is_overdue
        scheduler_missed.resolve_fuzzy_next_scheduled = _fake_resolver
        scheduler_missed.compute_next_occurrence = _fake_compute
        scheduler_missed.log_system = _fake_log_system
        scheduler_missed.now_server_naive = lambda: now_ref
        scheduler_missed.derive_startup_downtime_window = lambda now_dt: {
            "window_start": now_dt,
            "window_end": now_dt,
            "source": "test",
            "is_reliable": True,
            "reason_code": "ok",
            "instance_tag_current": None,
            "instance_tag_state": None,
            "identity_match": True,
            "last_pid_alive": False,
        }

        storage = _MissedStorageStub()
        asyncio.run(
            scheduler_missed.handle_missed_alerts(
                object(),
                storage,
                now=now_ref,
                send_missed_func=_fake_send_missed,
            )
        )

        due_resolver_call = next((c for c in resolver_calls if c.get("alert_id") == "fuzzy_due"), {})
        due_update = next((u for u in storage.schedule_updates if u.get("alert_id") == "fuzzy_due"), {})
        terminal_update = next((u for u in storage.schedule_updates if u.get("alert_id") == "fuzzy_terminal"), {})
        terminal_field_update = next((u for u in storage.field_updates if u.get("alert_id") == "fuzzy_terminal"), {})
        due_shift_user = next((e for e in storage.user_events if e.get("event_type") == "timezone_shift_forward"), {})
        due_shift_system = next(
            (
                e for e in system_events
                if e.get("event_type") == "timezone_shift_forward"
                and e.get("payload", {}).get("alert_id") == "fuzzy_due"
            ),
            {},
        )
        repetition_calls = {(c.get("alert_id"), c.get("should_count")) for c in storage.consume_calls}

        checks = {
            "missed_due_uses_fuzzy_resolver": due_resolver_call.get("reference_server_dt") == now_ref,
            "missed_history_recorded": due_resolver_call.get("record_history") is True and due_resolver_call.get("history_source") == "missed",
            "missed_atomic_update_contains_history": due_update.get("next_scheduled") == next_due and due_update.get("fuzzy_history") == [{"source": "missed"}],
            "missed_shift_logged_user": due_shift_user.get("payload", {}).get("next_scheduled") == next_due.isoformat(),
            "missed_shift_logged_system": due_shift_system.get("payload", {}).get("next_scheduled") == next_due.isoformat(),
            "repetition_consumed_for_overdue": repetition_calls == {("fuzzy_due", True), ("fuzzy_terminal", True)},
            "terminal_path_deactivates": terminal_update.get("last_triggered") == now_ref and terminal_field_update.get("updates") == {"active": False, "next_scheduled": None},
            "terminal_path_skips_resolver": all(call.get("alert_id") != "fuzzy_terminal" for call in resolver_calls),
            "fuzzy_missed_avoids_compute_path": all(call.get("alert_id") != "fuzzy_due" for call in compute_calls),
        }
        dbg.section("missed_recovery_fuzzy_branch", {
            "checks": checks,
            "resolver_calls": resolver_calls,
            "compute_calls": compute_calls,
            "schedule_updates": storage.schedule_updates,
            "field_updates": storage.field_updates,
            "consume_calls": storage.consume_calls,
            "system_events": system_events,
            "user_events": storage.user_events,
        })
        if not all(checks.values()):
            dbg.problem("missed_recovery_fuzzy_branch_failed", {"checks": checks})
    except Exception as exc:
        dbg.problem("missed_recovery_fuzzy_branch_failed", {"error": str(exc)})
    finally:
        scheduler_missed.is_overdue = original_is_overdue
        scheduler_missed.resolve_fuzzy_next_scheduled = original_resolver
        scheduler_missed.compute_next_occurrence = original_compute
        scheduler_missed.log_system = original_log_system
        scheduler_missed.derive_startup_downtime_window = original_window
        scheduler_missed.now_server_naive = original_now


def _check_startup_fuzzy_repair_guard(dbg, scheduler_coordinator):
    class _StartupStorageStub:
        def __init__(self):
            self.schedule_updates = []
            self.field_updates = []
            self.user_events = []
            self.alerts_by_user = {
                "7001": [
                    {
                        "id": "startup_fuzzy_missing",
                        "type": 7,
                        "active": True,
                        "schedule": {"interval_mode": "fuzzy", "fuzzy_mean": 20.0, "fuzzy_std": 3.0, "time": "10:00"},
                        "repetition": {"mode": "forever"},
                    },
                    {
                        "id": "startup_fuzzy_invalid",
                        "type": 7,
                        "active": True,
                        "schedule": {"interval_mode": "fuzzy", "fuzzy_mean": 20.0, "fuzzy_std": 3.0, "time": "10:00"},
                        "repetition": {"mode": "forever"},
                        "next_scheduled": "invalid-iso",
                    },
                    {
                        "id": "startup_fuzzy_past",
                        "type": 7,
                        "active": True,
                        "schedule": {"interval_mode": "fuzzy", "fuzzy_mean": 20.0, "fuzzy_std": 3.0, "time": "10:00"},
                        "repetition": {"mode": "forever"},
                        "next_scheduled": "2026-04-24T07:30:00",
                    },
                    {
                        "id": "startup_fuzzy_terminal",
                        "type": 7,
                        "active": True,
                        "schedule": {"interval_mode": "fuzzy", "fuzzy_mean": 20.0, "fuzzy_std": 3.0, "time": "10:00"},
                        "repetition": {"mode": "count", "count_remaining": 0},
                        "next_scheduled": "2026-04-24T08:00:00",
                    },
                    {
                        "id": "startup_fixed_missing",
                        "type": 7,
                        "active": True,
                        "schedule": {"interval_mode": "fixed", "interval": 1, "time": "09:00"},
                        "repetition": {"mode": "forever"},
                    },
                    {
                        "id": "startup_type2_negative",
                        "type": 2,
                        "active": True,
                        "schedule": {"ordinals": ["Last"], "weekdays": ["Mon"], "time": "10:00"},
                        "repetition": {"mode": "forever"},
                        "next_scheduled": "2026-04-28T10:00:00",
                    },
                ],
            }
            self.user_prefs = {"7001": {"timezone_mode": "server", "timezone": {"name": "Europe/Rome"}}}

        def get_all_active_alerts_all_users(self):
            return {
                uid: [dict(alert) for alert in alerts]
                for uid, alerts in self.alerts_by_user.items()
            }

        def get_user_prefs(self, user_id):
            return dict(self.user_prefs.get(str(user_id)) or {})

        def update_alert_schedule_state(self, user_id, alert_id, next_scheduled=None, last_triggered=None, fuzzy_history=None):
            self.schedule_updates.append({
                "user_id": str(user_id),
                "alert_id": str(alert_id),
                "next_scheduled": next_scheduled,
                "last_triggered": last_triggered,
                "fuzzy_history": fuzzy_history,
            })
            return True

        def update_alert_fields(self, user_id, alert_id, updates):
            self.field_updates.append({
                "user_id": str(user_id),
                "alert_id": str(alert_id),
                "updates": dict(updates or {}),
            })
            return True

        def log_user_event(self, user_id, event_type, payload=None):
            self.user_events.append({
                "user_id": str(user_id),
                "event_type": event_type,
                "payload": dict(payload or {}),
            })
            return True

    original_now = scheduler_coordinator.now_server_naive
    original_resolver = scheduler_coordinator.resolve_fuzzy_next_scheduled
    original_compute = scheduler_coordinator.compute_next_occurrence
    original_log_system = scheduler_coordinator.log_system
    original_storage = getattr(scheduler_coordinator, "_storage", None)

    resolver_calls = []
    compute_calls = []
    system_events = []
    now_ref = datetime(2026, 4, 24, 9, 0, 0)
    startup_storage = _StartupStorageStub()

    def _fake_resolver(alert, reference_server_dt, _user_prefs, *, last_fired_at=None, record_history=False, history_source=None):
        resolver_calls.append({
            "alert_id": alert.get("id"),
            "reference_server_dt": reference_server_dt,
            "record_history": bool(record_history),
            "history_source": history_source,
            "last_fired_at": last_fired_at,
        })
        alert_id = alert.get("id")
        if alert_id == "startup_fuzzy_missing":
            return 10, datetime(2026, 5, 4, 10, 0, 0), False
        if alert_id == "startup_fuzzy_invalid":
            return 11, datetime(2026, 5, 5, 10, 0, 0), True
        if alert_id == "startup_fuzzy_past":
            return 12, datetime(2026, 5, 6, 10, 0, 0), False
        if alert_id == "startup_fuzzy_terminal":
            return None, None, False
        return None, None, False

    def _fake_compute(alert, reference_server_dt, _user_prefs):
        compute_calls.append({
            "alert_id": alert.get("id"),
            "reference_server_dt": reference_server_dt,
        })
        if alert.get("id") == "startup_fixed_missing":
            return datetime(2026, 4, 25, 9, 0, 0), False
        if alert.get("id") == "startup_type2_negative":
            return datetime(2026, 4, 30, 10, 0, 0), False
        return datetime(2026, 4, 27, 9, 0, 0), False

    def _fake_log_system(category, event_type, payload=None, level="INFO"):
        system_events.append({
            "category": category,
            "event_type": event_type,
            "payload": dict(payload or {}),
            "level": level,
        })

    try:
        scheduler_coordinator.now_server_naive = lambda: now_ref
        scheduler_coordinator.resolve_fuzzy_next_scheduled = _fake_resolver
        scheduler_coordinator.compute_next_occurrence = _fake_compute
        scheduler_coordinator.log_system = _fake_log_system
        scheduler_coordinator._storage = startup_storage

        asyncio.run(scheduler_coordinator.load_all_alerts())

        updates_by_id = {item.get("alert_id"): item for item in startup_storage.schedule_updates}
        field_updates_by_id = {item.get("alert_id"): item for item in startup_storage.field_updates}
        user_shift_event = next((e for e in startup_storage.user_events if e.get("event_type") == "timezone_shift_forward"), {})
        system_shift_event = next(
            (
                e for e in system_events
                if e.get("event_type") == "timezone_shift_forward"
                and e.get("payload", {}).get("alert_id") == "startup_fuzzy_invalid"
            ),
            {},
        )
        resolver_ids = {call.get("alert_id") for call in resolver_calls}
        compute_ids = {call.get("alert_id") for call in compute_calls}

        checks = {
            "startup_fuzzy_missing_resampled": updates_by_id.get("startup_fuzzy_missing", {}).get("next_scheduled") == datetime(2026, 5, 4, 10, 0, 0),
            "startup_fuzzy_invalid_resampled": updates_by_id.get("startup_fuzzy_invalid", {}).get("next_scheduled") == datetime(2026, 5, 5, 10, 0, 0),
            "startup_fuzzy_past_resampled": updates_by_id.get("startup_fuzzy_past", {}).get("next_scheduled") == datetime(2026, 5, 6, 10, 0, 0),
            "startup_fuzzy_uses_resolver": {"startup_fuzzy_missing", "startup_fuzzy_invalid", "startup_fuzzy_past", "startup_fuzzy_terminal"}.issubset(resolver_ids),
            "startup_fuzzy_resolver_no_history": all(
                call.get("record_history") is False and call.get("history_source") is None
                for call in resolver_calls
            ),
            "startup_fuzzy_shift_logged_user": user_shift_event.get("payload", {}).get("alert_id") == "startup_fuzzy_invalid",
            "startup_fuzzy_shift_logged_system": system_shift_event.get("payload", {}).get("next_scheduled") == datetime(2026, 5, 5, 10, 0, 0).isoformat(),
            "startup_terminal_deactivated": (
                updates_by_id.get("startup_fuzzy_terminal", {}).get("last_triggered") == now_ref
                and field_updates_by_id.get("startup_fuzzy_terminal", {}).get("updates") == {"active": False, "next_scheduled": None}
            ),
            "startup_fixed_uses_compute": "startup_fixed_missing" in compute_ids,
            "startup_type2_revalidation_kept": updates_by_id.get("startup_type2_negative", {}).get("next_scheduled") == datetime(2026, 4, 30, 10, 0, 0),
            "startup_fuzzy_avoids_compute": not {"startup_fuzzy_missing", "startup_fuzzy_invalid", "startup_fuzzy_past", "startup_fuzzy_terminal"} & compute_ids,
        }
        dbg.section("startup_fuzzy_repair_guard", {
            "checks": checks,
            "resolver_calls": resolver_calls,
            "compute_calls": compute_calls,
            "schedule_updates": startup_storage.schedule_updates,
            "field_updates": startup_storage.field_updates,
            "user_events": startup_storage.user_events,
            "system_events": system_events,
        })
        if not all(checks.values()):
            dbg.problem("startup_fuzzy_repair_guard_failed", {"checks": checks})
    except Exception as exc:
        dbg.problem("startup_fuzzy_repair_guard_failed", {"error": str(exc)})
    finally:
        scheduler_coordinator.now_server_naive = original_now
        scheduler_coordinator.resolve_fuzzy_next_scheduled = original_resolver
        scheduler_coordinator.compute_next_occurrence = original_compute
        scheduler_coordinator.log_system = original_log_system
        scheduler_coordinator._storage = original_storage


def _check_edit_commit_fuzzy_semantics(dbg, edit_flow):
    original_compute = edit_flow.compute_next_occurrence
    original_resolver = edit_flow.resolve_fuzzy_next_scheduled
    resolver_calls = []
    compute_calls = []

    resolver_results = {
        "edit_a": (15, datetime(2026, 5, 25, 10, 0, 0), False),
        "edit_b": (12, datetime(2026, 5, 20, 10, 0, 0), True),
    }
    compute_results = {
        "edit_f": (datetime(2026, 4, 26, 10, 0, 0), False),
    }

    def _fake_resolver(alert, reference_server_dt, _user_prefs, *, last_fired_at=None, record_history=False, history_source=None):
        resolver_calls.append({
            "alert_id": alert.get("id"),
            "reference_server_dt": reference_server_dt,
            "last_fired_at": last_fired_at,
            "record_history": bool(record_history),
            "history_source": history_source,
        })
        return resolver_results.get(alert.get("id"), (None, None, False))

    def _fake_compute(alert, reference_server_dt, _user_prefs):
        compute_calls.append({
            "alert_id": alert.get("id"),
            "reference_server_dt": reference_server_dt,
        })
        return compute_results.get(alert.get("id"), (None, False))

    def _plan_for(temp_alert, original_alert, now_ref, user_prefs=None):
        return edit_flow._build_commit_plan(
            temp_alert,
            original_alert,
            now_ref,
            dict(user_prefs or {"timezone_mode": "server"}),
        )

    try:
        edit_flow.resolve_fuzzy_next_scheduled = _fake_resolver
        edit_flow.compute_next_occurrence = _fake_compute

        base_now = datetime(2026, 4, 24, 9, 0, 0)

        # Case A: fuzzy parameter change triggers re-sampling.
        original_a = {
            "id": "edit_a",
            "type": 7,
            "active": True,
            "schedule": {"interval_mode": "fuzzy", "fuzzy_mean": 20.0, "fuzzy_std": 3.0, "time": "10:00", "interval": 1},
            "next_scheduled": "2026-05-10T10:00:00",
        }
        temp_a = copy.deepcopy(original_a)
        temp_a["schedule"]["fuzzy_mean"] = 25.0
        plan_a = _plan_for(temp_a, original_a, base_now)

        # Case B: fixed -> fuzzy switch requires fresh sample.
        original_b = {
            "id": "edit_b",
            "type": 7,
            "active": True,
            "schedule": {"interval_mode": "fixed", "interval": 1, "time": "10:00"},
            "next_scheduled": "2026-05-10T10:00:00",
        }
        temp_b = {
            "id": "edit_b",
            "type": 7,
            "active": True,
            "schedule": {"interval_mode": "fuzzy", "interval": 1, "fuzzy_mean": 20.0, "fuzzy_std": 3.0, "time": "10:00"},
            "next_scheduled": "2026-05-10T10:00:00",
        }
        plan_b = _plan_for(temp_b, original_b, base_now)

        # Case C: fuzzy time-only change preserves sampled date.
        original_c = {
            "id": "edit_c",
            "type": 7,
            "active": True,
            "schedule": {"interval_mode": "fuzzy", "interval": 1, "fuzzy_mean": 20.0, "fuzzy_std": 3.0, "time": "10:00"},
            "next_scheduled": "2026-05-10T10:00:00",
        }
        temp_c = copy.deepcopy(original_c)
        temp_c["schedule"]["time"] = "08:30"
        plan_c = _plan_for(temp_c, original_c, datetime(2026, 5, 9, 9, 0, 0))

        # Case C2: timezone_mode=user keeps the sampled user-local date and applies local hour.
        user_prefs_ny = {
            "timezone_mode": "user",
            "timezone": {"name": "America/New_York"},
        }
        original_c_user = {
            "id": "edit_c_user",
            "type": 7,
            "active": True,
            "schedule": {"interval_mode": "fuzzy", "interval": 1, "fuzzy_mean": 20.0, "fuzzy_std": 3.0, "time": "10:00"},
            "next_scheduled": "2026-05-10T16:00:00",
        }
        temp_c_user = copy.deepcopy(original_c_user)
        temp_c_user["schedule"]["time"] = "12:00"
        plan_c_user = _plan_for(
            temp_c_user,
            original_c_user,
            datetime(2026, 5, 9, 9, 0, 0),
            user_prefs=user_prefs_ny,
        )
        user_tz = edit_flow.resolve_user_timezone(user_prefs_ny)
        original_c_user_local = edit_flow.to_user_naive_from_server(
            datetime.fromisoformat(original_c_user.get("next_scheduled")),
            user_tz,
        )
        plan_c_user_next = plan_c_user.get("next_scheduled")
        plan_c_user_local = (
            edit_flow.to_user_naive_from_server(plan_c_user_next, user_tz)
            if isinstance(plan_c_user_next, datetime)
            else None
        )

        # Case D: adjusted fuzzy timestamp moves one day forward when not future.
        original_d = {
            "id": "edit_d",
            "type": 7,
            "active": True,
            "schedule": {"interval_mode": "fuzzy", "interval": 1, "fuzzy_mean": 20.0, "fuzzy_std": 3.0, "time": "10:00"},
            "next_scheduled": "2026-05-10T10:00:00",
        }
        temp_d = copy.deepcopy(original_d)
        temp_d["schedule"]["time"] = "08:30"
        plan_d = _plan_for(temp_d, original_d, datetime(2026, 5, 10, 9, 0, 0))

        # Case E: no fuzzy-relevant schedule change preserves next_scheduled and avoids side effects.
        original_e = {
            "id": "edit_e",
            "type": 7,
            "active": True,
            "schedule": {"interval_mode": "fuzzy", "interval": 1, "fuzzy_mean": 20.0, "fuzzy_std": 3.0, "time": "10:00"},
            "next_scheduled": "2026-05-12T10:00:00",
        }
        temp_e = copy.deepcopy(original_e)
        temp_e["schedule"]["interval"] = 3
        plan_e = _plan_for(temp_e, original_e, base_now)

        # Case F: fuzzy -> fixed falls back to deterministic compute path.
        original_f = {
            "id": "edit_f",
            "type": 7,
            "active": True,
            "schedule": {"interval_mode": "fuzzy", "interval": 1, "fuzzy_mean": 20.0, "fuzzy_std": 3.0, "time": "10:00"},
            "next_scheduled": "2026-05-15T10:00:00",
            "fuzzy_history": [{"source": "due"}],
        }
        temp_f = copy.deepcopy(original_f)
        temp_f["schedule"] = {"interval_mode": "fixed", "interval": 2, "time": "10:00"}
        plan_f = _plan_for(temp_f, original_f, base_now)

        resolver_ids = [call.get("alert_id") for call in resolver_calls]
        compute_ids = [call.get("alert_id") for call in compute_calls]
        edit_a_call = next((c for c in resolver_calls if c.get("alert_id") == "edit_a"), {})
        edit_b_call = next((c for c in resolver_calls if c.get("alert_id") == "edit_b"), {})

        checks = {
            "params_change_resamples": plan_a.get("next_scheduled") == datetime(2026, 5, 25, 10, 0, 0),
            "params_change_uses_resolver_contract": (
                edit_a_call.get("reference_server_dt") == base_now
                and edit_a_call.get("record_history") is False
                and edit_a_call.get("history_source") is None
            ),
            "fixed_to_fuzzy_resamples": plan_b.get("next_scheduled") == datetime(2026, 5, 20, 10, 0, 0),
            "fixed_to_fuzzy_uses_resolver_contract": (
                edit_b_call.get("reference_server_dt") == base_now
                and edit_b_call.get("record_history") is False
                and edit_b_call.get("history_source") is None
            ),
            "time_only_preserves_date": plan_c.get("next_scheduled") == datetime(2026, 5, 10, 8, 30, 0),
            "time_only_user_preserves_local_wall_clock": (
                isinstance(plan_c_user_local, datetime)
                and plan_c_user_local.date() == original_c_user_local.date()
                and plan_c_user_local.hour == 12
                and plan_c_user_local.minute == 0
            ),
            "time_only_rolls_forward": plan_d.get("next_scheduled") == datetime(2026, 5, 11, 8, 30, 0),
            "time_only_no_resample": (
                "edit_c" not in resolver_ids
                and "edit_c_user" not in resolver_ids
                and "edit_d" not in resolver_ids
            ),
            "no_relevant_change_preserves_schedule": plan_e.get("next_scheduled") == datetime(2026, 5, 12, 10, 0, 0),
            "no_relevant_change_avoids_side_effects": plan_e.get("apply_schedule_side_effects") is False,
            "no_relevant_change_no_resolve_compute": "edit_e" not in resolver_ids and "edit_e" not in compute_ids,
            "fuzzy_to_fixed_uses_compute": "edit_f" in compute_ids and "edit_f" not in resolver_ids,
            "fuzzy_to_fixed_next_occurrence": plan_f.get("next_scheduled") == datetime(2026, 4, 26, 10, 0, 0),
            "fuzzy_to_fixed_preserves_history_field": "fuzzy_history" not in (plan_f.get("updates") or {}),
            "all_cases_no_schedule_compute_error": not any(
                p.get("schedule_compute_error")
                for p in (plan_a, plan_b, plan_c, plan_d, plan_e, plan_f)
            ),
        }
        dbg.section("edit_commit_fuzzy_semantics", {
            "checks": checks,
            "resolver_calls": resolver_calls,
            "compute_calls": compute_calls,
            "plan_a": plan_a,
            "plan_b": plan_b,
            "plan_c": plan_c,
            "plan_c_user": plan_c_user,
            "plan_c_user_local": plan_c_user_local.isoformat() if isinstance(plan_c_user_local, datetime) else None,
            "original_c_user_local": original_c_user_local.isoformat(),
            "plan_d": plan_d,
            "plan_e": plan_e,
            "plan_f": plan_f,
        })
        if not all(checks.values()):
            dbg.problem("edit_commit_fuzzy_semantics_failed", {"checks": checks})
    except Exception as exc:
        dbg.problem("edit_commit_fuzzy_semantics_failed", {"error": str(exc)})
    finally:
        edit_flow.compute_next_occurrence = original_compute
        edit_flow.resolve_fuzzy_next_scheduled = original_resolver


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})
        suppress_ptb_user_warning()
        dbg.run_meta({"project_root": ROOT_DIR})
        try:
            from modules import constants as C
            from modules import timezone_utils
            from modules.handlers.add_alert import add_alert_handler
            from modules.handlers.edit_flow.flow import edit_alert_handler
            from modules.handlers.edit_flow import flow as edit_flow
            from modules.handlers.add_flow import summary_flow
            from modules.handlers import list_alerts
            from modules.handlers import scheduler_handlers
            from modules.scheduler_core import coordinator as scheduler_coordinator
            from modules.scheduler_core import actions as scheduler_actions
            from modules.scheduler_core import missed as scheduler_missed
            from modules.ui.formatters import info_text
            from modules import scheduler_mathlogic
            from modules import storage as storage_module
            from modules.storage import StorageManager
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _check_state_callback_routing(dbg, C, add_alert_handler, edit_alert_handler)
        _check_resolver_behavior(dbg, timezone_utils, scheduler_mathlogic)
        _check_sampler_behavior(dbg, scheduler_mathlogic)
        _check_stored_read_paths(dbg, timezone_utils, scheduler_mathlogic)
        _check_trigger_alert_due_postpone_paths(dbg, C, scheduler_actions)
        _check_mark_alert_done_legacy_path(dbg, scheduler_actions)
        _check_activation_requeue_paths(
            dbg,
            C,
            scheduler_coordinator,
            scheduler_handlers,
            list_alerts,
        )
        _check_edit_commit_fuzzy_semantics(dbg, edit_flow)
        _check_startup_fuzzy_repair_guard(dbg, scheduler_coordinator)
        _check_missed_recovery_fuzzy_branch(dbg, scheduler_missed)
        _check_display_preview_surfaces(dbg, summary_flow, info_text)
        _check_defaults_and_schema(dbg, C, summary_flow)
        _check_atomic_schedule_state_update(dbg, StorageManager)
        _check_save_alert_fuzzy_initial_persistence(dbg, StorageManager, storage_module)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    state_routing_ok = not dbg.has_problem("state_callback_routing_failed")
    resolver_ok = not dbg.has_problem("resolver_behavior_failed")
    sampler_ok = not dbg.has_problem("sampler_behavior_failed")
    stored_read_ok = not dbg.has_problem("stored_read_paths_failed")
    trigger_due_postpone_ok = not dbg.has_problem("trigger_alert_due_postpone_paths_failed")
    mark_done_legacy_ok = not dbg.has_problem("mark_alert_done_legacy_path_failed")
    activation_requeue_ok = not dbg.has_problem("activation_requeue_paths_failed")
    edit_commit_ok = not dbg.has_problem("edit_commit_fuzzy_semantics_failed")
    startup_repair_ok = not dbg.has_problem("startup_fuzzy_repair_guard_failed")
    missed_recovery_ok = not dbg.has_problem("missed_recovery_fuzzy_branch_failed")
    display_preview_ok = not dbg.has_problem("display_preview_surfaces_failed")
    schema_ok = not dbg.has_problem("schema_defaults_failed")
    atomic_ok = not dbg.has_problem("atomic_schedule_state_failed")
    save_alert_initial_ok = not dbg.has_problem("save_alert_fuzzy_initial_persistence_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"state-callback-routing: {'OK' if state_routing_ok else 'FAIL'}",
        f"resolver-behavior: {'OK' if resolver_ok else 'FAIL'}",
        f"sampler-behavior: {'OK' if sampler_ok else 'FAIL'}",
        f"stored-read-paths: {'OK' if stored_read_ok else 'FAIL'}",
        f"trigger-alert-due-postpone: {'OK' if trigger_due_postpone_ok else 'FAIL'}",
        f"mark-alert-done-legacy: {'OK' if mark_done_legacy_ok else 'FAIL'}",
        f"activation-requeue-paths: {'OK' if activation_requeue_ok else 'FAIL'}",
        f"edit-commit-fuzzy-semantics: {'OK' if edit_commit_ok else 'FAIL'}",
        f"startup-fuzzy-repair-guard: {'OK' if startup_repair_ok else 'FAIL'}",
        f"missed-recovery-fuzzy-branch: {'OK' if missed_recovery_ok else 'FAIL'}",
        f"display-preview-surfaces: {'OK' if display_preview_ok else 'FAIL'}",
        f"schema-defaults: {'OK' if schema_ok else 'FAIL'}",
        f"atomic-schedule-state: {'OK' if atomic_ok else 'FAIL'}",
        f"save-alert-fuzzy-initial-persistence: {'OK' if save_alert_initial_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
