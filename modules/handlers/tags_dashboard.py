import logging
from html import escape as html_escape
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from modules.tags_logic import extract_tag_name, parse_tag
from modules import constants as C
from modules.shared.callback_codec import (
    build_value_token_map,
    ensure_callback_fits,
    extract_callback_token,
    is_token_candidate,
)
from modules.shared.acting_as import (
    build_acting_as_banner,
    build_acting_as_payload,
    get_actor_user_id,
    get_target_user_id,
)
from modules.shared.runtime_context import get_runtime_storage

# Note: storage is imported inside functions to avoid circular imports 
# since mainbot imports this file.

logger = logging.getLogger(__name__)

TAG_DELETE_CB_PREFIX = "manage_tag_do_del_t"
TAG_CONFIRM_CB_PREFIX = "manage_tag_confirm_del_t"
TAG_EDIT_CB_PREFIX = "manage_tag_do_edit_t"


def _build_tag_token_map(tags):
    return build_value_token_map(sorted(tags or [], key=extract_tag_name))

async def tags_dashboard_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render the /tags dashboard with per-tag alert counts and Add/Edit/Delete action buttons."""
    storage = get_runtime_storage(context)
    actor_id = get_actor_user_id(update)
    user_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)
    context.user_data.pop("expecting_birthday_search", None)
    context.user_data.pop("expecting_alert_search", None)
    
    user_data = storage.get_all_alerts(user_id)
    if not user_data:
        storage.setup_user_space(user_id)
        user_data = storage.get_all_alerts(user_id)

    payload = {
        "source": "callback" if update.callback_query else "command",
    }
    payload.update(acting_payload)
    storage.log_user_event(user_id, "tags_dashboard_opened", payload)

    tags_list = user_data.get("tags", list(C.TAGS))
    if not isinstance(tags_list, list):
        tags_list = list(C.TAGS)
    alerts_stats = {tag: 0 for tag in tags_list}
    bdays_stats = {tag: 0 for tag in tags_list}
    untagged_alerts = 0
    untagged_bdays = 0

    for alert in user_data.get("alerts", []):
        is_bday = alert.get("type") == 6
        alert_tags = alert.get("tags", [])
        if not alert_tags:
            if is_bday:
                untagged_bdays += 1
            else:
                untagged_alerts += 1
            continue
        for t in alert_tags:
            if is_bday:
                if t not in bdays_stats:
                    bdays_stats[t] = 0
                    if t not in tags_list:
                        tags_list.append(t)
                bdays_stats[t] += 1
            else:
                if t not in alerts_stats:
                    alerts_stats[t] = 0
                    if t not in tags_list:
                        tags_list.append(t)
                alerts_stats[t] += 1

    tags_list.sort(key=extract_tag_name)

    banner = build_acting_as_banner(update, context, parse_mode="HTML")
    text = f"{banner}<b>🤖 Tag Management Dashboard</b>\n\n"
    text += "Use this menu to organize your alert categories.\n\n"
    text += "<b>Your Tags:</b>\n"
    
    if not tags_list:
        text += "<i>No tags defined yet.</i>\n"
    
    shown = 0
    for tag in tags_list:
        count = alerts_stats.get(tag, 0)
        bcount = bdays_stats.get(tag, 0)
        emoji, name = parse_tag(tag)
        line = f"• {emoji} {name}: <b>{count}</b> alerts, <b>{bcount}</b> bdays\n"
        if len(text) + len(line) > 3600:
            remaining = len(tags_list) - shown
            text += f"<i>… and {remaining} more tags</i>\n"
            break
        text += line
        shown += 1

    text += (
        f"Untagged: <b>{untagged_alerts}</b> alerts, "
        f"<b>{untagged_bdays}</b> bdays\n\n"
    )
    text += "<i>Choose an action:</i>"

    keyboard = [
        [
            InlineKeyboardButton("➕ Add", callback_data="manage_tag_prompt_add"),
            InlineKeyboardButton("✏️ Edit", callback_data="manage_tag_edit_list"),
            InlineKeyboardButton("🗑️ Delete", callback_data="manage_tag_del_list"),
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Handle both command call and callback return
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def show_delete_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, as_new_message=False):
    """Show tag deletion options and store callback token mappings."""
    storage = get_runtime_storage(context)
    actor_id = get_actor_user_id(update)
    user_id = get_target_user_id(update, context)
    tags = storage.get_user_tags(user_id)
    
    # Handle empty tag list
    if not tags:
        keyboard = [[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="manage_tag_back")]]
        banner = build_acting_as_banner(update, context, parse_mode="HTML")
        text = (
            f"{banner}"
            "<b>No tags to delete.</b>\n\n"
            "<i>Add some tags first using the Add button.</i>"
        )
        if as_new_message:
            await context.bot.send_message(
                chat_id=actor_id,
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
        else:
            await update.callback_query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
        return
    
    token_map = _build_tag_token_map(tags)
    context.user_data["tag_delete_token_map"] = token_map

    keyboard = []
    # We create a grid of 2 columns for the delete buttons
    row = []
    for token, tag in token_map.items():
        # Each button shows the full tag name with emoji
        callback_data = f"{TAG_DELETE_CB_PREFIX}{token}"
        if not ensure_callback_fits(callback_data):
            logger.warning(f"Skipping oversized delete-tag callback for tag: {tag}")
            continue
        row.append(InlineKeyboardButton(f"❌ {tag}", callback_data=callback_data))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="manage_tag_back")])
    
    banner = build_acting_as_banner(update, context, parse_mode="HTML")
    text = (
        f"{banner}"
        "<b>Select a tag to permanently delete:</b>\n"
        "<i>This will remove the category from all alerts.</i>"
    )
    if as_new_message:
        await context.bot.send_message(
            chat_id=actor_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
    else:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

async def show_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, as_new_message=False):
    """Show the tag list as selectable buttons for rename; mirrors show_delete_menu."""
    storage = get_runtime_storage(context)
    actor_id = get_actor_user_id(update)
    user_id = get_target_user_id(update, context)
    tags = storage.get_user_tags(user_id)

    if not tags:
        keyboard = [[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="manage_tag_back")]]
        banner = build_acting_as_banner(update, context, parse_mode="HTML")
        text = (
            f"{banner}"
            "<b>No tags to edit.</b>\n\n"
            "<i>Add some tags first using the Add button.</i>"
        )
        if as_new_message:
            await context.bot.send_message(
                chat_id=actor_id,
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
        else:
            await update.callback_query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
        return

    token_map = _build_tag_token_map(tags)
    context.user_data["tag_edit_token_map"] = token_map

    keyboard = []
    row = []
    for token, tag in token_map.items():
        callback_data = f"{TAG_EDIT_CB_PREFIX}{token}"
        if not ensure_callback_fits(callback_data):
            logger.warning(f"Skipping oversized edit-tag callback for tag: {tag}")
            continue
        row.append(InlineKeyboardButton(f"✏️ {tag}", callback_data=callback_data))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="manage_tag_back")])

    banner = build_acting_as_banner(update, context, parse_mode="HTML")
    text = (
        f"{banner}"
        "<b>Select a tag to rename:</b>"
    )
    if as_new_message:
        await context.bot.send_message(
            chat_id=actor_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
    else:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )


async def handle_tag_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dispatch all manage_tag_* callback actions: add, edit, delete, and navigation."""
    storage = get_runtime_storage(context)
    query = update.callback_query
    await query.answer()
    actor_id = get_actor_user_id(update)
    user_id = get_target_user_id(update, context)
    data = query.data

    logger.info(f"Tag Callback received: {data}")

    if data == "manage_tag_back":
        await tags_dashboard_start(update, context)

    elif data == "manage_tag_del_list":
        try:
            await query.message.delete()
        except Exception:
            pass
        await show_delete_menu(update, context, as_new_message=True)

    elif data == "manage_tag_edit_list":
        try:
            await query.message.delete()
        except Exception:
            pass
        await show_edit_menu(update, context, as_new_message=True)

    elif data.startswith("manage_tag_do_edit_"):
        token_map = _build_tag_token_map(storage.get_user_tags(user_id))
        context.user_data["tag_edit_token_map"] = token_map
        token = extract_callback_token(data, TAG_EDIT_CB_PREFIX)
        if token and is_token_candidate(token):
            old_tag = token_map.get(token)
        else:
            old_tag = None
        if not old_tag:
            await query.message.reply_text("⚠️ This tag action expired. Open /tags again.")
            return
        try:
            await query.message.delete()
        except Exception:
            pass
        context.user_data["expecting_tag_rename"] = True
        context.user_data["tag_rename_old"] = old_tag
        await context.bot.send_message(
            chat_id=actor_id,
            text=f"✏️ <b>Rename tag:</b> {html_escape(old_tag)}\n\nType the new name (e.g., 🔥 Spicy):",
            parse_mode="HTML"
        )

    elif data == "manage_tag_prompt_add":
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=actor_id,
            text="➕ <b>Add New Tag</b>\n\nPlease type the name of the new tag (e.g., 🍕 Food):",
            parse_mode="HTML"
        )
        context.user_data['expecting_tag_name'] = True
        logger.info(f"User {user_id} is now in expecting_tag_name mode")

    elif data.startswith("manage_tag_do_del_"):
        # Step 1: Show confirmation prompt (don't delete yet)
        token_map = _build_tag_token_map(storage.get_user_tags(user_id))
        context.user_data["tag_delete_token_map"] = token_map
        token = extract_callback_token(data, TAG_DELETE_CB_PREFIX)
        if token and is_token_candidate(token):
            tag_to_del = token_map.get(token)
        else:
            # Legacy fallback: full tag directly in callback payload.
            tag_to_del = data.replace("manage_tag_do_del_", "", 1)
        if not tag_to_del:
            await query.message.reply_text("⚠️ This tag action expired. Open /tags again.")
            return

        # Count how many alerts use this tag
        user_data = storage.get_all_alerts(user_id)
        alerts = user_data.get("alerts", [])
        affected_count = sum(1 for a in alerts if tag_to_del in a.get("tags", []))
        
        if affected_count > 0:
            warning = f"\n\n⚠️ <b>{affected_count}</b> alert(s) use this tag."
        else:
            warning = ""
        
        confirm_token = next((k for k, v in token_map.items() if v == tag_to_del), None)
        if confirm_token:
            confirm_callback = f"{TAG_CONFIRM_CB_PREFIX}{confirm_token}"
        else:
            confirm_callback = f"manage_tag_confirm_del_{tag_to_del}"

        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, Delete", callback_data=confirm_callback),
                InlineKeyboardButton("❌ Cancel", callback_data="manage_tag_cancel_del")
            ]
        ]
        
        await query.edit_message_text(
            f"<b>Delete tag '{tag_to_del}'?</b>{warning}\n\n"
            "<i>This will remove the tag from all alerts.</i>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

    elif data.startswith("manage_tag_confirm_del_"):
        # Step 2: User confirmed, now actually delete
        token_map = _build_tag_token_map(storage.get_user_tags(user_id))
        token = extract_callback_token(data, TAG_CONFIRM_CB_PREFIX)
        if token and is_token_candidate(token):
            tag_to_del = token_map.get(token)
        else:
            # Legacy fallback: full tag directly in callback payload.
            tag_to_del = data.replace("manage_tag_confirm_del_", "", 1)
        if not tag_to_del:
            await query.message.reply_text("⚠️ This tag action expired. Open /tags again.")
            return
        storage.delete_user_tag(user_id, tag_to_del)
        await query.message.reply_text(f"✅ Tag '{tag_to_del}' removed.")
        await tags_dashboard_start(update, context)

    elif data == "manage_tag_cancel_del":
        # User cancelled, go back to delete menu
        await show_delete_menu(update, context)
