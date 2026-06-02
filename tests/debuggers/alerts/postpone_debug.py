#!/usr/bin/env python3
import contextlib
import io
import os
import sys
import tempfile
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch


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
from _lib.runtime import run_async

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "postpone_debug"
FEATURE_TITLE = "Postpone Queue"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _parse_pre_alert_silenced(parse_func, spec):
    err_buf = io.StringIO()
    with contextlib.redirect_stderr(err_buf):
        delta = parse_func(spec)
    return delta, err_buf.getvalue()


def _check_parse_samples(dbg, parse_pre_alert_string):
    samples = ["30m", "2h", "1d", "1w", "1mo", "bad"]
    parsed = {}
    captured_stderr = {}
    for sample in samples:
        delta, stderr_text = _parse_pre_alert_silenced(parse_pre_alert_string, sample)
        parsed[sample] = str(delta) if delta else None
        if stderr_text.strip():
            captured_stderr[sample] = stderr_text.strip().splitlines()
    dbg.section("parse_samples", {"samples": parsed, "captured_stderr": captured_stderr})

    if parsed.get("1mo") is None:
        dbg.problem("parse_month_failed", {"sample": "1mo", "parsed": parsed})
    if parsed.get("bad") is not None:
        dbg.problem("parse_invalid_should_fail", {"sample": "bad", "parsed": parsed.get("bad")})


def _check_callback_count_encoding(dbg, _parse_postpone_data, _build_postpone_callback):
    """Test that postpone_count survives callback encode → parse round-trip."""
    now = datetime.now()
    alert_id = "abc12345"

    # Old-style callback without count (backward compat)
    old_cb = _build_postpone_callback("menu", "due", alert_id, now, now)
    old_parsed = _parse_postpone_data(old_cb)

    # New-style callback with count
    new_cb = _build_postpone_callback("menu", "pre", alert_id, now, now, postpone_count=3)
    new_parsed = _parse_postpone_data(new_cb)

    # Set action with count
    set_cb = _build_postpone_callback("set", "due", alert_id, now, now, postpone_count=5)
    # Simulate what _build_postpone_options_keyboard does: pp_set_1h_{kind}_{id}_{ts}_{ts}[_{count}]
    # But _build_postpone_callback builds: pp_set_{kind}_{id}_{ts}_{ts}[_{count}]
    # The options keyboard inserts duration between set and kind, let's test the parser directly
    ts = str(int(now.timestamp()))
    options_cb_with_count = f"pp_set_1h_due_{alert_id}_{ts}_{ts}_7"
    options_parsed = _parse_postpone_data(options_cb_with_count)

    options_cb_no_count = f"pp_set_1h_due_{alert_id}_{ts}_{ts}"
    options_no_count_parsed = _parse_postpone_data(options_cb_no_count)

    custom_cb_with_count = f"pp_custom_pre_{alert_id}_{ts}_{ts}_4"
    custom_parsed = _parse_postpone_data(custom_cb_with_count)
    custom_cb_negative_count = f"pp_custom_due_{alert_id}_{ts}_{ts}_-2"
    custom_negative_parsed = _parse_postpone_data(custom_cb_negative_count)

    checks = {
        "old_callback_count_0": old_parsed is not None and old_parsed.get("postpone_count") == 0,
        "new_callback_count_3": new_parsed is not None and new_parsed.get("postpone_count") == 3,
        "options_callback_count_7": options_parsed is not None and options_parsed.get("postpone_count") == 7,
        "options_no_count_0": options_no_count_parsed is not None and options_no_count_parsed.get("postpone_count") == 0,
        "custom_callback_count_4": custom_parsed is not None and custom_parsed.get("postpone_count") == 4,
        "custom_negative_count_clamped": custom_negative_parsed is not None and custom_negative_parsed.get("postpone_count") == 0,
        "old_kind_correct": old_parsed is not None and old_parsed.get("kind") == "due",
        "new_kind_correct": new_parsed is not None and new_parsed.get("kind") == "pre",
        "callback_length_ok": len(options_cb_with_count) <= 64,
    }

    dbg.section("callback_count_encoding", {
        "old_cb": old_cb,
        "new_cb": new_cb,
        "options_cb": options_cb_with_count,
        "custom_negative_cb": custom_cb_negative_count,
        "checks": checks,
    })

    if not all(checks.values()):
        dbg.problem("callback_count_encoding_failed", {"checks": checks})


