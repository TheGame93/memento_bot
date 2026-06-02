"""
telegram_resilience.py - retry/backoff + degraded-mode tracking for Telegram API calls.
"""

import asyncio
import random
import time
from collections import defaultdict, deque

try:
    from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut
except Exception:  # pragma: no cover - fallback for limited environments
    class BadRequest(Exception):
        pass

    class NetworkError(Exception):
        pass

    class TimedOut(Exception):
        pass

    class RetryAfter(Exception):
        retry_after = 0


def is_retryable_telegram_error(exc):
    """Classify Telegram exceptions that should be retried with backoff."""
    # Explicit guard: invalid Telegram payload/media errors are deterministic
    # and must not trigger retry storms.
    if isinstance(exc, BadRequest):
        return False
    return isinstance(exc, (TimedOut, NetworkError, RetryAfter))


def is_message_not_modified_error(exc):
    """Detect Telegram no-op edit failures that should be treated as benign."""
    if not isinstance(exc, BadRequest):
        return False
    message = str(exc or "").strip().lower()
    if not message:
        return False
    return "message is not modified" in message


def _retry_delay_seconds(exc, attempt_index, base_delay, max_delay):
    if isinstance(exc, RetryAfter):
        retry_after = getattr(exc, "retry_after", None)
        if retry_after is not None:
            try:
                return min(max_delay, max(0.0, float(retry_after)))
            except Exception:
                pass
    # Exponential backoff + jitter
    delay = min(max_delay, base_delay * (2 ** (attempt_index - 1)))
    jitter = random.uniform(0.0, max(0.05, delay * 0.2))
    return delay + jitter


class ApiFailureTracker:
    """
    Sliding-window tracker for API failures, with per-user + global degraded flags.
    """
    def __init__(self, window_seconds, user_threshold, global_threshold):
        self.window_seconds = int(window_seconds)
        self.user_threshold = int(user_threshold)
        self.global_threshold = int(global_threshold)
        self._global_failures = deque()
        self._user_failures = defaultdict(deque)
        self._global_degraded = False
        self._user_degraded = {}

    def _prune(self, now_mono):
        cutoff = now_mono - self.window_seconds
        while self._global_failures and self._global_failures[0] < cutoff:
            self._global_failures.popleft()

        stale_users = []
        for chat_id, failures in self._user_failures.items():
            while failures and failures[0] < cutoff:
                failures.popleft()
            if not failures:
                stale_users.append(chat_id)

        for chat_id in stale_users:
            self._user_failures.pop(chat_id, None)
            self._user_degraded.pop(chat_id, None)

    def _build_snapshot(self, chat_id):
        user_count = len(self._user_failures.get(chat_id, ())) if chat_id is not None else 0
        global_count = len(self._global_failures)

        user_degraded = user_count >= self.user_threshold if chat_id is not None else False
        global_degraded = global_count >= self.global_threshold

        prev_user_degraded = self._user_degraded.get(chat_id, False) if chat_id is not None else False
        prev_global_degraded = self._global_degraded

        if chat_id is not None:
            self._user_degraded[chat_id] = user_degraded
        self._global_degraded = global_degraded

        return {
            "chat_id": str(chat_id) if chat_id is not None else None,
            "window_seconds": self.window_seconds,
            "user_failures": user_count,
            "global_failures": global_count,
            "user_degraded": user_degraded,
            "global_degraded": global_degraded,
            "user_transition": (
                "on" if (chat_id is not None and not prev_user_degraded and user_degraded)
                else "off" if (chat_id is not None and prev_user_degraded and not user_degraded)
                else None
            ),
            "global_transition": (
                "on" if (not prev_global_degraded and global_degraded)
                else "off" if (prev_global_degraded and not global_degraded)
                else None
            ),
        }

    def record_failure(self, chat_id):
        """Record one API-health failure and return degraded-state snapshot metadata.

        The returned snapshot includes per-user/global failure counts, degraded
        booleans, and transition flags (`on`/`off`) for lifecycle telemetry.
        """
        now_mono = time.monotonic()
        self._global_failures.append(now_mono)
        if chat_id is not None:
            self._user_failures[chat_id].append(now_mono)
        self._prune(now_mono)
        return self._build_snapshot(chat_id)

    def record_success(self, chat_id):
        """Prune stale failures after a success and return current degraded snapshot.

        The returned snapshot includes per-user/global counts, degraded flags,
        and transition markers relative to the previous tracker state.
        """
        now_mono = time.monotonic()
        self._prune(now_mono)
        return self._build_snapshot(chat_id)

    def snapshot(self, chat_id):
        """Return current degraded-state snapshot without recording a new failure.

        The snapshot exposes user/global failure counters, degraded booleans,
        and transition flags for downstream status and lifecycle reporting.
        """
        now_mono = time.monotonic()
        self._prune(now_mono)
        return self._build_snapshot(chat_id)


