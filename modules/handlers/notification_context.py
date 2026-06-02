"""Parse notification callbacks and derive notification-detail context metadata."""

import re
from dataclasses import dataclass
from datetime import datetime

from modules import constants as C
from modules.handlers.birthday_flow.message_suggestions.callbacks import (
    decode_bday_noted_callback,
)


def _parse_ts(raw_ts):
    try:
        return datetime.fromtimestamp(int(raw_ts))
    except Exception:
        return None


def _parse_iso(raw_text):
    try:
        return datetime.fromisoformat(raw_text) if raw_text else None
    except Exception:
        return None


def _parse_postpone_data(data):
    # Expected formats (with optional trailing postpone count):
    # pp_menu_{kind}_{alert_id}_{orig_ts}_{occ_ts}[_{count}]
    # pp_set_{duration}_{kind}_{alert_id}_{orig_ts}_{occ_ts}[_{count}]
    # pp_custom_{kind}_{alert_id}_{orig_ts}_{occ_ts}[_{count}]
    parts = data.split("_")
    if len(parts) < 6:
        return None

    action = parts[1]
    if action == "set":
        if len(parts) < 7:
            return None
        duration = parts[2]
        kind = parts[3]
        alert_id = parts[4]
        orig_ts = parts[5]
        occ_ts = parts[6]
        count_str = parts[7] if len(parts) > 7 else "0"
    else:
        duration = None
        kind = parts[2]
        alert_id = parts[3]
        orig_ts = parts[4]
        occ_ts = parts[5]
        count_str = parts[6] if len(parts) > 6 else "0"

    try:
        postpone_count = int(count_str)
        if postpone_count < 0:
            postpone_count = 0
    except (ValueError, TypeError):
        postpone_count = 0

    return {
        "action": action,
        "duration": duration,
        "kind": kind,
        "alert_id": alert_id,
        "original_time": _parse_ts(orig_ts),
        "occurrence_time": _parse_ts(occ_ts),
        "postpone_count": postpone_count,
    }


def _parse_prealert_info_data(data):
    # Expected format:
    # preinfo_{alert_id}_{orig_ts}_{occ_ts}[_{count}]
    parts = data.split("_")
    if len(parts) < 4:
        return None
    alert_id = parts[1]
    orig_ts = parts[2]
    occ_ts = parts[3]
    count_str = parts[4] if len(parts) > 4 else "0"
    try:
        postpone_count = int(count_str)
        if postpone_count < 0:
            postpone_count = 0
    except (ValueError, TypeError):
        postpone_count = 0
    return {
        "alert_id": alert_id,
        "original_time": _parse_ts(orig_ts),
        "occurrence_time": _parse_ts(occ_ts),
        "postpone_count": postpone_count,
    }


def _parse_alert_info_data(data):
    # Expected format:
    # ainfo_{alert_id}_{orig_ts}_{occ_ts}[_{count}]
    parts = data.split("_")
    if len(parts) < 4:
        return None
    alert_id = parts[1]
    orig_ts = parts[2]
    occ_ts = parts[3]
    count_str = parts[4] if len(parts) > 4 else "0"
    try:
        postpone_count = int(count_str)
        if postpone_count < 0:
            postpone_count = 0
    except (ValueError, TypeError):
        postpone_count = 0
    return {
        "alert_id": alert_id,
        "original_time": _parse_ts(orig_ts),
        "occurrence_time": _parse_ts(occ_ts),
        "postpone_count": postpone_count,
    }


def _parse_notif_back_data(data):
    # Expected format:
    # nback_{kind}_{alert_id}_{orig_ts}_{occ_ts}[_{count}]
    if not isinstance(data, str) or not data.startswith(C.CB_NOTIF_BACK):
        return None

    tail = data[len(C.CB_NOTIF_BACK):]
    kind, sep, payload = tail.partition("_")
    if sep != "_" or kind not in {"pre", "due"}:
        return None

    parsed = _parse_alert_callback_tail(payload)
    if not parsed:
        return None

    parsed["kind"] = kind
    return parsed


