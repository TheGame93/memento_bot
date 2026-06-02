#!/usr/bin/env python3
import asyncio
import json
import os
import sys
import tempfile


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
SCRIPT_TITLE = "media_path_policy_debug"
FEATURE_TITLE = "Media Path Policy"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _load_storage_manager():
    try:
        from modules.storage import StorageManager
        return StorageManager, None
    except ModuleNotFoundError as exc:
        return None, exc


def _touch_file(path, content=b"img"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)


def _build_seed_payload(paths):
    return {
        "tags": [],
        "alerts": [
            {"id": "inside_abs", "local_image_path": paths["inside_messy"]},
            {"id": "outside_rebind", "local_image_path": paths["outside_match_abs"]},
            {"id": "outside_clear", "local_image_path": paths["outside_missing_abs"]},
            {"id": "traversal_clear", "local_image_path": "../secrets.jpg"},
            {"id": "relative_convert", "local_image_path": "images/inside.jpg"},
            {"id": "windows_rebind", "local_image_path": r"C:\tmp\local_match.jpg"},
            {"id": "non_images_relative_clear", "local_image_path": "logs/events.log"},
        ],
        "postpone_queue": [],
    }


def _test_media_path_normalization(dbg, StorageManager):
    with tempfile.TemporaryDirectory(prefix="media_path_policy_") as tmp_root:
        storage = StorageManager(base_data_dir=tmp_root, admin_id="1")
        user_id = 1
        user_dir = storage.setup_user_space(user_id)
        images_dir = os.path.join(user_dir, "images")

        inside_abs = os.path.join(images_dir, "inside.jpg")
        local_match_abs = os.path.join(images_dir, "local_match.jpg")
        _touch_file(inside_abs)
        _touch_file(local_match_abs)

        outside_root = os.path.join(tmp_root, "outside_world")
        outside_match_abs = os.path.join(outside_root, "local_match.jpg")
        outside_missing_abs = os.path.join(outside_root, "ghost.jpg")
        _touch_file(outside_match_abs)

        inside_messy = os.path.join(images_dir, "..", "images", "inside.jpg")
        paths = {
            "inside_abs": os.path.realpath(inside_abs),
            "inside_messy": inside_messy,
            "local_match_abs": os.path.realpath(local_match_abs),
            "outside_match_abs": outside_match_abs,
            "outside_missing_abs": outside_missing_abs,
        }

        payload = _build_seed_payload(paths)

        stats_payload = json.loads(json.dumps(payload))
        media_changed, media_stats = storage._normalize_alert_media_paths(user_id, stats_payload)  # noqa: SLF001

        normalized, changed = storage._normalize_alerts_payload(payload, user_id=user_id)  # noqa: SLF001
        alerts = normalized.get("alerts", [])
        local_map = {item.get("id"): item.get("local_image_path") for item in alerts if isinstance(item, dict)}

        checks = {
            "media_changed": media_changed is True,
            "payload_changed": changed is True,
            "stats_converted_inside": media_stats.get("converted_inside") == 1,
            "stats_rebound_by_basename": media_stats.get("rebound_by_basename") == 2,
            "stats_cleared_invalid": media_stats.get("cleared_invalid") == 3,
            "stats_already_ok": media_stats.get("already_ok") == 1,
            "inside_abs_kept_in_user_images": local_map.get("inside_abs") == "images/inside.jpg",
            "outside_path_rebound_to_user_images": local_map.get("outside_rebind") == "images/local_match.jpg",
            "outside_missing_cleared": local_map.get("outside_clear") is None,
            "traversal_cleared": local_map.get("traversal_clear") is None,
            "relative_images_path_canonicalized": local_map.get("relative_convert") == "images/inside.jpg",
            "windows_style_path_rebound": local_map.get("windows_rebind") == "images/local_match.jpg",
            "non_images_relative_cleared": local_map.get("non_images_relative_clear") is None,
            "resolver_returns_valid_inside": (
                storage.resolve_local_image_path(user_id, paths["inside_abs"], require_exists=True) == paths["inside_abs"]
            ),
            "resolver_blocks_outside": (
                storage.resolve_local_image_path(user_id, outside_match_abs, require_exists=False) is None
            ),
        }

        retained = [
            local_map.get("inside_abs"),
            local_map.get("outside_rebind"),
            local_map.get("relative_convert"),
            local_map.get("windows_rebind"),
        ]
        retained = [p for p in retained if isinstance(p, str) and p]
        checks["retained_paths_are_relative_images"] = all(
            p.startswith("images/") and "/../" not in p for p in retained
        )
        resolved_retained = [
            storage.resolve_local_image_path(user_id, p, require_exists=False) for p in retained
        ]
        checks["retained_paths_resolve_within_user_images"] = all(
            isinstance(p, str) and storage._is_within_dir(images_dir, p) for p in resolved_retained  # noqa: SLF001
        )

        dbg.section("media_path_policy", {
            "checks": checks,
            "stats": media_stats,
            "retained_paths": retained,
            "resolved_retained_paths": resolved_retained,
        })
        if not all(checks.values()):
            dbg.problem("media_path_policy_failed", {
                "checks": checks,
                "stats": media_stats,
                "retained_paths": retained,
                "resolved_retained_paths": resolved_retained,
            })


