"""Compatibility facade for legacy scheduler message/keyboard exports.

This module preserves import compatibility for existing runtime modules and
legacy debuggers while the implementation is being migrated under `modules.ui`.
New code should import formatters/keyboards/send utilities directly from
`modules.ui.*` modules.
"""

import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from modules import constants as C
from modules.birthday_utils import calculate_turning_age
from modules.ghost_utils import get_pending_ghost_alerts, is_ghost_alert
from modules.scheduler_mathlogic import format_datetime_human, get_next_occurrence
from modules.shared.markdown_utils import md_escape as _md_escape
from modules.ui.formatters.alert_text import (
    format_missed_alert,
    format_missed_alerts_summary,
)
from modules.ui.formatters.shared import (
    _is_repetition_limit_reached,
    append_zodiac_block,
    format_next_occurrence_line,
    format_time_until as _format_time_until,
)
from modules.ui.keyboards.callbacks import (
    build_alert_info_callback,
    build_bday_noted_callback,
    build_placebo_noted_callback,
    build_postpone_callback,
    build_prealert_info_callback,
    ts,
)
from modules.ui.send_utils import send_alert

logger = logging.getLogger(__name__)


ACTION_LABEL_POSTPONE = "⏰ POSTPONE this notification"
ACTION_LABEL_SNOOZE = "🔄 SNOOZE until manual re-activation"
ACTION_LABEL_ACTIVATE = "🟢 ACTIVATE again the alarm"
ACTION_LABEL_DELETE = "🗑️ DELETE forever this alert"


# ---------------------------------------------------------------------------
# CALLBACK PAYLOAD BUILDERS (legacy names)
# ---------------------------------------------------------------------------

def _ts(dt):
    return ts(dt)


def _build_postpone_callback(action, kind, alert_id, original_time, occurrence_time, postpone_count=0):
    return build_postpone_callback(action, kind, alert_id, original_time, occurrence_time, postpone_count)


def _build_prealert_info_callback(alert_id, original_time, occurrence_time, postpone_count=0):
    return build_prealert_info_callback(alert_id, original_time, occurrence_time, postpone_count)


def _build_alert_info_callback(alert_id, original_time, occurrence_time, postpone_count=0):
    return build_alert_info_callback(alert_id, original_time, occurrence_time, postpone_count)


def _build_placebo_done_callback(alert_id, original_time, occurrence_time):
    """Return the legacy `pdone_` callback payload for regular due notifications."""
    orig_ts = _ts(original_time)
    occ_ts = _ts(occurrence_time or original_time)
    return f"{C.CB_PLACEBO_DONE}{alert_id}_{orig_ts}_{occ_ts}"


def _build_placebo_noted_callback(alert_id, original_time, occurrence_time):
    return build_placebo_noted_callback(alert_id, original_time, occurrence_time)


def _build_bday_noted_callback(alert_id, original_time, occurrence_time):
    return build_bday_noted_callback(alert_id, original_time, occurrence_time)


def _build_prealert_edittext_callback(alert_id, original_time, occurrence_time):
    orig_ts = _ts(original_time)
    occ_ts = _ts(occurrence_time or original_time)
    return f"manage_edittext_pre_{alert_id}_{orig_ts}_{occ_ts}"


def _build_alert_edittext_callback(alert_id, original_time, occurrence_time):
    orig_ts = _ts(original_time)
    occ_ts = _ts(occurrence_time or original_time)
    return f"manage_edittext_due_{alert_id}_{orig_ts}_{occ_ts}"


# ---------------------------------------------------------------------------
# LEGACY FORMATTERS (kept for backward compatibility)
# ---------------------------------------------------------------------------

def _format_tags(tags):
    tags_str = ", ".join(str(tag) for tag in tags) if tags else "None"
    return f"🏷️ Tags: `{_md_escape(tags_str)}`"


def _format_common_lines(alert, scheduled_time, include_schedule=None):
    raw_title = alert.get("title", "Untitled Alert")
    title = _md_escape(str(raw_title).upper())
    type_name = _md_escape(alert.get("type_name", "Unknown"))
    scheduled_raw = format_datetime_human(scheduled_time) if scheduled_time else "Unknown"
    scheduled_str = _md_escape(scheduled_raw)
    if include_schedule is None:
        include_schedule = alert.get("type") != 6
    lines = [
        f"📌 **{title}**",
        "",
        f"📑 Type: `{type_name}`",
        _format_tags(alert.get("tags", [])),
    ]
    if include_schedule:
        lines.insert(2, f"📅 `{scheduled_str}`")
    return "\n".join(lines)


def _format_next_occurrence_line(alert, reference_dt):
    return format_next_occurrence_line(alert, reference_dt)


# DEPRECATED

