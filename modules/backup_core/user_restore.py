import json
import os
import secrets
import shutil
import tempfile
from datetime import datetime
from typing import Any, Callable, Optional

from modules.backup_core import archive, manifest
from modules.backup_core.constants import (
    BACKUP_SCHEMA_VERSION,
    IMPORT_ARCHIVE_MAX_MEMBER_BYTES,
    IMPORT_ARCHIVE_MAX_MEMBERS,
    IMPORT_ARCHIVE_MAX_TOTAL_BYTES,
)
from modules.backup_core.user_backup import build_user_backup, enforce_folder_retention
from modules.security.roles import ROLE_ADMIN, ROLE_DEVELOPER, ROLE_USER, normalize_role
from modules.systemlog import force_runtime_state_untrust, log_system


def _archive_id_from_path(archive_path: str) -> str:
    """Return a stable archive identifier derived from archive filename."""
    return os.path.splitext(os.path.basename(str(archive_path or "")))[0]


def _counts_from_alerts(alerts_data: dict) -> dict:
    """Return alert/birthday counters from a canonical alerts payload dictionary."""
    alerts = alerts_data.get("alerts") if isinstance(alerts_data, dict) else []
    if not isinstance(alerts, list):
        alerts = []
    return {
        "alert_count": sum(1 for item in alerts if isinstance(item, dict) and item.get("type") != 6),
        "birthday_count": sum(1 for item in alerts if isinstance(item, dict) and item.get("type") == 6),
    }


def _image_count_from_manifest(manifest_data: dict) -> int:
    """Return image-file count declared in a validated manifest payload."""
    total = 0
    for entry in manifest_data.get("files", []):
        if isinstance(entry, dict) and str(entry.get("path") or "").startswith("images/"):
            total += 1
    return total


def _is_allowed_restore_path(rel_path: str) -> bool:
    """Check whether a manifest path is allowed in user restore archives."""
    return rel_path == "alerts.json" or rel_path.startswith("images/")


def _extract_and_validate_archive(archive_path: str, user_id: Any, data_root: str) -> dict:
    """Extract one archive into a user-local staging directory and validate file hashes."""
    staging_root = tempfile.mkdtemp(prefix=".restore_staging_", dir=data_root)
    try:
        archive.extract_zip(
            archive_path,
            staging_root,
            max_members=IMPORT_ARCHIVE_MAX_MEMBERS,
            max_member_uncompressed=IMPORT_ARCHIVE_MAX_MEMBER_BYTES,
            max_total_uncompressed=IMPORT_ARCHIVE_MAX_TOTAL_BYTES,
        )

        manifest_path = os.path.join(staging_root, "manifest.json")
        alerts_path = os.path.join(staging_root, "alerts.json")
        if not os.path.isfile(manifest_path):
            raise ValueError("manifest_missing")
        if not os.path.isfile(alerts_path):
            raise ValueError("alerts_missing")

        manifest_data = manifest.load_manifest(manifest_path)
        valid, errors = manifest.validate_manifest(manifest_data)
        if not valid:
            raise ValueError("manifest_invalid:" + ",".join(sorted(set(errors))))
        if manifest_data.get("schema_version") != BACKUP_SCHEMA_VERSION:
            raise ValueError("schema_version_mismatch")
        if str(manifest_data.get("user_id")) != str(user_id):
            raise ValueError("user_id_mismatch")

        manifest_files = manifest_data.get("files", [])
        if not isinstance(manifest_files, list):
            raise ValueError("manifest_files_not_list")

        has_alerts_entry = False
        for entry in manifest_files:
            if not isinstance(entry, dict):
                raise ValueError("manifest_file_entry_not_dict")
            rel_path = str(entry.get("path") or "")
            if not rel_path:
                raise ValueError("manifest_file_path_missing")
            if not _is_allowed_restore_path(rel_path):
                raise ValueError(f"restore_file_not_allowed:{rel_path}")

            abs_path = os.path.join(staging_root, rel_path)
            if not os.path.isfile(abs_path):
                raise ValueError(f"file_missing:{rel_path}")
            if manifest.hash_file(abs_path) != str(entry.get("sha256") or ""):
                raise ValueError(f"hash_mismatch:{rel_path}")
            if rel_path == "alerts.json":
                has_alerts_entry = True

        if not has_alerts_entry:
            raise ValueError("alerts_entry_missing")

        with open(alerts_path, "r", encoding="utf-8") as handle:
            alerts_data = json.load(handle)
        if not isinstance(alerts_data, dict):
            raise ValueError("alerts_payload_not_dict")

        return {
            "staging_root": staging_root,
            "manifest": manifest_data,
            "alerts_data": alerts_data,
        }
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise


