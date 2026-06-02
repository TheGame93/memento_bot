"""
detail_kb.py — Context-aware detail card keyboard builder.

Provides a single build_detail_keyboard() entry point that returns the correct
keyboard depending on whether the detail card was opened from a notification
(Variant A) or from the alert list (Variant B).

Variant A (from_notification=True):
    Row 1: [👀 NOTED]       — pnote_ (kind='pre'), pdone_ (due non-birthday),
                               bnote_ (due birthday)
    Row 2: [⏰ POSTPONE]     — pp_menu_{kind}_ callback
    Row 3: [🔄 SNOOZE | 🟢 ACTIVATE]  (hidden for type 5); alerttoggle_ prefix
    Row 4: [🗑️ DELETE]       — alertdel_ prefix (notification-origin handlers)
    Row 5: [✏️ Edit fields]  — manage_fulledit_{alert_id}
    Row 6: [⬅️ Back]         — nback_ callback (when include_back=True)

Variant B (from_notification=False):
    Row 1: [🔄 SNOOZE | 🟢 ACTIVATE]  (hidden for type 5); manage_toggle_ prefix
    Row 2: [🗑️ DELETE]       — manage_del_ prefix (list-origin handlers)
    Row 3: [✏️ Edit fields]  — manage_fulledit_{alert_id}
    Row 4: [⬅️ Back (<tag>)] — manage_backtolist callback (when include_back=True)

The SNOOZE/DELETE callback prefix differs between variants so that the correct
origin-specific handler is dispatched by the Telegram router.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from modules import constants as C
from modules.ui.keyboards.callbacks import (
    build_bday_noted_callback,
    build_notif_back_callback,
    build_placebo_noted_callback,
    build_postpone_callback,
    ts,
)
from modules.ui.keyboards.notification_kb import (
    ACTION_LABEL_ACTIVATE,
    ACTION_LABEL_DELETE,
    ACTION_LABEL_NOTED,
    ACTION_LABEL_POSTPONE,
    ACTION_LABEL_SNOOZE,
    get_toggle_action_label,
)

_EDIT_LABEL = "✏️ Edit fields"
_BACK_LABEL = "⬅️ Back"


def _noted_button(
    alert: dict,
    kind: str,
    original_time,
    occurrence_time,
) -> InlineKeyboardButton:
    """Return the NOTED button for the detail card, choosing the correct callback prefix.

    kind='pre' → pnote_; kind='due' + type==6 → bnote_; kind='due' otherwise → pdone_.
    """
    alert_id = alert.get("id", "unknown")
    if kind == "pre":
        cb = build_placebo_noted_callback(alert_id, original_time, occurrence_time)
    elif alert.get("type") == 6:
        cb = build_bday_noted_callback(alert_id, original_time, occurrence_time)
    else:
        cb = f"{C.CB_PLACEBO_DONE}{alert_id}_{ts(original_time)}_{ts(occurrence_time)}"
    return InlineKeyboardButton(ACTION_LABEL_NOTED, callback_data=cb)


def build_detail_keyboard(
    alert: dict,
    *,
    source: str = "alerts",
    from_notification: bool = False,
    kind: str = "due",
    occurrence_time=None,
    original_time=None,
    postpone_count: int = 0,
    include_back: bool = True,
    tag_filter: str = "ALL",
) -> InlineKeyboardMarkup:
    """Build the detail card keyboard with context-sensitive rows.

    When from_notification=True, prepends NOTED and POSTPONE rows and uses
    nback_ for the Back button. When from_notification=False, omits those
    rows and uses manage_backtolist for Back. The 'Edit fields' button always
    maps to manage_fulledit_{alert_id}. SNOOZE is hidden for type 5 regardless
    of origin.

    tag_filter must be resolved by the caller before calling this function.
    Step 11b's build_info_keyboard wrapper handles this for the from-list path.
    """
    alert_id = alert.get("id", "unknown")
    original_time = original_time or occurrence_time
    occurrence_time = occurrence_time or original_time

    keyboard = []

    if from_notification:
        # Variant A: prepend NOTED + POSTPONE rows
        keyboard.append([_noted_button(alert, kind, original_time, occurrence_time)])
        keyboard.append([InlineKeyboardButton(
            ACTION_LABEL_POSTPONE,
            callback_data=build_postpone_callback(
                "menu", kind, alert_id, original_time, occurrence_time, postpone_count
            ),
        )])

    # SNOOZE / ACTIVATE — hidden for type 5 in both variants
    if alert.get("type") != 5:
        toggle_cb = (
            f"{C.CB_ALERT_TOGGLE}{alert_id}"
            if from_notification
            else f"manage_toggle_{alert_id}"
        )
        keyboard.append([InlineKeyboardButton(get_toggle_action_label(alert), callback_data=toggle_cb)])

    # DELETE — different prefix depending on origin so the right handler fires
    delete_cb = (
        f"{C.CB_ALERT_DELETE}{alert_id}"
        if from_notification
        else f"manage_del_{alert_id}"
    )
    keyboard.append([InlineKeyboardButton(ACTION_LABEL_DELETE, callback_data=delete_cb)])

    # Edit fields — always manage_fulledit_ (registered in edit_flow/flow.py)
    keyboard.append([InlineKeyboardButton(
        _EDIT_LABEL,
        callback_data=f"manage_fulledit_{alert_id}",
    )])

    # Back button
    if include_back:
        if from_notification:
            back_cb = build_notif_back_callback(
                kind, alert_id, original_time, occurrence_time, postpone_count
            )
            keyboard.append([InlineKeyboardButton(_BACK_LABEL, callback_data=back_cb)])
        else:
            back_label = (
                _BACK_LABEL if tag_filter == "ALL" else f"{_BACK_LABEL} ({tag_filter})"
            )
            keyboard.append([InlineKeyboardButton(back_label, callback_data="manage_backtolist")])

    return InlineKeyboardMarkup(keyboard)
