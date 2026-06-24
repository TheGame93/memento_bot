"""Render detail cards and deliver alert detail views with media fallback."""

import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from modules.scheduler_mathlogic import format_pre_alert_display
from modules.shared.acting_as import (
    build_acting_as_payload,
    get_actor_user_id,
    get_target_user_id,
)
from modules.shared.markdown_utils import md_escape as _md_escape, md_escape_fence_content
from modules.shared.runtime_context import get_runtime_storage
from modules.ui.formatters.info_text import format_ia, format_ib
from modules.ui.keyboards.detail_kb import build_detail_keyboard

from .compact_list import _format_dt_for_list, _get_compact_context, _get_next_dt
from .filter_menu import LIST_CONTEXT_KEY, _render_filter_label

logger = logging.getLogger(__name__)

_BDAY_UNTAGGED_FILTER_VALUE = ("__bday_untagged_filter_state__",)
_BDAY_UNTAGGED_FILTER_LABEL = "🏷️ Untagged"

_INVALID_MEDIA_BADREQUEST_MARKERS = (
    "wrong file identifier",
    "wrong remote file identifier",
    "failed to get http url content",
    "wrong type of the web page content",
    "wrong file_id",
)


def _resolve_ids(update, context):
    actor_id = get_actor_user_id(update)
    target_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)
    return actor_id, target_id, acting_payload


def _format_additional_info_block(alert):
    text = (alert.get("additional_info") or "").rstrip()
    if not text:
        return "`None`"
    safe = md_escape_fence_content(text)
    return f"```\n{safe}\n```"


def _format_standard_card(alert, user_prefs=None):
    status_dot = "🟢" if alert.get("active", True) else "🔴"
    title = _md_escape((alert.get("title") or "Untitled").upper())
    tags_list = alert.get("tags", []) or []
    tags = _md_escape(", ".join(tags_list) if tags_list else "None")
    next_dt = _get_next_dt(alert)
    pre_alerts = alert.get("pre_alerts", [])
    pre_labels = [
        format_pre_alert_display(alert, token, due_dt=next_dt, user_prefs=user_prefs)
        for token in pre_alerts
    ]
    pre_line = f"🔔 Pre alert: `{_md_escape(', '.join(pre_labels))}`" if pre_labels else ""

    if alert.get("type") == 6:
        next_str = _format_dt_for_list(next_dt, include_time=False)
        lines = [
            f"{status_dot} **{title}**",
            "",
            f"⏰ Next scheduled: `{next_str}`",
        ]
        if pre_line:
            lines.append(pre_line)
        lines.append(f"🏷️ {tags}")
        return "\n".join(lines)

    type_name = _md_escape(alert.get("type_name") or "Unknown")
    next_str = _format_dt_for_list(next_dt, include_time=True)
    lines = [
        f"{status_dot} **{title}**",
        "",
        f"📑 Type: {type_name}",
        f"⏰ Next scheduled: `{next_str}`",
    ]
    if pre_line:
        lines.append(pre_line)
    lines.append(f"🏷️ {tags}")
    return "\n".join(lines)


def format_standard_card(alert):
    """Render the compact standard card text used by list/manage entry views."""
    return _format_standard_card(alert)


def format_detailed_card(alert, user_prefs=None):
    """Render the public detail card text for alerts and birthdays."""
    if alert.get("type") == 6:
        return format_ib(alert, user_prefs=user_prefs)
    return format_ia(alert, user_prefs=user_prefs)


def _format_detailed_card(alert, user_prefs=None):
    """Return the detailed card text through the public compatibility wrapper."""
    return format_detailed_card(alert, user_prefs=user_prefs)


def _normalize_back_source(source):
    if source == "next_birthdays":
        return "birthdays"
    if source == "next_alerts":
        return "alerts"
    return source


def _get_back_button(context, source):
    """Build the list-detail Back button preserving source-aware tag labels."""
    source = _normalize_back_source(source)
    if source in {"alerts_search", "birthdays_search"}:
        return InlineKeyboardButton("⬅️ Back to search", callback_data="manage_backtolist")

    if source == "birthdays":
        tag_filter = context.user_data.get("birthday_current_filter", "ALL")
    else:
        tag_filter = context.user_data.get("current_filter", "ALL")

    back_label = "⬅️ Back" if tag_filter == "ALL" else f"⬅️ Back ({_render_filter_label(tag_filter)})"
    return InlineKeyboardButton(back_label, callback_data="manage_backtolist")


def build_info_keyboard(alert_id, context, source="alerts", include_back=False, alert=None):
    """Build the list-origin detail keyboard via the shared UI keyboard builder."""
    normalized_source = _normalize_back_source(source)
    if normalized_source == "birthdays":
        tag_filter = context.user_data.get("birthday_current_filter", "ALL")
    else:
        tag_filter = context.user_data.get("current_filter", "ALL")
    if tag_filter == _BDAY_UNTAGGED_FILTER_VALUE:
        tag_filter = _BDAY_UNTAGGED_FILTER_LABEL
    elif tag_filter != "ALL":
        tag_filter = _render_filter_label(tag_filter)
    return build_detail_keyboard(
        alert or {"id": alert_id},
        source=normalized_source,
        from_notification=False,
        include_back=include_back,
        tag_filter=tag_filter,
    )