def _iter_message_callbacks(message):
    markup = getattr(message, "reply_markup", None)
    if not markup or not getattr(markup, "inline_keyboard", None):
        return
    for row in markup.inline_keyboard:
        for btn in row:
            callback_data = getattr(btn, "callback_data", None)
            if isinstance(callback_data, str) and callback_data:
                yield callback_data


def _extract_back_tag_filter(message):
    markup = getattr(message, "reply_markup", None)
    if not markup or not getattr(markup, "inline_keyboard", None):
        return "ALL"
    for row in markup.inline_keyboard:
        for btn in row:
            if getattr(btn, "callback_data", None) != "manage_backtolist":
                continue
            label = getattr(btn, "text", "") or ""
            match = re.match(r"^⬅️ Back \((.+)\)$", label)
            if match:
                return match.group(1)
            return "ALL"
    return "ALL"


def _parse_alert_callback_tail(payload):
    if not isinstance(payload, str) or not payload:
        return None
    parts = payload.split("_")
    if len(parts) < 3:
        return None

    def _looks_like_ts_token(raw):
        if not isinstance(raw, str):
            return False
        if raw == "0":
            return True
        return raw.isdigit() and len(raw) >= 9

    # Parse no-count shape first:
    # {alert_id}_{orig_ts}_{occ_ts}
    # This avoids mis-parsing IDs that end with numeric underscore segments
    # (e.g., foo_123_171..._171...) as if the last timestamp were a count.
    alert_id_no_count = "_".join(parts[:-2])
    if (
        alert_id_no_count
        and _looks_like_ts_token(parts[-2])
        and _looks_like_ts_token(parts[-1])
    ):
        return {
            "alert_id": alert_id_no_count,
            "original_time": _parse_ts(parts[-2]),
            "occurrence_time": _parse_ts(parts[-1]),
            "postpone_count": 0,
        }

    # Optional count shape:
    # {alert_id}_{orig_ts}_{occ_ts}_{count}
    if len(parts) >= 4:
        alert_id_with_count = "_".join(parts[:-3])
        if (
            alert_id_with_count
            and _looks_like_ts_token(parts[-3])
            and _looks_like_ts_token(parts[-2])
        ):
            try:
                parsed_count = int(parts[-1])
            except (TypeError, ValueError):
                parsed_count = None
            if parsed_count is not None:
                postpone_count = parsed_count if parsed_count >= 0 else 0
                return {
                    "alert_id": alert_id_with_count,
                    "original_time": _parse_ts(parts[-3]),
                    "occurrence_time": _parse_ts(parts[-2]),
                    "postpone_count": postpone_count,
                }

    return None


def _parse_alert_callback_with_prefix(callback_data, prefix):
    if not isinstance(callback_data, str) or not callback_data.startswith(prefix):
        return None
    tail = callback_data[len(prefix):]
    return _parse_alert_callback_tail(tail)