def format_main_alert(alert, scheduled_time=None, user_prefs=None):
    """Render the legacy main-alert text format for backward compatibility."""
    if scheduled_time is None:
        next_scheduled = alert.get("next_scheduled")
        if next_scheduled:
            try:
                scheduled_time = datetime.fromisoformat(next_scheduled)
            except ValueError:
                scheduled_time = None
    is_birthday = alert.get("type") == 6

    if is_birthday:
        name_raw = (alert.get("title") or "Untitled").upper()
        name_esc = _md_escape(name_raw)
        name_plain = _md_escape(alert.get("title") or "Untitled")
        message = f"🎂 BIRTHDAY\nof `{name_esc}`\n\n"

        turning = None
        if scheduled_time is not None:
            turning = calculate_turning_age(alert.get("birth_year"), scheduled_time.year)

        if turning is not None:
            message += f"🎉 {name_plain} turns **{turning}**!"
        else:
            message += f"🎉 Happy birthday, {name_plain}!\n*(year unknown — you could ask them!)*"

        message += append_zodiac_block(alert, user_prefs)
        message += f"\n\n{_format_tags(alert.get('tags', []))}"
        return message

    message = "🔔 **ALERT**\n\n"
    message += _format_common_lines(alert, scheduled_time)

    if alert.get("type") not in (5, 6):
        next_line = _format_next_occurrence_line(alert, scheduled_time or datetime.now())
        if next_line:
            message += f"\n\n{next_line}"
    return message


# DEPRECATED

def format_pre_alert(alert, main_trigger_time, scheduled_time=None, user_prefs=None):
    """Render the legacy pre-alert text format for backward compatibility."""
    if scheduled_time is None:
        scheduled_time = main_trigger_time
    time_until = _format_time_until(main_trigger_time)
    main_time_str = format_datetime_human(main_trigger_time)

    if alert.get("type") == 6:
        name_raw = (alert.get("title") or "Untitled").upper()
        name_esc = _md_escape(name_raw)
        name_plain = _md_escape(alert.get("title") or "Untitled")
        message = f"🎂 UPCOMING BIRTHDAY\nof `{name_esc}`\n\n"
        turning = None
        if main_trigger_time is not None:
            turning = calculate_turning_age(alert.get("birth_year"), main_trigger_time.year)
        if turning is not None:
            message += f"⚠️ {name_plain} will be **{turning}**!\n"
        else:
            message += f"⚠️ {name_plain}'s age is a mystery — maybe ask them? 😄\n"
        date_str = main_trigger_time.strftime("%d/%m") if main_trigger_time is not None else "??/??"
        message += f"The birthday will be on `{date_str}` in {time_until}!"
        message += append_zodiac_block(alert, user_prefs)
        message += f"\n\n{_format_tags(alert.get('tags', []))}"
        return message

    message = "⏳ **UPCOMING ALERT**\n\n"
    message += _format_common_lines(alert, scheduled_time)
    message += f"\n\n⚠️ This alert is due in **{time_until}**"
    message += f"\n📅 Scheduled: `{main_time_str}`"

    if alert.get("type") not in (5, 6):
        next_line = _format_next_occurrence_line(alert, main_trigger_time or datetime.now())
        if next_line:
            message += f"\n{next_line}"
    return message


# ---------------------------------------------------------------------------
# LEGACY KEYBOARD BUILDERS (kept for backward compatibility)
# ---------------------------------------------------------------------------

def get_toggle_action_label(alert):
    """Return the legacy state-aware toggle label for recurring alerts."""
    is_active = True
    if isinstance(alert, dict):
        is_active = bool(alert.get("active", True))
    return ACTION_LABEL_SNOOZE if is_active else ACTION_LABEL_ACTIVATE


def get_alert_keyboard(alert, occurrence_time=None, original_time=None, postpone_count=0):
    """Build the legacy due-notification keyboard."""
    if not alert:
        return None

    alert_id = alert.get("id", "unknown")
    original_time = original_time or occurrence_time
    occurrence_time = occurrence_time or original_time

    is_birthday = alert.get("type") == 6
    if is_birthday:
        placebo_btn = InlineKeyboardButton(
            "👀 NOTED !",
            callback_data=_build_bday_noted_callback(alert_id, original_time, occurrence_time),
        )
    else:
        placebo_btn = InlineKeyboardButton(
            "✅ DONE !",
            callback_data=_build_placebo_done_callback(alert_id, original_time, occurrence_time),
        )

    keyboard = [[placebo_btn]]
    keyboard.append([
        InlineKeyboardButton(
            ACTION_LABEL_POSTPONE,
            callback_data=_build_postpone_callback(
                "menu", "due", alert_id, original_time, occurrence_time, postpone_count
            ),
        )
    ])

    if alert.get("type") != 5:
        keyboard.append([
            InlineKeyboardButton(get_toggle_action_label(alert), callback_data=f"{C.CB_ALERT_TOGGLE}{alert_id}")
        ])

    keyboard.append([
        InlineKeyboardButton(ACTION_LABEL_DELETE, callback_data=f"{C.CB_ALERT_DELETE}{alert_id}")
    ])
    keyboard.append([
        InlineKeyboardButton(
            "ℹ️ Detailed info",
            callback_data=_build_alert_info_callback(alert_id, original_time, occurrence_time, postpone_count),
        )
    ])

    return InlineKeyboardMarkup(keyboard)


