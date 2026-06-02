#!/usr/bin/env python3
import json
import os
import sys
import tempfile
import zipfile
import asyncio
from datetime import datetime
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

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "backup_export_import_debug"
FEATURE_TITLE = "Export/Import Backups"

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


class _FakeStorageRuntime:
    def __init__(self, storage):
        self.storage = storage

    def __call__(self, _context):
        return self.storage


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
        self.answer_payloads = []

    async def answer(self, *args, **kwargs):
        self.answer_calls += 1
        self.answer_payloads.append({"args": args, "kwargs": kwargs})


class _FakeUpdate:
    def __init__(self, *, actor_id, callback_data):
        self.effective_user = SimpleNamespace(id=actor_id)
        self.effective_message = _FakeMessage()
        self.message = self.effective_message
        self.callback_query = _FakeCallbackQuery(callback_data)


class _FakeContext:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}
        self.args = []


def _run(coro):
    return asyncio.run(coro)


async def _inline_to_thread(func, /, *args, **kwargs):
    return func(*args, **kwargs)


def _zip_write(path, entries):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for rel_path, content in entries.items():
            handle.writestr(rel_path, content)


def _seed_alerts(storage, user_id, titles):
    payload = storage._default_user_payload()  # noqa: SLF001
    alerts = []
    for idx, title in enumerate(titles, start=1):
        alerts.append({
            "id": f"dbg{idx}",
            "title": title,
            "type": 5,
            "type_name": "One Time",
            "schedule": {"date": "10/10/2030", "time": "10:00"},
            "active": True,
        })
    payload["alerts"] = alerts
    ok = storage._write_user_data(user_id, payload)  # noqa: SLF001
    if not ok:
        raise RuntimeError("failed_to_seed_alerts")