def _swap_images_dir(storage, user_id: Any, staging_images_dir: str, data_root: str) -> None:
    """Atomically replace one user's images directory with a staged directory."""
    images_real = storage.resolve_user_images_dir(user_id, create=False)
    old_dir_name = f".images_restore_old_{secrets.token_hex(8)}"
    old_dir = os.path.join(data_root, old_dir_name)

    moved_old = False
    if os.path.isdir(images_real):
        os.rename(images_real, old_dir)
        moved_old = True

    try:
        os.rename(staging_images_dir, images_real)
    except Exception:
        if moved_old and os.path.isdir(old_dir) and not os.path.exists(images_real):
            os.rename(old_dir, images_real)
        raise

    if moved_old and os.path.isdir(old_dir):
        shutil.rmtree(old_dir, ignore_errors=True)


def _apply_staged_restore_unsafe(
    storage,
    user_id: Any,
    alerts_data: dict,
    staging_root: str,
    scheduler_state_module,
    data_root: str,
) -> dict:
    """Apply one pre-extracted restore payload while caller holds the user write lock."""
    staging_images_dir = os.path.join(staging_root, "images")
    os.makedirs(staging_images_dir, exist_ok=True)

    storage.restore_user_from_data(user_id, alerts_data)
    _swap_images_dir(storage, user_id, staging_images_dir, data_root)

    removed_pre = scheduler_state_module.prune_user_sent_pre_alerts(str(user_id))
    missed_prune = scheduler_state_module.prune_user_missed_state(str(user_id))
    runtime_untrust_ok = force_runtime_state_untrust()
    if not runtime_untrust_ok:
        raise RuntimeError("runtime_state_untrust_failed")

    return {
        "removed_pre_alert_entries": removed_pre,
        "missed_state_prune": missed_prune,
    }


def _apply_archive_unsafe(
    storage,
    user_id: Any,
    archive_path: str,
    scheduler_state_module,
    data_root: str,
) -> dict:
    """Apply one archive directly without permission/pre-import checks for rollback use only."""
    staged = _extract_and_validate_archive(archive_path, user_id, data_root)
    staging_root = staged["staging_root"]
    try:
        return _apply_staged_restore_unsafe(
            storage,
            user_id,
            staged["alerts_data"],
            staging_root,
            scheduler_state_module,
            data_root,
        )
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def _default_role_resolver(storage, get_role_fn: Optional[Callable[[Any], Optional[str]]]):
    """Resolve the role lookup callable for restore authorization checks."""
    if get_role_fn is not None:
        return get_role_fn
    return storage.get_user_role


def create_pre_import_backup(storage, user_id, now=None) -> dict:
    """Create and retain one pre-import safety snapshot archive for a user restore."""
    created = build_user_backup(
        storage,
        user_id,
        "pre_import",
        now=now,
        source="pre_import",
        enforce_quota=False,
    )
    enforce_folder_retention(user_id, "pre_import", now=now)
    return created


def check_restore_permission(actor_id, target_user_id, archive_manifest: dict, get_role_fn) -> tuple[bool, str]:
    """Authorize one restore request against actor role and target archive ownership rules."""
    target_id = str(target_user_id)
    actor_id_str = str(actor_id)
    manifest_user_id = str((archive_manifest or {}).get("user_id"))

    if manifest_user_id != target_id:
        return False, "manifest_user_mismatch"

    actor_role = normalize_role(get_role_fn(actor_id)) if callable(get_role_fn) else ROLE_USER
    target_role = normalize_role(get_role_fn(target_user_id)) if callable(get_role_fn) else ROLE_USER

    if actor_role == ROLE_DEVELOPER:
        return True, "ok_developer"

    if actor_role == ROLE_ADMIN:
        if target_role == ROLE_USER:
            return True, "ok_admin_user_target"
        return False, "admin_target_not_user"

    if actor_id_str == target_id:
        return True, "ok_self"
    return False, "user_target_mismatch"


