import os
import json
import logging
import uuid
import shutil
import threading
import re
import glob
import tempfile
from datetime import datetime

logger = logging.getLogger(__name__)


class StorageLimitError(Exception):
    """Raised when a storage operation would exceed a security limit."""
    pass


from modules.systemlog import log_system, append_json_log
from modules import constants as C
from modules.security.authz import get_user_role, is_authorized
from modules.shared.logging_utils import hash_text, text_meta
from modules.tags_logic import contains_emoji, parse_tag
from modules.timezone_utils import (
    get_server_tz,
    compute_next_occurrence,
    now_server_naive,
    normalize_one_time_date,
    resolve_fuzzy_next_scheduled,
    resolve_user_timezone,
    to_server_naive_from_user,
)
from modules.repetition_utils import (
    decrement_count_if_needed,
    normalize_repetition_payload,
)
from modules.storage_core._alloc import (
    _UNSET,
    _allocate_next_shortcode,
    _allocate_unique_alert_id,
    _is_shortcode_valid,
)
from modules.storage_core.user_prefs_service import UserPrefsService
from modules.storage_core.tag_service import TagService
from modules.storage_core.postpone_service import PostponeService
from modules.storage_core.scheduler_state_service import SchedulerStateService
from modules.storage_core.alert_service import AlertService
from modules.storage_core.birthday_service import BirthdayService

