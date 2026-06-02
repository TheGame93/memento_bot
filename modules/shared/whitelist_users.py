from typing import Any, Callable, Dict, Iterable, List, Tuple

from modules.shared.user_identity import build_label_sort_key, format_user_label_from_meta
from modules import constants as C

ROLE_SORT_ORDER = {
    "developer": 0,
    "admin": 1,
    "user": 2,
}
ROLE_SECTION_TITLES = {
    "developer": "**DEVELOPERS**",
    "admin": "**ADMINS**",
    "user": "**USERS**",
}


def _format_seconds_label(seconds: Any) -> str:
    try:
        value = int(seconds)
    except Exception:
        return "n/a"
    if value < 0:
        return "n/a"

    minute = 60
    hour = 60 * minute
    day = 24 * hour
    week = 7 * day
    month = 30 * day
    year = 365 * day

    def _clamp_round(value_seconds: int, unit_seconds: int, minimum: int, maximum: int | None = None) -> int:
        rounded = int(round(value_seconds / float(unit_seconds))) if unit_seconds else 0
        if rounded < minimum:
            rounded = minimum
        if maximum is not None and rounded > maximum:
            rounded = maximum
        return rounded

    if value < hour:
        return f"{_clamp_round(value, minute, 1, 59)}m"
    if value < day:
        return f"{_clamp_round(value, hour, 1, 23)}h"
    if value < week:
        return f"{_clamp_round(value, day, 1, 6)}d"
    if value < 4 * week:
        return f"{_clamp_round(value, week, 1, 3)}w"
    if value < 12 * month:
        return f"{_clamp_round(value, month, 1, 11)}m"
    return f"{_clamp_round(value, year, 1)}y"


def _build_activity_reminder() -> str:
    icon_purple = getattr(C, "ACTIVITY_ICON_PURPLE", "\U0001f7e3")
    icon_green = getattr(C, "ACTIVITY_ICON_GREEN", "\U0001f7e2")
    icon_orange = getattr(C, "ACTIVITY_ICON_ORANGE", "\U0001f7e0")
    icon_red = getattr(C, "ACTIVITY_ICON_RED", "\U0001f534")
    purple = _format_seconds_label(getattr(C, "ACTIVITY_PURPLE_SECONDS", getattr(C, "ACTIVITY_GREEN_SECONDS", 600)))
    green = _format_seconds_label(getattr(C, "ACTIVITY_GREEN_SECONDS", 86400))
    orange = _format_seconds_label(getattr(C, "ACTIVITY_ORANGE_SECONDS", 7 * 86400))
    return (
        "Status icons: "
        "(no icon)=never active, \n"
        f"{icon_purple}<={purple}, "
        f"{icon_green}<={green}, "
        f"{icon_orange}<={orange}, "
        f"{icon_red} older"
    )


def build_whitelist_users_empty_text() -> str:
    """Build the empty-state message for whitelist user lists."""
    return "\n".join([
        "👥 **Whitelisted Users**",
        _build_activity_reminder(),
        "No users found.",
    ])


def _normalize_role(role: Any) -> str:
    role_text = str(role).strip().lower() if role is not None else ""
    if role_text in ROLE_SORT_ORDER:
        return role_text
    return "user"


def _parse_limit(limit: int | None) -> int | None:
    """Parse an optional entry-count cap while keeping fail-open behavior."""
    if limit is None:
        return None
    try:
        parsed_limit = int(limit)
    except Exception:
        return None
    if parsed_limit <= 0:
        return None
    return parsed_limit


def _extract_icon_and_stats(raw: Any) -> tuple[str | None, str]:
    if isinstance(raw, tuple):
        icon, stats = raw
    else:
        icon, stats = None, raw
    icon_text = str(icon).strip() if icon is not None else ""
    stats_text = str(stats or "").strip()
    return (icon_text or None, stats_text)


def _build_compact_user_row(
    *,
    alias_value: str,
    include_alias: bool,
    icon: str | None,
    label: str,
    stats: str,
) -> str:
    """Build one compact whitelist row without introducing duplicate spacing."""
    prefix = f"/{alias_value}" if include_alias else alias_value
    parts = [prefix]
    if icon:
        parts.append(icon)
    parts.append(label)
    row = " ".join(parts)
    if stats:
        row += f" | {stats}"
    return row


def _build_role_rows(
    entries: Iterable[Dict[str, Any]],
    meta_map: Dict[str, Any],
    summary_map: Dict[str, Any],
    format_summary: Callable[..., str],
    *,
    include_alias: bool,
    limit: int | None = None,
) -> tuple[Dict[str, List[str]], Dict[str, str], int, int | None]:
    sorted_entries = sort_whitelist_entries(entries, meta_map)
    valid_entries = [entry for entry in sorted_entries if entry.get("id") is not None]
    applied_limit = _parse_limit(limit)
    role_rows: Dict[str, List[str]] = {
        "developer": [],
        "admin": [],
        "user": [],
    }
    alias_map: Dict[str, str] = {}
    shown = 0

    for role in ("developer", "admin", "user"):
        for entry in valid_entries:
            if applied_limit is not None and shown >= applied_limit:
                break
            entry_role = _normalize_role(entry.get("role"))
            if entry_role != role:
                continue
            uid = entry.get("id")
            meta = meta_map.get(str(uid)) or {}
            label = format_user_label_from_meta(uid, meta, escape_markdown=True)
            icon, stats = _extract_icon_and_stats(format_summary(summary_map.get(str(uid)), meta=meta))
            alias_value = f"{shown + 1:02d}"
            alias_map[alias_value] = str(uid)
            role_rows[role].append(
                _build_compact_user_row(
                    alias_value=alias_value,
                    include_alias=include_alias,
                    icon=icon,
                    label=label,
                    stats=stats,
                )
            )
            shown += 1

    return role_rows, alias_map, len(valid_entries), applied_limit


