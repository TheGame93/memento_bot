## Maintenance Contract

`bot_structure.md` is the always-loaded architecture map and truthfile router. It answers:

- Where does this live?
- Which source files, generated indexes, or truthfiles should an agent inspect next?

Update this file only for:

- file topology changes that affect where agents should look;
- module ownership or responsibility changes;
- runtime routing changes, such as handler priority groups or bootstrap flow;
- canonical path/root changes for data, logs, locks, backups, or system state;
- truthfile routing changes.

Do not add:

- detailed feature behavior;
- UI wording or keyboard layout details;
- callback-specific contracts beyond routing ownership;
- telemetry payload lists;
- backup/restore policy details;
- scheduler edge cases;
- feature-history notes.

Put global hard constraints in `PROJECT_RULES.md`. Put domain policy in the relevant truthfile (`bot_alert_types.md`, `policy_log.md`, `policy_backup.md`, `DEBUG_SUITE_DESIGN.md`) or leave discoverable implementation detail in source/tests. Before adding a long section here, either create/extend a focused truthfile or write a deliberate reason why the information must be mandatory-loaded.

When updating this file, verify the repo first with `git ls-files`, `rg --files`, and focused reads of the relevant entrypoints. Do not document generated/runtime directories such as `__pycache__` or `venv`, and do not list architecture-irrelevant root artifacts just because they are tracked.

## Purpose

This project is a Telegram notification engine for recurring and one-time alerts. It is not a calendar app. It stores per-user state in JSON files, sends notifications through Telegram, and runs as a single Linux service process with scheduler jobs.

## Codebase Map

