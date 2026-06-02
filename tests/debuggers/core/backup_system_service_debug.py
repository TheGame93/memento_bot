#!/usr/bin/env python3
import asyncio
import json
import os
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta
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
SCRIPT_TITLE = "backup_system_service_debug"
FEATURE_TITLE = "System Backup Service"

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


def _write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _hash_bytes(payload):
    from modules.backup_core.manifest import hash_bytes

    return hash_bytes(payload)


def _make_system_archive(path, entries, created_at, schema_version):
    files = []
    for rel_path, content in entries.items():
        data = content if isinstance(content, bytes) else str(content).encode("utf-8")
        files.append({"path": rel_path, "size": len(data), "sha256": _hash_bytes(data)})
    manifest_payload = {
        "schema_version": schema_version,
        "scope": "system",
        "created_at": created_at,
        "files": files,
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for rel_path, content in entries.items():
            if isinstance(content, bytes):
                handle.writestr(rel_path, content)
            else:
                handle.writestr(rel_path, str(content))
        handle.writestr("manifest.json", json.dumps(manifest_payload, indent=2, ensure_ascii=False))


class _FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})


class _FakeQuery:
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
    def __init__(self, *, actor_id, callback_data):
        self.effective_user = type("U", (), {"id": actor_id})()
        self.callback_query = _FakeQuery(callback_data)
        self.effective_message = self.callback_query.message
        self.message = self.callback_query.message


class _FakeContext:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}
        self.args = []


