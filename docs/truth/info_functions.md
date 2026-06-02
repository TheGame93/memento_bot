# Utility and Core Module Index

> **Location:** `docs/truth/info_functions.md`  
> **Auto-generated** by `scripts/gen_info_functions.py` — do not edit by hand.  
> Re-run whenever public functions are added, renamed, or removed:
> `python3 scripts/gen_info_functions.py`

Fields per entry: `name | parent | inputs | output | description`

## `modules/backup_core/archive.py`
- `create_zip` | `modules.backup_core.archive` | `archive_path`, `base_dir`, `files`, `extra_entries`, `source_map` | — | Create a ZIP archive from relative file paths and optional extra entries.
- `extract_zip` | `modules.backup_core.archive` | `archive_path`, `dest_dir`, `max_members`, `max_member_uncompressed`, `max_total_uncompressed` | — | Extract a ZIP archive with path, symlink, and size-safety enforcement.

## `modules/backup_core/archive_preview.py`
- `build_archive_preview_text` | `modules.backup_core.archive_preview` | `inspect_data`, `diff_data`, `title`, `target_user_id`, `created_label`, `size_bytes`, `age_days`, `source_fallback` | `str` | Build a Markdown backup-preview summary string from pre-computed inspect and diff data.

## `modules/backup_core/email_backup.py`
- `describe_monthly_backup_schedule` | `modules.backup_core.email_backup` | — | — | Human-readable recurring schedule derived from active scheduler constants.
- `describe_monthly_reminder_schedule` | `modules.backup_core.email_backup` | — | — | Human-readable reminder schedule derived from active scheduler constants.
- `normalize_email_address` | `modules.backup_core.email_backup` | `value` | — | Return a normalized deliverable email address or None when invalid.
- `smtp_service_status` | `modules.backup_core.email_backup` | — | — | Returns SMTP configuration diagnostic (no secrets exposed).
- `last_expected_backup_time` | `modules.backup_core.email_backup` | `now` | — | Return the most recent scheduled monthly-backup timestamp.
- `last_expected_reminder_time` | `modules.backup_core.email_backup` | `now` | — | Return the most recent scheduled monthly-reminder timestamp.
- `should_send_startup_backup` | `modules.backup_core.email_backup` | `now`, `prefs` | — | Decide whether a startup catch-up backup should be sent now.
- `should_send_startup_reminder` | `modules.backup_core.email_backup` | `now`, `prefs` | — | Decide whether a startup catch-up reminder should be sent now.
- `should_send_monthly` | `modules.backup_core.email_backup` | `now`, `prefs` | — | Return whether this month still requires a scheduled backup send.
- `should_send_monthly_reminder` | `modules.backup_core.email_backup` | `now`, `prefs` | — | Return whether this month still requires a scheduled reminder send.
- `build_email_backup_archive` | `modules.backup_core.email_backup` | `snapshot`, `now` | — | Build ZIP payload bytes and manifest data for one email backup send.
- `estimate_email_backup_size_bytes` | `modules.backup_core.email_backup` | `storage`, `user_id`, `now` | — | Estimate serialized backup attachment size for a user email backup.
- `send_backup_email` | `modules.backup_core.email_backup` | `storage`, `user_id`, `to_email`, `now`, `reason`, `history_slot_dt` | — | Send one backup email and return structured delivery outcome metadata.
- `run_monthly_email_backups` | `modules.backup_core.email_backup` | `storage`, `now` | — | Run scheduled monthly email backups for all eligible users.

## `modules/backup_core/export_import.py`
- `export_user_archive` | `modules.backup_core.export_import` | `storage`, `user_id`, `now`, `include_images` | — | Export one user dataset by creating a canonical quota-guarded backup archive.
- `import_user_archive` | `modules.backup_core.export_import` | `storage`, `user_id`, `archive_path`, `allow_overwrite` | — | Import one user archive by delegating to the restore service flow.

## `modules/backup_core/local_backup.py`
- `list_local_backups` | `modules.backup_core.local_backup` | `user_id` | — | List parsed local backup archives for one user.
- `create_local_backup` | `modules.backup_core.local_backup` | `storage`, `user_id`, `now` | — | Create one local backup archive and return manifest/path metadata.
- `enforce_retention` | `modules.backup_core.local_backup` | `user_id`, `now`, `daily`, `weekly`, `monthly`, `yearly` | — | Apply retention policy tiers and delete local backups outside keep buckets.
- `backup_user_local` | `modules.backup_core.local_backup` | `storage`, `user_id`, `now` | — | Create, retain, and optionally sync one user's local backup pipeline.
- `backup_all_users_local` | `modules.backup_core.local_backup` | `storage`, `now` | — | Run local backup pipeline for every user and collect per-user outcomes.

## `modules/backup_core/manifest.py`
- `hash_file` | `modules.backup_core.manifest` | `path`, `chunk_size` | — | Compute SHA256 digest hex for a file path.
- `hash_bytes` | `modules.backup_core.manifest` | `payload` | — | Compute SHA256 digest hex for an in-memory byte payload.
- `build_manifest` | `modules.backup_core.manifest` | `user_id`, `base_dir`, `files`, `created_at`, `schema_version`, `source_map` | — | Build a manifest dictionary with file size and hash entries.
- `write_manifest` | `modules.backup_core.manifest` | `path`, `manifest` | — | Write manifest JSON to disk with parent-directory creation.
- `to_json` | `modules.backup_core.manifest` | `manifest` | — | Serialize a manifest dictionary into indented JSON text.
- `load_manifest` | `modules.backup_core.manifest` | `path` | — | Load a manifest dictionary from a JSON file path.
- `validate_manifest` | `modules.backup_core.manifest` | `manifest` | — | Validate manifest schema essentials and return `(is_valid, errors)`.

## `modules/backup_core/paths.py`
- `get_backup_root` | `modules.backup_core.paths` | — | — | Return the configured global backup root directory.
- `get_user_backup_root` | `modules.backup_core.paths` | `user_id` | — | Return the backup root directory path for a specific user.
- `ensure_user_backup_root` | `modules.backup_core.paths` | `user_id` | — | Ensure and return the backup root directory for a specific user.
- `get_user_backup_folder` | `modules.backup_core.paths` | `user_id`, `folder` | — | Return and ensure a canonical per-user backup subfolder path.
- `get_system_backup_dir` | `modules.backup_core.paths` | — | — | Return and ensure the system backup root directory.

## `modules/backup_core/retention.py`
- `select_retention` | `modules.backup_core.retention` | `items`, `now`, `daily`, `weekly`, `monthly`, `yearly` | — | Select backups to keep based on tiered retention buckets.

## `modules/backup_core/sync_target.py`
- `get_sync_dir` | `modules.backup_core.sync_target` | — | — | Return external backup sync root configured by environment variable.
- `sync_backup_file` | `modules.backup_core.sync_target` | `src_path`, `user_id`, `now` | — | Copy a backup file to external sync target and report structured outcome.

## `modules/backup_core/system_backup.py`
- `build_system_backup` | `modules.backup_core.system_backup` | `now`, `base_dir`, `backup_dir` | `dict` | Build one system backup archive from durable system/whitelist JSON files.
- `list_system_backups` | `modules.backup_core.system_backup` | `backup_dir` | `list[dict]` | List system backup archives in canonical naming order from oldest to newest.
- `enforce_system_retention` | `modules.backup_core.system_backup` | `now`, `backup_dir` | `dict` | Apply tiered retention to system backups and delete archives outside keep buckets.
- `inspect_system_archive` | `modules.backup_core.system_backup` | `archive_path: str` | `dict` | Inspect a system backup archive by validating manifest and per-file hashes in-place.
- `check_restore_guards` | `modules.backup_core.system_backup` | `archive_path: str`, `actor_id`, `get_role_fn` | `tuple[bool, str]` | Evaluate actor and viability guards before applying a system restore archive.
- `apply_system_restore` | `modules.backup_core.system_backup` | `archive_path: str`, `actor_id`, `get_role_fn`, `base_dir` | `dict` | Restore system files from a validated archive with guard checks and snapshot safety.
- `send_system_backup_email` | `modules.backup_core.system_backup` | `developer_ids: list`, `storage`, `now` | `list[dict]` | Send current system backup archive by mail to eligible developer recipients.