def get_pre_alert_keyboard(alert, occurrence_time=None, original_time=None, include_info=True, postpone_count=0):
    """Build the legacy pre-alert keyboard."""
    if not alert:
        return None

    alert_id = alert.get("id", "unknown")
    original_time = original_time or occurrence_time
    occurrence_time = occurrence_time or original_time

    keyboard = [[
        InlineKeyboardButton(
            "👀 NOTED !",
            callback_data=_build_placebo_noted_callback(alert_id, original_time, occurrence_time),
        )
    ]]

    keyboard.append([
        InlineKeyboardButton(
            ACTION_LABEL_POSTPONE,
            callback_data=_build_postpone_callback(
                "menu", "pre", alert_id, original_time, occurrence_time, postpone_count
            ),
        )
    ])

    if alert.get("type") != 5:
        keyboard.append([
            InlineKeyboardButton(get_toggle_action_label(alert), callback_data=f"{C.CB_ALERT_TOGGLE}{alert_id}")
        ])

    keyboard.append([
        InlineKeyboardButton(ACTION_LABEL_DELETE, callback_data=f"{C.CB_ALERT_DELETE}{alert_id}")
    ])

    if include_info:
        keyboard.append([
            InlineKeyboardButton(
                "ℹ️ Detailed info",
                callback_data=_build_prealert_info_callback(alert_id, original_time, occurrence_time, postpone_count),
            )
        ])

    return InlineKeyboardMarkup(keyboard)


def build_pre_alert_detail_keyboard(alert, occurrence_time=None, original_time=None, postpone_count=0):
    """Build the legacy pre-alert detail keyboard used by old notification flows."""
    if not alert:
        return None

    alert_id = alert.get("id", "unknown")
    original_time = original_time or occurrence_time
    occurrence_time = occurrence_time or original_time

    keyboard = [[
        InlineKeyboardButton(
            "👀 NOTED !",
            callback_data=_build_placebo_noted_callback(alert_id, original_time, occurrence_time),
        )
    ]]

    keyboard.append([
        InlineKeyboardButton(
            ACTION_LABEL_POSTPONE,
            callback_data=_build_postpone_callback(
                "menu", "pre", alert_id, original_time, occurrence_time, postpone_count
            ),
        )
    ])

    if alert.get("type") != 5:
        keyboard.append([
            InlineKeyboardButton(get_toggle_action_label(alert), callback_data=f"{C.CB_ALERT_TOGGLE}{alert_id}")
        ])

    keyboard.append([
        InlineKeyboardButton(ACTION_LABEL_DELETE, callback_data=f"{C.CB_ALERT_DELETE}{alert_id}")
    ])
    keyboard.append([
        InlineKeyboardButton(
            "✏️ Edit text",
            callback_data=_build_prealert_edittext_callback(alert_id, original_time, occurrence_time),
        )
    ])

    return InlineKeyboardMarkup(keyboard)


def build_alert_detail_keyboard(alert, occurrence_time=None, original_time=None, postpone_count=0):
    """Build the legacy due-alert detail keyboard used by old notification flows."""
    if not alert:
        return None

    alert_id = alert.get("id", "unknown")
    original_time = original_time or occurrence_time
    occurrence_time = occurrence_time or original_time

    is_birthday = alert.get("type") == 6
    if is_birthday:
        placebo_btn = InlineKeyboardButton(
            "👀 NOTED !",
            callback_data=_build_bday_noted_callback(alert_id, original_time, occurrence_time),
        )
    else:
        placebo_btn = InlineKeyboardButton(
            "✅ DONE !",
            callback_data=_build_placebo_done_callback(alert_id, original_time, occurrence_time),
        )

    keyboard = [[placebo_btn]]
    keyboard.append([
        InlineKeyboardButton(
            ACTION_LABEL_POSTPONE,
            callback_data=_build_postpone_callback(
                "menu", "due", alert_id, original_time, occurrence_time, postpone_count
            ),
        )
    ])

    if alert.get("type") != 5:
        keyboard.append([
            InlineKeyboardButton(get_toggle_action_label(alert), callback_data=f"{C.CB_ALERT_TOGGLE}{alert_id}")
        ])

    keyboard.append([
        InlineKeyboardButton(ACTION_LABEL_DELETE, callback_data=f"{C.CB_ALERT_DELETE}{alert_id}")
    ])
    keyboard.append([
        InlineKeyboardButton(
            "✏️ Edit text",
            callback_data=_build_alert_edittext_callback(alert_id, original_time, occurrence_time),
        )
    ])

    return InlineKeyboardMarkup(keyboard)


