"""Build mail-backup texts and keyboards."""

import html
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from modules.backup_core.email_backup import (
    describe_monthly_backup_schedule,
    describe_monthly_reminder_schedule,
    estimate_email_backup_size_bytes,
    normalize_email_address,
)


def _format_last_email_sent(value):
    if not value:
        return "Never"
    return value


def _normalized_email_address(prefs):
    value = (prefs or {}).get("email_address")
    return normalize_email_address(value)


def _mail_reminder_state(prefs):
    prefs = prefs or {}
    email_address = _normalized_email_address(prefs)
    backup_enabled = bool(prefs.get("email_enabled"))
    applicable = (not bool(email_address)) and (not backup_enabled)
    disabled_flag = bool(prefs.get("email_reminder_disabled"))
    enabled = applicable and (not disabled_flag)
    return {
        "enabled": enabled,
        "disabled_flag": disabled_flag,
        "applicable": applicable,
    }


def build_mail_set_prompt_message(prefs):
    """Build the prompt message for setting the backup email address."""
    email_address = _normalized_email_address(prefs)
    email_line = email_address or "Not set"
    return (
        f"Current email address: {email_line}\n"
        "Send your new email address now."
    )


def build_mail_set_prompt_keyboard(prefs=None):
    """
    Builds the Set Mail prompt keyboard.

    Prompt safety behavior:
    - Show clear only when a normalized email exists in prefs.
    - If prefs are absent, default to hide clear (cancel-only prompt).
    """
    show_clear = bool(_normalized_email_address(prefs)) if prefs is not None else False

    rows = []
    if show_clear:
        rows.append([InlineKeyboardButton("🗑️ Clear Email Address", callback_data="settings_mail_clear")])
    rows.append([InlineKeyboardButton("❌ Cancel Operation", callback_data="settings_mail_set_cancel")])
    return InlineKeyboardMarkup(rows)


def build_mail_backup_keyboard(prefs=None, smtp_available=True):
    """Build mail-backup controls based on email, reminder, and service state."""
    prefs = prefs or {}
    reminder = _mail_reminder_state(prefs)
    email_set = bool(_normalized_email_address(prefs))

    rows = []
    if reminder["applicable"]:
        if reminder["enabled"]:
            toggle_label = "⛔️ Disable reminder to set the mail"
            toggle_callback = "settings_mail_disable"
        else:
            toggle_label = "✅ Enable reminder to set the mail"
            toggle_callback = "settings_mail_enable"
        rows.append([InlineKeyboardButton(toggle_label, callback_data=toggle_callback)])

    row_two = [InlineKeyboardButton("✍️ Set Mail", callback_data="settings_mail_set")]
    if email_set and smtp_available:
        row_two.append(InlineKeyboardButton("📤 Send Backup Now", callback_data="settings_mail_send"))
    rows.append(row_two)

    if smtp_available:
        if prefs.get("email_enabled"):
            backup_toggle_label = "⛔️ Disable Mail Backup"
        else:
            backup_toggle_label = "✅ Enable Mail Backup"
        rows.append([InlineKeyboardButton(backup_toggle_label, callback_data="settings_mail_toggle")])

    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="settings_back")])

    return InlineKeyboardMarkup(rows)