## `modules/backup_core/user_backup.py`
- `BackupQuotaError` | `modules.backup_core.user_backup` | — | — | Report backup quota overflow with exact usage and overflow metadata.
- `list_user_backups` | `modules.backup_core.user_backup` | `user_id`, `folder: str` | `list[dict]` | List timestamped backup archives for one user/folder in oldest-first order.
- `get_user_quota_usage_bytes` | `modules.backup_core.user_backup` | `user_id` | `int` | Return total size in bytes for quota-bound user backup folders.
- `check_quota_before_create` | `modules.backup_core.user_backup` | `user_id`, `exact_new_bytes: int` | `dict` | Check whether creating a backup of exact_new_bytes fits user backup quota.
- `enforce_folder_retention` | `modules.backup_core.user_backup` | `user_id`, `folder: str`, `now` | `dict` | Apply retention policy to one per-user backup folder and delete dropped archives.
- `build_user_backup` | `modules.backup_core.user_backup` | `storage`, `user_id`, `folder: str`, `now`, `source`, `enforce_quota` | `dict` | Build a canonical user backup archive and return metadata for restore/list workflows.
- `inspect_archive` | `modules.backup_core.user_backup` | `archive_path: str`, `expected_user_id` | `dict` | Inspect archive manifest and alerts payload to return safe summary metadata.
- `diff_archive_vs_current` | `modules.backup_core.user_backup` | `storage`, `user_id`, `archive_path: str` | `dict` | Compare archive content counts and preference previews against current user data.

## `modules/backup_core/user_restore.py`
- `create_pre_import_backup` | `modules.backup_core.user_restore` | `storage`, `user_id`, `now` | `dict` | Create and retain one pre-import safety snapshot archive for a user restore.
- `check_restore_permission` | `modules.backup_core.user_restore` | `actor_id`, `target_user_id`, `archive_manifest: dict`, `get_role_fn` | `tuple[bool, str]` | Authorize one restore request against actor role and target archive ownership rules.
- `apply_user_restore` | `modules.backup_core.user_restore` | `storage`, `user_id`, `archive_path: str`, `actor_id`, `scheduler_state_module`, `now`, `get_role_fn`, `source` | `dict` | Apply one user restore archive atomically with pre-import snapshot and rollback safety.

## `modules/birthday_utils.py`
- `calculate_current_age` | `modules.birthday_utils` | `birth_day`, `birth_month`, `birth_year`, `reference_date` | — | Return the person's current age as an int, or None if birth_year is missing.
- `calculate_turning_age` | `modules.birthday_utils` | `birth_year`, `birthday_year` | — | Return the age the person turns in *birthday_year*, or None.

## `modules/ghost_utils.py`
- `is_ghost_alert` | `modules.ghost_utils` | `alert: dict` | `bool` | Return whether the alert was created as a ghost reminder copy.
- `create_ghost_alert` | `modules.ghost_utils` | `storage`, `user_id: int`, `source_alert: dict`, `fire_at: datetime`, `missed_date_str: str` | `str | None` | Create and persist a one-time ghost copy and return its alert ID when saved.
- `get_pending_ghost_alerts` | `modules.ghost_utils` | `storage`, `user_id: int` | `list[dict]` | Return active one-time alerts that carry a ghost source reference.
- `find_existing_ghost` | `modules.ghost_utils` | `storage`, `user_id: int`, `source_alert_id: str` | `dict | None` | Return the first active ghost alert that points to the provided source alert ID.

## `modules/repetition_utils.py`
- `is_repetition_supported` | `modules.repetition_utils` | `alert_type: Any` | `bool` | Return whether the alert type supports persisted repetition settings.
- `default_repetition_payload` | `modules.repetition_utils` | `alert_type: Any` | `dict | None` | Return the default normalized repetition payload for supported alert types.
- `parse_until_date_strict` | `modules.repetition_utils` | `raw_text: Any` | `date | None` | Parse a strict `DD/MM/YYYY` repetition-until value into a valid date.
- `parse_until_date_input` | `modules.repetition_utils` | `raw_text: Any` | `tuple[date | None, bool]` | Parse user-facing repetition-until input.
- `normalize_repetition_payload` | `modules.repetition_utils` | `alert_type: Any`, `repetition_raw: Any` | `dict | None` | Normalize repetition data to the canonical storage schema for the alert type.
- `format_repetition_human` | `modules.repetition_utils` | `alert_type: Any`, `repetition_raw: Any` | `str` | Render repetition data as a user-facing summary label.
- `candidate_allowed_by_repetition` | `modules.repetition_utils` | `alert_type: Any`, `repetition_raw: Any`, `candidate_dt: Any` | `bool` | Return whether a candidate occurrence is allowed by repetition limits.
- `decrement_count_if_needed` | `modules.repetition_utils` | `repetition_raw: Any`, `should_count: bool` | — | Update count-based repetition for one due occurrence and report transition details.

## `modules/scheduler.py`
- `init_scheduler` | `modules.scheduler` | `app`, `storage` | — | Initialize scheduler globals and delegate startup wiring to coordinator.
- `trigger_alert` | `modules.scheduler` | `bot`, `user_id`, `alert`, `alert_type`, `missed_time`, `scheduled_time`, `clear_snooze`, `postpone_count`, `postpone_id`, `effective_fire_time` | — | Delegate alert triggering through the shared storage bridge state.
- `snooze_alert` | `modules.scheduler` | `user_id`, `alert_id`, `snooze_duration`, `storage` | — | Delegate snooze handling using caller-provided or coordinator-fallback storage.
- `mark_alert_done` | `modules.scheduler` | `user_id`, `alert_id`, `storage` | — | Delegate completion handling using caller-provided or coordinator-fallback storage.
- `handle_missed_alerts` | `modules.scheduler` | — | — | Send startup missed-alert summaries when app and storage are available.

## `modules/scheduler_core/actions.py`
- `trigger_alert` | `modules.scheduler_core.actions` | `bot`, `user_id`, `alert`, `alert_type`, `storage`, `sent_pre_alerts`, `missed_time`, `scheduled_time`, `clear_snooze`, `postpone_count`, `postpone_id`, `effective_fire_time` | — | Triggers an alert: sends the notification and updates state.
- `snooze_alert` | `modules.scheduler_core.actions` | `user_id`, `alert_id`, `snooze_duration`, `storage` | — | Snoozes an alert for a specified duration.
- `mark_alert_done` | `modules.scheduler_core.actions` | `user_id`, `alert_id`, `storage` | — | Marks an alert as done for this occurrence.

## `modules/scheduler_core/coordinator.py`
- `get_storage` | `modules.scheduler_core.coordinator` | — | — | Return the scheduler-wide storage manager reference.
- `get_app` | `modules.scheduler_core.coordinator` | — | — | Return the scheduler-wide application reference.
- `get_scheduler` | `modules.scheduler_core.coordinator` | — | — | Return the APScheduler instance managed by the coordinator.
- `reschedule_user_alerts` | `modules.scheduler_core.coordinator` | `user_id`, `reason`, `storage` | — | Recompute next_scheduled for all active alerts of a user using current prefs.
- `init_scheduler` | `modules.scheduler_core.coordinator` | `app`, `storage` | — | Initializes the scheduler system.
- `start_scheduler` | `modules.scheduler_core.coordinator` | — | — | Starts the scheduler and performs initial load.
- `stop_scheduler` | `modules.scheduler_core.coordinator` | — | — | Stops the scheduler gracefully.
- `load_all_alerts` | `modules.scheduler_core.coordinator` | — | — | Load active alerts on startup and refresh cached schedules when needed.
- `queue_single_alert` | `modules.scheduler_core.coordinator` | `user_id`, `alert_id` | — | Updates the schedule state for a single alert.
- `remove_alert_from_queue` | `modules.scheduler_core.coordinator` | `user_id`, `alert_id` | — | Called when an alert is deleted or deactivated.
- `check_due_alerts` | `modules.scheduler_core.coordinator` | — | — | Main scheduled job that runs every SCHEDULER_INTERVAL_SECONDS.
- `check_pre_alerts` | `modules.scheduler_core.coordinator` | `bot`, `user_id`, `alert`, `now`, `user_prefs` | — | Checks if any pre-alerts for this alert should fire.
- `handle_missed_alerts` | `modules.scheduler_core.coordinator` | — | — | Run missed-alert recovery through the coordinator-owned app and storage.

## `modules/scheduler_core/missed.py`
- `handle_missed_alerts` | `modules.scheduler_core.missed` | `bot`, `storage`, `now`, `send_missed_func` | — | Scan all users for alerts and pre-alerts missed during the offline window and send batch summaries on startup.

## `modules/scheduler_core/postpone.py`
- `parse_iso_datetime` | `modules.scheduler_core.postpone` | `value` | — | Parse an ISO datetime value and return a server-naive datetime.
- `process_postpone_queue_for_user` | `modules.scheduler_core.postpone` | `bot`, `user_id`, `alert_map`, `postpone_items`, `now`, `storage`, `sent_pre_alerts` | — | Sends any due postponed instances and marks their status.

