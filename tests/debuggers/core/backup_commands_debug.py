#!/usr/bin/env python3
import asyncio
import os
import sys
import tempfile
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
SCRIPT_TITLE = "backup_commands_debug"
FEATURE_TITLE = "Backup Command Flow"

IMPORT_ERROR = None
try:
    from telegram.ext import ApplicationHandlerStop
except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
    IMPORT_ERROR = exc

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


class _FakeStorage:
    def __init__(self):
        self.events = []

    def log_user_event(self, user_id, event_type, payload):
        self.events.append({
            "user_id": str(user_id),
            "event": event_type,
            "payload": payload or {},
        })

    def get_alert_by_shortcode(self, user_id, shortcode):
        return None


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyDownloadFile:
    def __init__(self, payload=b"testzip"):
        self.payload = payload

    async def download_to_drive(self, path):
        with open(path, "wb") as handle:
            handle.write(self.payload)


class _DummyDocument:
    def __init__(self, payload=b"testzip", file_name="backup.zip", mime_type="application/zip"):
        self._payload = payload
        self.file_name = file_name
        self.mime_type = mime_type
        self.file_size = len(payload)

    async def get_file(self):
        return _DummyDownloadFile(payload=self._payload)


class _DummyMessage:
    def __init__(self, *, text=None, document=None):
        self.text = text
        self.document = document
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})

    async def reply_document(self, document, **kwargs):
        self.replies.append({"document": True, "kwargs": kwargs})


class _DummyUpdate:
    def __init__(self, *, user_id, text=None, document=None):
        self.effective_user = _DummyUser(user_id)
        self.message = _DummyMessage(text=text, document=document)
        self.effective_message = self.message
        self.callback_query = None


class _DummyContext:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}
        self.args = []
        if _RUNTIME_MAINBOT is not None:
            seed_mainbot_runtime(_RUNTIME_MAINBOT, app=self, storage=_RUNTIME_STORAGE)


def _patch_asyncio_to_thread():
    original = asyncio.to_thread

    async def _sync_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    asyncio.to_thread = _sync_to_thread
    return original


