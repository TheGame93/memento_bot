import os
import shutil
import stat
import zipfile

from modules.backup_core.constants import (
    IMPORT_ARCHIVE_MAX_MEMBER_BYTES,
    IMPORT_ARCHIVE_MAX_MEMBERS,
    IMPORT_ARCHIVE_MAX_TOTAL_BYTES,
)


def create_zip(archive_path, base_dir, files, extra_entries=None, source_map=None):
    """Create a ZIP archive from relative file paths and optional extra entries."""
    source_map = source_map or {}
    os.makedirs(os.path.dirname(archive_path), exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for rel_path in files:
            abs_path = source_map.get(rel_path) or os.path.join(base_dir, rel_path)
            if not os.path.isfile(abs_path):
                raise FileNotFoundError(f"missing file: {abs_path}")
            handle.write(abs_path, arcname=rel_path)
        if extra_entries:
            for rel_path, content in extra_entries.items():
                handle.writestr(rel_path, content)


def _is_safe_path(base_dir, path):
    base_dir = os.path.realpath(base_dir)
    target = os.path.realpath(path)
    return target.startswith(base_dir + os.sep)


def _normalize_member_path(member_path):
    if not isinstance(member_path, str):
        return None
    value = member_path.replace("\\", "/").strip()
    while value.startswith("./"):
        value = value[2:]
    if not value:
        return None
    normalized = os.path.normpath(value).replace("\\", "/")
    if normalized in {"", ".", ".."}:
        return None
    if normalized.startswith("../"):
        return None
    if os.path.isabs(value) or os.path.isabs(normalized):
        return None
    first_segment = normalized.split("/", 1)[0]
    if ":" in first_segment:
        return None
    return normalized


def _is_symlink_entry(member):
    file_mode = (member.external_attr >> 16) & 0o170000
    return stat.S_IFMT(file_mode) == stat.S_IFLNK


def _is_limited(limit_value):
    return isinstance(limit_value, int) and limit_value > 0


def extract_zip(
    archive_path,
    dest_dir,
    max_members=IMPORT_ARCHIVE_MAX_MEMBERS,
    max_member_uncompressed=IMPORT_ARCHIVE_MAX_MEMBER_BYTES,
    max_total_uncompressed=IMPORT_ARCHIVE_MAX_TOTAL_BYTES,
):
    """Extract a ZIP archive with path, symlink, and size-safety enforcement."""
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(archive_path, "r") as handle:
        members = handle.infolist()
        if _is_limited(max_members) and len(members) > max_members:
            raise ValueError("zip_too_many_entries")

        declared_total = 0
        extracted_paths = set()
        total_written = 0
        for member in members:
            if _is_symlink_entry(member):
                raise ValueError("unsafe_zip_symlink")
            normalized_name = _normalize_member_path(member.filename)
            if not normalized_name:
                raise ValueError("unsafe_zip_path")
            if normalized_name in extracted_paths:
                raise ValueError("zip_duplicate_path")
            extracted_paths.add(normalized_name)
            target_path = os.path.join(dest_dir, normalized_name)
            if not _is_safe_path(dest_dir, target_path):
                raise ValueError("unsafe_zip_path")
            if member.is_dir():
                os.makedirs(target_path, exist_ok=True)
                continue
            if member.file_size < 0:
                raise ValueError("zip_member_size_invalid")
            if _is_limited(max_member_uncompressed) and member.file_size > max_member_uncompressed:
                raise ValueError("zip_member_too_large")
            declared_total += member.file_size
            if _is_limited(max_total_uncompressed) and declared_total > max_total_uncompressed:
                raise ValueError("zip_total_too_large")

            written_bytes = 0
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            try:
                with handle.open(member, "r") as source, open(target_path, "wb") as destination:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        written_bytes += len(chunk)
                        total_written += len(chunk)
                        if _is_limited(max_member_uncompressed) and written_bytes > max_member_uncompressed:
                            raise ValueError("zip_member_too_large")
                        if _is_limited(max_total_uncompressed) and total_written > max_total_uncompressed:
                            raise ValueError("zip_total_too_large")
                        destination.write(chunk)
                if written_bytes != member.file_size:
                    raise ValueError("zip_member_size_mismatch")
            except Exception:
                try:
                    os.remove(target_path)
                except OSError:
                    pass
                raise
