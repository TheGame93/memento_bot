"""
send_utils.py — Unified alert-notification send pipeline.

Houses the scheduler-facing send utility and media fallback helpers used by
notification deliveries (pre-alert, main alert, missed alert).
"""

import logging
import os

from telegram.constants import ParseMode

try:
    from telegram.error import BadRequest
except Exception:  # pragma: no cover - fallback for limited environments
    class BadRequest(Exception):
        pass

from modules import constants as C
from modules.ghost_utils import is_ghost_alert
from modules.scheduler_mathlogic import resolve_pre_alert_fire_time
from modules.shared.paths import DATA_DIR
from modules.systemlog import log_system
from modules.ui.formatters.alert_text import format_aa, format_ghost_alert, format_missed_alert, format_pa
from modules.ui.formatters.birthday_text import format_bb, format_pb
from modules.ui.keyboards.notification_kb import (
    build_alert_notification_keyboard,
    build_birthday_notification_keyboard,
    build_ghost_notification_keyboard,
    build_missed_alert_keyboard,
    build_prealert_notification_keyboard,
)

logger = logging.getLogger(__name__)
_INVALID_MEDIA_BADREQUEST_MARKERS = (
    "wrong file identifier",
    "wrong remote file identifier",
    "failed to get http url content",
    "wrong type of the web page content",
    "wrong file_id",
)


def _resolve_scheduler_local_image_path(user_id, local_image_path, storage=None, require_exists=True):
    if storage is not None:
        try:
            resolved = storage.resolve_local_image_path(
                user_id,
                local_image_path,
                require_exists=require_exists,
            )
            return resolved
        except Exception:
            return None

    if not isinstance(local_image_path, str):
        return None
    raw = local_image_path.strip()
    if not raw:
        return None

    if os.path.isabs(raw):
        candidate = os.path.realpath(raw)
    else:
        normalized_rel = os.path.normpath(raw.replace("\\", "/")).replace("\\", "/")
        if normalized_rel in {"", ".", ".."}:
            return None
        if normalized_rel.startswith("../") or "/../" in normalized_rel:
            return None
        if normalized_rel.startswith("/"):
            return None
        if normalized_rel == "images":
            return None
        if not normalized_rel.startswith("images/"):
            return None
        candidate = os.path.realpath(os.path.join(DATA_DIR, str(user_id), normalized_rel))

    images_root = os.path.realpath(os.path.join(DATA_DIR, str(user_id), "images"))
    try:
        if os.path.commonpath([candidate, images_root]) != images_root:
            return None
    except Exception:
        return None
    if require_exists and not os.path.isfile(candidate):
        return None
    return candidate


def _extract_photo_file_id(message):
    photos = getattr(message, "photo", None)
    if not isinstance(photos, list) or not photos:
        return None
    last = photos[-1]
    file_id = getattr(last, "file_id", None)
    if isinstance(file_id, str) and file_id.strip():
        return file_id.strip()
    return None


def _is_invalid_media_bad_request(exc):
    if not isinstance(exc, BadRequest):
        return False
    message = str(exc or "").lower()
    return any(marker in message for marker in _INVALID_MEDIA_BADREQUEST_MARKERS)


def _resolve_scheduler_local_path_with_reason(user_id, local_image_path, storage=None):
    resolved_existing = _resolve_scheduler_local_image_path(
        user_id,
        local_image_path,
        storage=storage,
        require_exists=True,
    )
    if resolved_existing:
        return resolved_existing, "local_ok"

    resolved_any = _resolve_scheduler_local_image_path(
        user_id,
        local_image_path,
        storage=storage,
        require_exists=False,
    )
    if resolved_any:
        return None, "local_file_missing"
    return None, "local_path_invalid"


def _log_scheduler_media_event(storage, user_id, event, payload, level="INFO"):
    safe_payload = dict(payload or {})
    try:
        if storage is not None:
            storage.log_user_event(user_id, event, safe_payload)
    except Exception:
        logger.warning("Failed to write scheduler media user event: %s", event)
    try:
        system_payload = dict(safe_payload)
        system_payload["user_id"] = str(user_id)
        log_system("scheduler", event, system_payload, level=level)
    except Exception:
        logger.warning("Failed to write scheduler media system event: %s", event)


