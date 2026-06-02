"""
callbacks.py — Callback payload builders for notification and detail keyboards.

Functions moved and renamed (leading underscore dropped) from
scheduler_messagelogic.py.  Vestigial builders that are no longer used in
new keyboards are intentionally omitted:
  - _build_placebo_done_callback  — NOTED for regular alerts keeps pdone_ prefix
    unchanged; only the button label changes, no new builder needed.
  - _build_prealert_edittext_callback / _build_alert_edittext_callback  — the
    edit-text flow is replaced by the full-edit flow (manage_fulledit_).
"""

from modules import constants as C
from modules.handlers.birthday_flow.message_suggestions.callbacks import (
    build_bday_noted_callback as _build_bday_noted_callback_token,
)


def ts(dt) -> str:
    """Return seconds-since-epoch string for use in callback payloads."""
    if not dt:
        return "0"
    return str(int(dt.timestamp()))


def build_postpone_callback(action, kind, alert_id, original_time, occurrence_time, postpone_count=0) -> str:
    """Return a postpone callback payload string for the given action, kind, and alert context."""
    orig_ts = ts(original_time)
    occ_ts = ts(occurrence_time or original_time)
    base = f"{C.CB_POSTPONE}{action}_{kind}_{alert_id}_{orig_ts}_{occ_ts}"
    if postpone_count and postpone_count > 0:
        return f"{base}_{postpone_count}"
    return base


def build_prealert_info_callback(alert_id, original_time, occurrence_time, postpone_count=0) -> str:
    """Return a pre-alert info callback payload that opens the detail card from a pre-alert notification."""
    orig_ts = ts(original_time)
    occ_ts = ts(occurrence_time or original_time)
    base = f"{C.CB_PREALERT_INFO}{alert_id}_{orig_ts}_{occ_ts}"
    if postpone_count and postpone_count > 0:
        return f"{base}_{postpone_count}"
    return base


def build_alert_info_callback(alert_id, original_time, occurrence_time, postpone_count=0) -> str:
    """Return an alert info callback payload that opens the detail card from an alert notification."""
    orig_ts = ts(original_time)
    occ_ts = ts(occurrence_time or original_time)
    base = f"{C.CB_ALERT_INFO}{alert_id}_{orig_ts}_{occ_ts}"
    if postpone_count and postpone_count > 0:
        return f"{base}_{postpone_count}"
    return base


def build_placebo_noted_callback(alert_id, original_time, occurrence_time) -> str:
    """Return a pre-alert NOTED callback payload using the pnote_ prefix."""
    orig_ts = ts(original_time)
    occ_ts = ts(occurrence_time or original_time)
    return f"{C.CB_PLACEBO_NOTED}{alert_id}_{orig_ts}_{occ_ts}"


def build_bday_noted_callback(alert_id, original_time, occurrence_time) -> str:
    """Return a birthday NOTED callback payload; delegates to the birthday message suggestion callbacks module."""
    return _build_bday_noted_callback_token(alert_id, original_time, occurrence_time)


def build_notif_back_callback(kind: str, alert_id: str, original_time, occurrence_time, postpone_count: int = 0) -> str:
    """Return a 'back to notification' callback for detail views opened from a notification.

    Format: nback_{kind}_{alert_id}_{orig_ts}_{occ_ts}[_{count}].
    original_time is the main alert fire time; occurrence_time is the pre-alert
    fire time (kind='pre') or the alert occurrence time (kind='due').
    Uses CB_NOTIF_BACK prefix from constants.
    """
    orig_ts = ts(original_time)
    occ_ts = ts(occurrence_time or original_time)
    base = f"{C.CB_NOTIF_BACK}{kind}_{alert_id}_{orig_ts}_{occ_ts}"
    if postpone_count and postpone_count > 0:
        return f"{base}_{postpone_count}"
    return base
