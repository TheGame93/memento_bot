# Handler and Flow Index

> **Location:** `docs/truth/info_handlers.md`  
> **Auto-generated** by `scripts/gen_info_functions.py` — do not edit by hand.  
> Re-run whenever public functions are added, renamed, or removed:
> `python3 scripts/gen_info_functions.py`

Fields per entry: `name | parent | inputs | output | description`

## `modules/handlers/add_alert.py`
- `ask_time` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `ask_time` add-flow handler to the modular implementation.
- `calculate_suggested_start` | `modules.handlers.add_alert` | `data` | — | Return a suggested first-occurrence datetime for interval prompts.
- `start_add` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `start_add` add-flow handler to the modular implementation.
- `start_add_from_menu` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `start_add_from_menu` add-flow handler to the modular implementation.
- `select_type` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `select_type` add-flow handler to the modular implementation.
- `get_title` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `get_title` add-flow handler to the modular implementation.
- `prompt_type_specific` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `prompt_type_specific` add-flow handler to the modular implementation.
- `type_1_days` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `type_1_days` add-flow handler to the modular implementation.
- `type_4_dates` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `type_4_dates` add-flow handler to the modular implementation.
- `type_5_date` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `type_5_date` add-flow handler to the modular implementation.
- `type_6_date` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `type_6_date` add-flow handler to the modular implementation.
- `toggle_handler` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE`, `data_list`, `cb_prefix`, `next_state`, `next_msg`, `next_kb_func`, `next_func` | — | Delegate the legacy `toggle_handler` add-flow handler to the modular implementation.
- `type_2_ordinal` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `type_2_ordinal` add-flow handler to the modular implementation.
- `type_2_fifth_policy` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `type_2_fifth_policy` add-flow handler to the modular implementation.
- `type_2_weekday` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `type_2_weekday` add-flow handler to the modular implementation.
- `type_3_weekdays` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `type_3_weekdays` add-flow handler to the modular implementation.
- `get_interval_prompt` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `get_interval_prompt` add-flow handler to the modular implementation.
- `get_interval_callback` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `get_interval_callback` add-flow handler to the modular implementation.
- `get_interval_input` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `get_interval_input` add-flow handler to the modular implementation.
- `daily_interval_confirm_callback` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `daily_interval_confirm_callback` add-flow handler to the modular implementation.
- `interval_mode_choice_callback` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate daily interval mode choice callbacks to the modular implementation.
- `fuzzy_mean_std_input` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate daily fuzzy mean/std parsing to the modular implementation.
- `get_start_date_callback` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `get_start_date_callback` add-flow handler to the modular implementation.
- `get_start_date_input` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `get_start_date_input` add-flow handler to the modular implementation.
- `get_time_input` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `get_time_input` add-flow handler to the modular implementation.
- `get_time_callback` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `get_time_callback` add-flow handler to the modular implementation.
- `show_pre_alert_menu` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `show_pre_alert_menu` add-flow handler to the modular implementation.
- `get_pre_alert_callback` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `get_pre_alert_callback` add-flow handler to the modular implementation.
- `get_custom_pre_alert_input` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `get_custom_pre_alert_input` add-flow handler to the modular implementation.
- `confirm_custom_pre_alert` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `confirm_custom_pre_alert` add-flow handler to the modular implementation.
- `show_tags_menu` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `show_tags_menu` add-flow handler to the modular implementation.
- `tags_toggle` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `tags_toggle` add-flow handler to the modular implementation.
- `show_multi_setting_menu` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `show_multi_setting_menu` add-flow handler to the modular implementation.
- `show_repetition_menu` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `show_repetition_menu` add-flow handler to the modular implementation.
- `prompt_repetition_until_date` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `prompt_repetition_until_date` add-flow handler to the modular implementation.
- `prompt_repetition_count` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `prompt_repetition_count` add-flow handler to the modular implementation.
- `handle_repetition_choice` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `handle_repetition_choice` add-flow handler to the modular implementation.
- `handle_repetition_until_date_input` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `handle_repetition_until_date_input` add-flow handler to the modular implementation.
- `handle_repetition_count_input` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `handle_repetition_count_input` add-flow handler to the modular implementation.
- `handle_multi_setting_choice` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `handle_multi_setting_choice` add-flow handler to the modular implementation.
- `handle_change_type_callback` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `handle_change_type_callback` add-flow handler to the modular implementation.
- `show_photo_menu` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `show_photo_menu` add-flow handler to the modular implementation.
- `prompt_additional_info` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `prompt_additional_info` add-flow handler to the modular implementation.
- `handle_additional_info_input` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `handle_additional_info_input` add-flow handler to the modular implementation.
- `handle_additional_info_skip` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `handle_additional_info_skip` add-flow handler to the modular implementation.
- `handle_additional_info_clear` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate explicit Additional Info clear action to shared add-flow settings logic.
- `get_photo` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `get_photo` add-flow handler to the modular implementation.
- `reject_document` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `reject_document` add-flow handler to the modular implementation.
- `photo_back` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `photo_back` add-flow handler to the modular implementation.
- `remove_photo` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate the legacy `remove_photo` add-flow handler to the modular implementation.
- `save_after_tags` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Persist the staged alert after tag selection completes.
- `cancel` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Cancel add flow, clear transient context, and force-end registered conversation state for this user.
- `handle_legacy_review_callback` | `modules.handlers.add_alert` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Global fallback for old review keyboards (save/discard) left in chat history.

## `modules/handlers/add_flow/flow_start.py`
- `start_add` | `modules.handlers.add_flow.flow_start` | `update`, `context` | — | Start the add-alert flow from a message entrypoint.
- `start_add_from_menu` | `modules.handlers.add_flow.flow_start` | `update`, `context` | — | Start the add-alert flow from the alerts menu callback.
- `select_type` | `modules.handlers.add_flow.flow_start` | `update`, `context` | — | Store the selected alert type and route to type-specific prompts.
- `get_title` | `modules.handlers.add_flow.flow_start` | `update`, `context`, `prompt_type_specific` | — | Validate and store the alert title before opening type selection.
- `prompt_type_specific` | `modules.handlers.add_flow.flow_start` | `update`, `context`, `get_interval_prompt` | — | Prompt for schedule fields required by the selected alert type.

## `modules/handlers/add_flow/keyboards.py`
- `build_toggle_keyboard` | `modules.handlers.add_flow.keyboards` | `items`, `selected_items`, `callback_prefix`, `cols` | — | Build a toggle-style inline keyboard with a DONE action.
- `build_type_keyboard` | `modules.handlers.add_flow.keyboards` | — | — | Build the add-flow alert-type picker keyboard.
- `build_change_type_keyboard` | `modules.handlers.add_flow.keyboards` | — | — | Build the change-type keyboard excluding unsupported alert types.

## `modules/handlers/add_flow/media_flow.py`
- `show_photo_menu` | `modules.handlers.add_flow.media_flow` | `update`, `context` | — | Show media options for adding, removing, or skipping alert photos.
- `get_photo` | `modules.handlers.add_flow.media_flow` | `update`, `context`, `show_settings_menu` | — | Store the uploaded photo identifier and return to settings.
- `reject_document` | `modules.handlers.add_flow.media_flow` | `update`, `context` | — | Reject document uploads and keep the flow on the photo step.
- `photo_back` | `modules.handlers.add_flow.media_flow` | `update`, `context`, `show_settings_menu` | — | Return from the photo step to the settings dashboard.
- `remove_photo` | `modules.handlers.add_flow.media_flow` | `update`, `context`, `show_settings_menu` | — | Remove staged photo fields and return to settings.

## `modules/handlers/add_flow/repetition_flow.py`
- `show_repetition_menu` | `modules.handlers.add_flow.repetition_flow` | `update`, `context` | — | Show repetition mode options for repetition-capable alert types.
- `handle_repetition_choice` | `modules.handlers.add_flow.repetition_flow` | `update`, `context`, `return_to_settings`, `prompt_until`, `prompt_count` | — | Handle repetition mode selection and route to the next repetition step.
- `prompt_repetition_until_date` | `modules.handlers.add_flow.repetition_flow` | `update`, `context` | — | Prompt for an inclusive repetition end date.
- `prompt_repetition_count` | `modules.handlers.add_flow.repetition_flow` | `update`, `context` | — | Prompt for a repetition occurrence-count limit.
- `handle_repetition_until_date_input` | `modules.handlers.add_flow.repetition_flow` | `update`, `context`, `return_to_settings` | — | Validate until-date input, log reasoned failures, and persist normalized repetition limits.
- `handle_repetition_count_input` | `modules.handlers.add_flow.repetition_flow` | `update`, `context`, `return_to_settings` | — | Validate count input, log reasoned failures, and persist normalized repetition limits.

## `modules/handlers/add_flow/settings_flow.py`
- `settings_return_target` | `modules.handlers.add_flow.settings_flow` | `context` | — | Return the settings destination key for alert, birthday, or edit flows.
- `return_to_settings` | `modules.handlers.add_flow.settings_flow` | `update`, `context`, `show_alert_settings_menu`, `show_birthday_settings_menu`, `show_edit_dashboard` | — | Route back to the settings dashboard that matches current flow context.
- `show_multi_setting_menu` | `modules.handlers.add_flow.settings_flow` | `update`, `context` | — | Render the add-flow settings menu with pre-alert labels resolved against the current schedule context.
- `handle_multi_setting_choice` | `modules.handlers.add_flow.settings_flow` | `update`, `context`, `get_interval_prompt`, `ask_time`, `show_pre_alert_menu`, `show_photo_menu`, `prompt_additional_info`, `show_tags_menu`, `show_repetition_menu` | — | Route settings-menu actions to the selected add-flow substep.
- `show_change_type_menu` | `modules.handlers.add_flow.settings_flow` | `update`, `context` | — | Show the inline menu for changing alert type mid-flow.
- `prompt_additional_info` | `modules.handlers.add_flow.settings_flow` | `update`, `context` | — | Prompt for optional additional info; send a raw copy of the current text when non-empty.
- `handle_additional_info_input` | `modules.handlers.add_flow.settings_flow` | `update`, `context`, `return_to_settings` | — | Validate and store additional information before returning to settings.
- `handle_additional_info_clear` | `modules.handlers.add_flow.settings_flow` | `update`, `context`, `return_to_settings` | — | Clear staged additional info explicitly and route back through the active settings destination.
- `handle_additional_info_skip` | `modules.handlers.add_flow.settings_flow` | `update`, `context`, `return_to_settings` | — | Skip additional information and return to settings.

## `modules/handlers/add_flow/state_helpers.py`
- `ensure_add_flow_tracker` | `modules.handlers.add_flow.state_helpers` | `context` | — | Ensure add-flow message tracking storage exists in user context.
- `track_add_flow_message_id` | `modules.handlers.add_flow.state_helpers` | `context`, `message_id` | — | Track a message id so add-flow cleanup can delete it later.
- `track_add_flow_incoming` | `modules.handlers.add_flow.state_helpers` | `update`, `context` | — | Track incoming user messages that belong to add-flow steps.
- `track_add_flow_callback_message` | `modules.handlers.add_flow.state_helpers` | `update`, `context` | — | Track callback-origin message ids used by add-flow menus.
- `track_add_flow_outgoing` | `modules.handlers.add_flow.state_helpers` | `context`, `message` | — | Track outgoing bot messages produced during add flow.
- `cleanup_add_flow_messages` | `modules.handlers.add_flow.state_helpers` | `context`, `bot`, `chat_id`, `end_message_id`, `keep_message_ids` | — | Delete tracked add-flow messages while preserving protected ids.

## `modules/handlers/add_flow/summary_flow.py`
- `ensure_default_settings` | `modules.handlers.add_flow.summary_flow` | `data` | — | Populate missing alert defaults and normalize daily/repetition schedule invariants.
- `format_interval` | `modules.handlers.add_flow.summary_flow` | `data` | — | Return a human-readable interval label for recurring alert types.
- `format_pre_alerts` | `modules.handlers.add_flow.summary_flow` | `data`, `due_dt`, `user_prefs`, `reference_time` | — | Render pre-alert entries using resolved datetime labels when due context is available.
- `format_repetition` | `modules.handlers.add_flow.summary_flow` | `data` | — | Return the repetition summary label for the current alert payload.
- `format_photo_choice` | `modules.handlers.add_flow.summary_flow` | `data` | — | Return whether the alert currently has an image attachment.
- `format_additional_info` | `modules.handlers.add_flow.summary_flow` | `data` | — | Return a compact additional-info preview, or `None` when empty.
- `is_one_time_past` | `modules.handlers.add_flow.summary_flow` | `data`, `reference_time`, `user_prefs` | — | Check whether a one-time alert resolves to a past-or-now datetime.
- `format_alert_summary` | `modules.handlers.add_flow.summary_flow` | `data`, `alert_id`, `user_prefs`, `reference_time` | — | Build a Markdown-safe detailed alert summary for preview and save flows.

## `modules/handlers/add_flow/type_flow.py`
- `ask_time` | `modules.handlers.add_flow.type_flow` | `update`, `context` | — | Prompt for reminder time with a default-time shortcut button.
- `calculate_suggested_start` | `modules.handlers.add_flow.type_flow` | `data` | — | Return a suggested first-occurrence datetime from the draft schedule.
- `type_1_days` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `show_multi_setting_menu` | — | Validate monthly day-of-month input and store it in the draft schedule.
- `type_4_dates` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `show_multi_setting_menu` | — | Validate yearly day/month tokens and store them in the draft schedule.
- `type_5_date` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `show_multi_setting_menu` | — | Normalize one-time date input, enforce same-day year disambiguation, and persist schedule date.
- `type_6_date` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `show_tags_menu` | — | Validate birthday date input and apply the default birthday reminder time.
- `toggle_handler` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `data_list`, `cb_prefix`, `next_state`, `next_msg`, `next_kb_func`, `next_func`, `get_interval_prompt` | — | Handle toggle keyboard interactions and persist selections on DONE.
- `type_2_ordinal` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `get_interval_prompt` | — | Handle relative-month ordinal selection before weekday selection.
- `type_2_fifth_policy` | `modules.handlers.add_flow.type_flow` | `update`, `context` | — | Store the fifth-occurrence fallback policy and continue weekday selection.
- `type_2_weekday` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `show_multi_setting_menu` | — | Handle relative-month weekday selection and continue to settings.
- `type_3_weekdays` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `show_multi_setting_menu` | — | Handle weekly weekday selection and continue to settings.
- `get_interval_prompt` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `show_multi_setting_menu` | — | Prompt for interval input and enforce daily-interval UX constraints.
- `interval_mode_choice_callback` | `modules.handlers.add_flow.type_flow` | `update`, `context` | — | Handle daily fixed-vs-fuzzy mode selection and route to the next prompt.
- `fuzzy_mean_std_input` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `show_multi_setting_menu` | — | Parse fuzzy daily mean/std, sample draft next occurrence, and return to settings.
- `get_interval_callback` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `return_to_settings` | — | Handle interval quick-button callbacks and return to settings.
- `get_interval_input` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `show_multi_setting_menu` | — | Validate interval text input, store schedule interval, and route next steps.
- `daily_interval_confirm_callback` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `return_to_settings`, `show_multi_setting_menu` | — | Handle explicit confirmation for daily interval value `1`.
- `get_start_date_callback` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `show_multi_setting_menu` | — | Store a start marker selected from interval suggestion callbacks.
- `get_start_date_input` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `show_multi_setting_menu` | — | Validate manual start-marker input and store it in the schedule.
- `get_time_input` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `show_multi_setting_menu` | — | Validate HH:MM input and store it as the schedule time.
- `get_time_callback` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `show_multi_setting_menu` | — | Apply default schedule time from the quick-button callback.
- `show_pre_alert_menu` | `modules.handlers.add_flow.type_flow` | `update`, `context` | — | Show pre-alert options for the current draft alert payload.
- `get_pre_alert_callback` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `return_to_settings` | — | Route pre-alert menu actions and present expanded custom-input guidance when requested.
- `get_custom_pre_alert_input` | `modules.handlers.add_flow.type_flow` | `update`, `context` | — | Parse custom pre-alert input, show interpreted outcomes, and return reasoned retry feedback.
- `confirm_custom_pre_alert` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `return_to_settings` | — | Handle custom pre-alert confirmation and re-prompt with full syntax guidance on retry.
- `show_tags_menu` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `pre_selected` | — | Show available tags and initialize tag toggle selection state.
- `tags_toggle` | `modules.handlers.add_flow.type_flow` | `update`, `context`, `finalize_after_tags` | — | Handle tag toggles and finalize the flow when DONE is selected.

## `modules/handlers/add_flow/validators.py`
- `normalize_pre_alert_unit` | `modules.handlers.add_flow.validators` | `unit_text` | — | Normalize textual pre-alert units into canonical token suffixes.
- `parse_custom_pre_alerts` | `modules.handlers.add_flow.validators` | `raw_text` | — | Parses comma-separated custom pre-alerts and normalizes them to tokens like:
- `merge_pre_alerts` | `modules.handlers.add_flow.validators` | `existing`, `new_items` | — | Merge pre-alert tokens while preserving order and removing duplicates.

## `modules/handlers/admin/invites.py`
- `show_admin_invites_list` | `modules.handlers.admin.invites` | `query`, `context`, `storage`, `actor_id` | — | Render pending invite entries after pruning stale id-based invites.
- `handle_admin_shortcut_invite` | `modules.handlers.admin.invites` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE`, `token: str` | `None` | Handle admin invite shortcut commands and render invite details.

