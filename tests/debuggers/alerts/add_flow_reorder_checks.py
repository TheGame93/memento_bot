import asyncio
import types


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyMessage:
    def __init__(self, text=None, message_id=100):
        self.text = text
        self.message_id = message_id
        self.replies = []
        self.edits = []
        self.reply_markup = None

    async def reply_text(self, text, reply_markup=None, parse_mode=None):
        payload = {
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.replies.append(payload)
        self.reply_markup = reply_markup
        return self

    async def edit_text(self, text, reply_markup=None, parse_mode=None):
        payload = {
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.edits.append(payload)
        self.reply_markup = reply_markup
        return self


class _DummyCallbackQuery:
    def __init__(self, data, message):
        self.data = data
        self.message = message
        self.answers = []
        self.edits = []
        self.reply_markup_edits = []

    async def answer(self, text=None, show_alert=None):
        self.answers.append({
            "text": text,
            "show_alert": show_alert,
        })

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        payload = {
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.edits.append(payload)
        self.message.edits.append(payload)
        self.message.reply_markup = reply_markup
        return self.message

    async def edit_message_reply_markup(self, reply_markup=None):
        self.reply_markup_edits.append(reply_markup)
        self.message.reply_markup = reply_markup
        return self.message


class _DummyUpdate:
    def __init__(self, *, user_id=1001, message=None, callback_query=None):
        self.effective_user = _DummyUser(user_id)
        self.message = message
        self.callback_query = callback_query
        self.effective_message = message or getattr(callback_query, "message", None)
        self.effective_chat = types.SimpleNamespace(id=user_id)


class _DummyContext:
    def __init__(self, user_data=None):
        self.user_data = dict(user_data or {})


def _extract_callback_rows(reply_markup):
    rows = []
    if not reply_markup:
        return rows
    for row in getattr(reply_markup, "inline_keyboard", []) or []:
        rows.append([getattr(button, "callback_data", None) for button in row])
    return rows


def run_constants_checks(constants_mod):
    names = ["CHANGE_ALERT_TYPE", "EDIT_DASHBOARD", "EDIT_NAME"]
    values = {}
    for name in names:
        values[name] = getattr(constants_mod, name, None)

    checks = {
        "change_alert_type_defined": isinstance(values["CHANGE_ALERT_TYPE"], int),
        "edit_dashboard_defined": isinstance(values["EDIT_DASHBOARD"], int),
        "edit_name_defined": isinstance(values["EDIT_NAME"], int),
        "values_are_unique": len(set(values.values())) == len(names),
    }
    return {
        "values": values,
        "checks": checks,
    }


def run_settings_change_type_button_checks(settings_flow_mod, constants_mod):
    context = _DummyContext(user_data={
        "temp_alert": {
            "title": "Weekly sync",
            "type": 3,
            "type_name": constants_mod.ALERT_TYPES.get(3),
            "schedule": {"weekdays": ["Mon"], "interval": 1, "time": "09:00"},
            "pre_alerts": [],
            "tags": [],
            "additional_info": "",
            "image_id": None,
            "local_image_path": None,
        },
    })
    message = _DummyMessage(message_id=401)
    query = _DummyCallbackQuery("ms_open", message)
    update = _DummyUpdate(user_id=42, callback_query=query)

    state = asyncio.run(settings_flow_mod.show_multi_setting_menu(update, context))
    last_edit = query.edits[-1] if query.edits else {}
    callback_rows = _extract_callback_rows(last_edit.get("reply_markup"))
    first_row = callback_rows[0] if callback_rows else []

    checks = {
        "state_multi_settings": state == constants_mod.MULTI_SETTINGS,
        "settings_return_alert": context.user_data.get("settings_return") == "alert",
        "first_row_is_change_type": first_row == ["ms_change_type"],
    }
    return {
        "state": state,
        "callback_rows": callback_rows,
        "checks": checks,
    }


def run_change_type_keyboard_contract_checks(keyboards_mod):
    markup = keyboards_mod.build_change_type_keyboard()
    rows = _extract_callback_rows(markup)
    callbacks = [cb for row in rows for cb in row if isinstance(cb, str)]

    expected_type_callbacks = {"ct_1", "ct_2", "ct_3", "ct_4", "ct_5", "ct_7"}
    present_type_callbacks = {cb for cb in callbacks if cb.startswith("ct_") and cb != "ct_back"}

    checks = {
        "has_back": "ct_back" in callbacks,
        "birthday_excluded": "ct_6" not in callbacks,
        "empty_excluded": "ct_8" not in callbacks,
        "expected_type_callbacks_present": expected_type_callbacks.issubset(present_type_callbacks),
        "all_type_callbacks_use_ct_prefix": all(cb.startswith("ct_") for cb in present_type_callbacks),
    }
    return {
        "rows": rows,
        "callbacks": sorted(callbacks),
        "checks": checks,
    }


def run_change_type_schedule_clearing_checks(settings_flow_mod, constants_mod):
    temp_alert = {
        "type": 3,
        "type_name": constants_mod.ALERT_TYPES.get(3),
        "schedule": {
            "days": [1, 15],
            "ordinals": ["1st"],
            "weekdays": ["Mon"],
            "fifth_policy": "skip",
            "dates": "01/01",
            "date": "10/10/2026",
            "interval": 2,
            "start_marker": "20/03/2026",
            "time": "09:30",
        },
        "tags": ["💼 Work"],
        "pre_alerts": ["1d"],
    }
    context = _DummyContext(user_data={"temp_alert": temp_alert, "temp_selection": ["Mon"]})
    message = _DummyMessage(message_id=402)
    query = _DummyCallbackQuery("ct_4", message)
    update = _DummyUpdate(user_id=42, callback_query=query)

    call_meta = {"return_calls": 0, "prompt_calls": 0}

    async def _return_fn(_update, _context):
        call_meta["return_calls"] += 1
        return constants_mod.MULTI_SETTINGS

    async def _prompt_fn(_update, _context):
        call_meta["prompt_calls"] += 1
        return constants_mod.TYPE_4_DATES

    state = asyncio.run(
        settings_flow_mod._change_type_callback_impl(
            update,
            context,
            _return_fn,
            _prompt_fn,
        )
    )

    schedule = context.user_data.get("temp_alert", {}).get("schedule", {}) or {}
    cleared_keys = ("days", "ordinals", "weekdays", "fifth_policy", "dates", "date", "interval", "start_marker")
    checks = {
        "state_from_prompt_fn": state == constants_mod.TYPE_4_DATES,
        "callback_answered_once": len(query.answers) == 1,
        "prompt_called_once": call_meta["prompt_calls"] == 1,
        "return_not_called": call_meta["return_calls"] == 0,
        "keys_cleared": all(key not in schedule for key in cleared_keys),
        "time_preserved": schedule.get("time") == "09:30",
        "type_updated": context.user_data.get("temp_alert", {}).get("type") == 4,
        "temp_selection_reset": context.user_data.get("temp_selection") == [],
    }
    return {
        "state": state,
        "schedule_after": schedule,
        "type_after": context.user_data.get("temp_alert", {}).get("type"),
        "call_meta": call_meta,
        "checks": checks,
    }


def run_change_type_invalid_type_checks(settings_flow_mod, constants_mod):
    temp_alert = {
        "type": 3,
        "type_name": constants_mod.ALERT_TYPES.get(3),
        "schedule": {
            "weekdays": ["Mon"],
            "interval": 1,
            "time": "09:30",
        },
        "tags": [],
        "pre_alerts": [],
    }
    context = _DummyContext(user_data={"temp_alert": temp_alert, "temp_selection": ["Mon"]})
    message = _DummyMessage(message_id=404)
    query = _DummyCallbackQuery("ct_6", message)
    update = _DummyUpdate(user_id=42, callback_query=query)

    call_meta = {"return_calls": 0, "prompt_calls": 0}

    async def _return_fn(_update, _context):
        call_meta["return_calls"] += 1
        return constants_mod.MULTI_SETTINGS

    async def _prompt_fn(_update, _context):
        call_meta["prompt_calls"] += 1
        return constants_mod.TYPE_1_DAYS

    state = asyncio.run(
        settings_flow_mod._change_type_callback_impl(
            update,
            context,
            _return_fn,
            _prompt_fn,
        )
    )

    answers = list(query.answers)
    schedule = context.user_data.get("temp_alert", {}).get("schedule", {}) or {}
    checks = {
        "state_stays_in_change_type": state == constants_mod.CHANGE_ALERT_TYPE,
        "callback_answered_once": len(answers) == 1,
        "answer_is_alert": bool(answers and answers[0].get("show_alert")),
        "prompt_not_called": call_meta["prompt_calls"] == 0,
        "return_not_called": call_meta["return_calls"] == 0,
        "type_not_changed": context.user_data.get("temp_alert", {}).get("type") == 3,
        "temp_selection_unchanged": context.user_data.get("temp_selection") == ["Mon"],
        "schedule_unchanged": schedule.get("weekdays") == ["Mon"] and schedule.get("time") == "09:30",
    }
    return {
        "state": state,
        "answers": answers,
        "type_after": context.user_data.get("temp_alert", {}).get("type"),
        "schedule_after": schedule,
        "call_meta": call_meta,
        "checks": checks,
    }


def run_prompt_type_specific_callback_context_checks(flow_start_mod, constants_mod):
    context = _DummyContext(user_data={
        "temp_alert": {
            "type": 1,
            "type_name": constants_mod.ALERT_TYPES.get(1),
            "schedule": {},
            "pre_alerts": [],
            "tags": [],
        },
    })
    message = _DummyMessage(message_id=403)
    query = _DummyCallbackQuery("type_1", message)
    update = _DummyUpdate(user_id=77, callback_query=query)

    error = None
    state = None
    try:
        state = asyncio.run(flow_start_mod.prompt_type_specific(update, context))
    except Exception as exc:
        error = repr(exc)

    checks = {
        "no_exception": error is None,
        "state_type_1_days": state == constants_mod.TYPE_1_DAYS,
        "edited_once": len(query.edits) == 1,
        "message_context_absent": update.message is None,
    }
    return {
        "state": state,
        "error": error,
        "edit_count": len(query.edits),
        "checks": checks,
    }


def run_prompt_type_specific_daily_callback_context_checks(flow_start_mod, constants_mod):
    context = _DummyContext(user_data={
        "temp_alert": {
            "type": 7,
            "type_name": constants_mod.ALERT_TYPES.get(7),
            "schedule": {},
            "pre_alerts": [],
            "tags": [],
        },
    })
    message = _DummyMessage(message_id=405)
    query = _DummyCallbackQuery("ct_7", message)
    update = _DummyUpdate(user_id=77, callback_query=query)

    error = None
    state = None
    try:
        state = asyncio.run(flow_start_mod.prompt_type_specific(update, context, get_interval_prompt=None))
    except Exception as exc:
        error = repr(exc)

    last_edit = query.edits[-1] if query.edits else {}
    text = last_edit.get("text") or ""
    checks = {
        "no_exception": error is None,
        "state_get_interval": state == constants_mod.GET_INTERVAL,
        "edited_once": len(query.edits) == 1,
        "daily_prompt_present": "How many days between occurrences?" in text,
    }
    return {
        "state": state,
        "error": error,
        "edit_count": len(query.edits),
        "text": text,
        "checks": checks,
    }
