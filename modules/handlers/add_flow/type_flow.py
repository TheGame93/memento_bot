from datetime import datetime, timedelta
import re

from dateutil.relativedelta import relativedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from modules import constants as C
from modules.handlers.add_flow.keyboards import build_toggle_keyboard
from modules.handlers.add_flow.validators import merge_pre_alerts, parse_custom_pre_alerts
from modules.scheduler_mathlogic import resolve_pre_alert_fire_time
from modules.shared.acting_as import get_target_user_id, build_acting_as_payload
from modules.shared.logging_utils import text_meta
from modules.shared.markdown_utils import md_escape
from modules.shared.messages import edit_callback_message_media_aware as _edit_callback_message
from modules.shared.runtime_context import get_runtime_storage
from modules.timezone_utils import (
    compute_next_occurrence,
    normalize_one_time_date,
    now_server_naive,
    parse_user_datetime_expression,
    resolve_fuzzy_next_scheduled,
    resolve_user_timezone,
    to_server_naive_from_user,
    to_user_naive_from_server,
)
from modules.handlers.base import _birthday_default_time_from_prefs


def _parse_yearly_dates_tokens(raw_dates):
    if isinstance(raw_dates, str):
        parts = [x.strip() for x in raw_dates.split(",")]
    elif isinstance(raw_dates, (list, tuple, set)):
        parts = [str(x).strip() for x in raw_dates]
    else:
        return []

    parsed = []
    for token in parts:
        if not token:
            continue
        try:
            dt = datetime.strptime(token + "/2024", "%d/%m/%Y")
            parsed.append((dt.day, dt.month))
        except ValueError:
            continue
    return sorted(set(parsed), key=lambda item: (item[1], item[0]))


def _suggest_next_yearly_date(now, raw_dates):
    date_pairs = _parse_yearly_dates_tokens(raw_dates)
    if not date_pairs:
        return now + timedelta(days=1)

    candidates = []
    for year in (now.year, now.year + 1, now.year + 2):
        for day, month in date_pairs:
            cand_day = day
            if day == 29 and month == 2:
                try:
                    datetime(year, 2, 29)
                except ValueError:
                    cand_day = 28
            try:
                candidate = datetime(year, month, cand_day, now.hour, now.minute, 0, 0)
            except ValueError:
                continue
            if candidate > now:
                candidates.append(candidate)

    if not candidates:
        return now + timedelta(days=1)
    return min(candidates)


async def ask_time(update, context):
    """Prompt for reminder time with a default-time shortcut button."""
    text = "⏰ **Set Time**\nEnter HH:MM or click default:"
    buttons = [[InlineKeyboardButton("Use Default (10:00)", callback_data="time_default")]]

    if update.callback_query:
        await _edit_callback_message(
            update.callback_query,
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.MARKDOWN,
        )
    return C.GET_TIME


def calculate_suggested_start(data):
    """Return a suggested first-occurrence datetime from the draft schedule."""
    now = datetime.now()
    alert_type = data.get("type")
    schedule = data.get("schedule", {})

    try:
        if alert_type == 1:
            day = schedule.get("days", [1])[0]
            target = now.replace(day=day)
            if target <= now:
                target += relativedelta(months=1)
            return target

        if alert_type == 3:
            return now + timedelta(days=(7 - now.weekday()))

        if alert_type == 4:
            return _suggest_next_yearly_date(now, schedule.get("dates"))

        return now + timedelta(days=1)
    except Exception:
        return now + timedelta(days=1)


async def type_1_days(update, context, show_multi_setting_menu):
    """Validate monthly day-of-month input and store it in the draft schedule."""
    text = update.message.text
    try:
        days = [int(x.strip()) for x in text.split(",") if x.strip().isdigit()]
        if not days or any(d < 1 or d > 31 for d in days):
            raise ValueError
        context.user_data["temp_alert"]["schedule"]["days"] = days
        return await show_multi_setting_menu(update, context)
    except ValueError:
        await update.message.reply_text(
            "❌ **Invalid.** Enter numbers 1-31 (e.g. `1, 15`):",
            parse_mode=ParseMode.MARKDOWN,
        )
        return C.TYPE_1_DAYS


async def type_4_dates(update, context, show_multi_setting_menu):
    """Validate yearly day/month tokens and store them in the draft schedule."""
    text = update.message.text
    try:
        parts = [x.strip() for x in text.split(",")]
        for token in parts:
            datetime.strptime(token + "/2024", "%d/%m/%Y")
        context.user_data["temp_alert"]["schedule"]["dates"] = text
        return await show_multi_setting_menu(update, context)
    except ValueError:
        await update.message.reply_text(
            "❌ **Invalid.** Use format DD/MM (e.g. `25/12`):",
            parse_mode=ParseMode.MARKDOWN,
        )
        return C.TYPE_4_DATES


def _resolve_one_time_today_reference(reference_server_dt, user_prefs):
    if not isinstance(user_prefs, dict):
        return reference_server_dt
    mode = user_prefs.get("timezone_mode") or C.TIMEZONE_DEFAULT_MODE
    if mode != C.TIMEZONE_MODE_USER:
        return reference_server_dt
    try:
        user_tz = resolve_user_timezone(user_prefs)
        return to_user_naive_from_server(reference_server_dt, user_tz)
    except Exception:
        return reference_server_dt


def _build_one_time_today_examples(reference_server_dt, user_prefs):
    today_ref = _resolve_one_time_today_reference(reference_server_dt, user_prefs)
    return today_ref.strftime("%d/%m/%y"), today_ref.strftime("%d/%m/%Y")


def _one_time_source_label(context):
    settings_return = None
    if context is not None:
        user_data = getattr(context, "user_data", None)
        if isinstance(user_data, dict):
            settings_return = user_data.get("settings_return")
    if isinstance(settings_return, str) and settings_return.strip().lower() == "edit":
        return "edit_flow"
    return "add_flow"