## `modules/handlers/admin/requests.py`
- `show_admin_requests_list` | `modules.handlers.admin.requests` | `query`, `context` | — | Render pending whitelist requests and store shortcut alias context.
- `handle_admin_shortcut_request` | `modules.handlers.admin.requests` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE`, `target_id: str` | `None` | Handle admin request shortcut commands and open request actions.

## `modules/handlers/admin/router.py`
- `handle_admin_callback` | `modules.handlers.admin.router` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Route admin dashboard callbacks for requests, invites, and user operations.

## `modules/handlers/admin/users.py`
- `start_admin_add_user` | `modules.handlers.admin.users` | `query`, `context` | — | Start admin add-user capture flow and arm transient input state.
- `handle_admin_shortcut_user` | `modules.handlers.admin.users` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE`, `target_id: str` | `None` | Handle admin user shortcut commands and render user detail cards.

## `modules/handlers/alerts.py`
- `alerts_start` | `modules.handlers.alerts` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Render the alerts home menu with tag statistics and markdown fallback handling.
- `rank_alerts_by_name` | `modules.handlers.alerts` | `query_text`, `alerts` | — | Ranks only non-birthday alerts by title similarity.
- `alert_search_start` | `modules.handlers.alerts` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Enables free-text alert search mode from /alerts menu button.
- `alert_search` | `modules.handlers.alerts` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Fuzzy-search non-birthday alerts by title.
- `alert_search_from_text` | `modules.handlers.alerts` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Runs alert search from free-text input after pressing alert search button.

