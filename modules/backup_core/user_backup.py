import json
import os
import re
import tempfile
import zipfile
from datetime import datetime

from modules import constants as C
from modules.backup_core import archive, manifest, retention
from modules.backup_core.constants import (
    BACKUP_SCHEMA_VERSION,
    PRE_IMPORT_RETENTION_DAILY,
    RETENTION_DAILY,
    RETENTION_WEEKLY,
    RETENTION_MONTHLY,
    RETENTION_YEARLY,
)
from modules.backup_core.paths import get_user_backup_folder, ensure_user_backup_root

BACKUP_NAME_RE = re.compile(r"^backup_(\d{8}_\d{6})(?:_\d+)?\.zip$")
QUOTA_BOUND_FOLDERS = ("local", "exports", "monthly")


class BackupQuotaError(Exception):
    """Report backup quota overflow with exact usage and overflow metadata."""

    def __init__(self, quota_bytes: int, usage_bytes: int, overflow_bytes: int):
        super().__init__(
            f"backup_quota_exceeded: usage={usage_bytes} quota={quota_bytes} overflow={overflow_bytes}"
        )
        self.quota_bytes = int(quota_bytes)
        self.usage_bytes = int(usage_bytes)
        self.overflow_bytes = int(overflow_bytes)


def _format_timestamp(ts):
    return ts.strftime("%Y%m%d_%H%M%S")


