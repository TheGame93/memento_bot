"""Provide add-flow delegation wrappers for edit-flow conversation states."""

from telegram import Update
from telegram.ext import ContextTypes

from modules import constants as C
from modules.handlers.add_flow.flow_start import (
    prompt_type_specific as _prompt_type_specific_impl,
)
from modules.handlers.add_flow.media_flow import (
    get_photo as _get_photo_impl,
    photo_back as _photo_back_impl,
    reject_document as _reject_document_impl,
    remove_photo as _remove_photo_impl,
    show_photo_menu as _show_photo_menu_impl,
)
from modules.handlers.add_flow.repetition_flow import (
    handle_repetition_choice as _handle_repetition_choice_impl,
    handle_repetition_count_input as _handle_repetition_count_input_impl,
    handle_repetition_until_date_input as _handle_repetition_until_date_input_impl,
    prompt_repetition_count as _prompt_repetition_count_impl,
    prompt_repetition_until_date as _prompt_repetition_until_date_impl,
    show_repetition_menu as _show_repetition_menu_impl,
)
from modules.handlers.add_flow.settings_flow import (
    _change_type_callback_impl,
    handle_additional_info_clear as _handle_additional_info_clear_impl,
    handle_additional_info_input as _handle_additional_info_input_impl,
    handle_additional_info_skip as _handle_additional_info_skip_impl,
    prompt_additional_info as _prompt_additional_info_impl,
)
from modules.handlers.add_flow.type_flow import (
    ask_time as _ask_time_impl,
    confirm_custom_pre_alert as _confirm_custom_pre_alert_impl,
    daily_interval_confirm_callback as _daily_interval_confirm_callback_impl,
    fuzzy_mean_std_input as _fuzzy_mean_std_input_impl,
    get_custom_pre_alert_input as _get_custom_pre_alert_input_impl,
    get_interval_callback as _get_interval_callback_impl,
    get_interval_input as _get_interval_input_impl,
    get_interval_prompt as _get_interval_prompt_impl,
    get_pre_alert_callback as _get_pre_alert_callback_impl,
    get_start_date_callback as _get_start_date_callback_impl,
    get_start_date_input as _get_start_date_input_impl,
    get_time_callback as _get_time_callback_impl,
    get_time_input as _get_time_input_impl,
    interval_mode_choice_callback as _interval_mode_choice_callback_impl,
    show_pre_alert_menu as _show_pre_alert_menu_impl,
    tags_toggle as _tags_toggle_impl,
    type_1_days as _type_1_days_impl,
    type_2_fifth_policy as _type_2_fifth_policy_impl,
    type_2_ordinal as _type_2_ordinal_impl,
    type_2_weekday as _type_2_weekday_impl,
    type_3_weekdays as _type_3_weekdays_impl,
    type_4_dates as _type_4_dates_impl,
    type_5_date as _type_5_date_impl,
)
from modules.shared.context_cleanup import require_temp_alert

from .origin import (
    _track_edit_callback_message,
    _track_edit_incoming_message,
)

_RETURN_TO_EDIT = None
_SHOW_EDIT_DASHBOARD = None


def configure_edit_dependencies(*, return_to_edit, show_edit_dashboard):
    """Configure flow-owned callback dependencies used by delegation wrappers."""
    global _RETURN_TO_EDIT, _SHOW_EDIT_DASHBOARD
    _RETURN_TO_EDIT = return_to_edit
    _SHOW_EDIT_DASHBOARD = show_edit_dashboard


def _require_return_to_edit():
    if _RETURN_TO_EDIT is None:
        raise RuntimeError("edit_flow.delegates return_to_edit callback is not configured")
    return _RETURN_TO_EDIT


def _require_show_edit_dashboard():
    if _SHOW_EDIT_DASHBOARD is None:
        raise RuntimeError("edit_flow.delegates show_edit_dashboard callback is not configured")
    return _SHOW_EDIT_DASHBOARD


async def ask_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate edit-flow time prompting to the shared add-flow implementation."""
    _track_edit_callback_message(update, context)
    return await _ask_time_impl(update, context)


async def prompt_type_specific_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate type-specific schedule prompting for edit flow."""
    _track_edit_callback_message(update, context)
    return await _prompt_type_specific_impl(
        update,
        context,
        get_interval_prompt=get_interval_prompt_edit,
    )