## `modules/handlers/backup_manage.py`
- `handle_manage_backups` | `modules.handlers.backup_manage` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Render the /manage Backups panel for elevated roles.
- `handle_restore_user_select` | `modules.handlers.backup_manage` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Render role-scoped user aliases for restore selection.
- `handle_restore_backup_select` | `modules.handlers.backup_manage` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE`, `target_user_id: str` | — | Render archive aliases for one restore target user.
- `handle_restore_summary` | `modules.handlers.backup_manage` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE`, `archive_ref: str` | — | Render one archive summary card and restore confirmation actions.
- `handle_restore_confirm` | `modules.handlers.backup_manage` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Run user restore from the selected summary archive and clear restore session state.
- `handle_restore_cancel` | `modules.handlers.backup_manage` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Cancel the in-progress restore confirmation and clear backup session state.
- `handle_system_backup_shortcut` | `modules.handlers.backup_manage` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE`, `alias_value: str` | — | Resolve numeric system-backup aliases to restore summary rendering.
- `handle_system_backup_panel` | `modules.handlers.backup_manage` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Render developer-only system backup controls under /manage -> Backups.
- `handle_system_backup_export` | `modules.handlers.backup_manage` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Build one system backup archive and render export metadata for developers.
- `handle_system_backup_restore_list` | `modules.handlers.backup_manage` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Render the system-backup restore-selection list and store its alias mapping.
- `handle_system_backup_restore_select` | `modules.handlers.backup_manage` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE`, `archive_ref: str` | — | Render one system backup summary and guard-gated restore confirmation controls.
- `handle_system_backup_restore_confirm` | `modules.handlers.backup_manage` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Apply selected system backup restore and render success/failure outcome.

## `modules/handlers/base/__init__.py`
- `status` | `modules.handlers.base.__init__` | `update`, `context` | — | Render the role-scoped status summary for the current target user.

