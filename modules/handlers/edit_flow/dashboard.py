"""Edit-flow dashboard helpers (keyboard/text scaffolding)."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from modules import constants as C
from modules.handlers.add_flow.summary_flow import (
    format_additional_info,
    format_interval,
    format_photo_choice,
    format_pre_alerts,
    format_repetition,
)
from modules.shared.markdown_utils import md_escape


def build_edit_dashboard_keyboard(alert_type):
    """Build the edit-dashboard keyboard with direct same-type schedule edit actions."""
    keyboard = [
        [InlineKeyboardButton("Change name", callback_data="ed_name")],
    ]

    if alert_type == 6:
        keyboard.append([InlineKeyboardButton("Change birthday date", callback_data="ed_bday_date")])
    else:
        keyboard.append([InlineKeyboardButton("Edit schedule", callback_data="ed_schedule")])

    if alert_type != 6:
        keyboard.append([InlineKeyboardButton("Change type", callback_data="ed_change_type")])

    if alert_type in [1, 2, 3, 4, 7]:
        keyboard.append([
            InlineKeyboardButton("Set interval", callback_data="ed_interval"),
            InlineKeyboardButton("Set time", callback_data="ed_time"),
        ])
    elif alert_type == 5:
        keyboard.append([InlineKeyboardButton("Set time", callback_data="ed_time")])

    if alert_type in C.REPETITION_SUPPORTED_TYPES:
        keyboard.extend([
            [
                InlineKeyboardButton("Set pre-alert", callback_data="ed_pre"),
                InlineKeyboardButton("Set repetition", callback_data="ed_repetition"),
            ],
            [
                InlineKeyboardButton("Set picture", callback_data="ed_photo"),
                InlineKeyboardButton("Set additional info", callback_data="ed_info"),
            ],
            [InlineKeyboardButton("Manage tags", callback_data="ed_tags")],
            [InlineKeyboardButton("✅ DONE", callback_data="ed_done")],
        ])
    else:
        keyboard.extend([
            [
                InlineKeyboardButton("Set pre-alert", callback_data="ed_pre"),
                InlineKeyboardButton("Set picture", callback_data="ed_photo"),
            ],
            [InlineKeyboardButton("Set additional info", callback_data="ed_info")],
            [InlineKeyboardButton("Manage tags", callback_data="ed_tags")],
            [InlineKeyboardButton("✅ DONE", callback_data="ed_done")],
        ])
    return InlineKeyboardMarkup(keyboard)


def format_edit_dashboard_text(temp_alert, *, user_prefs=None):
    """Build edit-dashboard summary text with resolved pre-alert labels when schedule context exists."""
    data = temp_alert or {}
    schedule = data.get("schedule") or {}
    alert_type = data.get("type")
    is_birthday = alert_type == 6

    title = md_escape(data.get("title") or "-")
    type_name = md_escape(data.get("type_name") or "Unknown")
    pre_alerts = md_escape(format_pre_alerts(data, user_prefs=user_prefs))
    photo = md_escape(format_photo_choice(data))
    additional = md_escape(format_additional_info(data))
    tags = data.get("tags") or []
    tags_text = md_escape(", ".join(str(tag) for tag in tags)) if tags else "None"

    lines = [
        "✏️ **Edit Birthday**" if is_birthday else "✏️ **Edit Alert**",
        "",
        f"• Name: {title}",
        f"• Type: {type_name}",
    ]

    if is_birthday:
        bday_date = md_escape(schedule.get("date") or "-")
        birth_year = data.get("birth_year")
        birth_year_text = md_escape(str(birth_year)) if birth_year is not None else "not set"
        lines.append(f"• Birthday date: {bday_date}")
        lines.append(f"• Birth year: {birth_year_text}")
    else:
        interval = md_escape(format_interval(data))
        time_value = md_escape(schedule.get("time") or "10:00")
        lines.append(f"• Interval: {interval}")
        lines.append(f"• Time: {time_value}")
        if alert_type in C.REPETITION_SUPPORTED_TYPES:
            repetition = md_escape(format_repetition(data))
            lines.append(f"• Repetition: {repetition}")

    lines.extend([
        f"• Pre-alerts: {pre_alerts}",
        f"• Picture: {photo}",
        f"• Additional info: {additional}",
        f"• Tags: {tags_text}",
        "",
        "Choose what to change:",
    ])
    return "\n".join(lines)
