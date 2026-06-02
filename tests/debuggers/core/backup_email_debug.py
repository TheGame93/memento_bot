#!/usr/bin/env python3
import asyncio
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from io import BytesIO


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

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "backup_email_debug"
FEATURE_TITLE = "Email Backups"

_DBG = None


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


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.storage import StorageManager
            from modules import constants as C
            from modules.backup_core.constants import MAX_EMAIL_SEND_HISTORY
            from modules.backup_core.email_backup import (
                build_email_backup_archive,
                describe_monthly_backup_schedule,
                describe_monthly_reminder_schedule,
                normalize_email_address,
                send_backup_email,
            )
            from modules.backup_core.manifest import validate_manifest
            from modules.handlers.base import (
                build_backup_email_sent_notification,
                build_mail_backup_reminder_message,
                build_mail_backup_reminder_keyboard,
                build_mail_backup_keyboard,
                build_mail_backup_status,
                build_mail_set_prompt_message,
                build_mail_set_prompt_keyboard,
            )
            from modules.scheduler_core import coordinator as scheduler_coordinator
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "data")

            storage = StorageManager(base_data_dir=data_dir)
            user_id = "debug_user_1001"
            user_dir = os.path.join(data_dir, user_id)
            try:
                storage.setup_user_space(user_id)
                storage.save_alert(user_id, {
                    "title": "Email Backup",
                    "type": 5,
                    "type_name": "One Time",
                    "schedule": {"date": "10/10/2030", "time": "10:00"},
                    "pre_alerts": [],
                    "tags": [],
                })

                img_path = os.path.join(user_dir, "images", "photo.jpg")
                with open(img_path, "wb") as handle:
                    handle.write(b"fakeimage")

                user_log_path = storage.get_user_event_log_path(user_id)
                os.makedirs(os.path.dirname(user_log_path), exist_ok=True)
                with open(user_log_path, "w", encoding="utf-8") as handle:
                    handle.write('{"event": "email"}\n')

                snapshot = storage.get_user_snapshot(
                    user_id,
                    include_images=True,
                    include_logs=False,
                    ensure_space=True,
                )
                payload, manifest_data = build_email_backup_archive(snapshot)

                valid, errors = validate_manifest(manifest_data)
                print_section("manifest_validation", {"valid": valid, "errors": errors})
                if not valid:
                    _log_problem("email_backup_manifest", {"errors": errors})

                with zipfile.ZipFile(BytesIO(payload), "r") as inner:
                    names = set(inner.namelist())

                checks = {
                    "has_alerts": "alerts.json" in names,
                    "has_manifest": "manifest.json" in names,
                    "has_log": "logs/events.log" in names,
                    "has_image": "images/photo.jpg" in names,
                }

                print_section("archive_checks", {"checks": checks})

                if not (checks["has_alerts"] and checks["has_manifest"] and checks["has_image"]):
                    _log_problem("email_backup_missing", {"checks": checks})
                if checks["has_log"]:
                    _log_problem("email_backup_includes_logs", {"checks": checks})

                includes = (manifest_data or {}).get("includes") or {}
                include_checks = {
                    "alerts_true": includes.get("alerts") is True,
                    "images_true": includes.get("images") is True,
                    "logs_false": includes.get("logs") is False,
                }
                print_section("manifest_includes", {"includes": includes, "checks": include_checks})
                if not all(include_checks.values()):
                    _log_problem("email_backup_manifest_includes_failed", {
                        "includes": includes,
                        "checks": include_checks,
                    })

                # Overflow path must use constants cap and return top_images metadata.
                send_globals = send_backup_email.__globals__
                original_limit = C.EMAIL_BACKUP_MAX_ATTACHMENT_BYTES
                original_send_limit = send_globals.get("EMAIL_BACKUP_MAX_ATTACHMENT_BYTES")
                original_smtp_host = os.environ.get("BOT_SMTP_HOST")
                try:
                    os.environ["BOT_SMTP_HOST"] = "smtp.debug.test"
                    C.EMAIL_BACKUP_MAX_ATTACHMENT_BYTES = 32
                    send_globals["EMAIL_BACKUP_MAX_ATTACHMENT_BYTES"] = 32
                    overflow_result = send_backup_email(
                        storage,
                        user_id,
                        "overflow@example.com",
                        now=datetime(2026, 4, 1, 1, 0, 0),
                        reason="monthly",
                    )
                finally:
                    if original_smtp_host is None:
                        os.environ.pop("BOT_SMTP_HOST", None)
                    else:
                        os.environ["BOT_SMTP_HOST"] = original_smtp_host
                    C.EMAIL_BACKUP_MAX_ATTACHMENT_BYTES = original_limit
                    send_globals["EMAIL_BACKUP_MAX_ATTACHMENT_BYTES"] = original_send_limit

                overflow_top_images = overflow_result.get("top_images") or []
                overflow_checks = {
                    "sent_false": overflow_result.get("sent") is False,
                    "error_code": overflow_result.get("error") == "attachment_too_large",
                    "top_images_present": bool(overflow_top_images),
                    "top_images_limited": len(overflow_top_images) <= 10,
                    "uses_user_relative_paths": all(
                        isinstance(item.get("filename"), str)
                        and item.get("filename", "").startswith("images/")
                        for item in overflow_top_images
                    ),
                }
                print_section("overflow_top_images", {
                    "result": overflow_result,
                    "checks": overflow_checks,
                })
                if not all(overflow_checks.values()):
                    _log_problem("email_backup_overflow_top_images_failed", {
                        "result": overflow_result,
                        "checks": overflow_checks,
                    })

                reminder_message = build_mail_backup_reminder_message({"email_address": None})
                reminder_keyboard = build_mail_backup_reminder_keyboard({
                    "email_reminder_disabled": False,
                })
                reminder_labels = [btn.text for row in reminder_keyboard.inline_keyboard for btn in row]
                reminder_checks = {
                    "message_has_title": "Mail Backup" in reminder_message,
                    "message_mentions_not_set": "Email: Not set" in reminder_message,
                    "has_settings": any("backup-via-mail settings" in label for label in reminder_labels),
                    "has_disable": any("don't want to backup" in label for label in reminder_labels),
                    "only_two_buttons": len(reminder_labels) == 2,
                }
                print_section("reminder_ui", {"labels": reminder_labels, "checks": reminder_checks})
                if not all(reminder_checks.values()):
                    _log_problem("email_backup_reminder_ui_failed", {
                        "checks": reminder_checks,
                        "labels": reminder_labels,
                    })

                settings_keyboard = build_mail_backup_keyboard({
                    "email_reminder_disabled": False,
                    "email_enabled": False,
                    "email_address": None,
                })
                settings_rows = settings_keyboard.inline_keyboard
                settings_labels = [btn.text for row in settings_rows for btn in row]
                settings_checks = {
                    "has_set_mail": any("Set Mail" in label for label in settings_labels),
                    "has_reminder_toggle": any("reminder to set the mail" in label for label in settings_labels),
                    "has_backup_toggle": any("Mail Backup" in label for label in settings_labels),
                    "has_back": any(label == "⬅️ Back" for label in settings_labels),
                    "send_now_hidden_without_email": not any("Send Backup Now" in label for label in settings_labels),
                    "layout_first_row_single": bool(settings_rows) and len(settings_rows[0]) == 1,
                    "layout_last_row_single": bool(settings_rows) and len(settings_rows[-1]) == 1,
                }
                print_section("settings_ui", {
                    "labels": settings_labels,
                    "row_lengths": [len(row) for row in settings_rows],
                    "checks": settings_checks,
                })
                if not all(settings_checks.values()):
                    _log_problem("email_backup_settings_ui_failed", {
                        "checks": settings_checks,
                        "labels": settings_labels,
                        "row_lengths": [len(row) for row in settings_rows],
                    })

                settings_with_email_keyboard = build_mail_backup_keyboard({
                    "email_reminder_disabled": False,
                    "email_enabled": False,
                    "email_address": "backup@example.com",
                })
                settings_with_email_rows = settings_with_email_keyboard.inline_keyboard
                settings_with_email_labels = [
                    btn.text for row in settings_with_email_rows for btn in row
                ]
                settings_with_email_checks = {
                    "has_set_mail": any("Set Mail" in label for label in settings_with_email_labels),
                    "has_backup_toggle": any("Mail Backup" in label for label in settings_with_email_labels),
                    "has_back": any(label == "⬅️ Back" for label in settings_with_email_labels),
                    "send_now_present": any("Send Backup Now" in label for label in settings_with_email_labels),
                    "row_two_has_two_buttons": len(settings_with_email_rows[0]) == 2 if settings_with_email_rows else False,
                }
                print_section("settings_ui_with_email", {
                    "labels": settings_with_email_labels,
                    "row_lengths": [len(row) for row in settings_with_email_rows],
                    "checks": settings_with_email_checks,
                })
                if not all(settings_with_email_checks.values()):
                    _log_problem("email_backup_settings_ui_with_email_failed", {
                        "checks": settings_with_email_checks,
                        "labels": settings_with_email_labels,
                        "row_lengths": [len(row) for row in settings_with_email_rows],
                    })
                set_prompt_with_email = build_mail_set_prompt_message({"email_address": "test@example.com"})
                set_prompt_without_email = build_mail_set_prompt_message({"email_address": None})
                set_prompt_whitespace_email = build_mail_set_prompt_message({"email_address": "   "})
                set_prompt_keyboard_with_email = build_mail_set_prompt_keyboard({"email_address": "test@example.com"})
                set_prompt_keyboard_without_email = build_mail_set_prompt_keyboard({"email_address": None})
                set_prompt_keyboard_whitespace = build_mail_set_prompt_keyboard({"email_address": "   "})
                set_prompt_labels_with_email = [btn.text for row in set_prompt_keyboard_with_email.inline_keyboard for btn in row]
                set_prompt_labels_without_email = [btn.text for row in set_prompt_keyboard_without_email.inline_keyboard for btn in row]
                set_prompt_labels_whitespace = [btn.text for row in set_prompt_keyboard_whitespace.inline_keyboard for btn in row]
                set_prompt_checks = {
                    "message_with_email_exact": set_prompt_with_email
                    == "Current email address: test@example.com\nSend your new email address now.",
                    "message_without_email_exact": set_prompt_without_email
                    == "Current email address: Not set\nSend your new email address now.",
                    "message_whitespace_email_exact": set_prompt_whitespace_email
                    == "Current email address: Not set\nSend your new email address now.",
                    "with_email_has_clear": any("Clear Email Address" in label for label in set_prompt_labels_with_email),
                    "with_email_has_cancel": any("Cancel Operation" in label for label in set_prompt_labels_with_email),
                    "with_email_rows_two": len(set_prompt_keyboard_with_email.inline_keyboard) == 2,
                    "without_email_clear_hidden": not any("Clear Email Address" in label for label in set_prompt_labels_without_email),
                    "without_email_has_cancel": any("Cancel Operation" in label for label in set_prompt_labels_without_email),
                    "without_email_single_row": len(set_prompt_keyboard_without_email.inline_keyboard) == 1,
                    "whitespace_clear_hidden": not any("Clear Email Address" in label for label in set_prompt_labels_whitespace),
                    "whitespace_has_cancel": any("Cancel Operation" in label for label in set_prompt_labels_whitespace),
                    "whitespace_single_row": len(set_prompt_keyboard_whitespace.inline_keyboard) == 1,
                }
                print_section("set_prompt_ui", {
                    "with_email": set_prompt_with_email,
                    "without_email": set_prompt_without_email,
                    "whitespace_email": set_prompt_whitespace_email,
                    "labels_with_email": set_prompt_labels_with_email,
                    "labels_without_email": set_prompt_labels_without_email,
                    "labels_whitespace": set_prompt_labels_whitespace,
                    "checks": set_prompt_checks,
                })
                if not all(set_prompt_checks.values()):
                    _log_problem("email_backup_set_prompt_ui_failed", {
                        "checks": set_prompt_checks,
                        "labels_with_email": set_prompt_labels_with_email,
                        "labels_without_email": set_prompt_labels_without_email,
                        "labels_whitespace": set_prompt_labels_whitespace,
                        "with_email": set_prompt_with_email,
                        "without_email": set_prompt_without_email,
                    })

                schedule_label = describe_monthly_backup_schedule()
                reminder_schedule_label = describe_monthly_reminder_schedule()

                # Ensure SMTP appears configured for the following status checks
                _saved_smtp_host = os.environ.get("BOT_SMTP_HOST")
                os.environ["BOT_SMTP_HOST"] = "smtp.debug.test"

                status_message, status_keyboard = build_mail_backup_status({
                    "email_enabled": False,
                    "email_address": None,
                    "last_email_sent": "2026-02-22T23:19:09.021816",
                    "email_reminder_disabled": False,
                }, size_bytes=123456)
                status_labels = [btn.text for row in status_keyboard.inline_keyboard for btn in row]
                status_checks = {
                    "has_reminder_line": "Reminder to setup the mail: <b>Enabled ✅</b>" in status_message,
                    "has_backup_line": "Backup via mail: <b>Disabled ⛔️</b>" in status_message,
                    "has_email_line": "Email: Not set" in status_message,
                    "has_last_sent_line": "Last backup sent: 2026-02-22T23:19:09.021816" in status_message,
                    "has_reminder_schedule": f"When: <b>{reminder_schedule_label}</b>" in status_message,
                    "has_backup_toggle": any("Mail Backup" in label for label in status_labels),
                    "has_size_line": "Size of data to backup:" in status_message,
                }
                print_section("status_ui", {
                    "message": status_message,
                    "labels": status_labels,
                    "checks": status_checks,
                })
                if not all(status_checks.values()):
                    _log_problem("email_backup_status_ui_failed", {
                        "checks": status_checks,
                        "message": status_message,
                        "labels": status_labels,
                    })

                enabled_status_message, _enabled_status_keyboard = build_mail_backup_status({
                    "email_enabled": True,
                    "email_address": "set@example.com",
                    "last_email_sent": None,
                    "email_reminder_disabled": False,
                }, size_bytes=123456)
                enabled_no_email_message, _enabled_no_email_keyboard = build_mail_backup_status({
                    "email_enabled": True,
                    "email_address": None,
                    "last_email_sent": None,
                    "email_reminder_disabled": False,
                }, size_bytes=123456)
                reminder_disabled_message, _reminder_disabled_keyboard = build_mail_backup_status({
                    "email_enabled": False,
                    "email_address": None,
                    "last_email_sent": None,
                    "email_reminder_disabled": True,
                }, size_bytes=123456)
                whitespace_email_message, _whitespace_email_keyboard = build_mail_backup_status({
                    "email_enabled": False,
                    "email_address": "   ",
                    "last_email_sent": None,
                    "email_reminder_disabled": False,
                }, size_bytes=123456)
                schedule_checks = {
                    "enabled_shows_schedule": schedule_label in enabled_status_message,
                    "disabled_hides_schedule": schedule_label not in status_message,
                    "enabled_no_email_shows_schedule": schedule_label in enabled_no_email_message,
                    "enabled_hides_reminder_line": "Reminder to setup the mail:" not in enabled_status_message,
                    "enabled_no_email_hides_reminder_line": "Reminder to setup the mail:" not in enabled_no_email_message,
                    "reminder_schedule_hidden_with_email": reminder_schedule_label not in enabled_status_message,
                    "reminder_schedule_hidden_when_disabled": reminder_schedule_label not in reminder_disabled_message,
                    "spam_note_present_when_email_set": "check the SPAM folder" in enabled_status_message,
                    "spam_note_hidden_without_email": "check the SPAM folder" not in whitespace_email_message,
                }
                whitespace_checks = {
                    "whitespace_email_rendered_not_set": "Email: Not set" in whitespace_email_message,
                    "whitespace_email_reminder_schedule_present": reminder_schedule_label in whitespace_email_message,
                }
                print_section("status_schedule_ui", {
                    "schedule_label": schedule_label,
                    "reminder_schedule_label": reminder_schedule_label,
                    "enabled_status_message": enabled_status_message,
                    "enabled_no_email_message": enabled_no_email_message,
                    "reminder_disabled_message": reminder_disabled_message,
                    "checks": schedule_checks,
                    "whitespace_checks": whitespace_checks,
                    "whitespace_email_message": whitespace_email_message,
                })
                if not all(schedule_checks.values()):
                    _log_problem("email_backup_schedule_ui_failed", {
                        "checks": schedule_checks,
                        "schedule_label": schedule_label,
                        "reminder_schedule_label": reminder_schedule_label,
                        "enabled_status_message": enabled_status_message,
                        "enabled_no_email_message": enabled_no_email_message,
                        "reminder_disabled_message": reminder_disabled_message,
                    })
                if not all(whitespace_checks.values()):
                    _log_problem("email_backup_whitespace_email_handling_failed", {
                        "checks": whitespace_checks,
                        "message": whitespace_email_message,
                        "reminder_schedule_label": reminder_schedule_label,
                    })

                # Restore SMTP host after status-with-smtp checks
                if _saved_smtp_host is None:
                    os.environ.pop("BOT_SMTP_HOST", None)
                else:
                    os.environ["BOT_SMTP_HOST"] = _saved_smtp_host

                previous_host = os.environ.get("BOT_SMTP_HOST")
                previous_port = os.environ.get("BOT_SMTP_PORT")
                os.environ["BOT_SMTP_HOST"] = "smtp.example.com"
                os.environ["BOT_SMTP_PORT"] = "not_a_number"
                try:
                    port_result = send_backup_email(storage, user_id, "test@example.com")
                finally:
                    if previous_host is None:
                        os.environ.pop("BOT_SMTP_HOST", None)
                    else:
                        os.environ["BOT_SMTP_HOST"] = previous_host
                    if previous_port is None:
                        os.environ.pop("BOT_SMTP_PORT", None)
                    else:
                        os.environ["BOT_SMTP_PORT"] = previous_port

                port_checks = {
                    "sent_false": port_result.get("sent") is False,
                    "error_smtp_port_invalid": port_result.get("error") == "smtp_port_invalid",
                }
                print_section("smtp_port_checks", {"result": port_result, "checks": port_checks})
                if not all(port_checks.values()):
                    _log_problem("smtp_port_validation_failed", {
                        "result": port_result,
                        "checks": port_checks,
                    })

                return_enrichment_checks = {
                    "no_from_email_on_error": "from_email" not in port_result,
                    "no_to_email_on_error": "to_email" not in port_result,
                    "no_sent_at_on_error": "sent_at" not in port_result,
                }
                print_section("return_enrichment_checks", {
                    "result_keys": list(port_result.keys()),
                    "checks": return_enrichment_checks,
                })
                if not all(return_enrichment_checks.values()):
                    _log_problem("email_backup_return_enrichment_failed", {
                        "result_keys": list(port_result.keys()),
                        "checks": return_enrichment_checks,
                    })

                missing_email_result = send_backup_email(storage, user_id, "   ")
                missing_email_checks = {
                    "sent_false": missing_email_result.get("sent") is False,
                    "error_email_missing": missing_email_result.get("error") == "email_missing",
                }
                print_section("email_missing_checks", {
                    "result": missing_email_result,
                    "checks": missing_email_checks,
                })
                if not all(missing_email_checks.values()):
                    _log_problem("email_backup_missing_email_validation_failed", {
                        "result": missing_email_result,
                        "checks": missing_email_checks,
                    })

                # Malformed history should be sanitized on successful send writes
                previous_host = os.environ.get("BOT_SMTP_HOST")
                previous_port = os.environ.get("BOT_SMTP_PORT")
                previous_tls = os.environ.get("BOT_SMTP_TLS")
                previous_ssl = os.environ.get("BOT_SMTP_SSL")
                previous_user = os.environ.get("BOT_SMTP_USER")
                previous_pass = os.environ.get("BOT_SMTP_PASS")
                previous_from = os.environ.get("BOT_SMTP_FROM")
                send_globals = send_backup_email.__globals__
                original_send_email = send_globals.get("_send_email")
                original_log_system = send_globals.get("log_system")
                original_update_backup_prefs = storage.update_backup_prefs
                try:
                    os.environ["BOT_SMTP_HOST"] = "smtp.example.com"
                    os.environ["BOT_SMTP_PORT"] = "587"
                    os.environ["BOT_SMTP_TLS"] = "0"
                    os.environ["BOT_SMTP_SSL"] = "0"
                    os.environ["BOT_SMTP_USER"] = ""
                    os.environ["BOT_SMTP_PASS"] = ""
                    os.environ["BOT_SMTP_FROM"] = "backup@example.com"

                    def _fake_send_email(message, config):
                        return None

                    send_globals["_send_email"] = _fake_send_email
                    storage.update_backup_prefs(user_id, {
                        "email_send_history": {"legacy": "bad_shape"},
                    })
                    repaired_result = send_backup_email(
                        storage,
                        user_id,
                        "repair@example.com",
                        now=datetime(2026, 3, 28, 3, 0, 0),
                        reason="manual",
                    )
                    repaired_history = storage.get_backup_prefs(user_id).get("email_send_history")
                    repaired_checks = {
                        "send_succeeds": repaired_result.get("sent") is True,
                        "history_is_list": isinstance(repaired_history, list),
                        "history_len_one": isinstance(repaired_history, list) and len(repaired_history) == 1,
                        "history_entry_dict": isinstance(repaired_history, list) and bool(repaired_history) and isinstance(repaired_history[0], dict),
                        "history_entry_email": isinstance(repaired_history, list) and bool(repaired_history) and repaired_history[0].get("to_email") == "repair@example.com",
                    }
                    print_section("history_repair_on_send", {
                        "result": repaired_result,
                        "history": repaired_history,
                        "checks": repaired_checks,
                    })
                    if not all(repaired_checks.values()):
                        _log_problem("email_backup_history_repair_on_send_failed", {
                            "result": repaired_result,
                            "history": repaired_history,
                            "checks": repaired_checks,
                        })

                    storage.update_backup_prefs(user_id, {"email_send_history": []})
                    slot_override_result = send_backup_email(
                        storage,
                        user_id,
                        "slot@example.com",
                        now=datetime(2026, 3, 1, 10, 0, 0),
                        reason="startup_catchup",
                        history_slot_dt=datetime(2026, 2, 28, 3, 0, 0),
                    )
                    slot_history = storage.get_backup_prefs(user_id).get("email_send_history") or []
                    slot_last_entry = slot_history[-1] if slot_history else {}
                    slot_checks = {
                        "send_succeeds": slot_override_result.get("sent") is True,
                        "slot_key_uses_override": slot_last_entry.get("slot_key") == "2026-02",
                        "sent_at_uses_send_time": isinstance(slot_last_entry.get("sent_at"), str)
                        and slot_last_entry.get("sent_at", "").startswith("2026-03-01T10:00:00"),
                    }
                    print_section("history_slot_override_on_send", {
                        "result": slot_override_result,
                        "slot_last_entry": slot_last_entry,
                        "checks": slot_checks,
                    })
                    if not all(slot_checks.values()):
                        _log_problem("email_backup_history_slot_override_failed", {
                            "result": slot_override_result,
                            "slot_last_entry": slot_last_entry,
                            "checks": slot_checks,
                        })

                    # History write warning payload should use reason-code fields only
                    captured_history_logs = []
                    def _capture_backup_log(category, event, payload, level="INFO"):
                        captured_history_logs.append({
                            "category": category,
                            "event": event,
                            "payload": payload,
                            "level": level,
                        })

                    def _failing_update_backup_prefs(target_user_id, updates):
                        if "email_send_history" in (updates or {}):
                            raise RuntimeError("history write failed for debug")
                        return original_update_backup_prefs(target_user_id, updates)

                    send_globals["log_system"] = _capture_backup_log
                    storage.update_backup_prefs = _failing_update_backup_prefs
                    history_warning_result = send_backup_email(
                        storage,
                        user_id,
                        "warning@example.com",
                        now=datetime(2026, 3, 29, 8, 15, 0),
                        reason="monthly",
                    )
                    history_warning_logs = [
                        item for item in captured_history_logs
                        if item.get("event") == "email_backup_history_write_failed"
                    ]
                    history_warning_payload = (
                        history_warning_logs[-1].get("payload", {})
                        if history_warning_logs else {}
                    )
                    history_warning_checks = {
                        "send_still_successful": history_warning_result.get("sent") is True,
                        "warning_emitted": bool(history_warning_logs),
                        "has_reason_code": history_warning_payload.get("reason_code") == "history_write_failed",
                        "has_error_class": history_warning_payload.get("error_class") == "RuntimeError",
                        "no_raw_error_field": "error" not in history_warning_payload,
                    }
                    print_section("history_write_warning_payload", {
                        "result": history_warning_result,
                        "payload": history_warning_payload,
                        "checks": history_warning_checks,
                    })
                    if not all(history_warning_checks.values()):
                        _log_problem("email_backup_history_warning_payload_failed", {
                            "result": history_warning_result,
                            "payload": history_warning_payload,
                            "checks": history_warning_checks,
                        })
                    storage.update_backup_prefs = original_update_backup_prefs
                    send_globals["log_system"] = original_log_system
                finally:
                    if previous_host is None:
                        os.environ.pop("BOT_SMTP_HOST", None)
                    else:
                        os.environ["BOT_SMTP_HOST"] = previous_host
                    if previous_port is None:
                        os.environ.pop("BOT_SMTP_PORT", None)
                    else:
                        os.environ["BOT_SMTP_PORT"] = previous_port
                    if previous_tls is None:
                        os.environ.pop("BOT_SMTP_TLS", None)
                    else:
                        os.environ["BOT_SMTP_TLS"] = previous_tls
                    if previous_ssl is None:
                        os.environ.pop("BOT_SMTP_SSL", None)
                    else:
                        os.environ["BOT_SMTP_SSL"] = previous_ssl
                    if previous_user is None:
                        os.environ.pop("BOT_SMTP_USER", None)
                    else:
                        os.environ["BOT_SMTP_USER"] = previous_user
                    if previous_pass is None:
                        os.environ.pop("BOT_SMTP_PASS", None)
                    else:
                        os.environ["BOT_SMTP_PASS"] = previous_pass
                    if previous_from is None:
                        os.environ.pop("BOT_SMTP_FROM", None)
                    else:
                        os.environ["BOT_SMTP_FROM"] = previous_from
                    if original_send_email is not None:
                        send_globals["_send_email"] = original_send_email
                    else:
                        send_globals.pop("_send_email", None)
                    if original_log_system is not None:
                        send_globals["log_system"] = original_log_system
                    else:
                        send_globals.pop("log_system", None)
                    storage.update_backup_prefs = original_update_backup_prefs

                email_checks = {
                    "emoji_rejected": normalize_email_address("test😀@example.com") is None,
                    "unicode_domain_rejected": normalize_email_address("test@exämple.com") is None,
                    "missing_dot_rejected": normalize_email_address("test@example") is None,
                    "short_tld_rejected": normalize_email_address("test@example.c") is None,
                    "plus_tag_ok": normalize_email_address("Name+tag@Example.COM") == "Name+tag@example.com",
                }
                print_section("email_validation_checks", {"checks": email_checks})
                if not all(email_checks.values()):
                    _log_problem("email_backup_validation_failed", {"checks": email_checks})

                # -------------------------------------------------------
                # SMTP unavailability: keyboard and status message checks
                # -------------------------------------------------------

                # Keyboard with smtp_available=False should hide toggle and send
                smtp_off_kb = build_mail_backup_keyboard(
                    {"email_enabled": True, "email_address": "a@b.com", "email_reminder_disabled": True},
                    smtp_available=False,
                )
                smtp_off_labels = [btn.text for row in smtp_off_kb.inline_keyboard for btn in row]
                smtp_off_kb_checks = {
                    "no_send_button": not any("Send Backup Now" in l for l in smtp_off_labels),
                    "no_toggle_button": not any("Mail Backup" in l for l in smtp_off_labels),
                    "set_mail_still_present": any("Set Mail" in l for l in smtp_off_labels),
                    "back_present": any(l == "⬅️ Back" for l in smtp_off_labels),
                }
                print_section("smtp_unavailable_keyboard", {
                    "labels": smtp_off_labels,
                    "checks": smtp_off_kb_checks,
                })
                if not all(smtp_off_kb_checks.values()):
                    _log_problem("smtp_unavailable_keyboard_failed", {
                        "checks": smtp_off_kb_checks,
                        "labels": smtp_off_labels,
                    })

                # Status message when SMTP is unconfigured should show warning
                saved_host = os.environ.get("BOT_SMTP_HOST")
                try:
                    os.environ.pop("BOT_SMTP_HOST", None)
                    smtp_off_msg, smtp_off_msg_kb = build_mail_backup_status(
                        {"email_enabled": False, "email_address": None,
                         "last_email_sent": None, "email_reminder_disabled": False},
                        size_bytes=0,
                    )
                    smtp_off_msg_labels = [btn.text for row in smtp_off_msg_kb.inline_keyboard for btn in row]
                    smtp_off_status_checks = {
                        "has_warning": "Service unavailable" in smtp_off_msg,
                        "has_contact_line": "Contact the bot administrator" in smtp_off_msg,
                        "kb_no_toggle": not any("Mail Backup" in l for l in smtp_off_msg_labels),
                        "kb_no_send": not any("Send Backup Now" in l for l in smtp_off_msg_labels),
                        "kb_has_back": any(l == "⬅️ Back" for l in smtp_off_msg_labels),
                    }
                    print_section("smtp_unavailable_status", {
                        "message_snippet": smtp_off_msg[:400],
                        "labels": smtp_off_msg_labels,
                        "checks": smtp_off_status_checks,
                    })
                    if not all(smtp_off_status_checks.values()):
                        _log_problem("smtp_unavailable_status_failed", {
                            "checks": smtp_off_status_checks,
                            "message_snippet": smtp_off_msg[:400],
                            "labels": smtp_off_msg_labels,
                        })
                finally:
                    if saved_host is None:
                        os.environ.pop("BOT_SMTP_HOST", None)
                    else:
                        os.environ["BOT_SMTP_HOST"] = saved_host

                # History storage round-trip and truncation
                history_full = [
                    {
                        "sent_at": f"2024-{(i % 12) + 1:02d}-28T03:00:00",
                        "to_email": f"hist{i}@example.com",
                        "from_email": "backup@example.com",
                        "size_bytes": 1024,
                        "reason": "monthly",
                        "slot_key": f"2024-{(i % 12) + 1:02d}",
                    }
                    for i in range(MAX_EMAIL_SEND_HISTORY)
                ]
                storage.update_backup_prefs(user_id, {"email_send_history": history_full})
                history_readback = storage.get_backup_prefs(user_id).get("email_send_history", [])
                extra_entry = {
                    "sent_at": "2026-03-28T03:00:00",
                    "to_email": "new@example.com",
                    "from_email": "backup@example.com",
                    "size_bytes": 2048,
                    "reason": "monthly",
                    "slot_key": "2026-03",
                }
                history_extended = list(history_readback) + [extra_entry]
                if len(history_extended) > MAX_EMAIL_SEND_HISTORY:
                    history_extended = history_extended[-MAX_EMAIL_SEND_HISTORY:]
                storage.update_backup_prefs(user_id, {"email_send_history": history_extended})
                history_after = storage.get_backup_prefs(user_id).get("email_send_history", [])
                truncation_checks = {
                    "readback_length": len(history_readback) == MAX_EMAIL_SEND_HISTORY,
                    "after_truncation_length": len(history_after) == MAX_EMAIL_SEND_HISTORY,
                    "newest_entry_kept": bool(history_after) and history_after[-1].get("slot_key") == "2026-03",
                    "oldest_entry_dropped": bool(history_after) and history_after[0].get("slot_key") != history_full[0].get("slot_key"),
                }
                print_section("history_truncation_checks", {
                    "readback_length": len(history_readback),
                    "after_truncation_length": len(history_after),
                    "newest_slot": history_after[-1].get("slot_key") if history_after else None,
                    "oldest_slot": history_after[0].get("slot_key") if history_after else None,
                    "checks": truncation_checks,
                })
                if not all(truncation_checks.values()):
                    _log_problem("email_backup_history_truncation_failed", {
                        "checks": truncation_checks,
                        "readback_length": len(history_readback),
                        "after_truncation_length": len(history_after),
                    })

                # Notification builder checks (all 3 reason variants)
                notif_manual = build_backup_email_sent_notification(
                    from_email="backup@example.com",
                    to_email="user@example.com",
                    size_bytes=45 * 1024 * 1024,
                    reason="manual",
                    sent_at_iso="2026-03-28T03:00:00",
                )
                notif_monthly = build_backup_email_sent_notification(
                    from_email="backup@example.com",
                    to_email="user@example.com",
                    size_bytes=45 * 1024 * 1024,
                    reason="monthly",
                    sent_at_iso="2026-03-28T03:00:00",
                )
                notif_startup = build_backup_email_sent_notification(
                    from_email="backup@example.com",
                    to_email="user@example.com",
                    size_bytes=45 * 1024 * 1024,
                    reason="startup_catchup",
                    sent_at_iso="2026-03-28T03:00:00",
                )
                notif_checks = {
                    "contains_from": "backup@example.com" in notif_manual,
                    "contains_to": "user@example.com" in notif_manual,
                    "contains_size": "45" in notif_manual,
                    "contains_reason_manual": "Manual send" in notif_manual,
                    "contains_reason_monthly": "Scheduled (monthly)" in notif_monthly,
                    "contains_reason_startup": "Startup catch-up" in notif_startup,
                    "under_4096": len(notif_manual) < 4096,
                    "returns_string": isinstance(notif_manual, str),
                    "sent_at_formatted": "2026-03-28 03:00" in notif_manual,
                }
                print_section("notification_builder_checks", {
                    "notif_manual_snippet": notif_manual[:300],
                    "notif_monthly_snippet": notif_monthly[:300],
                    "notif_startup_snippet": notif_startup[:300],
                    "checks": notif_checks,
                })
                if not all(notif_checks.values()):
                    _log_problem("email_backup_notification_builder_failed", {
                        "checks": notif_checks,
                        "notif_manual_snippet": notif_manual[:300],
                    })

                # Monthly job should offload batch work via asyncio.to_thread exactly once
                coordinator_globals = scheduler_coordinator.__dict__
                original_storage = coordinator_globals.get("_storage")
                original_app = coordinator_globals.get("_app")
                original_run_monthly = coordinator_globals.get("run_monthly_email_backups")
                original_coord_to_thread = coordinator_globals["asyncio"].to_thread
                try:
                    to_thread_calls = []
                    sent_notifications = []

                    async def _guard_to_thread(func, *args, **kwargs):
                        to_thread_calls.append({
                            "func": func,
                            "args": args,
                            "kwargs": kwargs,
                        })
                        return func(*args, **kwargs)

                    class _GuardBot:
                        async def send_message(self, *args, **kwargs):
                            sent_notifications.append({
                                "args": args,
                                "kwargs": kwargs,
                            })
                            return None

                    class _GuardApp:
                        def __init__(self):
                            self.bot = _GuardBot()

                    guard_storage = object()

                    def _guard_monthly_backups(storage_obj):
                        return [{
                            "user_id": "debug_user_notify",
                            "result": {
                                "sent": True,
                                "from_email": "backup@example.com",
                                "to_email": "notify@example.com",
                                "bytes": 1024,
                                "sent_at": "2026-03-28T03:00:00",
                            },
                        }]

                    coordinator_globals["asyncio"].to_thread = _guard_to_thread
                    coordinator_globals["_storage"] = guard_storage
                    coordinator_globals["_app"] = _GuardApp()
                    coordinator_globals["run_monthly_email_backups"] = _guard_monthly_backups
                    asyncio.run(scheduler_coordinator._run_email_backup_job())

                    to_thread_guard_checks = {
                        "to_thread_called_once": len(to_thread_calls) == 1,
                        "to_thread_func_matches": bool(to_thread_calls) and to_thread_calls[0].get("func") is _guard_monthly_backups,
                        "to_thread_storage_arg_forwarded": bool(to_thread_calls)
                        and tuple(to_thread_calls[0].get("args") or ()) == (guard_storage,),
                        "notification_still_sent": len(sent_notifications) == 1,
                        "notification_user_id_forwarded": bool(sent_notifications)
                        and sent_notifications[0].get("kwargs", {}).get("chat_id") == "debug_user_notify",
                    }
                    print_section("monthly_job_to_thread_guard", {
                        "to_thread_calls": [
                            {
                                "func_name": getattr(item.get("func"), "__name__", repr(item.get("func"))),
                                "args_count": len(item.get("args") or ()),
                                "kwargs_keys": sorted((item.get("kwargs") or {}).keys()),
                            }
                            for item in to_thread_calls
                        ],
                        "sent_notifications": sent_notifications,
                        "checks": to_thread_guard_checks,
                    })
                    if not all(to_thread_guard_checks.values()):
                        _log_problem("email_backup_monthly_to_thread_guard_failed", {
                            "to_thread_calls_count": len(to_thread_calls),
                            "sent_notifications_count": len(sent_notifications),
                            "checks": to_thread_guard_checks,
                        })
                finally:
                    coordinator_globals["_storage"] = original_storage
                    coordinator_globals["_app"] = original_app
                    coordinator_globals["run_monthly_email_backups"] = original_run_monthly
                    coordinator_globals["asyncio"].to_thread = original_coord_to_thread

                # Notification warning payload should use reason-code fields only
                coordinator_globals = scheduler_coordinator.__dict__
                original_storage = coordinator_globals.get("_storage")
                original_app = coordinator_globals.get("_app")
                original_run_monthly = coordinator_globals.get("run_monthly_email_backups")
                original_should_send_startup_reminder = coordinator_globals.get("should_send_startup_reminder")
                original_should_send_startup_backup = coordinator_globals.get("should_send_startup_backup")
                original_normalize_email = coordinator_globals.get("normalize_email_address")
                original_send_backup_email = coordinator_globals.get("send_backup_email")
                original_coord_log_system = coordinator_globals.get("log_system")
                original_coord_to_thread = coordinator_globals["asyncio"].to_thread
                try:
                    captured_notification_logs = []

                    def _capture_coord_log(category, event, payload, level="INFO"):
                        captured_notification_logs.append({
                            "category": category,
                            "event": event,
                            "payload": payload,
                            "level": level,
                        })

                    async def _direct_to_thread(func, *args, **kwargs):
                        return func(*args, **kwargs)

                    class _FailingBot:
                        async def send_message(self, *args, **kwargs):
                            raise RuntimeError("notify failed for debug")

                    class _StubApp:
                        def __init__(self):
                            self.bot = _FailingBot()

                    class _StubStorage:
                        def get_all_users(self):
                            return ["debug_user_notify"]

                        def is_user_whitelisted(self, user_id):
                            return True

                        def get_backup_prefs(self, user_id):
                            return {"email_enabled": True, "email_address": "notify@example.com"}

                        def update_backup_prefs(self, user_id, updates):
                            return True

                        def log_user_event(self, user_id, event_type, payload):
                            return True

                    def _stub_monthly_backups(storage_obj):
                        return [{
                            "user_id": "debug_user_notify",
                            "result": {
                                "sent": True,
                                "from_email": "backup@example.com",
                                "to_email": "notify@example.com",
                                "bytes": 1024,
                                "sent_at": "2026-03-28T03:00:00",
                            },
                        }]

                    def _stub_should_send_startup_reminder(now, prefs):
                        return False, "not_due", now

                    def _stub_should_send_startup_backup(now, prefs):
                        return True, "ok", now

                    def _stub_normalize_email(value):
                        return "notify@example.com"

                    def _stub_send_backup_email(storage_obj, user_id, to_email, **kwargs):
                        return {
                            "sent": True,
                            "from_email": "backup@example.com",
                            "to_email": to_email,
                            "bytes": 2048,
                            "sent_at": "2026-03-28T03:00:00",
                            "reason": "startup_catchup",
                        }

                    coordinator_globals["log_system"] = _capture_coord_log
                    coordinator_globals["asyncio"].to_thread = _direct_to_thread
                    coordinator_globals["_storage"] = _StubStorage()
                    coordinator_globals["_app"] = _StubApp()
                    coordinator_globals["run_monthly_email_backups"] = _stub_monthly_backups
                    asyncio.run(scheduler_coordinator._run_email_backup_job())

                    coordinator_globals["should_send_startup_reminder"] = _stub_should_send_startup_reminder
                    coordinator_globals["should_send_startup_backup"] = _stub_should_send_startup_backup
                    coordinator_globals["normalize_email_address"] = _stub_normalize_email
                    coordinator_globals["send_backup_email"] = _stub_send_backup_email
                    asyncio.run(scheduler_coordinator._run_startup_email_backup_catchup())

                    notification_warning_logs = [
                        item for item in captured_notification_logs
                        if item.get("event") == "email_backup_notification_failed"
                    ]
                    monthly_payload = {}
                    startup_payload = {}
                    for item in notification_warning_logs:
                        payload = item.get("payload", {})
                        source = payload.get("source")
                        if source == "monthly":
                            monthly_payload = payload
                        if source == "startup":
                            startup_payload = payload

                    notification_payload_checks = {
                        "monthly_warning_emitted": bool(monthly_payload),
                        "startup_warning_emitted": bool(startup_payload),
                        "monthly_reason_code": monthly_payload.get("reason_code") == "notification_send_failed",
                        "startup_reason_code": startup_payload.get("reason_code") == "notification_send_failed",
                        "monthly_error_class": monthly_payload.get("error_class") == "RuntimeError",
                        "startup_error_class": startup_payload.get("error_class") == "RuntimeError",
                        "monthly_no_raw_error": "error" not in monthly_payload,
                        "startup_no_raw_error": "error" not in startup_payload,
                    }
                    print_section("notification_warning_payload", {
                        "monthly_payload": monthly_payload,
                        "startup_payload": startup_payload,
                        "checks": notification_payload_checks,
                    })
                    if not all(notification_payload_checks.values()):
                        _log_problem("email_backup_notification_warning_payload_failed", {
                            "monthly_payload": monthly_payload,
                            "startup_payload": startup_payload,
                            "checks": notification_payload_checks,
                        })
                finally:
                    coordinator_globals["_storage"] = original_storage
                    coordinator_globals["_app"] = original_app
                    coordinator_globals["run_monthly_email_backups"] = original_run_monthly
                    coordinator_globals["should_send_startup_reminder"] = original_should_send_startup_reminder
                    coordinator_globals["should_send_startup_backup"] = original_should_send_startup_backup
                    coordinator_globals["normalize_email_address"] = original_normalize_email
                    coordinator_globals["send_backup_email"] = original_send_backup_email
                    coordinator_globals["log_system"] = original_coord_log_system
                    coordinator_globals["asyncio"].to_thread = original_coord_to_thread

            finally:
                shutil.rmtree(user_dir, ignore_errors=True)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    email_ok = not dbg.has_problem(
        "email_backup_missing",
        "email_backup_manifest",
        "smtp_port_validation_failed",
        "email_backup_includes_images",
        "email_backup_reminder_ui_failed",
        "email_backup_settings_ui_failed",
        "email_backup_settings_ui_with_email_failed",
        "email_backup_set_prompt_ui_failed",
        "email_backup_status_ui_failed",
        "email_backup_schedule_ui_failed",
        "email_backup_whitespace_email_handling_failed",
        "email_backup_missing_email_validation_failed",
        "email_backup_validation_failed",
        "smtp_unavailable_keyboard_failed",
        "smtp_unavailable_status_failed",
        "email_backup_return_enrichment_failed",
        "email_backup_history_repair_on_send_failed",
        "email_backup_history_slot_override_failed",
        "email_backup_history_warning_payload_failed",
        "email_backup_history_truncation_failed",
        "email_backup_notification_builder_failed",
        "email_backup_monthly_to_thread_guard_failed",
        "email_backup_notification_warning_payload_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"archive: {'OK' if email_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