async def get_interval_prompt_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the shared interval prompt and return to edit flow context."""
    _track_edit_callback_message(update, context)
    return await _get_interval_prompt_impl(update, context, _require_show_edit_dashboard())


@require_temp_alert
async def get_interval_input_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate interval text input handling for edit flow."""
    _track_edit_incoming_message(update, context)
    return await _get_interval_input_impl(update, context, _require_show_edit_dashboard())


@require_temp_alert
async def get_interval_callback_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate interval quick-button handling for edit flow."""
    _track_edit_callback_message(update, context)
    return await _get_interval_callback_impl(update, context, _require_return_to_edit())


@require_temp_alert
async def daily_interval_confirm_callback_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate daily-interval confirmation handling for edit flow."""
    _track_edit_callback_message(update, context)
    return await _daily_interval_confirm_callback_impl(
        update,
        context,
        _require_return_to_edit(),
        get_interval_prompt_edit,
    )


@require_temp_alert
async def interval_mode_choice_callback_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate daily interval mode choice callbacks while keeping edit-flow context."""
    _track_edit_callback_message(update, context)
    return await _interval_mode_choice_callback_impl(update, context)


@require_temp_alert
async def fuzzy_mean_std_input_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate daily fuzzy mean/std parsing while returning to the edit dashboard."""
    _track_edit_incoming_message(update, context)
    return await _fuzzy_mean_std_input_impl(update, context, _require_show_edit_dashboard())


@require_temp_alert
async def get_start_date_callback_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate start-date callback handling for edit flow."""
    _track_edit_callback_message(update, context)
    return await _get_start_date_callback_impl(update, context, _require_show_edit_dashboard())


@require_temp_alert
async def get_start_date_input_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate start-date text input handling for edit flow."""
    _track_edit_incoming_message(update, context)
    return await _get_start_date_input_impl(update, context, _require_show_edit_dashboard())


@require_temp_alert
async def get_time_input_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate time text input handling for edit flow."""
    _track_edit_incoming_message(update, context)
    return await _get_time_input_impl(update, context, _require_show_edit_dashboard())


@require_temp_alert
async def get_time_callback_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate default-time callback handling for edit flow."""
    _track_edit_callback_message(update, context)
    return await _get_time_callback_impl(update, context, _require_show_edit_dashboard())


async def show_pre_alert_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate pre-alert menu rendering to shared add-flow handlers."""
    _track_edit_callback_message(update, context)
    return await _show_pre_alert_menu_impl(update, context)


@require_temp_alert
async def get_pre_alert_callback_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate pre-alert callback handling while returning to edit flow."""
    _track_edit_callback_message(update, context)
    return await _get_pre_alert_callback_impl(update, context, _require_return_to_edit())


@require_temp_alert
async def get_custom_pre_alert_input_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate custom pre-alert parsing and preview handling for edits."""
    _track_edit_incoming_message(update, context)
    return await _get_custom_pre_alert_input_impl(update, context)


@require_temp_alert
async def confirm_custom_pre_alert_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate custom pre-alert confirmation handling for edits."""
    _track_edit_callback_message(update, context)
    return await _confirm_custom_pre_alert_impl(update, context, _require_return_to_edit())


async def show_photo_menu_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate photo menu rendering to shared add-flow handlers."""
    _track_edit_callback_message(update, context)
    return await _show_photo_menu_impl(update, context)


@require_temp_alert
async def show_repetition_menu_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show repetition options and normalize unsupported returns for edit flow."""
    _track_edit_callback_message(update, context)
    state = await _show_repetition_menu_impl(update, context)
    if state == C.MULTI_SETTINGS:
        return C.EDIT_DASHBOARD
    return state


async def prompt_repetition_until_date_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate repetition-until prompt rendering for edit flow."""
    _track_edit_callback_message(update, context)
    return await _prompt_repetition_until_date_impl(update, context)


async def prompt_repetition_count_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate repetition-count prompt rendering for edit flow."""
    _track_edit_callback_message(update, context)
    return await _prompt_repetition_count_impl(update, context)


