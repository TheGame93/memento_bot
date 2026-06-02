#!/bin/bash

# Get the absolute path to the directory where THIS script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

LOG_DIR="$SCRIPT_DIR/data/systemlog.d"
LIFECYCLE_LOG="$LOG_DIR/lifecycle.log"
RESPAWN_DELAY_SECONDS="${STARTBOT_RESPAWN_DELAY_SECONDS:-60}"
LOCK_FILE="$LOG_DIR/startbot.lock"
CHILD_PID=""
TERMINATION_REQUESTED=0
CHILD_SHUTDOWN_TIMEOUT_SECONDS="${STARTBOT_CHILD_SHUTDOWN_TIMEOUT_SECONDS:-12}"
FLAG_HELP=0
FLAG_CLEAN=0
FLAG_NEW=0
FLAG_FORCE_START=0
CLI_PARSE_REASON=""
CLI_PARSE_ARG=""
MAINBOT_LOCK_CONFLICT_EXIT_CODE="${MAINBOT_LOCK_CONFLICT_EXIT_CODE:-73}"

log_lifecycle() {
    local event="$1"
    local payload="$2"
    local level="${3:-INFO}"
    python3 - "$event" "$level" "$payload" <<'PY'
import json
import sys

event = sys.argv[1]
level = sys.argv[2]
payload_raw = sys.argv[3]

try:
    payload = json.loads(payload_raw)
except Exception:
    payload = {"raw_payload": payload_raw}

try:
    from modules.systemlog import log_system
    log_system("lifecycle", event, payload, level=level)
except Exception:
    pass
PY
}

_json_escape() {
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    value="${value//$'\n'/\\n}"
    value="${value//$'\r'/\\r}"
    value="${value//$'\t'/\\t}"
    printf '%s' "$value"
}

print_usage() {
    cat <<'EOF'
Usage: ./startbot.sh [options]

Options:
  -h, --help         Show this help message and exit
  -c, --clean        Run ./ops/remove_tests_artifacts.sh before launching
  -n, --new          Run ./ops/remove_all_logfiles.sh before launching
      --force-start  Continue startup even if cleanup phase fails

Examples:
  ./startbot.sh
  ./startbot.sh -c
  ./startbot.sh -n
  ./startbot.sh -nc
  ./startbot.sh --clean --new
EOF
}

_set_cli_error() {
    CLI_PARSE_REASON="$1"
    CLI_PARSE_ARG="$2"
}

parse_args() {
    while [ "$#" -gt 0 ]; do
        local arg="$1"
        shift
        case "$arg" in
            --help)
                FLAG_HELP=1
                ;;
            --clean)
                FLAG_CLEAN=1
                ;;
            --new)
                FLAG_NEW=1
                ;;
            --force-start)
                FLAG_FORCE_START=1
                ;;
            --)
                if [ "$#" -gt 0 ]; then
                    _set_cli_error "unexpected_positional" "$1"
                    return 1
                fi
                break
                ;;
            -?*)
                local short_flags="${arg#-}"
                while [ -n "$short_flags" ]; do
                    local short_opt="${short_flags:0:1}"
                    short_flags="${short_flags:1}"
                    case "$short_opt" in
                        h)
                            FLAG_HELP=1
                            ;;
                        c)
                            FLAG_CLEAN=1
                            ;;
                        n)
                            FLAG_NEW=1
                            ;;
                        *)
                            _set_cli_error "unknown_option" "-$short_opt"
                            return 1
                            ;;
                    esac
                done
                ;;
            *)
                _set_cli_error "unexpected_positional" "$arg"
                return 1
                ;;
        esac
    done
    return 0
}

