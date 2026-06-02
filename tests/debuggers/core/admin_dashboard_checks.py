import re
from dataclasses import dataclass


@dataclass
class AdminHelpers:
    build_invite_message: object
    build_requests_list: object
    build_users_list: object
    build_user_status: object
    is_admin_role: object
    is_self_removal: object
    is_target_whitelisted: object
    md_escape: object
    removal_result_text: object
    requests_text: object
    user_status_keyboard: object


def _extract_alias_rows(text):
    rows = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if len(line) < 4 or not line.startswith("/"):
            continue
        match = re.match(r"^/(\d{2})\s+(?:[🟣🟢🟠🔴]\s+)?(.+?)\s+\|\s+(\d+-\d+-\d+)$", line)
        if match is None:
            continue
        alias = match.group(1)
        rows[alias] = {
            "line": line,
            "summary": match.group(3),
        }
    return rows


def _test_markdown_escape(dbg, helpers):
    raw = "Name_*[`\\]\nLine"
    escaped = helpers.md_escape(raw)
    checks = {
        "no_newlines": "\n" not in escaped,
        "escape_star": "\\*" in escaped,
        "escape_underscore": "\\_" in escaped,
        "escape_backtick": "\\`" in escaped,
        "escape_bracket": "\\[" in escaped,
        "escape_backslash": "\\\\" in escaped,
    }
    dbg.section("markdown_escape", {"raw": raw, "escaped": escaped, "checks": checks})
    if not all(checks.values()):
        dbg.problem("admin_helpers_failed", {"step": "markdown_escape", "checks": checks})


def _test_requests_text_escape(dbg, helpers):
    requests = [
        {
            "user_id": "123",
            "username": "bad_name*",
            "display_name": "Display_[x]",
            "request_count": 1,
        },
        {
            "user_id": "456",
            "username": None,
            "display_name": "Display_[x]",
            "request_count": 1,
        },
    ]
    rendered = helpers.requests_text(requests)
    checks = {
        "escaped_username": "@bad\\_name\\*" in rendered,
        "escaped_display_name": "Display\\_\\[x]" in rendered,
    }
    dbg.section("requests_text", {"rendered": rendered, "checks": checks})
    if not all(checks.values()):
        dbg.problem("admin_helpers_failed", {"step": "requests_text", "checks": checks})


def _test_request_list_builder(dbg, helpers):
    requests = [
        {"user_id": "10", "username": "alpha", "display_name": None, "request_count": 2},
        {"user_id": "11", "username": None, "display_name": "Beta User", "request_count": 1},
    ]
    text, alias_map = helpers.build_requests_list(requests)
    checks = {
        "has_alias_01": "/01" in text,
        "has_alias_02": "/02" in text,
        "alias_map_01": alias_map.get("01") == "10",
        "alias_map_02": alias_map.get("02") == "11",
        "includes_username": "@alpha" in text,
        "includes_display_name": "Beta User" in text,
    }
    dbg.section("request_list", {"text": text, "alias_map": alias_map, "checks": checks})
    if not all(checks.values()):
        dbg.problem("admin_helpers_failed", {"step": "request_list", "checks": checks})