def main():
    global _DBG, _RUNTIME_MAINBOT, _RUNTIME_STORAGE
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg

    original_mainbot = sys.modules.get("mainbot")
    had_mainbot = "mainbot" in sys.modules
    original_to_thread = None

    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        if IMPORT_ERROR is not None:
            dbg.mark_dependency_error(IMPORT_ERROR)
            dbg.finish(exit_on_problems=False)
            return

        with tempfile.TemporaryDirectory() as _tmpdir:
            fake_storage = _FakeStorage()
            runtime_mainbot = types.SimpleNamespace(storage=fake_storage, API_FAILURE_TRACKER=None)
            sys.modules["mainbot"] = runtime_mainbot
            _RUNTIME_MAINBOT = runtime_mainbot
            _RUNTIME_STORAGE = fake_storage
            original_to_thread = _patch_asyncio_to_thread()

            try:
                from modules.handlers import export_import as export_handlers
                from modules.handlers import shortcut_router as shortcut_handlers
                from modules.handlers.base.settings import build_settings_keyboard
                from modules.handlers.base.settings_backup import build_settings_backup_keyboard
            except ModuleNotFoundError as exc:
                dbg.mark_dependency_error(exc)
                dbg.finish(exit_on_problems=False)
                return

            top_settings_labels = [
                btn.text
                for row in build_settings_keyboard().inline_keyboard
                for btn in row
            ]
            top_settings_callbacks = [
                btn.callback_data
                for row in build_settings_keyboard().inline_keyboard
                for btn in row
            ]
            top_settings_checks = {
                "has_backups_button": "🗄️ Backups" in top_settings_labels,
                "uses_settings_backup_callback": "settings_backup" in top_settings_callbacks,
                "legacy_export_removed": "settings_export" not in top_settings_callbacks,
                "legacy_import_removed": "settings_import" not in top_settings_callbacks,
            }
            print_section("settings_top_backups_button", {
                "labels": top_settings_labels,
                "callbacks": top_settings_callbacks,
                "checks": top_settings_checks,
            })
            if not all(top_settings_checks.values()):
                _log_problem("settings_top_backups_button_failed", {
                    "labels": top_settings_labels,
                    "callbacks": top_settings_callbacks,
                    "checks": top_settings_checks,
                })

            backups_callbacks_rows = [
                [btn.callback_data for btn in row]
                for row in build_settings_backup_keyboard().inline_keyboard
            ]
            backups_panel_checks = {
                "row_count_is_four": len(backups_callbacks_rows) == 4,
                "row1_export_import": backups_callbacks_rows[0] == [
                    "settings_backup_export",
                    "settings_backup_import",
                ],
                "row2_mail": len(backups_callbacks_rows) > 1 and backups_callbacks_rows[1] == ["settings_backup_mail"],
                "row3_restore": len(backups_callbacks_rows) > 2 and backups_callbacks_rows[2] == ["settings_backup_restore"],
                "row4_back_home": len(backups_callbacks_rows) > 3 and backups_callbacks_rows[3] == ["settings_home"],
            }
            print_section("settings_backups_keyboard_layout", {
                "rows": backups_callbacks_rows,
                "checks": backups_panel_checks,
            })
            if not all(backups_panel_checks.values()):
                _log_problem("settings_backups_keyboard_layout_failed", {
                    "rows": backups_callbacks_rows,
                    "checks": backups_panel_checks,
                })

            reserved_failures = []
            for cmd in ("/settings", "/alerts"):
                update = _DummyUpdate(user_id=1, text=cmd)
                context = _DummyContext()
                asyncio.run(shortcut_handlers.handle_dynamic_shortcut_command(update, context))
                if update.message.replies:
                    reserved_failures.append({"command": cmd, "replies": update.message.replies})
            print_section("reserved_shortcuts", {"failures": reserved_failures})
            if reserved_failures:
                _log_problem("reserved_shortcut_handling_failed", {"failures": reserved_failures})

            removed_failures = []
            for cmd in ("/export", "/import", "/backup_email", "/setting"):
                update = _DummyUpdate(user_id=1, text=cmd)
                context = _DummyContext()
                asyncio.run(shortcut_handlers.handle_dynamic_shortcut_command(update, context))
                replies = [r.get("text", "") for r in update.message.replies]
                if not any("Shortcut not found" in text for text in replies):
                    removed_failures.append({"command": cmd, "replies": replies})
            print_section("removed_shortcuts", {"failures": removed_failures})
            if removed_failures:
                _log_problem("removed_shortcut_feedback_failed", {"failures": removed_failures})

            unknown_update = _DummyUpdate(user_id=1, text="/abc")
            unknown_context = _DummyContext()
            asyncio.run(shortcut_handlers.handle_dynamic_shortcut_command(unknown_update, unknown_context))
            unknown_replies = [r.get("text", "") for r in unknown_update.message.replies]
            unknown_ok = any("Shortcut not found" in text for text in unknown_replies)
            print_section("unknown_shortcut", {
                "replies": unknown_replies,
                "ok": unknown_ok,
            })
            if not unknown_ok:
                _log_problem("unknown_shortcut_feedback_failed", {"replies": unknown_replies})

            developer_src = ""
            developer_path = os.path.join(ROOT_DIR, "modules", "handlers", "developer.py")
            try:
                with open(developer_path, "r", encoding="utf-8") as handle:
                    developer_src = handle.read()
            except Exception:
                developer_src = ""
            retired_developer_checks = {
                "legacy_backup_failsoft_message": "Backup actions moved to /manage → Backups." in developer_src,
                "legacy_backup_failsoft_back_button": "reply_markup=_back_only_keyboard()" in developer_src,
            }
            print_section("retired_developer_backup_callbacks", {"checks": retired_developer_checks})
            if not all(retired_developer_checks.values()):
                _log_problem("retired_developer_backup_callbacks_failed", {"checks": retired_developer_checks})

            alias_checks = {
                "alias_100_routed": False,
                "alias_1_canonicalized": False,
                "alias_00100_canonicalized": False,
                "missing_alias_expired_message": False,
            }
            admin_calls = []
            original_admin_shortcut = None
            try:
                from modules.handlers import admin as admin_handlers

                original_admin_shortcut = admin_handlers.handle_admin_shortcut_user

                async def _fake_admin_shortcut_user(update, context, target_id):
                    admin_calls.append(str(target_id))

                admin_handlers.handle_admin_shortcut_user = _fake_admin_shortcut_user

                alias_context = _DummyContext()
                alias_context.user_data[shortcut_handlers.LIST_CONTEXT_KEY] = {
                    "source": "admin_users",
                    "alias_map": {
                        "01": "u01",
                        "100": "u100",
                    },
                }

                alias_update_100 = _DummyUpdate(user_id=1, text="/100")
                asyncio.run(shortcut_handlers.handle_dynamic_shortcut_command(alias_update_100, alias_context))

                alias_update_1 = _DummyUpdate(user_id=1, text="/1")
                asyncio.run(shortcut_handlers.handle_dynamic_shortcut_command(alias_update_1, alias_context))

                alias_update_00100 = _DummyUpdate(user_id=1, text="/00100")
                asyncio.run(shortcut_handlers.handle_dynamic_shortcut_command(alias_update_00100, alias_context))

                alias_update_999 = _DummyUpdate(user_id=1, text="/999")
                asyncio.run(shortcut_handlers.handle_dynamic_shortcut_command(alias_update_999, alias_context))

                alias_checks.update({
                    "alias_100_routed": len(admin_calls) >= 1 and admin_calls[0] == "u100",
                    "alias_1_canonicalized": len(admin_calls) >= 2 and admin_calls[1] == "u01",
                    "alias_00100_canonicalized": len(admin_calls) >= 3 and admin_calls[2] == "u100",
                    "missing_alias_expired_message": any(
                        "local shortcut expired" in (r.get("text", "").lower())
                        for r in alias_update_999.message.replies
                    ),
                })
                print_section("local_alias_shortcuts", {
                    "admin_calls": admin_calls,
                    "missing_alias_replies": alias_update_999.message.replies,
                    "checks": alias_checks,
                })
                if not all(alias_checks.values()):
                    _log_problem("local_alias_shortcuts_failed", {
                        "admin_calls": admin_calls,
                        "checks": alias_checks,
                    })
            finally:
                if original_admin_shortcut is not None:
                    admin_handlers.handle_admin_shortcut_user = original_admin_shortcut

            original_import_fn = export_handlers.import_user_archive
            original_inspect_archive = export_handlers.inspect_archive
            original_diff_archive_vs_current = export_handlers.diff_archive_vs_current
            try:
                import_calls = []
                export_handlers.import_user_archive = lambda storage, user_id, path: import_calls.append((user_id, path)) or {"ok": True}
                export_handlers.inspect_archive = lambda path, user_id: {
                    "ok": True,
                    "size_bytes": 1234,
                    "source": "settings",
                    "retention_bucket": "manual",
                    "alert_count": 1,
                    "birthday_count": 0,
                    "tag_count": 0,
                    "image_count": 0,
                    "manifest": {"schema_version": "1.0"},
                }
                export_handlers.diff_archive_vs_current = lambda storage, user_id, path: {
                    "ok": True,
                    "current_alert_count": 0,
                    "archive_alert_count": 1,
                    "current_birthday_count": 0,
                    "archive_birthday_count": 0,
                    "current_image_count": 0,
                    "archive_image_count": 0,
                }

                step1_update = _DummyUpdate(user_id=1, text=None, document=None)
                step1_context = _DummyContext()
                asyncio.run(export_handlers._run_import_flow(step1_update, step1_context, source="settings"))

                step1_prompt = [r.get("text", "") for r in step1_update.message.replies]
                step1_flag = bool(step1_context.user_data.get("expecting_import_archive"))

                step2_update = _DummyUpdate(user_id=1, document=_DummyDocument())
                step2_context = _DummyContext()
                step2_context.user_data = dict(step1_context.user_data)
                try:
                    asyncio.run(export_handlers.handle_import_document_upload(step2_update, step2_context))
                except ApplicationHandlerStop:
                    pass

                step2_replies = [r.get("text", "") for r in step2_update.message.replies]
                step2_flag_cleared = not step2_context.user_data.get("expecting_import_archive")
                step2_preview = any("Backup Import Preview" in text for text in step2_replies)
                step2_session = step2_context.user_data.get("backup_import_session") or {}

                flow_checks = {
                    "step1_prompted": any("Send a backup archive" in text for text in step1_prompt),
                    "step1_flag_set": step1_flag,
                    "step2_preview_reply": step2_preview,
                    "step2_flag_cleared": step2_flag_cleared,
                    "step2_session_stored": isinstance(step2_session, dict) and bool(step2_session.get("temp_path")),
                    "import_not_applied_before_confirm": not import_calls,
                }
                print_section("import_followup_flow", {
                    "step1_replies": step1_prompt,
                    "step2_replies": step2_replies,
                    "checks": flow_checks,
                })
                export_handlers.discard_backup_import_session(step2_context.user_data)
                if not all(flow_checks.values()):
                    _log_problem("import_followup_flow_failed", {
                        "step1_replies": step1_prompt,
                        "step2_replies": step2_replies,
                        "checks": flow_checks,
                    })
            finally:
                export_handlers.import_user_archive = original_import_fn
                export_handlers.inspect_archive = original_inspect_archive
                export_handlers.diff_archive_vs_current = original_diff_archive_vs_current
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        if original_to_thread is not None:
            asyncio.to_thread = original_to_thread

        if had_mainbot:
            sys.modules["mainbot"] = original_mainbot
        else:
            sys.modules.pop("mainbot", None)

        _DBG = None
        _RUNTIME_MAINBOT = None
        _RUNTIME_STORAGE = None

    shortcuts_ok = not dbg.has_problem(
        "reserved_shortcut_handling_failed",
        "removed_shortcut_feedback_failed",
        "unknown_shortcut_feedback_failed",
        "local_alias_shortcuts_failed",
        "retired_developer_backup_callbacks_failed",
    )
    import_ok = not dbg.has_problem("import_followup_flow_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"shortcuts: {'OK' if shortcuts_ok else 'FAIL'}",
        f"import_flow: {'OK' if import_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
