"""Edit alert conversation flow."""

import copy

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from modules import constants as C
from modules.handlers.add_flow.settings_flow import (
    return_to_settings as _return_to_settings_impl,
    show_change_type_menu,
)
from modules.handlers.add_flow.state_helpers import (
    _delete_additional_info_copy_message,
    cleanup_add_flow_messages,
    track_add_flow_callback_message,
    track_add_flow_incoming,
    track_add_flow_outgoing,
)
from modules.handlers.add_flow.summary_flow import ensure_default_settings
from modules.handlers.add_flow.type_flow import (
    show_tags_menu as _show_tags_menu_impl,
)
from modules.handlers.edit_flow.dashboard import (
    build_edit_dashboard_keyboard,
    format_edit_dashboard_text,
)
from modules.scheduler_core.state import clear_pre_alert_tracking_for_alert
from modules.shared.acting_as import get_actor_user_id, get_target_user_id
from modules.shared.context_cleanup import (
    clear_transient_context,
    has_transient_context,
    require_temp_alert,
)
from modules.shared.logging_utils import text_meta
from modules.shared.markdown_utils import md_escape
from modules.shared.runtime_context import get_runtime_storage
from modules.handlers.base.conversation_fallbacks import (
    build_implicit_cancel_fallbacks,
    end_registered_conversations,
)
from modules.timezone_utils import (
    compute_next_occurrence,
    now_server_naive,
    resolve_fuzzy_next_scheduled,
    resolve_user_timezone,
    to_user_naive_from_server,
)


from .origin import (
    _build_edit_origin_context,
    _capture_origin_tag_filter,
    _extract_alert_id_from_manage_callback,
    _finalize_edit_success,
    _log_edit_flow_event,
    _normalize_origin_source_hint,
    _track_edit_callback_message,
    _track_edit_incoming_message,
    _track_edit_outgoing_message,
)
from .commit import (
    _build_commit_plan as _build_commit_plan_impl,
    _prepare_edit_snapshot,
)
from . import delegates


def _build_commit_plan(temp_alert, original_alert, now_ref, user_prefs):
    """Build commit/update plan while honoring flow-level monkeypatch seams used by debuggers."""
    return _build_commit_plan_impl(
        temp_alert,
        original_alert,
        now_ref,
        user_prefs,
        compute_next_occurrence_fn=compute_next_occurrence,
        resolve_fuzzy_next_scheduled_fn=resolve_fuzzy_next_scheduled,
    )


async def _send_actor_message(update, context, text, reply_markup=None):
    """Send an edit-flow message to the actor and return the sent message when available."""
    if update and update.message:
        sent = await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )
        _track_edit_outgoing_message(context, sent)
        return sent

    actor_id = get_actor_user_id(update)
    if actor_id is None and update and update.effective_user:
        actor_id = update.effective_user.id
    if actor_id is None:
        return None
    sent = await context.bot.send_message(
        chat_id=actor_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN,
    )
    _track_edit_outgoing_message(context, sent)
    return sent


def _is_message_not_modified_error(exc):
    """Return whether an exception is Telegram's benign no-op edit error."""
    try:
        text = str(exc or "")
    except Exception:
        return False
    return "message is not modified" in text.lower()


async def _edit_callback_message(
    query,
    text,
    *,
    reply_markup=None,
    parse_mode=ParseMode.MARKDOWN,
):
    """Edit callback message as caption for photo cards and text otherwise."""
    if query is None:
        return False

    message = getattr(query, "message", None)
    is_photo_message = bool(message and getattr(message, "photo", None))
    payload = {"reply_markup": reply_markup}
    if parse_mode is not None:
        payload["parse_mode"] = parse_mode

    try:
        if is_photo_message:
            await query.edit_message_caption(caption=text, **payload)
        else:
            await query.edit_message_text(text=text, **payload)
        return True
    except Exception as exc:
        if _is_message_not_modified_error(exc):
            return True
        return False


