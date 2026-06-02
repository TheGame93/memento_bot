"""Serve role-aware help pages and process help navigation callbacks."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from modules.shared.acting_as import (
    build_acting_as_banner,
    build_acting_as_payload,
    get_target_user_id,
)
from modules.shared.callback_codec import ensure_callback_fits, extract_callback_token
from modules.shared.runtime_context import get_runtime_storage

HELP_NEXT_PREFIX = "help_next_"
HELP_DONE_CB = "help_done"
HELP_NEXT_LABEL = "➡️ Next"
HELP_DONE_POPUP_TEXT = (
    "Now you know everything you need for start tracking your recurring alerts!"
)

HELP_INTRO_INTRO_TEXT = (
    "This is not a calendar! This is not an alarm clock!\n"
    "\n"
    "📌 <b>What This Bot Does</b>\n"
    "\n"
    "This bot is built to manage reminders for <b>recurring events</b>.\n"
    "Its purpose is to help you keep control of tasks, deadlines, and routines through timely notifications."
)

HELP_INTRO_USEIT_TEXT = (
    "🧭 <b>What You Can Use It For</b>\n"
    "\n"
    "Recurring payments, document expirations, maintenance tasks, health check reminders and birthdays.\n"
    "<b>Weekly</b>\n"
    "• Record overtime each week\n"
    "<b>Monthly</b>\n"
    "• Dental cleaning every 6 months\n"
    "• Car maintenance\n"
    "<b>One-Time</b>\n"
    "• ID card / Passport expiration\n"
    "• Expiration of a gift card\n"
    "<b>Custom time</b>\n"
    "• Water a plant every 5 days and another every 11 days\n"
    "• Feed you exotic pet every 40 days"
)

HELP_INTRO_ISNOT_TEXT = (
    "🚫 <b>What It Is Not</b>\n"
    "\n"
    "• This is NOT a calendar: NO month/week grid.\n"
    "• so DO NOT track your weekly meetings\n"
    "• DO NOT notify every 2 hours to drink water\n"
    "• Is NOT a good period tracker\n"
    "• DO NOT use for any kind of short-term timer that can set on the phone's alarm clock"
)

HELP_COMMANDS_TEXT = (
    "⚙️ <b>Main Commands</b>\n\n"
    "• /help - this guide\n"
    "• /alerts - recurring alerts\n"
    "• /birthdays - ...what do you think?\n"
    "• /tags - create and deletes tags\n"
    "• /cancel - stop current operation"
)

HELP_SYSTEM_COMMANDS_TEXT = (
    "🧰 <b>System Commands</b>\n\n"
    "• /status - show your account status\n"
    "• /settings - open your preferences"
)

HELP_ADMIN_TEXT = (
    "<b>Admin Info</b>\n\n"
    "Admin tools are focused on access control: reviewing incoming requests and managing whitelisted users.\n"
    "• /manage Open the management dashboard\n"
)

HELP_DEVELOPER_TEXT = (
    "<b>Developer Info</b>\n\n"
    "Your role includes all admin permissions plus developer controls, "
    "covering role management, acting-as sessions, and system export, import, and rollback operations.\n"
    "• Developer features are added to /manage\n"
)


def _help_sections_for_role(role):
    return [entry["text"] for entry in _help_section_entries_for_role(role)]


def _help_section_entries_for_role(role):
    role_name = str(role or "user").strip().lower()
    sections = [
        {"key": "intro_intro", "text": HELP_INTRO_INTRO_TEXT},
        {"key": "intro_useit", "text": HELP_INTRO_USEIT_TEXT},
        {"key": "intro_isnot", "text": HELP_INTRO_ISNOT_TEXT},
        {"key": "commands", "text": HELP_COMMANDS_TEXT},
        {"key": "system_commands", "text": HELP_SYSTEM_COMMANDS_TEXT},
    ]
    if role_name in {"admin", "developer"}:
        sections.append({"key": "admin", "text": HELP_ADMIN_TEXT})
    if role_name == "developer":
        sections.append({"key": "developer", "text": HELP_DEVELOPER_TEXT})
    return sections


def _help_next_callback_for_step(step_index, total_steps):
    # Step indices are 1-based for readability in callback payloads.
    if int(step_index) >= int(total_steps):
        return HELP_DONE_CB
    return f"{HELP_NEXT_PREFIX}{int(step_index) + 1}"


def _build_help_next_keyboard(step_index, total_steps):
    callback_data = _help_next_callback_for_step(step_index, total_steps)
    if not ensure_callback_fits(callback_data):
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(HELP_NEXT_LABEL, callback_data=callback_data)]]
    )


def _parse_help_next_step(callback_data):
    token = extract_callback_token(callback_data, HELP_NEXT_PREFIX)
    if not token:
        return None
    if not token.isdigit():
        return None
    return int(token)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the role-aware help guide by sending only the first section."""
    storage = get_runtime_storage(context)
    target_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)
    storage.log_user_event(target_id, "command_help", acting_payload)
    target = update.effective_message or update.message
    if not target:
        return
    role = storage.get_user_role(target_id) or "user"
    sections = _help_section_entries_for_role(role)
    if not sections:
        return
    banner = build_acting_as_banner(update, context, parse_mode="HTML")
    first_entry = sections[0]
    first_text = f"{banner}{first_entry['text']}"
    keyboard = _build_help_next_keyboard(step_index=1, total_steps=len(sections))
    await target.reply_text(first_text, parse_mode="HTML", reply_markup=keyboard)
    storage.log_user_event(
        target_id,
        "help_step_sent",
        {
            "source": "command",
            "step_index": 1,
            "step_key": first_entry["key"],
            "role": role,
            "is_final_step": len(sections) == 1,
            **acting_payload,
        },
    )