def apply_user_restore(
    storage,
    user_id,
    archive_path: str,
    actor_id,
    scheduler_state_module,
    now=None,
    *,
    get_role_fn=None,
    source="server_restore",
) -> dict:
    """Apply one user restore archive atomically with pre-import snapshot and rollback safety."""
    if now is None:
        now = datetime.now()

    archive_id = _archive_id_from_path(archive_path)
    role_resolver = _default_role_resolver(storage, get_role_fn)

    pre_import_backup_path = None
    pre_import_created = False
    staging_root = None

    with storage.get_user_write_lock(user_id):
        data_root = storage.resolve_user_data_dir(user_id, create=True)
        current_snapshot = storage.get_user_snapshot(
            user_id,
            include_images=True,
            include_logs=False,
            ensure_space=True,
        )
        current_counts = _counts_from_alerts(current_snapshot.get("alerts_data") or {})
        current_image_count = len(current_snapshot.get("files", {}).get("images", []))

        try:
            staged = _extract_and_validate_archive(archive_path, user_id, data_root)
            staging_root = staged["staging_root"]
            manifest_data = staged["manifest"]
            archive_alerts_data = staged["alerts_data"]

            allowed, reason_code = check_restore_permission(
                actor_id,
                user_id,
                manifest_data,
                role_resolver,
            )
            if not allowed:
                return {
                    "ok": False,
                    "pre_import_backup_path": None,
                    "archive_id": archive_id,
                    "counts_diff": {},
                    "error": reason_code,
                }

            archive_counts = _counts_from_alerts(archive_alerts_data)
            counts_diff = {
                "current_alert_count": current_counts["alert_count"],
                "current_birthday_count": current_counts["birthday_count"],
                "current_image_count": current_image_count,
                "archive_alert_count": archive_counts["alert_count"],
                "archive_birthday_count": archive_counts["birthday_count"],
                "archive_image_count": _image_count_from_manifest(manifest_data),
            }

            pre_import = create_pre_import_backup(storage, user_id, now=now)
            pre_import_backup_path = pre_import.get("path")
            pre_import_created = True

            apply_meta = _apply_staged_restore_unsafe(
                storage,
                user_id,
                archive_alerts_data,
                staging_root,
                scheduler_state_module,
                data_root,
            )

            payload = {
                "actor_id": str(actor_id),
                "target_user_id": str(user_id),
                "archive_id": archive_id,
                "manifest_user_id": str(manifest_data.get("user_id")),
                "source": str(source),
                "counts_diff": counts_diff,
                "scheduler_prune": apply_meta,
                "pre_import_backup_path": pre_import_backup_path,
            }
            log_system("backup", "backup_restored", payload)
            if source == "import":
                log_system("backup", "backup_imported", payload)
            if str(actor_id) != str(user_id):
                log_system("admin_audit", "admin_user_backup_restored", payload)

            return {
                "ok": True,
                "pre_import_backup_path": pre_import_backup_path,
                "archive_id": archive_id,
                "counts_diff": counts_diff,
                "error": None,
            }
        except Exception as exc:
            reason_code = str(exc)
            rollback_ok = None
            rollback_error = None
            if pre_import_created and pre_import_backup_path:
                try:
                    _apply_archive_unsafe(
                        storage,
                        user_id,
                        pre_import_backup_path,
                        scheduler_state_module,
                        data_root,
                    )
                    rollback_ok = True
                except Exception as rollback_exc:
                    rollback_ok = False
                    rollback_error = str(rollback_exc)

            log_system(
                "backup",
                "backup_restore_failed",
                {
                    "actor_id": str(actor_id),
                    "target_user_id": str(user_id),
                    "archive_id": archive_id,
                    "source": str(source),
                    "reason_code": reason_code,
                    "rollback_ok": rollback_ok,
                    "rollback_error": rollback_error,
                    "pre_import_backup_path": pre_import_backup_path,
                },
                level="ERROR",
            )
            return {
                "ok": False,
                "pre_import_backup_path": pre_import_backup_path,
                "archive_id": archive_id,
                "counts_diff": {},
                "error": reason_code,
                "rollback_ok": rollback_ok,
                "rollback_error": rollback_error,
            }
        finally:
            if staging_root:
                shutil.rmtree(staging_root, ignore_errors=True)