async def type_5_date(update, context, show_multi_setting_menu):
    """Normalize one-time date input, enforce same-day year disambiguation, and persist schedule date.
    
    Log year-assumption telemetry and same-day clarification prompts before returning to
    settings so one-time dates remain unambiguous across timezone modes.
    """
    text = (update.message.text or "").strip()
    storage = get_runtime_storage(context)
    user_id = get_target_user_id(update, context)
    user_prefs = storage.get_user_prefs(user_id) if user_id is not None else None
    time_str = (context.user_data.get("temp_alert", {}).get("schedule", {}) or {}).get("time")
    reference_server_dt = now_server_naive()
    status, normalized, assumed, reason = normalize_one_time_date(
        text,
        reference_server_dt=reference_server_dt,
        user_prefs=user_prefs,
        require_year_if_today=True,
        time_str=time_str,
    )
    source_label = _one_time_source_label(context)
    if status == "needs_year":
        short_example, full_example = _build_one_time_today_examples(reference_server_dt, user_prefs)
        payload = {
            "source": source_label,
            "today_short_example": short_example,
            "today_full_example": full_example,
        }
        payload.update(build_acting_as_payload(update, context))
        storage.log_user_event(user_id, "one_time_today_year_required_prompt", payload)
        await update.message.reply_text(
            "⚠️ **This date is today.** Please include the year to avoid ambiguity.\n"
            f"Use format `DD/MM/YY` or `DD/MM/YYYY` (e.g. `{short_example}` or `{full_example}`):",
            parse_mode=ParseMode.MARKDOWN,
        )
        return C.TYPE_5_DATE
    if status != "ok" or not normalized:
        await update.message.reply_text(
            "❌ **Invalid.** Use format DD/MM, DD/MM/YY or DD/MM/YYYY:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return C.TYPE_5_DATE
    context.user_data["temp_alert"]["schedule"]["date"] = normalized
    if assumed:
        assumption_kind = reason if reason in {"missing_year", "two_digit_year"} else "missing_year"
        payload = {
            "source": source_label,
            "date_meta": text_meta(text),
            "assumed_year": int(normalized.split("/")[-1]),
            "assumption_kind": assumption_kind,
        }
        payload.update(build_acting_as_payload(update, context))
        storage.log_user_event(user_id, "one_time_year_assumed", payload)
    return await show_multi_setting_menu(update, context)


async def type_6_date(update, context, show_tags_menu):
    """Validate birthday date input and apply the default birthday reminder time."""
    text = update.message.text.strip()
    try:
        datetime.strptime(text + "/2024", "%d/%m/%Y")
        storage = get_runtime_storage(context)
        user_id = get_target_user_id(update, context)
        default_time = _birthday_default_time_from_prefs(storage.get_user_prefs(user_id))
        context.user_data["temp_alert"]["schedule"]["date"] = text
        context.user_data["temp_alert"]["schedule"]["time"] = default_time
        return await show_tags_menu(update, context)
    except ValueError:
        await update.message.reply_text(
            "❌ **Invalid.** Use format DD/MM (e.g. `25/12`):",
            parse_mode=ParseMode.MARKDOWN,
        )
        return C.TYPE_6_DATE


async def toggle_handler(
    update,
    context,
    data_list,
    cb_prefix,
    next_state,
    next_msg,
    *,
    next_kb_func=None,
    next_func=None,
    get_interval_prompt=None,
):
    """Handle toggle keyboard interactions and persist selections on DONE."""
    query = update.callback_query
    await query.answer()
    data = query.data.replace(cb_prefix, "")
    current = context.user_data.get("temp_selection", [])

    if data == "DONE":
        if not current:
            await query.answer("⚠️ Select at least one option!", show_alert=True)
            return None

        if cb_prefix == C.CB_ORDINAL:
            context.user_data["temp_alert"]["schedule"]["ordinals"] = current
        elif cb_prefix == C.CB_WEEKDAY:
            context.user_data["temp_alert"]["schedule"]["weekdays"] = current
        elif cb_prefix == C.CB_TAG:
            context.user_data["temp_alert"]["tags"] = current

        context.user_data["temp_selection"] = []

        if next_func:
            return await next_func(update, context)
        if next_kb_func:
            await _edit_callback_message(
                query,
                next_msg,
                reply_markup=next_kb_func(),
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            if next_state == C.GET_INTERVAL and get_interval_prompt is not None:
                return await get_interval_prompt(update, context)
            await _edit_callback_message(query, next_msg, parse_mode=ParseMode.MARKDOWN)
        return next_state

    if data in current:
        current.remove(data)
    else:
        current.append(data)
    context.user_data["temp_selection"] = current
    await query.edit_message_reply_markup(
        reply_markup=build_toggle_keyboard(data_list, current, cb_prefix)
    )
    return None


async def type_2_ordinal(update, context, get_interval_prompt):
    """Handle relative-month ordinal selection before weekday selection."""
    query = update.callback_query
    data = query.data.replace(C.CB_ORDINAL, "")

    # If DONE is pressed, check if "5th" was selected before proceeding.
    if data == "DONE":
        current = context.user_data.get("temp_selection", [])
        if not current:
            await query.answer("⚠️ Select at least one option!", show_alert=True)
            return C.TYPE_2_ORDINAL
        context.user_data["temp_alert"]["schedule"]["ordinals"] = current
        context.user_data["temp_selection"] = []

        if "5th" in current:
            return await _show_fifth_policy_menu(update, context)

        # No "5th" selected — go straight to weekday selection.
        await query.answer()
        await _edit_callback_message(
            query,
            "📅 Select **Weekdays**:",
            reply_markup=build_toggle_keyboard(C.WEEKDAYS, [], C.CB_WEEKDAY),
            parse_mode="Markdown",
        )
        return C.TYPE_2_WEEKDAY

    # Toggle selection (not DONE).
    return await toggle_handler(
        update,
        context,
        C.ORDINALS,
        C.CB_ORDINAL,
        C.TYPE_2_WEEKDAY,
        "📅 Select **Weekdays**:",
        next_kb_func=lambda: build_toggle_keyboard(C.WEEKDAYS, [], C.CB_WEEKDAY),
        get_interval_prompt=get_interval_prompt,
    ) or C.TYPE_2_ORDINAL


async def _show_fifth_policy_menu(update, context):
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭️ Skip that month", callback_data=f"{C.CB_FIFTH_POLICY}skip")],
        [InlineKeyboardButton("📅 Alert on the 4th instead", callback_data=f"{C.CB_FIFTH_POLICY}fallback_4th")],
    ])
    await _edit_callback_message(
        query,
        "⚠️ **5th occurrence warning**\n\n"
        "Some months don't have a 5th occurrence of a weekday.\n"
        "What should the bot do in those months?",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )
    return C.TYPE_2_FIFTH_POLICY