## `modules/handlers/base/conversation_fallbacks.py`
- `register_conversation_handler` | `modules.handlers.base.conversation_fallbacks` | `handler: ConversationHandler` | `None` | Register a ConversationHandler for the implicit-cancel registry walk.
- `iter_registered_conversation_handlers` | `modules.handlers.base.conversation_fallbacks` | — | `Iterable[ConversationHandler]` | Yield ConversationHandlers registered for orphan-state cleanup, in registration order.
- `end_registered_conversations` | `modules.handlers.base.conversation_fallbacks` | `update: Update` | `int` | Force-end any orphaned ConversationHandler state for this update key and return count ended.
- `build_implicit_cancel_fallbacks` | `modules.handlers.base.conversation_fallbacks` | — | `list[CommandHandler]` | Build lazy cancel+dispatch fallback handlers for alerts, birthdays, help, manage, settings, status, and tags.

## `modules/handlers/base/help.py`
- `help_command` | `modules.handlers.base.help` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Starts the role-aware help guide by sending only the first section.
- `handle_help_callback` | `modules.handlers.base.help` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Handle paginated help callbacks and send the requested next section.

## `modules/handlers/base/lifecycle.py`
- `cancel` | `modules.handlers.base.lifecycle` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Exit active transient flows, force-end orphaned conversations for this user, and remove timezone-share UI when needed.

## `modules/handlers/base/onboarding.py`
- `clear_start_request_context` | `modules.handlers.base.onboarding` | `user_data` | — | Clear temporary /start access-request fields from user context.
- `start` | `modules.handlers.base.onboarding` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Entry point with whitelist check and user space setup.
- `handle_start_request_callback` | `modules.handlers.base.onboarding` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Handle onboarding access-request callbacks with fail-closed semantics.

## `modules/handlers/base/settings.py`
- `build_settings_keyboard` | `modules.handlers.base.settings` | — | — | Build the top-level settings dashboard keyboard.
- `build_settings_placeholder_keyboard` | `modules.handlers.base.settings` | — | — | Build a back-only keyboard for placeholder settings sections.
- `build_settings_placeholder_status` | `modules.handlers.base.settings` | `section` | — | Build placeholder text and keyboard for unimplemented settings sections.
- `settings` | `modules.handlers.base.settings` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Settings entrypoint.
- `handle_settings_callback` | `modules.handlers.base.settings` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Route settings callbacks across backup, birthday, and timezone subflows.

## `modules/handlers/base/settings_backup.py`
- `build_settings_backup_keyboard` | `modules.handlers.base.settings_backup` | — | — | Build the settings Backups panel keyboard with combined export/import actions.
- `handle_settings_backup` | `modules.handlers.base.settings_backup` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Render the Backups section under /settings.
- `handle_settings_backup_export` | `modules.handlers.base.settings_backup` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Build and send one Telegram export backup from the settings Backups panel.
- `handle_settings_backup_import` | `modules.handlers.base.settings_backup` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Arm ZIP import mode and prompt the user to send a backup archive document.
- `handle_settings_backup_mail` | `modules.handlers.base.settings_backup` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Open the mail backup subpanel from settings Backups.
- `handle_settings_backup_restore` | `modules.handlers.base.settings_backup` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Show restore guidance pointing users to /manage -> Backups for server restore.

## `modules/handlers/base/settings_bday.py`
- `normalize_time_input` | `modules.handlers.base.settings_bday` | `raw` | — | Normalize HH:MM text into zero-padded 24-hour format.
- `build_birthday_time_keyboard` | `modules.handlers.base.settings_bday` | — | — | Build the birthdays settings keyboard for time and bulk actions.
- `build_birthday_bulk_export_mode_keyboard` | `modules.handlers.base.settings_bday` | — | — | Build the bulk birthday export mode selection keyboard.
- `build_birthday_bulk_export_mode_status` | `modules.handlers.base.settings_bday` | — | — | Build bulk birthday export status text and keyboard.
- `build_birthday_bulk_import_decision_keyboard` | `modules.handlers.base.settings_bday` | — | — | Build the decision keyboard for birthday bulk import review.
- `build_birthday_bulk_import_prompt_keyboard` | `modules.handlers.base.settings_bday` | — | — | Build the birthday bulk import prompt keyboard.
- `build_birthday_zodiac_keyboard` | `modules.handlers.base.settings_bday` | — | — | Build the birthday zodiac mode selection keyboard.
- `build_birthday_zodiac_status` | `modules.handlers.base.settings_bday` | `prefs` | — | Build zodiac settings status text and keyboard for birthdays.
- `build_birthday_time_status` | `modules.handlers.base.settings_bday` | `prefs` | — | Build birthday time settings status text and keyboard.

## `modules/handlers/base/settings_mail.py`
- `build_mail_set_prompt_message` | `modules.handlers.base.settings_mail` | `prefs` | — | Build the prompt message for setting the backup email address.
- `build_mail_set_prompt_keyboard` | `modules.handlers.base.settings_mail` | `prefs` | — | Builds the Set Mail prompt keyboard.
- `build_mail_backup_keyboard` | `modules.handlers.base.settings_mail` | `prefs`, `smtp_available` | — | Build mail-backup controls based on email, reminder, and service state.
- `build_mail_backup_reminder_keyboard` | `modules.handlers.base.settings_mail` | `prefs` | — | Build quick actions for the backup-email reminder prompt.
- `build_mail_backup_reminder_message` | `modules.handlers.base.settings_mail` | `prefs` | — | Build the reminder message shown when backup email is unset.
- `build_mail_backup_status` | `modules.handlers.base.settings_mail` | `prefs`, `size_bytes` | — | Build mail-backup status text and action keyboard.
- `build_backup_email_sent_notification` | `modules.handlers.base.settings_mail` | `from_email`, `to_email`, `size_bytes`, `reason`, `sent_at_iso` | — | Build the plain HTML text notifying the user of a successful backup email dispatch.

## `modules/handlers/base/settings_tz.py`
- `build_timezone_keyboard` | `modules.handlers.base.settings_tz` | `prefs` | — | Build timezone settings controls for mode and source selection.
- `build_location_request_keyboard` | `modules.handlers.base.settings_tz` | — | — | Build a one-tap reply keyboard that requests location sharing.
- `build_timezone_status` | `modules.handlers.base.settings_tz` | `prefs` | — | Build timezone status text and settings keyboard from user preferences.
- `handle_timezone_query_input` | `modules.handlers.base.settings_tz` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Handle manual timezone query input and persist a selected timezone.
- `handle_timezone_location_input` | `modules.handlers.base.settings_tz` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Handle shared-location timezone detection and persist auto timezone.

## `modules/handlers/base/status.py`
- `get_size_format` | `modules.handlers.base.status` | `b`, `factor`, `suffix` | — | Scale bytes to its proper format (e.g., 125.50MB)
- `get_dir_size` | `modules.handlers.base.status` | `path` | — | Calculate total size of a directory
- `get_file_size` | `modules.handlers.base.status` | `path` | — | Return file size in bytes, falling back to zero when unavailable.
- `get_user_dirs` | `modules.handlers.base.status` | — | — | Return numeric user directories that contain an alerts database file.
- `status` | `modules.handlers.base.status` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Render the role-scoped status summary for the current target user.

