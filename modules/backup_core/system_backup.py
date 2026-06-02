import glob
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Optional

from modules import constants as C
from modules.backup_core import archive, manifest, retention
from modules.backup_core.constants import (
    BACKUP_SCHEMA_VERSION,
    RETENTION_DAILY,
    RETENTION_WEEKLY,
    RETENTION_MONTHLY,
    RETENTION_YEARLY,
)
from modules.backup_core.email_backup import _send_email, _smtp_config, normalize_email_address
from modules.backup_core.paths import get_system_backup_dir
from modules.security.authz import get_role_map, invalidate_role_map_cache
from modules.security.roles import ROLE_DEVELOPER, normalize_role
from modules.security.whitelist_store import list_whitelist_users
from modules.shared.paths import PROJECT_ROOT
from modules.systemlog import log_system

SYSTEM_BACKUP_STATE_FILENAME = "system_backup_state.json"
SYSTEM_EXCLUDE_NAMES = {"runtime_state.json"}
SYSTEM_EXCLUDE_PREFIXES = ("data/system/exports/", "data/system/imports/")
SYSTEM_BACKUP_NAME_PREFIX = "system_backup_"
SYSTEM_BACKUP_NAME_RE = r"^system_backup_(\d{8}_\d{6})(?:_\d+)?\.zip$"


def _resolve_system_data_dir(base_dir: Optional[str] = None) -> str:
    """Return system-data directory for a given project base directory."""
    root = base_dir or PROJECT_ROOT
    return os.path.join(root, "data", "system")


def _system_state_path(base_dir: Optional[str] = None) -> str:
    """Return the durable state-file path used for monthly system-backup email sends."""
    return os.path.join(_resolve_system_data_dir(base_dir), SYSTEM_BACKUP_STATE_FILENAME)


def _ensure_system_state_file(base_dir: Optional[str] = None) -> None:
    """Ensure the durable system-backup mail state file exists with default payload."""
    os.makedirs(_resolve_system_data_dir(base_dir), exist_ok=True)
    path = _system_state_path(base_dir)
    if os.path.exists(path):
        return
    payload = {"monthly_send_slots": {}}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _load_system_state(base_dir: Optional[str] = None) -> dict:
    """Load durable system-backup mail send state with normalized default structure."""
    _ensure_system_state_file(base_dir)
    path = _system_state_path(base_dir)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    slots = payload.get("monthly_send_slots")
    if not isinstance(slots, dict):
        payload["monthly_send_slots"] = {}
    return payload


def _save_system_state(payload: dict, base_dir: Optional[str] = None) -> None:
    """Persist durable system-backup mail send state atomically."""
    path = _system_state_path(base_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _is_excluded_rel_path(rel_path: str) -> bool:
    """Return whether a candidate relative system backup path is excluded by policy."""
    if rel_path in SYSTEM_EXCLUDE_NAMES:
        return True
    return any(rel_path.startswith(prefix) for prefix in SYSTEM_EXCLUDE_PREFIXES)


def _included_files(base_dir: str) -> list[str]:
    """Resolve the system-backup include set at call time from project/system JSON files."""
    _ensure_system_state_file(base_dir)

    included = []

    system_data_dir = _resolve_system_data_dir(base_dir)
    pattern = os.path.join(system_data_dir, "*.json")
    for abs_path in sorted(glob.glob(pattern)):
        rel_from_project = os.path.relpath(abs_path, base_dir).replace("\\", "/")
        rel_from_system = os.path.relpath(abs_path, system_data_dir).replace("\\", "/")
        if _is_excluded_rel_path(rel_from_project):
            continue
        if _is_excluded_rel_path(rel_from_system):
            continue
        included.append(rel_from_project)

    # Keep deterministic unique order.
    seen = set()
    result = []
    for rel_path in included:
        if rel_path in seen:
            continue
        seen.add(rel_path)
        result.append(rel_path)
    return result


SYSTEM_BACKUP_INCLUDED_FILES = _included_files


def _build_unique_archive_path(dest_dir: str, filename: str) -> str:
    """Build a collision-safe archive path in destination directory."""
    root, ext = os.path.splitext(filename)
    candidate = os.path.join(dest_dir, filename)
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(dest_dir, f"{root}_{counter}{ext}")
        counter += 1
    return candidate


def _parse_backup_timestamp(name: str) -> Optional[datetime]:
    """Parse timestamp from canonical system backup filename or return None."""
    import re

    match = re.match(SYSTEM_BACKUP_NAME_RE, str(name or ""))
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def _manifest_entries_for_files(base_dir: str, rel_files: list[str]) -> list[dict]:
    """Build manifest entries with size and hash for selected backup relative files."""
    entries = []
    for rel_path in rel_files:
        abs_path = os.path.join(base_dir, rel_path)
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"missing_file:{rel_path}")
        entries.append(
            {
                "path": rel_path,
                "size": os.path.getsize(abs_path),
                "sha256": manifest.hash_file(abs_path),
            }
        )
    return entries