## `modules/scheduler_core/state.py`
- `mark_dirty` | `modules.scheduler_core.state` | — | — | Mark pre-alert tracking state as needing persistence.
- `clear_pre_alert_tracking_for_alert` | `modules.scheduler_core.state` | `alert_id` | — | Remove all sent_pre_alerts entries for a given alert_id.
- `prune_user_sent_pre_alerts` | `modules.scheduler_core.state` | `user_id_str: str` | `int` | Remove all sent_pre_alerts entries for a specific user id.
- `save_pre_alert_state` | `modules.scheduler_core.state` | — | — | Persist sent_pre_alerts to runtime_state.json if dirty.
- `load_pre_alert_state` | `modules.scheduler_core.state` | — | — | Restore sent_pre_alerts from runtime_state.json.
- `is_missed_pre_notified` | `modules.scheduler_core.state` | `user_id_str`, `alert_id`, `pa_str`, `occurrence_iso` | — | Return True if this missed pre-alert was already notified on a previous restart.
- `mark_missed_pre_notified` | `modules.scheduler_core.state` | `user_id_str`, `alert_id`, `pa_str`, `occurrence_iso`, `when` | — | Record that this missed pre-alert occurrence has been notified.
- `cleanup_notified_missed_pre` | `modules.scheduler_core.state` | `alert_last_triggered_map`, `known_alert_ids_by_user` | — | Remove stale entries from notified_missed_pre.
- `save_notified_missed_pre` | `modules.scheduler_core.state` | — | — | Persist notified_missed_pre to runtime_state.json if dirty.
- `load_notified_missed_pre` | `modules.scheduler_core.state` | — | — | Restore notified_missed_pre from runtime_state.json.
- `record_pending_missed` | `modules.scheduler_core.state` | `user_id_str`, `alert_id`, `occurrence_iso`, `missed_pre_strs`, `missed_pre_times`, `missed_due_time_iso`, `first_notified_iso` | — | Store or update a missed alert entry for "always" mode re-notification.
- `clear_pending_missed_alert` | `modules.scheduler_core.state` | `user_id_str`, `alert_id` | — | Remove the pending entry when trigger_alert() fires normally (stops re-notification).
- `get_pending_missed_for_user` | `modules.scheduler_core.state` | `user_id_str` | — | Return {alert_id: {...}} for this user, or {}.
- `save_pending_missed` | `modules.scheduler_core.state` | — | — | Persist pending_missed_notifications to runtime_state.json if dirty.
- `load_pending_missed` | `modules.scheduler_core.state` | — | — | Restore pending_missed_notifications from runtime_state.json.
- `prune_user_missed_state` | `modules.scheduler_core.state` | `user_id_str: str` | `dict` | Prune missed-notification state entries for a specific user id.

