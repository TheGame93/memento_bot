# Logging Policy

This policy defines what we log, where it goes, and how long we keep it. The goal is
operational visibility without storing user message content.

## Principles

- **No message bodies** in logs. Use lengths + hashes instead.
- **Minimal payloads**: identifiers, timestamps, short labels, and counts.
- **User activity tracking** uses the user-scoped log only.
- **Scheduler outcomes** are logged in both user and global logs.

## Global Logs (data/systemlog.d/)

All global logs are JSONL and rotate daily.
All system/global records emitted via `log_system(...)` include a top-level `identity` tag:
- `instance_tag`
- `project_root_hash`
- `data_dir_hash`
- `project_root_name`
- `data_dir_name`

### system.log (retention: 90 days)
Purpose: cross-cut summary stream.
Events:
- startup/shutdown summary
- daily health/usage rollups
- backup retention summary

### errors.log (retention: 180 days)
Purpose: unhandled exceptions and tracebacks.
Events:
- unhandled exceptions with metadata (user_id, chat_id, callback_data, message_id)

### scheduler.log (retention: 60 days)
Purpose: scheduler outcomes and decisions.
Events:
- alert_sent / alert_send_failed
- pre_alert_sent / pre_alert_send_failed
  - includes discriminator `pre_alert_kind` (`duration` | `birthday_evening_before`)
- alert_snoozed / alert_marked_done
- repetition_consume_failed (warning; repetition-helper/storage consumption failure diagnostics)
- repetition_exhausted (occurrence-consumption exhaustion/deactivation outcome)
- repetition_exhaustion_deactivate_failed (warning; storage deactivation failure after exhaustion)
- missed_alerts_summary_sent
- missed_pre_offline_window (startup offline-window derivation metadata: source/reliability/reason_code)
  - Includes provenance diagnostics fields: `instance_tag_current`, `instance_tag_state`, `identity_match`, `last_pid_alive`.
- missed_pre_candidate_skipped (pre-alert missed-classification skip diagnostics with reason_code)
- scheduler_tick_slow (warning event when scheduler tick duration crosses threshold)
- scheduler_alert_media_attempt / scheduler_alert_media_result

`missed_pre_offline_window.reason_code` (current set):
- `ok_last_shutdown`
- `last_exit_running`
- `runtime_identity_missing`
- `runtime_identity_mismatch`
- `last_pid_still_alive`
- `shutdown_before_startup_fallback_startup`
- `shutdown_before_startup`
- `shutdown_after_window_end_fallback_startup`
- `shutdown_after_window_end`
- `invalid_last_shutdown_fallback_startup`
- `invalid_last_shutdown`
- `missing_last_shutdown_fallback_startup`
- `invalid_last_startup`
- `missing_runtime_timestamps`

`repetition_consume_failed.reason_code` (current set):
- `helper_missing`
- `invalid_helper_response`
- `storage_failure`

`alert_sent` payload semantics:
- Always keep `scheduled_time` as the occurrence time reference.
- Include postponed-disambiguation fields:
  - `is_postponed` (bool)
  - `postpone_id` (nullable)
  - `effective_fire_time` (nullable ISO timestamp)
  - `postpone_count` (int, non-negative)
- Non-postponed sends must log explicit defaults: `is_postponed=false`, `postpone_id=null`, `effective_fire_time=null`, `postpone_count=0`.
- For recurring alerts, include repetition outcome fields:
  - `repetition_counted` (bool; whether this send consumed repetition count)
  - `repetition_exhausted` (bool; whether this occurrence exhausted/deactivated repetition)

### api.log (retention: 30 days)
Purpose: Telegram API latency, retries, and failures.
Events:
- send_message / send_photo / edit_message_text (+ failures)
- api_call_slow (warning event when wrapped API call duration crosses threshold)
- polling_network_error (immediate warning, capped per aggregation window)
- polling_network_error_rollup (periodic warning rollup for suppressed polling network errors)
- polling_network_recovered (info event after quiet gap, summarizing previous polling-error burst; payload includes `recovery_source=error_path|api_success` and `operation` when available)
- `telegram_call_attempt_noop` for benign no-op API outcomes in `edit_message_text` (`reason_code=message_not_modified`).
- `edit_message_text_noop` for wrapper-level no-op classification (logged as success semantics, not failure).
- `menu_markdown_parse_failed` for deterministic Markdown parse failures in home-menu rendering (`menu=alerts|birthdays`, hash/len only).
- `menu_markdown_fallback_sent` when fallback plain-text menu send succeeds after markdown parse failure.
- `menu_markdown_fallback_failed` when fallback plain-text menu send also fails.
- `telegram_call_attempt_*` payloads include `counts_toward_degraded` (bool) to distinguish API-health failures from deterministic app/input failures.
- Deterministic non-retryable `BadRequest` failures (for example markdown-parse failures) must keep `counts_toward_degraded=false` and must not emit degraded-mode transition events by themselves.