def get_info_text_and_kb(alert, context, source="alerts", include_back=False, user_prefs=None):
    """Generate detailed text and keyboard for an info view."""
    alert_id = alert["id"]
    info_text = format_detailed_card(alert, user_prefs=user_prefs)
    return info_text, build_info_keyboard(
        alert_id,
        context,
        source=source,
        include_back=include_back,
        alert=alert,
    )


def _is_invalid_media_bad_request(exc):
    if not isinstance(exc, BadRequest):
        return False
    message = str(exc or "").lower()
    return any(marker in message for marker in _INVALID_MEDIA_BADREQUEST_MARKERS)


def _extract_photo_file_id(message):
    photos = getattr(message, "photo", None)
    if not isinstance(photos, list) or not photos:
        return None
    photo = photos[-1]
    file_id = getattr(photo, "file_id", None)
    if isinstance(file_id, str) and file_id.strip():
        return file_id.strip()
    return None


def _log_alert_detail_event(storage, user_id, event_type, payload, acting_payload=None):
    merged = dict(payload or {})
    if isinstance(acting_payload, dict):
        merged.update(acting_payload)
    try:
        storage.log_user_event(user_id, event_type, merged)
    except Exception:
        logger.warning("Failed to write alert detail telemetry event: %s", event_type)


def _resolve_detail_local_image(storage, user_id, local_image_path):
    if not local_image_path:
        return None, "local_missing"
    try:
        resolved_exists = storage.resolve_local_image_path(
            user_id, local_image_path, require_exists=True
        )
        if resolved_exists:
            return resolved_exists, "local_ok"
        resolved_any = storage.resolve_local_image_path(
            user_id, local_image_path, require_exists=False
        )
        if resolved_any:
            return None, "local_file_missing"
        return None, "local_path_invalid"
    except Exception:
        return None, "local_path_invalid"