```bash
/recurring_alert_bot
|-- PROJECT_RULES.md             # Global constraints, invariants, docstring policy, dev workflow.
|-- mainbot.py                     # Bot bootstrap, handler registration, auth guard, scheduler wiring, locks.
|-- startbot.sh                    # Launcher loop, venv bootstrap, DNS preflight, cleanup flags, respawn behavior.
|-- pythonrequirements.txt         # Runtime and debugger dependencies.
|
|-- modules/                       # Production Python package.
|   |-- constants.py               # Conversation states, callback constants, scheduler/security limits.
|   |-- storage.py                 # StorageManager facade: JSON IO, migrations, snapshots, user logs, media paths.
|   |-- storage_core/              # Storage services for alerts, birthdays, tags, prefs, scheduler state, postpone queues.
|   |-- scheduler.py               # Public scheduler facade used by bootstrap.
|   |-- scheduler_core/            # Scheduler lifecycle, tick orchestration, alert actions, missed recovery, postpone state.
|   |-- scheduler_mathlogic.py     # Recurrence, pre-alert, snooze, and next-occurrence math.
|   |-- scheduler_messagelogic.py  # Compatibility bridge; active rendering lives under modules/ui/.
|   |-- repetition_utils.py        # Repetition normalization, validation, and formatting helpers.
|   |-- telegram_resilience.py     # Telegram retry/fallback wrappers and degraded-state tracking.
|   |-- systemlog.py               # System logging, runtime-state persistence, rotation, retention.
|   |-- tags_logic.py              # Tag parsing, validation, normalization, and stats helpers.
|   |-- timezone_*.py              # Timezone conversion, catalog suggestions, and location lookup.
|   |-- birthday_utils.py          # Birthday age/date helpers, including leap-day handling.
|   |-- ghost_utils.py             # Ghost reminder helper utilities for missed-alert follow-up flows.
|   |-- zodiac.py                  # Western and Eastern zodiac computations.
|   |-- shared/                    # Cross-cutting helpers: codec, markdown, paths, runtime context, logging, status, cleanup.
|   |-- security/                  # Authorization, roles, whitelist persistence, request/invite notifications.
|   |-- backup_core/               # Backup/export/import services, archive safety, manifests, retention, restore.
|   |-- ui/                        # Notification/detail text formatters, keyboards, send utilities.
|   `-- handlers/                  # Telegram command/callback/conversation handlers.
|       |-- base/                  # /start, /help, /status, /settings, /cancel, timezone/mail/backup settings.
|       |-- add_flow/              # Alert creation wizard from type selection through save/cancel.
|       |-- edit_flow/             # Alert edit dashboard, origin handling, commit planning, add-flow delegates.
|       |-- list_alerts/           # Alert list filters, compact pagination, detail rendering, manage actions.
|       |-- birthday_flow/         # Birthday add/edit/list/search, bulk import/export, message suggestions.
|       |-- admin/                 # Admin request, invite, and user-management callbacks.
|       |-- backup_manage.py       # /manage -> Backups navigation, user aliases, system backup actions.
|       |-- manage.py              # Unified elevated /manage dashboard and dispatcher.
|       |-- developer.py           # Developer role management and acting-as controls.
|       |-- scheduler_handlers.py  # Fired-alert notification callbacks.
|       |-- ghost_flow.py          # Missed-summary ghost picker and dedup callback handlers.
|       |-- notification_*.py      # Notification action validation, context derivation, presenter helpers.
|       |-- shortcut_router.py     # Dynamic command shortcuts such as numeric backup/list aliases.
|       `-- tags_dashboard.py      # /tags dashboard and tag callbacks.
|
|-- docs/
|   |-- coding/                    # Workflow prompts, feature artifacts, workflow logs.
|   `-- truth/                     # Authoritative truthfiles and generated symbol indexes.
|
|-- tests/
|   |-- master_debugger.py         # Offline master validation runner.
|   `-- debuggers/                 # Focused suites by domain: alerts, birthdays, core.
|
|-- scripts/gen_info_functions.py  # Regenerates function/handler/mainbot indexes.
|-- ops/                           # Local maintenance scripts.
|-- data/                          # Default runtime data root; override with BOT_DATA_DIR.
`-- backups/                       # Default backup root; override with BOT_BACKUP_DIR.
```

Use `docs/truth/info_handlers.md` before adding or renaming handlers. Use `docs/truth/info_functions.md` before adding helpers. Use `docs/truth/info_mainbotfunctions.md` before editing bootstrap symbols.

## Canonical Runtime Paths

Path constants live in `modules/shared/paths.py`.

| Root | Default | Notes |
|---|---|---|
| `PROJECT_ROOT` | repo root | Derived from `modules/shared/paths.py`. |
| `DATA_DIR` | `data/` | Override with `BOT_DATA_DIR`. |
| `BACKUP_DIR` | `backups/` | Override with `BOT_BACKUP_DIR`. |
| `SYSTEM_LOG_DIR` | `data/systemlog.d/` | System logs, runtime state, local lock files. |
| `USER_LOG_DIR` | `data/userlog.d/` | Canonical per-user JSONL event logs. |
| `SYSTEM_DATA_DIR` | `data/system/` | Whitelist storage, whitelist requests, invite state, and system runtime JSON. |
| `WHITELIST_PATH` | `data/system/whitelist.json` | Canonical persisted whitelist source. |
| `USER_BACKUP_DIR` | `backups/users/` | Per-user backup/export artifacts. |
| System backup root | `backups/system/` | Returned by `modules.backup_core.paths.get_system_backup_dir()`. |
| Token-global lock root | `/tmp/recurring_alert_bot_locks` | Override with `BOT_GLOBAL_LOCK_DIR`. |

Per-user persistent state is under `data/<user_id>/`:

- `alerts.json`: canonical user DB for alerts, birthdays, tags, preferences, and metadata.
- `alerts.json.bak`: storage backup snapshot.
- `images/`: user media storage; stored media paths are user-relative.

All user DB writes go through `modules/storage.py`; see `PROJECT_RULES.md` for the hard atomic-write contract.

## Runtime Wiring Summary

Bootstrap and handler registration are in `mainbot.py`.

Startup flow:

- required environment is validated before singleton lock acquisition;
- local lock path is `data/systemlog.d/mainbot.lock`;
- token-global lock path is built under `BOT_GLOBAL_LOCK_DIR` using the bot token hash;
- `ApplicationBuilder(...).post_init(post_init).post_shutdown(post_shutdown)` builds the app;
- `BotRuntime(storage, api_failure_tracker)` is installed in `app.bot_data`;
- `scheduler.init_scheduler(app, storage)` runs before polling;
- `post_init` installs API wrappers, command menus, scheduler jobs, and startup diagnostics;
- `post_shutdown` stops scheduler and releases locks; final cleanup also records runtime shutdown metadata.

Handler priority groups, high to low:

- `-4`: activity touch/update handler.
- `-3`: authorization guard for callbacks and messages.
- `-2`: callback press logging with `block=False`.
- `-1`: location input, document upload, global text handler, dynamic command shortcuts.
- default group: conversation handlers, specific callback handlers, generic management callbacks, commands.

Callback routing is specific-first. Generic management patterns (`mgmt_`, `admin_`, `developer_`, `manage_`) are registered after more specific list/menu/settings callbacks. Commands include `/start`, `/manage`, `/alerts`, `/help`, `/status`, `/settings`, `/cancel`, `/birthdays`, and `/tags`.

## Truthfile Routing

| If touching... | Load / inspect... |
|---|---|
| Global hard constraints, callback limits, storage/logging/Markdown/time invariants, docstring policy | `PROJECT_RULES.md` |
| Workflow artifact mechanics, plan/checklist cadence, deferred queue, logging format | `docs/coding/AIprompt__workflow_invariants.md` |
| Alert type behavior, recurrence inputs, Daily/Birthday common rules | `docs/truth/bot_alert_types.md` |
| Scheduler math or notification runtime details | Relevant source in `modules/scheduler*.py`, `modules/scheduler_core/`, `modules/ui/`, plus alert/birthday debuggers. |
| Logging events, privacy policy, telemetry payloads | `docs/truth/policy_log.md` |
| Backup/archive/import/export/restore policy | `docs/truth/policy_backup.md` |
| Debugger structure or adding/updating debugger suites | `docs/truth/DEBUG_SUITE_DESIGN.md` |
| Existing public helpers/core functions | `docs/truth/info_functions.md` |
| Existing handlers/callbacks/flow steps | `docs/truth/info_handlers.md` |
| `mainbot.py` public symbols and bootstrap helpers | `docs/truth/info_mainbotfunctions.md` |
| Exact current code ownership | `rg --files`, focused source reads, and generated indexes. |

## Validation Commands

- Start bot: `bash startbot.sh`
- Run all offline checks: `venv/bin/python3 tests/master_debugger.py --offline`
- Regenerate generated truth indexes after public symbol/docstring changes: `python3 scripts/gen_info_functions.py`