### lifecycle.log (retention: 90 days)
Purpose: process lifecycle & lock events.
Events:
- startup, shutdown, crash, lock acquisition/conflict
- mainbot_lock_acquired (payload: `scope=local|token_global`, `lock_file`, `pid`, `token_hash_prefix` for global scope)
- mainbot_lock_conflict (payload: `scope=local|token_global`, `lock_file`, holder `pid` when available, `token_hash_prefix` for global scope)
- startbot_mainbot_lock_conflict_exit (payload: `exit_code`, `lock_conflict_exit_code`; terminal branch, no respawn)
- startbot_cli_flags (payload: help, clean, new, force_start)
- startbot_cli_help (payload: requested)
- startbot_cli_invalid_args (payload: reason, arg)
- startbot_dns_wait_ok (payload: host, waited_seconds, timeout_seconds, interval_seconds)
- startbot_dns_wait_timeout (payload: host, waited_seconds, timeout_seconds, interval_seconds)
- startbot_dns_wait_skipped (payload: host, reason, timeout/interval when invalid)
- startbot_cleanup_phase_started (payload: clean, new, force_start)
- startbot_cleanup_phase_completed (payload: clean, new, had_failure)
- startbot_cleanup_all_logs_started / startbot_cleanup_all_logs_ok / startbot_cleanup_all_logs_failed
- startbot_cleanup_tests_artifacts_started / startbot_cleanup_tests_artifacts_ok / startbot_cleanup_tests_artifacts_failed
- startbot_cleanup_phase_failed_abort / startbot_cleanup_phase_failed_continue (payload: scope, exit_code)
- startup_scope_snapshot (info snapshot of startup user scope: `dataset_users`, `authorized_users`, `excluded_users`, bounded `excluded_user_ids_sample`, threshold/filter metadata)
- startup_scope_warning (warning when auth filtering is enabled and excluded count crosses threshold)
- startup_scope_snapshot_failed (warning diagnostics when scope scan fails; startup remains non-blocking)
  - `startup_scope_snapshot.warning_suppressed_reason` values:
    - `auth_filter_disabled`
    - `no_excluded_users`
    - `below_threshold`

### storage.log (retention: 90 days)
Purpose: storage integrity and migrations.
Events:
- json decode/recovery
- migrations
- backup creation/retention
- local_image_delete_skipped / local_image_delete_failed (reason-code based)

### onboarding.log (retention: 90 days)

Purpose: events for users not yet whitelisted (request flow, bot messages during approval).

Events:

- Any event_type that would normally go to a user log but the user isn't whitelisted yet.
- Payload includes `user_id` and `note: "user_not_yet_whitelisted"`.

### admin_audit.log (retention: 180 days)
Purpose: privileged operations and access-control audit trail.
Events:
- role/whitelist/invite/request actions from `/manage`
- user-list render outcomes for privileged views (`manage_user_list_rendered`, `manage_user_list_render_failed`)
- user-detail render outcomes for privileged views (`manage_user_detail_rendered`, `manage_user_detail_render_failed`)
- manage storage summary outcomes (`manage_storage_summary_viewed`, `manage_storage_summary_failed`)
  - `manage_storage_summary_viewed` includes delivery metadata (`edited` | `message_not_modified`).

### Backup warning payload contracts

- `email_backup_history_write_failed` (level `WARNING`)
  - Required fields: `user_id`, `reason_code`, `error_class`
  - Current `reason_code` values: `history_write_failed`
- `email_backup_notification_failed` (level `WARNING`)
  - Required fields: `user_id`, `source`, `reason_code`, `error_class`
  - Current `source` values: `monthly`, `startup`
  - Current `reason_code` values: `notification_send_failed`

## User Logs (data/userlog.d/<user_id>_events.log)

User logs are JSONL, rotate daily, and are retained for **90 days**.