async def _render_edit_terminal(update, context, text):
    """Render terminal edit-flow feedback in-place or fall back to a fresh message."""
    query = update.callback_query if update else None
    if query:
        edited = await _edit_callback_message(
            query,
            text,
            parse_mode=ParseMode.MARKDOWN,
        )
        if edited:
            return
    await _send_actor_message(update, context, text)


async def _abort_start_edit(update, context, text):
    """Clear transient edit context and end the session with one fail-soft message."""
    clear_transient_context(context.user_data)
    try:
        await _render_edit_terminal(update, context, text)
    except Exception:
        pass
    return ConversationHandler.END


async def _return_to_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _return_to_settings_impl(
        update,
        context,
        show_edit_dashboard,
        show_edit_dashboard,
        show_edit_dashboard=show_edit_dashboard,
    )


async def show_edit_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render the edit dashboard with media-aware callback editing and resolved pre-alert labels."""
    temp_alert = context.user_data.get("temp_alert")
    if not isinstance(temp_alert, dict):
        clear_transient_context(context.user_data)
        await _render_edit_terminal(
            update,
            context,
            "❌ Edit session expired. Open the alert and start again.",
        )
        return ConversationHandler.END

    _track_edit_callback_message(update, context)

    ensure_default_settings(temp_alert)
    context.user_data["settings_return"] = "edit"

    user_prefs = None
    try:
        storage = get_runtime_storage(context)

        user_id = get_target_user_id(update, context)
        if user_id is not None and hasattr(storage, "get_user_prefs"):
            user_prefs = storage.get_user_prefs(user_id)
    except Exception:
        user_prefs = None

    text = format_edit_dashboard_text(temp_alert, user_prefs=user_prefs)
    keyboard = build_edit_dashboard_keyboard(temp_alert.get("type"))

    query = update.callback_query if update else None
    if query:
        edited = await _edit_callback_message(
            query,
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
        if not edited:
            await _send_actor_message(update, context, text, reply_markup=keyboard)
    else:
        await _send_actor_message(update, context, text, reply_markup=keyboard)
    return C.EDIT_DASHBOARD


delegates.configure_edit_dependencies(
    return_to_edit=_return_to_edit,
    show_edit_dashboard=show_edit_dashboard,
)

# Backward-compatible exports for debugger/import contracts that still resolve wrappers from flow.
ask_time = delegates.ask_time
prompt_type_specific_edit = delegates.prompt_type_specific_edit
get_interval_prompt_edit = delegates.get_interval_prompt_edit
get_interval_input_edit = delegates.get_interval_input_edit
get_interval_callback_edit = delegates.get_interval_callback_edit
daily_interval_confirm_callback_edit = delegates.daily_interval_confirm_callback_edit
interval_mode_choice_callback_edit = delegates.interval_mode_choice_callback_edit
fuzzy_mean_std_input_edit = delegates.fuzzy_mean_std_input_edit
get_start_date_callback_edit = delegates.get_start_date_callback_edit
get_start_date_input_edit = delegates.get_start_date_input_edit
get_time_input_edit = delegates.get_time_input_edit
get_time_callback_edit = delegates.get_time_callback_edit
show_pre_alert_menu = delegates.show_pre_alert_menu
get_pre_alert_callback_edit = delegates.get_pre_alert_callback_edit
get_custom_pre_alert_input_edit = delegates.get_custom_pre_alert_input_edit
confirm_custom_pre_alert_edit = delegates.confirm_custom_pre_alert_edit
show_photo_menu_edit = delegates.show_photo_menu_edit
show_repetition_menu_edit = delegates.show_repetition_menu_edit
prompt_repetition_until_date_edit = delegates.prompt_repetition_until_date_edit
prompt_repetition_count_edit = delegates.prompt_repetition_count_edit
handle_repetition_choice_edit = delegates.handle_repetition_choice_edit
handle_repetition_until_date_input_edit = delegates.handle_repetition_until_date_input_edit
handle_repetition_count_input_edit = delegates.handle_repetition_count_input_edit
get_photo_edit = delegates.get_photo_edit
reject_document_edit = delegates.reject_document_edit
photo_back_edit = delegates.photo_back_edit
remove_photo_edit = delegates.remove_photo_edit
prompt_additional_info = delegates.prompt_additional_info
handle_additional_info_input_edit = delegates.handle_additional_info_input_edit
handle_additional_info_skip_edit = delegates.handle_additional_info_skip_edit
handle_additional_info_clear_edit = delegates.handle_additional_info_clear_edit
type_1_days_edit = delegates.type_1_days_edit
type_2_ordinal_edit = delegates.type_2_ordinal_edit
type_2_fifth_policy_edit = delegates.type_2_fifth_policy_edit
type_2_weekday_edit = delegates.type_2_weekday_edit
type_3_weekdays_edit = delegates.type_3_weekdays_edit
type_4_dates_edit = delegates.type_4_dates_edit
type_5_date_edit = delegates.type_5_date_edit
tags_toggle_edit = delegates.tags_toggle_edit
handle_change_type_callback_edit = delegates.handle_change_type_callback_edit


async def start_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start an edit session and fail soft with cleanup if dashboard bootstrap fails."""
    query = update.callback_query
    if query is None:
        return ConversationHandler.END

    alert_id = _extract_alert_id_from_manage_callback(query.data)
    if alert_id is None:
        await query.answer("Invalid edit request.", show_alert=True)
        return ConversationHandler.END

    storage = get_runtime_storage(context)

    user_id = get_target_user_id(update, context)
    if user_id is None:
        await query.answer("Unable to resolve target user.", show_alert=True)
        return ConversationHandler.END

    alert = storage.get_alert_by_id(user_id, alert_id)
    if not isinstance(alert, dict):
        await query.answer("Alert not found.", show_alert=True)
        return ConversationHandler.END

    await query.answer()
    _track_edit_callback_message(update, context)

    if has_transient_context(context.user_data):
        clear_transient_context(context.user_data)

    try:
        snapshot = _prepare_edit_snapshot(alert)
        origin_context = _build_edit_origin_context(update, alert_id)
        source_hint = _normalize_origin_source_hint(context.user_data.get("manage_source"))
        if source_hint:
            origin_context["source_hint"] = source_hint
        tag_filter = _capture_origin_tag_filter(context, source_hint)
        if tag_filter is not None:
            origin_context["tag_filter"] = tag_filter
        try:
            origin_kind = str(origin_context.get("kind") or "due").strip().lower()
        except Exception:
            origin_kind = "due"
        if origin_kind not in {"pre", "due"}:
            origin_kind = "due"
        try:
            postpone_count = int(origin_context.get("postpone_count") or 0)
        except (TypeError, ValueError):
            postpone_count = 0
        if postpone_count < 0:
            postpone_count = 0
        _log_edit_flow_event(
            storage,
            user_id,
            "edit_origin_detected",
            {
                "source": "edit_flow",
                "alert_id": str(alert_id),
                "origin_source": str(origin_context.get("source") or "unknown"),
                "source_hint": str(origin_context.get("source_hint") or ""),
                "include_back": bool(origin_context.get("include_back")),
                "has_tag_filter": "tag_filter" in origin_context,
                "kind": origin_kind,
                "postpone_count": postpone_count,
                "has_chat_id_ref": origin_context.get("chat_id") is not None,
                "has_message_id_ref": origin_context.get("message_id") is not None,
                "is_photo_origin": bool(origin_context.get("is_photo")),
                "has_original_time": bool(origin_context.get("original_time")),
                "has_occurrence_time": bool(origin_context.get("occurrence_time")),
            },
        )
        context.user_data["edit_alert_id"] = alert_id
        context.user_data["edit_alert_original"] = copy.deepcopy(snapshot)
        context.user_data["edit_origin_context"] = origin_context
        context.user_data["temp_alert"] = copy.deepcopy(snapshot)
        context.user_data["add_flow_message_ids"] = []
        context.user_data["add_flow_start_message_id"] = None
        return await show_edit_dashboard(update, context)
    except Exception:
        return await _abort_start_edit(
            update,
            context,
            "❌ Could not open edit dashboard. Please retry from the alert card.",
        )


