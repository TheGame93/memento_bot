ADD_FLOW_KEYS = {
    "temp_alert",
    "temp_selection",
    "pending_pre_alerts",
    "pending_bday_name",
    "daily_interval_confirm_source",
    "settings_return",
    "add_flow_message_ids",
    "add_flow_start_message_id",
    "add_flow_save_in_progress",
    "birthday_save_in_progress",
    "additional_info_copy_msg_id",
}

SEARCH_KEYS = {
    "expecting_alert_search",
    "expecting_birthday_search",
}

TAG_KEYS = {
    "expecting_tag_name",
    "tag_delete_token_map",
    "expecting_tag_rename",
    "tag_rename_old",
    "tag_edit_token_map",
}

BACKUP_KEYS = {
    "expecting_backup_email",
    "backup_email_enable_after_set",
    "expecting_import_archive",
    "backup_import_session",
    "backup_manage_session",
}

TIMEZONE_KEYS = {
    "expecting_timezone_query",
    "expecting_timezone_location",
    "timezone_query_value",
    "timezone_pick_token_map",
}

SETTINGS_KEYS = {
    "expecting_birthday_time",
    "expecting_birthday_evening_time",
    "expecting_bday_bulk_import_message",
    "bday_bulk_import_session",
}

EDIT_TEXT_KEYS = {
    "expecting_edit_text",
    "edit_text_alert_id",
    "edit_text_source",
    "edit_text_message_id",
    "edit_text_is_photo",
    "edit_text_include_back",
    "edit_text_detail_ctx",
}

EDIT_FLOW_KEYS = {
    "edit_alert_id",
    "edit_alert_original",
    "edit_origin_context",
}

POSTPONE_KEYS = {
    "expecting_custom_postpone",
    "custom_postpone_alert_id",
    "postpone_alert_id",
    "postpone_kind",
    "postpone_original_time",
    "postpone_occurrence_time",
    "postpone_message_id",
}

GHOST_KEYS = {
    "expecting_ghost_custom",
}

FILTER_KEYS = {
    "alerts_filter_token_map",
    "birthdays_filter_token_map",
}

ADMIN_KEYS = {
    "expecting_admin_add_user",
    "expecting_admin_custom_name",
    "admin_custom_name_target_id",
    "admin_custom_name_target_kind",
}

ONBOARDING_KEYS = {
    "expecting_start_request_message",
    "start_request_message_draft",
    "start_request_confirm_pending",
}

NAVIGATION_KEYS = {
    "current_filter",
    "birthday_current_filter",
    "alerts_current_page",
    "birthdays_current_page",
    "manage_source",
    "compact_list_context",
}

DYNAMIC_PREFIXES = (
    "manage_del_ctx_",
    "manage_del_back_",
    "ghost_picker_",
    "ghost_dedup_",
    "ghost_summary_markup_",
    "ghost_delete_markup_",
)
