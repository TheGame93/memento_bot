"""Provide the public compatibility surface for `modules.handlers.admin`."""

from . import invites as _invites
from modules.security.whitelist_store import (
    find_whitelist_invite,
    list_whitelist_invites,
    remove_whitelist_invite,
)
from modules.shared.markdown_utils import md_escape as _md_escape
from modules.systemlog import log_system

from .invites import (
    _build_invite_message,
    _build_invites_list,
    _callback_data_safe,
    _invite_detail_text,
    _invite_token_from_record,
    handle_admin_shortcut_invite,
    show_admin_invites_list,
)
from .requests import (
    _build_requests_list,
    _find_request_record,
    _request_action_keyboard,
    _request_action_text,
    _requests_text,
    show_admin_requests_list,
    handle_admin_shortcut_request,
)
from .router import handle_admin_callback
from .users import (
    ADMIN_USER_SET_NAME_PROMPT,
    _admin_user_set_name_keyboard,
    _build_user_status,
    _build_users_list,
    _is_admin_role,
    _is_self_removal,
    _is_target_whitelisted,
    _removal_result_text,
    _user_status_keyboard,
    start_admin_add_user,
    handle_admin_shortcut_user,
)


def _find_invite_by_token(token):
    """Delegate token lookup while honoring package-level monkeypatches in debuggers."""
    _invites.find_whitelist_invite = find_whitelist_invite
    return _invites._find_invite_by_token(token)


def _remove_invite_record(record):
    """Delegate invite deletion while honoring package-level monkeypatches in debuggers."""
    _invites.remove_whitelist_invite = remove_whitelist_invite
    return _invites._remove_invite_record(record)


def _prune_stale_id_invites(storage, actor_id):
    """Delegate stale-prune flow while honoring package-level monkeypatches in debuggers."""
    _invites.list_whitelist_invites = list_whitelist_invites
    _invites.remove_whitelist_invite = remove_whitelist_invite
    _invites.log_system = log_system
    return _invites._prune_stale_id_invites(storage, actor_id)


__all__ = [
    "handle_admin_callback",
    "show_admin_requests_list",
    "show_admin_invites_list",
    "start_admin_add_user",
    "handle_admin_shortcut_request",
    "handle_admin_shortcut_invite",
    "handle_admin_shortcut_user",
    "ADMIN_USER_SET_NAME_PROMPT",
    "_build_invite_message",
    "_find_request_record",
    "_request_action_keyboard",
    "_request_action_text",
    "_is_target_whitelisted",
    "_user_status_keyboard",
    "_build_user_status",
    "_admin_user_set_name_keyboard",
    "_build_requests_list",
    "_build_users_list",
    "_is_admin_role",
    "_is_self_removal",
    "_md_escape",
    "_removal_result_text",
    "_requests_text",
    "_build_invites_list",
    "_invite_detail_text",
    "_find_invite_by_token",
    "_remove_invite_record",
    "_prune_stale_id_invites",
    "_invite_token_from_record",
    "_callback_data_safe",
    "find_whitelist_invite",
    "remove_whitelist_invite",
    "list_whitelist_invites",
    "log_system",
]