async def type_2_fifth_policy(update, context):
    """Store the fifth-occurrence fallback policy and continue weekday selection."""
    query = update.callback_query
    await query.answer()
    data = query.data.replace(C.CB_FIFTH_POLICY, "")
    if data not in ("skip", "fallback_4th"):
        return C.TYPE_2_FIFTH_POLICY
    context.user_data["temp_alert"]["schedule"]["fifth_policy"] = data
    await _edit_callback_message(
        query,
        "📅 Select **Weekdays**:",
        reply_markup=build_toggle_keyboard(C.WEEKDAYS, [], C.CB_WEEKDAY),
        parse_mode="Markdown",
    )
    return C.TYPE_2_WEEKDAY


async def type_2_weekday(update, context, show_multi_setting_menu):
    """Handle relative-month weekday selection and continue to settings."""
    return await toggle_handler(
        update,
        context,
        C.WEEKDAYS,
        C.CB_WEEKDAY,
        C.GET_TAGS,
        "",
        next_func=show_multi_setting_menu,
    ) or C.TYPE_2_WEEKDAY


async def type_3_weekdays(update, context, show_multi_setting_menu):
    """Handle weekly weekday selection and continue to settings."""
    return await toggle_handler(
        update,
        context,
        C.WEEKDAYS,
        C.CB_WEEKDAY,
        C.GET_TAGS,
        "",
        next_func=show_multi_setting_menu,
    ) or C.TYPE_3_WEEKDAYS


def _is_daily_alert(context):
    temp_alert = context.user_data.get("temp_alert", {}) or {}
    return temp_alert.get("type") == 7


def _daily_interval_confirm_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ I'm sure", callback_data="dint1_yes"),
        InlineKeyboardButton("✏️ Change interval", callback_data="dint1_change"),
    ]])


def _daily_interval_confirm_text():
    return (
        "⚠️ **Daily interval confirmation**\n"
        "Are you sure? Wouldn't you prefer using the phone alarm clock?"
    )


def _daily_interval_prompt_source(update, context):
    if context.user_data.get("settings_return") == "alert":
        return "alert_settings"
    if update and update.callback_query and update.callback_query.data == "dint1_change":
        return "daily_interval_change"
    return "initial_daily_flow"


def _daily_interval_mode_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Fixed interval", callback_data=C.CB_INTERVAL_FIXED)],
        [InlineKeyboardButton("Fuzzy interval", callback_data=C.CB_INTERVAL_FUZZY)],
    ])


def _daily_interval_mode_prompt_text():
    return (
        "🔁 **Daily interval mode**\n"
        "Choose how daily spacing should work:\n"
        "• **Fixed**: exact day interval (e.g. every 2 days)\n"
        "• **Fuzzy**: Gaussian interval (mean ± std days)"
    )


def _daily_fixed_interval_prompt_text():
    return "🔁 **Interval**\nHow many days between occurrences?\nEnter a number:"


def _normalize_schedule_time_or_default(schedule):
    raw = (schedule or {}).get("time") or "10:00"
    try:
        parsed = datetime.strptime(str(raw), "%H:%M")
        return parsed.hour, parsed.minute
    except Exception:
        return 10, 0


def _get_user_prefs_for_daily_flow(update, context):
    try:
        storage = get_runtime_storage(context)

        user_id = get_target_user_id(update, context)
        if user_id is None or not hasattr(storage, "get_user_prefs"):
            return {}
        prefs = storage.get_user_prefs(user_id)
        return prefs if isinstance(prefs, dict) else {}
    except Exception:
        return {}


def _parse_fuzzy_mean_std(raw_text):
    text = (raw_text or "").strip()
    pattern = r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*(?:[/:\-]|\s)\s*([0-9]+(?:[.,][0-9]+)?)\s*$"
    match = re.match(pattern, text)
    if not match:
        return None, None, "invalid_format"
    try:
        mean_val = float(match.group(1).replace(",", "."))
        std_val = float(match.group(2).replace(",", "."))
    except Exception:
        return None, None, "invalid_number"
    if mean_val <= 0:
        return None, None, "mean_non_positive"
    if std_val < 0:
        return None, None, "std_negative"
    return mean_val, std_val, None


def _is_daily_fuzzy_mode(context):
    if not _is_daily_alert(context):
        return False
    schedule = context.user_data.get("temp_alert", {}).get("schedule", {})
    return (schedule or {}).get("interval_mode") == "fuzzy"


def _adjust_fuzzy_draft_next_scheduled_time(temp_alert, user_prefs):
    if not isinstance(temp_alert, dict):
        return False
    schedule = temp_alert.get("schedule")
    if not isinstance(schedule, dict):
        return False
    raw_next = temp_alert.get("next_scheduled")
    if not isinstance(raw_next, str) or not raw_next.strip():
        return False
    try:
        current_next = datetime.fromisoformat(raw_next)
    except Exception:
        return False
    if current_next.tzinfo is not None:
        current_next = current_next.astimezone().replace(tzinfo=None)

    hour, minute = _normalize_schedule_time_or_default(schedule)
    mode = None
    if isinstance(user_prefs, dict):
        mode = user_prefs.get("timezone_mode") or C.TIMEZONE_DEFAULT_MODE

    now_server = now_server_naive()
    if mode == C.TIMEZONE_MODE_USER:
        try:
            user_tz = resolve_user_timezone(user_prefs)
            local_next = to_user_naive_from_server(current_next, user_tz)
            local_now = to_user_naive_from_server(now_server, user_tz)
            adjusted_local = local_next.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if adjusted_local <= local_now:
                adjusted_local += timedelta(days=1)
            adjusted_server, _shifted = to_server_naive_from_user(adjusted_local, user_tz)
            temp_alert["next_scheduled"] = adjusted_server.isoformat()
            return True
        except Exception:
            return False

    adjusted_server = current_next.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if adjusted_server <= now_server:
        adjusted_server += timedelta(days=1)
    temp_alert["next_scheduled"] = adjusted_server.isoformat()
    return True


