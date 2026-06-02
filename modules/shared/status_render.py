from datetime import datetime

from modules.timezone_utils import format_tz_offset
from modules.backup_core.email_backup import normalize_email_address
from modules.shared.markdown_utils import md_escape as _md_escape
from modules.shared.user_identity import format_user_label

VALID_STATUS_ROLES = {"user", "admin", "developer"}


def format_meta_timestamp(value, tz):
    """Format stored metadata timestamps for status output."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except Exception:
        return str(value)
    if tz is None:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    if dt.tzinfo is None:
        aware = dt.replace(tzinfo=tz)
    else:
        aware = dt.astimezone(tz)
    tz_name = getattr(tz, "key", None) or str(tz)
    offset = format_tz_offset(aware, tz)
    return f"{aware.strftime('%Y-%m-%d %H:%M:%S')} ({tz_name}, {offset})"


def _format_meta_value(value):
    if not value:
        return "`n/a`"
    return f"`{value}`"


def _format_username(value):
    if not value:
        return "`n/a`"
    text = str(value).strip()
    if not text:
        return "`n/a`"
    if not text.startswith("@"):
        text = f"@{text}"
    return f"`{text}`"


def _normalize_email_address(value):
    return normalize_email_address(value)


def _format_backup_email(value):
    email = _normalize_email_address(value)
    if not email:
        return "`Not set`"
    return f"`{email}`"


def _format_backup_last_sent(value):
    if not value:
        return "`Never`"
    return f"`{value}`"


def _format_identity_label(user_id, user_meta):
    meta = user_meta or {}
    return format_user_label(
        user_id,
        meta.get("username"),
        meta.get("display_name"),
        custom_name=meta.get("custom_name"),
        label_order=meta.get("label_order"),
        escape_markdown=True,
    )


def _as_non_negative_int(value, default=0):
    try:
        parsed = int(value)
    except Exception:
        return default
    if parsed < 0:
        return default
    return parsed


def _format_bytes(value):
    size = float(_as_non_negative_int(value, 0))
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{int(size)} B"


def _scoped_line(text, scope, show_debug_labels):
    if not text:
        return text
    if not show_debug_labels:
        return text
    return f"({scope}){text}"


def _is_scoped_blank(line):
    return line in {"", "(U)", "(A)", "(D)"}


def _normalize_viewer_role(role):
    text = str(role).strip().lower() if role is not None else ""
    if text in VALID_STATUS_ROLES:
        return text
    return "user"


def _normalize_subject_role(role):
    text = str(role).strip().lower() if role is not None else ""
    if text in VALID_STATUS_ROLES:
        return text
    return "unknown"


def build_status_message(
    *,
    viewer_role,
    subject_role,
    server_line,
    user_time_line,
    system_metrics,
    counts,
    log_maintenance=None,
    user_id,
    user_meta,
    user_stats,
    backup_prefs=None,
    degraded,
    show_debug_labels=False,
    email_service=None,
):
    """Build the role-scoped `/status` message with system and user sections."""
    user_meta = user_meta or {}
    viewer_role = _normalize_viewer_role(viewer_role)
    subject_role = _normalize_subject_role(subject_role)
    is_admin = viewer_role in {"admin", "developer"}
    is_dev = viewer_role == "developer"
    separator = "━━━━━━━━━━━━━━"

    lines = []

    def _add(scope, text):
        lines.append(_scoped_line(text, scope, show_debug_labels))

    def _blank(scope="U"):
        marker = f"({scope})" if show_debug_labels else ""
        if lines and _is_scoped_blank(lines[-1]):
            return
        lines.append(marker)

    _add("U", "🖥️ **System Status**")
    _add("U", separator)
    _add("U", f"🕒 **Server Time:** `{server_line}`")

    if user_time_line:
        _add("U", f"🕓 **User Time:** `{user_time_line}`")

    if is_dev:
        _add("D", f"⏱️ **Uptime:** `{system_metrics.get('uptime')}`")
        _add("D", f"🧠 **Memory:** `{system_metrics.get('memory')}`")
        _add(
            "D",
            f"📡 **API degraded (global):** {degraded.get('global_icon')} | "
            f" failures `{degraded.get('global_failures')}` / "
            f"`{degraded.get('global_threshold')}` in `{degraded.get('window_seconds')}s`",
        )

        _blank("D")
        maintenance = log_maintenance or {}
        _add("D", "🧹 **Log maintenance**")
        _add("D", f"📝 **Total bot log size:** `{system_metrics.get('bot_log_size')}`")
        _add("D", f"📝 **Total user log size:** `{system_metrics.get('user_log_size')}`")
        _add(
            "D",
            f"🕒 **Last run:** `{maintenance.get('last_run_ts') or 'n/a'}` "
            f"(`{maintenance.get('last_result') or 'n/a'}`)",
        )
        _add("D", f"📏 **Log cap:** `{_format_bytes(maintenance.get('last_limit_bytes'))}`")
        _add(
            "D",
            f"🗑️ **Freed bytes:** last `{_format_bytes(maintenance.get('last_freed_bytes'))}` / "
            f"total `{_format_bytes(maintenance.get('total_freed_bytes'))}`",
        )
        _add(
            "D",
            f"🧺 **Rotated deleted:** last `{_as_non_negative_int(maintenance.get('last_deleted_rotated'))}` / "
            f"total `{_as_non_negative_int(maintenance.get('total_deleted_rotated'))}`",
        )
        _add(
            "D",
            f"✂️ **Current logs truncated:** last "
            f"`{_as_non_negative_int(maintenance.get('last_truncated_current'))}` / "
            f"total `{_as_non_negative_int(maintenance.get('total_truncated_current'))}`",
        )

        _blank("D")
        if email_service is not None:
            configured = bool(email_service.get("configured"))
            svc_label = "Configured ✅" if configured else "Disabled ⛔️"
            _add("D", f"📧 **Email backup service:** {svc_label}")
            raw_from = email_service.get("from_addr")
            if configured and raw_from:
                from_label = f"`{_md_escape(str(raw_from))}`"
                _add("D", f"🤖 **Bot mail:** {from_label}")
            active_count = email_service.get("active_count", 0)
            _add("D", f"📨 **Email backup active users:** `{active_count}`")

    if is_admin:
        _blank("A")
        _add("A", f"👥 **# of users:** `{counts.get('users')}`")
        _add("A", f"🛡️ **# of admins:** `{counts.get('admins')}`")
        if is_dev:
            _add("D", f"🧑‍💻 **# of developers:** `{counts.get('developers')}`")

    _blank("U")
    _add("U", "👤 **User Status**")
    _add("U", separator)
    identity_label = _format_identity_label(user_id, user_meta)
    if is_admin:
        _add("A", f"🏷️ **Active Label:** {identity_label}")
        _add("A", f"🧩 **Custom name:** {_format_meta_value(user_meta.get('custom_name'))}")
    _add("U", f"👤 **Username:** {_format_username(user_meta.get('username'))}")
    _add("U", f"🧾 **Full name:** {_format_meta_value(user_meta.get('display_name'))}")
    _add("U", f"🆔 **User ID:** `{user_id}` (role: `{subject_role}`)")

    if is_admin:
        first_start = user_meta.get("first_start")
        last_seen = user_meta.get("last_seen")
        if first_start:
            _add("A", f"🟢 **First /start:** {_format_meta_value(first_start)}")
        if last_seen:
            _add("A", f"🕒 **Last active:** {_format_meta_value(last_seen)}")

    _blank("U")
    _add("U", f"📂 **Folder data size:** `{user_stats.get('total_space')}`")
    if is_admin:
        _add("A", f"📄 **Data (.json):** `{user_stats.get('data_json')}`")
        _add("A", f"📄 **Data (.json.bak):** `{user_stats.get('data_json_bak')}`")
    _add("U", f"🖼️ **Data (img):** `{user_stats.get('images')}`")
    if is_dev:
        _add("D", f"📝 **Log size:** `{user_stats.get('logs')}`")

    _blank("U")
    if is_dev:
        _add("D", f"💾 **Backup size:** `{user_stats.get('backups')}`")
    backup_prefs = backup_prefs or {}
    backup_enabled = bool(backup_prefs.get("email_enabled"))
    backup_status = "Enabled ✅" if backup_enabled else "Disabled ⛔️"
    backup_email = _format_backup_email(backup_prefs.get("email_address"))
    backup_last = _format_backup_last_sent(backup_prefs.get("last_email_sent"))
    _add("U", f"✉️ **Backup via mail:** {backup_status}")
    _add("U", f"📧 **Email:** {backup_email}")
    _add("U", f"📤 **Last backup sent:** {backup_last}")

    _blank("U")
    _add(
        "U",
        f"🔔 **# of alerts:** `{user_stats.get('alerts_count')}` | 🟢 `{user_stats.get('alerts_active')}`",
    )
    _add("U", f"🎂 **# of birthdays:** `{user_stats.get('birthdays_count')}`")
    _add("U", f"🏷️ **# of tags:** `{user_stats.get('tags_count')}`")
    if is_dev:
        _blank("D")
        _add(
            "D",
            f"📡 **API degraded:** {degraded.get('user_icon')} | "
            f" failures `{degraded.get('user_failures')}` / "
            f"`{degraded.get('user_threshold')}` in `{degraded.get('window_seconds')}s`",
        )
    _add("U", separator)

    return "\n".join(lines)