@require_temp_alert
async def handle_edit_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route edit-dashboard callbacks and render prompts with media-aware callback edits."""
    query = update.callback_query
    if query is None:
        return C.EDIT_DASHBOARD
    await query.answer()
    _track_edit_callback_message(update, context)
    data = query.data or ""
    temp_alert = context.user_data.get("temp_alert") or {}

    if data == "ed_name":
        current_title = md_escape(temp_alert.get("title") or "-")
        rename_text = f"✏️ **Rename alert**\nCurrent name: {current_title}\n\nEnter new name:"
        edited = await _edit_callback_message(
            query,
            rename_text,
            parse_mode=ParseMode.MARKDOWN,
        )
        if not edited:
            await _send_actor_message(update, context, rename_text)
        return C.EDIT_NAME
    if data == "ed_schedule":
        if temp_alert.get("type") == 6:
            return await prompt_birthday_date_edit(update, context)
        return await delegates.prompt_type_specific_edit(update, context)
    if data == "ed_change_type":
        return await show_change_type_menu(update, context)
    if data == "ed_interval":
        return await delegates.get_interval_prompt_edit(update, context)
    if data == "ed_time":
        return await delegates.ask_time(update, context)
    if data == "ed_pre":
        return await delegates.show_pre_alert_menu(update, context)
    if data == "ed_repetition":
        return await delegates.show_repetition_menu_edit(update, context)
    if data == "ed_photo":
        return await delegates.show_photo_menu_edit(update, context)
    if data == "ed_info":
        return await delegates.prompt_additional_info(update, context)
    if data == "ed_bday_date":
        return await prompt_birthday_date_edit(update, context)
    if data == "ed_tags":
        pre_selected = list((context.user_data.get("temp_alert") or {}).get("tags") or [])
        return await _show_tags_menu_impl(update, context, pre_selected=pre_selected)
    if data == "ed_done":
        return await commit_edit(update, context)
    return C.EDIT_DASHBOARD


@require_temp_alert
async def handle_edit_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Validate renamed alert text and return to the edit dashboard."""
    _track_edit_incoming_message(update, context)
    title = (update.message.text or "").strip()
    if not title:
        await update.message.reply_text("❌ Title cannot be empty. Try again.")
        return C.EDIT_NAME
    if len(title) > C.TITLE_MAX_LEN:
        try:
            storage = get_runtime_storage(context)

            target_id = get_target_user_id(update, context)
            storage.log_user_event(target_id, "title_input_too_long", {"title_len": len(title)})
        except Exception:
            pass
        await update.message.reply_text(
            f"⚠️ Title too long (max {C.TITLE_MAX_LEN} characters). Try again."
        )
        return C.EDIT_NAME
    context.user_data["temp_alert"]["title"] = title
    return await show_edit_dashboard(update, context)


