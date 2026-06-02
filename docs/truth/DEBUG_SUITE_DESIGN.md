# Debug Suite Design

## Goal
- Keep one command for full checks: `python3 tests/master_debugger.py`.
- Keep each debugger focused on one area to reduce coupling and simplify failures.
- Preserve fast terminal output and rich per-script log files for deep inspection.

## Folder Structure
- `tests/master_debugger.py`
  - Orchestrator only.
  - Discovers/runs debuggers, checks startup smoke, aggregates summary.
- `tests/debuggers/_lib/`
  - Shared harness/utilities only.
  - Must not contain executable entry scripts.
- `tests/debuggers/core/`
  - Cross-cutting runtime checks (logging, lifecycle, scheduler smoke compatibility).
- `tests/debuggers/alerts/`
  - Alert logic, pre-alert logic, postpone logic, storage behavior for alerts.
- `tests/debuggers/birthdays/`
  - Birthday flows and birthday search behavior.
- Per-feature internal check modules:
  - Large debuggers should split logic into sibling helper modules (for example, `<feature>_checks.py`).
  - Keep only thin executable entrypoints in `*_debug.py`.

## Scope Philosophy
- One debugger = one thematic responsibility.
- A debugger must not test unrelated features.
- If a debugger grows beyond one domain, split it.
- Keep deterministic checks first, then optional heavier checks.
- When splitting a debugger, preserve problem-code names and section labels to keep historical logs comparable.

## Dependency Rules
- Each debugger must resolve project root dynamically (do not assume fixed depth).
- Shared imports should prefer stable modules (`modules.*`) and avoid importing app boot code unless required.
- Avoid inter-debugger dependencies: no debugger should import another debugger.
- Dependency failures must be logged as `section=dependency_error` and exit non-zero.

## Logging Rules
- Child debugger logs are centralized under `tests/log/` as `tests/log/<script_name>.log`.
- Terminal output is compact summary only.
- Detailed diagnostics live in each debugger log.
- Master debugger writes `tests/log/master_debugger.log`.
- Startup smoke capture writes `tests/log/startbot_smoke.log`.
- Shared harness must preserve this behavior for all migrated debuggers.

## Naming Rules
- File names: `<feature>_debug.py`
- Summary title: short, stable, grep-friendly.
- Problem event names: snake_case and specific.
- Helper/internal modules under `tests/debuggers/` must NOT use `_debug.py` suffix.
- Shared utilities should be under `tests/debuggers/_lib/` with non-entry names.
- Entry scripts should stay orchestration-only (CLI parsing, dependency guard, harness/meta, summary).
- Heavy test logic should live in non-entry helper modules to keep entrypoints small and controllable.
- Debugger script basenames must stay unique across all domains because log files are flat in `tests/log/`.

## Execution Policy
- Master debugger runs all debuggers in quiet mode by default.
- Master debugger discovers children using `*_debug.py` only.
- Harness-migrated debuggers must treat unknown CLI args as a runtime problem (`cli_args_unknown`) instead of silently ignoring them.
- Master debugger records:
  - script return code
  - stderr/stdout lengths
  - whether script log contains `section=problem`
- Child stderr is strict by default:
  - every non-empty stderr line must match an allowlist rule
  - unmatched stderr line => suite failure
- Allowlist source: `tests/debuggers/stderr_allowlist.json`
  - rules are regex-based
  - rules are script-scoped via `script_glob`
  - malformed allowlist is a hard suite problem
- Startup smoke test remains part of master debugger.
- Master debugger forces `STARTBOT_DNS_WAIT_SECONDS=1` for the smoke run to avoid blocking startup.
- Warnings are strict by default (operational warning => suite failure).
- Optional downgrade for ad-hoc offline checks: `python3 tests/master_debugger.py --allow-warn`.
- Offline mode for network bootstrap noise only: `python3 tests/master_debugger.py --offline`
  or `MASTER_DEBUGGER_OFFLINE=1`. When startup hooks succeed, network bootstrap noise is logged as an informational note and keeps `network_bootstrap` at `OK`.

## Reliability Guards
- Per-script timeout is enforced to avoid suite hangs.
- Script logs are removed before each run to prevent stale pass/fail states.
- Master requires each child log to include `run_meta`, otherwise marks failure.
- Empty debugger discovery is treated as a hard problem.
- Stderr allowlist is evaluated line-by-line (not substring-any-match) to prevent false-green runs.
- Non-quiet child runs should print terminal summary only when problems are present; successful runs stay log-only.
- Any debugger that patches process globals/env (e.g., `sys.modules`, `asyncio` helpers, env vars) must restore original state before exit.
- If checks are split into helper modules, restoration of globals/env must still be owned by the entry script.
- Event-stream assertions should be order-agnostic unless ordering is an explicit contract.
- Telegram/framework imports used only for debug shims should be dependency-guarded (no top-level crash before `dependency_error` log).
- Debuggers must exit non-zero whenever any `section=problem` is recorded.

## Critical Review Targets
- **Conceptual problems to prevent**
  - Hung debugger blocks whole suite.
  - Stale log reused as if it were from current run.
  - Silent green run when no debuggers are actually discovered.
- **Fringe cases to include**
  - Child debugger exits non-zero and fails to emit a log file.
  - Child debugger emits dependency errors instead of `problem` records.
  - Startup smoke has temporary network noise but successful startup hooks.

## Growth Policy
- Add new debugger for each new feature family.
- Prefer adding checks to existing thematic debugger only if scope matches exactly.
- Keep backward compatibility for existing debug logs and summary format where possible.
