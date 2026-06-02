#!/usr/bin/env python3
import asyncio
import os
import sys
import types


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
from _lib.runtime import seed_mainbot_runtime

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "settings_mail_set_flow_debug"
FEATURE_TITLE = "Settings Mail Set Flow"

_DBG = None
_RUNTIME_MAINBOT = None
_RUNTIME_STORAGE = None


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _dbg():
    if _DBG is None:
        raise RuntimeError("debug harness not initialized")
    return _DBG


def print_section(label, payload):
    _dbg().section(label, payload)


def _log_problem(message, payload=None):
    _dbg().problem(message, payload or {})


def _extract_labels(reply_markup):
    if not reply_markup:
        return []
    labels = []
    for row in getattr(reply_markup, "inline_keyboard", []):
        for button in row:
            labels.append(getattr(button, "text", ""))
    return labels


def _payload_contains_email(value):
    if isinstance(value, str):
        return "@" in value
    if isinstance(value, dict):
        return any(_payload_contains_email(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_payload_contains_email(v) for v in value)
    return False


class _FakeStorage:
    def __init__(self):
        self.events = []
        self._prefs_map = {}

    def _key(self, user_id):
        return str(user_id)

    def _default_backup_prefs(self):
        return {
            "email_enabled": False,
            "email_address": None,
            "email_frequency": "monthly",
            "last_email_sent": None,
            "email_reminder_disabled": False,
            "last_email_reminder_sent": None,
        }

    def seed_backup_prefs(self, user_id, prefs):
        merged = self._default_backup_prefs()
        merged.update(prefs or {})
        self._prefs_map[self._key(user_id)] = merged

    def get_backup_prefs(self, user_id):
        merged = self._default_backup_prefs()
        merged.update(self._prefs_map.get(self._key(user_id), {}))
        return merged

    def update_backup_prefs(self, user_id, updates, ensure_space=True):
        merged = self.get_backup_prefs(user_id)
        merged.update(updates or {})
        self._prefs_map[self._key(user_id)] = merged
        return merged

    def log_user_event(self, user_id, event_type, payload):
        self.events.append({
            "user_id": str(user_id),
            "event_type": event_type,
            "payload": payload or {},
        })


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyMessage:
    def __init__(self):
        self.replies = []
        self.edits = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({
            "text": text,
            "kwargs": kwargs,
        })

    async def edit_text(self, text, **kwargs):
        self.edits.append({
            "text": text,
            "kwargs": kwargs,
        })


class _DummyCallbackQuery:
    def __init__(self, data):
        self.data = data
        self.message = _DummyMessage()
        self.answered = False
        self.answer_call_count = 0
        self.answer_payloads = []

    async def answer(self, *args, **kwargs):
        self.answer_call_count += 1
        self.answer_payloads.append({
            "args": list(args),
            "kwargs": dict(kwargs),
        })
        self.answered = True


class _DummyUpdate:
    def __init__(self, user_id, callback_data):
        self.effective_user = _DummyUser(user_id)
        self.callback_query = _DummyCallbackQuery(callback_data)
        self.message = None
        self.effective_message = self.callback_query.message


class _DummyContext:
    def __init__(self, user_data=None):
        self.user_data = dict(user_data or {})
        self.bot_data = {}
        if _RUNTIME_MAINBOT is not None:
            seed_mainbot_runtime(_RUNTIME_MAINBOT, app=self, storage=_RUNTIME_STORAGE)


async def _run_callback(base_handlers, *, user_id, callback_data, user_data=None):
    update = _DummyUpdate(user_id=user_id, callback_data=callback_data)
    context = _DummyContext(user_data=user_data)
    await base_handlers.handle_settings_callback(update, context)
    return update, context


def main():
    global _DBG, _RUNTIME_MAINBOT, _RUNTIME_STORAGE
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg

    original_mainbot = sys.modules.get("mainbot")
    had_mainbot = "mainbot" in sys.modules
    fake_storage = _FakeStorage()

    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        runtime_mainbot = types.SimpleNamespace(storage=fake_storage, API_FAILURE_TRACKER=None)
        sys.modules["mainbot"] = runtime_mainbot
        _RUNTIME_MAINBOT = runtime_mainbot
        _RUNTIME_STORAGE = fake_storage

        # Ensure SMTP appears configured so keyboard/status render normally
        _saved_smtp_host = os.environ.get("BOT_SMTP_HOST")
        os.environ["BOT_SMTP_HOST"] = "smtp.debug.test"

        try:
            from modules.handlers import base as base_handlers
            from modules.backup_core.email_backup import (
                describe_monthly_backup_schedule,
                describe_monthly_reminder_schedule,
            )
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        user_id = 4242

        fake_storage.seed_backup_prefs(user_id, {
            "email_enabled": True,
            "email_address": "first@example.com",
        })
        update, context = asyncio.run(_run_callback(
            base_handlers,
            user_id=user_id,
            callback_data="settings_mail_set",
            user_data={},
        ))
        set_with_email_reply = update.callback_query.message.replies[-1] if update.callback_query.message.replies else {}
        set_with_email_markup = set_with_email_reply.get("kwargs", {}).get("reply_markup")
        set_with_email_labels = _extract_labels(set_with_email_markup)
        set_with_email_checks = {
            "answer_called": update.callback_query.answered,
            "flag_set": context.user_data.get("expecting_backup_email") is True,
            "prompt_exact": set_with_email_reply.get("text")
            == "Current email address: first@example.com\nSend your new email address now.",
            "has_clear": any("Clear Email Address" in label for label in set_with_email_labels),
            "has_cancel": any("Cancel Operation" in label for label in set_with_email_labels),
            "event_logged": bool(fake_storage.events) and fake_storage.events[-1]["event_type"] == "backup_email_set_prompt",
        }
        print_section("settings_mail_set_with_email", {
            "reply": set_with_email_reply,
            "labels": set_with_email_labels,
            "checks": set_with_email_checks,
        })
        if not all(set_with_email_checks.values()):
            _log_problem("settings_mail_set_prompt_with_email_failed", {
                "checks": set_with_email_checks,
                "reply": set_with_email_reply,
                "labels": set_with_email_labels,
            })

        fake_storage.seed_backup_prefs(user_id, {
            "email_enabled": False,
            "email_address": None,
        })
        update, context = asyncio.run(_run_callback(
            base_handlers,
            user_id=user_id,
            callback_data="settings_mail_set",
            user_data={},
        ))
        set_without_email_reply = update.callback_query.message.replies[-1] if update.callback_query.message.replies else {}
        set_without_email_markup = set_without_email_reply.get("kwargs", {}).get("reply_markup")
        set_without_email_labels = _extract_labels(set_without_email_markup)
        set_without_email_checks = {
            "answer_called": update.callback_query.answered,
            "flag_set": context.user_data.get("expecting_backup_email") is True,
            "prompt_exact": set_without_email_reply.get("text")
            == "Current email address: Not set\nSend your new email address now.",
            "clear_hidden": not any("Clear Email Address" in label for label in set_without_email_labels),
            "has_cancel": any("Cancel Operation" in label for label in set_without_email_labels),
            "single_button_layout": len(set_without_email_labels) == 1 and bool(set_without_email_markup) and len(getattr(set_without_email_markup, "inline_keyboard", [])) == 1,
            "event_logged": bool(fake_storage.events) and fake_storage.events[-1]["event_type"] == "backup_email_set_prompt",
        }
        print_section("settings_mail_set_without_email", {
            "reply": set_without_email_reply,
            "labels": set_without_email_labels,
            "checks": set_without_email_checks,
        })
        if not all(set_without_email_checks.values()):
            _log_problem("settings_mail_set_prompt_without_email_failed", {
                "checks": set_without_email_checks,
                "reply": set_without_email_reply,
                "labels": set_without_email_labels,
            })

        fake_storage.seed_backup_prefs(user_id, {
            "email_enabled": False,
            "email_address": "   ",
        })
        update, context = asyncio.run(_run_callback(
            base_handlers,
            user_id=user_id,
            callback_data="settings_mail_set",
            user_data={},
        ))
        set_whitespace_reply = update.callback_query.message.replies[-1] if update.callback_query.message.replies else {}
        set_whitespace_markup = set_whitespace_reply.get("kwargs", {}).get("reply_markup")
        set_whitespace_labels = _extract_labels(set_whitespace_markup)
        set_whitespace_checks = {
            "answer_called": update.callback_query.answered,
            "flag_set": context.user_data.get("expecting_backup_email") is True,
            "prompt_exact": set_whitespace_reply.get("text")
            == "Current email address: Not set\nSend your new email address now.",
            "clear_hidden": not any("Clear Email Address" in label for label in set_whitespace_labels),
            "has_cancel": any("Cancel Operation" in label for label in set_whitespace_labels),
            "single_button_layout": len(set_whitespace_labels) == 1 and bool(set_whitespace_markup) and len(getattr(set_whitespace_markup, "inline_keyboard", [])) == 1,
            "event_logged": bool(fake_storage.events) and fake_storage.events[-1]["event_type"] == "backup_email_set_prompt",
        }
        print_section("settings_mail_set_whitespace_email", {
            "reply": set_whitespace_reply,
            "labels": set_whitespace_labels,
            "checks": set_whitespace_checks,
        })
        if not all(set_whitespace_checks.values()):
            _log_problem("settings_mail_set_prompt_whitespace_email_failed", {
                "checks": set_whitespace_checks,
                "reply": set_whitespace_reply,
                "labels": set_whitespace_labels,
            })

        fake_storage.seed_backup_prefs(user_id, {
            "email_enabled": True,
            "email_address": "clearme@example.com",
        })
        update, context = asyncio.run(_run_callback(
            base_handlers,
            user_id=user_id,
            callback_data="settings_mail_clear",
            user_data={
                "expecting_backup_email": True,
                "backup_email_enable_after_set": True,
            },
        ))
        prefs_after_clear = fake_storage.get_backup_prefs(user_id)
        clear_edit = update.callback_query.message.edits[-1] if update.callback_query.message.edits else {}
        clear_checks = {
            "email_cleared": prefs_after_clear.get("email_address") is None,
            "disabled_after_clear": prefs_after_clear.get("email_enabled") is False,
            "flow_flag_removed": "expecting_backup_email" not in context.user_data,
            "enable_after_set_removed": "backup_email_enable_after_set" not in context.user_data,
            "status_rendered": "Mail Backup" in (clear_edit.get("text") or ""),
            "event_logged": bool(fake_storage.events) and fake_storage.events[-1]["event_type"] == "backup_email_cleared",
        }
        print_section("settings_mail_clear", {
            "prefs_after_clear": prefs_after_clear,
            "edit": clear_edit,
            "checks": clear_checks,
        })
        if not all(clear_checks.values()):
            _log_problem("settings_mail_clear_failed", {
                "checks": clear_checks,
                "prefs_after_clear": prefs_after_clear,
                "edit": clear_edit,
            })

        fake_storage.seed_backup_prefs(user_id, {
            "email_enabled": True,
            "email_address": "keepme@example.com",
        })
        update, context = asyncio.run(_run_callback(
            base_handlers,
            user_id=user_id,
            callback_data="settings_mail_set_cancel",
            user_data={
                "expecting_backup_email": True,
                "backup_email_enable_after_set": True,
            },
        ))
        prefs_after_cancel = fake_storage.get_backup_prefs(user_id)
        cancel_edit = update.callback_query.message.edits[-1] if update.callback_query.message.edits else {}
        cancel_checks = {
            "email_unchanged": prefs_after_cancel.get("email_address") == "keepme@example.com",
            "enabled_unchanged": prefs_after_cancel.get("email_enabled") is True,
            "flow_flag_removed": "expecting_backup_email" not in context.user_data,
            "enable_after_set_removed": "backup_email_enable_after_set" not in context.user_data,
            "status_rendered": "Mail Backup" in (cancel_edit.get("text") or ""),
            "event_logged": bool(fake_storage.events) and fake_storage.events[-1]["event_type"] == "backup_email_set_cancelled",
        }
        print_section("settings_mail_set_cancel", {
            "prefs_after_cancel": prefs_after_cancel,
            "edit": cancel_edit,
            "checks": cancel_checks,
        })
        if not all(cancel_checks.values()):
            _log_problem("settings_mail_set_cancel_failed", {
                "checks": cancel_checks,
                "prefs_after_cancel": prefs_after_cancel,
                "edit": cancel_edit,
            })

        fake_storage.seed_backup_prefs(user_id, {
            "email_enabled": False,
            "email_address": None,
            "email_reminder_disabled": False,
        })

        fake_storage.seed_backup_prefs(user_id, {
            "email_enabled": False,
            "email_address": None,
            "email_reminder_disabled": True,
        })
        update, context = asyncio.run(_run_callback(
            base_handlers,
            user_id=user_id,
            callback_data="settings_mail_enable",
            user_data={},
        ))
        prefs_after_enable = fake_storage.get_backup_prefs(user_id)
        enable_edit = update.callback_query.message.edits[-1] if update.callback_query.message.edits else {}
        enable_labels = _extract_labels(enable_edit.get("kwargs", {}).get("reply_markup"))
        enable_checks = {
            "disabled_flag_cleared": prefs_after_enable.get("email_reminder_disabled") is False,
            "status_enabled": "Reminder to setup the mail: <b>Enabled ✅</b>" in (enable_edit.get("text") or ""),
            "disable_label_present": any("Disable reminder to set the mail" in label for label in enable_labels),
            "set_mail_present": any("Set Mail" in label for label in enable_labels),
            "backup_toggle_present": any("Mail Backup" in label for label in enable_labels),
            "send_now_hidden": not any("Send Backup Now" in label for label in enable_labels),
            "event_logged": bool(fake_storage.events) and fake_storage.events[-1]["event_type"] == "backup_email_reminder_enabled",
        }
        print_section("settings_mail_enable", {
            "prefs_after_enable": prefs_after_enable,
            "edit": enable_edit,
            "labels": enable_labels,
            "checks": enable_checks,
        })
        if not all(enable_checks.values()):
            _log_problem("settings_mail_enable_failed", {
                "checks": enable_checks,
                "prefs_after_enable": prefs_after_enable,
                "edit": enable_edit,
                "labels": enable_labels,
            })

        fake_storage.seed_backup_prefs(user_id, {
            "email_enabled": False,
            "email_address": "   ",
            "email_reminder_disabled": False,
        })
        update, context = asyncio.run(_run_callback(
            base_handlers,
            user_id=user_id,
            callback_data="settings_mail_toggle",
            user_data={},
        ))
        prefs_after_whitespace_toggle = fake_storage.get_backup_prefs(user_id)
        whitespace_toggle_reply = update.callback_query.message.replies[-1] if update.callback_query.message.replies else {}
        whitespace_toggle_markup = whitespace_toggle_reply.get("kwargs", {}).get("reply_markup")
        whitespace_toggle_labels = _extract_labels(whitespace_toggle_markup)
        whitespace_toggle_checks = {
            "enabled_stays_false": prefs_after_whitespace_toggle.get("email_enabled") is False,
            "prompt_exact": whitespace_toggle_reply.get("text")
            == "Current email address: Not set\nSend your new email address now.",
            "clear_hidden": not any("Clear Email Address" in label for label in whitespace_toggle_labels),
            "cancel_present": any("Cancel Operation" in label for label in whitespace_toggle_labels),
            "expecting_backup_email_set": context.user_data.get("expecting_backup_email") is True,
            "enable_after_set_set": context.user_data.get("backup_email_enable_after_set") is True,
            "event_logged": bool(fake_storage.events) and fake_storage.events[-1]["event_type"] == "backup_email_enable_prompt",
        }
        print_section("settings_mail_toggle_whitespace_email", {
            "prefs_after_toggle": prefs_after_whitespace_toggle,
            "reply": whitespace_toggle_reply,
            "labels": whitespace_toggle_labels,
            "user_data": context.user_data,
            "checks": whitespace_toggle_checks,
        })
        if not all(whitespace_toggle_checks.values()):
            _log_problem("settings_mail_toggle_whitespace_email_failed", {
                "checks": whitespace_toggle_checks,
                "prefs_after_toggle": prefs_after_whitespace_toggle,
                "reply": whitespace_toggle_reply,
                "user_data": context.user_data,
            })

        fake_storage.seed_backup_prefs(user_id, {
            "email_enabled": True,
            "email_address": "set@example.com",
            "email_reminder_disabled": False,
        })
        update, context = asyncio.run(_run_callback(
            base_handlers,
            user_id=user_id,
            callback_data="settings_mail",
            user_data={},
        ))
        status_edit = update.callback_query.message.edits[-1] if update.callback_query.message.edits else {}
        status_labels = _extract_labels(status_edit.get("kwargs", {}).get("reply_markup"))
        schedule_label = describe_monthly_backup_schedule()
        reminder_schedule_label = describe_monthly_reminder_schedule()
        status_checks = {
            "reminder_toggle_hidden": not any("reminder to set the mail" in label for label in status_labels),
            "reminder_line_hidden": "Reminder to setup the mail:" not in (status_edit.get("text") or ""),
            "set_mail_present": any("Set Mail" in label for label in status_labels),
            "backup_toggle_present": any("Mail Backup" in label for label in status_labels),
            "send_now_present": any("Send Backup Now" in label for label in status_labels),
            "back_present": any(label == "⬅️ Back" for label in status_labels),
            "schedule_line_present": schedule_label in (status_edit.get("text") or ""),
            "reminder_schedule_hidden": reminder_schedule_label not in (status_edit.get("text") or ""),
        }
        print_section("settings_mail_status_with_email", {
            "labels": status_labels,
            "text": status_edit.get("text"),
            "schedule_label": schedule_label,
            "reminder_schedule_label": reminder_schedule_label,
            "checks": status_checks,
        })
        if not all(status_checks.values()):
            _log_problem("settings_mail_status_with_email_failed", {
                "checks": status_checks,
                "labels": status_labels,
            })

        fake_storage.seed_backup_prefs(user_id, {
            "email_enabled": False,
            "email_address": None,
            "email_reminder_disabled": False,
        })
        update, context = asyncio.run(_run_callback(
            base_handlers,
            user_id=user_id,
            callback_data="settings_mail",
            user_data={},
        ))
        status_no_email_edit = update.callback_query.message.edits[-1] if update.callback_query.message.edits else {}
        status_no_email_labels = _extract_labels(status_no_email_edit.get("kwargs", {}).get("reply_markup"))
        status_no_email_checks = {
            "reminder_toggle_visible": any("reminder to set the mail" in label for label in status_no_email_labels),
            "reminder_line_present": "Reminder to setup the mail: <b>Enabled ✅</b>" in (status_no_email_edit.get("text") or ""),
            "reminder_schedule_present": f"When: <b>{reminder_schedule_label}</b>" in (status_no_email_edit.get("text") or ""),
            "backup_schedule_hidden": schedule_label not in (status_no_email_edit.get("text") or ""),
            "email_not_set_line": "Email: Not set" in (status_no_email_edit.get("text") or ""),
            "send_now_hidden": not any("Send Backup Now" in label for label in status_no_email_labels),
            "back_present": any(label == "⬅️ Back" for label in status_no_email_labels),
        }
        print_section("settings_mail_status_without_email", {
            "labels": status_no_email_labels,
            "text": status_no_email_edit.get("text"),
            "schedule_label": schedule_label,
            "reminder_schedule_label": reminder_schedule_label,
            "checks": status_no_email_checks,
        })
        if not all(status_no_email_checks.values()):
            _log_problem("settings_mail_status_without_email_failed", {
                "checks": status_no_email_checks,
                "labels": status_no_email_labels,
                "text": status_no_email_edit.get("text"),
            })

        # SMTP unavailable path for settings_mail_send must answer callback at most once
        fake_storage.seed_backup_prefs(user_id, {
            "email_enabled": True,
            "email_address": "send@example.com",
            "email_reminder_disabled": False,
        })
        _saved_smtp_host_case = os.environ.get("BOT_SMTP_HOST")
        os.environ.pop("BOT_SMTP_HOST", None)
        events_before_unavailable_send = len(fake_storage.events)
        try:
            update, context = asyncio.run(_run_callback(
                base_handlers,
                user_id=user_id,
                callback_data="settings_mail_send",
                user_data={},
            ))
        finally:
            if _saved_smtp_host_case is None:
                os.environ.pop("BOT_SMTP_HOST", None)
            else:
                os.environ["BOT_SMTP_HOST"] = _saved_smtp_host_case

        unavailable_send_replies = list(update.callback_query.message.replies)
        unavailable_send_edits = list(update.callback_query.message.edits)
        unavailable_send_answer_payloads = list(update.callback_query.answer_payloads)
        unavailable_send_new_events = fake_storage.events[events_before_unavailable_send:]
        unavailable_send_checks = {
            "single_answer": update.callback_query.answer_call_count == 1,
            "no_popup_alert": not any(
                bool((item.get("kwargs") or {}).get("show_alert"))
                for item in unavailable_send_answer_payloads
            ),
            "feedback_message_sent": any(
                "Email service unavailable" in str(item.get("text") or "")
                for item in unavailable_send_replies
            ) or any(
                "Email service unavailable" in str(item.get("text") or "")
                for item in unavailable_send_edits
            ),
            "send_not_requested": not any(
                evt.get("event_type") == "backup_email_send_requested"
                for evt in unavailable_send_new_events
            ),
        }
        print_section("settings_mail_send_smtp_unavailable", {
            "answer_call_count": update.callback_query.answer_call_count,
            "answer_payloads": unavailable_send_answer_payloads,
            "replies": unavailable_send_replies,
            "edits": unavailable_send_edits,
            "new_events": unavailable_send_new_events,
            "checks": unavailable_send_checks,
        })
        if not all(unavailable_send_checks.values()):
            _log_problem("settings_mail_send_smtp_unavailable_single_answer_failed", {
                "answer_call_count": update.callback_query.answer_call_count,
                "answer_payloads": unavailable_send_answer_payloads,
                "replies": unavailable_send_replies,
                "edits": unavailable_send_edits,
                "new_events": unavailable_send_new_events,
                "checks": unavailable_send_checks,
            })

        update, context = asyncio.run(_run_callback(
            base_handlers,
            user_id=user_id,
            callback_data="settings_birthday_time_set",
            user_data={"expecting_backup_email": True},
        ))
        overlap_reply = update.callback_query.message.replies[-1] if update.callback_query.message.replies else {}
        overlap_checks = {
            "blocked": "Finish the current flow" in (overlap_reply.get("text") or ""),
            "birthday_flag_not_set": not context.user_data.get("expecting_birthday_time"),
        }
        print_section("flow_overlap_guard", {
            "reply": overlap_reply,
            "checks": overlap_checks,
        })
        if not all(overlap_checks.values()):
            _log_problem("settings_mail_overlap_guard_failed", {
                "checks": overlap_checks,
                "reply": overlap_reply,
            })

        update, context = asyncio.run(_run_callback(
            base_handlers,
            user_id=user_id,
            callback_data="settings_birthday_evening_time_set",
            user_data={"expecting_backup_email": True},
        ))
        overlap_evening_reply = update.callback_query.message.replies[-1] if update.callback_query.message.replies else {}
        overlap_evening_checks = {
            "blocked": "Finish the current flow" in (overlap_evening_reply.get("text") or ""),
            "birthday_evening_flag_not_set": not context.user_data.get("expecting_birthday_evening_time"),
        }
        print_section("flow_overlap_guard_evening", {
            "reply": overlap_evening_reply,
            "checks": overlap_evening_checks,
        })
        if not all(overlap_evening_checks.values()):
            _log_problem("settings_mail_overlap_guard_evening_failed", {
                "checks": overlap_evening_checks,
                "reply": overlap_evening_reply,
            })

        logging_checks = {
            "no_raw_email_in_payloads": not any(_payload_contains_email(evt.get("payload")) for evt in fake_storage.events),
        }
        print_section("logging_policy", {
            "event_count": len(fake_storage.events),
            "checks": logging_checks,
        })
        if not all(logging_checks.values()):
            _log_problem("settings_mail_logging_policy_failed", {
                "checks": logging_checks,
                "events": fake_storage.events,
            })

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        # Restore SMTP host
        if _saved_smtp_host is None:
            os.environ.pop("BOT_SMTP_HOST", None)
        else:
            os.environ["BOT_SMTP_HOST"] = _saved_smtp_host
        if had_mainbot:
            sys.modules["mainbot"] = original_mainbot
        else:
            sys.modules.pop("mainbot", None)
        _DBG = None
        _RUNTIME_MAINBOT = None
        _RUNTIME_STORAGE = None

    flow_ok = not dbg.has_problem(
        "settings_mail_set_prompt_with_email_failed",
        "settings_mail_set_prompt_without_email_failed",
        "settings_mail_set_prompt_whitespace_email_failed",
        "settings_mail_clear_failed",
        "settings_mail_set_cancel_failed",
        "settings_mail_enable_failed",
        "settings_mail_toggle_whitespace_email_failed",
        "settings_mail_status_with_email_failed",
        "settings_mail_status_without_email_failed",
        "settings_mail_send_smtp_unavailable_single_answer_failed",
        "settings_mail_overlap_guard_failed",
        "settings_mail_overlap_guard_evening_failed",
        "settings_mail_logging_policy_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"flow: {'OK' if flow_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