def _test_self_removal(dbg, helpers):
    checks = {
        "self_true": helpers.is_self_removal(10, "10") is True,
        "self_false": helpers.is_self_removal(10, "11") is False,
        "none_false": helpers.is_self_removal(None, "10") is False,
    }
    dbg.section("self_removal", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("admin_helpers_failed", {"step": "self_removal", "checks": checks})


def _test_removal_text(dbg, helpers):
    removed_text = helpers.removal_result_text("10", True)
    missing_text = helpers.removal_result_text("10", False)
    checks = {
        "removed_has_icon": "🗑️" in removed_text,
        "removed_mentions_id": "10" in removed_text,
        "missing_has_warn": "⚠️" in missing_text,
        "missing_mentions_id": "10" in missing_text,
    }
    dbg.section("removal_text", {"removed": removed_text, "missing": missing_text, "checks": checks})
    if not all(checks.values()):
        dbg.problem("admin_helpers_failed", {"step": "removal_text", "checks": checks})


def _test_users_list_builder(dbg, helpers):
    entries = [
        {"id": "20", "role": "user"},
        {"id": "21", "role": "developer"},
        {"id": "22", "role": "admin"},
        {"id": "23", "role": "developer"},
    ]
    meta_map = {
        "20": {"display_name": "Zulu User"},
        "21": {"username": "charlie"},
        "22": {"username": "bravo"},
        "23": {"username": "alpha"},
    }
    summary_map = {
        "20": {"alerts": 3, "birthdays": 1, "tags": 4},
        "21": {"alerts": 0, "birthdays": 2, "tags": 1},
        "22": {"alerts": 5, "birthdays": 0, "tags": 2},
        "23": {"alerts": 1, "birthdays": 0, "tags": 0},
    }
    text, alias_map = helpers.build_users_list(entries, meta_map, summary_map)
    alias_rows = _extract_alias_rows(text)
    summary_01 = alias_rows.get("01", {}).get("summary", "")
    summary_03 = alias_rows.get("03", {}).get("summary", "")
    checks = {
        "has_alias_01": "/01 @alpha | 1-0-0" in text,
        "has_alias_02": "/02 @charlie | 0-2-1" in text,
        "alias_map_01": alias_map.get("01") == "23",
        "alias_map_02": alias_map.get("02") == "21",
        "alias_map_03": alias_map.get("03") == "22",
        "alias_map_04": alias_map.get("04") == "20",
        "has_compact_row_format": all(alias_rows.get(key, {}).get("line") for key in ("01", "02", "03", "04")),
        "has_sections": "**DEVELOPERS**" in text and "**ADMINS**" in text and "**USERS**" in text,
        "includes_username": "@alpha" in text and "@bravo" in text and "@charlie" in text,
        "includes_display_name": "Zulu User" in text,
        "role_not_shown": "(developer)" not in text and "(admin)" not in text and "(user)" not in text,
        "summary_01_counts": summary_01 == "1-0-0",
        "summary_03_counts": summary_03 == "5-0-2",
    }
    dbg.section("users_list", {"text": text, "alias_map": alias_map, "alias_rows": alias_rows, "checks": checks})
    if not all(checks.values()):
        dbg.problem("admin_helpers_failed", {"step": "users_list", "checks": checks})


def _test_users_list_no_hard_cap(dbg, helpers):
    entries = []
    meta_map = {}
    summary_map = {}
    for idx in range(1, 26):
        uid = str(200 + idx)
        entries.append({"id": uid, "role": "user"})
        meta_map[uid] = {"username": f"user{idx:02d}"}
        summary_map[uid] = {"alerts": idx % 3, "birthdays": 0, "tags": idx % 5}

    text, alias_map = helpers.build_users_list(entries, meta_map, summary_map)
    checks = {
        "alias_count_full": len(alias_map) == 25,
        "alias_20_present": alias_map.get("20") == "220",
        "alias_21_present": alias_map.get("21") == "221",
        "alias_25_present": alias_map.get("25") == "225",
        "text_has_25th_row": "/25 @user25" in text,
        "no_truncation_footer": "Showing 20 of" not in text,
        "legend_mentions_never_active": "(no icon)=never active" in text,
    }
    dbg.section("users_list_no_hard_cap", {"alias_map_size": len(alias_map), "checks": checks})
    if not all(checks.values()):
        dbg.problem("admin_helpers_failed", {"step": "users_list_no_hard_cap", "checks": checks})


def _test_invite_message_builder(dbg, helpers):
    text = helpers.build_invite_message("@alpha", "Alpha User", "TestAlerts_Bot")
    checks = {
        "includes_username": "@alpha" in text,
        "includes_bot": "@TestAlerts_Bot" in text,
        "includes_preapproved": "pre-approved" in text,
        "includes_start": "/start" in text,
        "includes_help": "/help" in text,
    }
    dbg.section("invite_message", {"text": text, "checks": checks})
    if not all(checks.values()):
        dbg.problem("admin_helpers_failed", {"step": "invite_message", "checks": checks})


def _test_target_whitelist_guard(dbg, helpers):
    class _StorageStub:
        def __init__(self, whitelisted):
            self._whitelisted = bool(whitelisted)

        def is_user_whitelisted(self, _target_id):
            return self._whitelisted

    checks = {
        "whitelisted_true": helpers.is_target_whitelisted(_StorageStub(True), "10") is True,
        "whitelisted_false": helpers.is_target_whitelisted(_StorageStub(False), "10") is False,
    }
    dbg.section("target_whitelist_guard", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("admin_helpers_failed", {"step": "target_whitelist_guard", "checks": checks})


def _test_admin_role_protection(dbg, helpers):
    kb_user = helpers.user_status_keyboard("100", target_role="user")
    labels_user = [btn.text for row in kb_user.inline_keyboard for btn in row]

    kb_admin = helpers.user_status_keyboard("200", target_role="admin")
    labels_admin = [btn.text for row in kb_admin.inline_keyboard for btn in row]

    kb_dev = helpers.user_status_keyboard("300", target_role="developer")
    labels_dev = [btn.text for row in kb_dev.inline_keyboard for btn in row]

    kb_none = helpers.user_status_keyboard("400", target_role=None)
    labels_none = [btn.text for row in kb_none.inline_keyboard for btn in row]

    checks = {
        "user_has_remove": any("Remove" in label for label in labels_user),
        "admin_no_remove": not any("Remove" in label for label in labels_admin),
        "dev_no_remove": not any("Remove" in label for label in labels_dev),
        "none_has_remove": any("Remove" in label for label in labels_none),
        "user_has_back": any("Back" in label for label in labels_user),
        "admin_has_back": any("Back" in label for label in labels_admin),
        "dev_has_back": any("Back" in label for label in labels_dev),
        "is_admin_role_true_admin": helpers.is_admin_role("admin") is True,
        "is_admin_role_true_dev": helpers.is_admin_role("developer") is True,
        "is_admin_role_false_user": helpers.is_admin_role("user") is False,
        "is_admin_role_false_none": helpers.is_admin_role(None) is False,
    }
    dbg.section("admin_role_protection", {
        "labels_user": labels_user,
        "labels_admin": labels_admin,
        "labels_dev": labels_dev,
        "labels_none": labels_none,
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("admin_helpers_failed", {"step": "admin_role_protection", "checks": checks})


def _test_user_status_render(dbg, helpers):
    class _StorageStub:
        def get_user_prefs(self, _user_id):
            return {}

        def get_all_alerts(self, _user_id):
            return {
                "alerts": [
                    {"id": "a1", "type": 1, "active": True},
                    {"id": "b1", "type": 6, "active": True},
                ],
                "tags": ["home"],
            }

        def get_user_meta(self, _user_id):
            return {
                "username": "target_user",
                "display_name": "Target User",
                "custom_name": "Tracked Target",
                "first_start": "2026-02-09T09:10:00",
                "last_seen": "2026-02-09T10:00:00",
            }

        def get_backup_prefs(self, _user_id):
            return {"email_enabled": False, "email_address": None, "last_email_sent": None}

        def get_user_role(self, _user_id):
            return "user"

    rendered = helpers.build_user_status(_StorageStub(), "123", viewer_role="developer")
    checks = {
        "has_truncation_line": "Current logs truncated" in rendered,
        "admin_scoped_json_rows_present": "(A)📄 **Data (.json):**" in rendered and "(A)📄 **Data (.json.bak):**" in rendered,
        "no_double_blank_after_truncation": "(D)\n(A)\n(A)👥" not in rendered,
    }
    dbg.section("user_status_render", {"rendered": rendered, "checks": checks})
    if not all(checks.values()):
        dbg.problem("admin_helpers_failed", {"step": "user_status_render", "checks": checks})


def run_checks(dbg, helpers):
    _test_markdown_escape(dbg, helpers)
    _test_requests_text_escape(dbg, helpers)
    _test_request_list_builder(dbg, helpers)
    _test_self_removal(dbg, helpers)
    _test_removal_text(dbg, helpers)
    _test_users_list_builder(dbg, helpers)
    _test_users_list_no_hard_cap(dbg, helpers)
    _test_invite_message_builder(dbg, helpers)
    _test_target_whitelist_guard(dbg, helpers)
    _test_admin_role_protection(dbg, helpers)
    _test_user_status_render(dbg, helpers)
