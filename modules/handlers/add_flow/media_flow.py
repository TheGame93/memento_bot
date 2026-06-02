from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from modules import constants as C
from modules.shared.messages import edit_callback_message_media_aware as _edit_callback_message


async def show_photo_menu(update, context):
    """Show media options for adding, removing, or skipping alert photos."""
    payload = context.user_data.get("temp_alert", {})
    # Keep UX consistent even when only the local-path marker is present.
    has_photo = bool(payload.get("image_id") or payload.get("local_image_path"))
    text = "📸 **Upload Photo**\nSend a photo now or choose an option:"
    buttons = []
    if has_photo:
        buttons.append([InlineKeyboardButton("🗑️ Remove Photo", callback_data="photo_remove")])
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="photo_back")])

    if update.callback_query:
        await _edit_callback_message(
            update.callback_query,
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.MARKDOWN,
        )
    return C.GET_PHOTO


async def get_photo(update, context, show_settings_menu):
    """Store the uploaded photo identifier and return to settings."""
    photo = getattr(update.message, "photo", None)
    if photo:
        context.user_data.setdefault("temp_alert", {})["image_id"] = photo[-1].file_id
    return await show_settings_menu(update, context)


async def reject_document(update, context):
    """Reject document uploads and keep the flow on the photo step."""
    instructions = (
        "⚠️ **Invalid Format**\n\n"
        "I cannot accept documents or uncompressed pictures.\n"
        "Please send me a picture and ensure the **'Compress'** option is checked."
    )
    await update.message.reply_text(instructions, parse_mode=ParseMode.MARKDOWN)
    return C.GET_PHOTO


async def photo_back(update, context, show_settings_menu):
    """Return from the photo step to the settings dashboard."""
    if update.callback_query:
        await update.callback_query.answer()
    return await show_settings_menu(update, context)


async def remove_photo(update, context, show_settings_menu):
    """Remove staged photo fields and return to settings."""
    query = update.callback_query
    await query.answer()
    alert = context.user_data.get("temp_alert", {})
    if "image_id" in alert:
        del alert["image_id"]
    if "local_image_path" in alert:
        del alert["local_image_path"]
    return await show_settings_menu(update, context)