def get_missed_alert_keyboard(alert):
    """Build the keyboard for missed-alert notifications."""
    # Superseded by per-alert buttons in send_missed_alerts_batch; retained for compatibility.
    if not alert:
        return None
    alert_id = alert.get("id", "unknown")
    keyboard = [[
        InlineKeyboardButton(ACTION_LABEL_DELETE, callback_data=f"{C.CB_ALERT_DELETE}{alert_id}"),
    ]]
    return InlineKeyboardMarkup(keyboard)


# ---------------------------------------------------------------------------
# Remaining legacy send helpers
# ---------------------------------------------------------------------------

def _truncated_title(title: str, max_len: int = 28) -> str:
    if not isinstance(title, str):
        title = str(title or "")
    return title[:max_len] + "…" if len(title) > max_len else title


def _missed_item_timestamp(item) -> str:
    if not isinstance(item, dict):
        return "0"
    candidates = []
    for key in ("missed_due", "missed_pre"):
        values = item.get(key) or []
        for dt in values:
            if isinstance(dt, datetime):
                candidates.append(dt)
    if candidates:
        return str(int(min(candidates).timestamp()))
    occ_iso = item.get("_occ_iso")
    if isinstance(occ_iso, str) and occ_iso.strip():
        try:
            return str(int(datetime.fromisoformat(occ_iso).timestamp()))
        except Exception:
            return "0"
    return "0"


async def send_missed_alerts_batch(bot, user_id: int, missed_alerts: list, *, storage=None):
    """Send the startup missed-alerts summary message to a user."""
    if not missed_alerts:
        return None

    try:
        standard_items = []
        missed_ghost_items = []
        for item in missed_alerts:
            alert = item.get("alert") if isinstance(item, dict) else None
            if is_ghost_alert(alert):
                missed_ghost_items.append(item)
            else:
                standard_items.append(item)

        pending_ghost_alerts = get_pending_ghost_alerts(storage, user_id) if storage else []
        summary_text = format_missed_alerts_summary(
            standard_items,
            missed_ghost_items,
            pending_ghost_alerts,
        )
        if not summary_text:
            return None

        keyboard = []
        for item in standard_items[:20]:
            alert = item.get("alert") if isinstance(item, dict) else None
            if not isinstance(alert, dict):
                continue
            alert_id = str(alert.get("id") or "")[:8]
            if not alert_id:
                continue
            missed_ts = _missed_item_timestamp(item)
            keyboard.append([
                InlineKeyboardButton(
                    f"🔔 {_truncated_title(alert.get('title') or 'Untitled')}",
                    callback_data=f"missed_dtl_{alert_id}_{missed_ts}",
                )
            ])

        msg = await bot.send_message(
            chat_id=user_id,
            text=summary_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        )
        logger.info("Missed alerts summary sent to %s (%s alerts)", user_id, len(standard_items))
        return msg
    except Exception as exc:
        logger.error("Failed to send missed alerts summary to %s: %s", user_id, exc)
        return None


async def send_snooze_confirmation(bot, user_id, alert, snoozed_until):
    """Send a confirmation message after snoozing an alert."""
    try:
        title = _md_escape(alert.get("title", "Alert"))
        until_str = _md_escape(format_datetime_human(snoozed_until))
        text = f"💤 **{title}** snoozed until `{until_str}`"

        return await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as exc:
        logger.error("Failed to send snooze confirmation to %s: %s", user_id, exc)
        return None


async def send_done_confirmation(bot, user_id, alert, was_one_time=False):
    """Send a confirmation message after marking an alert as done."""
    try:
        title = _md_escape(alert.get("title", "Alert"))

        if was_one_time:
            text = f"✅ **{title}** completed and archived."
        else:
            next_occ = get_next_occurrence(alert, datetime.now())
            if next_occ:
                next_str = _md_escape(format_datetime_human(next_occ))
                text = f"✅ **{title}** marked done.\n\n📅 Next: `{next_str}`"
            elif _is_repetition_limit_reached(alert, datetime.now()):
                text = (
                    f"✅ **{title}** marked done.\n\n"
                    "📅 No next occurrence: repetition limit reached."
                )
            else:
                text = f"✅ **{title}** marked done."

        return await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as exc:
        logger.error("Failed to send done confirmation to %s: %s", user_id, exc)
        return None
