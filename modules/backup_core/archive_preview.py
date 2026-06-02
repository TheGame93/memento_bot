from modules.shared.markdown_utils import md_escape_inline_code


def _fmt_size(size_bytes) -> str:
    """Format a byte count as a human-readable MB string, returning `n/a` when unavailable."""
    try:
        raw = int(size_bytes)
    except (TypeError, ValueError):
        return "n/a"
    if raw < 0:
        return "n/a"
    return f"{raw / (1024 * 1024):.2f} MB"


def _inline(value) -> str:
    """Return a Markdown-safe inline-code value for backup preview rows."""
    return md_escape_inline_code(value)


def build_archive_preview_text(
    inspect_data,
    diff_data,
    *,
    title,
    target_user_id=None,
    created_label=None,
    size_bytes=None,
    age_days=None,
    source_fallback=None,
) -> str:
    """Build a Markdown backup-preview summary string from pre-computed inspect and diff data."""
    inspected = inspect_data if isinstance(inspect_data, dict) else {}
    manifest = inspected.get("manifest") if isinstance(inspected.get("manifest"), dict) else {}

    source = inspected.get("source") or source_fallback or "n/a"
    diff_counts = {}
    if isinstance(diff_data, dict) and diff_data.get("ok") is not False:
        diff_counts = diff_data

    def count_value(key):
        return diff_counts.get(key, "n/a") if diff_counts else "n/a"

    lines = [str(title), ""]
    if target_user_id is not None:
        lines.append(f"Target user: `{_inline(target_user_id)}`")
    if created_label is not None:
        lines.append(f"Created at: `{_inline(created_label)}`")
    if age_days is not None:
        lines.append(f"Age: `{_inline(f'{age_days} days')}`")

    lines.extend(
        [
            f"Retention: `{_inline(inspected.get('retention_bucket') or 'n/a')}`",
            f"Source: `{_inline(source)}`",
            f"Alerts: `{_inline(inspected.get('alert_count'))}`",
            f"Birthdays: `{_inline(inspected.get('birthday_count'))}`",
            f"Tags: `{_inline(inspected.get('tag_count'))}`",
            f"Images: `{_inline(inspected.get('image_count'))}`",
        ]
    )
    if size_bytes is not None:
        lines.append(f"Archive size: `{_inline(_fmt_size(size_bytes))}`")
    lines.extend(
        [
            f"Schema: `{_inline(manifest.get('schema_version'))}`",
            "",
            f"Current alerts: `{_inline(count_value('current_alert_count'))}` → "
            f"Archive alerts: `{_inline(count_value('archive_alert_count'))}`",
            f"Current birthdays: `{_inline(count_value('current_birthday_count'))}` → "
            f"Archive birthdays: `{_inline(count_value('archive_birthday_count'))}`",
            f"Current images: `{_inline(count_value('current_image_count'))}` → "
            f"Archive images: `{_inline(count_value('archive_image_count'))}`",
        ]
    )
    return "\n".join(lines)