def _validate_system_manifest(manifest_data: dict) -> tuple[bool, list[str]]:
    """Validate schema/scope/hash essentials for system backup manifest payloads."""
    errors = []
    if not isinstance(manifest_data, dict):
        return False, ["manifest_not_dict"]
    if manifest_data.get("schema_version") != BACKUP_SCHEMA_VERSION:
        errors.append("schema_version_mismatch")
    if manifest_data.get("scope") != "system":
        errors.append("scope_mismatch")
    files = manifest_data.get("files")
    if not isinstance(files, list):
        errors.append("files_not_list")
    else:
        for entry in files:
            if not isinstance(entry, dict):
                errors.append("file_entry_not_dict")
                continue
            if not entry.get("path"):
                errors.append("file_path_missing")
            if entry.get("size") is None:
                errors.append("file_size_missing")
            if not entry.get("sha256"):
                errors.append("file_hash_missing")
    return len(errors) == 0, errors


def build_system_backup(now=None, base_dir=None, backup_dir=None) -> dict:
    """Build one system backup archive from durable system/whitelist JSON files."""
    if now is None:
        now = datetime.now()
    base_dir = base_dir or PROJECT_ROOT
    backup_dir = backup_dir or get_system_backup_dir()

    files = SYSTEM_BACKUP_INCLUDED_FILES(base_dir)
    file_entries = _manifest_entries_for_files(base_dir, files)

    manifest_data = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "scope": "system",
        "created_at": now.isoformat(),
        "files": file_entries,
        "file_count": len(file_entries),
    }

    os.makedirs(backup_dir, exist_ok=True)
    filename = f"{SYSTEM_BACKUP_NAME_PREFIX}{now.strftime('%Y%m%d_%H%M%S')}.zip"
    archive_path = _build_unique_archive_path(backup_dir, filename)

    archive.create_zip(
        archive_path,
        base_dir,
        files,
        extra_entries={"manifest.json": json.dumps(manifest_data, indent=2, ensure_ascii=False)},
    )

    return {
        "path": archive_path,
        "timestamp": now,
        "manifest": manifest_data,
        "file_count": len(file_entries),
    }


def list_system_backups(backup_dir=None) -> list[dict]:
    """List system backup archives in canonical naming order from oldest to newest."""
    backup_dir = backup_dir or get_system_backup_dir()
    os.makedirs(backup_dir, exist_ok=True)
    items = []
    for name in os.listdir(backup_dir):
        ts = _parse_backup_timestamp(name)
        if not ts:
            continue
        path = os.path.join(backup_dir, name)
        if not os.path.isfile(path):
            continue
        items.append(
            {
                "path": path,
                "timestamp": ts,
                "name": name,
                "size_bytes": os.path.getsize(path),
            }
        )
    return sorted(items, key=lambda item: item["timestamp"])


def enforce_system_retention(now=None, backup_dir=None) -> dict:
    """Apply tiered retention to system backups and delete archives outside keep buckets."""
    items = list_system_backups(backup_dir=backup_dir)
    result = retention.select_retention(
        items,
        now=now,
        daily=RETENTION_DAILY,
        weekly=RETENTION_WEEKLY,
        monthly=RETENTION_MONTHLY,
        yearly=RETENTION_YEARLY,
    )
    for item in result.get("drop", []):
        try:
            os.remove(item["path"])
        except FileNotFoundError:
            continue
    return result