## `modules/handlers/birthday_flow/bulk_birthdays.py`
- `collapse_internal_spaces` | `modules.handlers.birthday_flow.bulk_birthdays` | `value` | — | Trim and collapse all internal whitespace runs to a single space.
- `contains_disallowed_control_chars` | `modules.handlers.birthday_flow.bulk_birthdays` | `value` | — | Return True if the input contains ASCII control characters.
- `validate_bulk_separator_policy` | `modules.handlers.birthday_flow.bulk_birthdays` | `line` | — | Validate strict `::` separator policy for one bulk-import line.
- `split_bulk_line_sections` | `modules.handlers.birthday_flow.bulk_birthdays` | `line` | — | Split a valid bulk-import line into three trimmed sections.
- `normalize_date_separators` | `modules.handlers.birthday_flow.bulk_birthdays` | `raw_date` | — | Normalize accepted date separators to '/'.
- `split_normalized_date_tokens` | `modules.handlers.birthday_flow.bulk_birthdays` | `raw_date` | — | Return normalized numeric date tokens or None when date token is malformed.
- `parse_birthday_date_token` | `modules.handlers.birthday_flow.bulk_birthdays` | `raw_date` | — | Parse one birthday date token into storage-normalized values.
- `parse_bulk_birthday_line` | `modules.handlers.birthday_flow.bulk_birthdays` | `line_text`, `line_no`, `max_name_len` | — | Parse one bulk birthday line after empty-line filtering.
- `count_invalid_reasons` | `modules.handlers.birthday_flow.bulk_birthdays` | `invalid_entries` | — | Count invalid-entry reason codes from bulk birthday parse results.
- `build_bulk_export_lines` | `modules.handlers.birthday_flow.bulk_birthdays` | `birthdays`, `mode` | — | Build text blocks for bulk birthday export.
- `chunk_text_blocks` | `modules.handlers.birthday_flow.bulk_birthdays` | `blocks`, `safe_limit` | — | Chunk semantic text blocks into Telegram-safe message chunks.
- `build_import_preview_blocks` | `modules.handlers.birthday_flow.bulk_birthdays` | `parsed_result`, `tag_analysis`, `safe_limit`, `max_invalid_preview` | — | Build HTML preview blocks for the parsed bulk-import payload.
- `build_import_final_confirmation_blocks` | `modules.handlers.birthday_flow.bulk_birthdays` | `entries`, `safe_limit` | — | Build HTML final-confirmation blocks for entries about to be imported.
- `analyze_import_tags` | `modules.handlers.birthday_flow.bulk_birthdays` | `valid_entries`, `user_tags`, `suggestion_threshold` | — | Resolve provided import tags against user tags and compute fuzzy suggestions.
- `parse_bulk_birthday_message` | `modules.handlers.birthday_flow.bulk_birthdays` | `raw_text`, `max_lines`, `max_name_len` | — | Parse a multi-line bulk birthday payload.

## `modules/handlers/birthday_flow/flow.py`
- `parse_birthday_date_input` | `modules.handlers.birthday_flow.flow` | `raw_text`, `current_year` | — | Parse and validate birthday input for DD/MM and DD/MM/YYYY formats.
- `start_birthday_add` | `modules.handlers.birthday_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Start birthday creation and initialize a type-6 draft payload.
- `birthday_get_title` | `modules.handlers.birthday_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Validate birthday name input and route to date collection.
- `birthday_confirm_name` | `modules.handlers.birthday_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Handle single-word name confirmation before date entry.
- `birthday_get_date` | `modules.handlers.birthday_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Validate birthday date input, persist normalized fields, and route to settings.
- `birthday_show_tags_menu` | `modules.handlers.birthday_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Show available tags for birthday creation and initialize selection state.
- `show_birthday_settings_menu` | `modules.handlers.birthday_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Render birthday-specific settings for pre-alert and additional info.
- `handle_birthday_setting_choice` | `modules.handlers.birthday_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Route birthday settings actions to the selected follow-up step.
- `birthday_tags_toggle` | `modules.handlers.birthday_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Toggle birthday tag selections and finalize when DONE is pressed.
- `birthday_save_after_tags` | `modules.handlers.birthday_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Persist the staged birthday alert after tag selection completes.
- `birthday_cancel` | `modules.handlers.birthday_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Cancel birthday flow, clear transient context, and end registered conversation state for this user.

