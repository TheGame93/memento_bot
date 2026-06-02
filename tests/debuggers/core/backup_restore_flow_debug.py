#!/usr/bin/env python3
import asyncio
import os
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace


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
SCRIPT_TITLE = "backup_restore_flow_debug"
FEATURE_TITLE = "Manage Backup Restore Flow"

_DBG = None


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
        self.roles = {}
        self.prefs = {}

    def get_user_role(self, user_id):
        return self.roles.get(str(user_id), "user")

    def get_user_prefs(self, user_id):
        return self.prefs.get(str(user_id), {})

    def get_user_meta(self, user_id):
        return {"username": f"user{user_id}"}

    def get_all_alerts(self, user_id):
        return {"alerts": []}

    def get_alert_by_shortcode(self, user_id, shortcode):
        return None


class _FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})


class _FakeCallbackQuery:
    def __init__(self, data):
        self.data = data
        self.message = _FakeMessage()
        self.answer_calls = 0
        self.edits = []

    async def answer(self, *args, **kwargs):
        self.answer_calls += 1

    async def edit_message_text(self, text, **kwargs):
        self.edits.append({"text": text, "kwargs": kwargs})


class _FakeUpdate:
    def __init__(self, *, actor_id=1, callback_data=None, text=None):
        self.effective_user = SimpleNamespace(id=actor_id)
        self.effective_message = _FakeMessage()
        self.message = self.effective_message
        self.callback_query = _FakeCallbackQuery(callback_data) if callback_data is not None else None
        if text is not None:
            self.message.text = text


class _FakeContext:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}
        self.args = []
        self.bot = SimpleNamespace(send_message=self._send_message)
        self.sent_messages = []

    async def _send_message(self, chat_id, text, **kwargs):
        self.sent_messages.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})