For backup/import compatibility, archives still expose user logs as `logs/events.log`.

### Event categories (minimum set)
- **Command usage:** /start /help /status /alerts /list /next /birthdays /birthday /tags /settings /backup_email /export /import /cancel
- **Help navigation telemetry:** `help_step_sent`, `help_next_pressed`, `help_flow_completed_popup`, `help_callback_invalid`
  - metadata-only fields: `step_index`, `step_key`, `current_step_index`, `next_step_index`, `final_step_index`, `role`, `source`, `is_final_step`, `reason_code`
  - invalid callback diagnostics may include compact callback metadata (`callback_data`, requested/total indices), never message text bodies
- **Status rendering telemetry:** `status_rendered`, `status_render_failed`
  - metadata-only payload fields: `viewer_role`, `subject_role`, `has_user_time`, `status_len`,
    `size_data_bytes`, `size_logs_bytes`, `size_backups_bytes`, `fallback_used` (for rendered);
    failures use `reason_code` (`send_failed`, `build_exception_fallback_sent`).
- **Flows:** add alert/birthday start, save, delete, edit, tag add/remove, one_time_year_assumed (date_meta, assumed_year, assumption_kind), one_time_today_year_required_prompt (source, today_short_example, today_full_example, acting-as metadata)
  - Repetition flow telemetry (`add_flow` / `edit_flow` source-aware):
    - `repetition_menu_opened` (metadata-only: `source`, acting-as payload, `current_mode`)
    - `repetition_mode_selected` (metadata-only: `source`, acting-as payload, `mode`)
    - `repetition_forever_set` (metadata-only: `source`, acting-as payload, `mode`)
    - `repetition_until_invalid` (metadata-only: `source`, acting-as payload, `reason_code`, `until_input_meta`)
      - current `reason_code` values: `empty`, `invalid_format_or_date`, `past_date`, `unsupported_type`.
    - `repetition_until_set` (metadata-only: `source`, acting-as payload, `mode`, `until_date`)
    - `repetition_count_invalid` (metadata-only: `source`, acting-as payload, `reason_code`, `count_input_meta`)
    - `repetition_count_set` (metadata-only: `source`, acting-as payload, `mode`, `count_remaining`)
  - Daily interval telemetry:
    - `daily_interval_prompt_shown` (metadata-only: `source`, acting-as payload)
    - `daily_interval_mode_selected` (metadata-only: `source`, `mode`, acting-as payload)
    - `daily_interval_input_invalid` (metadata-only: `source`, `reason_code`, `interval_input_meta`)
    - `daily_interval_one_confirm_shown` (metadata-only: `source`, acting-as payload)
    - `daily_interval_one_confirmed` (metadata-only: `source`, acting-as payload)
    - `daily_interval_one_change_requested` (metadata-only: `source`, acting-as payload)
    - `daily_interval_set` (metadata-only: `source`, `interval_value`, `has_start_marker`, acting-as payload)
    - `daily_interval_fuzzy_input_invalid` (metadata-only: `source`, `reason_code`, `input_meta`)
    - `daily_interval_fuzzy_rejected` (metadata-only: `source`, `reason_code`, `mean`, `std`)
    - `daily_interval_fuzzy_set` (metadata-only: `source`, `mean`, `std`, `sampled_days`, `next_scheduled`, `shifted`)
    - `daily_interval_fuzzy_time_adjusted` (metadata-only: `source`, `adjusted`, `next_scheduled`)
  - Birthday settings telemetry: `birthday_evening_time_prompt`, `birthday_evening_time_set`, `birthday_evening_time_reset` (metadata-only, includes time value).
  - Birthday zodiac settings telemetry:
    - `birthday_zodiac_view` (metadata-only: `source`, `section`, acting-as payload) — emitted when the zodiac sub-panel is opened.
    - `birthday_zodiac_mode_set` (metadata-only: `mode`, acting-as payload) — emitted when a zodiac mode is selected.
  - Birthday date edit telemetry (`edit_flow`):
    - `birthday_date_edit_prompted` (metadata-only: `source`)
    - `birthday_date_edit_invalid` (metadata-only: `source`, `reason_code`, `date_input_meta`)
    - `birthday_date_edit_set` (metadata-only: `source`, `has_birth_year`, `birth_year`)
    - `birthday_date_edit_invalid.reason_code` (current set):
      - `empty`
      - `invalid_format`
      - `invalid_date`
      - `year_two_digits`
      - `year_in_future`
      - `year_before_1900`
  - Notification-origin edit completion telemetry (`edit_flow`):
    - `edit_origin_detected` (metadata-only: `source`, `alert_id`, `origin_source`, `kind`, `postpone_count`, `has_chat_id_ref`, `has_message_id_ref`, `is_photo_origin`, `has_original_time`, `has_occurrence_time`)
    - `edit_notification_restore_attempted` (metadata-only: `source`, `alert_id`, `kind`, `postpone_count`, `has_chat_id_ref`, `has_message_id_ref`, `is_photo_hint`, `has_original_time`, `has_occurrence_time`)
    - `edit_notification_restore_result` (metadata-only: attempt fields + `success`, `reason_code`)
    - `edit_notification_restore_result.reason_code` (current set):
      - `ok`
      - `message_not_modified`
      - `missing_alert_id`
      - `missing_message_id`
      - `restore_failed`
      - `message_not_found`
      - `chat_not_found`
      - `forbidden`
      - `restore_exception`
  - List-origin edit completion telemetry (`edit_flow`):
    - `edit_list_restore_attempted` (metadata-only: `source`, `alert_id`, `origin_source`, `source_hint`, `include_back`, `has_chat_id_ref`, `has_message_id_ref`, `is_photo_hint`, `has_tag_filter`)
    - `edit_list_restore_result` (metadata-only: attempt fields + `success`, `reason_code`)
    - `edit_list_restore_result.reason_code` (current set):
      - `ok`
      - `message_not_modified`
      - `restore_failed`
      - `alert_not_found`
      - `message_not_found`
      - `chat_not_found`
      - `forbidden`
      - `restore_exception`
  - Birthday bulk export/import telemetry:
    - `birthday_bulk_export_mode_opened`, `birthday_bulk_export_sent`
      - metadata-only fields: `mode`, `birthdays_count`, `rows_count`, `tags_nonempty_count`, `messages_sent`, acting-as payload.
    - `birthday_bulk_import_prompted`, `birthday_bulk_import_parsed`
      - parsing payload is metadata-only and keeps parser counters plus token-analysis counters:
        `input_len`, `input_hash`, `nonempty_lines`, `valid_lines`, `invalid_lines`,
        `reason_counts`, `lines_limit_exceeded`,
        `provided_tag_items`, `resolved_tag_items`, `unresolved_tags`, `unresolved_missing_tag_items`,
        `suggestions_over_threshold`, `entries_with_unresolved_tags`, `entries_analyzed`,
        `available_user_tags`, `suggestion_threshold`, acting-as payload.
      - `unresolved_tags` is currently a tag-item count (not a line count).
    - `birthday_bulk_import_decision`
      - metadata-only fields: `decision` (`continue|edit|gototags`), `valid_lines`, `unresolved_tags`,
        optional decision `reason_code` for stale/expired sessions.
    - `birthday_bulk_import_commit_failed`
      - metadata-only fields: `reason_code`, `valid_lines`, `unresolved_tags`, `saved_count`, acting-as payload.
    - `birthday_bulk_import_committed`
      - metadata-only fields: `imported_count`, `untagged_count`, `duplicates_possible`, `valid_lines`, `unresolved_tags`, acting-as payload.
      - `untagged_count` follows the `resolved_tags` contract (legacy `resolved_tag` fallback during migration).
    - `birthday_bulk_saved_storage` (storage-layer write success signal)
      - metadata-only fields: `source`, `saved_count`, `ids_count`.
  - Tag-add input telemetry: `tag_add_invalid_format`, `tag_add_success`, `tag_add_failed` (metadata-only fields such as `tag_len`, `tag_hash`, reason code, acting-as payload).
  - Tag-rename input telemetry: `tag_rename_invalid_format`, `tag_rename_success`, `tag_rename_failed` (metadata-only fields: `old_tag_len`, `old_tag_hash`, `new_tag_len`, `new_tag_hash`, reason code, acting-as payload).