def _check_iso_parse(dbg, parse_iso):
    now = datetime.now()
    valid = parse_iso(now.isoformat())
    invalid = parse_iso("not-a-date")
    none_value = parse_iso(None)
    checks = {
        "valid_roundtrip": valid is not None and valid.isoformat() == now.isoformat(),
        "invalid_none": invalid is None,
        "none_none": none_value is None,
    }
    dbg.section("iso_parse_samples", {
        "samples": {
            "valid": valid.isoformat() if valid else None,
            "invalid": invalid.isoformat() if invalid else None,
            "none": none_value.isoformat() if none_value else None,
        },
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("parse_iso_failed", {"checks": checks})


def _check_notification_module_surface(dbg):
    """Ensure notification-action/context helpers remain directly importable."""
    checks = {
        "validate_postpone_callable": False,
        "parse_postpone_data_callable": False,
    }
    details = {}
    try:
        from modules.handlers.notification_actions import _validate_postpone

        checks["validate_postpone_callable"] = callable(_validate_postpone)
    except Exception as exc:  # pragma: no cover - debugger surface check
        details["validate_postpone_error"] = str(exc)

    try:
        from modules.handlers.notification_context import _parse_postpone_data

        checks["parse_postpone_data_callable"] = callable(_parse_postpone_data)
    except Exception as exc:  # pragma: no cover - debugger surface check
        details["parse_postpone_data_error"] = str(exc)

    dbg.section("notification_module_surface", {"checks": checks, "details": details})
    if not all(checks.values()):
        dbg.problem("notification_module_surface_failed", {"checks": checks, "details": details})


async def _check_custom_postpone_expression_and_context(
    dbg,
    _resolve_custom_postpone_fire_at,
    handle_custom_postpone_input,
):
    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    now_ref = datetime(2026, 3, 2, 9, 0, 0)
    due_ref = datetime(2026, 3, 2, 9, 20, 0)

    accepted = {
        "token_30m": _resolve_custom_postpone_fire_at(
            "30m",
            now_server_dt=now_ref,
            user_prefs={},
            kind="due",
            occurrence_time=None,
        ),
        "natural_tomorrow": _resolve_custom_postpone_fire_at(
            "tomorrow 08:00",
            now_server_dt=now_ref,
            user_prefs={},
            kind="due",
            occurrence_time=None,
        ),
        "absolute_partial": _resolve_custom_postpone_fire_at(
            "5/3",
            now_server_dt=now_ref,
            user_prefs={},
            kind="due",
            occurrence_time=None,
        ),
        "absolute_full": _resolve_custom_postpone_fire_at(
            "05/03/2026 14:30",
            now_server_dt=now_ref,
            user_prefs={},
            kind="due",
            occurrence_time=None,
        ),
    }
    rejected = {
        "not_future": _resolve_custom_postpone_fire_at(
            "today at 09:00",
            now_server_dt=now_ref,
            user_prefs={},
            kind="due",
            occurrence_time=None,
        ),
        "not_before_due": _resolve_custom_postpone_fire_at(
            "today at 09:30",
            now_server_dt=now_ref,
            user_prefs={},
            kind="pre",
            occurrence_time=due_ref,
        ),
    }

    helper_checks = {
        "token_accepted": accepted["token_30m"][0] == datetime(2026, 3, 2, 9, 30, 0),
        "natural_accepted": accepted["natural_tomorrow"][0] == datetime(2026, 3, 3, 8, 0, 0),
        "absolute_partial_accepted": accepted["absolute_partial"][0] == datetime(2026, 3, 5, 9, 0, 0),
        "absolute_full_accepted": accepted["absolute_full"][0] == datetime(2026, 3, 5, 14, 30, 0),
        "not_future_reason": rejected["not_future"][1] == "not_future",
        "not_before_due_reason": rejected["not_before_due"][1] == "not_before_due",
    }

    class _DummyMessage:
        def __init__(self, text):
            self.text = text
            self.replies = []

        async def reply_text(self, text, parse_mode=None, reply_markup=None):
            self.replies.append({
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            })
            return self

    class _DummyBot:
        def __init__(self):
            self.edits = []

        async def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None):
            self.edits.append({
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": reply_markup,
            })

    class _DummyStorage:
        def __init__(self, alert):
            self._alert = dict(alert)
            self._queue = []

        def get_alert_by_id(self, user_id, alert_id):
            if str(alert_id) == str(self._alert.get("id")):
                return dict(self._alert)
            return None

        def get_user_prefs(self, user_id):
            return {}

        def get_postpone_queue(self, user_id):
            return list(self._queue)

        def update_postpone_instance(self, user_id, instance_id, updates):
            for item in self._queue:
                if item.get("id") == instance_id:
                    item.update(dict(updates or {}))
                    return True
            return False

        def add_postpone_instance(self, user_id, instance):
            self._queue.append(dict(instance or {}))

    async def _run_case(*, text, kind, occurrence_time, force_validate_ok=False):
        alert = {
            "id": "pp_custom_1",
            "title": "Postpone target",
            "type": 5,
            "type_name": "Once",
            "schedule": {"date": "03/03/2026", "time": "10:00"},
            "pre_alerts": [],
        }
        storage = _DummyStorage(alert)
        user_data = {
            "expecting_custom_postpone": True,
            "postpone_alert_id": alert["id"],
            "postpone_kind": kind,
            "postpone_original_time": now_ref.isoformat(),
            "postpone_occurrence_time": occurrence_time.isoformat() if occurrence_time else None,
            "postpone_message_id": 777,
            "postpone_count": 0,
        }
        context = SimpleNamespace(user_data=user_data, bot=_DummyBot())
        context.bot_data = {}
        set_bot_runtime(
            context.bot_data,
            BotRuntime(storage=storage, api_failure_tracker=None),
        )
        message = _DummyMessage(text)
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=12345),
            message=message,
        )

        with patch("modules.handlers.scheduler_handlers.now_server_naive", return_value=now_ref):
            if force_validate_ok:
                with patch("modules.handlers.scheduler_handlers._validate_postpone", return_value=(True, None)):
                    await handle_custom_postpone_input(update, context)
            else:
                await handle_custom_postpone_input(update, context)

        return {
            "context": context,
            "message": message,
            "storage": storage,
        }

    cancel_case = await _run_case(text="cancel", kind="due", occurrence_time=None)
    success_case = await _run_case(
        text="30m",
        kind="due",
        occurrence_time=None,
        force_validate_ok=True,
    )
    reject_case = await _run_case(text="today at 09:30", kind="pre", occurrence_time=due_ref)

    cancel_keys = cancel_case["context"].user_data.keys()
    success_keys = success_case["context"].user_data.keys()
    reject_keys = reject_case["context"].user_data.keys()

    flow_checks = {
        "cancel_context_cleared": "expecting_custom_postpone" not in cancel_keys,
        "cancel_keyboard_restored": len(cancel_case["context"].bot.edits) == 1,
        "success_context_cleared": "expecting_custom_postpone" not in success_keys,
        "success_keyboard_restored": len(success_case["context"].bot.edits) == 1,
        "success_queue_written": len(success_case["storage"].get_postpone_queue("12345")) == 1,
        "boundary_reject_keeps_context": "expecting_custom_postpone" in reject_keys,
        "boundary_reject_no_queue_write": len(reject_case["storage"].get_postpone_queue("12345")) == 0,
        "boundary_reject_no_keyboard_restore": len(reject_case["context"].bot.edits) == 0,
        "boundary_reject_message": any(
            "before the due time" in (reply.get("text") or "")
            for reply in reject_case["message"].replies
        ),
    }

    checks = {}
    checks.update(helper_checks)
    checks.update(flow_checks)

    dbg.section("custom_postpone_expression_and_context", {
        "helper_checks": helper_checks,
        "flow_checks": flow_checks,
        "cancel_replies": cancel_case["message"].replies,
        "success_replies": success_case["message"].replies,
        "reject_replies": reject_case["message"].replies,
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("custom_postpone_expression_and_context_failed", {"checks": checks})


async def _check_prealert_info_handler(dbg, handle_prealert_info):
    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    now = datetime.now().replace(second=0, microsecond=0)
    ts = str(int(now.timestamp()))
    postpone_count = 2
    callback_data = f"preinfo_md1_{ts}_{ts}_{postpone_count}"
    alert = {
        "id": "md1",
        "title": "Unsafe *[title",
        "type": 3,
        "type_name": "Weekly",
        "active": True,
        "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "10:00"},
        "pre_alerts": ["30m"],
        "tags": [],
        "created_at": now.isoformat(),
        "next_scheduled": now.isoformat(),
    }

    class _FakeStorage:
        def __init__(self):
            self.events = []

        def get_alert_by_id(self, user_id, alert_id):
            if str(user_id) == "777" and alert_id == alert.get("id"):
                return dict(alert)
            return None

        def get_user_prefs(self, user_id):
            return {}

        def log_user_event(self, user_id, event_type, payload=None):
            self.events.append({
                "user_id": str(user_id),
                "event_type": event_type,
                "payload": dict(payload or {}),
            })

    class _DummyQuery:
        def __init__(self, data):
            self.data = data
            self.message = SimpleNamespace(photo=None)
            self.answers = []
            self.edit_text_calls = []
            self.edit_caption_calls = []

        async def answer(self, text=None, show_alert=False):
            self.answers.append({"text": text, "show_alert": show_alert})

        async def edit_message_text(self, **kwargs):
            self.edit_text_calls.append(dict(kwargs))

        async def edit_message_caption(self, **kwargs):
            self.edit_caption_calls.append(dict(kwargs))

    storage = _FakeStorage()
    query = _DummyQuery(callback_data)
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=777),
    )
    context = SimpleNamespace(bot_data={})
    set_bot_runtime(
        context.bot_data,
        BotRuntime(storage=storage, api_failure_tracker=None),
    )
    error = None
    try:
        await handle_prealert_info(update, context)
    except Exception as exc:  # pragma: no cover - captured as debugger failure
        error = str(exc)

    call = query.edit_text_calls[0] if query.edit_text_calls else {}
    markup = call.get("reply_markup")
    callbacks = []
    if markup and getattr(markup, "inline_keyboard", None):
        for row in markup.inline_keyboard:
            for btn in row:
                callbacks.append(getattr(btn, "callback_data", None))

    checks = {
        "no_exception": error is None,
        "edited_text_once": len(query.edit_text_calls) == 1,
        "parse_mode_markdown": str(call.get("parse_mode")) == "Markdown",
        "event_logged": any(
            event.get("event_type") == "alert_detail_opened"
            and event.get("payload", {}).get("source") == "pre"
            for event in storage.events
        ),
        "postpone_count_propagated": any(
            isinstance(cb, str) and cb.startswith("pp_menu_pre_") and cb.endswith(f"_{postpone_count}")
            for cb in callbacks
        ),
    }

    dbg.section("prealert_info_handler", {
        "checks": checks,
        "error": error,
        "callback_data": callback_data,
        "callbacks": callbacks,
        "logged_events": storage.events,
    })
    if not all(checks.values()):
        dbg.problem("prealert_info_handler_failed", {
            "checks": checks,
            "error": error,
            "callbacks": callbacks,
            "logged_events": storage.events,
        })