def _derive_detail_origin_context(message, alert_id):
    """Derive detail-view origin and timing context for a target alert from inline callbacks."""
    context = {
        "kind": "due",
        "detail_from_notification": False,
        "detail_from_list": False,
        "include_back": False,
        "original_time": None,
        "occurrence_time": None,
        "postpone_count": 0,
    }
    target_id = str(alert_id or "")
    if not target_id:
        return context

    has_nback = False
    has_manage_fulledit = False
    has_legacy_detail = False

    for callback_data in _iter_message_callbacks(message):
        parsed = None
        matched = False

        if callback_data == "manage_backtolist":
            context["include_back"] = True
            continue

        if callback_data.startswith("manage_fulledit_"):
            payload_id = callback_data.replace("manage_fulledit_", "", 1)
            if payload_id == target_id:
                has_manage_fulledit = True
            continue

        if callback_data.startswith(C.CB_NOTIF_BACK):
            parsed = _parse_notif_back_data(callback_data)
            if parsed and str(parsed.get("alert_id")) == target_id:
                context["kind"] = parsed.get("kind") or context["kind"]
                has_nback = True
                matched = True
        elif callback_data.startswith("manage_edittext_pre_"):
            parsed = _parse_alert_callback_with_prefix(callback_data, "manage_edittext_pre_")
            if parsed and str(parsed.get("alert_id")) == target_id:
                context["kind"] = "pre"
                has_legacy_detail = True
                matched = True
        elif callback_data.startswith("manage_edittext_due_"):
            parsed = _parse_alert_callback_with_prefix(callback_data, "manage_edittext_due_")
            if parsed and str(parsed.get("alert_id")) == target_id:
                context["kind"] = "due"
                has_legacy_detail = True
                matched = True
        elif callback_data.startswith(C.CB_PREALERT_INFO):
            parsed = _parse_alert_callback_with_prefix(callback_data, C.CB_PREALERT_INFO)
            if parsed and str(parsed.get("alert_id")) == target_id:
                context["kind"] = "pre"
                matched = True
        elif callback_data.startswith(C.CB_ALERT_INFO):
            parsed = _parse_alert_callback_with_prefix(callback_data, C.CB_ALERT_INFO)
            if parsed and str(parsed.get("alert_id")) == target_id:
                context["kind"] = "due"
                matched = True
        elif callback_data.startswith(C.CB_PLACEBO_NOTED):
            parsed = _parse_alert_callback_with_prefix(callback_data, C.CB_PLACEBO_NOTED)
            if parsed and str(parsed.get("alert_id")) == target_id:
                context["kind"] = "pre"
                matched = True
        elif callback_data.startswith(C.CB_PLACEBO_DONE):
            parsed = _parse_alert_callback_with_prefix(callback_data, C.CB_PLACEBO_DONE)
            if parsed and str(parsed.get("alert_id")) == target_id:
                context["kind"] = "due"
                matched = True
        elif callback_data.startswith(C.CB_BDAY_NOTED):
            parsed_bday = decode_bday_noted_callback(callback_data)
            if parsed_bday.get("ok") and str(parsed_bday.get("alert_id")) == target_id:
                parsed = {
                    "alert_id": parsed_bday.get("alert_id"),
                    "original_time": parsed_bday.get("original_time"),
                    "occurrence_time": parsed_bday.get("occurrence_time"),
                    "postpone_count": 0,
                }
                context["kind"] = "due"
                matched = True
        elif callback_data.startswith(C.CB_POSTPONE):
            parsed_postpone = _parse_postpone_data(callback_data)
            if parsed_postpone and str(parsed_postpone.get("alert_id")) == target_id:
                context["kind"] = parsed_postpone.get("kind") or context["kind"]
                parsed = {
                    "alert_id": target_id,
                    "original_time": parsed_postpone.get("original_time"),
                    "occurrence_time": parsed_postpone.get("occurrence_time"),
                    "postpone_count": parsed_postpone.get("postpone_count", 0),
                }
                matched = True

        if not matched or not parsed:
            continue

        if parsed.get("original_time") is not None:
            context["original_time"] = parsed.get("original_time")
        if parsed.get("occurrence_time") is not None:
            context["occurrence_time"] = parsed.get("occurrence_time")
        try:
            count = int(parsed.get("postpone_count") or 0)
        except (TypeError, ValueError):
            count = 0
        if count > context["postpone_count"]:
            context["postpone_count"] = count

    if has_nback or has_legacy_detail:
        context["detail_from_notification"] = True
    elif has_manage_fulledit:
        context["detail_from_list"] = True

    return context


def _derive_toggle_keyboard_context(message, alert_id):
    """Build toggle-refresh context from the current detail or notification message keyboard."""
    return _derive_detail_origin_context(message, alert_id)


@dataclass
class NotificationContext:
    """Store notification-origin metadata derived from inline callback payloads."""

    kind: str = "due"
    detail_from_notification: bool = False
    detail_from_list: bool = False
    include_back: bool = False
    original_time: datetime | None = None
    occurrence_time: datetime | None = None
    postpone_count: int = 0

    @classmethod
    def from_message(cls, message, alert_id: str) -> "NotificationContext":
        """Derive notification origin and timing context by inspecting inline keyboard callbacks."""
        result = _derive_detail_origin_context(message, str(alert_id or ""))
        return cls(**result)