run_clean_all_logfiles() {
    log_lifecycle "startbot_cleanup_all_logs_started" '{"script":"ops/remove_all_logfiles.sh"}'
    bash ./ops/remove_all_logfiles.sh
    local rc=$?
    if [ "$rc" -ne 0 ]; then
        log_lifecycle "startbot_cleanup_all_logs_failed" "{\"script\":\"ops/remove_all_logfiles.sh\",\"exit_code\":$rc}" "WARNING"
        return "$rc"
    fi
    log_lifecycle "startbot_cleanup_all_logs_ok" '{"script":"ops/remove_all_logfiles.sh"}'
    return 0
}

run_clean_tests_artifacts() {
    log_lifecycle "startbot_cleanup_tests_artifacts_started" '{"script":"ops/remove_tests_artifacts.sh"}'
    bash ./ops/remove_tests_artifacts.sh
    local rc=$?
    if [ "$rc" -ne 0 ]; then
        log_lifecycle "startbot_cleanup_tests_artifacts_failed" "{\"script\":\"ops/remove_tests_artifacts.sh\",\"exit_code\":$rc}" "WARNING"
        return "$rc"
    fi
    log_lifecycle "startbot_cleanup_tests_artifacts_ok" '{"script":"ops/remove_tests_artifacts.sh"}'
    return 0
}

_handle_cleanup_failure() {
    local scope="$1"
    local rc="$2"
    if [ "$FLAG_FORCE_START" -eq 1 ]; then
        log_lifecycle "startbot_cleanup_phase_failed_continue" "{\"scope\":\"$scope\",\"exit_code\":$rc}" "WARNING"
        echo "Cleanup failed for $scope (exit $rc), continuing due to --force-start."
        return 0
    fi
    log_lifecycle "startbot_cleanup_phase_failed_abort" "{\"scope\":\"$scope\",\"exit_code\":$rc}" "WARNING"
    echo "Cleanup failed for $scope (exit $rc), aborting startup."
    return "$rc"
}

run_requested_cleanups() {
    log_lifecycle "startbot_cleanup_phase_started" "{\"clean\":$FLAG_CLEAN,\"new\":$FLAG_NEW,\"force_start\":$FLAG_FORCE_START}"

    local had_failure=0
    local rc=0

    if [ "$FLAG_NEW" -eq 1 ]; then
        run_clean_all_logfiles
        rc=$?
        if [ "$rc" -ne 0 ]; then
            had_failure=1
            _handle_cleanup_failure "all_logs" "$rc" || return "$rc"
        fi
    fi

    if [ "$FLAG_CLEAN" -eq 1 ]; then
        run_clean_tests_artifacts
        rc=$?
        if [ "$rc" -ne 0 ]; then
            had_failure=1
            _handle_cleanup_failure "tests_artifacts" "$rc" || return "$rc"
        fi
    fi

    log_lifecycle "startbot_cleanup_phase_completed" "{\"clean\":$FLAG_CLEAN,\"new\":$FLAG_NEW,\"had_failure\":$had_failure}"
    return 0
}

_is_int() {
    [[ "$1" =~ ^[0-9]+$ ]]
}

dns_wait() {
    local host="${STARTBOT_DNS_HOST:-api.telegram.org}"
    local timeout="${STARTBOT_DNS_WAIT_SECONDS:-15}"
    local interval="${STARTBOT_DNS_WAIT_INTERVAL:-1}"

    if ! command -v getent >/dev/null 2>&1; then
        log_lifecycle "startbot_dns_wait_skipped" "{\"host\":\"$host\",\"reason\":\"getent_missing\"}" "WARNING"
        return 0
    fi

    if ! _is_int "$timeout" || ! _is_int "$interval" || [ "$timeout" -le 0 ] || [ "$interval" -le 0 ]; then
        log_lifecycle "startbot_dns_wait_skipped" "{\"host\":\"$host\",\"reason\":\"invalid_config\",\"timeout\":\"$timeout\",\"interval\":\"$interval\"}" "WARNING"
        return 0
    fi

    local start_time=$SECONDS
    local deadline=$((SECONDS + timeout))
    while true; do
        if getent hosts "$host" >/dev/null 2>&1; then
            local waited=$((SECONDS - start_time))
            log_lifecycle "startbot_dns_wait_ok" "{\"host\":\"$host\",\"waited_seconds\":$waited,\"timeout_seconds\":$timeout,\"interval_seconds\":$interval}"
            return 0
        fi
        if [ "$SECONDS" -ge "$deadline" ]; then
            local waited=$((SECONDS - start_time))
            log_lifecycle "startbot_dns_wait_timeout" "{\"host\":\"$host\",\"waited_seconds\":$waited,\"timeout_seconds\":$timeout,\"interval_seconds\":$interval}" "WARNING"
            return 0
        fi
        sleep "$interval"
    done
}