async def handle_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle paginated help callbacks and send the requested next section."""
    query = update.callback_query
    if not query:
        return

    callback_data = query.data or ""
    storage = get_runtime_storage(context)
    user_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)
    role = storage.get_user_role(user_id) or "user"
    sections = _help_section_entries_for_role(role)
    total_steps = len(sections)

    if callback_data == HELP_DONE_CB:
        await query.answer(HELP_DONE_POPUP_TEXT, show_alert=True)
        storage.log_user_event(
            user_id,
            "help_flow_completed_popup",
            {
                "role": role,
                "final_step_index": total_steps,
                **acting_payload,
            },
        )
        return

    next_step = _parse_help_next_step(callback_data)
    if next_step is None:
        storage.log_user_event(
            user_id,
            "help_callback_invalid",
            {
                "reason_code": "invalid_payload",
                "callback_data": callback_data,
                **acting_payload,
            },
        )
        await query.answer("⚠️ Invalid help action.", show_alert=True)
        return

    if next_step < 2 or next_step > total_steps:
        storage.log_user_event(
            user_id,
            "help_callback_invalid",
            {
                "reason_code": "step_out_of_scope",
                "requested_step_index": next_step,
                "total_steps": total_steps,
                "role": role,
                **acting_payload,
            },
        )
        await query.answer("⚠️ This help step is not available.", show_alert=True)
        return

    target_message = getattr(query, "message", None) or update.effective_message
    if not target_message:
        storage.log_user_event(
            user_id,
            "help_callback_invalid",
            {
                "reason_code": "stale_or_unavailable",
                "requested_step_index": next_step,
                "role": role,
                **acting_payload,
            },
        )
        await query.answer("⚠️ This help step is unavailable now.", show_alert=True)
        return

    storage.log_user_event(
        user_id,
        "help_next_pressed",
        {
            "current_step_index": next_step - 1,
            "next_step_index": next_step,
            "role": role,
            **acting_payload,
        },
    )
    await query.answer()

    section_entry = sections[next_step - 1]
    keyboard = _build_help_next_keyboard(step_index=next_step, total_steps=total_steps)
    await target_message.reply_text(
        section_entry["text"],
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    storage.log_user_event(
        user_id,
        "help_step_sent",
        {
            "source": "callback",
            "step_index": next_step,
            "step_key": section_entry["key"],
            "role": role,
            "is_final_step": next_step == total_steps,
            **acting_payload,
        },
    )