def inspect_system_archive(archive_path: str) -> dict:
    """Inspect a system backup archive by validating manifest and per-file hashes in-place."""
    result = {
        "ok": False,
        "manifest": None,
        "errors": [],
        "size_bytes": os.path.getsize(archive_path) if os.path.isfile(archive_path) else 0,
        "file_count": 0,
    }

    if not os.path.isfile(archive_path):
        result["errors"].append("archive_missing")
        return result

    try:
        with zipfile.ZipFile(archive_path, "r") as handle:
            members = set(handle.namelist())
            if "manifest.json" not in members:
                result["errors"].append("manifest_missing")
                return result
            manifest_data = json.loads(handle.read("manifest.json").decode("utf-8"))
            result["manifest"] = manifest_data
            valid, errors = _validate_system_manifest(manifest_data)
            if not valid:
                result["errors"].extend(errors)
                return result

            files = manifest_data.get("files") or []
            result["file_count"] = len(files)
            for entry in files:
                rel_path = entry.get("path")
                if rel_path not in members:
                    result["errors"].append(f"file_missing:{rel_path}")
                    return result
                payload = handle.read(rel_path)
                if len(payload) != int(entry.get("size", -1)):
                    result["errors"].append(f"size_mismatch:{rel_path}")
                    return result
                if manifest.hash_bytes(payload) != str(entry.get("sha256") or ""):
                    result["errors"].append(f"hash_mismatch:{rel_path}")
                    return result

            result["ok"] = True
            return result
    except Exception as exc:
        result["errors"].append(str(exc))
        return result


def _restore_role_map_from_archive(archive_path: str) -> dict:
    """Load normalized role map from archived whitelist payload through authz parser."""
    with tempfile.TemporaryDirectory(prefix="system_restore_roles_") as tmp_dir:
        whitelist_path = os.path.join(tmp_dir, "whitelist.json")
        with zipfile.ZipFile(archive_path, "r") as handle:
            archive_member = "data/system/whitelist.json"
            if archive_member not in set(handle.namelist()):
                return {}
            with handle.open(archive_member) as src, open(whitelist_path, "wb") as dst:
                dst.write(src.read())
        # Use official parser to support all whitelist payload shapes.
        return get_role_map(path=whitelist_path, admin_id=None)


def check_restore_guards(archive_path: str, actor_id, get_role_fn) -> tuple[bool, str]:
    """Evaluate actor and viability guards before applying a system restore archive."""
    inspected = inspect_system_archive(archive_path)
    if not inspected.get("ok"):
        return False, "archive_invalid"

    if actor_id is None or not callable(get_role_fn):
        return False, "actor_unknown"

    actor_role = get_role_fn(actor_id)
    if actor_role is None:
        return False, "actor_unknown"

    restore_roles = _restore_role_map_from_archive(archive_path)
    developers = [uid for uid, role in restore_roles.items() if normalize_role(role) == ROLE_DEVELOPER]
    if not developers:
        return False, "no_developers_in_archive"

    actor_key = str(actor_id)
    restored_actor_role = normalize_role(restore_roles.get(actor_key)) if actor_key in restore_roles else None
    if restored_actor_role != ROLE_DEVELOPER:
        return False, "actor_self_downgrade"

    return True, None