def _prepare_project_tree(root):
    system_dir = os.path.join(root, "data", "system")
    os.makedirs(system_dir, exist_ok=True)

    _write_json(os.path.join(system_dir, "whitelist.json"), {"users": [{"id": 100, "role": "developer"}, {"id": 200, "role": "admin"}]})
    _write_json(os.path.join(system_dir, "whitelist_requests.json"), {"requests": []})
    _write_json(os.path.join(system_dir, "whitelist_invites.json"), {"invites": []})
    _write_json(os.path.join(system_dir, "whitelist_request_state.json"), {"requests": {}, "meta": {}})
    _write_json(os.path.join(system_dir, "runtime_state.json"), {"ephemeral": True})


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        with tempfile.TemporaryDirectory() as tmpdir:
            env_backup = os.environ.get("BOT_BACKUP_DIR")
            env_data = os.environ.get("BOT_DATA_DIR")
            os.environ["BOT_BACKUP_DIR"] = os.path.join(tmpdir, "backups")
            os.environ["BOT_DATA_DIR"] = os.path.join(tmpdir, "runtime_data")

            try:
                project_root = os.path.join(tmpdir, "project")
                backup_dir = os.path.join(tmpdir, "system_backups")
                os.makedirs(project_root, exist_ok=True)
                os.makedirs(backup_dir, exist_ok=True)
                _prepare_project_tree(project_root)

                from modules.backup_core.constants import BACKUP_SCHEMA_VERSION
                import modules.backup_core.system_backup as system_backup

                now = datetime(2026, 4, 29, 12, 0, 0)
                built = system_backup.build_system_backup(now=now, base_dir=project_root, backup_dir=backup_dir)
                built_path = built.get("path")

                with zipfile.ZipFile(built_path, "r") as handle:
                    names = set(handle.namelist())
                build_checks = {
                    "archive_created": bool(built_path and os.path.isfile(built_path)),
                    "manifest_present": "manifest.json" in names,
                    "whitelist_present": "data/system/whitelist.json" in names,
                    "runtime_state_excluded": "data/system/runtime_state.json" not in names,
                    "state_file_included": "data/system/system_backup_state.json" in names,
                }
                print_section("build_checks", {"checks": build_checks})
                if not all(build_checks.values()):
                    _log_problem("build_checks_failed", {"checks": build_checks, "names": sorted(names)})

                listed = system_backup.list_system_backups(backup_dir=backup_dir)
                list_checks = {
                    "listed": len(listed) >= 1,
                    "list_has_size": all(isinstance(item.get("size_bytes"), int) for item in listed),
                }
                print_section("list_checks", {"checks": list_checks})
                if not all(list_checks.values()):
                    _log_problem("list_checks_failed", {"checks": list_checks, "listed": listed})

                # Retention check with extra historical archives.
                for idx in range(3):
                    ts = (now - timedelta(days=idx + 10)).strftime("%Y%m%d_%H%M%S")
                    old_path = os.path.join(backup_dir, f"system_backup_{ts}.zip")
                    _make_system_archive(
                        old_path,
                        {
                            "data/system/whitelist.json": json.dumps({"users": [{"id": 100, "role": "developer"}]}, indent=2),
                            "data/system/whitelist_requests.json": json.dumps({"requests": []}),
                        },
                        now.isoformat(),
                        BACKUP_SCHEMA_VERSION,
                    )
                retention_result = system_backup.enforce_system_retention(now=now, backup_dir=backup_dir)
                retention_checks = {
                    "retention_stats": isinstance(retention_result.get("stats"), dict),
                }
                print_section("retention_checks", {"checks": retention_checks})
                if not all(retention_checks.values()):
                    _log_problem("retention_checks_failed", {"checks": retention_checks, "result": retention_result})

                inspected = system_backup.inspect_system_archive(built_path)
                inspect_checks = {
                    "inspect_ok": inspected.get("ok") is True,
                    "inspect_file_count": int(inspected.get("file_count") or 0) >= 2,
                }
                print_section("inspect_checks", {"checks": inspect_checks})
                if not all(inspect_checks.values()):
                    _log_problem("inspect_checks_failed", {"checks": inspect_checks, "inspected": inspected})

                # Guard checks.
                unknown_actor_checks = {
                    "none_actor_rejected": system_backup.check_restore_guards(built_path, None, lambda _uid: "developer") == (False, "actor_unknown"),
                    "unknown_actor_rejected": system_backup.check_restore_guards(built_path, "999", lambda _uid: None) == (False, "actor_unknown"),
                }
                print_section("unknown_actor_checks", {"checks": unknown_actor_checks})
                if not all(unknown_actor_checks.values()):
                    _log_problem("unknown_actor_checks_failed", {"checks": unknown_actor_checks})

                downgrade_archive = os.path.join(tmpdir, "downgrade.zip")
                _make_system_archive(
                    downgrade_archive,
                    {
                        "data/system/whitelist.json": json.dumps({"users": [{"id": 100, "role": "admin"}]}, indent=2),
                        "data/system/whitelist_requests.json": json.dumps({"requests": []}),
                    },
                    now.isoformat(),
                    BACKUP_SCHEMA_VERSION,
                )
                removed_actor_archive = os.path.join(tmpdir, "removed_actor.zip")
                _make_system_archive(
                    removed_actor_archive,
                    {
                        "data/system/whitelist.json": json.dumps({"users": [{"id": 200, "role": "developer"}]}, indent=2),
                        "data/system/whitelist_requests.json": json.dumps({"requests": []}),
                    },
                    now.isoformat(),
                    BACKUP_SCHEMA_VERSION,
                )
                no_devs_archive = os.path.join(tmpdir, "no_devs.zip")
                _make_system_archive(
                    no_devs_archive,
                    {
                        "data/system/whitelist.json": json.dumps({"users": [{"id": 200, "role": "admin"}]}, indent=2),
                        "data/system/whitelist_requests.json": json.dumps({"requests": []}),
                    },
                    now.isoformat(),
                    BACKUP_SCHEMA_VERSION,
                )
                guard_checks = {
                    "downgrade_rejected": system_backup.check_restore_guards(downgrade_archive, "100", lambda _uid: "developer") == (False, "no_developers_in_archive"),
                    "removed_rejected": system_backup.check_restore_guards(removed_actor_archive, "100", lambda _uid: "developer") == (False, "actor_self_downgrade"),
                    "viability_rejected": system_backup.check_restore_guards(no_devs_archive, "200", lambda _uid: "developer") == (False, "no_developers_in_archive"),
                }
                print_section("guard_checks", {"checks": guard_checks})
                if not all(guard_checks.values()):
                    _log_problem("guard_checks_failed", {"checks": guard_checks})

                # Apply restore success + cache invalidation.
                restore_archive = os.path.join(tmpdir, "restore_ok.zip")
                _make_system_archive(
                    restore_archive,
                    {
                        "data/system/whitelist.json": json.dumps({"users": [{"id": 100, "role": "developer"}]}, indent=2),
                        "data/system/whitelist_requests.json": json.dumps({"requests": [{"id": 1}]}),
                        "data/system/whitelist_invites.json": json.dumps({"invites": [{"id": 2}]}),
                    },
                    now.isoformat(),
                    BACKUP_SCHEMA_VERSION,
                )
                with patch.object(system_backup, "invalidate_role_map_cache") as invalidate_mock:
                    apply_result = system_backup.apply_system_restore(
                        restore_archive,
                        actor_id="100",
                        get_role_fn=lambda _uid: "developer",
                        base_dir=project_root,
                    )
                    invalidated = invalidate_mock.called
                with open(os.path.join(project_root, "data", "system", "whitelist_requests.json"), "r", encoding="utf-8") as handle:
                    restored_requests = json.load(handle)
                apply_checks = {
                    "apply_ok": apply_result.get("ok") is True,
                    "snapshot_created": bool(apply_result.get("snapshot_path")),
                    "files_restored_positive": int(apply_result.get("files_restored") or 0) >= 1,
                    "cache_invalidated": invalidated is True,
                    "content_restored": restored_requests.get("requests") == [{"id": 1}],
                }
                print_section("apply_checks", {"checks": apply_checks, "result": apply_result})
                if not all(apply_checks.values()):
                    _log_problem("apply_checks_failed", {"checks": apply_checks, "result": apply_result})

                # Hash mismatch rejected.
                bad_hash_archive = os.path.join(tmpdir, "bad_hash.zip")
                bad_manifest = {
                    "schema_version": BACKUP_SCHEMA_VERSION,
                    "scope": "system",
                    "created_at": now.isoformat(),
                    "files": [
                        {"path": "data/system/whitelist.json", "size": 2, "sha256": "0" * 64},
                    ],
                }
                with zipfile.ZipFile(bad_hash_archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
                    handle.writestr("data/system/whitelist.json", "{}")
                    handle.writestr("manifest.json", json.dumps(bad_manifest, indent=2))
                bad_apply = system_backup.apply_system_restore(
                    bad_hash_archive,
                    actor_id="100",
                    get_role_fn=lambda _uid: "developer",
                    base_dir=project_root,
                )
                if not (bad_apply.get("ok") is False and bad_apply.get("error") == "archive_invalid"):
                    _log_problem("hash_validation_failed", {"result": bad_apply})

                # Durable monthly state + developer-only email delivery.
                class _FakeStorage:
                    def get_backup_prefs(self, user_id):
                        if str(user_id) == "100":
                            return {"email_enabled": True, "email_address": "dev@example.com"}
                        return {"email_enabled": True, "email_address": "admin@example.com"}

                fake_storage = _FakeStorage()
                fake_config = {
                    "host": "smtp.example.com",
                    "port": 587,
                    "user": "u",
                    "password": "p",
                    "from_addr": "from@example.com",
                    "tls": True,
                    "ssl": False,
                }
                sent_calls = []

                def _fake_send(msg, _cfg):
                    sent_calls.append(msg["To"])

                with patch.object(system_backup, "list_whitelist_users", return_value=[
                    {"id": "100", "role": "developer"},
                    {"id": "200", "role": "admin"},
                ]), patch.object(system_backup, "_smtp_config", return_value=(fake_config, None)), patch.object(system_backup, "_send_email", side_effect=_fake_send):
                    mail_results = system_backup.send_system_backup_email(["100", "200"], fake_storage, now=now)

                state_path = os.path.join(project_root, "data", "system", "system_backup_state.json")
                if not os.path.isfile(state_path):
                    # system_backup uses PROJECT_ROOT state path; check fallback there.
                    state_path = os.path.join(ROOT_DIR, "data", "system", "system_backup_state.json")
                state_payload = {}
                if os.path.isfile(state_path):
                    with open(state_path, "r", encoding="utf-8") as handle:
                        state_payload = json.load(handle)

                mail_checks = {
                    "developer_only_sent": sent_calls == ["dev@example.com"],
                    "mail_results_len": len(mail_results) == 1,
                    "durable_state_has_slot": isinstance(state_payload.get("monthly_send_slots"), dict),
                }
                print_section("mail_checks", {"checks": mail_checks, "results": mail_results, "sent_calls": sent_calls})
                if not all(mail_checks.values()):
                    _log_problem("mail_checks_failed", {"checks": mail_checks, "results": mail_results, "state": state_payload})

                # Flow-level checks for /manage -> Backups -> System Backup handlers.
                import modules.handlers.backup_manage as backup_manage
                original_runtime_storage = backup_manage.get_runtime_storage
                original_build_system_backup = backup_manage.system_backup.build_system_backup
                original_list_system_backups = backup_manage.system_backup.list_system_backups
                original_check_restore_guards = backup_manage.system_backup.check_restore_guards
                original_inspect_system_archive = backup_manage.system_backup.inspect_system_archive
                original_apply_system_restore = backup_manage.system_backup.apply_system_restore
                original_normalize_role = backup_manage._normalize_role
                try:
                    fake_storage = type("S", (), {
                        "roles": {"1": "admin", "2": "developer"},
                        "get_user_role": lambda self, uid: self.roles.get(str(uid), "user"),
                        "get_user_prefs": lambda self, uid: {},
                    })()
                    backup_manage.get_runtime_storage = lambda _ctx: fake_storage

                    nondev_update = _FakeUpdate(actor_id=1, callback_data="mgmt_backups")
                    dev_update = _FakeUpdate(actor_id=2, callback_data="mgmt_backups")
                    nondev_ctx = _FakeContext()
                    dev_ctx = _FakeContext()

                    asyncio.run(backup_manage.handle_manage_backups(nondev_update, nondev_ctx))
                    asyncio.run(backup_manage.handle_manage_backups(dev_update, dev_ctx))
                    nondev_text = (nondev_update.callback_query.edits[-1]["text"]
                                   if nondev_update.callback_query.edits else "")
                    dev_markup = (dev_update.callback_query.edits[-1]["kwargs"].get("reply_markup")
                                  if dev_update.callback_query.edits else None)
                    dev_labels = []
                    if dev_markup is not None:
                        dev_labels = [btn.text for row in dev_markup.inline_keyboard for btn in row]
                    visibility_checks = {
                        "nondev_has_no_system_button": "System Backup" not in nondev_text,
                        "dev_has_system_button": any("System Backup" in label for label in dev_labels),
                    }
                    print_section("flow_visibility_checks", {"checks": visibility_checks, "dev_labels": dev_labels})
                    if not all(visibility_checks.values()):
                        _log_problem("flow_visibility_checks_failed", {"checks": visibility_checks, "dev_labels": dev_labels, "nondev_text": nondev_text})

                    export_called = {"count": 0}
                    backup_manage.system_backup.build_system_backup = lambda **kwargs: (
                        export_called.__setitem__("count", export_called["count"] + 1) or {
                            "path": built_path,
                            "file_count": 3,
                        }
                    )
                    export_update = _FakeUpdate(actor_id=2, callback_data="mgmt_system_backup_export")
                    export_ctx = _FakeContext()
                    asyncio.run(backup_manage.handle_system_backup_export(export_update, export_ctx))
                    export_text = export_update.callback_query.edits[-1]["text"] if export_update.callback_query.edits else ""
                    export_checks = {
                        "export_called": export_called["count"] == 1,
                        "export_text_has_files": "Files:" in export_text,
                        "export_text_has_size": "Size:" in export_text,
                    }
                    print_section("flow_export_checks", {"checks": export_checks})
                    if not all(export_checks.values()):
                        _log_problem("flow_export_checks_failed", {"checks": export_checks, "text": export_text})

                    list_items = [
                        {"path": "/tmp/sys_old.zip", "timestamp": datetime(2026, 1, 1, 10, 0, 0), "size_bytes": 111},
                        {"path": "/tmp/sys_new.zip", "timestamp": datetime(2026, 2, 1, 10, 0, 0), "size_bytes": 222},
                    ]
                    backup_manage.system_backup.list_system_backups = lambda: list_items
                    list_update = _FakeUpdate(actor_id=2, callback_data="mgmt_system_backup_list")
                    list_ctx = _FakeContext()
                    asyncio.run(backup_manage.handle_system_backup_list(list_update, list_ctx))
                    list_edit_text = (
                        list_update.callback_query.edits[-1]["text"]
                        if list_update.callback_query.edits
                        else ""
                    )
                    list_reply_text = "\n".join(item["text"] for item in list_update.callback_query.message.replies)
                    list_text = "\n".join([list_edit_text, list_reply_text]).strip()
                    list_checks = {
                        "ordered_oldest_first": "/01" in list_text and "/02" in list_text and list_text.find("/01") < list_text.find("/02"),
                        "source_alias_set": (list_ctx.user_data.get("LIST_CONTEXT_KEY") is None) or True,
                    }
                    # Ensure actual alias source is set on canonical LIST_CONTEXT_KEY key.
                    from modules.handlers.list_alerts import LIST_CONTEXT_KEY as _LCK
                    list_checks["source_alias_set"] = (list_ctx.user_data.get(_LCK) or {}).get("source") == "backup_system_archives"
                    print_section("flow_list_checks", {"checks": list_checks})
                    if not all(list_checks.values()):
                        _log_problem("flow_list_checks_failed", {"checks": list_checks, "text": list_text})

                    # Guard-failed restore summary should not show confirm button.
                    guard_ctx = _FakeContext()
                    guard_ctx.user_data["backup_manage_session"] = {"system_backup_items": list_items}
                    backup_manage.system_backup.inspect_system_archive = lambda _p: {"ok": True, "file_count": 2}
                    backup_manage.system_backup.check_restore_guards = lambda _p, _a, _g: (False, "actor_self_downgrade")
                    guard_update = _FakeUpdate(actor_id=2, callback_data="unused")
                    asyncio.run(backup_manage.handle_system_backup_restore_select(guard_update, guard_ctx, "0"))
                    guard_reply = guard_update.message.replies[-1] if guard_update.message.replies else {}
                    guard_markup = guard_reply.get("kwargs", {}).get("reply_markup")
                    guard_labels = []
                    if guard_markup is not None:
                        guard_labels = [btn.text for row in guard_markup.inline_keyboard for btn in row]
                    guard_checks = {
                        "guard_reason_shown": "actor_self_downgrade" in guard_reply.get("text", ""),
                        "confirm_hidden_on_guard_fail": not any("Confirm System Restore" in label for label in guard_labels),
                    }
                    print_section("flow_guard_checks", {"checks": guard_checks})
                    if not all(guard_checks.values()):
                        _log_problem("flow_guard_checks_failed", {"checks": guard_checks, "reply": guard_reply})

                    # Confirm restore wires to apply_system_restore.
                    confirm_calls = []
                    backup_manage.system_backup.apply_system_restore = lambda path, actor_id, get_role_fn: (
                        confirm_calls.append({"path": path, "actor_id": actor_id}) or
                        {"ok": True, "files_restored": 4, "snapshot_path": "/tmp/snap.zip"}
                    )
                    confirm_update = _FakeUpdate(actor_id=2, callback_data="mgmt_system_backup_restore_confirm")
                    confirm_ctx = _FakeContext()
                    confirm_ctx.user_data["backup_manage_session"] = {"selected_system_backup_path": "/tmp/sys_old.zip"}
                    asyncio.run(backup_manage.handle_system_backup_restore_confirm(confirm_update, confirm_ctx))
                    confirm_text = confirm_update.callback_query.edits[-1]["text"] if confirm_update.callback_query.edits else ""
                    confirm_checks = {
                        "apply_called_once": len(confirm_calls) == 1,
                        "success_message_rendered": "System restore completed" in confirm_text,
                    }
                    print_section("flow_confirm_checks", {"checks": confirm_checks})
                    if not all(confirm_checks.values()):
                        _log_problem("flow_confirm_checks_failed", {"checks": confirm_checks, "text": confirm_text})
                finally:
                    backup_manage.get_runtime_storage = original_runtime_storage
                    backup_manage.system_backup.build_system_backup = original_build_system_backup
                    backup_manage.system_backup.list_system_backups = original_list_system_backups
                    backup_manage.system_backup.check_restore_guards = original_check_restore_guards
                    backup_manage.system_backup.inspect_system_archive = original_inspect_system_archive
                    backup_manage.system_backup.apply_system_restore = original_apply_system_restore
                    backup_manage._normalize_role = original_normalize_role

            finally:
                if env_backup is None:
                    os.environ.pop("BOT_BACKUP_DIR", None)
                else:
                    os.environ["BOT_BACKUP_DIR"] = env_backup
                if env_data is None:
                    os.environ.pop("BOT_DATA_DIR", None)
                else:
                    os.environ["BOT_DATA_DIR"] = env_data

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    checks_ok = not dbg.has_problem(
        "build_checks_failed",
        "list_checks_failed",
        "retention_checks_failed",
        "inspect_checks_failed",
        "unknown_actor_checks_failed",
        "guard_checks_failed",
        "apply_checks_failed",
        "hash_validation_failed",
        "mail_checks_failed",
        "flow_visibility_checks_failed",
        "flow_export_checks_failed",
        "flow_list_checks_failed",
        "flow_guard_checks_failed",
        "flow_confirm_checks_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"checks: {'OK' if checks_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
