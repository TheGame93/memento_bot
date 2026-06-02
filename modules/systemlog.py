import glob
import hashlib
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler

from modules.shared.paths import DATA_DIR, PROJECT_ROOT, SYSTEM_LOG_DIR, USER_LOG_DIR

LOG_DIR = SYSTEM_LOG_DIR
SUMMARY_LOG = os.path.join(LOG_DIR, "system.log")
RUNTIME_STATE_FILE = os.path.join(LOG_DIR, "runtime_state.json")

# Rotation / retention policy
DEFAULT_LOG_RETENTION_DAYS = 90
USER_LOG_RETENTION_DAYS = 90
LOG_RETENTION_DAYS = {
    "system.log": 90,
    "errors.log": 180,
    "scheduler.log": 60,
    "api.log": 30,
    "lifecycle.log": 90,
    "storage.log": 90,
    "admin_audit.log": 180,
    "onboarding.log": 90,
}
ROTATION_BACKUP_COUNT = DEFAULT_LOG_RETENTION_DAYS
ROTATION_WHEN = "midnight"
ROTATION_INTERVAL = 1

# Global cap across all current+rotated logs (system + users)
LOG_SIZE_LIMIT_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB
PRUNE_MIN_INTERVAL_SECONDS = 60
LOGGER_CACHE_MAX_ENTRIES = 2048

# Detect major clock jumps (manual clock change/NTP issue)
CLOCK_JUMP_THRESHOLD_SECONDS = 120

_fallback_logger = logging.getLogger(__name__)
_logger_cache = OrderedDict()
_cache_lock = threading.Lock()
_prune_lock = threading.Lock()
_last_prune_mono = 0.0

_clock_lock = threading.Lock()
_last_wall_dt = None
_last_mono_ts = None
_clock_event_in_progress = False

IDENTITY_HASH_LEN = 12


def _default_log_maintenance_metrics():
    return {
        "last_run_ts": None,
        "last_result": "never",
        "last_limit_bytes": _coerce_non_negative_int(LOG_SIZE_LIMIT_BYTES, 0),
        "last_before_bytes": 0,
        "last_after_bytes": 0,
        "last_freed_bytes": 0,
        "last_deleted_rotated": 0,
        "last_truncated_current": 0,
        "total_runs": 0,
        "total_deleted_rotated": 0,
        "total_truncated_current": 0,
        "total_freed_bytes": 0,
    }


def _normalize_log_maintenance_metrics(raw):
    defaults = _default_log_maintenance_metrics()
    if not isinstance(raw, dict):
        return defaults

    metrics = dict(defaults)
    for key in ("last_run_ts", "last_result"):
        value = raw.get(key)
        if isinstance(value, str) and value:
            metrics[key] = value

    numeric_fields = [
        "last_limit_bytes",
        "last_before_bytes",
        "last_after_bytes",
        "last_freed_bytes",
        "last_deleted_rotated",
        "last_truncated_current",
        "total_runs",
        "total_deleted_rotated",
        "total_truncated_current",
        "total_freed_bytes",
    ]
    for key in numeric_fields:
        metrics[key] = _coerce_non_negative_int(raw.get(key), defaults[key])
    return metrics


def _persist_log_maintenance_metrics(
    *,
    before_bytes,
    after_bytes,
    deleted_rotated,
    truncated_current,
    result,
):
    with _runtime_state_lock:
        _persist_log_maintenance_metrics_locked(
            before_bytes=before_bytes,
            after_bytes=after_bytes,
            deleted_rotated=deleted_rotated,
            truncated_current=truncated_current,
            result=result,
        )


