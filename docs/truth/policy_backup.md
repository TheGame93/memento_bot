# Backup Policy

## (a) Inclusion predicate
- User backup includes only user-owned persistent state under `data/<user_id>/` plus declared per-user metadata stored in `alerts.json` (alerts, birthdays, tags, prefs/meta), and user media under `images/`.
- System backup includes project/runtime system scope required for administrative recovery (`code`, `data/system`, and other policy-allowed runtime/system artifacts), excluding user-scoped `data/<user_id>/` snapshots unless mode explicitly includes full data.

## (b) Exclusion rules
- Exclude logs (`data/systemlog.d/`, `data/userlog.d/`) from user backups to avoid privacy-leak and excessive archive growth.
- Exclude lock/runtime transient files (lock files, ephemeral staging, transient temp files) to prevent restoring stale process state.
- Exclude prior export/import archive artifacts from backup payloads to avoid recursive archive amplification.

## (c) Ownership table
- `data/<user_id>/alerts.json`: user backup
- `data/<user_id>/images/*`: user backup
- `backups/users/<user_id>/local|exports|monthly`: backup artifacts (managed outputs; not imported as source-of-truth)
- `backups/users/<user_id>/pre_import`: pre_import only (restore safety snapshots)
- `data/system/*`: system backup
- `data/systemlog.d/*`: neither
- `data/userlog.d/*`: neither
- New persistent files must be classified into one of: user backup / system backup / pre_import only / neither before merge.

## (d) Folder layout
- Per-user backup layout: `backups/users/<user_id>/{local,exports,monthly,pre_import}`.
- System backup root: `backups/system/` by default, rooted at `BOT_BACKUP_DIR/system` when `BOT_BACKUP_DIR` is set.

## (e) Retention policy
- Main folders (`local`, `exports`, `monthly`) use tiered retention: daily 7, weekly 4, monthly 6, yearly 10.
- `pre_import` is special: daily 3 only; no weekly/monthly/yearly tiers.

## (f) Quota policy
- `USER_BACKUP_QUOTA_BYTES = 100 MB` applied across per-user `local+exports+monthly`.
- `pre_import` and system backups are quota-exempt.
- `EMAIL_BACKUP_MAX_ATTACHMENT_BYTES = 20 MB`.
- `TELEGRAM_EXPORT_MAX_BYTES = 45 MB`.

## (g) Integrity contract
- Canonical manifest `schema_version` is `"1.0"`.
- Bump rules: additive/backward-compatible changes `+0.1`; breaking changes `+1.0`.
- Restore/import requires strict schema equality and valid per-file SHA256 digests.
- Missing, mismatched, or malformed hash/schema fields must be rejected.

## (h) Restore semantics
- Restore is exact-match for user scope: restored archive becomes authoritative target state.
- Stale images absent from archive are deleted.
- User restore does not touch `data/userlog.d/`.
- Critical sections run under per-user StorageManager write lock.
- Atomic-swap order must preserve durability and rollback safety.
- Post-restore cleanup prunes scheduler per-user caches (`sent_pre_alerts`, `notified_missed_pre`, `pending_missed_notifications`).
- Runtime trust markers are invalidated after restore (`runtime_state` downgrade flags).

## (i) Authorization scopes
- User can restore/export own backup only.
- Admin can operate on regular users (role `user`) via managed flows.
- Admin must not restore/export admin/developer user backups through user-scope admin flow.
- Developer can operate across all users and system backup surfaces.

## (j) System-restore guards
- Reject restore when actor identity is missing/unknown (`actor_unknown`).
- Reject self-downgrade scenarios that would remove current acting developer authority.
- Reject archives that would leave the system without any developer role.

## (k) Event taxonomy
- Required backup events:
  - `backup_created`
  - `backup_restored`
  - `backup_imported`
  - `backup_exported`
  - `backup_deleted`
  - `backup_create_failed`
  - `backup_restore_failed`
  - `admin_user_backup_restored`
  - `developer_system_backup_restored`
  - `developer_system_backup_exported`
- Event payloads must follow `docs/truth/policy_log.md` privacy rules (no raw sensitive content in logs).