@require_temp_alert
async def prompt_birthday_date_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt for birthday date edits and render with media-aware callback editing.
    
    Log prompt telemetry for edit flow and keep non-birthday alerts on the dashboard
    without mutating schedule state.
    """
    temp_alert = context.user_data.get("temp_alert") or {}
    if temp_alert.get("type") != 6:
        return C.EDIT_DASHBOARD
    _track_edit_callback_message(update, context)

    try:
        storage = get_runtime_storage(context)

        user_id = get_target_user_id(update, context)
        if user_id is not None:
            storage.log_user_event(user_id, "birthday_date_edit_prompted", {"source": "edit_flow"})
    except Exception:
        pass

    query = update.callback_query if update else None
    current_date_label = now_server_naive().strftime("%d/%m/%Y")
    prompt_text = (
        "📅 **Birthday Date**\n"
        f"Today is `{current_date_label}`.\n"
        "Write date as DD/MM or DD/MM/YYYY\n"
        "(set the year, I can remind you the age!)"
    )
    if query:
        edited = await _edit_callback_message(
            query,
            prompt_text,
            parse_mode=ParseMode.MARKDOWN,
        )
        if not edited:
            await _send_actor_message(update, context, prompt_text)
    else:
        await _send_actor_message(update, context, prompt_text)
    return C.TYPE_6_DATE


@require_temp_alert
async def type_6_date_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Validate birthday date edits, persist normalized fields, and log reasoned outcomes.
    
    Accept `DD/MM` or `DD/MM/YYYY`, enforce birth-year bounds, and preserve birthday
    default-time behavior when no explicit reminder time is set.
    """
    _track_edit_incoming_message(update, context)
    storage = get_runtime_storage(context)
    from modules.handlers.base import _birthday_default_time_from_prefs
    from modules.handlers.birthday_flow.flow import parse_birthday_date_input

    temp_alert = context.user_data.get("temp_alert") or {}
    if temp_alert.get("type") != 6:
        return C.EDIT_DASHBOARD

    raw_text = (update.message.text or "") if update and update.message else ""
    text = raw_text.strip()
    parsed = parse_birthday_date_input(text)
    reason = parsed.get("reason_code") or "invalid_date"
    user_id = get_target_user_id(update, context)

    if not parsed.get("ok"):
        try:
            if user_id is not None:
                storage.log_user_event(
                    user_id,
                    "birthday_date_edit_invalid",
                    {
                        "source": "edit_flow",
                        "reason_code": reason,
                        "date_input_meta": text_meta(raw_text),
                    },
                )
        except Exception:
            pass

        if reason == "year_two_digits":
            await _send_actor_message(
                update,
                context,
                "❌ **2-digit year not allowed.** Please use 4 digits (e.g. `25/12/1990`):",
            )
            return C.TYPE_6_DATE
        if reason == "year_in_future":
            await _send_actor_message(
                update,
                context,
                "❌ **Birth year cannot be in the future.**",
            )
            return C.TYPE_6_DATE
        if reason == "year_before_1900":
            await _send_actor_message(
                update,
                context,
                "❌ **Birth year must be 1900 or later.**",
            )
            return C.TYPE_6_DATE
        if len(text.split("/")) == 3:
            await _send_actor_message(
                update,
                context,
                "❌ **Invalid date.** Use format DD/MM or DD/MM/YYYY (e.g. `25/12` or `25/12/1990`):",
            )
            return C.TYPE_6_DATE
        await _send_actor_message(
            update,
            context,
            "❌ **Invalid.** Use format DD/MM or DD/MM/YYYY (e.g. `25/12` or `25/12/1990`):",
        )
        return C.TYPE_6_DATE

    schedule = temp_alert.setdefault("schedule", {})
    schedule["date"] = parsed.get("date_ddmm")
    if not schedule.get("time"):
        try:
            user_prefs = storage.get_user_prefs(user_id) if user_id is not None else {}
        except Exception:
            user_prefs = {}
        schedule["time"] = _birthday_default_time_from_prefs(user_prefs)

    birth_year = parsed.get("birth_year")
    if birth_year is None:
        temp_alert.pop("birth_year", None)
    else:
        temp_alert["birth_year"] = birth_year

    try:
        if user_id is not None:
            storage.log_user_event(
                user_id,
                "birthday_date_edit_set",
                {
                    "source": "edit_flow",
                    "has_birth_year": birth_year is not None,
                    "birth_year": birth_year,
                },
            )
    except Exception:
        pass
    return await show_edit_dashboard(update, context)


