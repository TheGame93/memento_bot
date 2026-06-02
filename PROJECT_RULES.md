# Recurring Alert Bot — AI Agent Quick-Orientation

## What This Is
A Telegram notification engine for recurring and one-time alerts (not a calendar app).
Runs on a Linux server, stores per-user data in JSON files, sends alerts via Telegram.

## Alert Types (full specs: `docs/truth/bot_alert_types.md`)
| Type | Name | Recurrence |
|---|---|---|
| 1 | Monthly (day) | Specific calendar day(s), every N months |
| 2 | Monthly (rel.) | Relative weekday (e.g. "last Monday"), every N months |
| 3 | Weekly | Specific weekday(s), every N weeks |
| 4 | Yearly | Specific DD/MM date(s) |
| 5 | Once | One-time, single date; fires immediately if date is past |
| 6 | Birthday | Yearly, alert time at 10:00/CUSTOM, no picture |
| 7 | Daily | Every N days, anchored to a start marker |

Repetition (`forever`/`until_date`/`count`) supported on types 1–4, 7. Types 5 and 6 must not persist `repetition`.
All alerts support: pre-alerts, custom time, tags.
All alerts except Birthday support: optional media.

## Critical Files
- `mainbot.py` — bot bootstrap: handlers, auth guard, scheduler wiring, API wrappers
- `startbot.sh` — launcher (venv bootstrap, lock, respawn-on-crash)
- `modules/storage.py` — atomic JSON read/write; **always use this, never raw file I/O**
- `modules/scheduler.py` — public scheduler facade (tick-based, 60s intervals)
- `modules/shared/callback_codec.py` — Telegram callback tokenizer (64-byte limit)
- `modules/telegram_resilience.py` — retry/fallback wrappers for Telegram API calls
- `modules/constants.py` — conversation states, callback constants, scheduler/security limits
- `data/<user_id>/alerts.json` — canonical per-user DB (alerts, birthdays, tags, prefs)

## Module Map
| Directory | Responsibility |
|---|---|
| `modules/` (root) | Core logic: scheduler, storage, logging, tags, timezone, utils |
| `modules/backup_core/` | Backup/export/import: local rolling, email, system export, manifests |
| `modules/scheduler_core/` | Scheduler lifecycle, tick orchestration, alert actions, missed-alert recovery |
| `modules/security/` | Authorization, roles, whitelist store, whitelist notifications |
| `modules/shared/` | Cross-cutting utilities: callback codec, paths, logging helpers, status render |
| `modules/handlers/` | Telegram command/callback handlers |
| `modules/handlers/add_flow/` | Alert creation wizard (type → schedule → media → summary) |
| `modules/handlers/birthday_flow/` | Birthday add/edit/list/search flows |