resolve_mainbot_lock_conflict_exit_code() {
    local resolved=""
    if [ -n "$VENV_PYTHON" ] && [ -x "$VENV_PYTHON" ]; then
        resolved="$("$VENV_PYTHON" -c 'from modules import constants as C; print(getattr(C, "MAINBOT_EXIT_LOCK_CONFLICT", 73))' 2>/dev/null || true)"
    fi
    if _is_int "$resolved" && [ "$resolved" -ge 0 ]; then
        MAINBOT_LOCK_CONFLICT_EXIT_CODE="$resolved"
    fi
}

on_termination_signal() {
    local signal_name="$1"
    TERMINATION_REQUESTED=1
    log_lifecycle "startbot_script_terminated" "{\"signal\":\"$signal_name\",\"child_pid\":${CHILD_PID:-null}}" "WARNING"

    if [ -n "$CHILD_PID" ] && kill -0 "$CHILD_PID" 2>/dev/null; then
        # Forward signal to running child so mainbot can shutdown gracefully.
        kill -s "$signal_name" "$CHILD_PID" 2>/dev/null || kill -TERM "$CHILD_PID" 2>/dev/null || true
        log_lifecycle "startbot_signal_forwarded_to_child" "{\"signal\":\"$signal_name\",\"child_pid\":$CHILD_PID}"

        child_deadline=$((SECONDS + CHILD_SHUTDOWN_TIMEOUT_SECONDS))
        while kill -0 "$CHILD_PID" 2>/dev/null; do
            if [ "$SECONDS" -ge "$child_deadline" ]; then
                log_lifecycle "startbot_child_force_kill" "{\"child_pid\":$CHILD_PID,\"timeout_seconds\":$CHILD_SHUTDOWN_TIMEOUT_SECONDS}" "WARNING"
                kill -KILL "$CHILD_PID" 2>/dev/null || true
                break
            fi
            sleep 1
        done
    fi

    exit 0
}

trap 'on_termination_signal "SIGTERM"' TERM
trap 'on_termination_signal "SIGINT"' INT

mkdir -p "$LOG_DIR" 2>/dev/null || true

if ! parse_args "$@"; then
    case "$CLI_PARSE_REASON" in
        unknown_option)
            echo "Unknown option: $CLI_PARSE_ARG" >&2
            ;;
        unexpected_positional)
            echo "Unexpected positional argument: $CLI_PARSE_ARG" >&2
            ;;
        *)
            echo "Invalid CLI arguments." >&2
            ;;
    esac
    escaped_reason="$(_json_escape "$CLI_PARSE_REASON")"
    escaped_arg="$(_json_escape "$CLI_PARSE_ARG")"
    log_lifecycle "startbot_cli_invalid_args" "{\"reason\":\"$escaped_reason\",\"arg\":\"$escaped_arg\"}" "WARNING"
    print_usage >&2
    exit 2
fi

log_lifecycle "startbot_cli_flags" "{\"help\":$FLAG_HELP,\"clean\":$FLAG_CLEAN,\"new\":$FLAG_NEW,\"force_start\":$FLAG_FORCE_START}"

if [ "$FLAG_HELP" -eq 1 ]; then
    log_lifecycle "startbot_cli_help" '{"requested":true}'
    print_usage
    exit 0
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "Another startbot.sh instance is already running. Exiting."
    log_lifecycle "startbot_already_running" "{\"lock_file\":\"$LOCK_FILE\"}" "WARNING"
    exit 1
