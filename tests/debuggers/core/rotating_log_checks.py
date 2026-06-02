import glob
import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta


def _read_json_lines(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as file_obj:
        for raw in file_obj:
            line = raw.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _reset_cache(sl):
    sl.clear_logger_cache()
    sl._last_prune_mono = 0.0
    sl._last_wall_dt = None
    sl._last_mono_ts = None
    sl._clock_event_in_progress = False


def _reset_log_dir(sl):
    _reset_cache(sl)
    if os.path.isdir(sl.LOG_DIR):
        shutil.rmtree(sl.LOG_DIR)
    os.makedirs(sl.LOG_DIR, exist_ok=True)


def _append_with_rollover_wait(sl, path, record, timeout_seconds=5.0):
    rotated_before = set(glob.glob(path + ".*"))
    sl.append_json_log(path, record)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        rotated_after = set(glob.glob(path + ".*"))
        if rotated_after - rotated_before:
            return True
        time.sleep(0.1)
    return False


def run_checks(dbg, sl):
    expected_policy = {
        "system.log": 90,
        "errors.log": 180,
        "scheduler.log": 60,
        "api.log": 30,
        "lifecycle.log": 90,
        "storage.log": 90,
        "admin_audit.log": 180,
        "onboarding.log": 90,
    }
    retention_map = dict(sl.LOG_RETENTION_DAYS)
    missing_or_mismatch = {
        key: {"expected": days, "actual": retention_map.get(key)}
        for key, days in expected_policy.items()
        if retention_map.get(key) != days
    }
    policy_ok = (
        sl.ROTATION_WHEN == "midnight"
        and sl.DEFAULT_LOG_RETENTION_DAYS == 90
        and sl.USER_LOG_RETENTION_DAYS == 90
        and not missing_or_mismatch
    )
    if not policy_ok:
        dbg.problem("rotation_policy_mismatch", {
            "when": sl.ROTATION_WHEN,
            "default_days": sl.DEFAULT_LOG_RETENTION_DAYS,
            "user_days": sl.USER_LOG_RETENTION_DAYS,
            "retention_map": retention_map,
            "missing_or_mismatch": missing_or_mismatch,
        })
    if sl.LOG_SIZE_LIMIT_BYTES != 10 * 1024 * 1024 * 1024:
        dbg.problem("size_policy_mismatch", {
            "limit": sl.LOG_SIZE_LIMIT_BYTES,
        })
    dbg.section("policy", {
        "when": sl.ROTATION_WHEN,
        "default_days": sl.DEFAULT_LOG_RETENTION_DAYS,
        "user_days": sl.USER_LOG_RETENTION_DAYS,
        "retention_map": sl.LOG_RETENTION_DAYS,
        "size_limit_bytes": sl.LOG_SIZE_LIMIT_BYTES,
    })

    with tempfile.TemporaryDirectory() as tmpdir:
        cwd_old = os.getcwd()
        os.chdir(tmpdir)
        try:
            sl.DATA_DIR = os.path.join(tmpdir, "sandbox")
            sl.USER_LOG_DIR = os.path.join(sl.DATA_DIR, "userlog.d")
            sl.LOG_DIR = os.path.join("data", "systemlog.d")
            sl.SUMMARY_LOG = os.path.join(sl.LOG_DIR, "system.log")
            sl.RUNTIME_STATE_FILE = os.path.join(sl.LOG_DIR, "runtime_state.json")
            _reset_cache(sl)

            _reset_log_dir(sl)
            sl.ROTATION_WHEN = "S"
            sl.ROTATION_INTERVAL = 1
            sl.DEFAULT_LOG_RETENTION_DAYS = 3

            path = os.path.join(sl.LOG_DIR, "rotation_test.log")
            sl.append_json_log(path, {"ts": datetime.now().isoformat(), "event": "a"})
            time.sleep(1.1)
            rolled = _append_with_rollover_wait(sl, path, {"ts": datetime.now().isoformat(), "event": "b"})
            time.sleep(1.1)
            sl.append_json_log(path, {"ts": datetime.now().isoformat(), "event": "c"})

            rotated = sorted(glob.glob(path + ".*"))
            dbg.section("rotation_files", {
                "active": path,
                "rotated_count": len(rotated),
                "rotated_files": rotated,
            })
            if not rotated or not rolled:
                dbg.problem("rotation_missing", {"path": path, "rotated_files": rotated, "rolled": rolled})

            for log_path in [path] + rotated:
                try:
                    _ = _read_json_lines(log_path)
                except Exception as exc:
                    dbg.problem("json_parse_failed", {"file": log_path, "error": str(exc)})

            _reset_cache(sl)
            _reset_log_dir(sl)
            sl.ROTATION_WHEN = "S"
            sl.ROTATION_INTERVAL = 1
            sl.DEFAULT_LOG_RETENTION_DAYS = 2
            path2 = os.path.join(sl.LOG_DIR, "retention_test.log")
            for index in range(5):
                sl.append_json_log(path2, {
                    "ts": datetime.now().isoformat(),
                    "event": f"ret_{index}",
                })
                time.sleep(1.1)
            rotated2 = sorted(glob.glob(path2 + ".*"))
            dbg.section("retention_files", {
                "rotated_count": len(rotated2),
                "files": rotated2,
            })
            if len(rotated2) > 2:
                dbg.problem("retention_failed", {
                    "expected_max": 2,
                    "actual": len(rotated2),
                })

            sl.DEFAULT_LOG_RETENTION_DAYS = 11
            sl.USER_LOG_RETENTION_DAYS = 5
            new_user_log = os.path.join(sl.USER_LOG_DIR, "42_events.log")
            legacy_user_log = os.path.join(sl.DATA_DIR, "42", "logs", "events.log")
            detected_retention_new = sl.get_retention_days_for_path(new_user_log)
            detected_retention_legacy = sl.get_retention_days_for_path(legacy_user_log)
            dbg.section("retention_detection", {
                "new_path": new_user_log,
                "new_detected_days": detected_retention_new,
                "legacy_path": legacy_user_log,
                "legacy_detected_days": detected_retention_legacy,
                "expected_days": sl.USER_LOG_RETENTION_DAYS,
            })
            if (
                detected_retention_new != sl.USER_LOG_RETENTION_DAYS
                or detected_retention_legacy != sl.USER_LOG_RETENTION_DAYS
            ):
                dbg.problem("user_retention_detection_failed", {
                    "new_path": new_user_log,
                    "new_detected": detected_retention_new,
                    "legacy_path": legacy_user_log,
                    "legacy_detected": detected_retention_legacy,
                    "expected": sl.USER_LOG_RETENTION_DAYS,
                })

            _reset_cache(sl)
            sl.LOGGER_CACHE_MAX_ENTRIES = 2
            cache_paths = [
                os.path.join(sl.LOG_DIR, "cache_a.log"),
                os.path.join(sl.LOG_DIR, "cache_b.log"),
                os.path.join(sl.LOG_DIR, "cache_c.log"),
            ]
            for index, cache_path in enumerate(cache_paths, start=1):
                sl.append_json_log(cache_path, {
                    "ts": datetime.now().isoformat(),
                    "event": f"cache_{index}",
                })
            first_abs = os.path.abspath(cache_paths[0])
            cache_keys = list(sl._logger_cache.keys())
            dbg.section("cache_eviction", {
                "cache_size": len(cache_keys),
                "max_entries": sl.LOGGER_CACHE_MAX_ENTRIES,
                "keys": cache_keys,
            })
            if len(cache_keys) > sl.LOGGER_CACHE_MAX_ENTRIES or first_abs in sl._logger_cache:
                dbg.problem("logger_cache_eviction_failed", {
                    "cache_size": len(cache_keys),
                    "max_entries": sl.LOGGER_CACHE_MAX_ENTRIES,
                    "first_present": first_abs in sl._logger_cache,
                })

            _reset_log_dir(sl)
            sl.log_system("../escape", "sanitize_test", {"raw": True})
            safe_path = os.path.join(sl.LOG_DIR, "escape.log")
            safe_rows = _read_json_lines(safe_path)
            safe_ok = bool(safe_rows) and safe_rows[-1].get("category") == "escape"
            identity = safe_rows[-1].get("identity") if safe_rows else {}
            identity_checks = {
                "identity_present": isinstance(identity, dict),
                "instance_tag_present": isinstance(identity.get("instance_tag"), str) and bool(identity.get("instance_tag")),
                "project_hash_present": isinstance(identity.get("project_root_hash"), str) and bool(identity.get("project_root_hash")),
                "data_hash_present": isinstance(identity.get("data_dir_hash"), str) and bool(identity.get("data_dir_hash")),
            }
            dbg.section("category_sanitize", {
                "safe_path": safe_path,
                "rows": len(safe_rows),
                "safe_ok": safe_ok,
                "identity_checks": identity_checks,
            })
            if not safe_ok:
                dbg.problem("category_sanitize_failed", {"safe_path": safe_path})
            if not all(identity_checks.values()):
                dbg.problem("identity_tag_missing", {
                    "safe_path": safe_path,
                    "identity": identity,
                    "checks": identity_checks,
                })

            _reset_log_dir(sl)
            sl.LOG_SIZE_LIMIT_BYTES = 1500
            keep_current = os.path.join(sl.LOG_DIR, "cap_test.log")
            old1 = keep_current + ".2024-01-01"
            old2 = keep_current + ".2024-01-02"
            os.makedirs(sl.LOG_DIR, exist_ok=True)
            with open(keep_current, "w", encoding="utf-8") as file_obj:
                file_obj.write("x" * 700)
            with open(old1, "w", encoding="utf-8") as file_obj:
                file_obj.write("x" * 900)
            with open(old2, "w", encoding="utf-8") as file_obj:
                file_obj.write("x" * 900)

            sl._enforce_log_size_limit(force=True)

            files_after = sorted(glob.glob(os.path.join(sl.LOG_DIR, "cap_test.log*")))
            total_after = sum(os.path.getsize(path) for path in files_after if os.path.exists(path))
            dbg.section("size_cap_after_prune", {
                "files": files_after,
                "total_bytes": total_after,
                "limit": sl.LOG_SIZE_LIMIT_BYTES,
            })
            if total_after > sl.LOG_SIZE_LIMIT_BYTES:
                dbg.problem("size_cap_failed", {
                    "total": total_after,
                    "limit": sl.LOG_SIZE_LIMIT_BYTES,
                })

            metrics = sl.get_log_maintenance_metrics()
            checks = {
                "has_last_run": bool(metrics.get("last_run_ts")),
                "result_expected": metrics.get("last_result") in {
                    "within_limit",
                    "pruned_or_truncated",
                    "cap_exceeded_after_prune",
                },
                "freed_non_zero": int(metrics.get("last_freed_bytes", 0)) > 0,
                "deleted_or_truncated": (
                    int(metrics.get("last_deleted_rotated", 0)) > 0
                    or int(metrics.get("last_truncated_current", 0)) > 0
                ),
                "totals_increase": int(metrics.get("total_runs", 0)) >= 1,
            }
            dbg.section("size_cap_metrics", {
                "checks": checks,
                "metrics": metrics,
            })
            if not all(checks.values()):
                dbg.problem("maintenance_metrics_failed", {
                    "checks": checks,
                    "metrics": metrics,
                })

            state = {
                "last_startup_ts": (datetime.now() - timedelta(minutes=5)).isoformat(),
                "last_shutdown_ts": (datetime.now() - timedelta(minutes=2)).isoformat(),
                "last_exit": "clean",
                "last_pid": 12345,
            }
            with open(sl.RUNTIME_STATE_FILE, "w", encoding="utf-8") as file_obj:
                json.dump(state, file_obj)

            sl.log_downtime_summary()
            lifecycle_path = os.path.join(sl.LOG_DIR, "lifecycle.log")
            lifecycle_rows = _read_json_lines(lifecycle_path)
            if not any(row.get("event") == "downtime_summary" for row in lifecycle_rows):
                dbg.problem("downtime_summary_failed", {})
            else:
                last_downtime = [row for row in lifecycle_rows if row.get("event") == "downtime_summary"][-1]
                payload = last_downtime.get("payload") or {}
                identity_fields = {
                    "instance_tag_current": payload.get("instance_tag_current"),
                    "instance_tag_state": payload.get("instance_tag_state"),
                    "identity_match": payload.get("identity_match"),
                }
                checks = {
                    "instance_tag_current_present": isinstance(identity_fields["instance_tag_current"], str) and bool(identity_fields["instance_tag_current"]),
                    "identity_match_key_present": "identity_match" in payload,
                }
                dbg.section("downtime_identity_fields", {
                    "checks": checks,
                    "fields": identity_fields,
                })
                if not all(checks.values()):
                    dbg.problem("downtime_identity_fields_missing", {
                        "checks": checks,
                        "fields": identity_fields,
                    })

            _reset_cache(sl)
            sl._last_wall_dt = datetime.now() - timedelta(minutes=10)
            sl._last_mono_ts = time.monotonic()
            sl.log_system("system", "clock_test", {})
            lifecycle_rows = _read_json_lines(lifecycle_path)
            if not any(row.get("event") == "clock_jump_detected" for row in lifecycle_rows):
                dbg.problem("clock_jump_not_logged", {})
        finally:
            os.chdir(cwd_old)