async def _test_download_image_storage_path(dbg, StorageManager):
    with tempfile.TemporaryDirectory(prefix="media_download_policy_") as tmp_root:
        storage = StorageManager(base_data_dir=tmp_root, admin_id="1")
        user_id = 1
        storage.setup_user_space(user_id)

        class FakeFile:
            file_path = "photos/fallback.png"

            async def download_to_drive(self, target):
                _touch_file(target, b"img")

        class FakeBot:
            async def get_file(self, _file_id):
                return FakeFile()

        rel_path = await storage.download_image(FakeBot(), user_id, "file_abc_123")
        resolved = storage.resolve_local_image_path(user_id, rel_path, require_exists=True)
        checks = {
            "download_returns_relative": isinstance(rel_path, str) and rel_path.startswith("images/"),
            "download_rel_uses_ext": isinstance(rel_path, str) and rel_path.endswith(".png"),
            "download_relative_resolves": isinstance(resolved, str) and os.path.isfile(resolved),
        }
        dbg.section("download_image_storage_path", {
            "checks": checks,
            "rel_path": rel_path,
            "resolved": resolved,
        })
        if not all(checks.values()):
            dbg.problem("download_image_storage_path_failed", {
                "checks": checks,
                "rel_path": rel_path,
                "resolved": resolved,
            })


def _test_save_alert_storage_path(dbg, StorageManager):
    with tempfile.TemporaryDirectory(prefix="media_save_policy_") as tmp_root:
        storage = StorageManager(base_data_dir=tmp_root, admin_id="1")
        user_id = 1
        user_dir = storage.setup_user_space(user_id)
        images_dir = os.path.join(user_dir, "images")
        img_name = "saved_img.jpg"
        img_abs = os.path.join(images_dir, img_name)
        _touch_file(img_abs)

        save_payload = {
            "title": "Media Save",
            "type": 5,
            "type_name": "One Time",
            "schedule": {"date": "01/01/2099", "time": "10:00"},
            "pre_alerts": [],
            "tags": [],
            "local_image_path": os.path.join(images_dir, "..", "images", img_name),
        }
        saved_id = storage.save_alert(user_id, save_payload)
        saved_alert = storage.get_alert_by_id(user_id, saved_id) if saved_id else None

        outside = os.path.join(tmp_root, "foreign", img_name)
        _touch_file(outside)
        rebound_payload = {
            "title": "Media Rebind",
            "type": 5,
            "type_name": "One Time",
            "schedule": {"date": "02/01/2099", "time": "10:00"},
            "pre_alerts": [],
            "tags": [],
            "local_image_path": outside,
        }
        rebound_id = storage.save_alert(user_id, rebound_payload)
        rebound_alert = storage.get_alert_by_id(user_id, rebound_id) if rebound_id else None

        checks = {
            "saved_alert_exists": isinstance(saved_alert, dict),
            "saved_alert_relative_path": isinstance(saved_alert, dict) and saved_alert.get("local_image_path") == f"images/{img_name}",
            "rebound_alert_exists": isinstance(rebound_alert, dict),
            "rebound_alert_relative_path": isinstance(rebound_alert, dict) and rebound_alert.get("local_image_path") == f"images/{img_name}",
        }
        dbg.section("save_alert_storage_path", {
            "checks": checks,
            "saved_alert": saved_alert,
            "rebound_alert": rebound_alert,
        })
        if not all(checks.values()):
            dbg.problem("save_alert_storage_path_failed", {
                "checks": checks,
                "saved_alert": saved_alert,
                "rebound_alert": rebound_alert,
            })


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})
        StorageManager, import_error = _load_storage_manager()
        if import_error is not None:
            dbg.mark_dependency_error(import_error)
            dbg.finish(exit_on_problems=False)
            return

        _test_media_path_normalization(dbg, StorageManager)
        _test_save_alert_storage_path(dbg, StorageManager)
        asyncio.run(_test_download_image_storage_path(dbg, StorageManager))
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    policy_ok = not dbg.has_problem(
        "media_path_policy_failed",
        "save_alert_storage_path_failed",
        "download_image_storage_path_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"policy: {'OK' if policy_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
