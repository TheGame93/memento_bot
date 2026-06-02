import hashlib
import json
import os
from datetime import datetime

from modules.backup_core.constants import BACKUP_SCHEMA_VERSION


def hash_file(path, chunk_size=1024 * 1024):
    """Compute SHA256 digest hex for a file path."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def hash_bytes(payload):
    """Compute SHA256 digest hex for an in-memory byte payload."""
    digest = hashlib.sha256()
    digest.update(payload)
    return digest.hexdigest()


def build_manifest(user_id, base_dir, files, created_at=None, schema_version=None, source_map=None):
    """Build a manifest dictionary with file size and hash entries."""
    if schema_version is None:
        schema_version = BACKUP_SCHEMA_VERSION
    if created_at is None:
        created_at = datetime.now().isoformat()
    source_map = source_map or {}

    entries = []
    for rel_path in files:
        abs_path = source_map.get(rel_path) or os.path.join(base_dir, rel_path)
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"missing file: {abs_path}")
        entries.append({
            "path": rel_path,
            "size": os.path.getsize(abs_path),
            "sha256": hash_file(abs_path),
        })

    return {
        "schema_version": schema_version,
        "created_at": created_at,
        "user_id": str(user_id),
        "files": entries,
    }


def write_manifest(path, manifest):
    """Write manifest JSON to disk with parent-directory creation."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)


def to_json(manifest):
    """Serialize a manifest dictionary into indented JSON text."""
    return json.dumps(manifest, indent=2, ensure_ascii=False)


def load_manifest(path):
    """Load a manifest dictionary from a JSON file path."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_manifest(manifest):
    """Validate manifest schema essentials and return `(is_valid, errors)`."""
    errors = []
    if not isinstance(manifest, dict):
        return False, ["manifest_not_dict"]

    if manifest.get("schema_version") != BACKUP_SCHEMA_VERSION:
        errors.append("schema_version_mismatch")
    if not manifest.get("created_at"):
        errors.append("created_at_missing")
    if not manifest.get("user_id"):
        errors.append("user_id_missing")

    files = manifest.get("files")
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