fi

if [ "$FLAG_NEW" -eq 1 ] || [ "$FLAG_CLEAN" -eq 1 ]; then
    run_requested_cleanups || exit $?
fi

# Define path to venv executables
VENV_PATH="$SCRIPT_DIR/venv"
VENV_PIP="$VENV_PATH/bin/pip"
VENV_PYTHON="$VENV_PATH/bin/python3"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        log_lifecycle "startbot_setup_error" '{"stage":"create_venv","reason":"venv_creation_failed"}' "ERROR"
        exit 1
    fi
fi

# Source the virtual environment using the local path
if [ -f "./venv/bin/activate" ]; then
    source ./venv/bin/activate
    echo "Virtual environment found in $SCRIPT_DIR/venv"
else
    echo "Error: Virtual environment not found in $SCRIPT_DIR/venv"
    log_lifecycle "startbot_setup_error" '{"stage":"activate_venv","reason":"venv_not_found"}' "ERROR"
    exit 1
fi

# Install/Update dependencies using the VENV's specific pip.
# Master smoke tests can skip this step to avoid network latency/failures.
if [ "${STARTBOT_SKIP_DEPS:-0}" != "1" ]; then
    $VENV_PIP install --upgrade pip
    if [ $? -ne 0 ]; then
        log_lifecycle "startbot_dependency_warning" '{"stage":"pip_upgrade","ok":false}' "WARNING"
    fi
    $VENV_PIP install -r pythonrequirements.txt
    if [ $? -ne 0 ]; then
        log_lifecycle "startbot_dependency_warning" '{"stage":"requirements_install","ok":false}' "WARNING"
    fi
else
    echo "Skipping dependency install (STARTBOT_SKIP_DEPS=1)"
fi

# Start the bot using the VENV's specific python
echo "Starting Alert Bot..."
resolve_mainbot_lock_conflict_exit_code
log_lifecycle "startbot_loop_started" "{\"respawn_delay_seconds\":$RESPAWN_DELAY_SECONDS,\"skip_deps\":${STARTBOT_SKIP_DEPS:-0},\"lock_conflict_exit_code\":$MAINBOT_LOCK_CONFLICT_EXIT_CODE}"

while true; do
    if [ "$TERMINATION_REQUESTED" -eq 1 ]; then
        log_lifecycle "startbot_exit_signal" "{\"reason\":\"termination_requested\"}" "WARNING"
        break
    fi

    dns_wait

    $VENV_PYTHON mainbot.py &
    CHILD_PID=$!
    wait "$CHILD_PID"
    exit_code=$?
    CHILD_PID=""

    if [ "$TERMINATION_REQUESTED" -eq 1 ]; then
        log_lifecycle "startbot_exit_signal" "{\"reason\":\"termination_requested\",\"exit_code\":$exit_code}" "WARNING"
        break
    fi

    if [ "$exit_code" -eq "$MAINBOT_LOCK_CONFLICT_EXIT_CODE" ]; then
        log_lifecycle "startbot_mainbot_lock_conflict_exit" "{\"exit_code\":$exit_code,\"lock_conflict_exit_code\":$MAINBOT_LOCK_CONFLICT_EXIT_CODE}" "WARNING"
        echo "Mainbot lock conflict detected (exit code $exit_code). Not respawning."
        break
    fi

    if [ $exit_code -eq 0 ]; then
        log_lifecycle "startbot_exit_clean" '{"exit_code":0}'
        break
    fi

    log_lifecycle "startbot_crash_respawn" "{\"exit_code\":$exit_code,\"respawn_delay_seconds\":$RESPAWN_DELAY_SECONDS}" "ERROR"
    echo "Bot crashed with exit code $exit_code. Respawning in $RESPAWN_DELAY_SECONDS seconds..."
    sleep "$RESPAWN_DELAY_SECONDS"
done
