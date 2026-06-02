#!/usr/bin/env python3
import json
import os
import sys
from uuid import uuid4


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
SCRIPT_TITLE = "admin_audit_debug"
FEATURE_TITLE = "Admin Audit Log"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _test_admin_audit_log(dbg, log_system, log_dir):
    audit_path = os.path.join(log_dir, "admin_audit.log")
    probe_id = f"probe-{uuid4()}"
    log_system("admin_audit", "debug_probe", {"probe_id": probe_id})

    found = False
    try:
        with open(audit_path, "r", encoding="utf-8") as handle:
            for line in handle.readlines()[-50:]:
                if probe_id in line:
                    found = True
                    break
    except FileNotFoundError:
        found = False

    checks = {
        "audit_log_exists": os.path.exists(audit_path),
        "probe_found": found,
    }
    dbg.section("audit_checks", {"audit_path": audit_path, "checks": checks})
    if not all(checks.values()):
        dbg.problem("audit_log_failed", {"checks": checks})


def _read_recent_audit_records(audit_path, max_lines=200):
    records = []
    try:
        with open(audit_path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()[-max_lines:]
    except FileNotFoundError:
        return records
    for raw in lines:
        line = (raw or "").strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    return records


def _test_user_detail_audit_event(dbg, log_dir, log_user_detail_render):
    class _StorageStub:
        def __init__(self):
            self.events = []

        def log_user_event(self, user_id, event_type, payload):
            self.events.append({
                "user_id": str(user_id),
                "event": event_type,
                "payload": payload or {},
            })
            return True

    storage = _StorageStub()
    marker = f"audit-marker-{uuid4()}"
    source = f"unit_{marker}"
    log_user_detail_render(
        storage,
        actor_id=999,
        actor_role="admin",
        target_id="1001",
        target_role="user",
        source=source,
        delivery="callback_edit",
        text="dummy text for hashing only",
        ok=True,
    )
    source_reason = f"{source}_reason"
    leak_probe = "SENSITIVE_TEXT_SHOULD_NOT_APPEAR"
    log_user_detail_render(
        storage,
        actor_id=999,
        actor_role="admin",
        target_id="1002",
        target_role="user",
        source=source_reason,
        delivery="callback_edit",
        text="dummy text for hashing only",
        ok=False,
        reason=f"bad_request:{leak_probe}",
    )

    user_event = next((e for e in storage.events if e.get("event") == "manage_user_detail_rendered"), None)
    user_event_reason = next((e for e in storage.events if e.get("payload", {}).get("source") == source_reason), None)
    payload = user_event.get("payload") if isinstance(user_event, dict) else {}
    payload_reason = user_event_reason.get("payload") if isinstance(user_event_reason, dict) else {}
    user_checks = {
        "user_event_logged": user_event is not None,
        "has_actor_role": payload.get("actor_role") == "admin",
        "has_target_role": payload.get("target_role") == "user",
        "has_source": payload.get("source") == source,
        "has_delivery": payload.get("delivery") == "callback_edit",
        "metadata_only": "text" not in payload and "text_len" in payload and "text_hash" in payload,
        "reason_code_sanitized": payload_reason.get("reason") == "bad_request",
        "reason_no_leak": leak_probe not in str(payload_reason),
    }

    audit_path = os.path.join(log_dir, "admin_audit.log")
    records = _read_recent_audit_records(audit_path)
    audit_record = None
    for record in reversed(records):
        if record.get("event") != "manage_user_detail_rendered":
            continue
        rp = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        if rp.get("source") == source:
            audit_record = record
            break
    audit_reason_record = None
    for record in reversed(records):
        if record.get("event") != "manage_user_detail_render_failed":
            continue
        rp = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        if rp.get("source") == source_reason:
            audit_reason_record = record
            break
    audit_payload = audit_record.get("payload") if isinstance(audit_record, dict) else {}
    audit_reason_payload = audit_reason_record.get("payload") if isinstance(audit_reason_record, dict) else {}
    audit_checks = {
        "audit_record_logged": audit_record is not None,
        "audit_actor_id": audit_payload.get("actor_id") == "999",
        "audit_actor_role": audit_payload.get("actor_role") == "admin",
        "audit_target_id": audit_payload.get("target_id") == "1001",
        "audit_target_role": audit_payload.get("target_role") == "user",
        "audit_source": audit_payload.get("source") == source,
        "audit_reason_record_logged": audit_reason_record is not None,
        "audit_reason_sanitized": audit_reason_payload.get("reason") == "bad_request",
        "audit_reason_no_leak": leak_probe not in str(audit_reason_payload),
    }

    checks = {}
    checks.update({f"user_{k}": v for k, v in user_checks.items()})
    checks.update({f"audit_{k}": v for k, v in audit_checks.items()})
    dbg.section("user_detail_audit_event", {
        "checks": checks,
        "user_payload": payload,
        "user_reason_payload": payload_reason,
        "audit_payload": audit_payload,
        "audit_reason_payload": audit_reason_payload,
    })
    if not all(checks.values()):
        dbg.problem("audit_log_failed", {"checks": checks})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.systemlog import LOG_DIR, log_system
            from modules.handlers.user_list import log_user_detail_render
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _test_admin_audit_log(dbg, log_system, LOG_DIR)
        _test_user_detail_audit_event(dbg, LOG_DIR, log_user_detail_render)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    audit_ok = not dbg.has_problem("audit_log_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"audit: {'OK' if audit_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
