from __future__ import annotations

import json
import time
from collections import OrderedDict
from datetime import datetime
from typing import Any

from modules import constants as C
from modules.shared.callback_codec import (
    build_value_token_map,
    ensure_callback_fits,
    extract_callback_token,
    is_token_candidate,
)

_REGISTRY_MAX_SIZE = 4096
_REGISTRY_TTL_SECONDS = 7 * 24 * 60 * 60

_BNOTE_REGISTRY: OrderedDict[str, tuple[dict[str, Any], float]] = OrderedDict()
_BMSG_REGISTRY: OrderedDict[str, tuple[dict[str, Any], float]] = OrderedDict()


def _parse_ts(raw_ts: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(raw_ts))
    except Exception:
        return None


def _to_ts_value(dt: datetime | None) -> int | None:
    if dt is None:
        return None
    try:
        return int(dt.timestamp())
    except Exception:
        return None


def _prune_registry(registry: OrderedDict[str, tuple[dict[str, Any], float]]) -> None:
    now = time.time()
    expired = []
    for token, (_payload, created_ts) in registry.items():
        if now - created_ts > _REGISTRY_TTL_SECONDS:
            expired.append(token)
    for token in expired:
        registry.pop(token, None)

    while len(registry) > _REGISTRY_MAX_SIZE:
        registry.popitem(last=False)


def _register_payload(
    registry: OrderedDict[str, tuple[dict[str, Any], float]],
    payload: dict[str, Any],
) -> str:
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    token = next(iter(build_value_token_map([payload_json], min_len=10, max_len=16)))
    now = time.time()
    registry[token] = (payload, now)
    registry.move_to_end(token)
    _prune_registry(registry)
    return token


def _decode_from_registry(
    registry: OrderedDict[str, tuple[dict[str, Any], float]],
    token: str | None,
) -> dict[str, Any] | None:
    if not token or not is_token_candidate(token):
        return None
    item = registry.get(token)
    if item is None:
        return None
    payload, created_ts = item
    if time.time() - created_ts > _REGISTRY_TTL_SECONDS:
        registry.pop(token, None)
        return None
    registry.move_to_end(token)
    return dict(payload)


def build_bday_noted_callback(alert_id: str, original_time: datetime | None, occurrence_time: datetime | None) -> str:
    """Build a tokenized birthday-noted callback that preserves occurrence context."""
    payload = {
        "v": 1,
        "alert_id": str(alert_id or ""),
        "orig_ts": _to_ts_value(original_time),
        "occ_ts": _to_ts_value(occurrence_time or original_time),
    }
    token = _register_payload(_BNOTE_REGISTRY, payload)
    callback_data = f"{C.CB_BDAY_NOTED}{token}"
    if not ensure_callback_fits(callback_data):
        raise ValueError("callback_too_long")
    return callback_data


def decode_bday_noted_callback(callback_data: str) -> dict[str, Any]:
    """Decode birthday-noted callback payloads with codec-first and legacy fallback support.
    
    Return a normalized payload contract (`ok`, `alert_id`, occurrence/original times,
    and `source`) so handlers can preserve backward compatibility safely.
    """
    if not isinstance(callback_data, str) or not callback_data.startswith(C.CB_BDAY_NOTED):
        return {"ok": False, "reason_code": "callback_payload_invalid"}

    token = extract_callback_token(callback_data, C.CB_BDAY_NOTED)
    payload = _decode_from_registry(_BNOTE_REGISTRY, token)
    if payload is None:
        # Legacy fallback: bnote_{alert_id}_{orig_ts}_{occ_ts}
        tail = callback_data[len(C.CB_BDAY_NOTED):]
        if tail:
            alert_and_orig = tail.rsplit("_", 1)
            if len(alert_and_orig) == 2:
                left, occ_ts = alert_and_orig
                alert_and_ts = left.rsplit("_", 1)
                if len(alert_and_ts) == 2:
                    raw_alert_id, orig_ts = alert_and_ts
                    if raw_alert_id:
                        return {
                            "ok": True,
                            "alert_id": raw_alert_id,
                            "original_time": _parse_ts(orig_ts),
                            "occurrence_time": _parse_ts(occ_ts),
                            "source": "legacy",
                        }
        return {"ok": False, "reason_code": "callback_payload_invalid"}

    return {
        "ok": True,
        "alert_id": str(payload.get("alert_id") or ""),
        "original_time": _parse_ts(payload.get("orig_ts")),
        "occurrence_time": _parse_ts(payload.get("occ_ts")),
        "source": "codec",
    }


def build_bday_msg_callback(style: str, alert_id: str, occurrence_time: datetime | None) -> str:
    """Build a tokenized birthday-style callback that preserves occurrence context."""
    payload = {
        "v": 1,
        "style": str(style or ""),
        "alert_id": str(alert_id or ""),
        "occ_ts": _to_ts_value(occurrence_time),
    }
    token = _register_payload(_BMSG_REGISTRY, payload)
    callback_data = f"{C.CB_BDAY_MSG}{token}"
    if not ensure_callback_fits(callback_data):
        raise ValueError("callback_too_long")
    return callback_data


def decode_bday_msg_callback(callback_data: str) -> dict[str, Any]:
    """Decode birthday-style callback payloads with codec-first and legacy fallback support.
    
    Return a normalized payload contract (`ok`, `style`, `alert_id`, occurrence time,
    and `source`) for uniform downstream style handling.
    """
    if not isinstance(callback_data, str) or not callback_data.startswith(C.CB_BDAY_MSG):
        return {"ok": False, "reason_code": "callback_payload_invalid"}

    token = extract_callback_token(callback_data, C.CB_BDAY_MSG)
    payload = _decode_from_registry(_BMSG_REGISTRY, token)
    if payload is None:
        # Legacy fallback: bmsg_{style}_{alert_id}[_{occ_ts}]
        tail = callback_data[len(C.CB_BDAY_MSG):]
        style_and_rest = tail.split("_", 1)
        if len(style_and_rest) == 2 and style_and_rest[0]:
            style, rest = style_and_rest
            if rest:
                alert_and_occ = rest.rsplit("_", 1)
                if len(alert_and_occ) == 2 and alert_and_occ[1].isdigit():
                    alert_id, occ_ts = alert_and_occ
                else:
                    alert_id, occ_ts = rest, None
                if alert_id:
                    return {
                        "ok": True,
                        "style": style,
                        "alert_id": alert_id,
                        "occurrence_time": _parse_ts(occ_ts),
                        "source": "legacy",
                    }
        return {"ok": False, "reason_code": "callback_payload_invalid"}

    return {
        "ok": True,
        "style": str(payload.get("style") or ""),
        "alert_id": str(payload.get("alert_id") or ""),
        "occurrence_time": _parse_ts(payload.get("occ_ts")),
        "source": "codec",
    }