def _parse_timestamp(name):
    match = BACKUP_NAME_RE.match(name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def _build_unique_archive_path(dest_dir, filename):
    root, ext = os.path.splitext(filename)
    candidate = os.path.join(dest_dir, filename)
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(dest_dir, f"{root}_{counter}{ext}")
        counter += 1
    return candidate


def _iter_zip_files(folder_path):
    for name in os.listdir(folder_path):
        full = os.path.join(folder_path, name)
        if os.path.isfile(full) and name.endswith(".zip"):
            yield name, full


def _archive_counts(alerts_data):
    alerts = alerts_data.get("alerts") if isinstance(alerts_data, dict) else []
    if not isinstance(alerts, list):
        alerts = []
    alert_count = sum(1 for item in alerts if isinstance(item, dict) and item.get("type") != 6)
    birthday_count = sum(1 for item in alerts if isinstance(item, dict) and item.get("type") == 6)
    tag_set = set()
    for item in alerts:
        if not isinstance(item, dict):
            continue
        tags = item.get("tags")
        if not isinstance(tags, list):
            continue
        for tag in tags:
            if isinstance(tag, str) and tag.strip():
                tag_set.add(tag.strip())
    return {
        "alert_count": alert_count,
        "birthday_count": birthday_count,
        "tag_count": len(tag_set),
    }


def list_user_backups(user_id, folder: str) -> list[dict]:
    """List timestamped backup archives for one user/folder in oldest-first order."""
    folder_dir = get_user_backup_folder(user_id, folder)
    items = []
    for name in os.listdir(folder_dir):
        ts = _parse_timestamp(name)
        if not ts:
            continue
        path = os.path.join(folder_dir, name)
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


def get_user_quota_usage_bytes(user_id) -> int:
    """Return total size in bytes for quota-bound user backup folders."""
    total = 0
    for folder in QUOTA_BOUND_FOLDERS:
        folder_dir = get_user_backup_folder(user_id, folder)
        for _name, path in _iter_zip_files(folder_dir):
            total += os.path.getsize(path)
    return total


def check_quota_before_create(user_id, exact_new_bytes: int) -> dict:
    """Check whether creating a backup of exact_new_bytes fits user backup quota."""
    usage = get_user_quota_usage_bytes(user_id)
    quota = int(getattr(C, "USER_BACKUP_QUOTA_BYTES", 0) or 0)
    projected = usage + max(0, int(exact_new_bytes or 0))
    fits = quota <= 0 or projected <= quota
    overflow = 0 if fits else projected - quota
    return {
        "fits": fits,
        "usage_bytes": usage,
        "quota_bytes": quota,
        "overflow_bytes": overflow,
    }


def enforce_folder_retention(user_id, folder: str, now=None) -> dict:
    """Apply retention policy to one per-user backup folder and delete dropped archives."""
    items = list_user_backups(user_id, folder)
    if folder == "pre_import":
        daily, weekly, monthly, yearly = PRE_IMPORT_RETENTION_DAILY, 0, 0, 0
    else:
        daily, weekly, monthly, yearly = (
            RETENTION_DAILY,
            RETENTION_WEEKLY,
            RETENTION_MONTHLY,
            RETENTION_YEARLY,
        )

    result = retention.select_retention(
        items,
        now=now,
        daily=daily,
        weekly=weekly,
        monthly=monthly,
        yearly=yearly,
    )
    for item in result.get("drop", []):
        try:
            os.remove(item["path"])
        except FileNotFoundError:
            continue
    return result


def build_user_backup(storage, user_id, folder: str, now=None, *, source=None, enforce_quota=True) -> dict:
    """Build a canonical user backup archive and return metadata for restore/list workflows."""
    if now is None:
        now = datetime.now()

    with storage.get_user_write_lock(user_id):
        snapshot = storage.get_user_snapshot(
            user_id,
            include_images=True,
            include_logs=False,
            ensure_space=True,
        )
    base_dir = snapshot["base_dir"]
    source_map = snapshot.get("source_map") or {}
    image_files = snapshot["files"].get("images", [])
    alerts_data = snapshot.get("alerts_data") or {}

    alerts_text = json.dumps(alerts_data, indent=2, ensure_ascii=False)
    alerts_bytes = alerts_text.encode("utf-8")
    manifest_data = manifest.build_manifest(
        user_id,
        base_dir,
        image_files,
        created_at=now.isoformat(),
        schema_version=BACKUP_SCHEMA_VERSION,
        source_map=source_map,
    )
    manifest_data.setdefault("includes", {})
    manifest_data["includes"].update(
        {
            "alerts": True,
            "images": True,
            "logs": False,
            "source": source,
        }
    )
    manifest_data["files"].append(
        {
            "path": "alerts.json",
            "size": len(alerts_bytes),
            "sha256": manifest.hash_bytes(alerts_bytes),
        }
    )

    dest_dir = get_user_backup_folder(user_id, folder)
    base_name = f"backup_{_format_timestamp(now)}.zip"
    final_path = _build_unique_archive_path(dest_dir, base_name)

    user_backup_root = ensure_user_backup_root(user_id)
    with tempfile.TemporaryDirectory(
        prefix=".user_backup_build_", dir=user_backup_root
    ) as tmp_build_dir:
        temp_path = os.path.join(tmp_build_dir, os.path.basename(final_path))
        archive.create_zip(
            temp_path,
            base_dir,
            image_files,
            source_map=source_map,
            extra_entries={
                "alerts.json": alerts_text,
                "manifest.json": manifest.to_json(manifest_data),
            },
        )
        exact_new_bytes = os.path.getsize(temp_path)

        enforce_folder_retention(user_id, folder, now=now)
        if enforce_quota and folder in QUOTA_BOUND_FOLDERS:
            quota_check = check_quota_before_create(user_id, exact_new_bytes)
            if not quota_check["fits"]:
                raise BackupQuotaError(
                    quota_check["quota_bytes"],
                    quota_check["usage_bytes"],
                    quota_check["overflow_bytes"],
                )

        os.replace(temp_path, final_path)

    counts = _archive_counts(alerts_data)
    return {
        "path": final_path,
        "timestamp": now,
        "manifest": manifest_data,
        "size_bytes": os.path.getsize(final_path),
        "alert_count": counts["alert_count"],
        "birthday_count": counts["birthday_count"],
        "image_count": len(image_files),
    }


def inspect_archive(archive_path: str, expected_user_id) -> dict:
    """Inspect archive manifest and alerts payload to return safe summary metadata."""
    result = {
        "ok": False,
        "manifest": None,
        "errors": [],
        "size_bytes": os.path.getsize(archive_path) if os.path.isfile(archive_path) else 0,
        "alert_count": None,
        "birthday_count": None,
        "image_count": 0,
        "tag_count": None,
        "source": None,
        "retention_bucket": None,
    }
    if not os.path.isfile(archive_path):
        result["errors"].append("archive_missing")
        return result

    try:
        with tempfile.TemporaryDirectory(prefix="inspect_backup_") as tmp_dir:
            manifest_path = os.path.join(tmp_dir, "manifest.json")
            alerts_path = os.path.join(tmp_dir, "alerts.json")
            with zipfile.ZipFile(archive_path, "r") as handle:
                members = set(handle.namelist())
                if "manifest.json" not in members:
                    result["errors"].append("manifest_missing")
                    return result
                if "alerts.json" not in members:
                    result["errors"].append("alerts_missing")
                    return result
                with handle.open("manifest.json") as src, open(manifest_path, "wb") as dst:
                    dst.write(src.read())
                with handle.open("alerts.json") as src, open(alerts_path, "wb") as dst:
                    dst.write(src.read())

            manifest_data = manifest.load_manifest(manifest_path)
            result["manifest"] = manifest_data
            valid, errors = manifest.validate_manifest(manifest_data)
            if not valid:
                result["errors"].extend(errors)
                return result
            if str(manifest_data.get("user_id")) != str(expected_user_id):
                result["errors"].append("user_id_mismatch")
                return result

            alerts_entry = None
            for entry in manifest_data.get("files", []):
                if not isinstance(entry, dict):
                    continue
                if entry.get("path") == "alerts.json":
                    alerts_entry = entry
                    break
            if alerts_entry is None:
                result["errors"].append("alerts_entry_missing")
                return result

            expected_hash = alerts_entry.get("sha256")
            if not expected_hash or manifest.hash_file(alerts_path) != expected_hash:
                result["errors"].append("alerts_hash_mismatch")
                return result

            with open(alerts_path, "r", encoding="utf-8") as handle:
                alerts_data = json.load(handle)
            counts = _archive_counts(alerts_data)
            result["alert_count"] = counts["alert_count"]
            result["birthday_count"] = counts["birthday_count"]
            result["tag_count"] = counts["tag_count"]
            result["image_count"] = sum(
                1
                for entry in manifest_data.get("files", [])
                if isinstance(entry, dict)
                and isinstance(entry.get("path"), str)
                and entry.get("path", "").startswith("images/")
            )
            includes = manifest_data.get("includes") if isinstance(manifest_data, dict) else {}
            if isinstance(includes, dict):
                result["source"] = includes.get("source")

            ts = _parse_timestamp(os.path.basename(archive_path))
            result["retention_bucket"] = retention.retention_bucket_for_timestamp(ts)
            result["ok"] = True
            return result
    except Exception as exc:
        result["errors"].append(str(exc))
        return result


def diff_archive_vs_current(storage, user_id, archive_path: str) -> dict:
    """Compare archive content counts and preference previews against current user data."""
    result = {
        "ok": False,
        "archive_alert_count": 0,
        "archive_birthday_count": 0,
        "archive_tag_count": 0,
        "archive_image_count": 0,
        "current_alert_count": 0,
        "current_birthday_count": 0,
        "current_tag_count": 0,
        "current_image_count": 0,
        "user_prefs_changed": False,
        "backup_prefs_changed": False,
        "backup_prefs_preview": {},
        "errors": [],
    }

    inspected = inspect_archive(archive_path, user_id)
    if not inspected.get("ok"):
        result["errors"] = list(inspected.get("errors") or ["inspect_failed"])
        return result

    snapshot = storage.get_user_snapshot(
        user_id,
        include_images=True,
        include_logs=False,
        ensure_space=True,
    )
    current_data = snapshot.get("alerts_data") or {}
    current_counts = _archive_counts(current_data)

    result["archive_alert_count"] = int(inspected.get("alert_count") or 0)
    result["archive_birthday_count"] = int(inspected.get("birthday_count") or 0)
    result["archive_tag_count"] = int(inspected.get("tag_count") or 0)
    result["archive_image_count"] = int(inspected.get("image_count") or 0)
    result["current_alert_count"] = current_counts["alert_count"]
    result["current_birthday_count"] = current_counts["birthday_count"]
    result["current_tag_count"] = current_counts["tag_count"]
    result["current_image_count"] = len(snapshot.get("files", {}).get("images", []))

    with tempfile.TemporaryDirectory(prefix="diff_backup_") as tmp_dir:
        alerts_path = os.path.join(tmp_dir, "alerts.json")
        with zipfile.ZipFile(archive_path, "r") as handle:
            with handle.open("alerts.json") as src, open(alerts_path, "wb") as dst:
                dst.write(src.read())
        with open(alerts_path, "r", encoding="utf-8") as handle:
            archive_data = json.load(handle)

    archive_user_prefs = archive_data.get("user_prefs", {}) if isinstance(archive_data, dict) else {}
    archive_backup_prefs = archive_data.get("backup_prefs", {}) if isinstance(archive_data, dict) else {}
    current_user_prefs = current_data.get("user_prefs", {}) if isinstance(current_data, dict) else {}
    current_backup_prefs = current_data.get("backup_prefs", {}) if isinstance(current_data, dict) else {}

    result["user_prefs_changed"] = archive_user_prefs != current_user_prefs
    result["backup_prefs_changed"] = archive_backup_prefs != current_backup_prefs
    result["backup_prefs_preview"] = {
        "archive": {
            "email_enabled": archive_backup_prefs.get("email_enabled"),
            "email_frequency": archive_backup_prefs.get("email_frequency"),
            "email_address": archive_backup_prefs.get("email_address"),
        },
        "current": {
            "email_enabled": current_backup_prefs.get("email_enabled"),
            "email_frequency": current_backup_prefs.get("email_frequency"),
            "email_address": current_backup_prefs.get("email_address"),
        },
    }
    result["ok"] = True
    return result