def _persist_log_maintenance_metrics_locked(
    *,
    before_bytes,
    after_bytes,
    deleted_rotated,
    truncated_current,
    result,
):
    state = _read_runtime_state()
    metrics = _normalize_log_maintenance_metrics(state.get("log_maintenance"))

    before_bytes = _coerce_non_negative_int(before_bytes, 0)
    after_bytes = _coerce_non_negative_int(after_bytes, 0)
    deleted_rotated = _coerce_non_negative_int(deleted_rotated, 0)
    truncated_current = _coerce_non_negative_int(truncated_current, 0)
    freed_bytes = max(0, before_bytes - after_bytes)

    metrics["last_run_ts"] = datetime.now().isoformat()
    metrics["last_result"] = str(result or "unknown")
    metrics["last_limit_bytes"] = _coerce_non_negative_int(LOG_SIZE_LIMIT_BYTES, 0)
    metrics["last_before_bytes"] = before_bytes
    metrics["last_after_bytes"] = after_bytes
    metrics["last_freed_bytes"] = freed_bytes
    metrics["last_deleted_rotated"] = deleted_rotated
    metrics["last_truncated_current"] = truncated_current

    metrics["total_runs"] = _coerce_non_negative_int(metrics.get("total_runs"), 0) + 1
    metrics["total_deleted_rotated"] = (
        _coerce_non_negative_int(metrics.get("total_deleted_rotated"), 0) + deleted_rotated
    )
    metrics["total_truncated_current"] = (
        _coerce_non_negative_int(metrics.get("total_truncated_current"), 0) + truncated_current
    )
    metrics["total_freed_bytes"] = (
        _coerce_non_negative_int(metrics.get("total_freed_bytes"), 0) + freed_bytes
    )

    state["log_maintenance"] = metrics
    _write_runtime_state(state)


def get_log_maintenance_metrics():
    """Return normalized runtime metrics for log-maintenance housekeeping."""
    state = _read_runtime_state()
    metrics = _normalize_log_maintenance_metrics(state.get("log_maintenance"))
    metrics["last_limit_bytes"] = _coerce_non_negative_int(LOG_SIZE_LIMIT_BYTES, metrics["last_limit_bytes"])
    return metrics


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def _json_line(record):
    return json.dumps(record, ensure_ascii=False, default=str)


def _coerce_non_negative_int(value, default):
    try:
        parsed = int(value)
    except Exception:
        return int(default)
    if parsed < 0:
        return int(default)
    return parsed


def _get_retention_days_for_path(path):
    base = os.path.basename(path)
    if base in LOG_RETENTION_DAYS:
        return _coerce_non_negative_int(LOG_RETENTION_DAYS[base], DEFAULT_LOG_RETENTION_DAYS)

    normalized = os.path.normpath(path)
    user_log_dir_norm = os.path.normpath(USER_LOG_DIR)
    try:
        common = os.path.commonpath([os.path.abspath(normalized), os.path.abspath(user_log_dir_norm)])
    except Exception:
        common = None
    if common == os.path.abspath(user_log_dir_norm):
        return _coerce_non_negative_int(USER_LOG_RETENTION_DAYS, DEFAULT_LOG_RETENTION_DAYS)

    if os.path.basename(os.path.dirname(normalized)) == "logs":
        return _coerce_non_negative_int(USER_LOG_RETENTION_DAYS, DEFAULT_LOG_RETENTION_DAYS)

    try:
        rel = os.path.relpath(normalized, os.path.normpath(DATA_DIR))
        parts = rel.split(os.sep)
    except Exception:
        parts = []

    if len(parts) >= 3 and parts[1] == "logs":
        return _coerce_non_negative_int(USER_LOG_RETENTION_DAYS, DEFAULT_LOG_RETENTION_DAYS)

    return _coerce_non_negative_int(DEFAULT_LOG_RETENTION_DAYS, 90)


def get_retention_days_for_path(path):
    """Resolve effective retention days for a log file path."""
    return _get_retention_days_for_path(path)


def _sanitize_log_component(value, fallback):
    text = str(value or "").strip()
    if not text:
        return fallback
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("._-")
    if not text:
        return fallback
    return text[:64]


