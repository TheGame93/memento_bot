"""Public re-export surface for the `modules.handlers.base` package."""

from modules.handlers.base.onboarding import (
    START_REQUEST_CANCEL_CB,
    START_REQUEST_EDIT_NO_CB,
    START_REQUEST_EDIT_YES_CB,
    START_REQUEST_MAX_MESSAGE_CHARS,
    START_REQUEST_PROCEED_CB,
    _start_request_pending_keyboard,
    _start_request_pending_text,
    clear_start_request_context,
    handle_start_request_callback,
    start,
)
from modules.handlers.base.help import (
    HELP_ADMIN_TEXT,
    HELP_COMMANDS_TEXT,
    HELP_DEVELOPER_TEXT,
    HELP_DONE_CB,
    HELP_DONE_POPUP_TEXT,
    HELP_INTRO_INTRO_TEXT,
    HELP_INTRO_ISNOT_TEXT,
    HELP_INTRO_USEIT_TEXT,
    HELP_NEXT_LABEL,
    HELP_NEXT_PREFIX,
    HELP_SYSTEM_COMMANDS_TEXT,
    _help_section_entries_for_role,
    _help_sections_for_role,
    handle_help_callback,
    help_command,
)
from modules.handlers.base.lifecycle import cancel
from modules.handlers.base.conversation_fallbacks import (
    build_implicit_cancel_fallbacks,
    end_registered_conversations,
    iter_registered_conversation_handlers,
    register_conversation_handler,
)
from modules.handlers.base.settings import (
    build_settings_keyboard,
    build_settings_placeholder_keyboard,
    build_settings_placeholder_status,
    handle_settings_callback,
    settings,
)
from modules.handlers.base.settings_bday import (
    _birthday_default_time_from_prefs,
    build_birthday_bulk_export_mode_keyboard,
    build_birthday_bulk_export_mode_status,
    build_birthday_bulk_import_decision_keyboard,
    build_birthday_time_keyboard,
    build_birthday_time_status,
    build_birthday_zodiac_keyboard,
    build_birthday_zodiac_status,
    normalize_time_input,
)
from modules.handlers.base.settings_mail import (
    build_backup_email_sent_notification,
    build_mail_backup_keyboard,
    build_mail_backup_reminder_keyboard,
    build_mail_backup_reminder_message,
    build_mail_backup_status,
    build_mail_set_prompt_keyboard,
    build_mail_set_prompt_message,
)
from modules.handlers.base.settings_tz import (
    _format_timezone_line,
    build_location_request_keyboard,
    build_timezone_keyboard,
    build_timezone_status,
    handle_timezone_location_input,
    handle_timezone_query_input,
)
import importlib

from modules.handlers.base.status import get_size_format

_status_module = importlib.import_module("modules.handlers.base.status")

# Compatibility surface used by debugger monkeypatches that import
# `modules.handlers.base` as a module object.
DATA_DIR = _status_module.DATA_DIR
SYSTEM_LOG_DIR = _status_module.SYSTEM_LOG_DIR
USER_LOG_DIR = _status_module.USER_LOG_DIR
build_status_message = _status_module.build_status_message
build_acting_as_payload = _status_module.build_acting_as_payload
build_acting_as_banner = _status_module.build_acting_as_banner
get_actor_user_id = _status_module.get_actor_user_id
get_target_user_id = _status_module.get_target_user_id


async def status(update, context):
    """Render the role-scoped status summary for the current target user."""
    _status_module.DATA_DIR = DATA_DIR
    _status_module.SYSTEM_LOG_DIR = SYSTEM_LOG_DIR
    _status_module.USER_LOG_DIR = USER_LOG_DIR
    _status_module.build_status_message = build_status_message
    _status_module.build_acting_as_payload = build_acting_as_payload
    _status_module.build_acting_as_banner = build_acting_as_banner
    _status_module.get_actor_user_id = get_actor_user_id
    _status_module.get_target_user_id = get_target_user_id
    return await _status_module.status(update, context)


__all__ = [
    "start",
    "handle_start_request_callback",
    "help_command",
    "handle_help_callback",
    "HELP_NEXT_PREFIX",
    "HELP_DONE_CB",
    "HELP_NEXT_LABEL",
    "HELP_DONE_POPUP_TEXT",
    "HELP_INTRO_INTRO_TEXT",
    "HELP_INTRO_USEIT_TEXT",
    "HELP_INTRO_ISNOT_TEXT",
    "HELP_COMMANDS_TEXT",
    "HELP_SYSTEM_COMMANDS_TEXT",
    "HELP_ADMIN_TEXT",
    "HELP_DEVELOPER_TEXT",
    "_help_sections_for_role",
    "_help_section_entries_for_role",
    "status",
    "cancel",
    "register_conversation_handler",
    "iter_registered_conversation_handlers",
    "end_registered_conversations",
    "build_implicit_cancel_fallbacks",
    "settings",
    "handle_settings_callback",
    "START_REQUEST_MAX_MESSAGE_CHARS",
    "START_REQUEST_PROCEED_CB",
    "START_REQUEST_CANCEL_CB",
    "START_REQUEST_EDIT_YES_CB",
    "START_REQUEST_EDIT_NO_CB",
    "_start_request_pending_text",
    "_start_request_pending_keyboard",
    "build_settings_keyboard",
    "build_settings_placeholder_status",
    "build_mail_set_prompt_message",
    "build_mail_set_prompt_keyboard",
    "build_mail_backup_keyboard",
    "build_mail_backup_status",
    "build_birthday_time_status",
    "build_birthday_zodiac_status",
    "build_birthday_bulk_import_decision_keyboard",
    "handle_timezone_query_input",
    "handle_timezone_location_input",
    "normalize_time_input",
    "build_backup_email_sent_notification",
    "build_mail_backup_reminder_message",
    "build_mail_backup_reminder_keyboard",
    "_birthday_default_time_from_prefs",
    "get_size_format",
    "clear_start_request_context",
    "build_birthday_time_keyboard",
    "build_birthday_bulk_export_mode_keyboard",
    "build_birthday_bulk_export_mode_status",
    "build_birthday_zodiac_keyboard",
    "build_timezone_keyboard",
    "build_location_request_keyboard",
    "build_timezone_status",
    "_format_timezone_line",
    "build_settings_placeholder_keyboard",
    "DATA_DIR",
    "SYSTEM_LOG_DIR",
    "USER_LOG_DIR",
    "build_status_message",
    "build_acting_as_payload",
    "build_acting_as_banner",
    "get_actor_user_id",
    "get_target_user_id",
]