def _build_user_payload(title):
    return {
        "alerts": [{
            "id": "inj1",
            "title": title,
            "type": 5,
            "type_name": "One Time",
            "schedule": {"date": "10/10/2030", "time": "10:00"},
            "active": True,
        }],
        "tags": [],
        "postpone_queue": [],
        "shortcut_meta": {"next_seq": 0},
        "backup_prefs": {},
        "user_prefs": {},
    }


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
            from modules.storage import StorageLimitError
            from modules.backup_core.constants import BACKUP_SCHEMA_VERSION
            from modules import constants as C
            from modules.backup_core.user_backup import BackupQuotaError
            import modules.scheduler_core.state as scheduler_state
            from modules.systemlog import force_runtime_state_untrust, _read_runtime_state
            from modules.shared.paths import SYSTEM_LOG_DIR
            from modules.shared import context_keys as context_keys
            from modules.shared.context_cleanup import clear_transient_context
            import modules.backup_core.export_import as export_import_module
            import modules.backup_core.user_restore as user_restore_module
            import modules.handlers.export_import as export_import_handler
            from modules.handlers.base import settings_backup as settings_backup_module
            from modules.backup_core.export_import import export_user_archive, import_user_archive
            from modules.backup_core.manifest import hash_bytes
            from modules.backup_core.user_backup import build_user_backup
            from modules.backup_core.user_restore import (
                apply_user_restore,
                check_restore_permission,
            )
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            previous_backup_dir = os.environ.get("BOT_BACKUP_DIR")
            os.environ["BOT_BACKUP_DIR"] = os.path.join(tmpdir, "backups")
            try:
                data_dir = os.path.join(tmpdir, "data")
                storage = StorageManager(base_data_dir=data_dir)
                user_id = "1001"
                storage.setup_user_space(user_id)
                lock_checks = {
                    "same_lock_object": storage.get_user_write_lock(user_id) is storage._get_user_lock(user_id),  # noqa: SLF001
                }
                print_section("storage_write_lock_checks", {"checks": lock_checks})
                if not all(lock_checks.values()):
                    _log_problem("storage_write_lock_checks_failed", {"checks": lock_checks})

                data_dir_path = storage.resolve_user_data_dir(user_id)
                data_dir_create_path = storage.resolve_user_data_dir(user_id, create=True)
                data_dir_checks = {
                    "user_data_dir_canonical": data_dir_path == os.path.join(data_dir, user_id),
                    "user_data_dir_create_same": data_dir_create_path == data_dir_path,
                    "user_data_dir_exists": os.path.isdir(data_dir_path),
                }
                print_section("storage_data_dir_checks", {
                    "path": data_dir_path,
                    "create_path": data_dir_create_path,
                    "checks": data_dir_checks,
                })
                if not all(data_dir_checks.values()):
                    _log_problem("storage_data_dir_checks_failed", {
                        "path": data_dir_path,
                        "create_path": data_dir_create_path,
                        "checks": data_dir_checks,
                    })

                images_dir_checks = {
                    "images_dir_created": os.path.isdir(storage.resolve_user_images_dir(user_id, create=True)),
                    "images_dir_no_create_path": storage.resolve_user_images_dir(user_id, create=False) == os.path.join(data_dir, user_id, "images"),
                }
                print_section("storage_images_dir_checks", {"checks": images_dir_checks})
                if not all(images_dir_checks.values()):
                    _log_problem("storage_images_dir_checks_failed", {"checks": images_dir_checks})

                restored_payload = {
                    "alerts": [{
                        "id": "r1",
                        "title": "Restored",
                        "type": 5,
                        "type_name": "One Time",
                        "schedule": {"date": "10/10/2030", "time": "10:00"},
                        "active": True,
                    }],
                    "tags": [],
                    "postpone_queue": [],
                    "backup_prefs": {},
                    "user_prefs": {},
                }
                storage.restore_user_from_data(user_id, restored_payload)
                restored_state = storage.get_all_alerts(user_id) or {}
                restore_checks = {
                    "restore_roundtrip_title": bool(restored_state.get("alerts")) and restored_state["alerts"][0].get("title") == "Restored",
                    "restore_includes_shortcode_meta": isinstance(restored_state.get("shortcut_meta"), dict),
                }
                print_section("storage_restore_roundtrip_checks", {"checks": restore_checks})
                if not all(restore_checks.values()):
                    _log_problem("storage_restore_roundtrip_checks_failed", {"checks": restore_checks})

                try:
                    storage.restore_user_from_data(user_id, [])
                    _log_problem("storage_restore_non_dict_not_rejected", {})
                except ValueError:
                    pass

                try:
                    with patch.object(C, "USER_ALERTS_JSON_MAX_BYTES", 64):
                        storage.restore_user_from_data(user_id, {"alerts": [], "tags": ["x" * 4096]})
                    _log_problem("storage_restore_oversize_not_rejected", {})
                except StorageLimitError:
                    pass

                if not force_runtime_state_untrust():
                    _log_problem("force_runtime_state_untrust_failed", {})
                state_after_untrust = _read_runtime_state()
                untrust_checks = {
                    "last_exit_running": state_after_untrust.get("last_exit") == "running",
                    "runtime_id_cleared": (
                        isinstance(state_after_untrust.get("instance_identity"), dict)
                        and state_after_untrust["instance_identity"].get("runtime_id") is None
                    ),
                }
                print_section("runtime_state_untrust_checks", {"checks": untrust_checks})
                if not all(untrust_checks.values()):
                    _log_problem("runtime_state_untrust_checks_failed", {"checks": untrust_checks})

                scheduler_state.sent_pre_alerts.clear()
                scheduler_state.sent_pre_alerts_dirty = False
                scheduler_state.sent_pre_alerts[("1001", "a1", "1h")] = datetime.now()
                scheduler_state.sent_pre_alerts[("1001", "a2", "2h")] = datetime.now()
                scheduler_state.sent_pre_alerts[("1002", "a3", "3h")] = datetime.now()
                removed_sent_pre = scheduler_state.prune_user_sent_pre_alerts("1001")
                sent_pre_checks = {
                    "removed_count_expected": removed_sent_pre == 2,
                    "target_user_entries_removed": all(k[0] != "1001" for k in scheduler_state.sent_pre_alerts.keys()),
                    "other_user_entries_kept": any(k[0] == "1002" for k in scheduler_state.sent_pre_alerts.keys()),
                    "dirty_set_on_remove": scheduler_state.sent_pre_alerts_dirty is True,
                }
                print_section("scheduler_prune_sent_pre_checks", {"checks": sent_pre_checks})
                if not all(sent_pre_checks.values()):
                    _log_problem("scheduler_prune_sent_pre_checks_failed", {"checks": sent_pre_checks})

                scheduler_state.notified_missed_pre.clear()
                scheduler_state.pending_missed_notifications.clear()
                scheduler_state.notified_missed_pre_dirty = False
                scheduler_state.pending_missed_dirty = False
                scheduler_state.notified_missed_pre[("1001", "a1", "1h", "2026-01-01T10:00:00")] = datetime.now()
                scheduler_state.notified_missed_pre[("1002", "a9", "1h", "2026-01-01T10:00:00")] = datetime.now()
                scheduler_state.pending_missed_notifications["1001"] = {"a1": {"occurrence": "x"}}
                scheduler_state.pending_missed_notifications["1002"] = {"a9": {"occurrence": "x"}}
                prune_missed_result = scheduler_state.prune_user_missed_state("1001")
                missed_checks = {
                    "notified_removed_expected": prune_missed_result.get("notified_missed_pre_removed") == 1,
                    "pending_removed_expected": prune_missed_result.get("pending_missed_removed") == 1,
                    "target_user_notified_removed": all(k[0] != "1001" for k in scheduler_state.notified_missed_pre.keys()),
                    "target_user_pending_removed": "1001" not in scheduler_state.pending_missed_notifications,
                    "other_user_notified_kept": any(k[0] == "1002" for k in scheduler_state.notified_missed_pre.keys()),
                    "other_user_pending_kept": "1002" in scheduler_state.pending_missed_notifications,
                    "notified_dirty_set": scheduler_state.notified_missed_pre_dirty is True,
                    "pending_dirty_set": scheduler_state.pending_missed_dirty is True,
                }
                print_section("scheduler_prune_missed_checks", {"checks": missed_checks})
                if not all(missed_checks.values()):
                    _log_problem("scheduler_prune_missed_checks_failed", {
                        "checks": missed_checks,
                        "result": prune_missed_result,
                    })

                cleanup_user_data = {
                    "expecting_import_archive": True,
                    "backup_import_session": {},
                }
                cleanup_key_checks = {
                    "backup_session_key_registered": "backup_import_session" in context_keys.BACKUP_KEYS,
                    "import_pending_key_registered": "expecting_import_archive" in context_keys.BACKUP_KEYS,
                }
                print_section("context_cleanup_keys_checks", {"checks": cleanup_key_checks})
                if not all(cleanup_key_checks.values()):
                    _log_problem("context_cleanup_keys_checks_failed", {"checks": cleanup_key_checks})

                with tempfile.NamedTemporaryFile(mode="wb", suffix=".zip", delete=False, dir=tmpdir) as temp_archive:
                    temp_archive.write(b"debug")
                    temp_archive_path = temp_archive.name
                cleanup_user_data["backup_import_session"] = {"temp_path": temp_archive_path}
                clear_transient_context(cleanup_user_data)
                cleanup_checks = {
                    "expecting_import_archive_cleared": "expecting_import_archive" not in cleanup_user_data,
                    "backup_import_session_cleared": "backup_import_session" not in cleanup_user_data,
                    "session_temp_deleted": not os.path.exists(temp_archive_path),
                }
                print_section("context_cleanup_backup_import_session", {"checks": cleanup_checks})
                if not all(cleanup_checks.values()):
                    _log_problem("context_cleanup_backup_import_session_failed", {"checks": cleanup_checks})

                kb = settings_backup_module.build_settings_backup_keyboard()
                rows = kb.inline_keyboard
                kb_checks = {
                    "export_import_same_row": len(rows[0]) == 2,
                    "export_button_label": rows[0][0].text == "📤 Export backup",
                    "import_button_label": rows[0][1].text == "📥 Import backup",
                    "restore_label_updated": any(
                        btn.text == "🔄 Restore Backup from Server"
                        for row in rows for btn in row
                    ),
                }
                print_section("settings_backup_keyboard_checks", {"checks": kb_checks})
                if not all(kb_checks.values()):
                    _log_problem("settings_backup_keyboard_checks_failed", {"checks": kb_checks})

                with tempfile.NamedTemporaryFile(mode="wb", suffix=".zip", delete=False, dir=tmpdir) as stale_archive:
                    stale_archive.write(b"stale")
                    stale_archive_path = stale_archive.name
                prompt_update = _FakeUpdate(actor_id=user_id, callback_data="settings_backup_import")
                prompt_context = _FakeContext()
                prompt_context.user_data["backup_import_session"] = {
                    "temp_path": stale_archive_path,
                    "source": "settings",
                    "target_user_id": user_id,
                }
                with patch.object(settings_backup_module, "get_runtime_storage", _FakeStorageRuntime(storage)):
                    _run(settings_backup_module.handle_settings_backup_import(prompt_update, prompt_context))
                prompt_checks = {
                    "old_temp_deleted": not os.path.exists(stale_archive_path),
                    "backup_import_session_cleared": "backup_import_session" not in prompt_context.user_data,
                    "expecting_import_archive_set": prompt_context.user_data.get("expecting_import_archive") is True,
                    "answered_once": prompt_update.callback_query.answer_calls == 1,
                }
                print_section("settings_import_prompt_cleanup_checks", {"checks": prompt_checks})
                if not all(prompt_checks.values()):
                    _log_problem("settings_import_prompt_cleanup_failed", {"checks": prompt_checks})

                import_calls = []

                def _fake_import_user_archive(_storage, target_user_id, archive_path):
                    import_calls.append({
                        "storage": _storage,
                        "target_user_id": str(target_user_id),
                        "archive_path": archive_path,
                    })
                    return {"ok": True}

                with tempfile.NamedTemporaryFile(mode="wb", suffix=".zip", delete=False, dir=tmpdir) as confirm_archive:
                    confirm_archive.write(b"confirm")
                    confirm_archive_path = confirm_archive.name
                confirm_update = _FakeUpdate(actor_id="actor_changed", callback_data="settings_backup_import_confirm")
                confirm_context = _FakeContext()
                confirm_context.user_data["backup_import_session"] = {
                    "temp_path": confirm_archive_path,
                    "source": "settings",
                    "target_user_id": user_id,
                }
                confirm_context.user_data["expecting_import_archive"] = True
                with (
                    patch.object(export_import_handler, "get_runtime_storage", _FakeStorageRuntime(storage)),
                    patch.object(export_import_handler, "import_user_archive", side_effect=_fake_import_user_archive),
                    patch.object(export_import_handler.asyncio, "to_thread", new=_inline_to_thread),
                ):
                    _run(export_import_handler.handle_settings_backup_import_confirm(confirm_update, confirm_context))
                    double_click_update = _FakeUpdate(actor_id=user_id, callback_data="settings_backup_import_confirm")
                    _run(export_import_handler.handle_settings_backup_import_confirm(double_click_update, confirm_context))
                confirm_checks = {
                    "import_called_once": len(import_calls) == 1,
                    "import_target_matches_session": bool(import_calls) and import_calls[0]["target_user_id"] == user_id,
                    "session_cleared": "backup_import_session" not in confirm_context.user_data,
                    "expecting_import_archive_cleared": "expecting_import_archive" not in confirm_context.user_data,
                    "tmp_removed": not os.path.exists(confirm_archive_path),
                    "answered_once": confirm_update.callback_query.answer_calls == 1,
                    "double_click_no_second_import": len(import_calls) == 1,
                    "double_click_alerted": double_click_update.callback_query.answer_calls == 1,
                }
                print_section("settings_import_confirm_checks", {"checks": confirm_checks})
                if not all(confirm_checks.values()):
                    _log_problem("settings_import_confirm_failed", {"checks": confirm_checks, "calls": import_calls})

                expired_calls = []
                expired_update = _FakeUpdate(actor_id=user_id, callback_data="settings_backup_import_confirm")
                expired_context = _FakeContext()
                expired_context.user_data["expecting_import_archive"] = True
                with (
                    patch.object(export_import_handler, "get_runtime_storage", _FakeStorageRuntime(storage)),
                    patch.object(export_import_handler, "import_user_archive", side_effect=lambda *args: expired_calls.append(args)),
                ):
                    _run(export_import_handler.handle_settings_backup_import_confirm(expired_update, expired_context))
                expired_answer = expired_update.callback_query.answer_payloads[-1] if expired_update.callback_query.answer_payloads else {}
                expired_checks = {
                    "show_alert_used": (expired_answer.get("kwargs") or {}).get("show_alert") is True,
                    "import_not_called": not expired_calls,
                    "session_cleared": "backup_import_session" not in expired_context.user_data,
                    "expecting_import_archive_cleared": "expecting_import_archive" not in expired_context.user_data,
                }
                print_section("settings_import_confirm_expired_checks", {"checks": expired_checks})
                if not all(expired_checks.values()):
                    _log_problem("settings_import_confirm_expired_failed", {"checks": expired_checks})

                with tempfile.NamedTemporaryFile(mode="wb", suffix=".zip", delete=False, dir=tmpdir) as exception_archive:
                    exception_archive.write(b"exception")
                    exception_archive_path = exception_archive.name
                exception_update = _FakeUpdate(actor_id=user_id, callback_data="settings_backup_import_confirm")
                exception_context = _FakeContext()
                exception_context.user_data["backup_import_session"] = {
                    "temp_path": exception_archive_path,
                    "source": "settings",
                    "target_user_id": user_id,
                }
                with (
                    patch.object(export_import_handler, "get_runtime_storage", _FakeStorageRuntime(storage)),
                    patch.object(export_import_handler, "import_user_archive", side_effect=RuntimeError("debug_import_boom")),
                    patch.object(export_import_handler.asyncio, "to_thread", new=_inline_to_thread),
                ):
                    _run(export_import_handler.handle_settings_backup_import_confirm(exception_update, exception_context))
                exception_replies = exception_update.callback_query.message.replies
                exception_checks = {
                    "failure_reply_sent": bool(exception_replies) and "Import failed" in exception_replies[-1].get("text", ""),
                    "tmp_removed": not os.path.exists(exception_archive_path),
                    "session_cleared": "backup_import_session" not in exception_context.user_data,
                    "answered_once": exception_update.callback_query.answer_calls == 1,
                }
                print_section("settings_import_confirm_exception_checks", {"checks": exception_checks})
                if not all(exception_checks.values()):
                    _log_problem("settings_import_confirm_exception_failed", {"checks": exception_checks})

                with tempfile.NamedTemporaryFile(mode="wb", suffix=".zip", delete=False, dir=tmpdir) as cancel_archive:
                    cancel_archive.write(b"cancel")
                    cancel_archive_path = cancel_archive.name
                cancel_update = _FakeUpdate(actor_id=user_id, callback_data="settings_backup_import_cancel")
                cancel_context = _FakeContext()
                cancel_context.user_data["backup_import_session"] = {
                    "temp_path": cancel_archive_path,
                    "source": "settings",
                    "target_user_id": user_id,
                }
                cancel_context.user_data["expecting_import_archive"] = True
                with patch.object(export_import_handler, "get_runtime_storage", _FakeStorageRuntime(storage)):
                    _run(export_import_handler.handle_settings_backup_import_cancel(cancel_update, cancel_context))
                cancel_replies = cancel_update.callback_query.message.replies
                cancel_checks = {
                    "session_cleared": "backup_import_session" not in cancel_context.user_data,
                    "expecting_import_archive_cleared": "expecting_import_archive" not in cancel_context.user_data,
                    "tmp_remove_attempted": not os.path.exists(cancel_archive_path),
                    "answered_once": cancel_update.callback_query.answer_calls == 1,
                    "cancel_message_sent": bool(cancel_replies) and "Import cancelled" in cancel_replies[-1].get("text", ""),
                }
                print_section("settings_import_cancel_checks", {"checks": cancel_checks})
                if not all(cancel_checks.values()):
                    _log_problem("settings_import_cancel_failed", {"checks": cancel_checks})

                class _FakeTGFile:
                    def __init__(self, file_path, content):
                        self.file_path = file_path
                        self._content = content

                    async def download_to_drive(self, dst_path):
                        await asyncio.sleep(0)
                        with open(dst_path, "wb") as handle:
                            handle.write(self._content)

                class _FakeBot:
                    def __init__(self, fake_file):
                        self._fake_file = fake_file

                    async def get_file(self, _file_id):
                        await asyncio.sleep(0)
                        return self._fake_file

                fake_file = _FakeTGFile("foo/bar/test.jpg", b"hello-image")
                fake_bot = _FakeBot(fake_file)
                rel_image_path = asyncio.run(storage.download_image(fake_bot, user_id, "file123"))
                tmp_uploads_dir = os.path.join(data_dir, user_id, ".tmp_uploads")
                image_path = os.path.join(data_dir, user_id, "images", "file123.jpg")
                placement_checks = {
                    "returned_canonical_rel_path": rel_image_path == "images/file123.jpg",
                    "image_written": os.path.isfile(image_path),
                    "tmp_uploads_under_user_dir": tmp_uploads_dir.startswith(os.path.join(data_dir, user_id)),
                    "tmp_uploads_empty_after_success": not any(os.scandir(tmp_uploads_dir)),
                }
                print_section("storage_download_image_placement_checks", {"checks": placement_checks})
                if not all(placement_checks.values()):
                    _log_problem("storage_download_image_placement_checks_failed", {"checks": placement_checks})

                oversized_user = "2002"
                storage.setup_user_space(oversized_user)
                oversized_root = os.path.join(data_dir, oversized_user)
                os.makedirs(os.path.join(oversized_root, "pad"), exist_ok=True)
                with open(os.path.join(oversized_root, "pad", "big.bin"), "wb") as handle:
                    handle.write(b"x" * 9000)
                with patch.object(C, "USER_FOLDER_MAX_BYTES", 8192):
                    try:
                        asyncio.run(storage.download_image(fake_bot, oversized_user, "ov1"))
                        _log_problem("storage_download_image_overflow_not_rejected", {})
                    except StorageLimitError:
                        pass
                oversized_tmp = os.path.join(oversized_root, ".tmp_uploads")
                overflow_checks = {
                    "tmp_uploads_empty_after_overflow": (not os.path.isdir(oversized_tmp)) or (not any(os.scandir(oversized_tmp))),
                    "image_not_written_on_overflow": not os.path.exists(os.path.join(oversized_root, "images", "ov1.jpg")),
                }
                print_section("storage_download_image_overflow_checks", {"checks": overflow_checks})
                if not all(overflow_checks.values()):
                    _log_problem("storage_download_image_overflow_checks_failed", {"checks": overflow_checks})

                near_user = "2003"
                storage.setup_user_space(near_user)
                near_root = os.path.join(data_dir, near_user)
                os.makedirs(os.path.join(near_root, "pad"), exist_ok=True)
                with open(os.path.join(near_root, "pad", "small.bin"), "wb") as handle:
                    handle.write(b"x" * 18000)
                with patch.object(C, "USER_FOLDER_MAX_BYTES", 20000):
                    under_rel = asyncio.run(storage.download_image(fake_bot, near_user, "ok1"))
                under_checks = {
                    "under_quota_allowed": under_rel == "images/ok1.jpg",
                    "under_quota_image_written": os.path.exists(os.path.join(near_root, "images", "ok1.jpg")),
                }
                print_section("storage_download_image_under_quota_checks", {"checks": under_checks})
                if not all(under_checks.values()):
                    _log_problem("storage_download_image_under_quota_checks_failed", {"checks": under_checks})

                _seed_alerts(storage, user_id, ["Export"])

                img_path = os.path.join(data_dir, user_id, "images", "photo.jpg")
                with open(img_path, "wb") as handle:
                    handle.write(b"fakeimage")

                user_log_path = storage.get_user_event_log_path(user_id)
                os.makedirs(os.path.dirname(user_log_path), exist_ok=True)
                with open(user_log_path, "w", encoding="utf-8") as handle:
                    handle.write('{"event": "export"}\n')

                export = export_user_archive(storage, user_id)
                export_path = export.get("path")
                if not export_path or not os.path.isfile(export_path):
                    _log_problem("export_failed", {"path": export_path})
                else:
                    export_folder_checks = {
                        "in_exports_folder": "/exports/" in export_path.replace("\\\\", "/"),
                    }
                    print_section("export_folder_checks", {"checks": export_folder_checks, "path": export_path})
                    if not all(export_folder_checks.values()):
                        _log_problem("export_folder_checks_failed", {"checks": export_folder_checks, "path": export_path})

                    with zipfile.ZipFile(export_path, "r") as handle:
                        export_names = set(handle.namelist())
                    export_logs_checks = {
                        "logs_excluded": not any(name.startswith("logs/") for name in export_names),
                    }
                    print_section("export_logs_checks", {"checks": export_logs_checks})
                    if not all(export_logs_checks.values()):
                        _log_problem("export_logs_checks_failed", {"checks": export_logs_checks})

                    fixed_now = datetime(2026, 2, 9, 12, 0, 0)
                    same_ts_export_a = export_user_archive(storage, user_id, now=fixed_now)
                    same_ts_export_b = export_user_archive(storage, user_id, now=fixed_now)
                    collision_checks = {
                        "first_path_recorded": bool(same_ts_export_a.get("path")),
                        "second_exists": os.path.isfile(same_ts_export_b.get("path", "")),
                        "paths_are_distinct": same_ts_export_a.get("path") != same_ts_export_b.get("path"),
                    }
                    print_section("export_collision_checks", {
                        "first_path": same_ts_export_a.get("path"),
                        "second_path": same_ts_export_b.get("path"),
                        "checks": collision_checks,
                    })
                    if not all(collision_checks.values()):
                        _log_problem("export_name_collision_not_handled", {
                            "checks": collision_checks,
                            "first_path": same_ts_export_a.get("path"),
                            "second_path": same_ts_export_b.get("path"),
                        })

                    quota_triggered = False
                    with patch.object(C, "USER_BACKUP_QUOTA_BYTES", 1):
                        try:
                            export_user_archive(storage, user_id, now=datetime(2026, 2, 9, 12, 0, 1))
                        except BackupQuotaError:
                            quota_triggered = True
                    if not quota_triggered:
                        _log_problem("export_quota_not_triggered", {})

                    user_dir = os.path.join(data_dir, user_id)
                    for name in os.listdir(user_dir):
                        if name in {"backups"}:
                            continue
                        path = os.path.join(user_dir, name)
                        if os.path.isdir(path):
                            for root, _dirs, files in os.walk(path):
                                for file_name in files:
                                    os.remove(os.path.join(root, file_name))
                        elif os.path.isfile(path):
                            os.remove(path)

                    result = import_user_archive(storage, user_id, export_path)
                    if not result.get("ok"):
                        _log_problem("import_failed", result)

                    restored_alerts = storage.get_all_alerts(user_id) or {}
                    restored_images = os.path.join(user_dir, "images", "photo.jpg")
                    restored_logs = storage.get_user_event_log_path(user_id)
                    restored_legacy_log_dir = os.path.join(user_dir, "logs")
                    checks = {
                        "alerts_present": bool(restored_alerts.get("alerts")),
                        "image_restored": os.path.isfile(restored_images),
                        "log_restored": os.path.isfile(restored_logs),
                        "legacy_log_dir_absent": not os.path.isdir(restored_legacy_log_dir),
                    }
                    print_section("restore_checks", {"checks": checks})
                    if not all(checks.values()):
                        _log_problem("import_failed", {"checks": checks})

                invalid_archive = os.path.join(tmpdir, "invalid_archive.zip")
                with open(invalid_archive, "w", encoding="utf-8") as handle:
                    handle.write("not a zip")
                invalid_result = import_user_archive(storage, user_id, invalid_archive)
                invalid_checks = {
                    "ok_false": invalid_result.get("ok") is False,
                    "error_present": isinstance(invalid_result.get("error"), str) and bool(invalid_result.get("error")),
                }
                print_section("invalid_archive_checks", {"result": invalid_result, "checks": invalid_checks})
                if not all(invalid_checks.values()):
                    _log_problem("invalid_archive_handling_failed", {
                        "result": invalid_result,
                        "checks": invalid_checks,
                    })

                symlink_archive = os.path.join(tmpdir, "unsafe_symlink_archive.zip")
                with zipfile.ZipFile(symlink_archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
                    link_info = zipfile.ZipInfo("logs/link")
                    link_info.create_system = 3
                    link_info.external_attr = 0o120777 << 16
                    handle.writestr(link_info, "../../etc/passwd")
                symlink_result = import_user_archive(storage, user_id, symlink_archive)
                symlink_checks = {
                    "ok_false": symlink_result.get("ok") is False,
                    "symlink_blocked": "unsafe_zip_symlink" in str(symlink_result.get("error")),
                }
                print_section("unsafe_symlink_checks", {"result": symlink_result, "checks": symlink_checks})
                if not all(symlink_checks.values()):
                    _log_problem("unsafe_symlink_archive_handling_failed", {
                        "result": symlink_result,
                        "checks": symlink_checks,
                    })

                alerts_payload = json.dumps({"alerts": [], "tags": []}, indent=2)
                alerts_bytes = alerts_payload.encode("utf-8")
                unsafe_manifest = {
                    "schema_version": BACKUP_SCHEMA_VERSION,
                    "created_at": datetime.now().isoformat(),
                    "user_id": str(user_id),
                    "files": [
                        {
                            "path": "alerts.json",
                            "size": len(alerts_bytes),
                            "sha256": hash_bytes(alerts_bytes),
                        },
                        {
                            "path": "../escape.txt",
                            "size": 1,
                            "sha256": hash_bytes(b"x"),
                        },
                    ],
                }
                unsafe_archive = os.path.join(tmpdir, "unsafe_manifest.zip")
                _zip_write(unsafe_archive, {
                    "alerts.json": alerts_payload,
                    "manifest.json": json.dumps(unsafe_manifest, indent=2),
                })
                unsafe_result = import_user_archive(storage, user_id, unsafe_archive)
                unsafe_checks = {
                    "ok_false": unsafe_result.get("ok") is False,
                    "path_rejected": "not_allowed" in str(unsafe_result.get("error")),
                }
                print_section("unsafe_manifest_checks", {"result": unsafe_result, "checks": unsafe_checks})
                if not all(unsafe_checks.values()):
                    _log_problem("unsafe_manifest_path_failed", {
                        "result": unsafe_result,
                        "checks": unsafe_checks,
                    })

                storage.setup_user_space(user_id)
                _seed_alerts(storage, user_id, ["Export", "OriginalState"])
                before = storage.get_all_alerts(user_id) or {}
                before_titles = [a.get("title") for a in before.get("alerts", [])]

                injected_payload = json.dumps(_build_user_payload("InjectedState"), indent=2)
                injected_bytes = injected_payload.encode("utf-8")
                missing_manifest = {
                    "schema_version": BACKUP_SCHEMA_VERSION,
                    "created_at": datetime.now().isoformat(),
                    "user_id": str(user_id),
                    "files": [
                        {
                            "path": "alerts.json",
                            "size": len(injected_bytes),
                            "sha256": hash_bytes(injected_bytes),
                        },
                        {
                            "path": "logs/missing.log",
                            "size": 5,
                            "sha256": hash_bytes(b"dummy"),
                        },
                    ],
                }
                missing_archive = os.path.join(tmpdir, "missing_file_manifest.zip")
                _zip_write(missing_archive, {
                    "alerts.json": injected_payload,
                    "manifest.json": json.dumps(missing_manifest, indent=2),
                })
                missing_result = import_user_archive(storage, user_id, missing_archive)
                after = storage.get_all_alerts(user_id) or {}
                after_titles = [a.get("title") for a in after.get("alerts", [])]
                partial_checks = {
                    "ok_false": missing_result.get("ok") is False,
                    "logs_rejected": "not_allowed" in str(missing_result.get("error")),
                    "alerts_not_replaced": "InjectedState" not in after_titles,
                    "previous_alerts_intact": bool(before_titles) and set(before_titles).issubset(set(after_titles)),
                }
                print_section("partial_apply_checks", {
                    "result": missing_result,
                    "before_titles": before_titles,
                    "after_titles": after_titles,
                    "checks": partial_checks,
                })
                if not all(partial_checks.values()):
                    _log_problem("partial_apply_guard_failed", {
                        "result": missing_result,
                        "before_titles": before_titles,
                        "after_titles": after_titles,
                        "checks": partial_checks,
                    })

                transactional_checks = {"skipped_obsolete_legacy_import_path": True}
                print_section("transactional_apply_rollback_checks", {"checks": transactional_checks})

                permission_manifest = {"user_id": "3001"}
                role_map = {
                    "u_self": "user",
                    "u_other": "user",
                    "a_actor": "admin",
                    "d_actor": "developer",
                    "t_user": "user",
                    "t_admin": "admin",
                }

                def _role_lookup(uid):
                    return role_map.get(str(uid), "user")

                permission_checks = {
                    "user_self_allow": check_restore_permission(
                        "u_self",
                        "u_self",
                        {"user_id": "u_self"},
                        _role_lookup,
                    )[0]
                    is True,
                    "user_other_deny": check_restore_permission(
                        "u_self",
                        "u_other",
                        {"user_id": "u_other"},
                        _role_lookup,
                    )[0]
                    is False,
                    "admin_to_user_allow": check_restore_permission(
                        "a_actor",
                        "t_user",
                        {"user_id": "t_user"},
                        _role_lookup,
                    )[0]
                    is True,
                    "admin_to_admin_deny": check_restore_permission(
                        "a_actor",
                        "t_admin",
                        {"user_id": "t_admin"},
                        _role_lookup,
                    )[0]
                    is False,
                    "developer_to_any_allow": check_restore_permission(
                        "d_actor",
                        "t_admin",
                        {"user_id": "t_admin"},
                        _role_lookup,
                    )[0]
                    is True,
                }
                print_section("restore_permission_checks", {"checks": permission_checks})
                if not all(permission_checks.values()):
                    _log_problem("restore_permission_checks_failed", {"checks": permission_checks})

                restore_user = "3001"
                storage.setup_user_space(restore_user)
                _seed_alerts(storage, restore_user, ["Restore-Archive"])
                restore_img = os.path.join(data_dir, restore_user, "images", "restore.jpg")
                with open(restore_img, "wb") as handle:
                    handle.write(b"restore-image")
                restore_archive = build_user_backup(
                    storage,
                    restore_user,
                    "exports",
                    now=datetime(2026, 3, 10, 10, 0, 0),
                    source="export",
                    enforce_quota=False,
                )["path"]

                _seed_alerts(storage, restore_user, ["After-Archive"])
                old_only_img = os.path.join(data_dir, restore_user, "images", "old_only.jpg")
                with open(old_only_img, "wb") as handle:
                    handle.write(b"old-only")

                scheduler_state.sent_pre_alerts[(restore_user, "a1", "1h")] = datetime.now()
                scheduler_state.notified_missed_pre[(restore_user, "a1", "1h", "2026-01-01T10:00:00")] = datetime.now()
                scheduler_state.pending_missed_notifications[restore_user] = {"a1": {"occurrence": "x"}}

                backup_log = os.path.join(SYSTEM_LOG_DIR, "backup.log")
                server_before_size = os.path.getsize(backup_log) if os.path.isfile(backup_log) else 0
                restore_result = apply_user_restore(
                    storage,
                    restore_user,
                    restore_archive,
                    actor_id=restore_user,
                    scheduler_state_module=scheduler_state,
                    source="server_restore",
                    get_role_fn=lambda _uid: "user",
                )
                if os.path.isfile(backup_log):
                    with open(backup_log, "r", encoding="utf-8") as handle:
                        handle.seek(server_before_size)
                        server_lines = handle.read().splitlines()
                    server_events = []
                    for line in server_lines:
                        try:
                            record = json.loads(line)
                        except Exception:
                            continue
                        server_events.append(record.get("event"))
                else:
                    server_events = []
                restored_data = storage.get_all_alerts(restore_user) or {}
                restored_titles = [a.get("title") for a in restored_data.get("alerts", [])]
                full_restore_checks = {
                    "restore_ok": restore_result.get("ok") is True,
                    "pre_import_created": bool(restore_result.get("pre_import_backup_path")),
                    "alerts_restored": "Restore-Archive" in restored_titles and "After-Archive" not in restored_titles,
                    "restore_image_present": os.path.exists(restore_img),
                    "old_image_removed": not os.path.exists(old_only_img),
                    "scheduler_pre_pruned": not any(k[0] == restore_user for k in scheduler_state.sent_pre_alerts.keys()),
                    "scheduler_missed_pruned": restore_user not in scheduler_state.pending_missed_notifications,
                    "server_restore_logged": "backup_restored" in server_events and "backup_imported" not in server_events,
                }
                print_section("full_restore_checks", {"result": restore_result, "checks": full_restore_checks})
                if not all(full_restore_checks.values()):
                    _log_problem("full_restore_checks_failed", {
                        "result": restore_result,
                        "titles": restored_titles,
                        "checks": full_restore_checks,
                    })

                noimg_user = "3002"
                storage.setup_user_space(noimg_user)
                _seed_alerts(storage, noimg_user, ["Before-NoImg"])
                noimg_live = os.path.join(data_dir, noimg_user, "images", "live.jpg")
                with open(noimg_live, "wb") as handle:
                    handle.write(b"live")
                noimg_alerts_payload = json.dumps(_build_user_payload("NoImg"), indent=2)
                noimg_alerts_bytes = noimg_alerts_payload.encode("utf-8")
                noimg_manifest = {
                    "schema_version": BACKUP_SCHEMA_VERSION,
                    "created_at": datetime.now().isoformat(),
                    "user_id": noimg_user,
                    "files": [
                        {
                            "path": "alerts.json",
                            "size": len(noimg_alerts_bytes),
                            "sha256": hash_bytes(noimg_alerts_bytes),
                        },
                    ],
                }
                noimg_archive = os.path.join(tmpdir, "backup_20260310_101010.zip")
                _zip_write(noimg_archive, {
                    "alerts.json": noimg_alerts_payload,
                    "manifest.json": json.dumps(noimg_manifest, indent=2),
                })
                real_mkdtemp = user_restore_module.tempfile.mkdtemp
                staged_dirs = []

                def _capture_mkdtemp(*args, **kwargs):
                    staged_dirs.append(kwargs.get("dir"))
                    return real_mkdtemp(*args, **kwargs)

                with patch.object(user_restore_module.tempfile, "mkdtemp", side_effect=_capture_mkdtemp):
                    noimg_result = apply_user_restore(
                        storage,
                        noimg_user,
                        noimg_archive,
                        actor_id="dev1",
                        scheduler_state_module=scheduler_state,
                        source="server_restore",
                        get_role_fn=lambda uid: "developer" if str(uid) == "dev1" else "user",
                    )
                noimg_dir = os.path.join(data_dir, noimg_user, "images")
                noimg_checks = {
                    "restore_ok": noimg_result.get("ok") is True,
                    "images_dir_exists": os.path.isdir(noimg_dir),
                    "images_dir_emptied": os.listdir(noimg_dir) == [],
                    "staging_dir_under_user_data": bool(staged_dirs) and any(
                        str(item or "").startswith(storage.resolve_user_data_dir(noimg_user, create=True))
                        for item in staged_dirs
                    ),
                }
                print_section("restore_no_images_checks", {"result": noimg_result, "checks": noimg_checks})
                if not all(noimg_checks.values()):
                    _log_problem("restore_no_images_checks_failed", {
                        "result": noimg_result,
                        "checks": noimg_checks,
                    })

                mismatch_user = "3003"
                storage.setup_user_space(mismatch_user)
                pre_import_dir = os.path.join(tmpdir, "backups", "users", mismatch_user, "pre_import")
                os.makedirs(pre_import_dir, exist_ok=True)
                pre_before = set(os.listdir(pre_import_dir))
                mismatch_result = apply_user_restore(
                    storage,
                    mismatch_user,
                    restore_archive,
                    actor_id="dev1",
                    scheduler_state_module=scheduler_state,
                    source="server_restore",
                    get_role_fn=lambda _uid: "developer",
                )
                pre_after = set(os.listdir(pre_import_dir))
                mismatch_checks = {
                    "restore_denied": mismatch_result.get("ok") is False,
                    "reason_manifest_mismatch": "mismatch" in str(mismatch_result.get("error")),
                    "no_pre_import_created": pre_before == pre_after,
                }
                print_section("restore_manifest_mismatch_checks", {"result": mismatch_result, "checks": mismatch_checks})
                if not all(mismatch_checks.values()):
                    _log_problem("restore_manifest_mismatch_checks_failed", {
                        "result": mismatch_result,
                        "checks": mismatch_checks,
                    })

                rollback_user = "3004"
                storage.setup_user_space(rollback_user)
                _seed_alerts(storage, rollback_user, ["Rollback-Original"])
                rollback_archive = build_user_backup(
                    storage,
                    rollback_user,
                    "exports",
                    now=datetime(2026, 3, 11, 9, 0, 0),
                    source="export",
                    enforce_quota=False,
                )["path"]
                _seed_alerts(storage, rollback_user, ["Rollback-New"])
                real_restore = storage.restore_user_from_data

                restore_call_counter = {"count": 0}

                def _boom_restore(uid, payload):
                    if str(uid) == rollback_user and restore_call_counter["count"] == 0:
                        restore_call_counter["count"] += 1
                        raise RuntimeError("debug_restore_failure")
                    return real_restore(uid, payload)

                with patch.object(storage, "restore_user_from_data", side_effect=_boom_restore):
                    rollback_result = apply_user_restore(
                        storage,
                        rollback_user,
                        rollback_archive,
                        actor_id=rollback_user,
                        scheduler_state_module=scheduler_state,
                        source="server_restore",
                        get_role_fn=lambda _uid: "user",
                    )
                rollback_after = storage.get_all_alerts(rollback_user) or {}
                rollback_titles = [a.get("title") for a in rollback_after.get("alerts", [])]
                rollback_checks = {
                    "restore_failed": rollback_result.get("ok") is False,
                    "rollback_ok": rollback_result.get("rollback_ok") is True,
                    "original_state_restored": "Rollback-New" in rollback_titles and "Rollback-Original" not in rollback_titles,
                }
                print_section("restore_rollback_checks", {"result": rollback_result, "checks": rollback_checks})
                if not all(rollback_checks.values()):
                    _log_problem("restore_rollback_checks_failed", {
                        "result": rollback_result,
                        "titles": rollback_titles,
                        "checks": rollback_checks,
                    })

                before_size = os.path.getsize(backup_log) if os.path.isfile(backup_log) else 0
                import_result = apply_user_restore(
                    storage,
                    restore_user,
                    restore_archive,
                    actor_id=restore_user,
                    scheduler_state_module=scheduler_state,
                    source="import",
                    get_role_fn=lambda _uid: "user",
                )
                if os.path.isfile(backup_log):
                    with open(backup_log, "r", encoding="utf-8") as handle:
                        handle.seek(before_size)
                        appended = handle.read().splitlines()
                    appended_events = []
                    for line in appended:
                        try:
                            record = json.loads(line)
                        except Exception:
                            continue
                        appended_events.append(record.get("event"))
                else:
                    appended_events = []
                source_checks = {
                    "import_source_restore_ok": import_result.get("ok") is True,
                    "import_event_logged": "backup_imported" in appended_events,
                    "restored_event_logged": "backup_restored" in appended_events,
                }
                print_section("restore_source_checks", {"checks": source_checks})
                if not all(source_checks.values()):
                    _log_problem("restore_source_checks_failed", {"checks": source_checks})
            finally:
                if previous_backup_dir is None:
                    os.environ.pop("BOT_BACKUP_DIR", None)
                else:
                    os.environ["BOT_BACKUP_DIR"] = previous_backup_dir
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    routines_ok = not dbg.has_problem(
        "storage_write_lock_checks_failed",
        "storage_data_dir_checks_failed",
        "storage_images_dir_checks_failed",
        "storage_restore_roundtrip_checks_failed",
        "storage_restore_non_dict_not_rejected",
        "storage_restore_oversize_not_rejected",
        "force_runtime_state_untrust_failed",
        "runtime_state_untrust_checks_failed",
        "scheduler_prune_sent_pre_checks_failed",
        "scheduler_prune_missed_checks_failed",
        "settings_backup_keyboard_checks_failed",
        "settings_import_prompt_cleanup_failed",
        "settings_import_confirm_failed",
        "settings_import_confirm_expired_failed",
        "settings_import_confirm_exception_failed",
        "settings_import_cancel_failed",
        "storage_download_image_placement_checks_failed",
        "storage_download_image_overflow_not_rejected",
        "storage_download_image_overflow_checks_failed",
        "storage_download_image_under_quota_checks_failed",
        "export_failed",
        "export_folder_checks_failed",
        "export_logs_checks_failed",
        "import_failed",
        "invalid_archive_handling_failed",
        "export_name_collision_not_handled",
        "export_quota_not_triggered",
        "unsafe_symlink_archive_handling_failed",
        "unsafe_manifest_path_failed",
        "partial_apply_guard_failed",
        "transactional_apply_rollback_failed",
        "restore_permission_checks_failed",
        "full_restore_checks_failed",
        "restore_no_images_checks_failed",
        "restore_manifest_mismatch_checks_failed",
        "restore_rollback_checks_failed",
        "restore_source_checks_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"routines: {'OK' if routines_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