@require_temp_alert
async def commit_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Persist edit-session changes, apply scheduler side effects, and enforce terminal restore/cleanup contract."""
    storage = get_runtime_storage(context)

    if context.user_data.get("add_flow_save_in_progress"):
        return C.EDIT_DASHBOARD
    context.user_data["add_flow_save_in_progress"] = True

    user_id = get_target_user_id(update, context)
    alert_id = context.user_data.get("edit_alert_id")
    original = context.user_data.get("edit_alert_original")
    temp_alert = context.user_data.get("temp_alert")
    origin_context = copy.deepcopy(context.user_data.get("edit_origin_context") or {})
    try:
        if user_id is None or not alert_id or not isinstance(original, dict) or not isinstance(temp_alert, dict):
            clear_transient_context(context.user_data)
            await _render_edit_terminal(
                update,
                context,
                "❌ Edit session expired. Open the alert and start again.",
            )
            return ConversationHandler.END

        ensure_default_settings(temp_alert)
        ensure_default_settings(original)

        now_ref = now_server_naive()
        try:
            user_prefs = storage.get_user_prefs(user_id)
        except Exception:
            user_prefs = None

        plan = _build_commit_plan(temp_alert, original, now_ref, user_prefs)
        changed_fields = list(plan["changed_fields"])
        updates = dict(plan["updates"])
        schedule_changed = bool(plan["schedule_changed"])
        next_scheduled = plan["next_scheduled"]
        apply_schedule_side_effects = bool(plan.get("apply_schedule_side_effects", False))

        if plan["schedule_compute_error"]:
            await _send_actor_message(
                update,
                context,
                "❌ Could not compute the next occurrence. Please review schedule fields.",
            )
            return C.EDIT_DASHBOARD

        if not updates:
            await _finalize_edit_success(
                update,
                context,
                user_id=user_id,
                alert_id=alert_id,
                origin_context=origin_context,
                ack_text="ℹ️ No changes detected. Alert left unchanged.",
            )
            return ConversationHandler.END

        ok = storage.update_alert_fields(user_id, alert_id, updates)
        if not ok:
            await _send_actor_message(
                update,
                context,
                "❌ Could not update the alert. Please try again.",
            )
            return C.EDIT_DASHBOARD

        if schedule_changed and next_scheduled is not None and apply_schedule_side_effects:
            storage.update_alert_schedule_state(
                user_id,
                alert_id,
                next_scheduled=next_scheduled,
            )
            storage.clear_alert_snooze(user_id, alert_id)
            clear_pre_alert_tracking_for_alert(alert_id)
            storage.expire_pending_postpones_for_alert(user_id, alert_id)

        storage.log_user_event(user_id, "alert_edited", {
            "alert_id": str(alert_id),
            "changed_fields": changed_fields,
        })

        await _finalize_edit_success(
            update,
            context,
            user_id=user_id,
            alert_id=alert_id,
            origin_context=origin_context,
            ack_text="✅ Alert updated!",
        )
        return ConversationHandler.END
    finally:
        context.user_data.pop("add_flow_save_in_progress", None)


async def cancel_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel edit flow, clear transient context, and end registered conversation state for this user."""
    await _delete_additional_info_copy_message(update, context)
    clear_transient_context(context.user_data, include_navigation=True)
    end_registered_conversations(update)
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass
        await _render_edit_terminal(update, context, "⏹️ Edit cancelled.")
        return ConversationHandler.END

    await _send_actor_message(update, context, "⏹️ Edit cancelled.")
    return ConversationHandler.END