def _log_daily_interval_event(update, context, event_type, payload=None):
    if not _is_daily_alert(context):
        return
    try:
        storage = get_runtime_storage(context)
        user_id = get_target_user_id(update, context)
        event_payload = {}
        if isinstance(payload, dict):
            event_payload.update(payload)
        event_payload.update(build_acting_as_payload(update, context))
        storage.log_user_event(user_id, event_type, event_payload)
    except Exception:
        pass


async def _show_daily_interval_confirm(update, context, source):
    context.user_data["daily_interval_confirm_source"] = source
    _log_daily_interval_event(update, context, "daily_interval_one_confirm_shown", {
        "source": source,
    })
    text = _daily_interval_confirm_text()
    keyboard = _daily_interval_confirm_keyboard()
    if update.callback_query:
        await _edit_callback_message(
            update.callback_query,
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
    return C.DAILY_INTERVAL_CONFIRM


async def get_interval_prompt(update, context, show_multi_setting_menu):
    """Prompt for interval input and enforce daily-interval UX constraints."""
    alert_type = context.user_data["temp_alert"].get("type")
    if alert_type not in [1, 2, 3, 4, 7]:
        if update.callback_query:
            await update.callback_query.answer("Interval not applicable for this alert type.", show_alert=True)
        else:
            await update.message.reply_text("⚠️ Interval is not applicable for this alert type.")
        return await show_multi_setting_menu(update, context)

    if alert_type == 7:
        _log_daily_interval_event(update, context, "daily_interval_prompt_shown", {
            "source": _daily_interval_prompt_source(update, context),
            "step": "mode_choice",
        })
        text = _daily_interval_mode_prompt_text()
        keyboard = _daily_interval_mode_keyboard()
        if update.callback_query:
            await _edit_callback_message(
                update.callback_query,
                text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(
                text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN,
            )
        return C.FUZZY_INTERVAL_MODE_CHOICE

    if alert_type in [1, 2]:
        period = "month"
    elif alert_type == 3:
        period = "week"
    elif alert_type == 4:
        period = "year"
    else:
        period = "day"
    text = f"🔁 **Interval**\nHow many {period}s between occurrences?\nEnter a number or click below:"

    if update.callback_query:
        kwargs = {"text": text, "parse_mode": ParseMode.MARKDOWN}
        keyboard = [[InlineKeyboardButton(f"Each {period}", callback_data="int_1")]]
        kwargs["reply_markup"] = InlineKeyboardMarkup(keyboard)
        await _edit_callback_message(
            update.callback_query,
            kwargs.get("text", ""),
            reply_markup=kwargs.get("reply_markup"),
            parse_mode=kwargs.get("parse_mode"),
        )
    else:
        kwargs = {"text": text, "parse_mode": ParseMode.MARKDOWN}
        keyboard = [[InlineKeyboardButton(f"Each {period}", callback_data="int_1")]]
        kwargs["reply_markup"] = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(**kwargs)
    return C.GET_INTERVAL


async def interval_mode_choice_callback(update, context):
    """Handle daily fixed-vs-fuzzy mode selection and route to the next prompt."""
    query = update.callback_query
    data = (query.data or "").strip()
    temp_alert = context.user_data.get("temp_alert", {})
    schedule = temp_alert.setdefault("schedule", {})

    if data == C.CB_INTERVAL_FIXED:
        await query.answer()
        schedule["interval_mode"] = "fixed"
        schedule.pop("fuzzy_mean", None)
        schedule.pop("fuzzy_std", None)
        temp_alert.pop("next_scheduled", None)
        _log_daily_interval_event(update, context, "daily_interval_mode_selected", {
            "source": "mode_choice",
            "mode": "fixed",
        })
        await _edit_callback_message(
            query,
            _daily_fixed_interval_prompt_text(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return C.GET_INTERVAL

    if data == C.CB_INTERVAL_FUZZY:
        await query.answer()
        schedule["interval_mode"] = "fuzzy"
        if not schedule.get("interval"):
            schedule["interval"] = 1
        _log_daily_interval_event(update, context, "daily_interval_mode_selected", {
            "source": "mode_choice",
            "mode": "fuzzy",
        })
        await _edit_callback_message(
            query,
            "🎲 **Fuzzy daily interval**\n"
            "Send `mean std` (days).\n"
            "Accepted separators: space, `/`, `-`, `:`\n"
            "Examples: `20 3`, `20/3`, `20:3`, `20-3`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return C.FUZZY_MEAN_STD_INPUT

    await query.answer("Invalid mode selection.", show_alert=True)
    return C.FUZZY_INTERVAL_MODE_CHOICE


async def fuzzy_mean_std_input(update, context, show_multi_setting_menu):
    """Parse fuzzy daily mean/std, sample draft next occurrence, and return to settings."""
    raw_text = (update.message.text or "").strip()
    mean_val, std_val, reason = _parse_fuzzy_mean_std(raw_text)
    if reason is not None:
        _log_daily_interval_event(update, context, "daily_interval_fuzzy_input_invalid", {
            "source": "fuzzy_mean_std_input",
            "reason_code": reason,
            "input_meta": text_meta(raw_text),
        })
        await update.message.reply_text(
            "❌ Invalid format.\nUse `mean std` with mean > 0 and std >= 0.\n"
            "Examples: `20 3`, `20/3`, `20:3`, `20-3`."
        )
        return C.FUZZY_MEAN_STD_INPUT

    temp_alert = context.user_data.get("temp_alert", {})
    schedule = temp_alert.setdefault("schedule", {})
    schedule["interval_mode"] = "fuzzy"
    schedule["fuzzy_mean"] = mean_val
    schedule["fuzzy_std"] = std_val
    if not schedule.get("interval"):
        schedule["interval"] = 1

    user_prefs = _get_user_prefs_for_daily_flow(update, context)
    sampled_days, next_dt, shifted = resolve_fuzzy_next_scheduled(
        temp_alert,
        now_server_naive(),
        user_prefs,
        record_history=False,
    )
    if next_dt is None:
        _log_daily_interval_event(update, context, "daily_interval_fuzzy_rejected", {
            "source": "fuzzy_mean_std_input",
            "reason_code": "repetition_rejected",
            "mean": round(mean_val, 6),
            "std": round(std_val, 6),
        })
        await update.message.reply_text(
            "⚠️ Unable to schedule with the current repetition constraints. Adjust parameters and try again."
        )
        return C.FUZZY_MEAN_STD_INPUT

    temp_alert["next_scheduled"] = next_dt.isoformat()
    _log_daily_interval_event(update, context, "daily_interval_fuzzy_set", {
        "source": "fuzzy_mean_std_input",
        "mean": round(mean_val, 6),
        "std": round(std_val, 6),
        "sampled_days": sampled_days,
        "next_scheduled": next_dt.isoformat(),
        "shifted": bool(shifted),
    })
    return await show_multi_setting_menu(update, context)


async def get_interval_callback(update, context, return_to_settings):
    """Handle interval quick-button callbacks and return to settings."""
    query = update.callback_query
    await query.answer()
    if _is_daily_alert(context):
        return await _show_daily_interval_confirm(update, context, source="interval_quick_button")
    schedule = context.user_data["temp_alert"].setdefault("schedule", {})
    schedule["interval"] = 1
    schedule.pop("start_marker", None)
    return await return_to_settings(update, context)


async def get_interval_input(update, context, show_multi_setting_menu):
    """Validate interval text input, store schedule interval, and route next steps."""
    if _is_daily_fuzzy_mode(context):
        return await fuzzy_mean_std_input(update, context, show_multi_setting_menu)
    raw_text = (update.message.text or "").strip()
    try:
        val = int(raw_text)
        if val < 1:
            raise ValueError
        if _is_daily_alert(context) and val == 1:
            return await _show_daily_interval_confirm(update, context, source="interval_text_input")
        schedule = context.user_data["temp_alert"].setdefault("schedule", {})
        schedule["interval"] = val
        if _is_daily_alert(context):
            _log_daily_interval_event(update, context, "daily_interval_set", {
                "source": "interval_text_input",
                "interval_value": val,
                "has_start_marker": bool(schedule.get("start_marker")),
            })

        if val > 1:
            suggested_dt = calculate_suggested_start(context.user_data["temp_alert"])
            suggested_str = suggested_dt.strftime("%d/%m/%Y")

            keyboard = [
                [InlineKeyboardButton("Today", callback_data="start_today")],
                [InlineKeyboardButton(f"Next: {suggested_str}", callback_data=f"start_{suggested_str}")],
            ]

            await update.message.reply_text(
                "📆 **First Occurrence**\nWhen should the first alert happen?\n"
                "Pick a suggestion or write a date (`DD/MM/YYYY`):",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN,
            )
            return C.GET_START_DATE
        schedule.pop("start_marker", None)
        return await show_multi_setting_menu(update, context)
    except ValueError:
        if _is_daily_alert(context):
            _log_daily_interval_event(update, context, "daily_interval_input_invalid", {
                "source": "interval_text_input",
                "reason_code": "invalid_number",
                "interval_input_meta": text_meta(raw_text),
            })
        await update.message.reply_text("❌ Enter a number >= 1.")
        return C.GET_INTERVAL


async def daily_interval_confirm_callback(update, context, return_to_settings, show_multi_setting_menu):
    """Handle explicit confirmation for daily interval value `1`."""
    query = update.callback_query
    data = (query.data or "").strip()

    if data not in {"dint1_yes", "dint1_change"}:
        await query.answer("Invalid option. Please choose again.", show_alert=True)
        return C.DAILY_INTERVAL_CONFIRM

    await query.answer()
    source = context.user_data.get("daily_interval_confirm_source", "interval_confirm")

    if data == "dint1_change":
        _log_daily_interval_event(update, context, "daily_interval_one_change_requested", {
            "source": source,
        })
        return await get_interval_prompt(update, context, show_multi_setting_menu)

    schedule = context.user_data["temp_alert"].setdefault("schedule", {})
    schedule["interval"] = 1
    schedule.pop("start_marker", None)
    _log_daily_interval_event(update, context, "daily_interval_one_confirmed", {
        "source": source,
    })
    _log_daily_interval_event(update, context, "daily_interval_set", {
        "source": source,
        "interval_value": 1,
        "has_start_marker": False,
    })
    context.user_data.pop("daily_interval_confirm_source", None)
    return await return_to_settings(update, context)


async def get_start_date_callback(update, context, show_multi_setting_menu):
    """Store a start marker selected from interval suggestion callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data.replace("start_", "", 1)
    if data == "today":
        final_date = datetime.now().strftime("%d/%m/%Y")
    else:
        # Reject malformed callback payloads from stale/tampered keyboards.
        try:
            datetime.strptime(data, "%d/%m/%Y")
        except ValueError:
            await query.answer("Invalid date selection. Please choose again.", show_alert=True)
            return C.GET_START_DATE
        final_date = data

    context.user_data["temp_alert"]["schedule"]["start_marker"] = final_date
    return await show_multi_setting_menu(update, context)


async def get_start_date_input(update, context, show_multi_setting_menu):
    """Validate manual start-marker input and store it in the schedule."""
    text = update.message.text.strip()
    try:
        datetime.strptime(text, "%d/%m/%Y")
        context.user_data["temp_alert"]["schedule"]["start_marker"] = text
        return await show_multi_setting_menu(update, context)
    except ValueError:
        await update.message.reply_text(
            "❌ **Invalid format.** Please use `DD/MM/YYYY` (e.g., `05/03/2026`):"
        )
        return C.GET_START_DATE


async def get_time_input(update, context, show_multi_setting_menu):
    """Validate HH:MM input and store it as the schedule time."""
    try:
        text = (update.message.text or "").strip()
        datetime.strptime(text, "%H:%M")
        temp_alert = context.user_data["temp_alert"]
        schedule = temp_alert.setdefault("schedule", {})
        schedule["time"] = text
        if _is_daily_fuzzy_mode(context):
            user_prefs = _get_user_prefs_for_daily_flow(update, context)
            adjusted = _adjust_fuzzy_draft_next_scheduled_time(temp_alert, user_prefs)
            next_scheduled = temp_alert.get("next_scheduled")
            _log_daily_interval_event(update, context, "daily_interval_fuzzy_time_adjusted", {
                "source": "time_text_input",
                "adjusted": bool(adjusted),
                "next_scheduled": next_scheduled if isinstance(next_scheduled, str) else None,
            })
        return await show_multi_setting_menu(update, context)
    except ValueError:
        await update.message.reply_text("❌ **Invalid.** Use HH:MM:")
        return C.GET_TIME


async def get_time_callback(update, context, show_multi_setting_menu):
    """Apply default schedule time from the quick-button callback."""
    await update.callback_query.answer()
    temp_alert = context.user_data["temp_alert"]
    schedule = temp_alert.setdefault("schedule", {})
    schedule["time"] = "10:00"
    if _is_daily_fuzzy_mode(context):
        user_prefs = _get_user_prefs_for_daily_flow(update, context)
        adjusted = _adjust_fuzzy_draft_next_scheduled_time(temp_alert, user_prefs)
        next_scheduled = temp_alert.get("next_scheduled")
        _log_daily_interval_event(update, context, "daily_interval_fuzzy_time_adjusted", {
            "source": "time_default_callback",
            "adjusted": bool(adjusted),
            "next_scheduled": next_scheduled if isinstance(next_scheduled, str) else None,
        })
    return await show_multi_setting_menu(update, context)


async def show_pre_alert_menu(update, context):
    """Show pre-alert options for the current draft alert payload."""
    pre_alerts = context.user_data.get("temp_alert", {}).get("pre_alerts")
    if not isinstance(pre_alerts, list):
        pre_alerts = []
        if isinstance(context.user_data.get("temp_alert"), dict):
            context.user_data["temp_alert"]["pre_alerts"] = pre_alerts
    temp_alert = context.user_data.get("temp_alert", {})
    is_birthday_context = isinstance(temp_alert, dict) and temp_alert.get("type") == 6
    has_evening_before = C.BIRTHDAY_PREALERT_EVENING_BEFORE_TOKEN in pre_alerts
    no_pre_icon = "✅" if not pre_alerts else "🚫"
    keyboard = [[
        InlineKeyboardButton("1 day", callback_data="pre_1d"),
        InlineKeyboardButton("1 week", callback_data="pre_1w"),
        InlineKeyboardButton("1 month", callback_data="pre_1mo"),
    ]]
    if is_birthday_context:
        evening_label = "✅ Evening before" if has_evening_before else "🌆 Evening before"
        keyboard.append([InlineKeyboardButton(evening_label, callback_data="pre_bdayeve")])
    keyboard.extend([
        [
            InlineKeyboardButton("⚙️ Custom", callback_data="pre_custom"),
            InlineKeyboardButton(f"{no_pre_icon} No pre-alert", callback_data="pre_none"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="pre_cancel")],
    ])
    text = "🔔 **Pre-Notification**\nWhen should I remind you *before* the event?"

    if update.callback_query:
        await _edit_callback_message(
            update.callback_query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )
    return C.GET_PRE_ALERT


def _custom_pre_alert_instructions():
    return (
        "⚙️ **Custom Pre-Alert**\n"
        "You can send one or more entries separated by commas.\n\n"
        "**Supported input families**\n"
        "• Duration tokens: `30m`, `2h`, `1d`, `2w`, `1mo`\n"
        "• Natural datetime: `today`, `tomorrow`, `today at 18:30`\n"
        "• Calendar datetime: `25/12`, `25/12 09:00`, `25/12/2026 09:00`\n\n"
        "**Defaults**\n"
        "• Missing time uses the event time.\n"
        "• Missing year uses the next future occurrence.\n\n"
        "**Examples**\n"
        "• `1h, tomorrow 09:30`\n"
        "• `today at 18:00`\n"
        "• `25/12 09:00`"
    )


def _custom_pre_alert_reason_label(reason_code: str | None) -> str:
    code = (reason_code or "").strip().lower()
    labels = {
        "empty": "empty value",
        "invalid_format": "invalid format",
        "invalid_time": "invalid time",
        "invalid_date": "invalid date",
        "not_future": "in the past or right now",
        "not_before_due": "not before the due event",
        "due_unresolved": "due event could not be resolved",
        "delta_not_representable": "not representable as a token",
        "boundary_mode_unknown": "unsupported boundary mode",
        "boundary_missing": "missing boundary date",
        "candidate_not_future": "in the past or right now",
        "candidate_not_before_boundary": "not before the due event",
    }
    return labels.get(code, "invalid value")


def _format_pre_alert_pre_fire(pre_fire: datetime, user_prefs: dict | None) -> str:
    local_dt = pre_fire
    timezone_suffix = ""
    if isinstance(user_prefs, dict):
        mode = user_prefs.get("timezone_mode") or C.TIMEZONE_DEFAULT_MODE
        if mode == C.TIMEZONE_MODE_USER:
            try:
                user_tz = resolve_user_timezone(user_prefs)
                local_dt = to_user_naive_from_server(pre_fire, user_tz)
                timezone_suffix = f" ({user_tz.key})"
            except Exception:
                pass
    return f"{local_dt.strftime('%d/%m/%Y %H:%M')}{timezone_suffix}"


async def get_pre_alert_callback(update, context, return_to_settings):
    """Route pre-alert menu actions and present expanded custom-input guidance when requested."""
    query = update.callback_query
    data = query.data.replace("pre_", "", 1)
    temp_alert = context.user_data.get("temp_alert", {})
    is_birthday_context = isinstance(temp_alert, dict) and temp_alert.get("type") == 6
    allowed_data = {"1d", "1w", "1mo", "none", "custom", "cancel"}
    if is_birthday_context:
        allowed_data.add("bdayeve")
    if data not in allowed_data:
        await query.answer("Invalid pre-alert option. Please choose again.", show_alert=True)
        return C.GET_PRE_ALERT
    await query.answer()

    if data == "none":
        context.user_data["pending_pre_alerts"] = []
        context.user_data["temp_alert"]["pre_alerts"] = []
        return await return_to_settings(update, context)

    if data == "cancel":
        context.user_data["pending_pre_alerts"] = []
        return await return_to_settings(update, context)

    if data == "custom":
        context.user_data["pending_pre_alerts"] = []
        await _edit_callback_message(
            query,
            _custom_pre_alert_instructions(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return C.GET_CUSTOM_PRE_ALERT

    if data == "bdayeve":
        context.user_data["pending_pre_alerts"] = []
        current = context.user_data["temp_alert"].get("pre_alerts", [])
        if not isinstance(current, list):
            current = []
        context.user_data["temp_alert"]["pre_alerts"] = merge_pre_alerts(
            current,
            [C.BIRTHDAY_PREALERT_EVENING_BEFORE_TOKEN],
        )
        return await return_to_settings(update, context)

    context.user_data["pending_pre_alerts"] = []
    current = context.user_data["temp_alert"].get("pre_alerts", [])
    if not isinstance(current, list):
        current = []
    context.user_data["temp_alert"]["pre_alerts"] = merge_pre_alerts(current, [data])
    return await return_to_settings(update, context)


def _load_user_prefs_for_pre_alert(update, context):
    user_id = get_target_user_id(update, context)
    if user_id is None:
        return None
    try:
        storage = get_runtime_storage(context)
    except Exception:
        return None
    if not hasattr(storage, "get_user_prefs"):
        return None
    try:
        return storage.get_user_prefs(user_id)
    except Exception:
        return None


def _build_pre_alert_token_from_resolved(pre_fire: datetime, main_due: datetime) -> tuple[str | None, str | None]:
    """Convert a resolved pre-fire datetime into a canonical duration token with reasoned failures."""
    if not isinstance(pre_fire, datetime) or not isinstance(main_due, datetime):
        return None, "invalid_datetime"
    if pre_fire >= main_due:
        return None, "candidate_not_before_due"

    month_delta = (main_due.year - pre_fire.year) * 12 + (main_due.month - pre_fire.month)
    if month_delta > 0:
        try:
            if (main_due - relativedelta(months=month_delta)) == pre_fire:
                return f"{month_delta}mo", None
        except Exception:
            pass

    delta = main_due - pre_fire
    total_seconds = delta.total_seconds()
    if total_seconds <= 0:
        return None, "candidate_not_before_due"
    if total_seconds % 60 != 0:
        return None, "delta_not_minute_aligned"

    total_minutes = int(total_seconds // 60)
    if total_minutes % (7 * 24 * 60) == 0:
        return f"{total_minutes // (7 * 24 * 60)}w", None
    if total_minutes % (24 * 60) == 0:
        return f"{total_minutes // (24 * 60)}d", None
    if total_minutes % 60 == 0:
        return f"{total_minutes // 60}h", None
    return f"{total_minutes}m", None


def _resolve_custom_pre_alert_tokens(
    raw_text: str,
    *,
    alert_payload: dict,
    due_server_dt: datetime,
    now_server_dt: datetime,
    user_prefs: dict | None,
) -> tuple[list[dict], list[dict]]:
    parts = [part.strip() for part in (raw_text or "").split(",") if part.strip()]
    if not parts:
        return [], [{
            "raw": "",
            "reason_code": "empty",
        }]

    resolved_items = []
    invalid_items = []

    for part in parts:
        token_fast_path, token_invalid = parse_custom_pre_alerts(part)
        if len(token_fast_path) == 1 and not token_invalid:
            token_candidate = token_fast_path[0]
            pre_fire, _kind = resolve_pre_alert_fire_time(
                alert_payload,
                token_candidate,
                due_server_dt,
                user_prefs=user_prefs,
            )
            if pre_fire is None:
                invalid_items.append({"raw": part, "reason_code": "invalid_format"})
                continue
            if pre_fire <= now_server_dt:
                invalid_items.append({"raw": part, "reason_code": "not_future"})
                continue
            canonical_token, reason_code = _build_pre_alert_token_from_resolved(pre_fire, due_server_dt)
            if canonical_token is None or reason_code is not None:
                mapped_reason = "not_before_due" if reason_code == "candidate_not_before_due" else "delta_not_representable"
                invalid_items.append({"raw": part, "reason_code": mapped_reason})
                continue
            resolved_items.append({
                "raw": part,
                "token": canonical_token,
                "pre_fire": pre_fire,
            })
            continue

        status, pre_fire, meta = parse_user_datetime_expression(
            part,
            reference_server_dt=now_server_dt,
            user_prefs=user_prefs,
            default_time=due_server_dt.strftime("%H:%M"),
            boundary_mode="future_before_boundary",
            boundary_server_dt=due_server_dt,
            now_server_dt=now_server_dt,
        )
        if status != "ok" or pre_fire is None:
            invalid_items.append({
                "raw": part,
                "reason_code": (meta or {}).get("reason_code") or "invalid_format",
            })
            continue

        canonical_token, reason_code = _build_pre_alert_token_from_resolved(pre_fire, due_server_dt)
        if canonical_token is None or reason_code is not None:
            mapped_reason = "not_before_due" if reason_code == "candidate_not_before_due" else "delta_not_representable"
            invalid_items.append({"raw": part, "reason_code": mapped_reason})
            continue
        resolved_items.append({
            "raw": part,
            "token": canonical_token,
            "pre_fire": pre_fire,
        })

    return resolved_items, invalid_items


async def get_custom_pre_alert_input(update, context):
    """Parse custom pre-alert input, show interpreted outcomes, and return reasoned retry feedback."""
    raw_text = update.message.text.strip()
    temp_alert = context.user_data.get("temp_alert", {})
    if not isinstance(temp_alert, dict):
        temp_alert = {}
        context.user_data["temp_alert"] = temp_alert

    user_prefs = _load_user_prefs_for_pre_alert(update, context)
    now_ref = now_server_naive()
    due_server_dt, _shifted = compute_next_occurrence(temp_alert, now_ref, user_prefs)
    if due_server_dt is None:
        await update.message.reply_text(
            "❌ **Cannot evaluate pre-alerts right now.**\n"
            "Set a valid future schedule first, then try again.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return C.GET_CUSTOM_PRE_ALERT

    resolved_items, invalid_items = _resolve_custom_pre_alert_tokens(
        raw_text,
        alert_payload=temp_alert,
        due_server_dt=due_server_dt,
        now_server_dt=now_ref,
        user_prefs=user_prefs,
    )
    resolved_tokens = [str(item.get("token")) for item in resolved_items if item.get("token")]
    tokens = merge_pre_alerts([], resolved_tokens)

    if invalid_items or not tokens:
        reason_lines = []
        for item in invalid_items:
            raw_item = md_escape(str(item.get("raw") or "(empty)"))
            reason_label = md_escape(_custom_pre_alert_reason_label(item.get("reason_code")))
            reason_lines.append(f"• `{raw_item}` → {reason_label}")
        reason_block = "\n".join(reason_lines)
        if reason_block:
            reason_block = f"\n\n**Rejected entries**\n{reason_block}"
        await update.message.reply_text(
            "❌ **Could not save custom pre-alerts.**\n"
            "Use duration tokens or datetime expressions, separated by commas."
            f"{reason_block}\n\n"
            "Send a new value, or /cancel to leave this step.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return C.GET_CUSTOM_PRE_ALERT

    tokens = merge_pre_alerts([], tokens)
    context.user_data["pending_pre_alerts"] = tokens

    interpreted_lines = []
    for item in resolved_items:
        token = str(item.get("token"))
        fire_time = item.get("pre_fire")
        if not isinstance(fire_time, datetime):
            continue
        raw_item = md_escape(str(item.get("raw") or token))
        fire_label = md_escape(_format_pre_alert_pre_fire(fire_time, user_prefs))
        interpreted_lines.append(f"• `{raw_item}` → `{token}` ({fire_label})")
    interpreted_block = "\n".join(interpreted_lines)
    summary = ", ".join(tokens)
    keyboard = [[
        InlineKeyboardButton("✅ Yes", callback_data="precustom_yes"),
        InlineKeyboardButton("❌ No", callback_data="precustom_no"),
    ]]
    await update.message.reply_text(
        "✅ **Parsed custom pre-alerts**\n"
        f"Canonical tokens: `{summary}`\n\n"
        f"Interpreted entries:\n{interpreted_block}\n\n"
        "Confirm?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )
    return C.CONFIRM_CUSTOM_PRE_ALERT


async def confirm_custom_pre_alert(update, context, return_to_settings):
    """Handle custom pre-alert confirmation and re-prompt with full syntax guidance on retry."""
    query = update.callback_query
    data = query.data

    if data not in {"precustom_yes", "precustom_no"}:
        await query.answer("Invalid confirmation option. Please choose again.", show_alert=True)
        return C.CONFIRM_CUSTOM_PRE_ALERT

    await query.answer()

    if data == "precustom_no":
        context.user_data["pending_pre_alerts"] = []
        await _edit_callback_message(
            query,
            _custom_pre_alert_instructions(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return C.GET_CUSTOM_PRE_ALERT

    pending = context.user_data.get("pending_pre_alerts", [])
    current = context.user_data["temp_alert"].get("pre_alerts", [])
    context.user_data["temp_alert"]["pre_alerts"] = merge_pre_alerts(current, pending)
    context.user_data["pending_pre_alerts"] = []
    return await return_to_settings(update, context)


async def show_tags_menu(update, context, pre_selected=None):
    """Show available tags and initialize tag toggle selection state."""
    storage = get_runtime_storage(context)

    user_id = get_target_user_id(update, context)
    available_tags = storage.get_user_tags(user_id)

    context.user_data["temp_selection"] = list(pre_selected) if pre_selected is not None else []
    if available_tags:
        text = (
            "🏷️ **Select Tags** (One or more, then DONE):\n\n"
            "💡 _If your desired tag is not listed, skip this step._\n"
            "_After saving, go to /tags to create it, then edit this event's tag._"
        )
    else:
        text = (
            "🏷️ **No tags available.** Press DONE to continue without tags.\n\n"
            "💡 _After saving, go to /tags to create tags, then edit this event's tag._"
        )
    kb = build_toggle_keyboard(available_tags, context.user_data["temp_selection"], C.CB_TAG)

    if update.callback_query:
        await _edit_callback_message(
            update.callback_query,
            text,
            reply_markup=kb,
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    return C.GET_TAGS


async def tags_toggle(update, context, finalize_after_tags):
    """Handle tag toggles and finalize the flow when DONE is selected."""
    storage = get_runtime_storage(context)

    query = update.callback_query
    user_id = get_target_user_id(update, context)
    available_tags = storage.get_user_tags(user_id)
    data = query.data.replace(C.CB_TAG, "")

    if data == "DONE":
        await query.answer()
        context.user_data["temp_alert"]["tags"] = context.user_data.get("temp_selection", [])
        return await finalize_after_tags(update, context)

    return await toggle_handler(
        update,
        context,
        available_tags,
        C.CB_TAG,
        None,
        "",
    ) or C.GET_TAGS