def _copy_file_atomic(src_path: str, dest_path: str) -> None:
    """Copy one file to destination path through a same-directory atomic replace."""
    dest_dir = os.path.dirname(dest_path) or "."
    os.makedirs(dest_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".system_restore_tmp_", dir=dest_dir)
    os.close(fd)
    try:
        shutil.copy2(src_path, tmp_path)
        os.replace(tmp_path, dest_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _apply_copy_plan_transactional(copy_plan: list[dict]) -> dict:
    """Apply copy plan transactionally with rollback to previous file states on failure."""
    rollback_root = tempfile.mkdtemp(prefix="system_restore_rollback_")
    applied = []
    current_path = None
    current_phase = "prepare"
    try:
        for idx, item in enumerate(copy_plan):
            src_path = item.get("src")
            dest_path = item.get("dest")
            rel_path = item.get("rel_path")
            current_path = rel_path
            if not src_path or not dest_path or not rel_path:
                raise RuntimeError("invalid_copy_plan_entry")
            if os.path.isdir(dest_path):
                raise RuntimeError(f"destination_is_directory:{rel_path}")

            backup_path = None
            existed = os.path.isfile(dest_path)
            if existed:
                current_phase = "backup_existing"
                backup_path = os.path.join(rollback_root, f"{idx}.bak")
                shutil.copy2(dest_path, backup_path)

            current_phase = "apply_copy"
            _copy_file_atomic(src_path, dest_path)
            applied.append({"dest_path": dest_path, "backup_path": backup_path, "existed": existed})
            current_phase = "prepare"

        return {
            "ok": True,
            "applied_count": len(applied),
            "partial_apply": False,
            "rollback_ok": True,
        }
    except Exception as exc:
        rollback_ok = True
        rollback_error = None
        for applied_item in reversed(applied):
            dest_path = applied_item.get("dest_path")
            backup_path = applied_item.get("backup_path")
            existed = bool(applied_item.get("existed"))
            try:
                if existed and backup_path and os.path.isfile(backup_path):
                    _copy_file_atomic(backup_path, dest_path)
                elif (not existed) and os.path.exists(dest_path):
                    os.remove(dest_path)
            except Exception as rollback_exc:
                rollback_ok = False
                if rollback_error is None:
                    rollback_error = str(rollback_exc)

        return {
            "ok": False,
            "error": "apply_failed",
            "details": str(exc),
            "partial_apply": bool(applied),
            "rollback_ok": rollback_ok,
            "rollback_error": rollback_error,
            "failure_point": {"phase": current_phase, "path": current_path},
        }
    finally:
        shutil.rmtree(rollback_root, ignore_errors=True)


def _create_system_snapshot(now=None, base_dir=None, backup_dir=None) -> dict:
    """Create a pre-restore snapshot archive for current system backup-included files."""
    if now is None:
        now = datetime.now()
    base_dir = base_dir or PROJECT_ROOT
    backup_dir = backup_dir or get_system_backup_dir()
    snapshots_dir = os.path.join(backup_dir, "snapshots")
    os.makedirs(snapshots_dir, exist_ok=True)

    files = SYSTEM_BACKUP_INCLUDED_FILES(base_dir)
    entries = _manifest_entries_for_files(base_dir, files)
    snapshot_manifest = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "scope": "system",
        "kind": "pre_restore_snapshot",
        "created_at": now.isoformat(),
        "files": entries,
        "file_count": len(entries),
    }

    filename = f"system_snapshot_{now.strftime('%Y%m%d_%H%M%S')}.zip"
    snapshot_path = _build_unique_archive_path(snapshots_dir, filename)
    archive.create_zip(
        snapshot_path,
        base_dir,
        files,
        extra_entries={"manifest.json": json.dumps(snapshot_manifest, indent=2, ensure_ascii=False)},
    )
    return {"path": snapshot_path, "manifest": snapshot_manifest}


def _extract_to_temp_dir(archive_path: str) -> str:
    """Extract system archive into a temporary directory and return its path."""
    temp_dir = tempfile.mkdtemp(prefix="system_restore_extract_")
    try:
        archive.extract_zip(archive_path, temp_dir)
        return temp_dir
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def apply_system_restore(archive_path: str, actor_id, get_role_fn, base_dir=None) -> dict:
    """Restore system files from a validated archive with guard checks and snapshot safety."""
    base_dir = base_dir or PROJECT_ROOT

    inspected = inspect_system_archive(archive_path)
    if not inspected.get("ok"):
        return {"ok": False, "snapshot_path": None, "files_restored": 0, "error": "archive_invalid"}

    allowed, reason = check_restore_guards(archive_path, actor_id, get_role_fn)
    if not allowed:
        return {"ok": False, "snapshot_path": None, "files_restored": 0, "error": reason}

    snapshot = _create_system_snapshot(base_dir=base_dir)
    snapshot_path = snapshot.get("path")

    extracted = _extract_to_temp_dir(archive_path)
    try:
        manifest_data = inspected.get("manifest") or {}
        copy_plan = []
        for entry in manifest_data.get("files", []):
            rel_path = entry.get("path")
            src_path = os.path.join(extracted, rel_path)
            dest_path = os.path.join(base_dir, rel_path)
            copy_plan.append({"src": src_path, "dest": dest_path, "rel_path": rel_path})

        tx_result = _apply_copy_plan_transactional(copy_plan)
        if not tx_result.get("ok"):
            return {
                "ok": False,
                "snapshot_path": snapshot_path,
                "files_restored": 0,
                "error": tx_result.get("error", "apply_failed"),
            }

        invalidate_role_map_cache()
        files_restored = int(tx_result.get("applied_count") or 0)
        log_system(
            "admin_audit",
            "developer_system_backup_restored",
            {
                "actor_id": str(actor_id),
                "archive_path": archive_path,
                "files_restored": files_restored,
                "snapshot_path": snapshot_path,
            },
        )
        return {
            "ok": True,
            "snapshot_path": snapshot_path,
            "files_restored": files_restored,
            "error": None,
        }
    finally:
        shutil.rmtree(extracted, ignore_errors=True)