def _check_queue_cleanup(dbg, StorageManager):
    now = datetime.now()
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(base_data_dir=tmpdir)
        user_id = "999"
        storage.setup_user_space(user_id)

        alert_data = {
            "title": "Postpone Test",
            "type": 3,
            "type_name": "Weekly",
            "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "10:00"},
            "pre_alerts": ["1h"],
            "tags": [],
        }
        alert_id = storage.save_alert(user_id, alert_data)

        pending = {
            "id": "p1",
            "alert_id": alert_id,
            "kind": "pre",
            "status": "pending",
            "created_at": now.isoformat(),
            "fire_at": (now + timedelta(hours=1)).isoformat(),
            "original_time": now.isoformat(),
            "occurrence_time": (now + timedelta(hours=2)).isoformat(),
        }
        fired = {
            "id": "p2",
            "alert_id": alert_id,
            "kind": "due",
            "status": "fired",
            "created_at": now.isoformat(),
            "fire_at": (now + timedelta(hours=3)).isoformat(),
            "original_time": now.isoformat(),
            "occurrence_time": (now + timedelta(hours=3)).isoformat(),
        }
        storage.add_postpone_instance(user_id, pending)
        storage.add_postpone_instance(user_id, fired)

        queue_before = storage.get_postpone_queue(user_id)
        removed = storage.cleanup_postpone_queue(user_id, now.isoformat())
        queue_after = storage.get_postpone_queue(user_id)
        checks = {
            "queue_size_before_2": len(queue_before) == 2,
            "cleanup_removed_1": removed == 1,
            "queue_size_after_1": len(queue_after) == 1,
        }
        dbg.section("queue_cleanup", {
            "before": len(queue_before),
            "after": len(queue_after),
            "removed": removed,
            "checks": checks,
        })

        if not checks["queue_size_before_2"]:
            dbg.problem("queue_size_before_unexpected", {"count": len(queue_before)})
        if not checks["cleanup_removed_1"]:
            dbg.problem("cleanup_removed_unexpected", {"removed": removed})
        if not checks["queue_size_after_1"]:
            dbg.problem("queue_size_after_unexpected", {"count": len(queue_after)})