edit_alert_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(start_edit, pattern="^manage_fulledit_"),
    ],
    states={
        C.EDIT_DASHBOARD: [CallbackQueryHandler(handle_edit_choice, pattern="^ed_")],
        C.EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_name_input)],
        C.CHANGE_ALERT_TYPE: [CallbackQueryHandler(delegates.handle_change_type_callback_edit, pattern="^ct_")],
        C.TYPE_1_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, delegates.type_1_days_edit)],
        C.TYPE_2_ORDINAL: [CallbackQueryHandler(delegates.type_2_ordinal_edit, pattern=f"^{C.CB_ORDINAL}")],
        C.TYPE_2_FIFTH_POLICY: [CallbackQueryHandler(delegates.type_2_fifth_policy_edit, pattern=f"^{C.CB_FIFTH_POLICY}")],
        C.TYPE_2_WEEKDAY: [CallbackQueryHandler(delegates.type_2_weekday_edit, pattern=f"^{C.CB_WEEKDAY}")],
        C.TYPE_3_WEEKDAYS: [CallbackQueryHandler(delegates.type_3_weekdays_edit, pattern=f"^{C.CB_WEEKDAY}")],
        C.TYPE_4_DATES: [MessageHandler(filters.TEXT & ~filters.COMMAND, delegates.type_4_dates_edit)],
        C.TYPE_5_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, delegates.type_5_date_edit)],
        C.TYPE_6_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, type_6_date_edit)],
        C.GET_INTERVAL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, delegates.get_interval_input_edit),
            CallbackQueryHandler(delegates.get_interval_callback_edit, pattern="^int_"),
        ],
        C.FUZZY_INTERVAL_MODE_CHOICE: [
            CallbackQueryHandler(
                delegates.interval_mode_choice_callback_edit,
                pattern=f"^({C.CB_INTERVAL_FIXED}|{C.CB_INTERVAL_FUZZY})$",
            ),
        ],
        C.FUZZY_MEAN_STD_INPUT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, delegates.fuzzy_mean_std_input_edit),
        ],
        C.DAILY_INTERVAL_CONFIRM: [
            CallbackQueryHandler(delegates.daily_interval_confirm_callback_edit, pattern="^dint1_"),
        ],
        C.GET_START_DATE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, delegates.get_start_date_input_edit),
            CallbackQueryHandler(delegates.get_start_date_callback_edit, pattern="^start_"),
        ],
        C.GET_TIME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, delegates.get_time_input_edit),
            CallbackQueryHandler(delegates.get_time_callback_edit, pattern="^time_"),
        ],
        C.GET_PRE_ALERT: [
            CallbackQueryHandler(delegates.get_pre_alert_callback_edit, pattern="^pre_"),
        ],
        C.GET_CUSTOM_PRE_ALERT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, delegates.get_custom_pre_alert_input_edit),
        ],
        C.GET_REPETITION_MENU: [
            CallbackQueryHandler(delegates.handle_repetition_choice_edit, pattern="^rep_"),
        ],
        C.GET_REPETITION_COUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, delegates.handle_repetition_count_input_edit),
        ],
        C.GET_REPETITION_UNTIL_DATE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, delegates.handle_repetition_until_date_input_edit),
        ],
        C.CONFIRM_CUSTOM_PRE_ALERT: [
            CallbackQueryHandler(delegates.confirm_custom_pre_alert_edit, pattern="^precustom_"),
        ],
        C.GET_ADDITIONAL_INFO: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, delegates.handle_additional_info_input_edit),
            CallbackQueryHandler(delegates.handle_additional_info_skip_edit, pattern="^info_skip$"),
            CallbackQueryHandler(delegates.handle_additional_info_clear_edit, pattern="^info_clear$"),
        ],
        C.GET_TAGS: [CallbackQueryHandler(delegates.tags_toggle_edit, pattern=f"^{C.CB_TAG}")],
        C.GET_PHOTO: [
            MessageHandler(filters.PHOTO, delegates.get_photo_edit),
            MessageHandler(filters.Document.ALL, delegates.reject_document_edit),
            CallbackQueryHandler(delegates.photo_back_edit, pattern="^photo_back$"),
            CallbackQueryHandler(delegates.remove_photo_edit, pattern="^photo_remove$"),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel_edit), *build_implicit_cancel_fallbacks()],
    allow_reentry=True,
    per_message=False,
)