## Hard Constraints (do not break these)
- **Callback data: 64-byte hard limit.** Telegram inline keyboard callback payloads must fit in 64 bytes. Always use `modules/shared/callback_codec.py` for encoding.
- **Callback query answer contract.** Each callback query must be answered at most once. Never call `query.answer(...)` twice in the same handler path; choose either a popup answer (`show_alert=True`) or a single non-popup ack.
- **Tag-filter orphan UX contract.** `/list` and `/birthdays` filter menus must build known-tag buttons from tags actually used in scope, preserving master-tag JSON order; when orphan tags exist they must expose a `🧩 Orphan tag` filter and send a second warning message listing orphan tags with Markdown escaping and Telegram-length safety. Orphan-filter callbacks that become stale must fail soft with a refresh instruction, and orphan filter results must include items that contain at least one orphan tag even when known tags are also present.
- **Atomic JSON writes only.** All user DB writes go through `modules/storage.py`. Never write JSON files directly — partial writes corrupt data on power loss.
- **Privacy-first logging.** Never log raw message text. Use SHA256 hash + length via `modules/shared/logging_utils.py`. See `docs/truth/policy_log.md` for full policy.
- **UTC-internal time logic.** Scheduler stores and compares times in UTC. User-facing display converts to the user's configured timezone.
- **Feb 29 adjustment.** Yearly alerts on Feb 29 auto-adjust to Feb 28 in non-leap years.
- **Markdown escape policy (legacy Markdown).** The codebase uses `ParseMode.MARKDOWN` (legacy), NOT MarkdownV2. Use helpers by context: `md_escape()` for general inline Markdown text, `md_escape_inline_code()` for inline-code spans, `md_escape_fence_content()` for code-fence content (inside `` ``` ``), and `md_escape_multiline_text()` for multiline non-fence text. Never define local escape functions — import from `markdown_utils` only.
- **Input length limits.** Free-text user inputs enforce maximum lengths: title (200), additional\_info (2000), custom\_name (100), request\_message (500). Constants defined in `modules/constants.py`.
- **File upload policy.** Photo uploads: only compressed photos accepted (Telegram `photo` field, not `document`). Only `file_id` and scoped local path stored. ZIP imports: path normalization, symlink rejection, size limits enforced in `modules/backup_core/archive.py`.
- **Backup manifest schema contract.** Canonical backup `schema_version` is `"1.0"`; strict mismatch rejection is required. Additive changes bump `+0.1`, breaking changes bump `+1.0`.
- **Backup quota and transport caps.** Enforce `USER_BACKUP_QUOTA_BYTES` for user backup artifacts; enforce `EMAIL_BACKUP_MAX_ATTACHMENT_BYTES` and `TELEGRAM_EXPORT_MAX_BYTES` on delivery paths.
- **Restore lock + atomic-swap contract.** User restore critical sections run under StorageManager per-user write lock and preserve atomic-swap ordering/durability guarantees.
- **Restore same-filesystem staging contract.** Restore image staging and upload temp placement must live under `resolve_user_data_dir(user_id)` (never system `/tmp`) to prevent `EXDEV` swap failures.
- **Restore scheduler/runtime cleanup contract.** After user restore, prune user-scoped `sent_pre_alerts`, `notified_missed_pre`, and `pending_missed_notifications`, and invalidate runtime trust markers in `runtime_state`.
- **Post-restore degraded shield contract.** Deterministic stale-media failures after restore must not increment degraded-mode counters.
- **System-restore guard contract.** System restore must enforce actor identity checks, self-downgrade protection, and system-viability guard (at least one developer remains).
- **Pre-import backup policy contract.** `pre_import` backups are quota-exempt safety snapshots with retention daily=3 only.
- **Single-instance lock (dual scope).** `mainbot.py` enforces both `data/systemlog.d/mainbot.lock` and token-global lock `${BOT_GLOBAL_LOCK_DIR:-/tmp/recurring_alert_bot_locks}/mainbot_<token_hash>.lock`. Do not bypass either scope.
- **Startup env-before-lock invariant.** Validate required startup env (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_USER_ID`) before attempting singleton lock acquisition, so misconfigured startups do not generate misleading lock-conflict outcomes.
- **Local media path scope.** Stored `local_image_path` must be user-relative (`images/...`) and resolve strictly inside the current `StorageManager.base_data_dir/<user_id>/images` subtree. No sibling-worktree traversal, no parent traversal (`..`), and no absolute cross-root references.
- **No-op edit semantics.** Telegram `BadRequest: Message is not modified` must be treated as a benign no-op, not as an operational error path.
- **Degraded-mode failure scope.** API degraded counters track API-health failures only (retryable timeout/network/retry-after class). Deterministic `BadRequest` failures must not increment degraded counters or trigger degraded-mode transition events.
- **Tag write target scope.** Tag add/remove writes must resolve against `get_target_user_id(...)` (acting-as target when present), never blindly against `effective_user.id`.
- **Postponed alert log contract.** `scheduler.alert_sent` must include `is_postponed`, `postpone_id`, `effective_fire_time`, and `postpone_count`; non-postponed sends must log explicit defaults (`false`/`null`/`null`/`0`).
- **Startup recovery ordering contract.** Scheduler startup must restore `sent_pre_alerts` (`load_pre_alert_state()`) before running missed-alert recovery.
- **Missed pre-alert causality contract.** Startup missed-pre classification must be bounded by a reliable offline window from runtime state; when the offline window is missing/unreliable, missed pre-alerts must be skipped (diagnostics-only).
- **Birthday evening pre-alert resolver contract.** The dedicated birthday token `bday_evening_before` must be resolved only through `resolve_pre_alert_fire_time(...)` (timezone-aware), never treated as a numeric duration via `parse_pre_alert_string(...)`.
- **Birthday message callback occurrence contract.** Tokenized birthday style callbacks (`bmsg_`) must preserve the fired occurrence timestamp and birthday message inference/selection must use that callback occurrence context (not mutable current schedule state) when deriving turning-age metadata.
- **Runtime-state trust contract.** `derive_startup_downtime_window()` must downgrade `last_shutdown` reliability when guard conditions indicate stale/unsafe provenance (for example `last_exit=running`, runtime identity missing/mismatch, alive previous PID, inconsistent shutdown/startup ordering).
- **Startup scope telemetry contract.** Startup must emit user-scope diagnostics comparing dataset users vs authorized users; warnings must trigger only when auth filtering is enabled and excluded-count crosses threshold (bounded user-id sample only).
- **Repetition count-consumption contract.** Repetition `count` must be consumed only on real due-occurrence sends; pre-alert sends, postponed sends, and `clear_snooze` sends must not decrement the counter.
- **Repetition until-date boundary contract.** `until_date` is inclusive and evaluated on local date semantics (user-local date when `timezone_mode=user`, server-local date otherwise).
- **Daily interval UX contract.** For Daily alerts (`type == 7`), interval prompt must not expose a quick `Each day` button and interval `1` must require explicit confirmation (`I'm sure` / `Change interval`) in both initial add-flow and alert-settings flow.
- **Birthday bulk import atomicity contract.** `settings_bday_bulk_import_continue` must commit through `StorageManager.save_birthdays_bulk(...)` in one transaction after explicit confirmation; never perform per-line partial writes. On success/failure, clear transient bulk-import session keys.
- **Birthday bulk import multi-tag contract.** Import session entries may carry `resolved_tags` (with legacy `resolved_tag` fallback during migration); final confirmation rendering and committed telemetry `untagged_count` must follow that same resolved-tags contract to avoid preview/commit drift.
- **Snooze semantics (`active` field).** Snooze sets `active=false` without clearing `schedule`; the scheduler silently skips inactive alerts. Reactivation sets `active=true` and triggers `next_scheduled` recalculation. Toggle button labels must be state-aware (snooze when active, activate when inactive).
- **Telegram message length limit.** Messages over 4096 characters will fail. Long outputs (bulk export, status, list) must be chunked. Follow existing chunking patterns in `modules/handlers/birthday_flow/bulk_birthdays.py`.
- **Orphaned conversation state.** Always clean up `context.user_data` after conversations end or are cancelled — use `modules/shared/context_cleanup.py`. Stale wizard state from abandoned flows causes incorrect handler routing.
- **Past-date input behavior.** One-time alerts (`type 5`) on past dates fire immediately (not rejected). Recurring alerts on past dates silently advance to the first future occurrence. Do not reject past dates.