- **Input validation:** `title_input_too_long`, `additional_info_input_too_long`, `custom_name_input_too_long` (metadata-only fields: `title_len` / `text_len` / `name_len`)
- **Manage/Admin:** user-list and user-detail render success/failure with metadata only (`*_len`, `*_hash`, ids/roles/source/delivery/reason, activity bucket counts)
- **Manage/Admin storage summary:** `manage_storage_summary_viewed`, `manage_storage_summary_failed`
  - metadata-only fields include actor/source and aggregate byte counters (`total_data_root_bytes`, `total_backup_root_bytes`,
    `total_system_log_root_bytes`, `total_user_log_root_bytes`, `total_user_data_bytes`, `total_user_logs_bytes`,
    `total_user_backups_bytes`, `total_rows_bytes`, `rows_count`).
  - `manage_storage_summary_viewed` also carries `delivery` (`edited` | `message_not_modified`).
  - `manage_storage_summary_failed` uses `reason_code=message_edit_failed`.
- **Backups:** export/import requested + completed/failed, import preview shown/cancelled (`backup_import_preview_shown`,
  `backup_import_cancelled`), email enabled/disabled, email sent, backup_email_invalid_input (email_meta only)
- **Scheduler:** alert sent/snoozed/done, pre-alert sent, missed summary sent
  - repetition-exhaustion outcomes include `repetition_exhausted` (metadata-only: alert ids/type, deactivation/result fields)
  - recurring `alert_sent` outcomes include `repetition_counted` and `repetition_exhausted` flags
  - pre-alert outcomes include metadata field `pre_alert_kind` (`duration` | `birthday_evening_before`)