async def _send_alert_detail_with_media_fallback(
    *,
    context,
    storage,
    actor_id,
    user_id,
    alert,
    source,
    include_back,
    open_origin,
    acting_payload=None,
    user_prefs=None,
):
    alert_id = alert.get("id")
    info_text, kb = get_info_text_and_kb(
        alert, context, source=source, include_back=include_back, user_prefs=user_prefs
    )
    image_id = alert.get("image_id")
    local_image_path = alert.get("local_image_path")
    if alert.get("type") == 6:
        image_id = None
        local_image_path = None

    has_image_id = bool(image_id)
    has_local = bool(local_image_path)
    fallback_reasons = []
    autoheal_image_id = False

    _log_alert_detail_event(
        storage,
        user_id,
        "alert_detail_open_attempt",
        {
            "alert_id": alert_id,
            "source": source,
            "origin": open_origin,
            "has_image_id": has_image_id,
            "has_local_image_path": has_local,
            "include_back": bool(include_back),
        },
        acting_payload=acting_payload,
    )

    if image_id:
        try:
            msg = await context.bot.send_photo(
                chat_id=actor_id,
                photo=image_id,
                caption=info_text,
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN,
            )
            _log_alert_detail_event(
                storage,
                user_id,
                "alert_detail_open_result",
                {
                    "alert_id": alert_id,
                    "source": source,
                    "origin": open_origin,
                    "delivery_mode": "image_id",
                    "reason_code": "image_id_ok",
                    "autoheal_image_id": False,
                },
                acting_payload=acting_payload,
            )
            return {
                "delivered": True,
                "delivery_mode": "image_id",
                "reason_code": "image_id_ok",
                "message": msg,
                "is_photo": True,
            }
        except BadRequest as exc:
            if _is_invalid_media_bad_request(exc):
                fallback_reasons.append("invalid_image_id")
            else:
                fallback_reasons.append("image_id_bad_request")
            logger.warning(
                "Detail send via image_id failed for alert=%s reason=%s", alert_id, fallback_reasons[-1]
            )
        except Exception:
            fallback_reasons.append("image_id_send_failed")
            logger.warning(
                "Detail send via image_id failed for alert=%s reason=%s", alert_id, fallback_reasons[-1]
            )

    resolved_local_path = None
    local_status = "local_missing"
    if local_image_path:
        resolved_local_path, local_status = _resolve_detail_local_image(
            storage, user_id, local_image_path
        )
        if not resolved_local_path:
            fallback_reasons.append(local_status)
            logger.warning("Detail local media unavailable for alert=%s reason=%s", alert_id, local_status)

    if resolved_local_path:
        try:
            with open(resolved_local_path, "rb") as local_file:
                msg = await context.bot.send_photo(
                    chat_id=actor_id,
                    photo=local_file,
                    caption=info_text,
                    reply_markup=kb,
                    parse_mode=ParseMode.MARKDOWN,
                )
            repaired_image_id = _extract_photo_file_id(msg)
            if alert_id and repaired_image_id and repaired_image_id != image_id:
                autoheal_image_id = bool(
                    storage.update_alert_fields(
                        user_id, alert_id, {"image_id": repaired_image_id}
                    )
                )
            reason_code = "local_ok"
            if autoheal_image_id:
                reason_code = "autoheal_image_id"
            _log_alert_detail_event(
                storage,
                user_id,
                "alert_detail_open_result",
                {
                    "alert_id": alert_id,
                    "source": source,
                    "origin": open_origin,
                    "delivery_mode": "local",
                    "reason_code": reason_code,
                    "autoheal_image_id": autoheal_image_id,
                    "fallback_reasons": fallback_reasons[-3:],
                },
                acting_payload=acting_payload,
            )
            return {
                "delivered": True,
                "delivery_mode": "local",
                "reason_code": reason_code,
                "message": msg,
                "is_photo": True,
            }
        except Exception:
            fallback_reasons.append("local_send_failed")
            logger.warning("Detail send via local media failed for alert=%s", alert_id)

    if not fallback_reasons:
        fallback_reasons.append("no_media")

    try:
        msg = await context.bot.send_message(
            chat_id=actor_id,
            text=info_text,
            reply_markup=kb,
            parse_mode=ParseMode.MARKDOWN,
        )
        _log_alert_detail_event(
            storage,
            user_id,
            "alert_detail_open_result",
            {
                "alert_id": alert_id,
                "source": source,
                "origin": open_origin,
                "delivery_mode": "text",
                "reason_code": "fallback_to_text",
                "autoheal_image_id": False,
                "fallback_reasons": fallback_reasons[-3:],
            },
            acting_payload=acting_payload,
        )
        return {
            "delivered": True,
            "delivery_mode": "text",
            "reason_code": "fallback_to_text",
            "message": msg,
            "is_photo": False,
        }
    except BadRequest:
        try:
            msg = await context.bot.send_message(
                chat_id=actor_id,
                text=info_text,
                reply_markup=kb,
            )
            _log_alert_detail_event(
                storage,
                user_id,
                "alert_detail_open_result",
                {
                    "alert_id": alert_id,
                    "source": source,
                    "origin": open_origin,
                    "delivery_mode": "text_plain",
                    "reason_code": "text_markdown_bad_request",
                    "autoheal_image_id": False,
                    "fallback_reasons": fallback_reasons[-3:],
                },
                acting_payload=acting_payload,
            )
            return {
                "delivered": True,
                "delivery_mode": "text_plain",
                "reason_code": "text_markdown_bad_request",
                "message": msg,
                "is_photo": False,
            }
        except Exception:
            pass
    except Exception:
        pass

    _log_alert_detail_event(
        storage,
        user_id,
        "alert_detail_open_result",
        {
            "alert_id": alert_id,
            "source": source,
            "origin": open_origin,
            "delivery_mode": "failed",
            "reason_code": "detail_send_failed",
            "autoheal_image_id": autoheal_image_id,
            "fallback_reasons": fallback_reasons[-3:],
        },
        acting_payload=acting_payload,
    )
    return {
        "delivered": False,
        "delivery_mode": "failed",
        "reason_code": "detail_send_failed",
        "message": None,
        "is_photo": False,
    }


async def send_alert_detail_by_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    alert_id,
    source_hint=None,
    include_back: bool = True,
):
    """Open detailed view for one alert or birthday by ID."""
    storage = get_runtime_storage(context)
    actor_id, user_id, acting_payload = _resolve_ids(update, context)
    alert = storage.get_alert_by_id(user_id, alert_id)
    if not alert:
        await context.bot.send_message(chat_id=actor_id, text="❌ Item not found.")
        return

    source = source_hint or ("birthdays" if alert.get("type") == 6 else "alerts")
    context.user_data["manage_source"] = source
    if source_hint is None:
        default_filter = "ALL"
        if source == "alerts":
            default_filter = context.user_data.get("current_filter", "ALL")
        else:
            default_filter = context.user_data.get("birthday_current_filter", "ALL")
        context.user_data[LIST_CONTEXT_KEY] = {
            "source": source,
            "tag_filter": default_filter,
            "page": 1,
            "alias_map": {},
            "saved_at": datetime.now().isoformat(),
        }
    open_origin = "shortcut_global"
    if source_hint is not None:
        open_origin = "shortcut_local_alias"
    result = await _send_alert_detail_with_media_fallback(
        context=context,
        storage=storage,
        actor_id=actor_id,
        user_id=user_id,
        alert=alert,
        source=source,
        include_back=include_back,
        open_origin=open_origin,
        acting_payload=acting_payload,
        user_prefs=storage.get_user_prefs(user_id) or {},
    )
    if not result.get("delivered"):
        await context.bot.send_message(
            chat_id=actor_id,
            text="⚠️ Could not open item details now. Please retry from /list.",
        )