def _close_logger_handlers(logger):
    handlers = list(getattr(logger, "handlers", []) or [])
    for handler in handlers:
        try:
            logger.removeHandler(handler)
        except Exception:
            pass
        try:
            handler.close()
        except Exception:
            pass
    try:
        logger._jsonlog_configured = False
    except Exception:
        pass


def _evict_logger_cache_if_needed_locked(exclude_path=None):
    max_entries = _coerce_non_negative_int(LOGGER_CACHE_MAX_ENTRIES, 2048)
    if max_entries <= 0:
        max_entries = 1

    while len(_logger_cache) > max_entries:
        victim_path = None
        for candidate_path in _logger_cache.keys():
            if candidate_path == exclude_path and len(_logger_cache) > 1:
                continue
            victim_path = candidate_path
            break
        if victim_path is None:
            break
        victim_logger = _logger_cache.pop(victim_path, None)
        if victim_logger is not None:
            _close_logger_handlers(victim_logger)


def clear_logger_cache(close_handlers=True):
    """Clear cached JSON loggers and optionally close their handlers."""
    with _cache_lock:
        if close_handlers:
            for logger in list(_logger_cache.values()):
                _close_logger_handlers(logger)
        _logger_cache.clear()


def _get_logger_for_path(path):
    abs_path = os.path.abspath(path)
    with _cache_lock:
        logger = _logger_cache.get(abs_path)
        if logger:
            _logger_cache.move_to_end(abs_path)
            return logger

        _ensure_dir(os.path.dirname(abs_path))
        logger_name = f"jsonlog::{abs_path}"
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.INFO)
        logger.propagate = False

        if not getattr(logger, "_jsonlog_configured", False) or not logger.handlers:
            _close_logger_handlers(logger)
            backup_count = _get_retention_days_for_path(abs_path)
            handler = TimedRotatingFileHandler(
                abs_path,
                when=ROTATION_WHEN,
                interval=ROTATION_INTERVAL,
                backupCount=backup_count,
                encoding="utf-8",
                delay=True,
            )
            # Compression is intentionally disabled for now, but TimedRotatingFileHandler
            # keeps this architecture compatible with future namer/rotator hooks.
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
            logger._jsonlog_configured = True

        _logger_cache[abs_path] = logger
        _logger_cache.move_to_end(abs_path)
        _evict_logger_cache_if_needed_locked(exclude_path=abs_path)
        return logger


def _parse_iso(ts):
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is not None:
            return dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _short_sha256(value, length=IDENTITY_HASH_LEN):
    digest = hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
    return digest[: max(1, int(length))]


def _runtime_identity_payload():
    project_root_abs = os.path.abspath(PROJECT_ROOT)
    data_dir_abs = os.path.abspath(DATA_DIR)
    return {
        "instance_tag": _short_sha256(f"{project_root_abs}|{data_dir_abs}"),
        "project_root_hash": _short_sha256(project_root_abs),
        "data_dir_hash": _short_sha256(data_dir_abs),
        "project_root_name": os.path.basename(project_root_abs) or project_root_abs,
        "data_dir_name": os.path.basename(data_dir_abs) or data_dir_abs,
    }


def _normalize_runtime_identity(raw):
    if not isinstance(raw, dict):
        return None
    instance_tag = raw.get("instance_tag")
    project_root_hash = raw.get("project_root_hash")
    data_dir_hash = raw.get("data_dir_hash")
    if not all(isinstance(value, str) and value for value in (instance_tag, project_root_hash, data_dir_hash)):
        return None
    return {
        "instance_tag": instance_tag,
        "project_root_hash": project_root_hash,
        "data_dir_hash": data_dir_hash,
        "project_root_name": raw.get("project_root_name"),
        "data_dir_name": raw.get("data_dir_name"),
    }


def _coerce_positive_pid(value):
    try:
        parsed = int(value)
    except Exception:
        return None
    if parsed <= 0:
        return None
    return parsed


