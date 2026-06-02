from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from modules import constants as C


def build_toggle_keyboard(items, selected_items, callback_prefix, cols=2):
    """Build a toggle-style inline keyboard with a DONE action."""
    keyboard = []
    row = []
    for item in items:
        label = f"{item} ✅" if item in selected_items else item
        data = f"{callback_prefix}{item}"
        row.append(InlineKeyboardButton(label, callback_data=data))
        if len(row) == cols:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("DONE", callback_data=f"{callback_prefix}DONE")])
    return InlineKeyboardMarkup(keyboard)


def build_type_keyboard():
    """Build the add-flow alert-type picker keyboard."""
    def _build_type_button(type_id, label):
        name = C.ALERT_TYPES.get(type_id)
        if not isinstance(name, str) or "Empty" in name:
            return None
        return InlineKeyboardButton(label, callback_data=f"{C.CB_TYPE}{type_id}")

    keyboard = []

    row_daily_weekly = []
    daily_btn = _build_type_button(7, "Daily")
    weekly_btn = _build_type_button(3, "Weekly")
    if daily_btn:
        row_daily_weekly.append(daily_btn)
    if weekly_btn:
        row_daily_weekly.append(weekly_btn)
    if row_daily_weekly:
        keyboard.append(row_daily_weekly)

    monthly_specific_btn = _build_type_button(1, "Monthly (Specific Day)")
    if monthly_specific_btn:
        keyboard.append([monthly_specific_btn])

    monthly_relative_btn = _build_type_button(2, "Monthly (Relative Day)")
    if monthly_relative_btn:
        keyboard.append([monthly_relative_btn])

    row_yearly_one_time = []
    yearly_btn = _build_type_button(4, "Yearly")
    one_time_btn = _build_type_button(5, "One Time")
    if yearly_btn:
        row_yearly_one_time.append(yearly_btn)
    if one_time_btn:
        row_yearly_one_time.append(one_time_btn)
    if row_yearly_one_time:
        keyboard.append(row_yearly_one_time)

    return InlineKeyboardMarkup(keyboard)


def build_change_type_keyboard():
    """Build the change-type keyboard excluding unsupported alert types."""
    def _build_change_type_button(type_id, label):
        name = C.ALERT_TYPES.get(type_id)
        if not isinstance(name, str):
            return None
        if type_id in {6, 8}:
            return None
        if "Empty" in name:
            return None
        return InlineKeyboardButton(label, callback_data=f"ct_{type_id}")

    keyboard = []

    row_daily_weekly = []
    daily_btn = _build_change_type_button(7, "Daily")
    weekly_btn = _build_change_type_button(3, "Weekly")
    if daily_btn:
        row_daily_weekly.append(daily_btn)
    if weekly_btn:
        row_daily_weekly.append(weekly_btn)
    if row_daily_weekly:
        keyboard.append(row_daily_weekly)

    monthly_specific_btn = _build_change_type_button(1, "Monthly (Specific Day)")
    if monthly_specific_btn:
        keyboard.append([monthly_specific_btn])

    monthly_relative_btn = _build_change_type_button(2, "Monthly (Relative Day)")
    if monthly_relative_btn:
        keyboard.append([monthly_relative_btn])

    row_yearly_one_time = []
    yearly_btn = _build_change_type_button(4, "Yearly")
    one_time_btn = _build_change_type_button(5, "One Time")
    if yearly_btn:
        row_yearly_one_time.append(yearly_btn)
    if one_time_btn:
        row_yearly_one_time.append(one_time_btn)
    if row_yearly_one_time:
        keyboard.append(row_yearly_one_time)

    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="ct_back")])
    return InlineKeyboardMarkup(keyboard)