## Docstring Policy
- All public functions, methods, and classes require a docstring. Private `_name` helpers may skip only if the body is short and the name is self-explanatory.
- Summary line: imperative mood (`Return...`, `Build...`, `Check...`), one sentence. Must add information the name doesn't already convey — what it returns, what side effect it has, what it guards against. Not a restatement with different words. The index already captures argument names/types and return type from annotations — do not restate what the signature shows; convey semantic meaning instead.
- The summary line is the only line extracted into `docs/truth/info_functions.md` / `docs/truth/info_handlers.md` / `docs/truth/info_mainbotfunctions.md`. A vague summary produces a useless grep result. The body is never included in the index — it lives in source only.
- For complex functions (multiple return paths, error codes, non-obvious invariants), add a blank line after the summary and document the details in the body. Do not omit the body to keep docstrings short — it is read directly from source when an agent opens the file.
- Update the docstring when behavior or signature changes meaningfully.

## Existing Utilities to Reuse (don't reimplement)
Before writing any new helper or handler, grep the relevant index file:
- **`docs/truth/info_functions.md`** (311 entries) — utilities and core modules; grep this before writing any helper function
- **`docs/truth/info_handlers.md`** (337 entries) — `modules/handlers/` subtree; grep this before adding a new handler, callback, or flow step
- **`docs/truth/info_mainbotfunctions.md`** — auto-generated `mainbot.py` public symbol index; grep this before editing bootstrap wiring functions

Grepping one focused file is faster and cheaper than searching the whole codebase.

- `modules/shared/markdown_utils.py` — centralized Markdown escape helpers (`md_escape`, `md_escape_inline_code`, `md_escape_multiline_text`, `md_escape_fence_content`)
- `modules/shared/callback_codec.py` — callback payload encoding/decoding
- `modules/telegram_resilience.py` — retried Telegram API calls with degraded-state tracking
- `modules/shared/logging_utils.py` — safe text hashing for log events
- `modules/shared/paths.py` — canonical project/data/backup/system paths
- `modules/shared/context_cleanup.py` — context-state cleanup after conversations
- `modules/birthday_utils.py` — birthday age/date helpers including leap-day logic
- `modules/tags_logic.py` — tag parsing, validation, stat helpers

## Dev Workflow
- **Start the bot:** `bash startbot.sh`
- **Run all tests:** `venv/bin/python3 tests/master_debugger.py --offline` (the master debugger could run more than 3 minutes)
- **Regenerate function/handler/mainbot indexes:** `python3 scripts/gen_info_functions.py` (run after adding, removing, or renaming public functions)
- **Debugger policy:** `docs/truth/DEBUG_SUITE_DESIGN.md`
- **Logging policy:** `docs/truth/policy_log.md`

## Key Documentation (for deeper context)
- `docs/truth/bot_structure.md` — compact architecture map and truthfile router; includes its own maintenance contract
- `docs/truth/bot_alert_types.md` — alert-type functional specs (type 1–7 inputs, common fields, pre-alert/time/media rules)
- `docs/truth/info_functions.md` — auto-generated utility/core index (311 entries); **grep before writing any helper**
- `docs/truth/info_handlers.md` — auto-generated handler/flow index (337 entries); **grep before adding any handler or callback**
- `docs/truth/info_mainbotfunctions.md` — auto-generated `mainbot.py` public symbol index; **grep before editing main bootstrap symbols**
- Regenerate all three: `python3 scripts/gen_info_functions.py`
- `docs/truth/policy_log.md` — logging policy (privacy rules, event taxonomy, telemetry contracts)