async def send_alert(
    bot,
    user_id: int,
    alert: dict,
    alert_type: str = C.ALERT_MSG_TYPE_MAIN,
    *,
    missed_time=None,
    pre_alert_str: str | None = None,
    main_trigger_time=None,
    scheduled_time=None,
    occurrence_time=None,
    postpone_count: int = 0,
    storage=None,
) -> object | None:
    """Send an alert notification (pre-alert, main, or missed) to the user.

    Dispatch to the formatter/keyboard pair for the chosen message type,
    then deliver through the image_id -> local file -> text fallback chain.
    """
    if not isinstance(alert, dict):
        return None

    try:
        alert_id = alert.get("id", "unknown")
        image_id = alert.get("image_id")
        local_image_path = alert.get("local_image_path")
        fallback_reasons = []
        autoheal_image_id = False

        if alert.get("type") == 6:
            # Birthday alerts never send images.
            image_id = None
            local_image_path = None

        _log_scheduler_media_event(
            storage,
            user_id,
            "scheduler_alert_media_attempt",
            {
                "alert_id": alert_id,
                "alert_type": alert_type,
                "has_image_id": bool(image_id),
                "has_local_image_path": bool(local_image_path),
                "postpone_count": int(postpone_count or 0),
            },
        )

        fmt_user_prefs = None
        if storage is not None and alert.get("type") == 6:
            try:
                fmt_user_prefs = storage.get_user_prefs(user_id)
            except Exception:
                fmt_user_prefs = None

        if alert_type == C.ALERT_MSG_TYPE_PRE:
            if scheduled_time is None and pre_alert_str and main_trigger_time:
                resolve_prefs = fmt_user_prefs
                if resolve_prefs is None and storage is not None:
                    try:
                        resolve_prefs = storage.get_user_prefs(user_id)
                    except Exception:
                        resolve_prefs = None
                resolved_pre, _kind = resolve_pre_alert_fire_time(
                    alert,
                    pre_alert_str,
                    main_trigger_time,
                    user_prefs=resolve_prefs,
                )
                if resolved_pre:
                    scheduled_time = resolved_pre
            if occurrence_time is None:
                occurrence_time = main_trigger_time

            if alert.get("type") == 6:
                text = format_pb(
                    alert,
                    main_trigger_time,
                    scheduled_time,
                    user_prefs=fmt_user_prefs,
                )
            else:
                text = format_pa(alert, main_trigger_time, scheduled_time)
            keyboard = build_prealert_notification_keyboard(
                alert,
                occurrence_time,
                scheduled_time,
                postpone_count=postpone_count,
            )
        elif alert_type == C.ALERT_MSG_TYPE_MISSED:
            text = format_missed_alert(alert, missed_time)
            keyboard = build_missed_alert_keyboard(alert)
        else:
            if occurrence_time is None:
                occurrence_time = scheduled_time

            if alert.get("type") == 6:
                text = format_bb(alert, scheduled_time, user_prefs=fmt_user_prefs)
                keyboard = build_birthday_notification_keyboard(
                    alert,
                    occurrence_time,
                    scheduled_time,
                    postpone_count=postpone_count,
                )
            elif is_ghost_alert(alert):
                text = format_ghost_alert(alert, scheduled_time)
                keyboard = build_ghost_notification_keyboard(
                    alert,
                    occurrence_time,
                    scheduled_time,
                )
            else:
                text = format_aa(alert, scheduled_time, user_prefs=fmt_user_prefs)
                keyboard = build_alert_notification_keyboard(
                    alert,
                    occurrence_time,
                    scheduled_time,
                    postpone_count=postpone_count,
                )

        if image_id:
            try:
                msg = await bot.send_photo(
                    chat_id=user_id,
                    photo=image_id,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN,
                )
                _log_scheduler_media_event(
                    storage,
                    user_id,
                    "scheduler_alert_media_result",
                    {
                        "alert_id": alert_id,
                        "alert_type": alert_type,
                        "delivery_mode": "image_id",
                        "reason_code": "image_id_ok",
                        "autoheal_image_id": False,
                    },
                )
                logger.info("Alert %s sent to %s (with image)", alert_id, user_id)
                return msg
            except BadRequest as exc:
                reason_code = "invalid_image_id" if _is_invalid_media_bad_request(exc) else "image_id_bad_request"
                fallback_reasons.append(reason_code)
                logger.warning(
                    "Scheduler media send via image_id failed for alert=%s user=%s reason=%s",
                    alert_id,
                    user_id,
                    reason_code,
                )
            except Exception:
                reason_code = "image_id_send_failed"
                fallback_reasons.append(reason_code)
                logger.warning(
                    "Scheduler media send via image_id failed for alert=%s user=%s reason=%s",
                    alert_id,
                    user_id,
                    reason_code,
                )

        resolved_local_path = None
        local_status = None
        if local_image_path:
            resolved_local_path, local_status = _resolve_scheduler_local_path_with_reason(
                user_id,
                local_image_path,
                storage=storage,
            )
            if not resolved_local_path and local_status:
                fallback_reasons.append(local_status)
                logger.warning(
                    "Scheduler local media unavailable for alert=%s user=%s reason=%s",
                    alert_id,
                    user_id,
                    local_status,
                )

        if resolved_local_path:
            try:
                with open(resolved_local_path, "rb") as img_file:
                    msg = await bot.send_photo(
                        chat_id=user_id,
                        photo=img_file,
                        caption=text,
                        reply_markup=keyboard,
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    recovered_image_id = _extract_photo_file_id(msg)
                    if (
                        storage is not None
                        and alert_id
                        and recovered_image_id
                        and recovered_image_id != image_id
                    ):
                        try:
                            updated = storage.update_alert_fields(
                                user_id,
                                alert_id,
                                {"image_id": recovered_image_id},
                            )
                            if updated:
                                alert["image_id"] = recovered_image_id
                                autoheal_image_id = True
                        except Exception:
                            logger.warning(
                                "Failed to auto-heal image_id for alert %s user %s",
                                alert_id,
                                user_id,
                            )
                    reason_code = "autoheal_image_id" if autoheal_image_id else "local_ok"
                    _log_scheduler_media_event(
                        storage,
                        user_id,
                        "scheduler_alert_media_result",
                        {
                            "alert_id": alert_id,
                            "alert_type": alert_type,
                            "delivery_mode": "local",
                            "reason_code": reason_code,
                            "autoheal_image_id": autoheal_image_id,
                            "fallback_reasons": fallback_reasons[-3:],
                        },
                    )
                    logger.info("Alert %s sent to %s (with local image)", alert_id, user_id)
                    return msg
            except Exception:
                fallback_reasons.append("local_send_failed")
                logger.warning(
                    "Scheduler media send via local file failed for alert=%s user=%s reason=%s",
                    alert_id,
                    user_id,
                    "local_send_failed",
                )

        if not fallback_reasons:
            fallback_reasons.append("no_media")

        try:
            msg = await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            _log_scheduler_media_event(
                storage,
                user_id,
                "scheduler_alert_media_result",
                {
                    "alert_id": alert_id,
                    "alert_type": alert_type,
                    "delivery_mode": "failed",
                    "reason_code": "detail_send_failed",
                    "autoheal_image_id": autoheal_image_id,
                    "fallback_reasons": fallback_reasons[-3:],
                },
                level="ERROR",
            )
            raise

        _log_scheduler_media_event(
            storage,
            user_id,
            "scheduler_alert_media_result",
            {
                "alert_id": alert_id,
                "alert_type": alert_type,
                "delivery_mode": "text",
                "reason_code": "fallback_to_text",
                "autoheal_image_id": autoheal_image_id,
                "fallback_reasons": fallback_reasons[-3:],
            },
        )
        logger.info("Alert %s sent to %s", alert_id, user_id)
        return msg
    except Exception as exc:
        logger.error("Failed to send alert %s to %s: %s", alert.get("id"), user_id, exc)
        return None