## `modules/handlers/birthday_flow/list_view.py`
- `birthday_list_start` | `modules.handlers.birthday_flow.list_view` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Send the birthday tag filter menu with orphan-aware guidance when needed.
- `show_birthdays_list` | `modules.handlers.birthday_flow.list_view` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE`, `manual_tag`, `manual_page` | — | Show a paginated birthday list for the selected tag filter, including orphan mode.
- `show_next_birthdays` | `modules.handlers.birthday_flow.list_view` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Render next birthdays in LAST/TODAY/NEXT sections with alias and pre-alert rows.

## `modules/handlers/birthday_flow/menu.py`
- `get_birthday_tag_stats` | `modules.handlers.birthday_flow.menu` | `user_data` | — | Return birthday tag usage stats and untagged count from user data.
- `build_birthday_home_text` | `modules.handlers.birthday_flow.menu` | `tags`, `stats`, `untagged` | — | Build birthday home text with per-tag birthday counts.
- `build_birthday_home_keyboard` | `modules.handlers.birthday_flow.menu` | `action_prefix` | — | Build the birthday home action keyboard.
- `build_toggle_keyboard` | `modules.handlers.birthday_flow.menu` | `items`, `selected_items`, `callback_prefix`, `cols` | — | Build a birthday toggle keyboard with a DONE action.

## `modules/handlers/birthday_flow/message_suggestions/callbacks.py`
- `build_bday_noted_callback` | `modules.handlers.birthday_flow.message_suggestions.callbacks` | `alert_id: str`, `original_time: datetime | None`, `occurrence_time: datetime | None` | `str` | Build a tokenized birthday-noted callback that preserves occurrence context.
- `decode_bday_noted_callback` | `modules.handlers.birthday_flow.message_suggestions.callbacks` | `callback_data: str` | `dict[str, Any]` | Decode birthday-noted callback payloads with codec-first and legacy fallback support.
- `build_bday_msg_callback` | `modules.handlers.birthday_flow.message_suggestions.callbacks` | `style: str`, `alert_id: str`, `occurrence_time: datetime | None` | `str` | Build a tokenized birthday-style callback that preserves occurrence context.
- `decode_bday_msg_callback` | `modules.handlers.birthday_flow.message_suggestions.callbacks` | `callback_data: str` | `dict[str, Any]` | Decode birthday-style callback payloads with codec-first and legacy fallback support.

## `modules/handlers/birthday_flow/message_suggestions/catalog.py`
- `ArchiveValidationError` | `modules.handlers.birthday_flow.message_suggestions.catalog` | — | — | Represent archive-validation failures with structured mode/index/field metadata.
- `get_archive_modes` | `modules.handlers.birthday_flow.message_suggestions.catalog` | — | — | Return supported birthday message archive mode names.
- `clear_archive_cache` | `modules.handlers.birthday_flow.message_suggestions.catalog` | — | — | Clear the in-memory birthday message archive cache.
- `get_archive_path` | `modules.handlers.birthday_flow.message_suggestions.catalog` | `mode` | — | Return the JSON archive path for the requested message mode.
- `validate_archive_entries` | `modules.handlers.birthday_flow.message_suggestions.catalog` | `entries`, `mode`, `allow_empty` | — | Validate and normalize archive entries against schema and enum/range constraints.
- `load_archive` | `modules.handlers.birthday_flow.message_suggestions.catalog` | `mode`, `allow_empty`, `use_cache` | — | Load, validate, cache, and clone archive entries for the requested message mode.

## `modules/handlers/birthday_flow/message_suggestions/handlers.py`
- `handle_bday_noted` | `modules.handlers.birthday_flow.message_suggestions.handlers` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Handle birthday-noted callbacks and send the message-style prompt.
- `handle_bday_msg_style` | `modules.handlers.birthday_flow.message_suggestions.handlers` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Handle birthday style selection and send generated style output.

## `modules/handlers/birthday_flow/message_suggestions/inference.py`
- `infer_tag_groups` | `modules.handlers.birthday_flow.message_suggestions.inference` | `tags: Any` | `list[str]` | Infer canonical tag groups from birthday tag values.
- `infer_title_hints` | `modules.handlers.birthday_flow.message_suggestions.inference` | `title: Any` | `list[str]` | Infer title-hint categories from normalized birthday title text.
- `infer_gender_hint` | `modules.handlers.birthday_flow.message_suggestions.inference` | `title: Any`, `title_hints: list[str] | None` | `str` | Infer gender hint from title tokens and inferred title hints.
- `infer_turning_age` | `modules.handlers.birthday_flow.message_suggestions.inference` | `alert: dict[str, Any] | None`, `occurrence_time: datetime | None`, `occurrence_year: int | None` | `int | None` | Infer turning age for the occurrence year when birth year is valid.
- `infer_message_context` | `modules.handlers.birthday_flow.message_suggestions.inference` | `alert: dict[str, Any] | None`, `occurrence_time: datetime | None`, `occurrence_year: int | None` | `dict[str, Any]` | Build message-selection context from alert metadata and occurrence timing.
- `infer_zodiac_context` | `modules.handlers.birthday_flow.message_suggestions.inference` | `alert: dict[str, Any] | None`, `user_prefs: dict[str, Any] | None` | `dict[str, Any]` | Infer zodiac context for birthday message generation.

## `modules/handlers/birthday_flow/message_suggestions/selector.py`
- `select_template` | `modules.handlers.birthday_flow.message_suggestions.selector` | `entries: list[dict[str, Any]] | None`, `context: dict[str, Any] | None`, `rng: random.Random | None` | `dict[str, Any]` | Select a template through staged fallback filters and weighted random choice.
- `select_template_from_mode` | `modules.handlers.birthday_flow.message_suggestions.selector` | `mode: str`, `context: dict[str, Any] | None`, `rng: random.Random | None` | `dict[str, Any]` | Load mode archive entries and select a template via staged fallback rules.

## `modules/handlers/birthday_flow/message_suggestions/zodiac_assembler.py`
- `assemble_zodiac_message` | `modules.handlers.birthday_flow.message_suggestions.zodiac_assembler` | `western_info: dict | None`, `eastern_info: dict | None`, `turning_age: int | None`, `title: str | None`, `use_western: bool`, `use_eastern: bool`, `rng: _random.Random | None` | `str | None` | Procedurally assemble an Italian birthday message incorporating zodiac traits.

## `modules/handlers/birthday_flow/render.py`
- `format_compact_date` | `modules.handlers.birthday_flow.render` | `dt` | — | Return a compact date label and include year only when needed.
- `build_compact_birthday_lines` | `modules.handlers.birthday_flow.render` | `page_items`, `default_time`, `user_prefs` | — | Build compact birthday list rows using resolved pre-alert datetime labels when due context exists.
- `format_bday_pre_alerts` | `modules.handlers.birthday_flow.render` | `data`, `due_dt`, `user_prefs` | — | Render birthday pre-alert labels and fallback to `None` when nothing is renderable.
- `format_bday_additional_info` | `modules.handlers.birthday_flow.render` | `data` | — | Return a compact birthday additional-info preview, or `None` when empty.
- `format_birthday_summary` | `modules.handlers.birthday_flow.render` | `data`, `alert_id`, `user_prefs` | — | Build a Markdown-safe birthday summary with resolved pre-alert labels when available.
- `format_search_due` | `modules.handlers.birthday_flow.render` | `dt` | — | Return a search-facing due label, or `Not scheduled` when missing.

## `modules/handlers/birthday_flow/search.py`
- `rank_birthdays_by_name` | `modules.handlers.birthday_flow.search` | `query_text`, `birthdays` | — | Rank birthdays by normalized title similarity against the query text.

## `modules/handlers/birthdays.py`
- `birthday_start` | `modules.handlers.birthdays` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Render the birthdays home menu with tag stats and markdown fallback handling.
- `handle_birthday_menu` | `modules.handlers.birthdays` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Route birthday menu callbacks while preserving single-answer semantics.
- `birthday_search` | `modules.handlers.birthdays` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Fuzzy-search birthdays by title/name.
- `birthday_search_from_text` | `modules.handlers.birthdays` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Runs birthday search from free-text input after pressing birthday search button.

## `modules/handlers/developer.py`
- `handle_developer_shortcut_user` | `modules.handlers.developer` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE`, `target_id: str` | `None` | Handle developer user shortcut commands and render user detail cards.
- `handle_developer_callback` | `modules.handlers.developer` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Route developer dashboard callbacks for roles, acting-as, and system actions.

## `modules/handlers/edit_flow/dashboard.py`
- `build_edit_dashboard_keyboard` | `modules.handlers.edit_flow.dashboard` | `alert_type` | — | Build the edit-dashboard keyboard with direct same-type schedule edit actions.
- `format_edit_dashboard_text` | `modules.handlers.edit_flow.dashboard` | `temp_alert`, `user_prefs` | — | Build edit-dashboard summary text with resolved pre-alert labels when schedule context exists.

