# Mainbot Public Symbol Index

> **Location:** `docs/truth/info_mainbotfunctions.md`  
> **Auto-generated** by `scripts/gen_info_functions.py` — do not edit by hand.  
> Re-run whenever public functions are added, renamed, or removed:
> `python3 scripts/gen_info_functions.py`

Fields per entry: `name | parent | inputs | output | description`

## `mainbot.py`
- `acquire_single_instance_lock` | `mainbot` | `token` | — | Ensure only one mainbot process runs at once per worktree and per token.
- `release_single_instance_lock` | `mainbot` | — | — | Release both global and local process locks for this bot instance.
- `post_init` | `mainbot` | `application` | — | Setup that runs after the bot has started.
- `touch_activity_handler` | `mainbot` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Pre-processing handler that updates last_seen for every whitelisted user interaction.
- `log_callback_press` | `mainbot` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Log callback metadata and clear pending free-text search modes when needed.
- `error_handler` | `mainbot` | `update: object`, `context: ContextTypes.DEFAULT_TYPE` | — | Log unhandled exceptions and route polling network errors through rollup handling.
- `post_shutdown` | `mainbot` | `application` | — | Stop scheduler services and release process locks during shutdown.
- `global_text_handler` | `mainbot` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Handles text input for multiple features:
- `authorization_guard` | `mainbot` | `update: Update`, `context: ContextTypes.DEFAULT_TYPE` | — | Fail-closed authorization guard for all inbound user updates.