@require_temp_alert
async def handle_repetition_choice_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate repetition mode choice handling for edit flow."""
    _track_edit_callback_message(update, context)
    return await _handle_repetition_choice_impl(
        update,
        context,
        _require_return_to_edit(),
        prompt_repetition_until_date_edit,
        prompt_repetition_count_edit,
    )


@require_temp_alert
async def handle_repetition_until_date_input_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate repetition-until input handling for edit flow."""
    _track_edit_incoming_message(update, context)
    return await _handle_repetition_until_date_input_impl(update, context, _require_return_to_edit())


@require_temp_alert
async def handle_repetition_count_input_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate repetition-count input handling for edit flow."""
    _track_edit_incoming_message(update, context)
    return await _handle_repetition_count_input_impl(update, context, _require_return_to_edit())


@require_temp_alert
async def get_photo_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate photo upload handling for edit flow."""
    _track_edit_incoming_message(update, context)
    return await _get_photo_impl(update, context, _require_show_edit_dashboard())


@require_temp_alert
async def reject_document_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate document rejection handling for edit flow."""
    _track_edit_incoming_message(update, context)
    return await _reject_document_impl(update, context)


@require_temp_alert
async def photo_back_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate photo-step back navigation for edit flow."""
    _track_edit_callback_message(update, context)
    return await _photo_back_impl(update, context, _require_show_edit_dashboard())


@require_temp_alert
async def remove_photo_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate staged photo removal for edit flow."""
    _track_edit_callback_message(update, context)
    return await _remove_photo_impl(update, context, _require_show_edit_dashboard())


async def prompt_additional_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate additional-info prompting for edit flow."""
    _track_edit_callback_message(update, context)
    return await _prompt_additional_info_impl(update, context)


@require_temp_alert
async def handle_additional_info_input_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate additional-info input handling for edit flow."""
    _track_edit_incoming_message(update, context)
    return await _handle_additional_info_input_impl(update, context, _require_return_to_edit())


@require_temp_alert
async def handle_additional_info_skip_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate additional-info skip handling for edit flow."""
    _track_edit_callback_message(update, context)
    return await _handle_additional_info_skip_impl(update, context, _require_return_to_edit())


@require_temp_alert
async def handle_additional_info_clear_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate explicit Additional Info clear handling and return to edit dashboard context."""
    _track_edit_callback_message(update, context)
    return await _handle_additional_info_clear_impl(update, context, _require_return_to_edit())


@require_temp_alert
async def type_1_days_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate monthly-days schedule handling for edit flow."""
    _track_edit_incoming_message(update, context)
    return await _type_1_days_impl(update, context, _require_show_edit_dashboard())


@require_temp_alert
async def type_2_ordinal_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate relative-month ordinal handling for edit flow."""
    _track_edit_callback_message(update, context)
    return await _type_2_ordinal_impl(update, context, get_interval_prompt_edit)


@require_temp_alert
async def type_2_fifth_policy_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate fifth-occurrence policy handling for edit flow."""
    _track_edit_callback_message(update, context)
    return await _type_2_fifth_policy_impl(update, context)


@require_temp_alert
async def type_2_weekday_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate relative-month weekday handling for edit flow."""
    _track_edit_callback_message(update, context)
    return await _type_2_weekday_impl(update, context, _require_show_edit_dashboard())


@require_temp_alert
async def type_3_weekdays_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate weekly weekday handling for edit flow."""
    _track_edit_callback_message(update, context)
    return await _type_3_weekdays_impl(update, context, _require_show_edit_dashboard())


@require_temp_alert
async def type_4_dates_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate yearly date handling for edit flow."""
    _track_edit_incoming_message(update, context)
    return await _type_4_dates_impl(update, context, _require_show_edit_dashboard())


@require_temp_alert
async def type_5_date_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate one-time date handling for edit flow."""
    _track_edit_incoming_message(update, context)
    return await _type_5_date_impl(update, context, _require_show_edit_dashboard())


@require_temp_alert
async def tags_toggle_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate tag toggle handling for edit flow."""
    _track_edit_callback_message(update, context)
    return await _tags_toggle_impl(update, context, _require_show_edit_dashboard())


@require_temp_alert
async def handle_change_type_callback_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate type-change callbacks while preserving edit routing."""
    _track_edit_callback_message(update, context)
    return await _change_type_callback_impl(
        update,
        context,
        _require_return_to_edit(),
        prompt_type_specific_edit,
    )