## `modules/handlers/edit_flow/delegates.py`
- `configure_edit_dependencies` | `modules.handlers.edit_flow.delegates` | `return_to_edit`, `show_edit_dashboard` | — | Configure flow-owned callback dependencies used by delegation wrappers.
- `ask_time` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate edit-flow time prompting to the shared add-flow implementation.
- `prompt_type_specific_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate type-specific schedule prompting for edit flow.
- `get_interval_prompt_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Show the shared interval prompt and return to edit flow context.
- `get_interval_input_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate interval text input handling for edit flow.
- `get_interval_callback_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate interval quick-button handling for edit flow.
- `daily_interval_confirm_callback_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate daily-interval confirmation handling for edit flow.
- `interval_mode_choice_callback_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate daily interval mode choice callbacks while keeping edit-flow context.
- `fuzzy_mean_std_input_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate daily fuzzy mean/std parsing while returning to the edit dashboard.
- `get_start_date_callback_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate start-date callback handling for edit flow.
- `get_start_date_input_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate start-date text input handling for edit flow.
- `get_time_input_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate time text input handling for edit flow.
- `get_time_callback_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate default-time callback handling for edit flow.
- `show_pre_alert_menu` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate pre-alert menu rendering to shared add-flow handlers.
- `get_pre_alert_callback_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate pre-alert callback handling while returning to edit flow.
- `get_custom_pre_alert_input_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate custom pre-alert parsing and preview handling for edits.
- `confirm_custom_pre_alert_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate custom pre-alert confirmation handling for edits.
- `show_photo_menu_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate photo menu rendering to shared add-flow handlers.
- `show_repetition_menu_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Show repetition options and normalize unsupported returns for edit flow.
- `prompt_repetition_until_date_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate repetition-until prompt rendering for edit flow.
- `prompt_repetition_count_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate repetition-count prompt rendering for edit flow.
- `handle_repetition_choice_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate repetition mode choice handling for edit flow.
- `handle_repetition_until_date_input_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate repetition-until input handling for edit flow.
- `handle_repetition_count_input_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate repetition-count input handling for edit flow.
- `get_photo_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate photo upload handling for edit flow.
- `reject_document_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate document rejection handling for edit flow.
- `photo_back_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate photo-step back navigation for edit flow.
- `remove_photo_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate staged photo removal for edit flow.
- `prompt_additional_info` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate additional-info prompting for edit flow.
- `handle_additional_info_input_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate additional-info input handling for edit flow.
- `handle_additional_info_skip_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate additional-info skip handling for edit flow.
- `handle_additional_info_clear_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate explicit Additional Info clear handling and return to edit dashboard context.
- `type_1_days_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate monthly-days schedule handling for edit flow.
- `type_2_ordinal_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate relative-month ordinal handling for edit flow.
- `type_2_fifth_policy_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate fifth-occurrence policy handling for edit flow.
- `type_2_weekday_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate relative-month weekday handling for edit flow.
- `type_3_weekdays_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate weekly weekday handling for edit flow.
- `type_4_dates_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate yearly date handling for edit flow.
- `type_5_date_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate one-time date handling for edit flow.
- `tags_toggle_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate tag toggle handling for edit flow.
- `handle_change_type_callback_edit` | `modules.handlers.edit_flow.delegates` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate type-change callbacks while preserving edit routing.

## `modules/handlers/edit_flow/flow.py`
- `show_edit_dashboard` | `modules.handlers.edit_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Render the edit dashboard with media-aware callback editing and resolved pre-alert labels.
- `start_edit` | `modules.handlers.edit_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Start an edit session and fail soft with cleanup if dashboard bootstrap fails.
- `handle_edit_choice` | `modules.handlers.edit_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Route edit-dashboard callbacks and render prompts with media-aware callback edits.
- `handle_edit_name_input` | `modules.handlers.edit_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Validate renamed alert text and return to the edit dashboard.
- `prompt_birthday_date_edit` | `modules.handlers.edit_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Prompt for birthday date edits and render with media-aware callback editing.
- `type_6_date_edit` | `modules.handlers.edit_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Validate birthday date edits, persist normalized fields, and log reasoned outcomes.
- `commit_edit` | `modules.handlers.edit_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Persist edit-session changes, apply scheduler side effects, and enforce terminal restore/cleanup contract.
- `cancel_edit` | `modules.handlers.edit_flow.flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Cancel edit flow, clear transient context, and end registered conversation state for this user.

## `modules/handlers/export_import.py`
- `discard_backup_import_session` | `modules.handlers.export_import` | `user_data` | `dict | None` | Clear a pending backup import session and remove its staged archive best-effort.
- `handle_settings_backup_import_confirm` | `modules.handlers.export_import` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Run a pending user import from the stored session archive and clean up session state.
- `handle_settings_backup_import_cancel` | `modules.handlers.export_import` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Cancel a pending user import, discard the staged archive, and clear session state.
- `export_command` | `modules.handlers.export_import` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Export user data as a zip archive.
- `import_command` | `modules.handlers.export_import` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Import user data from a previously exported archive.
- `handle_import_document_upload` | `modules.handlers.export_import` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Consumes a pending /import flow when the next document is uploaded.

## `modules/handlers/ghost_flow.py`
- `handle_missed_dtl` | `modules.handlers.ghost_flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Open the ghost picker for one missed-summary alert button.
- `handle_ghost_set` | `modules.handlers.ghost_flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Create a ghost reminder with one quick-duration picker token.
- `handle_ghost_set_custom` | `modules.handlers.ghost_flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Switch ghost creation to custom datetime input mode.
- `handle_ghost_custom_text` | `modules.handlers.ghost_flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Parse custom ghost time text and create or deduplicate the reminder.
- `handle_ghost_dedup_confirm` | `modules.handlers.ghost_flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Confirm duplicate ghost creation after explicit user approval.
- `handle_ghost_dedup_cancel` | `modules.handlers.ghost_flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Cancel duplicate ghost creation and clear in-memory picker state.
- `handle_ghost_noop` | `modules.handlers.ghost_flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Acknowledge no-op ghost summary buttons after creation.
- `handle_ghost_noted` | `modules.handlers.ghost_flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Acknowledge ghost notification noted action without mutating storage.
- `handle_ghost_dtl` | `modules.handlers.ghost_flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Open source alert details or explain source deletion for a ghost notification.
- `handle_ghost_del` | `modules.handlers.ghost_flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Show delete-confirmation prompt for a ghost notification.
- `handle_ghost_del_confirm` | `modules.handlers.ghost_flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delete ghost alert after explicit confirmation and remove confirmation state.
- `handle_ghost_del_cancel` | `modules.handlers.ghost_flow` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Restore original ghost notification keyboard after delete cancellation.

## `modules/handlers/list_alerts/compact_list.py`
- `show_alerts_list` | `modules.handlers.list_alerts.compact_list` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE`, `manual_tag`, `manual_page` | — | Show a paginated alert list for the selected tag filter, including orphan mode.

