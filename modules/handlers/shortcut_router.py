import logging

from telegram import Update
from telegram.ext import ContextTypes

from modules import constants as C
from modules.handlers.list_alerts import LIST_CONTEXT_KEY, send_alert_detail_by_id
from modules.shared.acting_as import (
    build_acting_as_payload,
    get_actor_user_id,
    get_target_user_id,
)
from modules.shared.runtime_context import get_runtime_storage

logger = logging.getLogger(__name__)


def _resolve_ids(update, context):
    actor_id = get_actor_user_id(update)
    target_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)
    return actor_id, target_id, acting_payload


def _get_compact_context(context):
    data = context.user_data.get(LIST_CONTEXT_KEY)
    if isinstance(data, dict):
        return data
    return {}


def _extract_command_name(text):
    if not text or not text.startswith("/"):
        return None
    token = text.strip().split()[0]
    if not token.startswith("/"):
        return None
    command = token[1:]
    if "@" in command:
        command = command.split("@", 1)[0]
    return command


def _canonical_local_alias(command):
    if not isinstance(command, str) or not command.isdigit():
        return None
    try:
        value = int(command)
    except Exception:
        return None
    if value < 100:
        return f"{value:02d}"
    return str(value)


async def handle_dynamic_shortcut_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles:
      - local list aliases: /01 .. /20+ (page-scoped)
      - global stable shortcut: /a0f, /B9Z, ...
    Leaves regular bot commands to their dedicated handlers.
    """
    storage = get_runtime_storage(context)

    message = update.effective_message or update.message
    if not message:
        return

    text = (message.text or "").strip()
    command = _extract_command_name(text)
    if not command:
        return

    cmd_lower = command.lower()
    if cmd_lower in {"admin", "developer"}:
        await message.reply_text("⚠️ /admin and /developer were removed. Use /manage.")
        return
    if cmd_lower in set(getattr(C, "SHORTCODE_RESERVED_COMMANDS", set())):
        # Avoid stale search modes after normal slash-commands (/status, /help, ...).
        # Keep /cancel behavior untouched (it clears all context on its own).
        if cmd_lower != "cancel":
            _, user_id, acting_payload = _resolve_ids(update, context)
            if context.user_data.get("expecting_birthday_search"):
                context.user_data["expecting_birthday_search"] = False
                payload = {"command": cmd_lower}
                payload.update(acting_payload)
                storage.log_user_event(user_id, "birthday_search_cancelled_by_command", payload)
            if context.user_data.get("expecting_alert_search"):
                context.user_data["expecting_alert_search"] = False
                payload = {"command": cmd_lower}
                payload.update(acting_payload)
                storage.log_user_event(user_id, "alert_search_cancelled_by_command", payload)
        return

    # Avoid context collisions with active creation/tag/postpone flows.
    if (context.user_data.get("temp_alert")
            or context.user_data.get("expecting_tag_name")
            or context.user_data.get("expecting_tag_rename")):
        await message.reply_text("⚠️ Finish or /cancel the current flow before opening shortcuts.")
        return
    if context.user_data.get("expecting_custom_postpone"):
        await message.reply_text("⚠️ Finish custom postpone input first (or /cancel).")
        return
    if context.user_data.get("expecting_edit_text"):
        await message.reply_text("⚠️ Finish text editing first (or /cancel).")
        return

    _, user_id, _ = _resolve_ids(update, context)

    # Local aliases are numeric shortcuts on current list page.
    alias_key = _canonical_local_alias(command)
    if alias_key is not None:
        list_ctx = _get_compact_context(context)
        source = list_ctx.get("source") if isinstance(list_ctx, dict) else None
        alias_map = list_ctx.get("alias_map") if isinstance(list_ctx, dict) else None
        target_id = alias_map.get(alias_key) if isinstance(alias_map, dict) else None
        if not target_id:
            await message.reply_text("⚠️ This local shortcut expired. Open the list page again.")
            return
        if source == "admin_requests":
            from modules.handlers.admin import handle_admin_shortcut_request
            await handle_admin_shortcut_request(update, context, target_id)
            return
        if source == "admin_invites":
            from modules.handlers.admin import handle_admin_shortcut_invite
            await handle_admin_shortcut_invite(update, context, target_id)
            return
        if source == "admin_users":
            from modules.handlers.admin import handle_admin_shortcut_user
            await handle_admin_shortcut_user(update, context, target_id)
            return
        if source == "developer_users":
            from modules.handlers.developer import handle_developer_shortcut_user
            await handle_developer_shortcut_user(update, context, target_id)
            return
        if source == "backup_restore_users":
            from modules.handlers.backup_manage import handle_restore_backup_select
            await handle_restore_backup_select(update, context, target_id)
            return
        if source == "backup_restore_archives":
            from modules.handlers.backup_manage import handle_restore_summary
            await handle_restore_summary(update, context, target_id)
            return
        if source == "backup_system_archives":
            from modules.handlers.backup_manage import handle_system_backup_shortcut
            await handle_system_backup_shortcut(update, context, target_id)
            return
        await send_alert_detail_by_id(update, context, target_id, source_hint=source)
        return

    # Global persistent shortcut pattern.
    if len(command) >= 3 and command[0].isalpha() and command[1:].isalnum():
        alert = storage.get_alert_by_shortcode(user_id, command)
        if not alert:
            await message.reply_text("⚠️ Shortcut not found.")
            return
        await send_alert_detail_by_id(update, context, alert.get("id"))
        return

    # Non-reserved slash commands that are not valid aliases/shortcodes
    # are treated as unknown shortcuts.
    await message.reply_text("⚠️ Shortcut not found.")