async def run_with_retry(
    operation,
    chat_id,
    call_coro_factory,
    log_callback,
    tracker,
    attempts,
    max_window_seconds,
    base_delay_seconds,
    max_delay_seconds,
):
    """
    Runs a Telegram API call with bounded retry for retryable network/timeout errors.
    """
    attempts = max(1, int(attempts))
    started = time.monotonic()
    last_exc = None

    for attempt in range(1, attempts + 1):
        try:
            result = await call_coro_factory()
            if tracker:
                tracker.record_success(chat_id)
            return result
        except Exception as exc:
            last_exc = exc
            retryable = is_retryable_telegram_error(exc)
            # Scope no-op semantics to edit_message_text only.
            # Other API methods keep normal BadRequest failure classification.
            is_noop_not_modified = (
                operation == "edit_message_text"
                and is_message_not_modified_error(exc)
            )
            counts_toward_degraded = retryable and (not is_noop_not_modified)
            if tracker:
                snapshot = (
                    tracker.record_success(chat_id)
                    if is_noop_not_modified
                    else tracker.record_failure(chat_id)
                    if counts_toward_degraded
                    else tracker.snapshot(chat_id)
                )
            else:
                snapshot = {}

            if log_callback:
                event_name = "telegram_call_attempt_noop" if is_noop_not_modified else "telegram_call_attempt_failed"
                reason_code = "message_not_modified" if is_noop_not_modified else None
                level = "INFO" if is_noop_not_modified else ("WARNING" if retryable else "ERROR")
                payload = {
                    "operation": operation,
                    "chat_id": str(chat_id) if chat_id is not None else None,
                    "attempt": attempt,
                    "attempts": attempts,
                    "retryable": retryable,
                    "counts_toward_degraded": counts_toward_degraded,
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                    "degraded": snapshot,
                }
                if reason_code:
                    payload["reason_code"] = reason_code
                log_callback("api", event_name, payload, level=level)

                if (
                    counts_toward_degraded
                    and (snapshot.get("user_transition") == "on" or snapshot.get("global_transition") == "on")
                ):
                    log_callback("lifecycle", "api_degraded_mode_on", {
                        "operation": operation,
                        "chat_id": str(chat_id) if chat_id is not None else None,
                        "degraded": snapshot,
                    }, level="WARNING")
                if (
                    counts_toward_degraded
                    and (snapshot.get("user_transition") == "off" or snapshot.get("global_transition") == "off")
                ):
                    log_callback("lifecycle", "api_degraded_mode_off", {
                        "operation": operation,
                        "chat_id": str(chat_id) if chat_id is not None else None,
                        "degraded": snapshot,
                    })

            if not retryable:
                break
            if attempt >= attempts:
                break

            elapsed = time.monotonic() - started
            remaining = max(0.0, float(max_window_seconds) - elapsed)
            if remaining <= 0:
                break

            delay = _retry_delay_seconds(exc, attempt, float(base_delay_seconds), float(max_delay_seconds))
            delay = max(0.0, min(delay, remaining))
            if delay <= 0:
                break

            if log_callback:
                log_callback("api", "telegram_retry_scheduled", {
                    "operation": operation,
                    "chat_id": str(chat_id) if chat_id is not None else None,
                    "attempt": attempt,
                    "sleep_seconds": round(delay, 3),
                    "remaining_window_seconds": round(remaining, 3),
                    "error_type": exc.__class__.__name__,
                })

            await asyncio.sleep(delay)

    raise last_exc