def sort_whitelist_entries(entries: Iterable[Dict[str, Any]], meta_map: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Sort whitelist entries by role priority and configured identity label."""
    safe_entries = [e for e in entries if isinstance(e, dict)]
    meta_map = meta_map or {}

    def _key(entry: Dict[str, Any]):
        uid = entry.get("id")
        role = _normalize_role(entry.get("role"))
        meta = meta_map.get(str(uid)) or {}
        return (
            ROLE_SORT_ORDER.get(role, 99),
            build_label_sort_key(
                uid,
                meta.get("username"),
                meta.get("display_name"),
                custom_name=meta.get("custom_name"),
                label_order=meta.get("label_order"),
            ),
        )

    return sorted(safe_entries, key=_key)


def build_whitelist_users_text(
    entries: Iterable[Dict[str, Any]],
    meta_map: Dict[str, Any],
    summary_map: Dict[str, Any],
    format_summary: Callable[..., str],
    *,
    include_alias: bool,
    empty_text: str,
    limit: int | None = None,
) -> Tuple[str, Dict[str, str]]:
    """Render grouped whitelist sections with compact one-line rows and alias mapping."""
    entries = list(entries or [])
    if not entries:
        return empty_text, {}

    summary_map = summary_map or {}
    meta_map = meta_map or {}
    role_rows, alias_map, valid_total, applied_limit = _build_role_rows(
        entries,
        meta_map,
        summary_map,
        format_summary,
        include_alias=include_alias,
        limit=limit,
    )
    total_rows = sum(len(rows) for rows in role_rows.values())
    if total_rows <= 0:
        return empty_text, {}

    lines = ["👥 **Whitelisted Users**", _build_activity_reminder()]
    for role in ("developer", "admin", "user"):
        rows = role_rows.get(role) or []
        if not rows:
            continue
        lines.append("")
        lines.append(ROLE_SECTION_TITLES[role])
        lines.extend(rows)

    if applied_limit is not None and valid_total > applied_limit:
        lines.append("")
        lines.append(f"Showing {applied_limit} of {valid_total} users.")

    return "\n".join(lines).strip(), alias_map


def _build_first_chunk_header_lines() -> List[str]:
    return ["👥 **Whitelisted Users**", *_build_activity_reminder().splitlines()]


def _fits_with_block(current_lines: List[str], block_lines: List[str], safe_limit: int) -> bool:
    return len("\n".join(current_lines + block_lines)) <= safe_limit


def _chunk_has_body(lines: List[str], header_len: int) -> bool:
    return len(lines) > header_len


def build_whitelist_users_chunks(
    entries: Iterable[Dict[str, Any]],
    meta_map: Dict[str, Any],
    summary_map: Dict[str, Any],
    format_summary: Callable[..., str],
    *,
    include_alias: bool,
    empty_text: str,
    safe_limit: int = 3800,
    continuation_header: str = "👥 **Whitelisted Users** (cont.)",
) -> Tuple[List[str], Dict[str, str], bool]:
    """Render whitelist user sections into Telegram-safe message chunks and aggregate alias mapping."""
    entries = list(entries or [])
    if not entries:
        return [empty_text], {}, False

    summary_map = summary_map or {}
    meta_map = meta_map or {}
    role_rows, alias_map, _valid_total, _applied_limit = _build_role_rows(
        entries,
        meta_map,
        summary_map,
        format_summary,
        include_alias=include_alias,
        limit=None,
    )
    total_rows = sum(len(rows) for rows in role_rows.values())
    if total_rows <= 0:
        return [empty_text], {}, False

    try:
        parsed_safe_limit = int(safe_limit)
    except Exception:
        parsed_safe_limit = 3800
    if parsed_safe_limit <= 0:
        parsed_safe_limit = 3800

    chunks: List[str] = []
    overflowed = False
    current_lines = _build_first_chunk_header_lines()
    current_header_len = len(current_lines)

    def _flush_current_chunk() -> None:
        nonlocal current_lines, current_header_len
        if _chunk_has_body(current_lines, current_header_len):
            chunks.append("\n".join(current_lines).strip())
        current_lines = [continuation_header]
        current_header_len = 1

    for role in ("developer", "admin", "user"):
        rows = role_rows.get(role) or []
        if not rows:
            continue
        role_started = False
        row_index = 0
        while row_index < len(rows):
            block_lines = [rows[row_index]]
            if not role_started:
                block_lines.insert(0, ROLE_SECTION_TITLES[role])
            if _fits_with_block(current_lines, block_lines, parsed_safe_limit):
                current_lines.extend(block_lines)
                role_started = True
                row_index += 1
                continue
            if _chunk_has_body(current_lines, current_header_len):
                _flush_current_chunk()
                continue
            overflowed = True
            current_lines.extend(block_lines)
            role_started = True
            row_index += 1
            _flush_current_chunk()

    if _chunk_has_body(current_lines, current_header_len):
        chunks.append("\n".join(current_lines).strip())

    if not chunks:
        chunks = [empty_text]
    return chunks, alias_map, overflowed
