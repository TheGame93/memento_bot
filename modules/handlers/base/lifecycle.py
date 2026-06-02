"""Handle generic flow lifecycle commands."""

from telegram import ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes, ConversationHandler

from modules.shared.acting_as import build_acting_as_payload, get_actor_user_id
from modules.shared.context_cleanup import clear_transient_context, has_transient_context
from modules.shared.runtime_context import get_runtime_storage


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exit active transient flows, force-end orphaned conversations for this user, and remove timezone-share UI when needed."""
    expecting_timezone_location = bool(context.user_data.get("expecting_timezone_location"))
    transient_was_active = has_transient_context(context.user_data)
    from modules.handlers.base.conversation_fallbacks import end_registered_conversations

    ended_count = end_registered_conversations(update)
    was_active = transient_was_active or ended_count > 0
    clear_transient_context(context.user_data, include_navigation=True)
    storage = get_runtime_storage(context)
    actor_id = get_actor_user_id(update)
    payload = build_acting_as_payload(update, context)
    payload["was_active"] = was_active
    storage.log_user_event(actor_id, "command_cancel", payload)
    reply_kwargs = {}
    if expecting_timezone_location:
        reply_kwargs["reply_markup"] = ReplyKeyboardRemove()
    target = update.effective_message or update.message
    if was_active:
        await target.reply_text("❌ Operation cancelled. Returning to idle state.", **reply_kwargs)
    else:
        await target.reply_text("Nothing to cancel, you already are in idle state.", **reply_kwargs)
    return ConversationHandler.END
