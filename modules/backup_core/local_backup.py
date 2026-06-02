import os
import re
from datetime import datetime

from modules.backup_core import retention
from modules.backup_core.constants import (
    RETENTION_DAILY,
    RETENTION_WEEKLY,
    RETENTION_MONTHLY,
    RETENTION_YEARLY,
)
from modules.backup_core.paths import get_user_backup_folder
from modules.backup_core.user_backup import BackupQuotaError, build_user_backup
from modules.systemlog import log_system
from modules.backup_core.sync_target import sync_backup_file

BACKUP_NAME_RE = re.compile(r"^backup_(\d{8}_\d{6})(?:_\d+)?\.zip$")


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


def _local_backup_dir(user_id):
    return get_user_backup_folder(user_id, "local")


def list_local_backups(user_id):
    """List parsed local backup archives for one user."""
    local_dir = _local_backup_dir(user_id)
    items = []
    for name in os.listdir(local_dir):
        ts = _parse_timestamp(name)
        if not ts:
            continue
        items.append({
            "path": os.path.join(local_dir, name),
            "timestamp": ts,
            "name": name,
        })
    return items


def create_local_backup(storage, user_id, now=None):
    """Create one local backup archive and return manifest/path metadata."""
    if now is None:
        now = datetime.now()
    return build_user_backup(
        storage,
        user_id,
        "local",
        now=now,
        source="local",
        enforce_quota=True,
    )


def enforce_retention(user_id, now=None,
                      daily=RETENTION_DAILY,
                      weekly=RETENTION_WEEKLY,
                      monthly=RETENTION_MONTHLY,
                      yearly=RETENTION_YEARLY):
    """Apply retention policy tiers and delete local backups outside keep buckets."""
    items = list_local_backups(user_id)
    if not items:
        return {
            "keep": [],
            "drop": [],
            "stats": {
                "daily": 0,
                "weekly": 0,
                "monthly": 0,
                "yearly": 0,
                "total_keep": 0,
                "total_drop": 0,
                "total_items": 0,
            },
        }

    result = retention.select_retention(
        items,
        now=now,
        daily=daily,
        weekly=weekly,
        monthly=monthly,
        yearly=yearly,
    )

    for item in result["drop"]:
        try:
            os.remove(item["path"])
        except FileNotFoundError:
            continue

    return result


def backup_user_local(storage, user_id, now=None):
    """Create, retain, and optionally sync one user's local backup pipeline."""
    try:
        created = create_local_backup(storage, user_id, now=now)
        retention_result = enforce_retention(user_id, now=now)
        sync_result = sync_backup_file(created.get("path"), user_id, now=now)
        log_system("backup", "local_backup_created", {
            "user_id": str(user_id),
            "path": created.get("path"),
            "kept": retention_result["stats"].get("total_keep"),
            "dropped": retention_result["stats"].get("total_drop"),
            "sync": sync_result,
        })
        storage.log_user_event(str(user_id), "backup_created", {
            "source": "local",
            "archive_id": os.path.splitext(os.path.basename(created.get("path") or ""))[0],
            "size_bytes": int(created.get("size_bytes") or 0),
            "alert_count": int(created.get("alert_count") or 0),
            "image_count": int(created.get("image_count") or 0),
        })
        return {
            "created": created,
            "retention": retention_result,
            "sync": sync_result,
        }
    except Exception as exc:
        log_system("backup", "local_backup_failed", {
            "user_id": str(user_id),
            "error": str(exc),
        }, level="ERROR")
        raise


def backup_all_users_local(storage, now=None):
    """Run local backup pipeline for every user and collect per-user outcomes."""
    results = []
    for user_id in storage.get_all_users():
        try:
            result = backup_user_local(storage, user_id, now=now)
            results.append({"user_id": str(user_id), "result": result})
        except BackupQuotaError as exc:
            log_system("backup", "backup_create_failed", {
                "user_id": str(user_id),
                "reason_code": "quota_exceeded",
                "quota_bytes": exc.quota_bytes,
                "usage_bytes": exc.usage_bytes,
                "overflow_bytes": exc.overflow_bytes,
            }, level="WARNING")
            results.append({
                "user_id": str(user_id),
                "error": "quota_exceeded",
            })
        except Exception as exc:
            results.append({
                "user_id": str(user_id),
                "error": str(exc),
            })
    return results