- **Ghost reminders:** ghost picker and notification lifecycle
  - `ghost_created` (metadata-only: `ghost_id`, `source_alert_id`, `fire_at` ISO timestamp) — emitted in `_do_create_ghost` on successful ghost creation
  - `ghost_deleted` (metadata-only: `ghost_id`, `source_id`) — emitted in `handle_ghost_del_confirm` on confirmed deletion
- **Placebo interactions:** `placebo_done_pressed`, `placebo_noted_pressed`, `bday_noted_pressed`, `bday_msg_style_selected`,
  `bday_msg_prompt_shown`, `bday_msg_generated`, `bday_msg_generation_failed`,
  `placebo_done_feedback_sent`, `placebo_done_feedback_failed`, `placebo_noted_feedback_sent`, `placebo_noted_feedback_failed`
  (metadata-only fields: `alert_id`, `alert_type`, `style`, `selection_result`, `fallback_stage`, `template_id`, `reason_code`,
  callback-length diagnostics, and inferred context descriptors such as `tag_groups`/`gender_hint`/`title_hints`)
  - `bday_msg_generated` carries `zodiac_used` field: `null` for template-based styles (`polite`/`boomer`/`cringe`),
    `"western"` | `"eastern"` | `"both"` for the `zodiac` style; also includes `zodiac_mode_setting` (user pref at generation
    time) and `zodiac_eastern_fallback_to_western` (bool, True when eastern was requested but unavailable due to missing
    or out-of-range birth year).
- **API wrapper no-ops:** `bot_message_edit_noop` for `edit_message_text` `message_not_modified` outcomes.
- **Menu fail-soft:** explicit events:
  - `alerts_menu_markdown_fallback`, `alerts_menu_markdown_fallback_sent`, `alerts_menu_markdown_fallback_failed`
  - `birthday_menu_markdown_fallback`, `birthday_menu_markdown_fallback_sent`, `birthday_menu_markdown_fallback_failed`
  - reason codes: `markdown_parse_error`, `fallback_plain_text_ok`, `fallback_send_failed` (metadata-only; hash/len where text signal is needed)

### Payload rules
- Never log raw text, titles, or messages.
- Use **hash + length** for any needed text signal.
- Use counts, IDs, and booleans.
- For error causes, log short **reason codes** (for example `bad_request`, `target_missing`), not raw exception strings.
- For benign no-op edit outcomes, use reason code `message_not_modified`.
- Placebo callback-feedback failures use reason codes only (for example `query_too_old_or_invalid`, `callback_answer_failed`).
- Birthday message generation failures use reason codes only:
  `invalid_style`, `callback_payload_invalid`, `alert_not_found`, `alert_not_birthday`, `archive_invalid`, `selection_empty`, `send_failed`, `zodiac_assemble_failed`.
- Media fallback reason codes currently used include:
  - `invalid_image_id`
  - `local_path_invalid`
  - `local_file_missing`
  - `local_send_failed`
  - `fallback_to_text`
  - `autoheal_image_id`

## Hashing policy

Any text signals in logs must be converted to:
- `*_len`: length of original text
- `*_hash`: short SHA256 hash (prefix)

This preserves debugging signal without storing content.