class StorageManager:
    """Manage per-user alert data with atomic writes, migrations, and media safety."""

    def __init__(self, base_data_dir="data", admin_id=None):
        self.base_data_dir = base_data_dir
        self.admin_id = str(admin_id) if admin_id else None
        self._write_locks = {}
        self._locks_guard = threading.Lock()
        
        if not os.path.exists(self.base_data_dir):
            os.makedirs(self.base_data_dir)

        self._prefs_svc = UserPrefsService(self)
        self._tag_svc = TagService(self)
        self._postpone_svc = PostponeService(self)
        self._scheduler_svc = SchedulerStateService(self)
        self._alert_svc = AlertService(self)
        self._birthday_svc = BirthdayService(self)

    # --- INTERNAL FILE SAFETY HELPERS ---

    def _alerts_path(self, user_id):
        return os.path.join(self.base_data_dir, str(user_id), "alerts.json")

    def _user_space_dir(self, user_id):
        return os.path.join(self.base_data_dir, str(user_id))

    def _user_images_dir(self, user_id):
        return os.path.join(self._user_space_dir(user_id), "images")

    def resolve_user_data_dir(self, user_id, *, create=False):
        """Return the canonical per-user data directory path."""
        user_dir = self._user_space_dir(user_id)
        if create:
            self.setup_user_space(user_id)
        return user_dir

    def resolve_user_images_dir(self, user_id, *, create=True):
        """Return the canonical per-user images directory path."""
        images_dir = self._user_images_dir(user_id)
        if create:
            os.makedirs(images_dir, exist_ok=True)
        return images_dir

    def _looks_like_windows_abs_path(self, value):
        if not isinstance(value, str):
            return False
        return bool(re.match(r"^[A-Za-z]:[\\/]", value.strip()))

    def _is_within_dir(self, base_dir, candidate_path):
        try:
            base_real = os.path.realpath(base_dir)
            candidate_real = os.path.realpath(candidate_path)
            return os.path.commonpath([base_real, candidate_real]) == base_real
        except Exception:
            return False

    def resolve_local_image_path(self, user_id, local_image_path, require_exists=False):
        """
        Resolves alert local image path to a safe absolute path inside:
          <base_data_dir>/<user_id>/images
        Returns None when the path is invalid, escapes user scope, or (when requested) does not exist.
        """
        if not isinstance(local_image_path, str):
            return None
        raw = local_image_path.strip()
        if not raw:
            return None

        user_dir = self._user_space_dir(user_id)
        images_dir = self._user_images_dir(user_id)

        is_abs = os.path.isabs(raw) or self._looks_like_windows_abs_path(raw)
        if is_abs:
            candidate = os.path.realpath(raw.replace("\\", "/"))
        else:
            normalized_rel = os.path.normpath(raw.replace("\\", "/")).replace("\\", "/")
            if normalized_rel in {"", ".", ".."}:
                return None
            if normalized_rel.startswith("../") or "/../" in normalized_rel:
                return None
            if normalized_rel.startswith("/"):
                return None
            if normalized_rel == "images":
                return None
            if not normalized_rel.startswith("images/"):
                return None
            candidate = os.path.realpath(os.path.join(user_dir, normalized_rel))

        if not self._is_within_dir(user_dir, candidate):
            return None
        if not self._is_within_dir(images_dir, candidate):
            return None
        if require_exists and not os.path.isfile(candidate):
            return None
        return candidate

    def _to_canonical_storage_local_image_path(self, user_id, local_image_path, require_exists=False):
        """
        Converts any valid absolute/relative local image reference into canonical
        user-relative storage form: images/<filename>.
        """
        resolved = self.resolve_local_image_path(
            user_id, local_image_path, require_exists=require_exists
        )
        if not resolved:
            return None
        rel_path = os.path.relpath(resolved, self._user_space_dir(user_id)).replace("\\", "/")
        rel_path = os.path.normpath(rel_path).replace("\\", "/")
        if rel_path in {"", ".", ".."}:
            return None
        if rel_path.startswith("../") or "/../" in rel_path:
            return None
        if rel_path == "images":
            return None
        if not rel_path.startswith("images/"):
            return None
        return rel_path

    def _rebind_local_image_by_basename(self, user_id, raw_path):
        if not isinstance(raw_path, str):
            return None
        basename = os.path.basename(raw_path.strip().replace("\\", "/"))
        if not basename or basename in {".", ".."}:
            return None
        rebound = f"images/{basename}"
        if self.resolve_local_image_path(user_id, rebound, require_exists=True):
            return rebound
        return None

    def _normalize_alert_media_paths(self, user_id, data):
        """
        Normalizes alert local media paths to safe worktree-local relative paths.
        Returns (changed, stats).
        """
        stats = {
            "converted_inside": 0,
            "rebound_by_basename": 0,
            "cleared_invalid": 0,
            "already_ok": 0,
        }
        changed = False
        alerts = data.get("alerts")
        if not isinstance(alerts, list):
            return changed, stats

        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            if "local_image_path" not in alert:
                continue

            raw_value = alert.get("local_image_path")
            resolved_storage = self._to_canonical_storage_local_image_path(
                user_id, raw_value, require_exists=False
            )
            if resolved_storage:
                raw_text = raw_value.strip() if isinstance(raw_value, str) else ""
                raw_norm = os.path.normpath(raw_text.replace("\\", "/")).replace("\\", "/") if raw_text else ""
                if raw_norm == resolved_storage:
                    stats["already_ok"] += 1
                else:
                    alert["local_image_path"] = resolved_storage
                    stats["converted_inside"] += 1
                    changed = True
                continue

            rebound = self._rebind_local_image_by_basename(user_id, raw_value)
            if rebound:
                alert["local_image_path"] = rebound
                stats["rebound_by_basename"] += 1
                changed = True
                continue

            alert.pop("local_image_path", None)
            stats["cleared_invalid"] += 1
            changed = True

        return changed, stats

    def _sanitize_user_log_id(self, user_id):
        raw = str(user_id or "").strip()
        if not raw:
            return "unknown"
        normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("._-")
        if not normalized:
            return "unknown"
        return normalized[:128]

    def _user_log_dir(self):
        return os.path.join(self.base_data_dir, "userlog.d")

    def _user_event_log_primary_path(self, user_id):
        safe_id = self._sanitize_user_log_id(user_id)
        return os.path.join(self._user_log_dir(), f"{safe_id}_events.log")

    def _user_event_log_legacy_path(self, user_id):
        return os.path.join(self.base_data_dir, str(user_id), "logs", "events.log")

    def _remove_dir_if_empty(self, path):
        if not os.path.isdir(path):
            return False
        try:
            if not os.listdir(path):
                os.rmdir(path)
                return True
        except Exception:
            return False
        return False

    def get_user_event_log_path(self, user_id):
        """
        Canonical destination for per-user event logs.
        """
        return self._user_event_log_primary_path(user_id)

    def migrate_user_event_log(self, user_id):
        """
        Move/merge legacy data/<user_id>/logs/events.log into data/userlog.d/<user_id>_events.log.
        """
        lock = self._get_user_lock(user_id)
        with lock:
            primary_base = self._user_event_log_primary_path(user_id)
            legacy_base = self._user_event_log_legacy_path(user_id)
            legacy_dir = os.path.dirname(legacy_base)
            legacy_files = sorted(
                path
                for path in glob.glob(legacy_base + "*")
                if os.path.isfile(path)
            )

            if not legacy_files:
                self._remove_dir_if_empty(legacy_dir)
                return primary_base

            os.makedirs(os.path.dirname(primary_base), exist_ok=True)

            def _next_free_path(path):
                if not os.path.exists(path):
                    return path
                counter = 1
                while True:
                    candidate = f"{path}.legacy{counter}"
                    if not os.path.exists(candidate):
                        return candidate
                    counter += 1

            for legacy_path in legacy_files:
                suffix = legacy_path[len(legacy_base):]
                primary_path = primary_base + suffix
                if os.path.abspath(primary_path) == os.path.abspath(legacy_path):
                    continue
                try:
                    if not os.path.exists(primary_path):
                        shutil.move(legacy_path, primary_path)
                        continue

                    if suffix == "":
                        with open(legacy_path, "r", encoding="utf-8") as source:
                            legacy_content = source.read()
                        if legacy_content:
                            append_newline = False
                            try:
                                with open(primary_path, "rb") as destination_probe:
                                    destination_probe.seek(0, os.SEEK_END)
                                    if destination_probe.tell() > 0:
                                        destination_probe.seek(-1, os.SEEK_END)
                                        append_newline = destination_probe.read(1) != b"\n"
                            except Exception:
                                append_newline = False

                            with open(primary_path, "a", encoding="utf-8") as destination:
                                if append_newline:
                                    destination.write("\n")
                                destination.write(legacy_content)
                        os.remove(legacy_path)
                        continue

                    fallback_target = _next_free_path(primary_path)
                    shutil.move(legacy_path, fallback_target)
                except Exception as exc:
                    log_system("storage", "user_log_migration_failed", {
                        "user_id": str(user_id),
                        "legacy_path": legacy_path,
                        "primary_path": primary_path,
                        "error": str(exc),
                    }, level="ERROR")

            self._remove_dir_if_empty(legacy_dir)

            return primary_base

    def _collect_relative_files(self, root_dir, base_dir):
        if not os.path.isdir(root_dir):
            return []
        rel_paths = []
        for root, _, files in os.walk(root_dir):
            for name in files:
                abs_path = os.path.join(root, name)
                if os.path.isfile(abs_path):
                    rel_paths.append(os.path.relpath(abs_path, base_dir))
        return sorted(rel_paths)

    def _default_user_payload(self):
        return {
            "tags": list(C.TAGS),
            "alerts": [],
            "postpone_queue": [],
            "shortcut_meta": {"next_seq": 0},
            "backup_prefs": self._default_backup_prefs(),
            "user_prefs": self._default_user_prefs(),
            "user_meta": self._default_user_meta(),
        }

    def _default_user_meta(self):
        return {
            "username": None,
            "first_start": None,
            "last_seen": None,
            "added_at": None,
            "added_by": None,
            "added_via": None,
        }

    def _default_backup_prefs(self):
        return {
            "email_enabled": False,
            "email_address": None,
            "email_frequency": "monthly",
            "last_email_sent": None,
            "email_reminder_disabled": False,
            "last_email_reminder_sent": None,
            "email_send_history": [],
        }

    def _merge_backup_prefs(self, prefs):
        defaults = self._default_backup_prefs()
        if not isinstance(prefs, dict):
            return dict(defaults)
        merged = dict(defaults)
        merged.update(prefs)
        return merged

    def _default_user_prefs(self):
        return {
            "timezone_mode": C.TIMEZONE_DEFAULT_MODE,
            "timezone": {
                "source": C.TIMEZONE_SOURCE_DEFAULT,
                "name": C.SERVER_TZ,
                "state": None,
                "updated_at": None,
            },
            "birthday_default_time": C.BIRTHDAY_DEFAULT_TIME,
            "birthday_evening_before_time": C.BIRTHDAY_EVENING_BEFORE_DEFAULT_TIME,
            "birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_NONE,
        }

    def _merge_user_prefs(self, prefs):
        defaults = self._default_user_prefs()
        if not isinstance(prefs, dict):
            return dict(defaults)
        merged = dict(defaults)
        merged.update(prefs)
        return merged

    def _get_user_lock(self, user_id):
        key = str(user_id)
        with self._locks_guard:
            lock = self._write_locks.get(key)
            if lock is None:
                # Re-entrant lock allows safe nested storage operations in one thread.
                lock = threading.RLock()
                self._write_locks[key] = lock
            return lock

    def get_user_write_lock(self, user_id):
        """Return the reentrant per-user write lock for context-managed writes."""
        return self._get_user_lock(user_id)

    def _atomic_write_json(self, file_path, data):
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        tmp_path = file_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
                f.flush()
                if getattr(C, "STORAGE_ENABLE_FSYNC", False):
                    os.fsync(f.fileno())

            # Enforce alerts.json size limit before committing.
            max_bytes = getattr(C, "USER_ALERTS_JSON_MAX_BYTES", 0)
            if max_bytes > 0:
                tmp_size = os.path.getsize(tmp_path)
                if tmp_size > max_bytes:
                    os.remove(tmp_path)
                    raise StorageLimitError(
                        f"alerts.json exceeds size limit "
                        f"({tmp_size / (1024*1024):.1f} MB > "
                        f"{max_bytes / (1024*1024):.0f} MB)"
                    )

            os.replace(tmp_path, file_path)
            if getattr(C, "STORAGE_ENABLE_FSYNC", False):
                dir_fd = os.open(os.path.dirname(file_path), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            return True
        except StorageLimitError:
            raise
        except Exception:
            # Keep tmp file for possible auto-recovery.
            return False

    def get_user_folder_size(self, user_id):
        """Returns total size in bytes of the user's data folder."""
        user_dir = os.path.join(self.base_data_dir, str(user_id))
        if not os.path.isdir(user_dir):
            return 0
        total = 0
        for root, _dirs, files in os.walk(user_dir):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
        return total

    def _backup_alerts_json(self, user_id, reason):
        if not reason:
            return None
        file_path = self._alerts_path(user_id)
        if not os.path.exists(file_path):
            return None
        backup_path = file_path + ".bak"
        try:
            shutil.copy2(file_path, backup_path)
            log_system("storage", "alerts_backup_created", {
                "user_id": str(user_id),
                "reason": reason,
                "backup_path": backup_path,
            })
            return backup_path
        except Exception as e:
            log_system("storage", "alerts_backup_failed", {
                "user_id": str(user_id),
                "reason": reason,
                "error": str(e),
            }, level="ERROR")
            return None

    def _write_user_data(self, user_id, data, backup_reason=None):
        file_path = self._alerts_path(user_id)
        lock = self._get_user_lock(user_id)
        with lock:
            if backup_reason:
                self._backup_alerts_json(user_id, backup_reason)
            ok = self._atomic_write_json(file_path, data)
        if not ok:
            log_system("storage", "atomic_write_failed", {
                "user_id": str(user_id),
                "file": file_path,
            }, level="ERROR")
        return ok

    def _mutate_user_data(self, user_id, mutator, ensure_space=False, backup_reason=None):
        """
        Atomic read-modify-write helper under one user lock.
        mutator receives data dict and returns (changed: bool, result: Any).
        """
        file_path = self._alerts_path(user_id)
        lock = self._get_user_lock(user_id)
        with lock:
            if ensure_space:
                self.setup_user_space(user_id)
            data = self.get_all_alerts(user_id)
            if data is None:
                data = self._default_user_payload()

            changed, result = mutator(data)
            if not changed:
                return True, result

            if backup_reason:
                self._backup_alerts_json(user_id, backup_reason)
            ok = self._atomic_write_json(file_path, data)
            if not ok:
                log_system("storage", "atomic_write_failed", {
                    "user_id": str(user_id),
                    "file": file_path,
                }, level="ERROR")
                return False, result

            return True, result

    def _recover_corrupted_alerts(self, user_id, file_path):
        if not getattr(C, "STORAGE_AUTO_RECOVER_CORRUPTED_JSON", True):
            return None

        candidates = []
        for suffix in (".tmp", ".bak"):
            candidate = file_path + suffix
            if not os.path.exists(candidate):
                continue
            try:
                mtime = os.path.getmtime(candidate)
            except OSError:
                mtime = 0
            candidates.append((mtime, candidate))
        if not candidates:
            return None
        # Prefer freshest candidate. This avoids restoring stale-but-parseable files.
        candidates.sort(key=lambda item: item[0], reverse=True)

        forensic_backup_path = None
        if os.path.exists(file_path):
            try:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                forensic_backup_path = f"{file_path}.corrupt.{stamp}.bak"
                shutil.copy2(file_path, forensic_backup_path)
            except Exception as e:
                forensic_backup_path = None
                log_system("storage", "corrupted_source_backup_failed", {
                    "user_id": str(user_id),
                    "source": file_path,
                    "error": str(e),
                }, level="WARNING")

        for _, candidate in candidates:
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    recovered = json.load(f)
                if not isinstance(recovered, dict):
                    continue

                source_kind = "tmp" if candidate.endswith(".tmp") else "bak"
                if candidate.endswith(".tmp"):
                    os.replace(candidate, file_path)
                else:
                    restore_tmp = file_path + ".recovery.tmp"
                    with open(restore_tmp, "w", encoding="utf-8") as tmp_handle:
                        json.dump(recovered, tmp_handle, indent=4)
                    os.replace(restore_tmp, file_path)

                # Verify the restored target is truly readable from disk.
                with open(file_path, "r", encoding="utf-8") as f:
                    persisted = json.load(f)
                if not isinstance(persisted, dict):
                    raise ValueError("restored_payload_not_dict")

                log_system("storage", "alerts_json_recovered", {
                    "user_id": str(user_id),
                    "source": candidate,
                    "source_kind": source_kind,
                    "target": file_path,
                    "candidate_count": len(candidates),
                    "forensic_backup_path": forensic_backup_path,
                }, level="WARNING")
                return persisted
            except Exception as e:
                log_system("storage", "alerts_json_recovery_failed", {
                    "user_id": str(user_id),
                    "source": candidate,
                    "target": file_path,
                    "forensic_backup_path": forensic_backup_path,
                    "error": str(e),
                }, level="ERROR")
        return None

    def _normalize_alert_repetition_inplace(self, alert):
        """
        Enforces repetition schema for a single alert payload.
        Returns (normalized_repetition, changed).
        """
        if not isinstance(alert, dict):
            return None, False

        had_repetition = "repetition" in alert
        normalized = normalize_repetition_payload(alert.get("type"), alert.get("repetition"))
        if normalized is None:
            if had_repetition:
                alert.pop("repetition", None)
                return None, True
            return None, False

        if (not had_repetition) or alert.get("repetition") != normalized:
            alert["repetition"] = normalized
            return normalized, True
        return normalized, False

    def _normalize_alerts_payload(self, data, user_id=None):
        """
        Ensures alerts payload schema consistency for both normal reads and recovery.
        Returns (normalized_data, changed).
        """
        changed = False
        if not isinstance(data, dict):
            return self._default_user_payload(), True

        if "tags" not in data:
            data["tags"] = list(C.TAGS)
            changed = True
        if "alerts" not in data or not isinstance(data.get("alerts"), list):
            data["alerts"] = []
            changed = True
        if "postpone_queue" not in data or not isinstance(data.get("postpone_queue"), list):
            data["postpone_queue"] = []
            changed = True
        if "backup_prefs" not in data or not isinstance(data.get("backup_prefs"), dict):
            data["backup_prefs"] = self._default_backup_prefs()
            changed = True
        if "user_prefs" not in data or not isinstance(data.get("user_prefs"), dict):
            data["user_prefs"] = self._default_user_prefs()
            changed = True
        if "user_meta" not in data or not isinstance(data.get("user_meta"), dict):
            data["user_meta"] = self._default_user_meta()
            changed = True
        alerts = data.get("alerts")
        if isinstance(alerts, list):
            for alert in alerts:
                if not isinstance(alert, dict):
                    continue
                _normalized, rep_changed = self._normalize_alert_repetition_inplace(alert)
                if rep_changed:
                    changed = True
        if user_id is not None:
            media_changed, media_stats = self._normalize_alert_media_paths(user_id, data)
            if media_changed:
                changed = True
                total_paths = sum(media_stats.values())
                log_system("storage", "migration_local_image_paths_normalized", {
                    "user_id": str(user_id),
                    "alerts_total": len(data.get("alerts") or []),
                    "paths_total": total_paths,
                    **media_stats,
                }, level="WARNING")
        if self._ensure_shortcodes_in_data(data):
            changed = True
        return data, changed

    def _ensure_shortcodes_in_data(self, data):
        changed = False
        if not isinstance(data, dict):
            return changed

        meta = data.get("shortcut_meta")
        if not isinstance(meta, dict):
            meta = {"next_seq": 0}
            data["shortcut_meta"] = meta
            changed = True

        try:
            next_seq = int(meta.get("next_seq", 0))
        except Exception:
            next_seq = 0
            meta["next_seq"] = 0
            changed = True

        alerts = data.get("alerts")
        if not isinstance(alerts, list):
            return changed

        used_lower = set()
        missing_or_invalid = []
        for alert in alerts:
            code = alert.get("shortcode")
            lower = code.lower() if isinstance(code, str) else None
            if _is_shortcode_valid(code) and lower not in used_lower:
                used_lower.add(lower)
            else:
                missing_or_invalid.append(alert)

        for alert in missing_or_invalid:
            code, next_seq = _allocate_next_shortcode(next_seq, used_lower)
            alert["shortcode"] = code
            used_lower.add(code.lower())
            changed = True

        if meta.get("next_seq") != next_seq:
            meta["next_seq"] = next_seq
            changed = True

        return changed

    # --- LOGGING METHODS ---

    def _compact_text(self, text, max_len=200):
        if text is None:
            return None
        single_line = " ".join(str(text).split())
        if len(single_line) <= max_len:
            return single_line
        return single_line[: max_len - 3] + "..."

    def _alert_summary(self, alert_data):
        if not alert_data:
            return None
        title = alert_data.get("title", "Untitled")
        type_name = alert_data.get("type_name", "Unknown")
        schedule = alert_data.get("schedule", {})
        parts = []
        if "date" in schedule:
            parts.append(f"date={schedule.get('date')}")
        if "dates" in schedule:
            parts.append(f"dates={schedule.get('dates')}")
        if "days" in schedule:
            parts.append(f"days={schedule.get('days')}")
        if "weekdays" in schedule:
            parts.append(f"weekdays={schedule.get('weekdays')}")
        if "ordinals" in schedule:
            parts.append(f"ordinals={schedule.get('ordinals')}")
        if "interval" in schedule:
            parts.append(f"interval={schedule.get('interval')}")
        if "time" in schedule:
            parts.append(f"time={schedule.get('time')}")
        tags = alert_data.get("tags", [])
        pre_alerts = alert_data.get("pre_alerts", [])
        summary = f"{title} | {type_name} | " + ", ".join(parts)
        if tags:
            summary += f" | tags={tags}"
        if pre_alerts:
            summary += f" | pre_alerts={pre_alerts}"
        return self._compact_text(summary, max_len=240)

    def log_user_event(self, user_id, event_type, payload=None):
        """
        Append a structured log line for a user.
        Stored at: data/userlog.d/<user_id>_events.log
        """
        try:
            # Security hardening: never auto-provision unknown users through logging side-effects.
            if not self.is_user_whitelisted(user_id):
                log_system("onboarding", event_type, {
                    "user_id": str(user_id),
                    "note": "user_not_yet_whitelisted",
                    **(payload or {}),
                }, level="INFO")
                return False

            self.setup_user_space(user_id)
            log_path = self.migrate_user_event_log(user_id)
            os.makedirs(os.path.dirname(log_path), exist_ok=True)

            record = {
                "ts": datetime.now().isoformat(),
                "user_id": str(user_id),
                "event": event_type,
                "payload": payload or {}
            }
            ok = append_json_log(log_path, record)
            if not ok:
                raise RuntimeError("append_json_log failed")
            return True
        except Exception as e:
            logger.error(f"Failed to write user log for {user_id}: {e}")
            log_system("storage", "user_log_write_failed", {
                "user_id": str(user_id),
                "error": str(e),
            }, level="ERROR")
            return False

    def is_user_whitelisted(self, user_id):
        """Returns True when the user is present in whitelist/roles policy."""
        return is_authorized(user_id, admin_id=self.admin_id)

    def get_user_role(self, user_id):
        """Returns user role: developer/admin/user or None when unauthorized."""
        return get_user_role(user_id, admin_id=self.admin_id)

    def setup_user_space(self, user_id):
        """Create or migrate a user's storage space to the current schema."""
        user_path = self._user_space_dir(user_id)
        # Concurrent setup calls may happen from multiple handlers/threads.
        os.makedirs(user_path, exist_ok=True)
        os.makedirs(os.path.join(user_path, "images"), exist_ok=True)
        os.makedirs(self._user_log_dir(), exist_ok=True)
            
        file_path = os.path.join(user_path, "alerts.json")
        
        if not os.path.exists(file_path):
            # Brand new user
            self._write_user_data(user_id, self._default_user_payload())
        else:
            # EXISTING USER MIGRATION
            data = self.get_all_alerts(user_id)
            if data is not None and "tags" not in data:
                # We add the default tags from constants.py to your existing file
                data["tags"] = C.TAGS
                self._write_user_data(user_id, data, backup_reason="migration")
                logger.info(f"✅ Migrated user {user_id}: added default tags key.")
                log_system("storage", "migration_add_tags", {
                    "user_id": str(user_id),
                    "tags_added": len(C.TAGS),
                })
            if data is not None and "postpone_queue" not in data:
                data["postpone_queue"] = []
                self._write_user_data(user_id, data, backup_reason="migration")
                log_system("storage", "migration_add_postpone_queue", {
                    "user_id": str(user_id),
                })
            if data is not None and "backup_prefs" not in data:
                data["backup_prefs"] = self._default_backup_prefs()
                self._write_user_data(user_id, data, backup_reason="migration")
                log_system("storage", "migration_add_backup_prefs", {
                    "user_id": str(user_id),
                })
            if data is not None and "user_prefs" not in data:
                data["user_prefs"] = self._default_user_prefs()
                self._write_user_data(user_id, data, backup_reason="migration")
                log_system("storage", "migration_add_user_prefs", {
                    "user_id": str(user_id),
                })
            if data is not None and "user_meta" not in data:
                data["user_meta"] = self._default_user_meta()
                self._write_user_data(user_id, data, backup_reason="migration")
                log_system("storage", "migration_add_user_meta", {
                    "user_id": str(user_id),
                })
            if data is not None:
                changed = self._ensure_shortcodes_in_data(data)
                if changed:
                    self._write_user_data(user_id, data, backup_reason="migration")
                    log_system("storage", "migration_add_shortcodes", {
                        "user_id": str(user_id),
                        "alerts": len(data.get("alerts", [])),
                    })
        self.migrate_user_event_log(user_id)
        return user_path

    def get_all_alerts(self, user_id):
        """Reads the entire JSON for the user."""
        file_path = self._alerts_path(user_id)
        if not os.path.exists(file_path): 
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            data, changed = self._normalize_alerts_payload(loaded, user_id=user_id)
            if changed:
                self._write_user_data(user_id, data, backup_reason="migration")
            return data
        except json.JSONDecodeError as e:
            logger.error(f"Corrupted JSON for user {user_id}")
            log_system("storage", "json_decode_error", {
                "user_id": str(user_id),
                "file": file_path,
                "error": str(e),
            }, level="ERROR")
            recovered = self._recover_corrupted_alerts(user_id, file_path)
            if recovered is not None:
                data, changed = self._normalize_alerts_payload(recovered, user_id=user_id)
                if changed:
                    self._write_user_data(user_id, data, backup_reason="migration")
                return data
            return None

    def get_user_snapshot(self, user_id, include_images=True, include_logs=True, ensure_space=False):
        """
        Returns a consistent snapshot of user data and related files under a lock.
        """
        lock = self._get_user_lock(user_id)
        with lock:
            if ensure_space:
                self.setup_user_space(user_id)
            user_dir = os.path.join(self.base_data_dir, str(user_id))
            alerts_path = self._alerts_path(user_id)
            alerts_data = self.get_all_alerts(user_id) or self._default_user_payload()

            image_files = []
            if include_images:
                image_files = self._collect_relative_files(
                    os.path.join(user_dir, "images"),
                    user_dir,
                )

            source_map = {}
            log_files = []
            if include_logs:
                primary_base = self._user_event_log_primary_path(user_id)
                legacy_base = self._user_event_log_legacy_path(user_id)
                primary_paths = sorted(
                    path
                    for path in glob.glob(primary_base + "*")
                    if os.path.isfile(path)
                )
                legacy_paths = sorted(
                    path
                    for path in glob.glob(legacy_base + "*")
                    if os.path.isfile(path)
                )

                selected_paths = primary_paths or legacy_paths
                using_primary = bool(primary_paths)
                user_dir_abs = os.path.abspath(user_dir)

                for selected_abs in selected_paths:
                    if using_primary:
                        suffix = selected_abs[len(primary_base):]
                        rel_log = os.path.join("logs", f"events.log{suffix}")
                    else:
                        rel_log = os.path.relpath(selected_abs, user_dir)

                    if rel_log in log_files:
                        continue
                    log_files.append(rel_log)

                    selected_abs_norm = os.path.abspath(selected_abs)
                    try:
                        common = os.path.commonpath([selected_abs_norm, user_dir_abs])
                    except Exception:
                        common = None
                    if common != user_dir_abs:
                        source_map[rel_log] = selected_abs_norm

                log_files.sort()

            alert_rel = []
            if os.path.isfile(alerts_path):
                alert_rel = [os.path.relpath(alerts_path, user_dir)]

            return {
                "user_id": str(user_id),
                "base_dir": user_dir,
                "alerts_path": alerts_path,
                "alerts_data": alerts_data,
                "files": {
                    "alerts": alert_rel,
                    "images": image_files,
                    "logs": log_files,
                },
                "source_map": source_map,
            }

    def restore_user_from_data(self, user_id, alerts_data):
        """Validate, normalize, and atomically persist restored user alerts payload."""
        if not isinstance(alerts_data, dict):
            raise ValueError("alerts_data must be a dict")
        normalized_input = json.loads(json.dumps(alerts_data))
        normalized, _changed = self._normalize_alerts_payload(
            normalized_input, user_id=user_id
        )
        ok = self._atomic_write_json(self._alerts_path(user_id), normalized)
        if not ok:
            raise OSError("atomic_write_failed")

    def get_backup_prefs(self, user_id):
        """Return merged backup preferences with defaults applied."""
        data = self.get_all_alerts(user_id) or self._default_user_payload()
        prefs = data.get("backup_prefs")
        return self._merge_backup_prefs(prefs)

    def get_user_prefs(self, user_id):
        """Return merged user preferences with defaults applied."""
        data = self.get_all_alerts(user_id) or self._default_user_payload()
        return self._merge_user_prefs(data.get("user_prefs"))

    def get_user_meta(self, user_id):
        """Return user metadata, falling back to default metadata shape."""
        data = self.get_all_alerts(user_id) or self._default_user_payload()
        meta = data.get("user_meta")
        if not isinstance(meta, dict):
            meta = self._default_user_meta()
        return meta

    def update_user_meta(self, user_id, updates, ensure_space=True):
        """Persist user metadata updates and return the merged metadata snapshot."""
        return self._prefs_svc.update_user_meta(user_id, updates, ensure_space=ensure_space)

    def touch_user_activity(self, user_id):
        """
        Update last_seen for a user, throttled to avoid excessive disk I/O.
        Skips the write if last_seen is already within ACTIVITY_WRITE_THROTTLE_SECONDS.
        """
        return self._prefs_svc.touch_user_activity(user_id)

    def update_user_prefs(self, user_id, updates, ensure_space=True):
        """Persist user preference updates and return the merged preferences."""
        return self._prefs_svc.update_user_prefs(user_id, updates, ensure_space=ensure_space)

    def update_birthday_schedule_time(self, user_id, time_str, user_prefs=None):
        """Update birthday alert times and recompute their next scheduled occurrences.

        Return a status payload with `ok`, `updated`, and `total` counters so
        callers can report partial or empty updates without re-reading alerts.
        """
        return self._prefs_svc.update_birthday_schedule_time(
            user_id, time_str, user_prefs=user_prefs
        )

    def update_backup_prefs(self, user_id, updates, ensure_space=True):
        """Persist backup preference updates and return the merged preferences."""
        return self._prefs_svc.update_backup_prefs(user_id, updates, ensure_space=ensure_space)

    def save_birthdays_bulk(self, user_id, entries, *, source="settings_bulk_import"):
        """
        Atomically saves multiple birthday alerts in one storage transaction.

        Returns:
            {
              "ok": bool,
              "saved_count": int,
              "ids": list[str],
              "failure_reason": str|None
            }
        """
        return self._birthday_svc.save_birthdays_bulk(user_id, entries, source=source)

    def save_alert(self, user_id, alert_data):
        """Persist a new alert, compute next_scheduled, and return the allocated alert ID.

        Returns the new alert ID string on success, None on write failure, or raises
        StorageLimitError when the per-user alert cap is reached.
        """
        return self._alert_svc.save_alert(user_id, alert_data)

    def delete_alert(self, user_id, alert_id):
        """Delete an alert and clean related postpone entries and local media files."""
        return self._alert_svc.delete_alert(user_id, alert_id)

    def toggle_alert(self, user_id, alert_id):
        """Toggle an alert active flag, clearing stale snooze state when re-enabling it."""
        return self._alert_svc.toggle_alert(user_id, alert_id)

    # --- TAG MANAGEMENT METHODS ---

    def get_user_tags(self, user_id):
        """Returns the list of custom tags for a user, or the default list."""
        data = self.get_all_alerts(user_id)
        if data and "tags" in data:
            tags = data["tags"]
            if isinstance(tags, list):
                return tags
        
        # Fallback to defaults from constants if user has no custom tags yet
        from modules import constants as C
        return list(C.TAGS)

    def add_user_tag(self, user_id, tag_name):
        """
        Adds a new tag to the user's master list.
        Returns: (success: bool, error_reason: str or None)
        
        Checks for:
        - Exact duplicate (same emoji + name)
        - Name duplicate (different emoji, same name)
        """
        return self._tag_svc.add_user_tag(user_id, tag_name)

    def delete_user_tag(self, user_id, tag_to_del):
        """Removes a tag from the master list and all alerts."""
        return self._tag_svc.delete_user_tag(user_id, tag_to_del)

    def rename_user_tag(self, user_id, old_tag, new_tag):
        """
        Rename old_tag to new_tag in the master list and propagate to every alert that carries it.

        Returns (success: bool, error_reason: str | None).
        error_reason values: 'not_found', 'same_tag', 'exact_duplicate',
        'name_duplicate:<existing_tag>', 'storage_unavailable'.
        Tag order within each alert's tags list is preserved.
        """
        return self._tag_svc.rename_user_tag(user_id, old_tag, new_tag)

    async def download_image(self, bot, user_id, file_id):
        """Download Telegram media into user storage with lock-serialized final placement."""
        self.setup_user_space(user_id)
        data_root = self.resolve_user_data_dir(user_id, create=True)
        tmp_upload_dir = os.path.join(data_root, ".tmp_uploads")
        os.makedirs(tmp_upload_dir, exist_ok=True)

        new_file = await bot.get_file(file_id)
        ext = (new_file.file_path or "").split(".")[-1] if getattr(new_file, "file_path", None) else "bin"
        final_name = f"{file_id}.{ext}"
        tmp_file = tempfile.NamedTemporaryFile(
            prefix=f"upload_{file_id}_",
            suffix=f".{ext}",
            dir=tmp_upload_dir,
            delete=False,
        )
        tmp_path = tmp_file.name
        tmp_file.close()

        try:
            await new_file.download_to_drive(tmp_path)
            with self.get_user_write_lock(user_id):
                max_folder = getattr(C, "USER_FOLDER_MAX_BYTES", 0)
                if max_folder > 0:
                    current_size = self.get_user_folder_size(user_id)
                    if current_size > max_folder:
                        try:
                            os.remove(tmp_path)
                        except OSError:
                            pass
                        raise StorageLimitError(
                            f"User folder is full "
                            f"({current_size / (1024*1024):.1f} MB / "
                            f"{max_folder / (1024*1024):.0f} MB limit)"
                        )

                img_dir = self.resolve_user_images_dir(user_id, create=True)
                final_path = os.path.join(img_dir, final_name)
                os.replace(tmp_path, final_path)
                rel_path = self._to_canonical_storage_local_image_path(
                    user_id, final_path, require_exists=True
                )
                if not rel_path:
                    raise OSError("canonical_path_verification_failed")
                return rel_path
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    # =========================================================================
    # SCHEDULER METHODS
    # =========================================================================

    def get_all_users(self):
        """
        Returns a list of all user_ids that have data folders.
        Used by scheduler to load alerts for all users on startup.
        """
        users = self.get_all_dataset_users()
        # Enforce user filtering only when admin identity is configured.
        enforce_auth_filter = bool(self.admin_id)
        if not enforce_auth_filter:
            return users

        authorized_users = []
        for item in users:
            # Security hardening: scheduler should never process non-authorized users.
            if self.is_user_whitelisted(item):
                authorized_users.append(item)
        return authorized_users

    def get_all_dataset_users(self, raise_on_error=False):
        """
        Returns numeric user IDs that have a dataset directory with alerts.json.
        No whitelist/auth filtering is applied.
        Set `raise_on_error=True` to surface scan failures to callers that need
        explicit failure telemetry.
        """
        users = []
        try:
            for item in os.listdir(self.base_data_dir):
                item_path = os.path.join(self.base_data_dir, item)
                # Check if it's a directory and the name is numeric (user_id)
                if os.path.isdir(item_path) and item.isdigit():
                    # Verify alerts.json exists
                    if os.path.exists(os.path.join(item_path, "alerts.json")):
                        users.append(item)
        except Exception as e:
            logger.error(f"Error scanning user directories: {e}")
            log_system("storage", "scan_users_failed", {
                "error": str(e),
            }, level="ERROR")
            if raise_on_error:
                raise
        return sorted(users, key=lambda x: int(x))

    def get_active_alerts(self, user_id):
        """Returns only alerts where active=True for a given user."""
        data = self.get_all_alerts(user_id)
        if not data:
            return []
        return [a for a in data.get('alerts', []) if a.get('active', True)]

    def get_alert_by_id(self, user_id, alert_id):
        """Returns a single alert by ID, or None if not found."""
        data = self.get_all_alerts(user_id)
        if not data:
            return None
        return next((a for a in data.get('alerts', []) if a['id'] == alert_id), None)

    def get_alert_by_shortcode(self, user_id, shortcode):
        """Returns a single alert by permanent user-local shortcut code."""
        if not isinstance(shortcode, str):
            return None
        data = self.get_all_alerts(user_id)
        if not data:
            return None
        return next(
            (a for a in data.get("alerts", []) if a.get("shortcode") == shortcode),
            None
        )

    def update_alert_fields(self, user_id, alert_id, updates):
        """
        Updates arbitrary top-level fields on an alert.
        Returns True if updated, False otherwise.
        """
        return self._scheduler_svc.update_alert_fields(user_id, alert_id, updates)

    def update_alert_schedule_state(
        self,
        user_id,
        alert_id,
        last_triggered=None,
        next_scheduled=None,
        snoozed_until=None,
        fuzzy_history=_UNSET,
    ):
        """
        Update scheduling metadata for an alert in one atomic storage mutation.
        
        Args:
            user_id: User ID
            alert_id: Alert ID
            last_triggered: datetime or ISO string of last trigger time
            next_scheduled: datetime or ISO string of next scheduled time
            snoozed_until: datetime or ISO string if alert is snoozed.
                Passing None does not modify snooze state; callers must use
                clear_alert_snooze(...) to clear an existing snooze.
            fuzzy_history: Optional list payload to persist at alert top level.
                Pass None to clear stored history; omit to leave unchanged.
        
        Returns:
            True if update successful, False otherwise
        """
        return self._scheduler_svc.update_alert_schedule_state(
            user_id,
            alert_id,
            last_triggered=last_triggered,
            next_scheduled=next_scheduled,
            snoozed_until=snoozed_until,
            fuzzy_history=fuzzy_history,
        )

    def clear_alert_snooze(self, user_id, alert_id):
        """Clears the snoozed_until field for an alert."""
        return self._scheduler_svc.clear_alert_snooze(user_id, alert_id)

    def mark_alert_done(self, user_id, alert_id):
        """
        Marks an alert as 'done' for this occurrence.
        For one-time alerts: sets active=False
        For recurring alerts: updates last_triggered and clears snooze
        
        Returns: (success: bool, was_one_time: bool)
        """
        return self._scheduler_svc.mark_alert_done(user_id, alert_id)

    def consume_repetition_occurrence(self, user_id, alert_id, *, should_count=True):
        """
        Atomically normalizes/decrements repetition for one alert occurrence.

        Returns a structured dict:
        {
            "ok": bool,
            "found": bool,
            "changed": bool,
            "alert_type": Any,
            "repetition": dict|None,
            "before": int|None,
            "after": int|None,
            "exhausted": bool,
            "should_count": bool,
        }
        """
        return self._scheduler_svc.consume_repetition_occurrence(
            user_id,
            alert_id,
            should_count=should_count,
        )

    def get_all_active_alerts_all_users(self):
        """
        Returns a dict of {user_id: [active_alerts]} for all users.
        Used by scheduler for bulk loading on startup.
        """
        result = {}
        for user_id in self.get_all_users():
            alerts = self.get_active_alerts(user_id)
            if alerts:
                result[user_id] = alerts
        return result

    # =========================================================================
    # POSTPONE QUEUE METHODS
    # =========================================================================

    def get_postpone_queue(self, user_id):
        """Return the stored postpone queue for a user."""
        data = self.get_all_alerts(user_id)
        if not data:
            return []
        return data.get("postpone_queue", []) or []

    def add_postpone_instance(self, user_id, instance):
        """Append a postpone instance and emit the corresponding user event."""
        return self._postpone_svc.add_postpone_instance(user_id, instance)

    def update_postpone_instance(self, user_id, instance_id, updates):
        """Update one postpone instance and report whether it was found."""
        return self._postpone_svc.update_postpone_instance(user_id, instance_id, updates)

    def remove_postpone_instance(self, user_id, instance_id):
        """Remove one postpone instance and report whether removal occurred."""
        return self._postpone_svc.remove_postpone_instance(user_id, instance_id)

    def cleanup_postpone_queue(self, user_id, now_iso=None):
        """
        Removes any postpone instances that are not pending.
        Returns count of removed items.
        """
        return self._postpone_svc.cleanup_postpone_queue(user_id, now_iso=now_iso)

    def expire_pending_postpones_for_alert(self, user_id, alert_id):
        """
        Marks pending postpone items for a given alert as expired.

        Returns count of items transitioned from pending -> expired.
        """
        return self._postpone_svc.expire_pending_postpones_for_alert(user_id, alert_id)
