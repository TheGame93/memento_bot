#!/usr/bin/env python3
import os
import sys


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
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "callback_payload_debug"
FEATURE_TITLE = "Callback Payload Hardening"


def _test_callback_lengths(dbg, tags, api):
    token_map = api["build_value_token_map"](tags)
    checks = {}
    for token, tag in token_map.items():
        callbacks = {
            "alerts_filter": f"{api['FILTER_TOKEN_PREFIX']}{token}",
            "birthdays_filter": f"{api['BDAY_FILTER_TOKEN_PREFIX']}{token}",
            "tag_delete": f"{api['TAG_DELETE_CB_PREFIX']}{token}",
            "tag_confirm_delete": f"{api['TAG_CONFIRM_CB_PREFIX']}{token}",
        }
        for name, callback_data in callbacks.items():
            checks[f"{name}:{tag}"] = api["callback_bytes_len"](callback_data) <= api["MAX_CALLBACK_BYTES"]

    dbg.section("callback_lengths", {
        "checks": checks,
        "max_callback_bytes": api["MAX_CALLBACK_BYTES"],
    })
    if not all(checks.values()):
        dbg.problem("callback_length_failed", {"checks": checks})
    return token_map


def _test_roundtrip(dbg, tags, token_map, api):
    checks = {}
    for token, tag in token_map.items():
        list_callback = f"{api['FILTER_TOKEN_PREFIX']}{token}"
        bday_callback = f"{api['BDAY_FILTER_TOKEN_PREFIX']}{token}"
        checks[f"list:{tag}"] = api["decode_filter"](list_callback, token_map) == tag
        checks[f"birthday:{tag}"] = api["decode_bday_filter"](bday_callback, token_map) == tag
        checks[f"tag_delete:{tag}"] = api["extract_callback_token"](
            f"{api['TAG_DELETE_CB_PREFIX']}{token}",
            api["TAG_DELETE_CB_PREFIX"],
        ) == token
        checks[f"tag_confirm:{tag}"] = api["extract_callback_token"](
            f"{api['TAG_CONFIRM_CB_PREFIX']}{token}",
            api["TAG_CONFIRM_CB_PREFIX"],
        ) == token

    dbg.section("callback_roundtrip", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("callback_roundtrip_failed", {"checks": checks})


def _test_legacy_backcompat(dbg, tags, token_map, api):
    checks = {}
    for tag in tags:
        legacy_list = f"filter_{tag}"
        legacy_bday = f"bday_filter_{tag}"
        checks[f"legacy_list:{tag}"] = api["decode_filter"](legacy_list, token_map) == tag
        checks[f"legacy_bday:{tag}"] = api["decode_bday_filter"](legacy_bday, token_map) == tag
        legacy_tag_delete = f"manage_tag_do_del_{tag}"
        checks[f"legacy_tag_delete:{tag}"] = legacy_tag_delete.replace("manage_tag_do_del_", "", 1) == tag

    dbg.section("legacy_backcompat", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("callback_legacy_failed", {"checks": checks})


def _test_orphan_filter_callbacks(dbg, api):
    stale_candidate = f"{api['FILTER_TOKEN_PREFIX']}{'a' * 8}"
    stale_bday_candidate = f"{api['BDAY_FILTER_TOKEN_PREFIX']}{'a' * 8}"
    real_tag_named_orphan = "__ORPHAN__"
    real_tag_map = api["build_value_token_map"]([real_tag_named_orphan])
    real_tag_token = next(iter(real_tag_map.keys())) if real_tag_map else None
    real_tag_alerts_cb = (
        f"{api['FILTER_TOKEN_PREFIX']}{real_tag_token}" if real_tag_token else None
    )
    real_tag_bday_cb = (
        f"{api['BDAY_FILTER_TOKEN_PREFIX']}{real_tag_token}" if real_tag_token else None
    )
    checks = {
        "orphan_callback_fits_64": api["callback_bytes_len"](
            api["ORPHAN_FILTER_CALLBACK_DATA"]
        ) <= api["MAX_CALLBACK_BYTES"],
        "orphan_callback_decodes": api["decode_filter"](
            api["ORPHAN_FILTER_CALLBACK_DATA"],
            {},
        ) == api["ORPHAN_FILTER_VALUE"],
        "birthday_orphan_callback_fits_64": api["callback_bytes_len"](
            api["BDAY_ORPHAN_FILTER_CALLBACK_DATA"]
        ) <= api["MAX_CALLBACK_BYTES"],
        "birthday_orphan_callback_decodes": api["decode_bday_filter"](
            api["BDAY_ORPHAN_FILTER_CALLBACK_DATA"],
            {},
        ) == api["ORPHAN_FILTER_VALUE"],
        "stale_tokenized_filter_fails_closed": api["decode_filter"](
            stale_candidate,
            {},
        ) is None,
        "stale_tokenized_bday_filter_fails_closed": api["decode_bday_filter"](
            stale_bday_candidate,
            {},
        ) is None,
        "tokenized_real_orphan_name_list_decodes_real_tag": (
            isinstance(real_tag_alerts_cb, str)
            and api["decode_filter"](real_tag_alerts_cb, real_tag_map) == real_tag_named_orphan
            and api["decode_filter"](real_tag_alerts_cb, real_tag_map) != api["ORPHAN_FILTER_VALUE"]
        ),
        "tokenized_real_orphan_name_bday_decodes_real_tag": (
            isinstance(real_tag_bday_cb, str)
            and api["decode_bday_filter"](real_tag_bday_cb, real_tag_map) == real_tag_named_orphan
            and api["decode_bday_filter"](real_tag_bday_cb, real_tag_map) != api["ORPHAN_FILTER_VALUE"]
        ),
        "legacy_real_orphan_name_list_decodes_real_tag": (
            api["decode_filter"](f"filter_{real_tag_named_orphan}", {}) == real_tag_named_orphan
        ),
        "legacy_real_orphan_name_bday_decodes_real_tag": (
            api["decode_bday_filter"](f"bday_filter_{real_tag_named_orphan}", {}) == real_tag_named_orphan
        ),
    }
    dbg.section("orphan_filter_callbacks", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("orphan_filter_callbacks_failed", {"checks": checks})


def _test_untagged_filter_callbacks(dbg, api):
    real_tag_named_untagged = "__UNTAGGED__"
    real_tag_map = api["build_value_token_map"]([real_tag_named_untagged])
    real_tag_token = next(iter(real_tag_map.keys())) if real_tag_map else None
    real_tag_alerts_cb = (
        f"{api['FILTER_TOKEN_PREFIX']}{real_tag_token}" if real_tag_token else None
    )
    real_tag_bday_cb = (
        f"{api['BDAY_FILTER_TOKEN_PREFIX']}{real_tag_token}" if real_tag_token else None
    )
    checks = {
        "untagged_callback_fits_64": api["callback_bytes_len"](
            api["UNTAGGED_FILTER_CALLBACK_DATA"]
        ) <= api["MAX_CALLBACK_BYTES"],
        "untagged_callback_decodes": api["decode_filter"](
            api["UNTAGGED_FILTER_CALLBACK_DATA"],
            {},
        ) == api["UNTAGGED_FILTER_VALUE"],
        "birthday_untagged_callback_fits_64": api["callback_bytes_len"](
            api["BDAY_UNTAGGED_FILTER_CALLBACK_DATA"]
        ) <= api["MAX_CALLBACK_BYTES"],
        "birthday_untagged_callback_decodes": api["decode_bday_filter"](
            api["BDAY_UNTAGGED_FILTER_CALLBACK_DATA"],
            {},
        ) == api["BDAY_UNTAGGED_FILTER_VALUE"],
        "tokenized_real_untagged_name_list_decodes_real_tag": (
            isinstance(real_tag_alerts_cb, str)
            and api["decode_filter"](real_tag_alerts_cb, real_tag_map) == real_tag_named_untagged
            and api["decode_filter"](real_tag_alerts_cb, real_tag_map) != api["UNTAGGED_FILTER_VALUE"]
        ),
        "tokenized_real_untagged_name_bday_decodes_real_tag": (
            isinstance(real_tag_bday_cb, str)
            and api["decode_bday_filter"](real_tag_bday_cb, real_tag_map) == real_tag_named_untagged
            and api["decode_bday_filter"](real_tag_bday_cb, real_tag_map) != api["BDAY_UNTAGGED_FILTER_VALUE"]
        ),
        "legacy_real_untagged_name_list_decodes_real_tag": (
            api["decode_filter"](f"filter_{real_tag_named_untagged}", {}) == real_tag_named_untagged
        ),
        "legacy_real_untagged_name_bday_decodes_real_tag": (
            api["decode_bday_filter"](f"bday_filter_{real_tag_named_untagged}", {}) == real_tag_named_untagged
        ),
    }
    dbg.section("untagged_filter_callbacks", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("untagged_filter_callbacks_failed", {"checks": checks})


def _test_notif_back_callback(dbg, api):
    from datetime import datetime
    from modules.ui.keyboards.callbacks import build_notif_back_callback
    from modules import constants as C

    sample_id = "a1b2c3d4"
    orig = datetime(2025, 6, 1, 10, 0, 0)
    occ = datetime(2025, 6, 1, 8, 0, 0)

    checks = {}
    for kind in ("pre", "due"):
        for count in (0, 1, 99):
            cb = build_notif_back_callback(kind, sample_id, orig, occ, postpone_count=count)
            byte_len = api["callback_bytes_len"](cb)
            label = f"nback_{kind}_count{count}"
            checks[f"{label}_fits_64"] = byte_len <= api["MAX_CALLBACK_BYTES"]
            checks[f"{label}_starts_with_prefix"] = cb.startswith(C.CB_NOTIF_BACK)

    dbg.section("notif_back_callback", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("notif_back_callback_failed", {"checks": checks})


def _test_notification_callback_builders(dbg, api):
    from datetime import datetime
    from modules.ui.keyboards.callbacks import (
        build_alert_info_callback,
        build_notif_back_callback,
        build_postpone_callback,
        build_prealert_info_callback,
    )

    sample_id = "a1b2c3d4"
    orig = datetime(2025, 6, 1, 10, 0, 0)
    occ = datetime(2025, 6, 1, 8, 0, 0)
    callbacks = {
        "postpone": build_postpone_callback("menu", "due", sample_id, orig, occ, postpone_count=3),
        "prealert_info": build_prealert_info_callback(sample_id, orig, occ, postpone_count=3),
        "alert_info": build_alert_info_callback(sample_id, orig, occ, postpone_count=3),
        "notif_back": build_notif_back_callback("due", sample_id, orig, occ, postpone_count=3),
    }
    checks = {
        f"{name}_fits_64": api["callback_bytes_len"](callback_data) <= api["MAX_CALLBACK_BYTES"]
        for name, callback_data in callbacks.items()
    }

    dbg.section("notification_callback_builders", {"checks": checks, "callbacks": callbacks})
    if not all(checks.values()):
        dbg.problem("notification_callback_builders_failed", {"checks": checks, "callbacks": callbacks})


def _test_constants_cleanup(dbg):
    from modules import constants as C

    checks = {
        "notif_back_constant_present": hasattr(C, "CB_NOTIF_BACK"),
        "notif_back_constant_value": getattr(C, "CB_NOTIF_BACK", None) == "nback_",
        "alert_detail_show_debug_removed": not hasattr(C, "ALERT_DETAIL_SHOW_DEBUG"),
    }
    dbg.section("constants_cleanup", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("constants_cleanup_failed", {"checks": checks})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            from modules.handlers.birthdays import (
                BDAY_ORPHAN_FILTER_CALLBACK_DATA,
                BDAY_FILTER_TOKEN_PREFIX,
                _decode_birthday_filter_value,
            )
            from modules.handlers.birthday_flow.list_view import (
                BDAY_UNTAGGED_FILTER_CALLBACK_DATA,
                BDAY_UNTAGGED_FILTER_VALUE,
            )
            from modules.handlers.list_alerts import (
                FILTER_TOKEN_PREFIX,
                ORPHAN_FILTER_CALLBACK_DATA,
                ORPHAN_FILTER_VALUE,
                UNTAGGED_FILTER_CALLBACK_DATA,
                UNTAGGED_FILTER_VALUE,
                _decode_filter_value,
            )
            from modules.handlers.tags_dashboard import (
                TAG_CONFIRM_CB_PREFIX,
                TAG_DELETE_CB_PREFIX,
            )
            from modules.shared.callback_codec import (
                MAX_CALLBACK_BYTES,
                build_value_token_map,
                callback_bytes_len,
                extract_callback_token,
            )
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        api = {
            "BDAY_FILTER_TOKEN_PREFIX": BDAY_FILTER_TOKEN_PREFIX,
            "BDAY_ORPHAN_FILTER_CALLBACK_DATA": BDAY_ORPHAN_FILTER_CALLBACK_DATA,
            "BDAY_UNTAGGED_FILTER_CALLBACK_DATA": BDAY_UNTAGGED_FILTER_CALLBACK_DATA,
            "BDAY_UNTAGGED_FILTER_VALUE": BDAY_UNTAGGED_FILTER_VALUE,
            "FILTER_TOKEN_PREFIX": FILTER_TOKEN_PREFIX,
            "ORPHAN_FILTER_CALLBACK_DATA": ORPHAN_FILTER_CALLBACK_DATA,
            "ORPHAN_FILTER_VALUE": ORPHAN_FILTER_VALUE,
            "UNTAGGED_FILTER_CALLBACK_DATA": UNTAGGED_FILTER_CALLBACK_DATA,
            "UNTAGGED_FILTER_VALUE": UNTAGGED_FILTER_VALUE,
            "TAG_CONFIRM_CB_PREFIX": TAG_CONFIRM_CB_PREFIX,
            "TAG_DELETE_CB_PREFIX": TAG_DELETE_CB_PREFIX,
            "MAX_CALLBACK_BYTES": MAX_CALLBACK_BYTES,
            "build_value_token_map": build_value_token_map,
            "callback_bytes_len": callback_bytes_len,
            "extract_callback_token": extract_callback_token,
            "decode_filter": _decode_filter_value,
            "decode_bday_filter": _decode_birthday_filter_value,
        }
        tags = [
            "🏷️ Very Very Very Long Tag Name That Would Overflow Telegram Callback Payload If Used Directly",
            "📚 Another Extremely Long Tag Name With Spaces And Numbers 1234567890",
            "🧪 test",
            "task",
        ]
        token_map = _test_callback_lengths(dbg, tags, api)
        _test_roundtrip(dbg, tags, token_map, api)
        _test_legacy_backcompat(dbg, tags, token_map, api)
        _test_orphan_filter_callbacks(dbg, api)
        _test_untagged_filter_callbacks(dbg, api)
        _test_notif_back_callback(dbg, api)
        _test_notification_callback_builders(dbg, api)
        _test_constants_cleanup(dbg)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    length_ok = not dbg.has_problem("callback_length_failed")
    roundtrip_ok = not dbg.has_problem("callback_roundtrip_failed")
    legacy_ok = not dbg.has_problem("callback_legacy_failed")
    orphan_filter_ok = not dbg.has_problem("orphan_filter_callbacks_failed")
    untagged_filter_ok = not dbg.has_problem("untagged_filter_callbacks_failed")
    notif_back_ok = not dbg.has_problem("notif_back_callback_failed")
    notif_builders_ok = not dbg.has_problem("notification_callback_builders_failed")
    constants_ok = not dbg.has_problem("constants_cleanup_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception")
    dbg.finish(summary_lines=[
        f"length: {'OK' if length_ok else 'FAIL'}",
        f"roundtrip: {'OK' if roundtrip_ok else 'FAIL'}",
        f"legacy: {'OK' if legacy_ok else 'FAIL'}",
        f"orphan_filter: {'OK' if orphan_filter_ok else 'FAIL'}",
        f"untagged_filter: {'OK' if untagged_filter_ok else 'FAIL'}",
        f"notif_back: {'OK' if notif_back_ok else 'FAIL'}",
        f"notif_builders: {'OK' if notif_builders_ok else 'FAIL'}",
        f"constants: {'OK' if constants_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
    ])


if __name__ == "__main__":
    main()