def _check_expire_pending_postpones_for_alert(dbg, StorageManager):
    now = datetime.now()
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(base_data_dir=tmpdir)
        user_id = "997"
        storage.setup_user_space(user_id)

        alert_a = storage.save_alert(user_id, {
            "title": "Expire Test A",
            "type": 3,
            "type_name": "Weekly",
            "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "10:00"},
            "pre_alerts": [],
            "tags": [],
        })
        alert_b = storage.save_alert(user_id, {
            "title": "Expire Test B",
            "type": 3,
            "type_name": "Weekly",
            "schedule": {"weekdays": ["Tue"], "interval": 1, "time": "11:00"},
            "pre_alerts": [],
            "tags": [],
        })

        base_occ = (now + timedelta(hours=2)).isoformat()
        storage.add_postpone_instance(user_id, {
            "id": "exp-1",
            "alert_id": alert_a,
            "kind": "pre",
            "status": "pending",
            "created_at": now.isoformat(),
            "fire_at": (now + timedelta(hours=1)).isoformat(),
            "original_time": now.isoformat(),
            "occurrence_time": base_occ,
        })
        storage.add_postpone_instance(user_id, {
            "id": "exp-2",
            "alert_id": alert_a,
            "kind": "due",
            "status": "pending",
            "created_at": now.isoformat(),
            "fire_at": (now + timedelta(hours=1, minutes=30)).isoformat(),
            "original_time": now.isoformat(),
            "occurrence_time": base_occ,
        })
        storage.add_postpone_instance(user_id, {
            "id": "exp-3",
            "alert_id": alert_a,
            "kind": "due",
            "status": "fired",
            "created_at": now.isoformat(),
            "fire_at": (now - timedelta(minutes=5)).isoformat(),
            "original_time": now.isoformat(),
            "occurrence_time": base_occ,
        })
        storage.add_postpone_instance(user_id, {
            "id": "exp-4",
            "alert_id": alert_b,
            "kind": "pre",
            "status": "pending",
            "created_at": now.isoformat(),
            "fire_at": (now + timedelta(hours=1)).isoformat(),
            "original_time": now.isoformat(),
            "occurrence_time": base_occ,
        })

        expired = storage.expire_pending_postpones_for_alert(user_id, alert_a)
        queue = storage.get_postpone_queue(user_id)
        by_id = {item.get("id"): item for item in queue}

        checks = {
            "expired_count_2": expired == 2,
            "target_pending_expired": by_id.get("exp-1", {}).get("status") == "expired"
            and by_id.get("exp-2", {}).get("status") == "expired",
            "target_reason_set": by_id.get("exp-1", {}).get("reason") == "alert_edited"
            and by_id.get("exp-2", {}).get("reason") == "alert_edited",
            "target_fired_untouched": by_id.get("exp-3", {}).get("status") == "fired",
            "other_alert_untouched": by_id.get("exp-4", {}).get("status") == "pending",
        }

        dbg.section("expire_pending_for_alert", {
            "expired": expired,
            "queue_ids": sorted([str(k) for k in by_id.keys()]),
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("expire_pending_postpones_for_alert_failed", {"checks": checks})


def _check_postpone_count(dbg, StorageManager):
    """Test that postpone_count field is stored and incremented correctly."""
    now = datetime.now()
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(base_data_dir=tmpdir)
        user_id = "998"
        storage.setup_user_space(user_id)

        alert_id = storage.save_alert(user_id, {
            "title": "Count Test",
            "type": 3,
            "type_name": "Weekly",
            "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "10:00"},
            "pre_alerts": ["1h"],
            "tags": [],
        })

        orig_iso = now.isoformat()
        occ_iso = (now + timedelta(hours=2)).isoformat()

        # Create first instance with count=1 (prior_count=0)
        inst1 = {
            "id": "cnt1",
            "alert_id": alert_id,
            "kind": "pre",
            "status": "pending",
            "created_at": now.isoformat(),
            "fire_at": (now + timedelta(hours=1)).isoformat(),
            "original_time": orig_iso,
            "occurrence_time": occ_iso,
            "postpone_count": 1,
        }
        storage.add_postpone_instance(user_id, inst1)

        # Verify stored
        queue = storage.get_postpone_queue(user_id)
        stored_count = queue[0].get("postpone_count") if queue else None

        # Update instance with incremented count
        storage.update_postpone_instance(user_id, "cnt1", {
            "fire_at": (now + timedelta(hours=2)).isoformat(),
            "postpone_count": 2,
        })
        queue2 = storage.get_postpone_queue(user_id)
        updated_count = queue2[0].get("postpone_count") if queue2 else None

        # Create second instance with prior_count=2 (simulating callback propagation)
        inst2 = {
            "id": "cnt2",
            "alert_id": alert_id,
            "kind": "due",
            "status": "pending",
            "created_at": now.isoformat(),
            "fire_at": (now + timedelta(hours=3)).isoformat(),
            "original_time": orig_iso,
            "occurrence_time": occ_iso,
            "postpone_count": 3,
        }
        storage.add_postpone_instance(user_id, inst2)
        queue3 = storage.get_postpone_queue(user_id)
        due_item = [q for q in queue3 if q.get("kind") == "due"]
        new_count = due_item[0].get("postpone_count") if due_item else None

        # Legacy instance without postpone_count field
        inst_legacy = {
            "id": "cnt-legacy",
            "alert_id": alert_id,
            "kind": "pre",
            "status": "fired",
            "created_at": now.isoformat(),
            "fire_at": (now - timedelta(hours=1)).isoformat(),
            "original_time": orig_iso,
            "occurrence_time": occ_iso,
            # No postpone_count — simulates pre-existing data
        }
        storage.add_postpone_instance(user_id, inst_legacy)
        queue4 = storage.get_postpone_queue(user_id)
        legacy_item = [q for q in queue4 if q.get("id") == "cnt-legacy"]
        legacy_count = legacy_item[0].get("postpone_count") if legacy_item else "MISSING"

        checks = {
            "initial_count_1": stored_count == 1,
            "updated_count_2": updated_count == 2,
            "new_instance_count_3": new_count == 3,
            "legacy_no_count_ok": legacy_count is None or legacy_count == "MISSING",
        }

        dbg.section("postpone_count", {
            "stored_count": stored_count,
            "updated_count": updated_count,
            "new_count": new_count,
            "legacy_count": legacy_count,
            "checks": checks,
        })

        if not all(checks.values()):
            dbg.problem("postpone_count_failed", {"checks": checks})


def _mk_due_postpone(alert_id, now, instance_id="pp1"):
    occurrence_time = now - timedelta(minutes=1)
    return occurrence_time, {
        "id": instance_id,
        "alert_id": alert_id,
        "kind": "due",
        "status": "pending",
        "created_at": now.isoformat(),
        "fire_at": (now - timedelta(seconds=10)).isoformat(),
        "original_time": occurrence_time.isoformat(),
        "occurrence_time": occurrence_time.isoformat(),
    }


async def _check_due_state_transitions(dbg, C, StorageManager, process_postpone_queue_for_user):
    now = datetime.now().replace(second=0, microsecond=0)
    weekday = C.WEEKDAYS[now.weekday()]

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(base_data_dir=tmpdir)
        recurring_user = "9101"
        one_time_user = "9102"
        storage.setup_user_space(recurring_user)
        storage.setup_user_space(one_time_user)

        recurring_alert_id = storage.save_alert(recurring_user, {
            "title": "Recurring Due Postpone",
            "type": 3,
            "type_name": C.ALERT_TYPES[3],
            "schedule": {
                "weekdays": [weekday],
                "interval": 1,
                "time": now.strftime("%H:%M"),
            },
            "pre_alerts": ["1h"],
            "tags": [],
        })
        recurring_occ, recurring_pp = _mk_due_postpone(recurring_alert_id, now, "rec-pp")
        storage.update_alert_schedule_state(recurring_user, recurring_alert_id, next_scheduled=recurring_occ)
        storage.add_postpone_instance(recurring_user, recurring_pp)

        one_time_alert_id = storage.save_alert(one_time_user, {
            "title": "One-time Due Postpone",
            "type": 5,
            "type_name": C.ALERT_TYPES[5],
            "schedule": {
                "date": (now + timedelta(days=2)).strftime("%d/%m/%Y"),
                "time": now.strftime("%H:%M"),
            },
            "pre_alerts": [],
            "tags": [],
        })
        one_time_occ, one_time_pp = _mk_due_postpone(one_time_alert_id, now, "one-pp")
        storage.update_alert_schedule_state(one_time_user, one_time_alert_id, next_scheduled=one_time_occ)
        storage.add_postpone_instance(one_time_user, one_time_pp)

        async def _fake_send_alert(*_args, **_kwargs):
            return {"ok": True}

        sent_pre_alerts = {
            (recurring_user, recurring_alert_id, "1h"): now,
        }

        from modules.scheduler_core import actions as scheduler_actions
        captured_user_events = []
        captured_system_events = []
        original_log_user_event = storage.log_user_event

        def _capture_log_user_event(log_user_id, event_type, payload=None):
            if event_type == "alert_sent":
                captured_user_events.append({
                    "user_id": str(log_user_id),
                    "event": event_type,
                    "payload": dict(payload or {}),
                })
            return original_log_user_event(log_user_id, event_type, payload)

        def _capture_log_system(category, event, payload=None, level="INFO"):
            if category == "scheduler" and event == "alert_sent":
                captured_system_events.append({
                    "category": category,
                    "event": event,
                    "level": level,
                    "payload": dict(payload or {}),
                })

        storage.log_user_event = _capture_log_user_event

        with (
            patch.object(scheduler_actions, "send_alert", _fake_send_alert),
            patch.object(scheduler_actions, "log_system", _capture_log_system),
        ):
            rec_data = storage.get_all_alerts(recurring_user)
            rec_map = {a.get("id"): a for a in rec_data.get("alerts", []) if a.get("id")}
            rec_pre_sent, rec_due_sent = await process_postpone_queue_for_user(
                bot=object(),
                user_id=recurring_user,
                alert_map=rec_map,
                postpone_items=rec_data.get("postpone_queue", []),
                now=now,
                storage=storage,
                sent_pre_alerts=sent_pre_alerts,
            )

            one_data = storage.get_all_alerts(one_time_user)
            one_map = {a.get("id"): a for a in one_data.get("alerts", []) if a.get("id")}
            one_pre_sent, one_due_sent = await process_postpone_queue_for_user(
                bot=object(),
                user_id=one_time_user,
                alert_map=one_map,
                postpone_items=one_data.get("postpone_queue", []),
                now=now,
                storage=storage,
                sent_pre_alerts={},
            )
        storage.log_user_event = original_log_user_event

        recurring_after = storage.get_alert_by_id(recurring_user, recurring_alert_id) or {}
        recurring_next_raw = recurring_after.get("next_scheduled")
        recurring_last_raw = recurring_after.get("last_triggered")
        recurring_next = None
        recurring_last = None
        try:
            recurring_next = datetime.fromisoformat(recurring_next_raw) if recurring_next_raw else None
            recurring_last = datetime.fromisoformat(recurring_last_raw) if recurring_last_raw else None
        except Exception:
            pass

        recurring_checks = {
            "due_sent_once": rec_pre_sent == 0 and rec_due_sent == 1,
            "last_triggered_set": recurring_last is not None,
            "next_scheduled_advanced": recurring_next is not None and recurring_next > recurring_occ,
            "queue_cleaned": len(storage.get_postpone_queue(recurring_user)) == 0,
            "pre_tracking_cleared": len(sent_pre_alerts) == 0,
            "alert_still_active": recurring_after.get("active", True) is True,
        }

        one_time_after = storage.get_alert_by_id(one_time_user, one_time_alert_id) or {}
        one_time_last_raw = one_time_after.get("last_triggered")
        one_time_last = None
        try:
            one_time_last = datetime.fromisoformat(one_time_last_raw) if one_time_last_raw else None
        except Exception:
            pass

        one_time_checks = {
            "due_sent_once": one_pre_sent == 0 and one_due_sent == 1,
            "deactivated_after_fire": one_time_after.get("active") is False,
            "last_triggered_set": one_time_last is not None,
            "queue_cleaned": len(storage.get_postpone_queue(one_time_user)) == 0,
        }

        recurring_user_alert_sent = next(
            (e for e in captured_user_events if e.get("payload", {}).get("alert_id") == recurring_alert_id),
            None,
        )
        recurring_system_alert_sent = next(
            (e for e in captured_system_events if e.get("payload", {}).get("alert_id") == recurring_alert_id),
            None,
        )
        one_time_user_alert_sent = next(
            (e for e in captured_user_events if e.get("payload", {}).get("alert_id") == one_time_alert_id),
            None,
        )
        one_time_system_alert_sent = next(
            (e for e in captured_system_events if e.get("payload", {}).get("alert_id") == one_time_alert_id),
            None,
        )

        log_checks = {
            "user_events_captured_2": len(captured_user_events) == 2,
            "system_events_captured_2": len(captured_system_events) == 2,
            "recurring_user_is_postponed": isinstance(recurring_user_alert_sent, dict) and recurring_user_alert_sent.get("payload", {}).get("is_postponed") is True,
            "recurring_user_postpone_id": isinstance(recurring_user_alert_sent, dict) and recurring_user_alert_sent.get("payload", {}).get("postpone_id") == recurring_pp.get("id"),
            "recurring_user_effective_fire": isinstance(recurring_user_alert_sent, dict) and recurring_user_alert_sent.get("payload", {}).get("effective_fire_time") == recurring_pp.get("fire_at"),
            "recurring_user_postpone_count": isinstance(recurring_user_alert_sent, dict) and recurring_user_alert_sent.get("payload", {}).get("postpone_count") == 0,
            "recurring_system_is_postponed": isinstance(recurring_system_alert_sent, dict) and recurring_system_alert_sent.get("payload", {}).get("is_postponed") is True,
            "recurring_system_postpone_id": isinstance(recurring_system_alert_sent, dict) and recurring_system_alert_sent.get("payload", {}).get("postpone_id") == recurring_pp.get("id"),
            "recurring_system_effective_fire": isinstance(recurring_system_alert_sent, dict) and recurring_system_alert_sent.get("payload", {}).get("effective_fire_time") == recurring_pp.get("fire_at"),
            "recurring_system_postpone_count": isinstance(recurring_system_alert_sent, dict) and recurring_system_alert_sent.get("payload", {}).get("postpone_count") == 0,
            "one_time_user_is_postponed": isinstance(one_time_user_alert_sent, dict) and one_time_user_alert_sent.get("payload", {}).get("is_postponed") is True,
            "one_time_user_postpone_id": isinstance(one_time_user_alert_sent, dict) and one_time_user_alert_sent.get("payload", {}).get("postpone_id") == one_time_pp.get("id"),
            "one_time_user_effective_fire": isinstance(one_time_user_alert_sent, dict) and one_time_user_alert_sent.get("payload", {}).get("effective_fire_time") == one_time_pp.get("fire_at"),
            "one_time_user_postpone_count": isinstance(one_time_user_alert_sent, dict) and one_time_user_alert_sent.get("payload", {}).get("postpone_count") == 0,
            "one_time_system_is_postponed": isinstance(one_time_system_alert_sent, dict) and one_time_system_alert_sent.get("payload", {}).get("is_postponed") is True,
            "one_time_system_postpone_id": isinstance(one_time_system_alert_sent, dict) and one_time_system_alert_sent.get("payload", {}).get("postpone_id") == one_time_pp.get("id"),
            "one_time_system_effective_fire": isinstance(one_time_system_alert_sent, dict) and one_time_system_alert_sent.get("payload", {}).get("effective_fire_time") == one_time_pp.get("fire_at"),
            "one_time_system_postpone_count": isinstance(one_time_system_alert_sent, dict) and one_time_system_alert_sent.get("payload", {}).get("postpone_count") == 0,
        }

        dbg.section("due_state_transitions", {
            "recurring_checks": recurring_checks,
            "one_time_checks": one_time_checks,
            "log_checks": log_checks,
            "recurring_state": {
                "last_triggered": recurring_last_raw,
                "next_scheduled": recurring_next_raw,
                "active": recurring_after.get("active"),
            },
            "one_time_state": {
                "last_triggered": one_time_last_raw,
                "active": one_time_after.get("active"),
            },
            "captured_user_events": captured_user_events,
            "captured_system_events": captured_system_events,
        })

        if not all(recurring_checks.values()):
            dbg.problem("recurring_postpone_due_state_failed", {
                "checks": recurring_checks,
                "alert": recurring_after,
            })
        if not all(one_time_checks.values()):
            dbg.problem("one_time_postpone_due_state_failed", {
                "checks": one_time_checks,
                "alert": one_time_after,
            })
        if not all(log_checks.values()):
            dbg.problem("postpone_due_alert_sent_log_payload_failed", {
                "checks": log_checks,
                "captured_user_events": captured_user_events,
                "captured_system_events": captured_system_events,
            })


async def _check_due_retry_behavior(dbg, C, StorageManager, process_postpone_queue_for_user):
    now = datetime.now().replace(second=0, microsecond=0)
    weekday = C.WEEKDAYS[now.weekday()]

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(base_data_dir=tmpdir)
        user_id = "9103"
        storage.setup_user_space(user_id)

        alert_id = storage.save_alert(user_id, {
            "title": "Retry Due Postpone",
            "type": 3,
            "type_name": C.ALERT_TYPES[3],
            "schedule": {
                "weekdays": [weekday],
                "interval": 1,
                "time": now.strftime("%H:%M"),
            },
            "pre_alerts": [],
            "tags": [],
        })
        occurrence_time, postpone_item = _mk_due_postpone(alert_id, now, "retry-pp")
        storage.update_alert_schedule_state(user_id, alert_id, next_scheduled=occurrence_time)
        storage.add_postpone_instance(user_id, postpone_item)

        async def _fake_send_fail(*_args, **_kwargs):
            return None

        from modules.scheduler_core import actions as scheduler_actions

        with (
            patch.object(scheduler_actions, "send_alert", _fake_send_fail),
            patch.object(scheduler_actions.logger, "error", lambda *_args, **_kwargs: None),
        ):
            data = storage.get_all_alerts(user_id)
            alert_map = {a.get("id"): a for a in data.get("alerts", []) if a.get("id")}
            pre_sent, due_sent = await process_postpone_queue_for_user(
                bot=object(),
                user_id=user_id,
                alert_map=alert_map,
                postpone_items=data.get("postpone_queue", []),
                now=now,
                storage=storage,
                sent_pre_alerts={},
            )

        alert_after = storage.get_alert_by_id(user_id, alert_id) or {}
        queue_after = storage.get_postpone_queue(user_id)
        pending_status = queue_after[0].get("status") if queue_after else None
        checks = {
            "no_send_counted": pre_sent == 0 and due_sent == 0,
            "queue_item_still_pending": len(queue_after) == 1 and pending_status == "pending",
            "last_triggered_unchanged": alert_after.get("last_triggered") in (None, ""),
            "next_scheduled_unchanged": alert_after.get("next_scheduled") == occurrence_time.isoformat(),
        }

        dbg.section("due_retry_behavior", {
            "checks": checks,
            "queue_len": len(queue_after),
            "queue_status": pending_status,
            "alert_last_triggered": alert_after.get("last_triggered"),
            "alert_next_scheduled": alert_after.get("next_scheduled"),
        })

        if not all(checks.values()):
            dbg.problem("postpone_due_retry_behavior_failed", {
                "checks": checks,
                "queue_after": queue_after,
                "alert_after": alert_after,
            })


async def _check_due_metadata_plumbing(dbg, C, StorageManager, process_postpone_queue_for_user):
    now = datetime.now().replace(second=0, microsecond=0)
    weekday = C.WEEKDAYS[now.weekday()]

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(base_data_dir=tmpdir)
        user_id = "9104"
        storage.setup_user_space(user_id)

        alert_id = storage.save_alert(user_id, {
            "title": "Metadata Due Postpone",
            "type": 3,
            "type_name": C.ALERT_TYPES[3],
            "schedule": {
                "weekdays": [weekday],
                "interval": 1,
                "time": now.strftime("%H:%M"),
            },
            "pre_alerts": [],
            "tags": [],
        })
        occurrence_time, postpone_item = _mk_due_postpone(alert_id, now, "meta-pp")
        postpone_item["postpone_count"] = 4
        fire_at = datetime.fromisoformat(postpone_item["fire_at"])
        storage.update_alert_schedule_state(user_id, alert_id, next_scheduled=occurrence_time)
        storage.add_postpone_instance(user_id, postpone_item)

        captured = {}
        sent_pre_alerts = {"sentinel": "ok"}

        async def _fake_trigger_alert(
            bot,
            call_user_id,
            alert,
            alert_type,
            call_storage,
            call_sent_pre_alerts,
            **kwargs,
        ):
            captured["user_id"] = call_user_id
            captured["alert_id"] = alert.get("id")
            captured["alert_type"] = alert_type
            captured["storage_is_same"] = call_storage is storage
            captured["sent_pre_alerts_is_same"] = call_sent_pre_alerts is sent_pre_alerts
            captured["kwargs"] = dict(kwargs)
            return True

        from modules.scheduler_core import postpone as postpone_module

        with patch.object(postpone_module, "trigger_alert", _fake_trigger_alert):
            data = storage.get_all_alerts(user_id)
            alert_map = {a.get("id"): a for a in data.get("alerts", []) if a.get("id")}
            pre_sent, due_sent = await process_postpone_queue_for_user(
                bot=object(),
                user_id=user_id,
                alert_map=alert_map,
                postpone_items=data.get("postpone_queue", []),
                now=now,
                storage=storage,
                sent_pre_alerts=sent_pre_alerts,
            )

        kw = captured.get("kwargs", {})
        effective_fire_time = kw.get("effective_fire_time")
        scheduled_time = kw.get("scheduled_time")
        checks = {
            "counts_ok": pre_sent == 0 and due_sent == 1,
            "called_for_due": captured.get("alert_type") == C.ALERT_MSG_TYPE_MAIN,
            "user_id_passed": captured.get("user_id") == user_id,
            "alert_id_passed": captured.get("alert_id") == alert_id,
            "storage_passed": captured.get("storage_is_same") is True,
            "sent_pre_alerts_passed": captured.get("sent_pre_alerts_is_same") is True,
            "postpone_id_passed": kw.get("postpone_id") == postpone_item.get("id"),
            "postpone_count_passed": kw.get("postpone_count") == postpone_item.get("postpone_count"),
            "effective_fire_time_passed": isinstance(effective_fire_time, datetime) and effective_fire_time == fire_at,
            "scheduled_time_passed": isinstance(scheduled_time, datetime) and scheduled_time == occurrence_time,
            "queue_cleaned": len(storage.get_postpone_queue(user_id)) == 0,
        }

        dbg.section("due_metadata_plumbing", {
            "checks": checks,
            "captured": captured,
            "pre_sent": pre_sent,
            "due_sent": due_sent,
        })

        if not all(checks.values()):
            dbg.problem("postpone_due_metadata_plumbing_failed", {
                "checks": checks,
                "captured": captured,
                "pre_sent": pre_sent,
                "due_sent": due_sent,
            })


async def _check_non_postponed_alert_sent_defaults(dbg, C, StorageManager):
    now = datetime.now().replace(second=0, microsecond=0)
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(base_data_dir=tmpdir)
        user_id = "9105"
        storage.setup_user_space(user_id)

        alert_id = storage.save_alert(user_id, {
            "title": "Normal Alert Defaults",
            "type": 5,
            "type_name": C.ALERT_TYPES[5],
            "schedule": {
                "date": (now + timedelta(days=1)).strftime("%d/%m/%Y"),
                "time": now.strftime("%H:%M"),
            },
            "pre_alerts": [],
            "tags": [],
        })
        alert = storage.get_alert_by_id(user_id, alert_id)

        captured_user_events = []
        captured_system_events = []
        original_log_user_event = storage.log_user_event

        def _capture_log_user_event(log_user_id, event_type, payload=None):
            if event_type == "alert_sent":
                captured_user_events.append({
                    "user_id": str(log_user_id),
                    "event": event_type,
                    "payload": dict(payload or {}),
                })
            return original_log_user_event(log_user_id, event_type, payload)

        def _capture_log_system(category, event, payload=None, level="INFO"):
            if category == "scheduler" and event == "alert_sent":
                captured_system_events.append({
                    "category": category,
                    "event": event,
                    "level": level,
                    "payload": dict(payload or {}),
                })

        async def _fake_send_alert(*_args, **_kwargs):
            return {"ok": True}

        from modules.scheduler_core import actions as scheduler_actions

        storage.log_user_event = _capture_log_user_event
        with (
            patch.object(scheduler_actions, "send_alert", _fake_send_alert),
            patch.object(scheduler_actions, "log_system", _capture_log_system),
        ):
            sent = await scheduler_actions.trigger_alert(
                bot=object(),
                user_id=user_id,
                alert=alert,
                alert_type=C.ALERT_MSG_TYPE_MAIN,
                storage=storage,
                sent_pre_alerts={},
                scheduled_time=now,
            )
        storage.log_user_event = original_log_user_event

        user_payload = captured_user_events[0]["payload"] if captured_user_events else {}
        system_payload = captured_system_events[0]["payload"] if captured_system_events else {}
        checks = {
            "trigger_sent": sent is True,
            "single_user_event": len(captured_user_events) == 1,
            "single_system_event": len(captured_system_events) == 1,
            "user_is_postponed_false": user_payload.get("is_postponed") is False,
            "user_postpone_id_none": user_payload.get("postpone_id") is None,
            "user_effective_fire_none": user_payload.get("effective_fire_time") is None,
            "user_postpone_count_zero": user_payload.get("postpone_count") == 0,
            "system_is_postponed_false": system_payload.get("is_postponed") is False,
            "system_postpone_id_none": system_payload.get("postpone_id") is None,
            "system_effective_fire_none": system_payload.get("effective_fire_time") is None,
            "system_postpone_count_zero": system_payload.get("postpone_count") == 0,
        }

        dbg.section("non_postponed_alert_sent_defaults", {
            "checks": checks,
            "captured_user_events": captured_user_events,
            "captured_system_events": captured_system_events,
        })

        if not all(checks.values()):
            dbg.problem("non_postponed_alert_sent_defaults_failed", {
                "checks": checks,
                "captured_user_events": captured_user_events,
                "captured_system_events": captured_system_events,
            })


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.handlers.scheduler_handlers import (
                _parse_iso,
                _parse_postpone_data,
                _resolve_custom_postpone_fire_at,
                handle_custom_postpone_input,
                handle_prealert_info,
            )
            from modules.scheduler_messagelogic import _build_postpone_callback
            from modules import constants as C
            from modules.scheduler_core.postpone import process_postpone_queue_for_user
            from modules.scheduler_mathlogic import parse_pre_alert_string
            from modules.storage import StorageManager
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _check_parse_samples(dbg, parse_pre_alert_string)
        run_async(_check_custom_postpone_expression_and_context(
            dbg,
            _resolve_custom_postpone_fire_at,
            handle_custom_postpone_input,
        ))
        _check_callback_count_encoding(dbg, _parse_postpone_data, _build_postpone_callback)
        _check_iso_parse(dbg, _parse_iso)
        _check_notification_module_surface(dbg)
        run_async(_check_prealert_info_handler(dbg, handle_prealert_info))
        _check_queue_cleanup(dbg, StorageManager)
        _check_expire_pending_postpones_for_alert(dbg, StorageManager)
        _check_postpone_count(dbg, StorageManager)
        run_async(_check_due_state_transitions(
            dbg,
            C,
            StorageManager,
            process_postpone_queue_for_user,
        ))
        run_async(_check_due_retry_behavior(
            dbg,
            C,
            StorageManager,
            process_postpone_queue_for_user,
        ))
        run_async(_check_due_metadata_plumbing(
            dbg,
            C,
            StorageManager,
            process_postpone_queue_for_user,
        ))
        run_async(_check_non_postponed_alert_sent_defaults(
            dbg,
            C,
            StorageManager,
        ))
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    parse_ok = not dbg.has_problem(
        "parse_month_failed",
        "parse_invalid_should_fail",
        "custom_postpone_expression_and_context_failed",
    )
    callback_ok = not dbg.has_problem("callback_count_encoding_failed")
    iso_ok = not dbg.has_problem("parse_iso_failed")
    surface_ok = not dbg.has_problem("notification_module_surface_failed")
    handler_ok = not dbg.has_problem("prealert_info_handler_failed")
    queue_ok = not dbg.has_problem(
        "queue_size_before_unexpected",
        "cleanup_removed_unexpected",
        "queue_size_after_unexpected",
        "expire_pending_postpones_for_alert_failed",
    )
    count_ok = not dbg.has_problem("postpone_count_failed")
    due_state_ok = not dbg.has_problem(
        "recurring_postpone_due_state_failed",
        "one_time_postpone_due_state_failed",
    )
    payload_ok = not dbg.has_problem(
        "postpone_due_alert_sent_log_payload_failed",
        "non_postponed_alert_sent_defaults_failed",
    )
    retry_ok = not dbg.has_problem("postpone_due_retry_behavior_failed")
    metadata_ok = not dbg.has_problem("postpone_due_metadata_plumbing_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"parse: {'OK' if parse_ok else 'FAIL'}",
        f"callback: {'OK' if callback_ok else 'FAIL'}",
        f"iso: {'OK' if iso_ok else 'FAIL'}",
        f"surface: {'OK' if surface_ok else 'FAIL'}",
        f"handler: {'OK' if handler_ok else 'FAIL'}",
        f"cleanup: {'OK' if queue_ok else 'FAIL'}",
        f"count: {'OK' if count_ok else 'FAIL'}",
        f"due-state: {'OK' if due_state_ok else 'FAIL'}",
        f"payload: {'OK' if payload_ok else 'FAIL'}",
        f"retry: {'OK' if retry_ok else 'FAIL'}",
        f"metadata: {'OK' if metadata_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