def _resolve_developer_ids(developer_ids: Optional[list]) -> list[str]:
    """Resolve requested developer ids against whitelist store developer-role entries."""
    entries = list_whitelist_users()
    whitelist_developers = {
        str(item.get("id"))
        for item in entries
        if normalize_role(item.get("role")) == ROLE_DEVELOPER and item.get("id") is not None
    }
    if developer_ids:
        requested = {str(item) for item in developer_ids}
        return sorted(whitelist_developers.intersection(requested))
    return sorted(whitelist_developers)


def _build_system_backup_email_message(to_email: str, archive_bytes: bytes, filename: str, now: datetime) -> EmailMessage:
    """Build system-backup outbound email message with one ZIP attachment."""
    msg = EmailMessage()
    msg["Subject"] = f"System Backup Export - {now.strftime('%Y-%m-%d')}"
    msg["To"] = to_email
    msg.set_content(
        "System backup export attached.\n\n"
        f"Created at: {now.isoformat()}\n"
    )
    msg.add_attachment(
        archive_bytes,
        maintype="application",
        subtype="zip",
        filename=filename,
    )
    return msg


def send_system_backup_email(developer_ids: list, storage, now=None) -> list[dict]:
    """Send current system backup archive by mail to eligible developer recipients."""
    if now is None:
        now = datetime.now()

    resolved_ids = _resolve_developer_ids(developer_ids)
    if not resolved_ids:
        return []

    built = build_system_backup(now=now)
    archive_path = built.get("path")
    if not archive_path or not os.path.isfile(archive_path):
        return [{"developer_id": dev_id, "sent": False, "error": "archive_missing"} for dev_id in resolved_ids]

    with open(archive_path, "rb") as handle:
        archive_bytes = handle.read()

    max_bytes = int(getattr(C, "EMAIL_BACKUP_MAX_ATTACHMENT_BYTES", 0) or 0)
    if max_bytes > 0 and len(archive_bytes) > max_bytes:
        log_system(
            "backup",
            "system_backup_email_too_large",
            {
                "bytes": len(archive_bytes),
                "limit": max_bytes,
                "archive_path": archive_path,
            },
            level="ERROR",
        )
        return [
            {
                "developer_id": dev_id,
                "sent": False,
                "error": "attachment_too_large",
            }
            for dev_id in resolved_ids
        ]

    config, config_error = _smtp_config()
    if config_error:
        return [{"developer_id": dev_id, "sent": False, "error": config_error} for dev_id in resolved_ids]
    if not config.get("host"):
        return [{"developer_id": dev_id, "sent": False, "error": "smtp_host_missing"} for dev_id in resolved_ids]

    from_addr = config.get("from_addr") or config.get("user") or "no-reply@localhost"

    state = _load_system_state(PROJECT_ROOT)
    slot_key = f"{now.year}-{now.month:02d}"
    slot_bucket = state.setdefault("monthly_send_slots", {}).setdefault(slot_key, {})

    results = []
    for developer_id in resolved_ids:
        prefs = storage.get_backup_prefs(developer_id)
        to_email = normalize_email_address((prefs or {}).get("email_address"))
        if not (prefs or {}).get("email_enabled"):
            results.append({"developer_id": developer_id, "sent": False, "error": "mail_disabled"})
            slot_bucket[developer_id] = {"sent": False, "error": "mail_disabled", "ts": now.isoformat()}
            continue
        if not to_email:
            results.append({"developer_id": developer_id, "sent": False, "error": "email_missing"})
            slot_bucket[developer_id] = {"sent": False, "error": "email_missing", "ts": now.isoformat()}
            continue

        message = _build_system_backup_email_message(
            to_email,
            archive_bytes,
            os.path.basename(archive_path),
            now,
        )
        message["From"] = from_addr
        try:
            _send_email(message, config)
            payload = {
                "developer_id": str(developer_id),
                "archive_path": archive_path,
                "bytes": len(archive_bytes),
                "to_email": to_email,
            }
            log_system("admin_audit", "developer_system_backup_exported", payload)
            slot_bucket[developer_id] = {"sent": True, "ts": now.isoformat(), "bytes": len(archive_bytes)}
            results.append({"developer_id": developer_id, "sent": True, "bytes": len(archive_bytes)})
        except Exception as exc:
            slot_bucket[developer_id] = {"sent": False, "error": str(exc), "ts": now.isoformat()}
            results.append({"developer_id": developer_id, "sent": False, "error": str(exc)})

    _save_system_state(state, PROJECT_ROOT)
    return results