## `modules/scheduler_mathlogic.py`
- `get_constants_compatibility_issues` | `modules.scheduler_mathlogic` | — | — | Returns a list of compatibility issues between constants.py and this module.
- `sample_fuzzy_interval` | `modules.scheduler_mathlogic` | `mean: float`, `std: float` | `int` | Return a positive integer day interval sampled from the fuzzy daily distribution.
- `get_next_occurrence` | `modules.scheduler_mathlogic` | `alert`, `reference_date` | — | Return the next datetime when an alert should fire.
- `parse_pre_alert_string` | `modules.scheduler_mathlogic` | `pre_alert_str` | — | Parses a pre-alert string like "2d", "1w", "30m", "4h", "1mo" into a timedelta/relativedelta.
- `resolve_pre_alert_fire_time` | `modules.scheduler_mathlogic` | `alert`, `pre_alert_str`, `main_trigger_time`, `user_prefs` | — | Resolves a pre-alert token to an absolute fire datetime.
- `calculate_pre_alert_times` | `modules.scheduler_mathlogic` | `alert`, `main_trigger_time`, `user_prefs`, `reference_now` | — | Calculates pre-alert notification times based on the main trigger time.
- `is_due` | `modules.scheduler_mathlogic` | `alert`, `current_time`, `tolerance_seconds` | — | Checks if an alert should fire now (within tolerance window).
- `is_overdue` | `modules.scheduler_mathlogic` | `alert`, `current_time` | — | Checks if an alert was missed (scheduled time has passed but wasn't triggered).
- `is_pre_alert_due` | `modules.scheduler_mathlogic` | `alert`, `pre_alert_str`, `current_time`, `tolerance_seconds`, `user_prefs` | — | Checks if a specific pre-alert should fire now.
- `get_snooze_limit` | `modules.scheduler_mathlogic` | `alert` | — | For recurring alerts, returns the maximum datetime an alert can be snoozed to.
- `calculate_snooze_time` | `modules.scheduler_mathlogic` | `snooze_option`, `from_time` | — | Calculates the snooze-until datetime.
- `can_snooze_to` | `modules.scheduler_mathlogic` | `alert`, `snooze_until` | — | Checks if an alert can be snoozed to a specific time.
- `format_datetime_human` | `modules.scheduler_mathlogic` | `dt` | — | Formats a datetime for human display.
- `format_pre_alert_human` | `modules.scheduler_mathlogic` | `pre_alert_str` | — | Converts "2d" to "2 days", etc.
- `format_pre_alert_display` | `modules.scheduler_mathlogic` | `alert: dict`, `pre_alert_str: str`, `due_dt: datetime | None`, `user_prefs: dict | None` | `str` | Render a pre-alert as resolved datetime text when possible, otherwise fallback to stable token wording.

## `modules/scheduler_messagelogic.py`
- `format_main_alert` | `modules.scheduler_messagelogic` | `alert`, `scheduled_time`, `user_prefs` | — | Render the legacy main-alert text format for backward compatibility.
- `format_pre_alert` | `modules.scheduler_messagelogic` | `alert`, `main_trigger_time`, `scheduled_time`, `user_prefs` | — | Render the legacy pre-alert text format for backward compatibility.
- `get_toggle_action_label` | `modules.scheduler_messagelogic` | `alert` | — | Return the legacy state-aware toggle label for recurring alerts.
- `get_alert_keyboard` | `modules.scheduler_messagelogic` | `alert`, `occurrence_time`, `original_time`, `postpone_count` | — | Build the legacy due-notification keyboard.
- `get_pre_alert_keyboard` | `modules.scheduler_messagelogic` | `alert`, `occurrence_time`, `original_time`, `include_info`, `postpone_count` | — | Build the legacy pre-alert keyboard.
- `build_pre_alert_detail_keyboard` | `modules.scheduler_messagelogic` | `alert`, `occurrence_time`, `original_time`, `postpone_count` | — | Build the legacy pre-alert detail keyboard used by old notification flows.
- `build_alert_detail_keyboard` | `modules.scheduler_messagelogic` | `alert`, `occurrence_time`, `original_time`, `postpone_count` | — | Build the legacy due-alert detail keyboard used by old notification flows.
- `get_missed_alert_keyboard` | `modules.scheduler_messagelogic` | `alert` | — | Build the keyboard for missed-alert notifications.
- `send_missed_alerts_batch` | `modules.scheduler_messagelogic` | `bot`, `user_id: int`, `missed_alerts: list`, `storage` | — | Send the startup missed-alerts summary message to a user.
- `send_snooze_confirmation` | `modules.scheduler_messagelogic` | `bot`, `user_id`, `alert`, `snoozed_until` | — | Send a confirmation message after snoozing an alert.
- `send_done_confirmation` | `modules.scheduler_messagelogic` | `bot`, `user_id`, `alert`, `was_one_time` | — | Send a confirmation message after marking an alert as done.

## `modules/security/authz.py`
- `get_role_map` | `modules.security.authz` | `path: str`, `admin_id: Any` | `Dict[str, str]` | Load and cache the normalized user-role map from whitelist storage.
- `invalidate_role_map_cache` | `modules.security.authz` | `path: str` | `None` | Invalidate cached role-map data globally or for a specific path.
- `get_user_role` | `modules.security.authz` | `user_id: Any`, `path: str`, `admin_id: Any` | `Optional[str]` | Return normalized role for a user id, or None when unauthorized.
- `is_authorized` | `modules.security.authz` | `user_id: Any`, `path: str`, `admin_id: Any` | `bool` | Return whether the user id is present in the effective role map.
- `is_admin_or_developer` | `modules.security.authz` | `user_id: Any`, `path: str`, `admin_id: Any` | `bool` | Return whether the user has admin-or-developer effective access.

## `modules/security/roles.py`
- `normalize_role` | `modules.security.roles` | `raw_role` | — | Normalize raw role labels to supported canonical roles.
- `pick_stronger_role` | `modules.security.roles` | `role_a`, `role_b` | — | Return the stronger role according to configured privilege priority.
- `build_status_role_counts` | `modules.security.roles` | `role_map` | — | Build role counters used by status views.

## `modules/security/whitelist_notifications.py`
- `build_request_admin_text` | `modules.security.whitelist_notifications` | `record: Optional[Dict[str, Any]]`, `state: Optional[Dict[str, Any]]`, `status: str` | `str` | Build admin-facing Markdown text for one whitelist request state.
- `build_request_action_keyboard` | `modules.security.whitelist_notifications` | `user_id: Any` | `InlineKeyboardMarkup` | Build admin action buttons for approving or editing a request.
- `notify_admins_for_request` | `modules.security.whitelist_notifications` | `bot`, `storage`, `record: Dict[str, Any]`, `state: Optional[Dict[str, Any]]` | `Dict[str, Any]` | Send whitelist-request notifications to all admin/developer recipients.
- `update_request_messages` | `modules.security.whitelist_notifications` | `bot`, `user_id: Any`, `text: str`, `reply_markup` | `Dict[str, Any]` | Edit stored request notifications, optionally preserving pending action buttons.
- `send_pending_requests_digest` | `modules.security.whitelist_notifications` | `bot`, `storage` | `Dict[str, Any]` | Send one daily digest of pending whitelist requests to privileged users.

## `modules/security/whitelist_store.py`
- `load_whitelist_invites` | `modules.security.whitelist_store` | `path: str` | `Dict[str, Any]` | Load whitelist invites payload with a stable default structure.
- `list_whitelist_invites` | `modules.security.whitelist_store` | `path: str` | `List[Dict[str, Any]]` | Return invite records filtered to dictionary entries.
- `upsert_whitelist_invite` | `modules.security.whitelist_store` | `user_id: Any`, `username: Any`, `display_name: Any`, `role: Optional[str]`, `invited_by: Any`, `now_iso: Optional[str]`, `path: str` | `bool` | Create or update a whitelist invite matched by user id or username.
- `find_whitelist_invite` | `modules.security.whitelist_store` | `user_id: Any`, `username: Any`, `path: str` | `Optional[Dict[str, Any]]` | Return the first invite matching user id or normalized username.
- `remove_whitelist_invite` | `modules.security.whitelist_store` | `user_id: Any`, `username: Any`, `path: str` | `bool` | Remove invites matching user id or normalized username.
- `load_whitelist_requests` | `modules.security.whitelist_store` | `path: str` | `Dict[str, Any]` | Load whitelist request payload with a stable default structure.
- `list_whitelist_requests` | `modules.security.whitelist_store` | `path: str` | `List[Dict[str, Any]]` | Return whitelist request records filtered to dictionary entries.
- `find_whitelist_request` | `modules.security.whitelist_store` | `user_id: Any`, `path: str` | `Optional[Dict[str, Any]]` | Return the pending whitelist request record for the target user id.
- `load_whitelist_request_state` | `modules.security.whitelist_store` | `path: str` | `Dict[str, Any]` | Load whitelist request-state payload with stable requests/meta buckets.
- `get_whitelist_request_state` | `modules.security.whitelist_store` | `user_id: Any`, `path: str` | `Optional[Dict[str, Any]]` | Return request-state metadata for a user id, if present.
- `update_whitelist_request_state_meta` | `modules.security.whitelist_store` | `updates: Dict[str, Any]`, `path: str` | `bool` | Merge global request-state metadata updates atomically.
- `get_whitelist_request_state_meta` | `modules.security.whitelist_store` | `path: str` | `Dict[str, Any]` | Return global request-state metadata with dict fallback guarantees.
- `upsert_whitelist_request` | `modules.security.whitelist_store` | `user_id: Any`, `username: Any`, `display_name: Any`, `custom_name: Any`, `request_message: Any`, `label_order: Any`, `now_iso: Optional[str]`, `path: str` | `bool` | Create or refresh a pending whitelist request record for a user.
- `update_whitelist_request` | `modules.security.whitelist_store` | `user_id: Any`, `custom_name: Any`, `label_order: Any`, `path: str`, `state_path: str` | `bool` | Update editable request fields and sync mirrored request-state snapshot.
- `update_whitelist_request_message` | `modules.security.whitelist_store` | `user_id: Any`, `request_message: Any`, `now_iso: Optional[str]`, `requests_path: str`, `state_path: str` | `Dict[str, Any]` | Update pending request message text and synchronize request-state mirrors.
- `ensure_whitelist_request` | `modules.security.whitelist_store` | `user_id: Any`, `username: Any`, `display_name: Any`, `custom_name: Any`, `request_message: Any`, `label_order: Any`, `now_iso: Optional[str]`, `requests_path: str`, `state_path: str` | `Dict[str, Any]` | Ensure a pending whitelist request exists and reset resolved-cycle state safely.
- `register_whitelist_request_message` | `modules.security.whitelist_store` | `user_id: Any`, `chat_id: Any`, `message_id: Any`, `now_iso: Optional[str]`, `path: str` | `bool` | Register one admin notification message reference for a request.
- `set_whitelist_request_notified` | `modules.security.whitelist_store` | `user_id: Any`, `now_iso: Optional[str]`, `path: str` | `bool` | Mark request notification timestamps for first/last notify tracking.
- `prune_whitelist_request_message_refs` | `modules.security.whitelist_store` | `user_id: Any`, `message_refs: List[Dict[str, Any]]`, `path: str` | `bool` | Replace stored request message references with the surviving subset.
- `resolve_whitelist_request` | `modules.security.whitelist_store` | `user_id: Any`, `action: str`, `actor_id: Any`, `actor_role: Any`, `actor_label: Optional[str]`, `now_iso: Optional[str]`, `requests_path: str`, `state_path: str` | `Dict[str, Any]` | Resolve a pending whitelist request and persist a resolution snapshot.
- `remove_whitelist_request` | `modules.security.whitelist_store` | `user_id: Any`, `path: str` | `bool` | Remove one pending whitelist request by user id.
- `list_whitelist_users` | `modules.security.whitelist_store` | `path: str` | `List[Dict[str, Any]]` | List whitelist users as sorted `{id, role}` entries.
- `ensure_whitelist_seeded` | `modules.security.whitelist_store` | `admin_id: Any`, `path: str` | `dict` | Seed whitelist storage with the env developer when first-start auth has no persisted file.
- `reconcile_startup_whitelist` | `modules.security.whitelist_store` | `admin_id: Any`, `path: str` | `dict` | Ensure canonical whitelist storage is initialized for startup, seeding it with admin_id on first run.
- `add_whitelist_user` | `modules.security.whitelist_store` | `user_id: Any`, `role: Optional[str]`, `path: str`, `force: bool` | `bool` | Add or upgrade a whitelist user role with optional force override.
- `remove_whitelist_user` | `modules.security.whitelist_store` | `user_id: Any`, `path: str` | `bool` | Remove a whitelist user and invalidate cached role mappings.

## `modules/shared/acting_as.py`
- `get_actor_user_id` | `modules.shared.acting_as` | `update` | `Optional[int | str]` | Return the effective actor user id from the update payload.
- `get_target_user_id` | `modules.shared.acting_as` | `update`, `context` | `Optional[int | str]` | Resolve the active target user id, falling back to the actor id.
- `is_acting_as` | `modules.shared.acting_as` | `update`, `context` | `bool` | Return whether the current context targets a user different from the actor.
- `build_acting_as_payload` | `modules.shared.acting_as` | `update`, `context` | `dict` | Build acting-as telemetry payload using actor and resolved target ids.
- `build_acting_as_payload_for` | `modules.shared.acting_as` | `actor_id`, `target_id` | `dict` | Build normalized acting-as payload for explicit actor and target ids.
- `build_acting_as_banner` | `modules.shared.acting_as` | `update`, `context`, `parse_mode: str | None` | `str` | Build the acting-as banner for the current update context.
- `build_acting_as_banner_for` | `modules.shared.acting_as` | `actor_id`, `target_id`, `parse_mode: str | None` | `str` | Render the acting-as banner with formatting for the selected parse mode.
- `set_acting_as` | `modules.shared.acting_as` | `context`, `target_id: Any` | `Optional[int | str]` | Persist acting-as target state in conversation user_data.
- `clear_acting_as` | `modules.shared.acting_as` | `context` | `None` | Remove acting-as target state from conversation user_data.

## `modules/shared/callback_codec.py`
- `callback_bytes_len` | `modules.shared.callback_codec` | `callback_data` | — | Return callback payload length in UTF-8 bytes.
- `ensure_callback_fits` | `modules.shared.callback_codec` | `callback_data`, `limit` | — | Validate that callback payload length stays within Telegram byte limits.
- `build_value_token_map` | `modules.shared.callback_codec` | `values`, `min_len`, `max_len` | — | Builds a collision-free token->value mapping for the provided values.
- `extract_callback_token` | `modules.shared.callback_codec` | `callback_data`, `prefix` | — | Extract token suffix from a callback payload with the expected prefix.
- `is_token_candidate` | `modules.shared.callback_codec` | `token`, `min_len`, `max_len` | — | Return whether a token matches the expected lowercase hex shape.

## `modules/shared/context_cleanup.py`
- `require_temp_alert` | `modules.shared.context_cleanup` | `func` | — | Guard: ends conversation gracefully if temp_alert is missing from user_data.
- `has_transient_context` | `modules.shared.context_cleanup` | `user_data` | — | Returns True when user_data contains any transient flow state.
- `clear_transient_context` | `modules.shared.context_cleanup` | `user_data`, `include_navigation` | — | Removes temporary runtime state while keeping persistent/user preference data.

## `modules/shared/forward_extract.py`
- `extract_forward_identity` | `modules.shared.forward_extract` | `message: Any` | `Dict[str, Any]` | Extract forwarded sender identity and standardized failure reason codes.

## `modules/shared/logging_utils.py`
- `hash_text` | `modules.shared.logging_utils` | `value`, `length` | — | Return a short SHA256 prefix for privacy-safe text correlation.
- `text_meta` | `modules.shared.logging_utils` | `value` | — | Return privacy-safe text metadata with length and hashed fingerprint.

## `modules/shared/markdown_utils.py`
- `md_escape` | `modules.shared.markdown_utils` | `value` | — | Escape user-provided text for Telegram legacy Markdown parse mode.
- `md_escape_inline_code` | `modules.shared.markdown_utils` | `value` | — | Sanitize dynamic text interpolated inside Markdown inline-code spans.
- `md_escape_multiline_text` | `modules.shared.markdown_utils` | `value` | — | Escape multiline Markdown text while preserving original line boundaries.
- `md_escape_fence_content` | `modules.shared.markdown_utils` | `value` | — | Escape user text intended for inside a ``` code fence.

## `modules/shared/messages.py`
- `is_message_not_modified_error` | `modules.shared.messages` | `exc: Exception` | `bool` | Return whether an exception is Telegram's benign message-not-modified edit outcome.
- `edit_callback_message_media_aware` | `modules.shared.messages` | `query`, `text`, `reply_markup`, `parse_mode` | — | Edit a callback message as caption for photo cards and text otherwise, treating no-op edits as benign.
- `send_feature_not_implemented` | `modules.shared.messages` | `update: Any`, `context: Any`, `storage: Any`, `feature_label: Optional[str]`, `reply_markup: Any` | `str` | Send the standard not-implemented response and emit optional user telemetry.

## `modules/shared/paths.py`
- `token_lock_hash_prefix` | `modules.shared.paths` | `token` | — | Return the first 16 hex chars of the SHA256 hash of token for use in lock filenames.
- `token_global_lock_path` | `modules.shared.paths` | `token` | — | Return the full path to the token-scoped global lock file under GLOBAL_LOCK_DIR.

## `modules/shared/runtime_context.py`
- `BotRuntime` | `modules.shared.runtime_context` | — | — | Carry bootstrap-owned runtime services for handler-edge dependency lookup.
- `set_bot_runtime` | `modules.shared.runtime_context` | `bot_data`, `runtime: BotRuntime` | `BotRuntime` | Persist the bootstrap-owned runtime bundle in PTB bot_data.
- `get_bot_runtime` | `modules.shared.runtime_context` | `context` | `BotRuntime` | Return the runtime bundle from PTB context and fail fast when missing.
- `get_runtime_storage` | `modules.shared.runtime_context` | `context` | — | Return the shared StorageManager from the runtime bundle.
- `get_runtime_api_failure_tracker` | `modules.shared.runtime_context` | `context` | — | Return the shared ApiFailureTracker from the runtime bundle.

## `modules/shared/status_render.py`
- `format_meta_timestamp` | `modules.shared.status_render` | `value`, `tz` | — | Format stored metadata timestamps for status output.
- `build_status_message` | `modules.shared.status_render` | `viewer_role`, `subject_role`, `server_line`, `user_time_line`, `system_metrics`, `counts`, `log_maintenance`, `user_id`, `user_meta`, `user_stats`, `backup_prefs`, `degraded`, `show_debug_labels`, `email_service` | — | Build the role-scoped `/status` message with system and user sections.

## `modules/shared/storage_metrics.py`
- `get_dir_size_bytes` | `modules.shared.storage_metrics` | `path` | — | Return recursive directory size in bytes, ignoring inaccessible paths.
- `get_logs_size_bytes` | `modules.shared.storage_metrics` | `path` | — | Return recursive size of `.log` and rotated log files in bytes.
- `get_files_size_bytes` | `modules.shared.storage_metrics` | `paths` | — | Return total size in bytes for existing files in the provided list.
- `get_user_data_dir_bytes` | `modules.shared.storage_metrics` | `user_id` | — | Return total bytes used by a user's data directory.
- `get_user_json_files_bytes` | `modules.shared.storage_metrics` | `user_id` | — | Return total bytes of top-level JSON files in a user's data directory.
- `get_user_json_backup_files_bytes` | `modules.shared.storage_metrics` | `user_id` | — | Return total bytes of top-level JSON backup files in a user's data directory.
- `get_user_event_log_paths` | `modules.shared.storage_metrics` | `storage`, `user_id` | — | Return event-log file paths (including rotations) for the target user.
- `get_user_event_logs_bytes` | `modules.shared.storage_metrics` | `storage`, `user_id` | — | Return total bytes consumed by a user's event log files.
- `get_user_backup_dir_bytes` | `modules.shared.storage_metrics` | `user_id` | — | Return total bytes used by a user's backup directory.
- `get_data_root_bytes` | `modules.shared.storage_metrics` | — | — | Return total bytes used under the global data root.
- `get_backup_root_bytes` | `modules.shared.storage_metrics` | — | — | Return total bytes used under the global backup root.
- `get_system_log_root_bytes` | `modules.shared.storage_metrics` | — | — | Return total bytes used under the system log root.
- `get_user_log_root_bytes` | `modules.shared.storage_metrics` | — | — | Return total bytes used under the user log root.

## `modules/shared/user_identity.py`
- `normalize_label_order` | `modules.shared.user_identity` | `order` | — | Normalize configured label-order tokens and guarantee `user_id` fallback.
- `format_label_order` | `modules.shared.user_identity` | `order` | — | Render normalized label-order tokens in readable precedence format.
- `build_label_sort_key` | `modules.shared.user_identity` | `user_id`, `username`, `display_name`, `custom_name`, `label_order` | — | Build a stable lowercase sort key using configured identity precedence.
- `format_user_label` | `modules.shared.user_identity` | `user_id`, `username`, `display_name`, `custom_name`, `label_order`, `escape_markdown` | — | Format a display label using configured identity precedence and escaping.
- `format_user_label_from_meta` | `modules.shared.user_identity` | `user_id`, `meta`, `escape_markdown` | — | Format a user label from metadata dict fields and label-order preferences.

## `modules/shared/user_status.py`
- `build_user_status_message` | `modules.shared.user_status` | `storage`, `user_id`, `viewer_role`, `actor_role`, `api_failure_tracker` | — | Assemble all status metrics and render a role-scoped `/status` response.

## `modules/shared/whitelist_users.py`
- `build_whitelist_users_empty_text` | `modules.shared.whitelist_users` | — | `str` | Build the empty-state message for whitelist user lists.
- `sort_whitelist_entries` | `modules.shared.whitelist_users` | `entries: Iterable[Dict[str, Any]]`, `meta_map: Dict[str, Any]` | `List[Dict[str, Any]]` | Sort whitelist entries by role priority and configured identity label.
- `build_whitelist_users_text` | `modules.shared.whitelist_users` | `entries: Iterable[Dict[str, Any]]`, `meta_map: Dict[str, Any]`, `summary_map: Dict[str, Any]`, `format_summary: Callable[..., str]`, `include_alias: bool`, `empty_text: str`, `limit: int | None` | `Tuple[str, Dict[str, str]]` | Render grouped whitelist sections with compact one-line rows and alias mapping.
- `build_whitelist_users_chunks` | `modules.shared.whitelist_users` | `entries: Iterable[Dict[str, Any]]`, `meta_map: Dict[str, Any]`, `summary_map: Dict[str, Any]`, `format_summary: Callable[..., str]`, `include_alias: bool`, `empty_text: str`, `safe_limit: int`, `continuation_header: str` | `Tuple[List[str], Dict[str, str], bool]` | Render whitelist user sections into Telegram-safe message chunks and aggregate alias mapping.

## `modules/storage.py`
- `StorageLimitError` | `modules.storage` | — | — | Raised when a storage operation would exceed a security limit.
- `StorageManager` | `modules.storage` | — | — | Manage per-user alert data with atomic writes, migrations, and media safety.
- `resolve_user_data_dir` | `StorageManager` | `user_id`, `create` | — | Return the canonical per-user data directory path.
- `resolve_user_images_dir` | `StorageManager` | `user_id`, `create` | — | Return the canonical per-user images directory path.
- `resolve_local_image_path` | `StorageManager` | `user_id`, `local_image_path`, `require_exists` | — | Resolves alert local image path to a safe absolute path inside:
- `get_user_event_log_path` | `StorageManager` | `user_id` | — | Canonical destination for per-user event logs.
- `migrate_user_event_log` | `StorageManager` | `user_id` | — | Move/merge legacy data/<user_id>/logs/events.log into data/userlog.d/<user_id>_events.log.
- `get_user_write_lock` | `StorageManager` | `user_id` | — | Return the reentrant per-user write lock for context-managed writes.
- `get_user_folder_size` | `StorageManager` | `user_id` | — | Returns total size in bytes of the user's data folder.
- `log_user_event` | `StorageManager` | `user_id`, `event_type`, `payload` | — | Append a structured log line for a user.
- `is_user_whitelisted` | `StorageManager` | `user_id` | — | Returns True when the user is present in whitelist/roles policy.
- `get_user_role` | `StorageManager` | `user_id` | — | Returns user role: developer/admin/user or None when unauthorized.
- `setup_user_space` | `StorageManager` | `user_id` | — | Create or migrate a user's storage space to the current schema.
- `get_all_alerts` | `StorageManager` | `user_id` | — | Reads the entire JSON for the user.
- `get_user_snapshot` | `StorageManager` | `user_id`, `include_images`, `include_logs`, `ensure_space` | — | Returns a consistent snapshot of user data and related files under a lock.
- `restore_user_from_data` | `StorageManager` | `user_id`, `alerts_data` | — | Validate, normalize, and atomically persist restored user alerts payload.
- `get_backup_prefs` | `StorageManager` | `user_id` | — | Return merged backup preferences with defaults applied.
- `get_user_prefs` | `StorageManager` | `user_id` | — | Return merged user preferences with defaults applied.
- `get_user_meta` | `StorageManager` | `user_id` | — | Return user metadata, falling back to default metadata shape.
- `update_user_meta` | `StorageManager` | `user_id`, `updates`, `ensure_space` | — | Persist user metadata updates and return the merged metadata snapshot.
- `touch_user_activity` | `StorageManager` | `user_id` | — | Update last_seen for a user, throttled to avoid excessive disk I/O.
- `update_user_prefs` | `StorageManager` | `user_id`, `updates`, `ensure_space` | — | Persist user preference updates and return the merged preferences.
- `update_birthday_schedule_time` | `StorageManager` | `user_id`, `time_str`, `user_prefs` | — | Update birthday alert times and recompute their next scheduled occurrences.
- `update_backup_prefs` | `StorageManager` | `user_id`, `updates`, `ensure_space` | — | Persist backup preference updates and return the merged preferences.
- `save_birthdays_bulk` | `StorageManager` | `user_id`, `entries`, `source` | — | Atomically saves multiple birthday alerts in one storage transaction.
- `save_alert` | `StorageManager` | `user_id`, `alert_data` | — | Persist a new alert, compute next_scheduled, and return the allocated alert ID.
- `delete_alert` | `StorageManager` | `user_id`, `alert_id` | — | Delete an alert and clean related postpone entries and local media files.
- `toggle_alert` | `StorageManager` | `user_id`, `alert_id` | — | Toggle an alert active flag, clearing stale snooze state when re-enabling it.
- `get_user_tags` | `StorageManager` | `user_id` | — | Returns the list of custom tags for a user, or the default list.
- `add_user_tag` | `StorageManager` | `user_id`, `tag_name` | — | Adds a new tag to the user's master list.
- `delete_user_tag` | `StorageManager` | `user_id`, `tag_to_del` | — | Removes a tag from the master list and all alerts.
- `rename_user_tag` | `StorageManager` | `user_id`, `old_tag`, `new_tag` | — | Rename old_tag to new_tag in the master list and propagate to every alert that carries it.
- `download_image` | `StorageManager` | `bot`, `user_id`, `file_id` | — | Download Telegram media into user storage with lock-serialized final placement.
- `get_all_users` | `StorageManager` | — | — | Returns a list of all user_ids that have data folders.
- `get_all_dataset_users` | `StorageManager` | `raise_on_error` | — | Returns numeric user IDs that have a dataset directory with alerts.json.
- `get_active_alerts` | `StorageManager` | `user_id` | — | Returns only alerts where active=True for a given user.
- `get_alert_by_id` | `StorageManager` | `user_id`, `alert_id` | — | Returns a single alert by ID, or None if not found.
- `get_alert_by_shortcode` | `StorageManager` | `user_id`, `shortcode` | — | Returns a single alert by permanent user-local shortcut code.
- `update_alert_fields` | `StorageManager` | `user_id`, `alert_id`, `updates` | — | Updates arbitrary top-level fields on an alert.
- `update_alert_schedule_state` | `StorageManager` | `user_id`, `alert_id`, `last_triggered`, `next_scheduled`, `snoozed_until`, `fuzzy_history` | — | Update scheduling metadata for an alert in one atomic storage mutation.
- `clear_alert_snooze` | `StorageManager` | `user_id`, `alert_id` | — | Clears the snoozed_until field for an alert.
- `mark_alert_done` | `StorageManager` | `user_id`, `alert_id` | — | Marks an alert as 'done' for this occurrence.
- `consume_repetition_occurrence` | `StorageManager` | `user_id`, `alert_id`, `should_count` | — | Atomically normalizes/decrements repetition for one alert occurrence.
- `get_all_active_alerts_all_users` | `StorageManager` | — | — | Returns a dict of {user_id: [active_alerts]} for all users.
- `get_postpone_queue` | `StorageManager` | `user_id` | — | Return the stored postpone queue for a user.
- `add_postpone_instance` | `StorageManager` | `user_id`, `instance` | — | Append a postpone instance and emit the corresponding user event.
- `update_postpone_instance` | `StorageManager` | `user_id`, `instance_id`, `updates` | — | Update one postpone instance and report whether it was found.
- `remove_postpone_instance` | `StorageManager` | `user_id`, `instance_id` | — | Remove one postpone instance and report whether removal occurred.
- `cleanup_postpone_queue` | `StorageManager` | `user_id`, `now_iso` | — | Removes any postpone instances that are not pending.
- `expire_pending_postpones_for_alert` | `StorageManager` | `user_id`, `alert_id` | — | Marks pending postpone items for a given alert as expired.

## `modules/storage_core/alert_service.py`
- `AlertService` | `modules.storage_core.alert_service` | — | — | Handle alert save/delete/toggle mutations through the storage manager.
- `save_alert` | `AlertService` | `user_id`, `alert_data` | — | Persist a new alert, compute next_scheduled, and return the allocated alert ID.
- `delete_alert` | `AlertService` | `user_id`, `alert_id` | — | Delete an alert and clean related postpone entries and local media files.
- `toggle_alert` | `AlertService` | `user_id`, `alert_id` | — | Toggle an alert active flag, clearing stale snooze state when re-enabling it.

## `modules/storage_core/birthday_service.py`
- `BirthdayService` | `modules.storage_core.birthday_service` | — | — | Own bulk birthday import with tag resolution and atomic multi-insert.
- `save_birthdays_bulk` | `BirthdayService` | `user_id`, `entries`, `source` | — | Atomically saves multiple birthday alerts in one storage transaction.

## `modules/storage_core/postpone_service.py`
- `PostponeService` | `modules.storage_core.postpone_service` | — | — | Manage postpone queue add/update/remove/cleanup/expire mutations.
- `add_postpone_instance` | `PostponeService` | `user_id`, `instance` | — | Append a postpone instance and emit the corresponding user event.
- `update_postpone_instance` | `PostponeService` | `user_id`, `instance_id`, `updates` | — | Update one postpone instance and report whether it was found.
- `remove_postpone_instance` | `PostponeService` | `user_id`, `instance_id` | — | Remove one postpone instance and report whether removal occurred.
- `cleanup_postpone_queue` | `PostponeService` | `user_id`, `now_iso` | — | Removes any postpone instances that are not pending.
- `expire_pending_postpones_for_alert` | `PostponeService` | `user_id`, `alert_id` | — | Marks pending postpone items for a given alert as expired.

## `modules/storage_core/scheduler_state_service.py`
- `SchedulerStateService` | `modules.storage_core.scheduler_state_service` | — | — | Own per-alert schedule-state, snooze, done-marking, and repetition mutations.
- `update_alert_fields` | `SchedulerStateService` | `user_id`, `alert_id`, `updates` | — | Atomically update arbitrary alert fields for a single alert.
- `update_alert_schedule_state` | `SchedulerStateService` | `user_id`, `alert_id`, `last_triggered`, `next_scheduled`, `snoozed_until`, `fuzzy_history` | — | Update scheduling metadata for an alert in one atomic storage mutation.
- `clear_alert_snooze` | `SchedulerStateService` | `user_id`, `alert_id` | — | Clears the snoozed_until field for an alert.
- `mark_alert_done` | `SchedulerStateService` | `user_id`, `alert_id` | — | Marks an alert as 'done' for this occurrence.
- `consume_repetition_occurrence` | `SchedulerStateService` | `user_id`, `alert_id`, `should_count` | — | Atomically normalizes/decrements repetition for one alert occurrence.

## `modules/storage_core/tag_service.py`
- `TagService` | `modules.storage_core.tag_service` | — | — | Manage tag add/delete/rename mutations in user storage payloads.
- `add_user_tag` | `TagService` | `user_id`, `tag_name` | — | Adds a new tag to the user's master list.
- `delete_user_tag` | `TagService` | `user_id`, `tag_to_del` | — | Removes a tag from the master list and all alerts.
- `rename_user_tag` | `TagService` | `user_id`, `old_tag`, `new_tag` | — | Rename old_tag to new_tag in the master list and propagate to every alert that carries it.

## `modules/storage_core/user_prefs_service.py`
- `UserPrefsService` | `modules.storage_core.user_prefs_service` | — | — | Handle user preference and metadata mutations through the storage layer.
- `update_user_meta` | `UserPrefsService` | `user_id`, `updates`, `ensure_space` | — | Persist user metadata updates and return the merged metadata snapshot.
- `touch_user_activity` | `UserPrefsService` | `user_id` | — | Update last_seen for a user, throttled to avoid excessive disk I/O.
- `update_user_prefs` | `UserPrefsService` | `user_id`, `updates`, `ensure_space` | — | Persist user preference updates and return the merged preferences.
- `update_birthday_schedule_time` | `UserPrefsService` | `user_id`, `time_str`, `user_prefs` | — | Update birthday alert times and recompute their next scheduled occurrences.
- `update_backup_prefs` | `UserPrefsService` | `user_id`, `updates`, `ensure_space` | — | Persist backup preference updates and return the merged preferences.

## `modules/systemlog.py`
- `get_log_maintenance_metrics` | `modules.systemlog` | — | — | Return normalized runtime metrics for log-maintenance housekeeping.
- `get_retention_days_for_path` | `modules.systemlog` | `path` | — | Resolve effective retention days for a log file path.
- `clear_logger_cache` | `modules.systemlog` | `close_handlers` | — | Clear cached JSON loggers and optionally close their handlers.
- `update_runtime_state_key` | `modules.systemlog` | `key`, `value` | — | Atomically update a single key in runtime_state.json.
- `force_runtime_state_untrust` | `modules.systemlog` | — | `bool` | Invalidate runtime-state trust markers so startup reliability is downgraded.
- `derive_startup_downtime_window` | `modules.systemlog` | `now_dt`, `runtime_state` | — | Derive startup offline window bounds from runtime_state.json.
- `append_json_log` | `modules.systemlog` | `path`, `record` | — | Public helper for JSONL logs with rotation + retention.
- `log_system` | `modules.systemlog` | `category`, `event`, `payload`, `level` | — | Write a structured system log entry.
- `log_downtime_summary` | `modules.systemlog` | — | — | Logs a startup downtime summary based on persisted runtime state.
- `mark_runtime_shutdown` | `modules.systemlog` | `clean` | — | Persist runtime shutdown markers for startup downtime reconstruction.

## `modules/tags_logic.py`
- `contains_emoji` | `modules.tags_logic` | `text` | — | Check if text contains at least one emoji.
- `parse_tag` | `modules.tags_logic` | `tag_string` | — | Splits a tag string into (emoticon, name).
- `extract_tag_name` | `modules.tags_logic` | `tag_string` | — | Extracts just the name portion from a tag string.
- `validate_tag_format` | `modules.tags_logic` | `tag_string` | — | Validates that a tag follows the format: "emoji name"
- `normalize_tag_input` | `modules.tags_logic` | `tag_string` | — | Strip and collapse all internal whitespace runs to a single space.
- `get_tag_stats` | `modules.tags_logic` | `user_data` | — | Counts alerts per tag and identifies untagged alerts.
- `partition_used_tags_by_master_order` | `modules.tags_logic` | `alerts`, `master_tags` | — | Return used master tags in master-list order plus first-seen orphan tags.
- `alert_has_any_orphan_tag` | `modules.tags_logic` | `alert`, `master_tags` | — | Return whether an alert contains at least one tag absent from the master list.

## `modules/telegram_resilience.py`
- `is_retryable_telegram_error` | `modules.telegram_resilience` | `exc` | — | Classify Telegram exceptions that should be retried with backoff.
- `is_message_not_modified_error` | `modules.telegram_resilience` | `exc` | — | Detect Telegram no-op edit failures that should be treated as benign.
- `ApiFailureTracker` | `modules.telegram_resilience` | — | — | Sliding-window tracker for API failures, with per-user + global degraded flags.
- `record_failure` | `ApiFailureTracker` | `chat_id` | — | Record one API-health failure and return degraded-state snapshot metadata.
- `record_success` | `ApiFailureTracker` | `chat_id` | — | Prune stale failures after a success and return current degraded snapshot.
- `snapshot` | `ApiFailureTracker` | `chat_id` | — | Return current degraded-state snapshot without recording a new failure.
- `run_with_retry` | `modules.telegram_resilience` | `operation`, `chat_id`, `call_coro_factory`, `log_callback`, `tracker`, `attempts`, `max_window_seconds`, `base_delay_seconds`, `max_delay_seconds` | — | Runs a Telegram API call with bounded retry for retryable network/timeout errors.

## `modules/timezone_catalog.py`
- `list_timezones` | `modules.timezone_catalog` | — | `list[str]` | Return the cached sorted list of available IANA timezone names.
- `list_areas` | `modules.timezone_catalog` | — | `set[str]` | Return top-level timezone area names derived from the catalog cache.
- `describe_timezone` | `modules.timezone_catalog` | `tz_name: str`, `reference: datetime | None` | `str` | Render a timezone label including its current UTC offset.
- `suggest_timezones` | `modules.timezone_catalog` | `query: str`, `limit: int | None` | `list[str]` | Return best-match timezone suggestions for free-text user input.

## `modules/timezone_geo.py`
- `resolve_timezone_from_location` | `modules.timezone_geo` | `latitude: float`, `longitude: float` | `Optional[str]` | Resolve an IANA timezone name from geographic coordinates.

## `modules/timezone_utils.py`
- `validate_tz_name` | `modules.timezone_utils` | `name: str | None` | `bool` | Return whether the provided timezone name resolves in the current tz database.
- `get_server_tz_name` | `modules.timezone_utils` | — | `str` | Return the configured server timezone name with a safe default.
- `get_server_tz` | `modules.timezone_utils` | — | `ZoneInfo` | Return the server timezone object, falling back to UTC when unavailable.
- `resolve_user_timezone` | `modules.timezone_utils` | `user_prefs: dict | None` | `ZoneInfo` | Resolve the effective timezone for user-facing scheduling and parsing.
- `now_server_naive` | `modules.timezone_utils` | — | `datetime` | Return the current server-local time as a naive datetime.
- `to_user_naive_from_server` | `modules.timezone_utils` | `server_dt: datetime`, `user_tz: ZoneInfo`, `server_tz: ZoneInfo | None` | `datetime` | Convert a server timestamp into user-local naive wall time.
- `to_server_naive_from_user` | `modules.timezone_utils` | `local_dt: datetime`, `user_tz: ZoneInfo`, `server_tz: ZoneInfo | None` | `tuple[datetime, bool]` | Convert user-local wall time to server-local naive time with DST-gap handling.
- `localize_with_shift` | `modules.timezone_utils` | `local_dt: datetime`, `tz: ZoneInfo` | `tuple[datetime, bool]` | Attach timezone to naive datetime. If local time is invalid (DST gap),
- `compute_next_occurrence` | `modules.timezone_utils` | `alert: dict`, `reference_server_dt: datetime | None`, `user_prefs: dict | None` | `tuple[datetime | None, bool]` | Compute the next alert occurrence in server-naive time for scheduler storage.
- `resolve_fuzzy_next_scheduled` | `modules.timezone_utils` | `alert: dict`, `reference_server_dt: datetime`, `user_prefs: dict | None`, `last_fired_at: datetime | None`, `record_history: bool`, `history_source: str | None` | `tuple[int | None, datetime | None, bool]` | Resolve the next fuzzy daily occurrence in server-naive time while preserving user-local repetition semantics.
- `format_tz_offset` | `modules.timezone_utils` | `dt: datetime`, `tz: ZoneInfo` | `str` | Format the UTC offset for a datetime in the target timezone.
- `parse_user_datetime_expression` | `modules.timezone_utils` | `raw_text: str | None`, `reference_server_dt: datetime | None`, `user_prefs: dict | None`, `default_time: str | None`, `assume_year_policy: str`, `allow_relative_tokens: bool`, `allow_day_only: bool`, `boundary_mode: str | None`, `boundary_server_dt: datetime | None`, `now_server_dt: datetime | None` | `tuple[str, datetime | None, dict]` | Parse datetime expressions into a server-naive candidate and enforce optional boundary policies.
- `normalize_one_time_date` | `modules.timezone_utils` | `raw_date: str | None`, `reference_server_dt: datetime | None`, `user_prefs: dict | None`, `require_year_if_today: bool`, `time_str: str | None` | `tuple[str, str | None, bool, str | None]` | Normalize a one-time date string.

## `modules/ui/formatters/alert_text.py`
- `format_pa` | `modules.ui.formatters.alert_text` | `alert: dict`, `main_trigger_time`, `scheduled_time` | `str` | Render the pre-alert notification text for a non-birthday alert (PA).
- `format_aa` | `modules.ui.formatters.alert_text` | `alert: dict`, `scheduled_time`, `user_prefs` | `str` | Render the main alert notification text (AA).
- `format_ghost_alert` | `modules.ui.formatters.alert_text` | `alert: dict`, `trigger_time` | `str` | Render a ghost-reminder notification message.
- `format_missed_alert` | `modules.ui.formatters.alert_text` | `alert: dict`, `missed_time` | `str` | Render a missed-alert startup-recovery notification.
- `format_missed_alerts_summary` | `modules.ui.formatters.alert_text` | `standard_items: list`, `missed_ghost_items: list | None`, `pending_ghost_alerts: list | None` | `str | None` | Render startup missed-alert summary sections for standard and ghost items.

## `modules/ui/formatters/birthday_text.py`
- `format_pb` | `modules.ui.formatters.birthday_text` | `alert: dict`, `main_trigger_time`, `scheduled_time`, `user_prefs` | `str` | Render the pre-alert notification text for a birthday alert (PB).
- `format_bb` | `modules.ui.formatters.birthday_text` | `alert: dict`, `scheduled_time`, `user_prefs` | `str` | Render the main birthday notification text (BB).

## `modules/ui/formatters/info_text.py`
- `format_ia` | `modules.ui.formatters.info_text` | `alert: dict`, `user_prefs` | `str` | Render the alert detail card text (IA).
- `format_ib` | `modules.ui.formatters.info_text` | `alert: dict`, `user_prefs` | `str` | Render the birthday detail card text (IB).

## `modules/ui/formatters/shared.py`
- `format_tags_line` | `modules.ui.formatters.shared` | `tags: list` | `str` | Render a tag list as ':icon: name, :icon: name' or '🏷️ Untagged' when empty.
- `format_alert_type_rows` | `modules.ui.formatters.shared` | `alert: dict` | `list` | Return type-specific schedule fields with ├─ / ╰─ tree prefixes for the IA detail card.
- `format_time_until` | `modules.ui.formatters.shared` | `main_trigger_time`, `now` | `str` | Return a human-readable countdown string for time remaining until main_trigger_time.
- `format_next_occurrence_line` | `modules.ui.formatters.shared` | `alert`, `reference_dt` | `str | None` | Return a formatted next-occurrence line, or None when no future occurrences exist.
- `append_zodiac_block` | `modules.ui.formatters.shared` | `alert`, `user_prefs` | `str` | Return a zodiac info string (with leading \n\n) to append to birthday messages.

## `modules/ui/keyboards/callbacks.py`
- `ts` | `modules.ui.keyboards.callbacks` | `dt` | `str` | Return seconds-since-epoch string for use in callback payloads.
- `build_postpone_callback` | `modules.ui.keyboards.callbacks` | `action`, `kind`, `alert_id`, `original_time`, `occurrence_time`, `postpone_count` | `str` | Return a postpone callback payload string for the given action, kind, and alert context.
- `build_prealert_info_callback` | `modules.ui.keyboards.callbacks` | `alert_id`, `original_time`, `occurrence_time`, `postpone_count` | `str` | Return a pre-alert info callback payload that opens the detail card from a pre-alert notification.
- `build_alert_info_callback` | `modules.ui.keyboards.callbacks` | `alert_id`, `original_time`, `occurrence_time`, `postpone_count` | `str` | Return an alert info callback payload that opens the detail card from an alert notification.
- `build_placebo_noted_callback` | `modules.ui.keyboards.callbacks` | `alert_id`, `original_time`, `occurrence_time` | `str` | Return a pre-alert NOTED callback payload using the pnote_ prefix.
- `build_bday_noted_callback` | `modules.ui.keyboards.callbacks` | `alert_id`, `original_time`, `occurrence_time` | `str` | Return a birthday NOTED callback payload; delegates to the birthday message suggestion callbacks module.
- `build_notif_back_callback` | `modules.ui.keyboards.callbacks` | `kind: str`, `alert_id: str`, `original_time`, `occurrence_time`, `postpone_count: int` | `str` | Return a 'back to notification' callback for detail views opened from a notification.

## `modules/ui/keyboards/detail_kb.py`
- `build_detail_keyboard` | `modules.ui.keyboards.detail_kb` | `alert: dict`, `source: str`, `from_notification: bool`, `kind: str`, `occurrence_time`, `original_time`, `postpone_count: int`, `include_back: bool`, `tag_filter: str` | `InlineKeyboardMarkup` | Build the detail card keyboard with context-sensitive rows.

## `modules/ui/keyboards/notification_kb.py`
- `get_toggle_action_label` | `modules.ui.keyboards.notification_kb` | `alert: dict` | `str` | Return SNOOZE or ACTIVATE label based on alert.active state.
- `build_alert_notification_keyboard` | `modules.ui.keyboards.notification_kb` | `alert: dict`, `occurrence_time`, `original_time`, `postpone_count: int` | `InlineKeyboardMarkup` | Keyboard for AA (regular alert notification).
- `build_birthday_notification_keyboard` | `modules.ui.keyboards.notification_kb` | `alert: dict`, `occurrence_time`, `original_time`, `postpone_count: int` | `InlineKeyboardMarkup` | Keyboard for BB (birthday notification).
- `build_prealert_notification_keyboard` | `modules.ui.keyboards.notification_kb` | `alert: dict`, `occurrence_time`, `original_time`, `postpone_count: int` | `InlineKeyboardMarkup` | Keyboard for PA and PB (pre-alert notifications, both alert and birthday).
- `build_missed_alert_keyboard` | `modules.ui.keyboards.notification_kb` | `alert: dict` | `InlineKeyboardMarkup` | Keyboard for missed-alert recovery messages (one DELETE button row).
- `build_ghost_notification_keyboard` | `modules.ui.keyboards.notification_kb` | `alert: dict`, `occurrence_time`, `scheduled_time` | `InlineKeyboardMarkup` | Build the ghost-alert notification keyboard with noted/postpone/detail/delete actions.

## `modules/ui/send_utils.py`
- `send_alert` | `modules.ui.send_utils` | `bot`, `user_id: int`, `alert: dict`, `alert_type: str`, `missed_time`, `pre_alert_str: str | None`, `main_trigger_time`, `scheduled_time`, `occurrence_time`, `postpone_count: int`, `storage` | `object | None` | Send an alert notification (pre-alert, main, or missed) to the user.

## `modules/zodiac.py`
- `get_western_zodiac` | `modules.zodiac` | `day: int`, `month: int` | `dict | None` | Return Western zodiac info for (day, month), or None if invalid.
- `get_eastern_zodiac` | `modules.zodiac` | `day: int`, `month: int`, `year: int` | `dict | None` | Return Eastern (Chinese) zodiac info for (day, month, year), or None.
- `get_zodiac_info` | `modules.zodiac` | `day: int`, `month: int`, `year: int | None` | `dict` | Return combined zodiac info dict with keys: western, eastern.
- `format_western_line` | `modules.zodiac` | `western: dict` | `str` | Format a Western zodiac dict as a compact line.
- `format_eastern_line` | `modules.zodiac` | `eastern: dict` | `str` | Format an Eastern zodiac dict as a compact line.