def _pid_is_alive(pid):
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _window_result(
    *,
    window_start,
    window_end,
    source,
    is_reliable,
    reason_code,
    current_identity,
    state_identity,
    last_pid_alive,
):
    return {
        "window_start": window_start,
        "window_end": window_end,
        "source": source,
        "is_reliable": bool(is_reliable),
        "reason_code": reason_code,
        "instance_tag_current": current_identity.get("instance_tag"),
        "instance_tag_state": state_identity.get("instance_tag") if isinstance(state_identity, dict) else None,
        "identity_match": (
            current_identity.get("instance_tag") == state_identity.get("instance_tag")
            if isinstance(state_identity, dict)
            else None
        ),
        "last_pid_alive": bool(last_pid_alive),
    }


def _as_server_naive_datetime(value):
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone().replace(tzinfo=None)
        return value
    return datetime.now()


def _read_runtime_state():
    try:
        with open(RUNTIME_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return {}


def _write_runtime_state(state):
    try:
        _ensure_dir(LOG_DIR)
        tmp_path = f"{RUNTIME_STATE_FILE}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state or {}, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp_path, RUNTIME_STATE_FILE)
        return True
    except Exception as e:
        _fallback_logger.error(f"runtime_state_write_failed: {e}")
        return False


_runtime_state_lock = threading.Lock()


def update_runtime_state_key(key, value):
    """Atomically update a single key in runtime_state.json."""
    with _runtime_state_lock:
        state = _read_runtime_state()
        state[key] = value
        return _write_runtime_state(state)


def force_runtime_state_untrust() -> bool:
    """Invalidate runtime-state trust markers so startup reliability is downgraded."""
    with _runtime_state_lock:
        state = _read_runtime_state()
        state["last_exit"] = "running"
        identity = state.setdefault("instance_identity", {})
        if not isinstance(identity, dict):
            identity = {}
            state["instance_identity"] = identity
        identity["runtime_id"] = None
        return _write_runtime_state(state)


def derive_startup_downtime_window(now_dt=None, runtime_state=None):
    """
    Derive startup offline window bounds from runtime_state.json.

    Returns:
      {
        "window_start": datetime|None,
        "window_end": datetime|None,
        "source": "last_shutdown"|"last_startup"|"none",
        "is_reliable": bool,
        "reason_code": str,
      }

    Notes:
      - Read-only helper: never mutates runtime state.
      - "reliable" is True only when `last_shutdown_ts` is valid and usable.
      - Fallback to `last_startup_ts` is explicitly marked unreliable.
    """
    end_dt = _as_server_naive_datetime(now_dt)
    if isinstance(runtime_state, dict):
        state = runtime_state
    else:
        with _runtime_state_lock:
            state = _read_runtime_state()

    current_identity = _runtime_identity_payload()
    state_identity = _normalize_runtime_identity(state.get("instance_identity"))

    raw_shutdown = state.get("last_shutdown_ts")
    raw_startup = state.get("last_startup_ts")
    shutdown_dt = _parse_iso(raw_shutdown) if raw_shutdown else None
    startup_dt = _parse_iso(raw_startup) if raw_startup else None
    last_exit = str(state.get("last_exit") or "").strip().lower()
    last_pid = _coerce_positive_pid(state.get("last_pid"))
    last_pid_alive = _pid_is_alive(last_pid)

    if raw_startup and not startup_dt:
        return _window_result(
            window_start=None,
            window_end=None,
            source="none",
            is_reliable=False,
            reason_code="invalid_last_startup",
            current_identity=current_identity,
            state_identity=state_identity,
            last_pid_alive=last_pid_alive,
        )

    if raw_shutdown and not shutdown_dt:
        if startup_dt and startup_dt <= end_dt:
            return _window_result(
                window_start=startup_dt,
                window_end=end_dt,
                source="last_startup",
                is_reliable=False,
                reason_code="invalid_last_shutdown_fallback_startup",
                current_identity=current_identity,
                state_identity=state_identity,
                last_pid_alive=last_pid_alive,
            )
        return _window_result(
            window_start=None,
            window_end=None,
            source="none",
            is_reliable=False,
            reason_code="invalid_last_shutdown",
            current_identity=current_identity,
            state_identity=state_identity,
            last_pid_alive=last_pid_alive,
        )

    if shutdown_dt and startup_dt and shutdown_dt < startup_dt:
        if startup_dt <= end_dt:
            return _window_result(
                window_start=startup_dt,
                window_end=end_dt,
                source="last_startup",
                is_reliable=False,
                reason_code="shutdown_before_startup_fallback_startup",
                current_identity=current_identity,
                state_identity=state_identity,
                last_pid_alive=last_pid_alive,
            )
        return _window_result(
            window_start=None,
            window_end=None,
            source="none",
            is_reliable=False,
            reason_code="shutdown_before_startup",
            current_identity=current_identity,
            state_identity=state_identity,
            last_pid_alive=last_pid_alive,
        )

    if shutdown_dt and shutdown_dt <= end_dt:
        if last_exit == "running":
            return _window_result(
                window_start=shutdown_dt,
                window_end=end_dt,
                source="last_shutdown",
                is_reliable=False,
                reason_code="last_exit_running",
                current_identity=current_identity,
                state_identity=state_identity,
                last_pid_alive=last_pid_alive,
            )
        if state_identity is None:
            return _window_result(
                window_start=shutdown_dt,
                window_end=end_dt,
                source="last_shutdown",
                is_reliable=False,
                reason_code="runtime_identity_missing",
                current_identity=current_identity,
                state_identity=state_identity,
                last_pid_alive=last_pid_alive,
            )
        if state_identity.get("instance_tag") != current_identity.get("instance_tag"):
            return _window_result(
                window_start=shutdown_dt,
                window_end=end_dt,
                source="last_shutdown",
                is_reliable=False,
                reason_code="runtime_identity_mismatch",
                current_identity=current_identity,
                state_identity=state_identity,
                last_pid_alive=last_pid_alive,
            )
        if last_pid and last_pid_alive:
            return _window_result(
                window_start=shutdown_dt,
                window_end=end_dt,
                source="last_shutdown",
                is_reliable=False,
                reason_code="last_pid_still_alive",
                current_identity=current_identity,
                state_identity=state_identity,
                last_pid_alive=last_pid_alive,
            )
        return _window_result(
            window_start=shutdown_dt,
            window_end=end_dt,
            source="last_shutdown",
            is_reliable=True,
            reason_code="ok_last_shutdown",
            current_identity=current_identity,
            state_identity=state_identity,
            last_pid_alive=last_pid_alive,
        )

    if shutdown_dt and shutdown_dt > end_dt:
        if startup_dt and startup_dt <= end_dt:
            return _window_result(
                window_start=startup_dt,
                window_end=end_dt,
                source="last_startup",
                is_reliable=False,
                reason_code="shutdown_after_window_end_fallback_startup",
                current_identity=current_identity,
                state_identity=state_identity,
                last_pid_alive=last_pid_alive,
            )
        return _window_result(
            window_start=None,
            window_end=None,
            source="none",
            is_reliable=False,
            reason_code="shutdown_after_window_end",
            current_identity=current_identity,
            state_identity=state_identity,
            last_pid_alive=last_pid_alive,
        )

    if startup_dt and startup_dt <= end_dt:
        return _window_result(
            window_start=startup_dt,
            window_end=end_dt,
            source="last_startup",
            is_reliable=False,
            reason_code="missing_last_shutdown_fallback_startup",
            current_identity=current_identity,
            state_identity=state_identity,
            last_pid_alive=last_pid_alive,
        )

    return _window_result(
        window_start=None,
        window_end=None,
        source="none",
        is_reliable=False,
        reason_code="missing_runtime_timestamps",
        current_identity=current_identity,
        state_identity=state_identity,
        last_pid_alive=last_pid_alive,
    )


def _iter_all_log_files():
    patterns = [
        os.path.join(LOG_DIR, "*.log*"),
        os.path.join(USER_LOG_DIR, "*.log*"),
        os.path.join(DATA_DIR, "*", "logs", "*.log*"),
    ]
    seen = set()
    for pattern in patterns:
        for path in glob.glob(pattern):
            if path in seen:
                continue
            seen.add(path)
            if os.path.isfile(path):
                yield path


def _is_rotated_log(path):
    return ".log." in os.path.basename(path)


def _enforce_log_size_limit(force=False):
    global _last_prune_mono
    now_mono = time.monotonic()
    with _prune_lock:
        if not force and (now_mono - _last_prune_mono) < PRUNE_MIN_INTERVAL_SECONDS:
            return
        _last_prune_mono = now_mono

    files = []
    total_size = 0
    for path in _iter_all_log_files():
        try:
            size = os.path.getsize(path)
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        files.append((path, size, mtime))
        total_size += size

    initial_total_size = total_size
    deleted_rotated = 0
    truncated_current = 0
    result = "within_limit"

    if total_size > LOG_SIZE_LIMIT_BYTES:
        # Prune oldest rotated logs first.
        rotated = sorted(
            [item for item in files if _is_rotated_log(item[0])],
            key=lambda item: item[2],
        )

        for path, size, _ in rotated:
            if total_size <= LOG_SIZE_LIMIT_BYTES:
                break
            try:
                os.remove(path)
                total_size -= size
                deleted_rotated += 1
            except OSError:
                continue

        # If still above limit, truncate oldest current logs.
        if total_size > LOG_SIZE_LIMIT_BYTES:
            current_logs = sorted(
                [item for item in files if not _is_rotated_log(item[0])],
                key=lambda item: item[2],
            )
            for path, size, _ in current_logs:
                if total_size <= LOG_SIZE_LIMIT_BYTES:
                    break
                if size <= 0:
                    continue
                try:
                    with open(path, "w", encoding="utf-8"):
                        pass
                    total_size -= size
                    truncated_current += 1
                except OSError:
                    continue

            if total_size <= LOG_SIZE_LIMIT_BYTES:
                result = "pruned_or_truncated"
            else:
                result = "cap_exceeded_after_prune"
        else:
            result = "pruned_or_truncated"

        if total_size > LOG_SIZE_LIMIT_BYTES:
            _fallback_logger.warning(
                "log_size_cap_exceeded_after_prune total_bytes=%s limit_bytes=%s",
                total_size,
                LOG_SIZE_LIMIT_BYTES,
            )

    _persist_log_maintenance_metrics(
        before_bytes=initial_total_size,
        after_bytes=total_size,
        deleted_rotated=deleted_rotated,
        truncated_current=truncated_current,
        result=result,
    )


def _emit_json_record(path, record):
    try:
        logger = _get_logger_for_path(path)
        logger.info(_json_line(record))
        return True
    except Exception as e:
        _fallback_logger.error(f"log_write_failed path={path} error={e}")
        return False
    finally:
        _enforce_log_size_limit()


def _detect_clock_jump(now_dt):
    global _last_wall_dt, _last_mono_ts, _clock_event_in_progress
    mono_now = time.monotonic()
    payload = None
    should_log = False

    with _clock_lock:
        if _last_wall_dt is None:
            _last_wall_dt = now_dt
            _last_mono_ts = mono_now
            return

        expected_wall = _last_wall_dt + timedelta(seconds=(mono_now - _last_mono_ts))
        jump_seconds = (now_dt - expected_wall).total_seconds()
        if abs(jump_seconds) >= CLOCK_JUMP_THRESHOLD_SECONDS and not _clock_event_in_progress:
            _clock_event_in_progress = True
            should_log = True
            payload = {
                "jump_seconds": round(jump_seconds, 3),
                "threshold_seconds": CLOCK_JUMP_THRESHOLD_SECONDS,
                "previous_wall_ts": _last_wall_dt.isoformat(),
                "current_wall_ts": now_dt.isoformat(),
            }

        _last_wall_dt = now_dt
        _last_mono_ts = mono_now

    if should_log:
        try:
            log_system("lifecycle", "clock_jump_detected", payload, level="WARNING")
        finally:
            with _clock_lock:
                _clock_event_in_progress = False


def append_json_log(path, record):
    """Public helper for JSONL logs with rotation + retention."""
    return _emit_json_record(path, record)


def log_system(category, event, payload=None, level="INFO"):
    """
    Write a structured system log entry.
    - category: errors|scheduler|api|lifecycle|storage|system
    - event: short event name
    - payload: dict with compact details
    """
    now_dt = datetime.now()
    _detect_clock_jump(now_dt)

    safe_category = _sanitize_log_component(category, "system")
    identity = _runtime_identity_payload()
    record = {
        "ts": now_dt.isoformat(),
        "category": safe_category,
        "event": event,
        "level": level,
        "payload": payload or {},
        "identity": identity,
    }

    category_path = os.path.join(LOG_DIR, f"{safe_category}.log")
    ok_category = _emit_json_record(category_path, record)
    ok_summary = _emit_json_record(SUMMARY_LOG, record)
    return ok_category and ok_summary


def log_downtime_summary():
    """
    Logs a startup downtime summary based on persisted runtime state.
    """
    now_dt = datetime.now()
    with _runtime_state_lock:
        state = _read_runtime_state()
        current_identity = _runtime_identity_payload()
        state_identity = _normalize_runtime_identity(state.get("instance_identity"))
        identity_match = (
            bool(state_identity)
            and state_identity.get("instance_tag") == current_identity.get("instance_tag")
        )

        last_startup_dt = _parse_iso(state.get("last_startup_ts"))
        last_shutdown_dt = _parse_iso(state.get("last_shutdown_ts"))
        last_exit = state.get("last_exit", "unknown")
        last_pid = state.get("last_pid")

        window = derive_startup_downtime_window(now_dt=now_dt, runtime_state=state)
        window_start = window.get("window_start")
        window_end = window.get("window_end")
        source = window.get("source", "none")
        reliability = bool(window.get("is_reliable"))
        reason_code = window.get("reason_code", "unknown")
        downtime_seconds = None
        if window_start and window_end:
            downtime_seconds = max(0, int((window_end - window_start).total_seconds()))

        payload = {
            "now_ts": now_dt.isoformat(),
            "last_startup_ts": last_startup_dt.isoformat() if last_startup_dt else None,
            "last_shutdown_ts": last_shutdown_dt.isoformat() if last_shutdown_dt else None,
            "last_exit": last_exit,
            "last_pid": last_pid,
            "downtime_seconds": downtime_seconds,
            "downtime_source": source,
            "downtime_window_reliable": reliability,
            "downtime_reason_code": reason_code,
            "previous_exit_clean": bool(last_exit == "clean"),
            "instance_tag_current": current_identity.get("instance_tag"),
            "instance_tag_state": state_identity.get("instance_tag") if state_identity else None,
            "identity_match": identity_match if state_identity else None,
            "last_pid_alive": bool(window.get("last_pid_alive")),
        }
        log_system("lifecycle", "downtime_summary", payload)

        state["last_startup_ts"] = now_dt.isoformat()
        state["last_exit"] = "running"
        state["last_pid"] = os.getpid()
        state["instance_identity"] = current_identity
        _write_runtime_state(state)


def mark_runtime_shutdown(clean=True):
    """Persist runtime shutdown markers for startup downtime reconstruction."""
    now_dt = datetime.now()
    with _runtime_state_lock:
        state = _read_runtime_state()
        state["last_shutdown_ts"] = now_dt.isoformat()
        state["last_exit"] = "clean" if clean else "unclean"
        state["last_pid"] = os.getpid()
        state["instance_identity"] = _runtime_identity_payload()
        _write_runtime_state(state)
