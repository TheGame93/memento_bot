"""
notification_kb.py — Inline keyboard builders for notification message types.

Covers PA and PB (pre-alert), AA (regular alert), BB (birthday alert), and
missed-alert recovery keyboards.  Button labels are defined as module-level
constants so that detail_kb.py and other callers can import them.

Note on 'pdone_' prefix: the NOTED button on regular AA notifications uses the
'pdone_' callback prefix for backward compatibility with existing Telegram
messages already in chat.  The label changed from '✅ DONE !' to '👀 NOTED',
but the prefix is intentionally preserved so old keyboards remain functional.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from modules import constants as C
from modules.ui.keyboards.callbacks import (
    build_alert_info_callback,
    build_bday_noted_callback,
    build_placebo_noted_callback,
    build_postpone_callback,
    build_prealert_info_callback,
    ts,
)

ACTION_LABEL_NOTED    = "👀 NOTED"
ACTION_LABEL_POSTPONE = "⏰ POSTPONE this notification"
ACTION_LABEL_SNOOZE   = "🔄 SNOOZE until manual re-activation"
ACTION_LABEL_ACTIVATE = "🟢 ACTIVATE again the alarm"
ACTION_LABEL_DELETE   = "🗑️ DELETE forever this alert"
ACTION_LABEL_INFO     = "ℹ️ Detailed INFO"


def get_toggle_action_label(alert: dict) -> str:
    """Return SNOOZE or ACTIVATE label based on alert.active state."""
    return ACTION_LABEL_SNOOZE if alert.get("active", True) else ACTION_LABEL_ACTIVATE


def build_alert_notification_keyboard(
    alert: dict,
    occurrence_time,
    original_time,
    postpone_count: int = 0,
) -> InlineKeyboardMarkup:
    """Keyboard for AA (regular alert notification).

    Row 1: [👀 NOTED]  (pdone_ callback — label changed from '✅ DONE !', prefix preserved)
    Row 2: [⏰ POSTPONE this notification]
    Row 3: [🔄 SNOOZE | 🟢 ACTIVATE]  (hidden for type 5 one-time alerts)
    Row 4: [🗑️ DELETE forever this alert]
    Row 5: [ℹ️ Detailed INFO]
    """
    if not alert:
        return None
    alert_id = alert.get("id", "unknown")
    original_time = original_time or occurrence_time
    occurrence_time = occurrence_time or original_time

    # pdone_ prefix preserved; only the label changes to "👀 NOTED"
    noted_cb = f"{C.CB_PLACEBO_DONE}{alert_id}_{ts(original_time)}_{ts(occurrence_time)}"
    keyboard = [[InlineKeyboardButton(ACTION_LABEL_NOTED, callback_data=noted_cb)]]

    keyboard.append([InlineKeyboardButton(
        ACTION_LABEL_POSTPONE,
        callback_data=build_postpone_callback(
            "menu", "due", alert_id, original_time, occurrence_time, postpone_count
        ),
    )])

    if alert.get("type") != 5:
        keyboard.append([InlineKeyboardButton(
            get_toggle_action_label(alert),
            callback_data=f"{C.CB_ALERT_TOGGLE}{alert_id}",
        )])

    keyboard.append([InlineKeyboardButton(
        ACTION_LABEL_DELETE,
        callback_data=f"{C.CB_ALERT_DELETE}{alert_id}",
    )])
    keyboard.append([InlineKeyboardButton(
        ACTION_LABEL_INFO,
        callback_data=build_alert_info_callback(
            alert_id, original_time, occurrence_time, postpone_count
        ),
    )])

    return InlineKeyboardMarkup(keyboard)


def build_birthday_notification_keyboard(
    alert: dict,
    occurrence_time,
    original_time,
    postpone_count: int = 0,
) -> InlineKeyboardMarkup:
    """Keyboard for BB (birthday notification).

    Row 1: [👀 NOTED]  (bnote_ callback → triggers birthday message suggestion flow)
    Row 2: [⏰ POSTPONE this notification]
    Row 3: [🔄 SNOOZE | 🟢 ACTIVATE]
    Row 4: [🗑️ DELETE forever this alert]
    Row 5: [ℹ️ Detailed INFO]
    """
    if not alert:
        return None
    alert_id = alert.get("id", "unknown")
    original_time = original_time or occurrence_time
    occurrence_time = occurrence_time or original_time

    keyboard = [[InlineKeyboardButton(
        ACTION_LABEL_NOTED,
        callback_data=build_bday_noted_callback(alert_id, original_time, occurrence_time),
    )]]

    keyboard.append([InlineKeyboardButton(
        ACTION_LABEL_POSTPONE,
        callback_data=build_postpone_callback(
            "menu", "due", alert_id, original_time, occurrence_time, postpone_count
        ),
    )])

    # Birthday alerts are always recurring (type 6) — snooze always shown
    keyboard.append([InlineKeyboardButton(
        get_toggle_action_label(alert),
        callback_data=f"{C.CB_ALERT_TOGGLE}{alert_id}",
    )])

    keyboard.append([InlineKeyboardButton(
        ACTION_LABEL_DELETE,
        callback_data=f"{C.CB_ALERT_DELETE}{alert_id}",
    )])
    keyboard.append([InlineKeyboardButton(
        ACTION_LABEL_INFO,
        callback_data=build_alert_info_callback(
            alert_id, original_time, occurrence_time, postpone_count
        ),
    )])

    return InlineKeyboardMarkup(keyboard)


def build_prealert_notification_keyboard(
    alert: dict,
    occurrence_time,
    original_time,
    postpone_count: int = 0,
) -> InlineKeyboardMarkup:
    """Keyboard for PA and PB (pre-alert notifications, both alert and birthday).

    Row 1: [👀 NOTED]  (pnote_ callback)
    Row 2: [⏰ POSTPONE this notification]
    Row 3: [🔄 SNOOZE | 🟢 ACTIVATE]  (hidden for type 5 one-time alerts)
    Row 4: [🗑️ DELETE forever this alert]
    Row 5: [ℹ️ Detailed INFO]
    """
    if not alert:
        return None
    alert_id = alert.get("id", "unknown")
    original_time = original_time or occurrence_time
    occurrence_time = occurrence_time or original_time

    keyboard = [[InlineKeyboardButton(
        ACTION_LABEL_NOTED,
        callback_data=build_placebo_noted_callback(alert_id, original_time, occurrence_time),
    )]]

    keyboard.append([InlineKeyboardButton(
        ACTION_LABEL_POSTPONE,
        callback_data=build_postpone_callback(
            "menu", "pre", alert_id, original_time, occurrence_time, postpone_count
        ),
    )])

    if alert.get("type") != 5:
        keyboard.append([InlineKeyboardButton(
            get_toggle_action_label(alert),
            callback_data=f"{C.CB_ALERT_TOGGLE}{alert_id}",
        )])

    keyboard.append([InlineKeyboardButton(
        ACTION_LABEL_DELETE,
        callback_data=f"{C.CB_ALERT_DELETE}{alert_id}",
    )])
    keyboard.append([InlineKeyboardButton(
        ACTION_LABEL_INFO,
        callback_data=build_prealert_info_callback(
            alert_id, original_time, occurrence_time, postpone_count
        ),
    )])

    return InlineKeyboardMarkup(keyboard)


def build_missed_alert_keyboard(alert: dict) -> InlineKeyboardMarkup:
    """Keyboard for missed-alert recovery messages (one DELETE button row)."""
    if not alert:
        return None
    alert_id = alert.get("id", "unknown")
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(ACTION_LABEL_DELETE, callback_data=f"{C.CB_ALERT_DELETE}{alert_id}"),
    ]])


def build_ghost_notification_keyboard(
    alert: dict,
    occurrence_time,
    scheduled_time,
) -> InlineKeyboardMarkup:
    """Build the ghost-alert notification keyboard with noted/postpone/detail/delete actions."""
    if not alert:
        return None
    alert_id = (alert.get("id") or "unknown")[:8]
    scheduled_time = scheduled_time or occurrence_time
    occurrence_time = occurrence_time or scheduled_time
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Noted", callback_data=f"ghost_noted_{alert_id}"),
            InlineKeyboardButton(
                "⏰ Postpone",
                callback_data=build_postpone_callback(
                    "menu", "due", alert_id, scheduled_time, occurrence_time, 0
                ),
            ),
        ],
        [
            InlineKeyboardButton("ℹ️ Detail info", callback_data=f"ghost_dtl_{alert_id}"),
            InlineKeyboardButton("👻🗑️ Delete", callback_data=f"ghost_del_{alert_id}"),
        ],
    ])