def _run(coro):
    return asyncio.run(coro)


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        dbg.run_meta({"project_root": ROOT_DIR})
        try:
            from modules.backup_core.archive_preview import build_archive_preview_text
            from modules.handlers import backup_manage
            from modules.handlers import shortcut_router
            from modules.handlers import user_list
            from modules.handlers.list_alerts import LIST_CONTEXT_KEY
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        storage = _FakeStorage()
        storage.roles = {
            "1": "admin",
            "2": "developer",
            "u_user": "user",
            "u_admin": "admin",
        }
        storage.prefs = {"1": {}, "2": {}}

        original_get_runtime_storage_backup = backup_manage.get_runtime_storage
        original_get_runtime_storage_shortcuts = shortcut_router.get_runtime_storage
        original_get_runtime_storage_user_list = user_list.get_runtime_storage
        original_list_whitelist_users = user_list.list_whitelist_users
        original_list_user_backups = backup_manage.list_user_backups
        original_inspect_archive = backup_manage.inspect_archive
        original_diff_archive_vs_current = backup_manage.diff_archive_vs_current
        original_apply_user_restore = backup_manage.apply_user_restore
        original_handle_restore_backup_select = backup_manage.handle_restore_backup_select
        original_handle_restore_summary = backup_manage.handle_restore_summary
        original_handle_system_backup_shortcut = backup_manage.handle_system_backup_shortcut
        original_send_alert_detail_by_id = shortcut_router.send_alert_detail_by_id

        try:
            backup_manage.get_runtime_storage = lambda _ctx: storage
            shortcut_router.get_runtime_storage = lambda _ctx: storage
            user_list.get_runtime_storage = lambda _ctx: storage
            user_list.list_whitelist_users = lambda: [
                {"id": "u_dev", "role": "developer"},
                {"id": "u_admin", "role": "admin"},
                {"id": "u_user", "role": "user"},
            ]

            # Role scoping: admin sees only role=user on restore user selection.
            admin_update = _FakeUpdate(actor_id=1, callback_data="mgmt_restore_users")
            admin_ctx = _FakeContext()
            _run(backup_manage.handle_restore_user_select(admin_update, admin_ctx))
            admin_alias_values = set((admin_ctx.user_data.get(LIST_CONTEXT_KEY) or {}).get("alias_map", {}).values())
            admin_scope_checks = {
                "answered_once": admin_update.callback_query.answer_calls == 1,
                "source_set": (admin_ctx.user_data.get(LIST_CONTEXT_KEY) or {}).get("source") == "backup_restore_users",
                "admin_only_user_targets": admin_alias_values == {"u_user"},
            }
            print_section("role_scope_admin", {"checks": admin_scope_checks})
            if not all(admin_scope_checks.values()):
                _log_problem("backup_restore_role_scope_admin_failed", {"checks": admin_scope_checks})

            # Role scoping: developer sees all users.
            dev_update = _FakeUpdate(actor_id=2, callback_data="mgmt_restore_users")
            dev_ctx = _FakeContext()
            _run(backup_manage.handle_restore_user_select(dev_update, dev_ctx))
            dev_alias_values = set((dev_ctx.user_data.get(LIST_CONTEXT_KEY) or {}).get("alias_map", {}).values())
            dev_scope_checks = {
                "answered_once": dev_update.callback_query.answer_calls == 1,
                "developer_sees_all": {"u_user", "u_admin", "u_dev"}.issubset(dev_alias_values),
            }
            print_section("role_scope_developer", {"checks": dev_scope_checks})
            if not all(dev_scope_checks.values()):
                _log_problem("backup_restore_role_scope_developer_failed", {"checks": dev_scope_checks})

            # Backup list order + chunking (>10 archives).
            base = datetime(2026, 1, 1, 12, 0, 0)
            many_items = []
            for i in range(40):
                ts = base + timedelta(days=i)
                many_items.append({"path": f"/tmp/b{i}.zip", "timestamp": ts, "name": f"backup_{i}", "size_bytes": 1024 + i})

            def _fake_list_user_backups(_user_id, folder):
                # Split data across folders to validate aggregate sorting.
                if folder == "local":
                    return list(reversed(many_items[:14]))
                if folder == "exports":
                    return list(reversed(many_items[14:28]))
                if folder == "monthly":
                    return list(reversed(many_items[28:]))
                return []

            backup_manage.list_user_backups = _fake_list_user_backups
            backup_manage.inspect_archive = lambda path, _uid: {
                "ok": True,
                "source": "export",
                "retention_bucket": "daily",
                "alert_count": 1,
                "birthday_count": 0,
                "image_count": 0,
                "tag_count": 0,
                "manifest": {"schema_version": "1.0"},
            }
            list_update = _FakeUpdate(actor_id=2, text="/01")
            list_ctx = _FakeContext()
            _run(backup_manage.handle_restore_backup_select(list_update, list_ctx, "u_user"))
            session = list_ctx.user_data.get("backup_manage_session") or {}
            archive_items = session.get("archive_items") or []
            list_text = "\n".join(item.get("text", "") for item in list_update.message.replies if isinstance(item, dict))
            backup_list_checks = {
                "session_has_items": len(archive_items) == 40,
                "oldest_first": bool(archive_items) and archive_items[0]["timestamp"] <= archive_items[-1]["timestamp"],
                "alias_source_set": (list_ctx.user_data.get(LIST_CONTEXT_KEY) or {}).get("source") == "backup_restore_archives",
                "chunked_output": len(list_update.message.replies) >= 2,
            }
            print_section("backup_list_checks", {"checks": backup_list_checks, "reply_count": len(list_update.message.replies)})
            if not all(backup_list_checks.values()):
                _log_problem("backup_restore_list_failed", {"checks": backup_list_checks, "text_sample": list_text[:400]})

            # Summary card completeness.
            summary_update = _FakeUpdate(actor_id=2, text="/02")
            summary_ctx = _FakeContext()
            summary_ctx.user_data["backup_manage_session"] = {
                "phase": "archive_select",
                "target_user_id": "u_user",
                "archive_items": archive_items[:2],
            }
            backup_manage.diff_archive_vs_current = lambda *_args, **_kwargs: {
                "ok": True,
                "current_alert_count": 3,
                "archive_alert_count": 1,
                "current_birthday_count": 1,
                "archive_birthday_count": 0,
                "current_image_count": 4,
                "archive_image_count": 2,
            }
            backup_manage.inspect_archive = lambda _path, _uid: {
                "ok": True,
                "source": "",
                "retention_bucket": "daily",
                "alert_count": 1,
                "birthday_count": 0,
                "image_count": 0,
                "tag_count": 0,
                "manifest": {"schema_version": "1.0"},
            }
            _run(backup_manage.handle_restore_summary(summary_update, summary_ctx, "1"))
            summary_text = summary_update.message.replies[-1]["text"] if summary_update.message.replies else ""
            summary_checks = {
                "has_created_at": "Created at:" in summary_text,
                "has_age": "Age:" in summary_text,
                "has_retention": "Retention:" in summary_text,
                "has_source": "Source:" in summary_text,
                "has_alerts": "Alerts:" in summary_text,
                "has_birthdays": "Birthdays:" in summary_text,
                "has_tags": "Tags:" in summary_text,
                "has_images": "Images:" in summary_text,
                "has_schema": "Schema:" in summary_text,
                "has_current_alerts_line": "Current alerts:" in summary_text,
                "counts_not_na": "n/a" not in summary_text,
                "source_falls_back_to_folder": "Source: `local`" in summary_text,
            }
            print_section("restore_summary_checks", {"checks": summary_checks})
            if not all(summary_checks.values()):
                _log_problem("backup_restore_summary_incomplete", {"checks": summary_checks, "summary": summary_text})
            escaped_preview = build_archive_preview_text(
                {
                    "ok": True,
                    "source": "bad`source",
                    "retention_bucket": "daily",
                    "alert_count": 1,
                    "birthday_count": 0,
                    "tag_count": 0,
                    "image_count": 0,
                    "manifest": {"schema_version": "1.0"},
                },
                {
                    "ok": True,
                    "current_alert_count": 3,
                    "archive_alert_count": 1,
                    "current_birthday_count": 1,
                    "archive_birthday_count": 0,
                    "current_image_count": 4,
                    "archive_image_count": 2,
                },
                title="📄 **Backup Restore Summary**",
            )
            escape_checks = {
                "source_line_present": "Source: `bad'source`" in escaped_preview,
                "raw_backtick_payload_absent": "Source: `bad`source`" not in escaped_preview,
            }
            print_section("restore_summary_escape_checks", {"checks": escape_checks})
            if not all(escape_checks.values()):
                _log_problem(
                    "backup_restore_summary_escape_failed",
                    {"checks": escape_checks, "summary": escaped_preview},
                )

            # Confirm wiring.
            restore_calls = []

            def _fake_apply_user_restore(*args, **kwargs):
                restore_calls.append({"args": args, "kwargs": kwargs})
                return {
                    "ok": True,
                    "archive_id": "backup_01",
                    "counts_diff": {
                        "current_alert_count": 3,
                        "archive_alert_count": 1,
                        "current_birthday_count": 1,
                        "archive_birthday_count": 0,
                        "current_image_count": 2,
                        "archive_image_count": 1,
                    },
                }

            backup_manage.apply_user_restore = _fake_apply_user_restore
            confirm_update = _FakeUpdate(actor_id=2, callback_data="mgmt_restore_confirm")
            confirm_ctx = _FakeContext()
            confirm_ctx.user_data["backup_manage_session"] = {
                "target_user_id": "u_user",
                "selected_archive_path": "/tmp/sel.zip",
            }
            confirm_ctx.user_data[LIST_CONTEXT_KEY] = {"source": "backup_restore_archives", "alias_map": {"01": "0"}}
            _run(backup_manage.handle_restore_confirm(confirm_update, confirm_ctx))
            confirm_checks = {
                "answered_once": confirm_update.callback_query.answer_calls == 1,
                "restore_called_once": len(restore_calls) == 1,
                "source_server_restore": bool(restore_calls) and restore_calls[0]["kwargs"].get("source") == "server_restore",
                "session_cleared": "backup_manage_session" not in confirm_ctx.user_data,
                "list_ctx_cleared": LIST_CONTEXT_KEY not in confirm_ctx.user_data,
            }
            print_section("restore_confirm_checks", {"checks": confirm_checks})
            if not all(confirm_checks.values()):
                _log_problem("backup_restore_confirm_failed", {"checks": confirm_checks, "calls": restore_calls})

            # Numeric shortcut routing for restore/system sources.
            route_calls = {"users": 0, "archives": 0, "system": 0, "alert_detail": 0}

            async def _fake_handle_restore_backup_select(update, context, target_id):
                route_calls["users"] += 1

            async def _fake_handle_restore_summary(update, context, archive_ref):
                route_calls["archives"] += 1

            async def _fake_handle_system_backup_shortcut(update, context, alias_value):
                route_calls["system"] += 1

            async def _fake_send_alert_detail_by_id(*_args, **_kwargs):
                route_calls["alert_detail"] += 1

            backup_manage.handle_restore_backup_select = _fake_handle_restore_backup_select
            backup_manage.handle_restore_summary = _fake_handle_restore_summary
            backup_manage.handle_system_backup_shortcut = _fake_handle_system_backup_shortcut
            shortcut_router.send_alert_detail_by_id = _fake_send_alert_detail_by_id

            for source_name, command in [
                ("backup_restore_users", "/01"),
                ("backup_restore_archives", "/01"),
                ("backup_system_archives", "/01"),
            ]:
                route_update = _FakeUpdate(actor_id=2, text=command)
                route_ctx = _FakeContext()
                route_ctx.user_data[LIST_CONTEXT_KEY] = {
                    "source": source_name,
                    "alias_map": {"01": "target"},
                }
                _run(shortcut_router.handle_dynamic_shortcut_command(route_update, route_ctx))

            routing_checks = {
                "users_routed": route_calls["users"] == 1,
                "archives_routed": route_calls["archives"] == 1,
                "system_routed": route_calls["system"] == 1,
                "alert_detail_not_used": route_calls["alert_detail"] == 0,
            }
            print_section("shortcut_routing_checks", {"checks": routing_checks, "route_calls": route_calls})
            if not all(routing_checks.values()):
                _log_problem("backup_restore_shortcut_routing_failed", {"checks": routing_checks, "route_calls": route_calls})

            # Session cleanup on cancel.
            cancel_update = _FakeUpdate(actor_id=2, callback_data="mgmt_restore_cancel")
            cancel_ctx = _FakeContext()
            cancel_ctx.user_data["backup_manage_session"] = {"phase": "summary", "selected_archive_path": "/tmp/x.zip"}
            cancel_ctx.user_data[LIST_CONTEXT_KEY] = {"source": "backup_restore_archives", "alias_map": {"01": "0"}}
            _run(backup_manage.handle_restore_cancel(cancel_update, cancel_ctx))
            cancel_checks = {
                "answered_once": cancel_update.callback_query.answer_calls == 1,
                "session_cleared": "backup_manage_session" not in cancel_ctx.user_data,
                "list_context_cleared": LIST_CONTEXT_KEY not in cancel_ctx.user_data,
            }
            print_section("session_cleanup_cancel", {"checks": cancel_checks})
            if not all(cancel_checks.values()):
                _log_problem("backup_restore_cancel_cleanup_failed", {"checks": cancel_checks})

        finally:
            backup_manage.get_runtime_storage = original_get_runtime_storage_backup
            shortcut_router.get_runtime_storage = original_get_runtime_storage_shortcuts
            user_list.get_runtime_storage = original_get_runtime_storage_user_list
            user_list.list_whitelist_users = original_list_whitelist_users
            backup_manage.list_user_backups = original_list_user_backups
            backup_manage.inspect_archive = original_inspect_archive
            backup_manage.diff_archive_vs_current = original_diff_archive_vs_current
            backup_manage.apply_user_restore = original_apply_user_restore
            backup_manage.handle_restore_backup_select = original_handle_restore_backup_select
            backup_manage.handle_restore_summary = original_handle_restore_summary
            backup_manage.handle_system_backup_shortcut = original_handle_system_backup_shortcut
            shortcut_router.send_alert_detail_by_id = original_send_alert_detail_by_id

        dbg.finish(exit_on_problems=False)
    except Exception as exc:
        dbg.section("fatal", {"error": f"{type(exc).__name__}: {exc}"})
        dbg.finish(exit_on_problems=False)


if __name__ == "__main__":
    main()