def build_mail_backup_reminder_keyboard(prefs=None):
    """Build quick actions for the backup-email reminder prompt."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Go to backup-via-mail settings", callback_data="settings_mail")],
        [InlineKeyboardButton("🚫 I don't want to backup my data via email", callback_data="settings_mail_disable")],
    ])


def build_mail_backup_reminder_message(prefs):
    """Build the reminder message shown when backup email is unset."""
    prefs = prefs or {}
    last_sent = _format_last_email_sent(prefs.get("last_email_sent"))
    enabled = bool(prefs.get("email_enabled"))
    backup_label = "Enabled ✅" if enabled else "Disabled ⛔️"
    last_sent_line = html.escape(str(last_sent))
    return (
        "✉️ <b>Mail Backup</b>\n\n"
        "It is possible to receive monthly backup of your personal data. "
        "It useful for migrating to another reminder service or to recover you data "
        "if this bot will permanently stop.\n\n"
        f"Backup via Mail: <b>{backup_label}</b>\n"
        "Email: Not set\n"
        f"Last sent: {last_sent_line}\n\n"
        "Go to the bot settings to set your email or disable this reminder:"
    )


def _get_backup_size_bytes(storage, user_id):
    try:
        return estimate_email_backup_size_bytes(storage, user_id)
    except Exception:
        return None


def _format_backup_size_label(size_bytes):
    if size_bytes is None:
        return "n/a"
    try:
        mb_value = float(size_bytes) / (1024 * 1024)
    except Exception:
        return "n/a"
    return f"{mb_value:.2f} MB"


def build_mail_backup_status(prefs, *, size_bytes=None):
    """Build mail-backup status text and action keyboard."""
    from modules.backup_core.email_backup import smtp_service_status
    smtp_available = smtp_service_status().get("configured", False)

    prefs = prefs or {}
    enabled = bool(prefs.get("email_enabled"))
    reminder = _mail_reminder_state(prefs)
    email_address = _normalized_email_address(prefs)
    last_sent = _format_last_email_sent(prefs.get("last_email_sent"))

    unavailable_block = ""
    if not smtp_available:
        unavailable_block = (
            "⚠️ <b>Service unavailable</b>\n"
            "The email backup service is not configured on this server.\n"
            "Contact the bot administrator for assistance.\n\n"
        )

    backup_label = "Enabled ✅" if enabled else "Disabled ⛔️"
    email_line = html.escape(email_address) if email_address else "Not set"
    last_sent_line = html.escape(str(last_sent))
    reminder_block = ""
    if reminder["applicable"]:
        reminder_label = "Enabled ✅" if reminder["enabled"] else "Disabled ⛔️"
        reminder_schedule_line = ""
        if reminder["enabled"]:
            reminder_schedule_line = (
                f"When: <b>{html.escape(describe_monthly_reminder_schedule())}</b>\n"
            )
        reminder_block = (
            "Reminder to setup the mail: "
            f"<b>{reminder_label}</b>\n"
            f"{reminder_schedule_line}"
        )
    schedule_line = ""
    if enabled:
        recurring = html.escape(describe_monthly_backup_schedule())
        schedule_line = f"\nRecurring backup: <b>{recurring}</b>"
    size_label = _format_backup_size_label(size_bytes)

    message = (
        "✉️ <b>Mail Backup</b>\n\n"
        f"{unavailable_block}"
        "It is possible to receive monthly backup of your personal data. "
        "It useful for migrating to another reminder service or to recover you data "
        "if this bot will permanently stop.\n\n"
        f"{reminder_block}"
        f"\n"
        f"Backup via mail: <b>{backup_label}</b>\n"
        f"Email: {email_line}"
        f"{schedule_line}\n"
        f"\n"
        f"Size of data to backup: {size_label}\n"
        f"Last backup sent: {last_sent_line}"
    )
    if email_address:
        message = (
            f"{message}\n\nIf you don't find the backup email,\n"
            "check the SPAM folder!!"
        )
    keyboard = build_mail_backup_keyboard(prefs, smtp_available=smtp_available)
    return message, keyboard


_BACKUP_SENT_REASON_LABELS = {
    "manual": "Manual send",
    "monthly": "Scheduled (monthly)",
    "startup_catchup": "Startup catch-up",
}


def build_backup_email_sent_notification(from_email, to_email, size_bytes, reason, sent_at_iso):
    """Build the plain HTML text notifying the user of a successful backup email dispatch.

    Returns a message string ready for `parse_mode="HTML"` with no inline keyboard.
    Includes from/to addresses, backup size, human-readable trigger reason, and
    send timestamp formatted as YYYY-MM-DD HH:MM (server time).
    """
    reason_label = _BACKUP_SENT_REASON_LABELS.get(reason) or html.escape(str(reason or ""))
    size_label = _format_backup_size_label(size_bytes)
    try:
        sent_dt = datetime.fromisoformat(str(sent_at_iso))
        sent_label = sent_dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        sent_label = html.escape(str(sent_at_iso or ""))
    return "\n".join([
        "📧 <b>Backup email sent</b>",
        "",
        f"From: {html.escape(str(from_email or ''))}",
        f"To: {html.escape(str(to_email or ''))}",
        f"Size: {size_label}",
        f"Reason: {reason_label}",
        f"Sent at: {sent_label}",
    ])
