def ensure_add_flow_tracker(context):
    """Ensure add-flow message tracking storage exists in user context."""
    context.user_data.setdefault("add_flow_message_ids", [])


def track_add_flow_message_id(context, message_id):
    """Track a message id so add-flow cleanup can delete it later."""
    if message_id is None:
        return
    ensure_add_flow_tracker(context)
    tracked = context.user_data["add_flow_message_ids"]
    if message_id not in tracked:
        tracked.append(message_id)


def track_add_flow_incoming(update, context):
    """Track incoming user messages that belong to add-flow steps."""
    if update and update.message:
        track_add_flow_message_id(context, update.message.message_id)


def track_add_flow_callback_message(update, context):
    """Track callback-origin message ids used by add-flow menus."""
    if update and update.callback_query and update.callback_query.message:
        track_add_flow_message_id(context, update.callback_query.message.message_id)


def track_add_flow_outgoing(context, message):
    """Track outgoing bot messages produced during add flow."""
    if message:
        track_add_flow_message_id(context, getattr(message, "message_id", None))


async def _delete_additional_info_copy_message(update, context):
    """Delete the stored additional-info copy message and clear its transient key.

    Clears the key before attempting deletion so the key is always removed even
    when the Telegram call fails.  Guards silently when bot or chat_id are
    unavailable.  All delete failures are swallowed as benign no-ops.
    """
    msg_id = context.user_data.pop("additional_info_copy_msg_id", None)
    if not msg_id:
        return
    chat_id = update.effective_chat.id if (update and update.effective_chat) else None
    if not getattr(context, "bot", None) or not chat_id:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass


async def cleanup_add_flow_messages(context, bot, chat_id, end_message_id=None, keep_message_ids=None):
    """Delete tracked add-flow messages while preserving protected ids."""
    keep_ids = set(keep_message_ids or [])
    tracked = set(context.user_data.get("add_flow_message_ids", []))

    start_id = context.user_data.get("add_flow_start_message_id")
    if isinstance(start_id, int) and isinstance(end_message_id, int) and end_message_id >= start_id:
        # Defensive cap avoids broad accidental deletes if IDs drift too far.
        if (end_message_id - start_id) <= 250:
            tracked.update(range(start_id, end_message_id + 1))

    for message_id in sorted(tracked):
        if message_id in keep_ids:
            continue
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            continue
    context.user_data["add_flow_message_ids"] = []
    context.user_data["add_flow_start_message_id"] = None
