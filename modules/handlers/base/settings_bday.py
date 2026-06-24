"""Build birthday-settings texts and keyboards."""

import html
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from modules import constants as C


def normalize_time_input(raw):
    """Normalize HH:MM text into zero-padded 24-hour format."""
    text = (raw or "").strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def _birthday_default_time_from_prefs(prefs):
    prefs = prefs or {}
    candidate = normalize_time_input(prefs.get("birthday_default_time"))
    return candidate or C.BIRTHDAY_DEFAULT_TIME


def _birthday_evening_time_from_prefs(prefs):
    prefs = prefs or {}
    candidate = normalize_time_input(prefs.get("birthday_evening_before_time"))
    return candidate or C.BIRTHDAY_EVENING_BEFORE_DEFAULT_TIME


def build_birthday_time_keyboard():
    """Build the birthdays settings keyboard for time and bulk actions."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✍️ Set default time", callback_data="settings_birthday_time_set"),
            InlineKeyboardButton("↺ Reset to default", callback_data="settings_birthday_time_reset"),
        ],
        [
            InlineKeyboardButton("🌆 Set evening-before time", callback_data="settings_birthday_evening_time_set"),
            InlineKeyboardButton("↺ Reset to default", callback_data="settings_birthday_evening_time_reset"),
        ],
        [
            InlineKeyboardButton("📤 Bulk Bday Export", callback_data="settings_bday_bulk_export"),
            InlineKeyboardButton("📥 Bulk Bday Import", callback_data="settings_bday_bulk_import"),
        ],
        [InlineKeyboardButton("🔮 Zodiac", callback_data="settings_bday_zodiac")],
        [InlineKeyboardButton("⬅️ Back", callback_data="settings_back")],
    ])


def build_birthday_bulk_export_mode_keyboard():
    """Build the bulk birthday export mode selection keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Everything", callback_data="settings_bday_bulk_export_everything"),
            InlineKeyboardButton("By tag", callback_data="settings_bday_bulk_export_bytag"),
        ],
        [InlineKeyboardButton("⬅️ Back to Birthdays", callback_data="settings_bdays")],
    ])


def build_birthday_bulk_export_mode_status():
    """Build bulk birthday export status text and keyboard."""
    message = (
        "🎂 <b>Bulk Birthday Export</b>\n\n"
        "Choose how to export your birthdays:\n"
        "• <b>Everything</b>: one global export sorted by name\n"
        "• <b>By tag</b>: one block per tag (plus untagged when present)\n\n"
        "Export format:\n"
        "<code>Name :: DD/MM[/YYYY] :: Tag</code>"
    )
    return message, build_birthday_bulk_export_mode_keyboard()


def build_birthday_bulk_import_decision_keyboard():
    """Build the decision keyboard for birthday bulk import review."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Continue", callback_data="settings_bday_bulk_import_continue")],
        [InlineKeyboardButton("Edit Message", callback_data="settings_bday_bulk_import_edit")],
        [InlineKeyboardButton("Go to /tags", callback_data="settings_bday_bulk_import_gototags")],
    ])


def build_birthday_bulk_import_prompt_keyboard():
    """Build the birthday bulk import prompt keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back to Birthdays", callback_data="settings_bdays")],
    ])


def build_birthday_zodiac_keyboard():
    """Build the birthday zodiac mode selection keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Disabled", callback_data="settings_bday_zodiac_none")],
        [InlineKeyboardButton("♈ Western", callback_data="settings_bday_zodiac_west")],
        [InlineKeyboardButton("🐉 Eastern", callback_data="settings_bday_zodiac_east")],
        [InlineKeyboardButton("✨ Both", callback_data="settings_bday_zodiac_both")],
        [InlineKeyboardButton("⬅️ Back to Birthdays", callback_data="settings_bdays")],
    ])


def build_birthday_zodiac_status(prefs):
    """Build zodiac settings status text and keyboard for birthdays."""
    mode = (prefs or {}).get("birthday_zodiac_mode", C.BIRTHDAY_ZODIAC_MODE_NONE)
    mode_labels = {
        C.BIRTHDAY_ZODIAC_MODE_NONE: "❌ Disabled",
        C.BIRTHDAY_ZODIAC_MODE_WESTERN: "♈ Western",
        C.BIRTHDAY_ZODIAC_MODE_EASTERN: "🐉 Eastern",
        C.BIRTHDAY_ZODIAC_MODE_BOTH: "✨ Both",
    }
    current = mode_labels.get(mode, "❌ Disabled")
    message = (
        "🔮 <b>Zodiac Settings</b>\n\n"
        f"Current mode: <b>{current}</b>\n\n"
        "If enabled, zodiac sign info is shown in birthday reminders "
        "and birthday details.\n"
        "<i>Eastern zodiac requires the birth year.</i>"
    )
    return message, build_birthday_zodiac_keyboard()


_ZODIAC_MODE_MAP = {
    "settings_bday_zodiac_none": C.BIRTHDAY_ZODIAC_MODE_NONE,
    "settings_bday_zodiac_west": C.BIRTHDAY_ZODIAC_MODE_WESTERN,
    "settings_bday_zodiac_east": C.BIRTHDAY_ZODIAC_MODE_EASTERN,
    "settings_bday_zodiac_both": C.BIRTHDAY_ZODIAC_MODE_BOTH,
}


def build_birthday_time_status(prefs):
    """Build birthday time settings status text and keyboard."""
    default_time = _birthday_default_time_from_prefs(prefs)
    evening_time = _birthday_evening_time_from_prefs(prefs)
    message = (
        "🎂 <b>Birthdays</b>\n\n"
        f"Default birthday time: <code>{html.escape(default_time)}</code>\n"
        f"Evening-before pre-alert time: <code>{html.escape(evening_time)}</code>\n\n"
        "Default birthday time is used for new birthdays and updates existing ones.\n"
        "Evening-before time is used by the dedicated birthday pre-alert option.\n"
        "You can also export or import birthdays in bulk from this panel."
    )
    return message, build_birthday_time_keyboard()