## `modules/handlers/list_alerts/detail.py`
- `format_standard_card` | `modules.handlers.list_alerts.detail` | `alert` | — | Render the compact standard card text used by list/manage entry views.
- `format_detailed_card` | `modules.handlers.list_alerts.detail` | `alert`, `user_prefs` | — | Render the public detail card text for alerts and birthdays.
- `build_info_keyboard` | `modules.handlers.list_alerts.detail` | `alert_id`, `context`, `source`, `include_back`, `alert` | — | Build the list-origin detail keyboard via the shared UI keyboard builder.
- `get_info_text_and_kb` | `modules.handlers.list_alerts.detail` | `alert`, `context`, `source`, `include_back`, `user_prefs` | — | Generate detailed text and keyboard for an info view.
- `send_alert_detail_by_id` | `modules.handlers.list_alerts.detail` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE`, `alert_id`, `source_hint`, `include_back: bool` | — | Open detailed view for one alert or birthday by ID.

## `modules/handlers/list_alerts/filter_menu.py`
- `list_alerts_start` | `modules.handlers.list_alerts.filter_menu` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Send the /list filter menu with known tags and optional orphan-tag warning.

## `modules/handlers/list_alerts/manage_actions.py`
- `build_manage_list_keyboard` | `modules.handlers.list_alerts.manage_actions` | `alert_id` | — | Build manage-list action keyboard for a specific alert id.
- `handle_management` | `modules.handlers.list_alerts.manage_actions` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Handle alert-management callbacks for list/detail cards.
- `refresh_alert_message` | `modules.handlers.list_alerts.manage_actions` | `query`, `user_id`, `alert_id`, `storage` | — | Refresh an alert list card after mutations with resolved pre-alert labels.
- `handle_edit_text_input` | `modules.handlers.list_alerts.manage_actions` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Handle free-text updates for additional_info from list or birthday detail views.

## `modules/handlers/manage.py`
- `build_manage_keyboard` | `modules.handlers.manage` | `role`, `target_id` | — | Build manage-dashboard controls based on elevated role and acting target.
- `build_manage_text` | `modules.handlers.manage` | `role`, `target_id`, `target_label` | — | Build manage-dashboard header text with optional acting-as context.
- `manage_dashboard_start` | `modules.handlers.manage` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Start the manage dashboard for authorized elevated roles.
- `handle_manage_callback` | `modules.handlers.manage` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Route manage dashboard callbacks to admin/developer feature handlers.

## `modules/handlers/next_alerts.py`
- `show_next_alerts` | `modules.handlers.next_alerts` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Displays the exactly next 7 items in the schedule.

## `modules/handlers/notification_context.py`
- `NotificationContext` | `modules.handlers.notification_context` | — | — | Store notification-origin metadata derived from inline callback payloads.
- `from_message` | `NotificationContext` | `message`, `alert_id: str` | `'NotificationContext'` | Derive notification origin and timing context by inspecting inline keyboard callbacks.

## `modules/handlers/scheduler_handlers.py`
- `handle_postpone_menu` | `modules.handlers.scheduler_handlers` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Open postpone options keyboard for a parsed notification callback payload.
- `handle_postpone_set` | `modules.handlers.scheduler_handlers` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Apply selected postpone duration and restore notification keyboard state.
- `handle_postpone_custom` | `modules.handlers.scheduler_handlers` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Prompt for custom postpone expressions while preserving cancel semantics.
- `handle_custom_postpone_input` | `modules.handlers.scheduler_handlers` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Parse custom postpone expressions, validate them, and persist postpone state.
- `handle_prealert_info` | `modules.handlers.scheduler_handlers` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Render the notification-origin pre-alert detail card in place.
- `handle_alert_info` | `modules.handlers.scheduler_handlers` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Render the notification-origin due-alert detail card in place.
- `handle_notif_back` | `modules.handlers.scheduler_handlers` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Restore the original notification view from a notification-detail card.
- `handle_alert_toggle` | `modules.handlers.scheduler_handlers` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Toggle alert active state and refresh detail or notification controls.
- `handle_alert_delete` | `modules.handlers.scheduler_handlers` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Handle delete confirmation flow for alert deletion callbacks.
- `handle_placebo_done` | `modules.handlers.scheduler_handlers` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Handle ✅ DONE ! button on main (non-birthday) alerts.
- `handle_placebo_noted` | `modules.handlers.scheduler_handlers` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Handle 👀 NOTED ! button on pre-alerts (all types).
- `handle_bday_noted` | `modules.handlers.scheduler_handlers` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate birthday-noted callback handling to message-suggestion module.
- `handle_bday_msg_style` | `modules.handlers.scheduler_handlers` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Delegate birthday style callback handling to message-suggestion module.
- `handle_alert_done` | `modules.handlers.scheduler_handlers` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Handle legacy done callbacks and finalize alert completion messaging.
- `handle_pre_alert_ack` | `modules.handlers.scheduler_handlers` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Handle legacy pre-alert acknowledgment by removing inline controls.
- `get_scheduler_handlers` | `modules.handlers.scheduler_handlers` | — | — | Return callback handlers for scheduler notification actions.
- `get_custom_postpone_text_handler` | `modules.handlers.scheduler_handlers` | — | — | Return the text handler that routes custom postpone input messages.

## `modules/handlers/shortcut_router.py`
- `handle_dynamic_shortcut_command` | `modules.handlers.shortcut_router` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Handles:

## `modules/handlers/tags_dashboard.py`
- `tags_dashboard_start` | `modules.handlers.tags_dashboard` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Render the /tags dashboard with per-tag alert counts and Add/Edit/Delete action buttons.
- `show_delete_menu` | `modules.handlers.tags_dashboard` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE`, `as_new_message` | — | Show tag deletion options and store callback token mappings.
- `show_edit_menu` | `modules.handlers.tags_dashboard` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE`, `as_new_message` | — | Show the tag list as selectable buttons for rename; mirrors show_delete_menu.
- `handle_tag_callbacks` | `modules.handlers.tags_dashboard` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Dispatch all manage_tag_* callback actions: add, edit, delete, and navigation.

## `modules/handlers/user_list.py`
- `resolve_user_detail_back_cb` | `modules.handlers.user_list` | `context`, `actor_role` | — | Resolve the back callback target for user-detail views.
- `build_user_detail_keyboard` | `modules.handlers.user_list` | `actor_role`, `target_role`, `target_id`, `actor_id`, `back_cb` | — | Build role-aware user detail action keyboard for admin/developer flows.
- `summarize_user_data` | `modules.handlers.user_list` | `data` | — | Summarize alert, birthday, and tag counts from user data payloads.
- `format_user_summary` | `modules.handlers.user_list` | `summary`, `last_seen`, `first_start` | — | Format compact whitelist stats triplets with an activity icon for one user row.
- `build_users_text` | `modules.handlers.user_list` | `entries`, `meta_map`, `summary_map`, `include_alias`, `empty_text` | — | Build whitelist user list text using summary and activity metadata.
- `is_message_not_modified_error` | `modules.handlers.user_list` | `error: Exception` | `bool` | Return whether an error represents Telegram message-not-modified no-op.
- `normalize_render_reason` | `modules.handlers.user_list` | `reason` | `str | None` | Normalize render failure reasons to the allowed audit reason set.
- `log_user_detail_render` | `modules.handlers.user_list` | `storage`, `actor_id`, `actor_role`, `target_id`, `target_role`, `source`, `delivery`, `text`, `ok`, `reason` | — | Log user-detail render outcomes to user events and admin audit stream.
- `show_user_list` | `modules.handlers.user_list` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE`, `storage`, `role: str`, `origin: str | None` | `None` | Render the whitelist user list, chunk oversized output, and persist alias mapping context.
- `userlist_command` | `modules.handlers.user_list` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | `None` | Handle `/userlist` command with elevated-role authorization checks.
- `build_scoped_user_alias_chunks` | `modules.handlers.user_list` | `storage`, `role_filter`, `include_alias` | — | Build Telegram-safe user-list chunks and alias mapping for an optional role scope.
