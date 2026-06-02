import os
import json
import tempfile
from dataclasses import dataclass


@dataclass
class WhitelistRequestsApi:
    load_whitelist_requests: object
    upsert_whitelist_request: object
    remove_whitelist_request: object
    update_whitelist_request: object
    ensure_whitelist_request: object
    update_whitelist_request_message: object
    resolve_whitelist_request: object
    get_whitelist_request_state: object


def _request_for_user(payload, user_id):
    uid = str(user_id)
    requests = payload.get("requests") if isinstance(payload, dict) else []
    # Prefer latest record to avoid stale assertions on duplicate/corrupted state.
    for record in reversed(requests or []):
        if isinstance(record, dict) and str(record.get("user_id")) == uid:
            return record
    return None


def _test_request_flow(dbg, api):
    with tempfile.TemporaryDirectory() as tmpdir:
        requests_path = os.path.join(tmpdir, "whitelist_requests.json")
        state_path = os.path.join(tmpdir, "whitelist_request_state.json")

        empty = api.load_whitelist_requests(path=requests_path)
        checks = {
            "empty_payload": isinstance(empty, dict) and empty.get("requests") == [],
        }
        dbg.section("requests_empty", {"payload": empty, "checks": checks})
        if not all(checks.values()):
            dbg.problem("request_flow_failed", {"step": "empty", "checks": checks})
            return

        first_ts = "2026-02-09T12:00:00"
        ok_first = api.upsert_whitelist_request(
            user_id=123,
            username="@Alice",
            display_name="Alice Example",
            request_message="Hi admins, I am Alice.",
            now_iso=first_ts,
            path=requests_path,
        )
        payload = api.load_whitelist_requests(path=requests_path)
        first_req = _request_for_user(payload, 123)
        checks = {
            "upsert_first_ok": ok_first is True,
            "first_request_count": first_req and first_req.get("request_count") == 1,
            "first_requested_at": first_req and first_req.get("first_requested_at") == first_ts,
            "last_requested_at": first_req and first_req.get("last_requested_at") == first_ts,
            "username_normalized": first_req and first_req.get("username") == "Alice",
            "display_name_saved": first_req and first_req.get("display_name") == "Alice Example",
            "request_message_saved": first_req and first_req.get("request_message") == "Hi admins, I am Alice.",
        }
        dbg.section("requests_first", {"payload": payload, "checks": checks})
        if not all(checks.values()):
            dbg.problem("request_flow_failed", {"step": "first", "checks": checks, "payload": payload})
            return

        second_ts = "2026-02-09T12:05:00"
        ok_second = api.upsert_whitelist_request(
            user_id=123,
            username="AliceNew",
            request_message="Updated message for verification.",
            now_iso=second_ts,
            path=requests_path,
        )
        payload = api.load_whitelist_requests(path=requests_path)
        second_req = _request_for_user(payload, 123)
        checks = {
            "upsert_second_ok": ok_second is True,
            "second_request_count": second_req and second_req.get("request_count") == 2,
            "first_requested_at_unchanged": second_req and second_req.get("first_requested_at") == first_ts,
            "last_requested_at_updated": second_req and second_req.get("last_requested_at") == second_ts,
            "username_updated": second_req and second_req.get("username") == "AliceNew",
            "request_message_updated": second_req and second_req.get("request_message") == "Updated message for verification.",
        }
        dbg.section("requests_second", {"payload": payload, "checks": checks})
        if not all(checks.values()):
            dbg.problem("request_flow_failed", {"step": "second", "checks": checks, "payload": payload})
            return

        ok_update = api.update_whitelist_request(
            123,
            custom_name="Custom Alice",
            label_order=["custom_name", "username", "display_name", "user_id"],
            path=requests_path,
            state_path=state_path,
        )
        payload = api.load_whitelist_requests(path=requests_path)
        updated_req = _request_for_user(payload, 123)
        checks = {
            "update_ok": ok_update is True,
            "custom_name_saved": updated_req and updated_req.get("custom_name") == "Custom Alice",
            "label_order_saved": updated_req and updated_req.get("label_order") == ["custom_name", "username", "display_name", "user_id"],
        }
        dbg.section("requests_update", {"payload": payload, "checks": checks})
        if not all(checks.values()):
            dbg.problem("request_flow_failed", {"step": "update", "checks": checks, "payload": payload})
            return

        ensured = api.ensure_whitelist_request(
            user_id=123,
            username="AliceNew",
            display_name="Alice Example",
            request_message="Final pending message.",
            now_iso="2026-02-09T12:06:00",
            requests_path=requests_path,
            state_path=state_path,
        )
        state = api.get_whitelist_request_state(123, path=state_path)
        checks = {
            "ensure_ok": ensured.get("ok") is True,
            "state_pending": state and state.get("status") == "pending",
            "state_custom_name": state and state.get("custom_name") == "Custom Alice",
            "state_label_order": state and state.get("label_order") == ["custom_name", "username", "display_name", "user_id"],
            "state_request_message": state and state.get("request_message") == "Final pending message.",
        }
        dbg.section("request_state_sync", {"state": state, "checks": checks})
        if not all(checks.values()):
            dbg.problem("request_flow_failed", {"step": "state_sync", "checks": checks, "state": state})
            return

        ok_third = api.upsert_whitelist_request(
            user_id=123,
            username="AliceAgain",
            now_iso="2026-02-09T12:10:00",
            path=requests_path,
        )
        payload = api.load_whitelist_requests(path=requests_path)
        third_req = _request_for_user(payload, 123)
        third_count = third_req.get("request_count") if isinstance(third_req, dict) else None
        checks = {
            "upsert_third_ok": ok_third is True,
            "custom_name_preserved": third_req and third_req.get("custom_name") == "Custom Alice",
            "label_order_preserved": third_req and third_req.get("label_order") == ["custom_name", "username", "display_name", "user_id"],
            "request_message_preserved": third_req and third_req.get("request_message") == "Final pending message.",
        }
        dbg.section("requests_preserve", {"payload": payload, "checks": checks})
        if not all(checks.values()):
            dbg.problem("request_flow_failed", {"step": "preserve", "checks": checks, "payload": payload})
            return

        edited_ts = "2026-02-09T12:11:00"
        msg_update = api.update_whitelist_request_message(
            user_id=123,
            request_message="Edited pending message.",
            now_iso=edited_ts,
            requests_path=requests_path,
            state_path=state_path,
        )
        payload = api.load_whitelist_requests(path=requests_path)
        edited_req = _request_for_user(payload, 123)
        edited_state = api.get_whitelist_request_state(123, path=state_path)
        checks = {
            "message_update_status": msg_update.get("status") == "updated",
            "message_update_ok": msg_update.get("request_ok") is True and msg_update.get("state_ok") is True,
            "message_updated_in_request": edited_req and edited_req.get("request_message") == "Edited pending message.",
            "message_updated_in_state": edited_state and edited_state.get("request_message") == "Edited pending message.",
            "count_unchanged": edited_req and edited_req.get("request_count") == third_count,
            "first_requested_at_unchanged": edited_req and edited_req.get("first_requested_at") == first_ts,
            "last_requested_at_unchanged": edited_req and edited_req.get("last_requested_at") == "2026-02-09T12:10:00",
            "state_updated_at_set": edited_state and edited_state.get("updated_at") == edited_ts,
        }
        dbg.section("requests_message_update", {
            "result": msg_update,
            "request": edited_req,
            "state": edited_state,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("request_flow_failed", {"step": "message_update", "checks": checks})
            return

        resolved = api.resolve_whitelist_request(
            user_id=123,
            action="approved",
            actor_id=999,
            actor_role="admin",
            actor_label="AdminUser",
            now_iso="2026-02-09T12:20:00",
            requests_path=requests_path,
            state_path=state_path,
        )
        state_after = api.get_whitelist_request_state(123, path=state_path)
        checks = {
            "resolved_status": resolved.get("status") in {"resolved", "resolved_partial"},
            "state_resolved": state_after and state_after.get("status") == "approved",
            "state_has_snapshot": state_after and isinstance(state_after.get("request"), dict),
            "snapshot_request_message": state_after and (state_after.get("request") or {}).get("request_message") == "Edited pending message.",
        }
        dbg.section("request_resolve", {"state": state_after, "checks": checks})
        if not all(checks.values()):
            dbg.problem("request_flow_failed", {"step": "resolve", "checks": checks, "state": state_after})
            return

        renewed = api.ensure_whitelist_request(
            user_id=123,
            username="AliceAgain",
            display_name="Alice Example",
            now_iso="2026-02-09T12:30:00",
            requests_path=requests_path,
            state_path=state_path,
        )
        state_reset = api.get_whitelist_request_state(123, path=state_path)
        checks = {
            "renew_ok": renewed.get("ok") is True,
            "reset_pending": state_reset and state_reset.get("status") == "pending",
            "resolved_cleared": state_reset and not state_reset.get("resolved_at"),
        }
        dbg.section("request_reset", {"state": state_reset, "checks": checks})
        if not all(checks.values()):
            dbg.problem("request_flow_failed", {"step": "reset", "checks": checks, "state": state_reset})
            return

        removed = api.remove_whitelist_request(123, path=requests_path)
        payload = api.load_whitelist_requests(path=requests_path)
        checks = {
            "removed_true": removed is True,
            "requests_empty_after_remove": payload.get("requests") == [],
        }
        dbg.section("requests_remove", {"payload": payload, "checks": checks})
        if not all(checks.values()):
            dbg.problem("request_flow_failed", {"step": "remove", "checks": checks, "payload": payload})
            return

        removed_again = api.remove_whitelist_request(123, path=requests_path)
        checks = {
            "removed_missing_false": removed_again is False,
        }
        dbg.section("requests_remove_missing", {"checks": checks})
        if not all(checks.values()):
            dbg.problem("request_flow_failed", {"step": "remove_missing", "checks": checks})


def _test_message_update_edge_cases(dbg, api):
    with tempfile.TemporaryDirectory() as tmpdir:
        requests_path = os.path.join(tmpdir, "whitelist_requests.json")
        state_path = os.path.join(tmpdir, "whitelist_request_state.json")

        # Edge case 1: request exists but state is missing/corrupted -> helper self-heals pending state.
        api.ensure_whitelist_request(
            user_id=777,
            username="Carol",
            display_name="Carol Test",
            request_message="Original Carol message",
            now_iso="2026-02-10T10:00:00",
            requests_path=requests_path,
            state_path=state_path,
        )
        with open(state_path, "w", encoding="utf-8") as handle:
            json.dump({"requests": {}, "meta": {}}, handle, indent=2)

        healed = api.update_whitelist_request_message(
            user_id=777,
            request_message="Healed Carol message",
            now_iso="2026-02-10T10:05:00",
            requests_path=requests_path,
            state_path=state_path,
        )
        payload = api.load_whitelist_requests(path=requests_path)
        req_777 = _request_for_user(payload, 777)
        state_777 = api.get_whitelist_request_state(777, path=state_path)
        checks_heal = {
            "heal_status_updated": healed.get("status") == "updated",
            "heal_message_saved": req_777 and req_777.get("request_message") == "Healed Carol message",
            "heal_state_rebuilt": state_777 and state_777.get("status") == "pending",
            "heal_state_message_synced": state_777 and state_777.get("request_message") == "Healed Carol message",
            "heal_count_unchanged": req_777 and req_777.get("request_count") == 1,
        }
        dbg.section("message_update_heal_missing_state", {
            "result": healed,
            "request": req_777,
            "state": state_777,
            "checks": checks_heal,
        })

        # Edge case 2: inconsistent approved state should block pending-message edits.
        api.upsert_whitelist_request(
            user_id=888,
            request_message="Original Bob message",
            now_iso="2026-02-10T11:00:00",
            path=requests_path,
        )
        with open(state_path, "r", encoding="utf-8") as handle:
            state_payload = json.load(handle)
        requests_block = state_payload.get("requests") if isinstance(state_payload, dict) else None
        if not isinstance(requests_block, dict):
            requests_block = {}
        requests_block["888"] = {
            "status": "approved",
            "updated_at": "2026-02-10T11:01:00",
        }
        state_payload["requests"] = requests_block
        if "meta" not in state_payload or not isinstance(state_payload.get("meta"), dict):
            state_payload["meta"] = {}
        with open(state_path, "w", encoding="utf-8") as handle:
            json.dump(state_payload, handle, indent=2)

        blocked = api.update_whitelist_request_message(
            user_id=888,
            request_message="Should not be written",
            now_iso="2026-02-10T11:05:00",
            requests_path=requests_path,
            state_path=state_path,
        )
        payload = api.load_whitelist_requests(path=requests_path)
        req_888 = _request_for_user(payload, 888)
        checks_block = {
            "blocked_status": blocked.get("status") == "not_pending",
            "blocked_request_unchanged": req_888 and req_888.get("request_message") == "Original Bob message",
            "blocked_no_write_flags": blocked.get("request_ok") is False and blocked.get("state_ok") is False,
        }
        dbg.section("message_update_block_resolved_state", {
            "result": blocked,
            "request": req_888,
            "checks": checks_block,
        })

        if not (all(checks_heal.values()) and all(checks_block.values())):
            dbg.problem("message_update_edge_cases_failed", {
                "checks_heal": checks_heal,
                "checks_block": checks_block,
            })


def _test_reject_rerequest_history(dbg, api):
    with tempfile.TemporaryDirectory() as tmpdir:
        requests_path = os.path.join(tmpdir, "whitelist_requests.json")
        state_path = os.path.join(tmpdir, "whitelist_request_state.json")

        t1 = "2026-02-09T12:00:00"
        result1 = api.ensure_whitelist_request(
            user_id=456,
            username="Bob",
            display_name="Bob Test",
            request_message="Initial Bob message",
            now_iso=t1,
            requests_path=requests_path,
            state_path=state_path,
        )
        state1 = api.get_whitelist_request_state(456, path=state_path)
        checks1 = {
            "created": result1.get("created") is True,
            "first_requested_at": state1 and state1.get("first_requested_at") == t1,
            "request_count_1": state1 and state1.get("request_count") == 1,
            "status_pending": state1 and state1.get("status") == "pending",
            "message_saved": state1 and state1.get("request_message") == "Initial Bob message",
        }
        dbg.section("reject_rerequest_step1", {"state": state1, "checks": checks1})

        t2 = "2026-02-09T12:10:00"
        resolved1 = api.resolve_whitelist_request(
            user_id=456,
            action="rejected",
            actor_id=999,
            actor_role="admin",
            now_iso=t2,
            requests_path=requests_path,
            state_path=state_path,
        )
        state2 = api.get_whitelist_request_state(456, path=state_path)
        checks2 = {
            "resolved": resolved1.get("status") in {"resolved", "resolved_partial"},
            "state_rejected": state2 and state2.get("status") == "rejected",
            "snapshot_exists": state2 and isinstance(state2.get("request"), dict),
            "snapshot_first_at": (
                state2 and isinstance(state2.get("request"), dict) and state2["request"].get("first_requested_at") == t1
            ),
        }
        dbg.section("reject_rerequest_step2", {"state": state2, "checks": checks2})

        t3 = "2026-02-09T12:30:00"
        result3 = api.ensure_whitelist_request(
            user_id=456,
            username="Bob",
            display_name="Bob Test",
            request_message="Second Bob message",
            now_iso=t3,
            requests_path=requests_path,
            state_path=state_path,
        )
        state3 = api.get_whitelist_request_state(456, path=state_path)
        checks3 = {
            "rerequest_ok": result3.get("ok") is True,
            "first_requested_at_preserved": state3 and state3.get("first_requested_at") == t1,
            "request_count_2": state3 and state3.get("request_count") == 2,
            "status_pending": state3 and state3.get("status") == "pending",
            "resolved_at_cleared": state3 and not state3.get("resolved_at"),
            "snapshot_cleared": state3 and state3.get("request") is None,
            "message_updated": state3 and state3.get("request_message") == "Second Bob message",
        }
        dbg.section("reject_rerequest_step3", {"state": state3, "checks": checks3})

        t4 = "2026-02-09T12:40:00"
        api.resolve_whitelist_request(
            user_id=456,
            action="rejected",
            actor_id=999,
            actor_role="admin",
            now_iso=t4,
            requests_path=requests_path,
            state_path=state_path,
        )

        t5 = "2026-02-09T13:00:00"
        result5 = api.ensure_whitelist_request(
            user_id=456,
            username="Bob",
            display_name="Bob Test",
            now_iso=t5,
            requests_path=requests_path,
            state_path=state_path,
        )
        state5 = api.get_whitelist_request_state(456, path=state_path)
        checks5 = {
            "third_rerequest_ok": result5.get("ok") is True,
            "first_requested_at_still_original": state5 and state5.get("first_requested_at") == t1,
            "request_count_3": state5 and state5.get("request_count") == 3,
            "status_pending": state5 and state5.get("status") == "pending",
        }
        dbg.section("reject_rerequest_step5", {"state": state5, "checks": checks5})

        all_ok = all(checks1.values()) and all(checks2.values()) and all(checks3.values()) and all(checks5.values())
        if not all_ok:
            dbg.problem("reject_rerequest_history_failed", {
                "checks1": checks1,
                "checks2": checks2,
                "checks3": checks3,
                "checks5": checks5,
            })


def run_checks(dbg, api):
    _test_request_flow(dbg, api)
    _test_message_update_edge_cases(dbg, api)
    _test_reject_rerequest_history(dbg, api)
