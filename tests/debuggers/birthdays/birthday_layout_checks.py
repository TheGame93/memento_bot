"""birthday_layout_checks.py — Checks for birthday message layout overhaul.

Covers steps 1-5 of plan_bdaylayout.md:
  Step 1: append_zodiac_block is a public export from scheduler_messagelogic.
  Step 2: user_prefs parameter threaded through format_detailed_card /
          get_info_text_and_kb / _send_alert_detail_with_media_fallback.
  Step 3: format_main_alert birthday path uses new layout (no 📌/📑, header
          "🎂 BIRTHDAY / of `NAME`", age line or year-unknown fallback, tags at end).
  Step 4: format_pre_alert birthday path uses new layout (header, age/mystery,
          countdown, zodiac, tags).
  Step 5: _format_detailed_card birthday path uses new layout (birth date line,
          current age, pre-alerts shown, zodiac block, 🖥 Debug header).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def parse_unknown_args(args: list[str]) -> list[str]:
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


# ---------------------------------------------------------------------------
# Fixtures shared across sections
# ---------------------------------------------------------------------------

def _bday_alert_with_year():
    return {
        "id": "b_layout_01",
        "type": 6,
        "type_name": "Birthday",
        "title": "Mario Rossi",
        "birth_year": 1988,
        "schedule": {"date": "21/03", "time": "09:00"},
        "tags": ["👨‍👩‍👧 Family"],
        "active": True,
        "pre_alerts": [],
    }


def _bday_alert_no_year():
    return {
        "id": "b_layout_02",
        "type": 6,
        "type_name": "Birthday",
        "title": "Lucia Verde",
        "schedule": {"date": "15/06", "time": "09:00"},
        "tags": [],
        "active": True,
        "pre_alerts": [],
    }


def _recurring_alert():
    return {
        "id": "a_layout_01",
        "type": 7,
        "type_name": "Daily",
        "title": "Stand-up Meeting",
        "schedule": {"interval": 1},
        "tags": [],
        "active": True,
        "pre_alerts": [],
        "next_scheduled": "2025-06-15T09:00:00",
    }


# ---------------------------------------------------------------------------
# Section 1: append_zodiac_block public export (Step 1)
# ---------------------------------------------------------------------------

def run_zodiac_public_export_checks(dbg: Any) -> None:
    """Verify append_zodiac_block is importable as a public name."""
    try:
        from modules.scheduler_messagelogic import append_zodiac_block
    except ImportError as exc:
        dbg.section("zodiac_public_export", {"error": str(exc), "skipped": True})
        dbg.problem("zodiac_public_export_import_failed", {"error": str(exc)})
        return

    # Calling with prefs=None must return empty string (mode default is none)
    result_none = append_zodiac_block(_bday_alert_with_year(), None)
    result_no_mode = append_zodiac_block(_bday_alert_with_year(), {})

    # Calling with western mode must return non-empty string for a valid birthday
    try:
        from modules import constants as C
        mode_western = C.BIRTHDAY_ZODIAC_MODE_WESTERN
    except Exception:
        mode_western = "western"

    result_western = append_zodiac_block(
        _bday_alert_with_year(),
        {"birthday_zodiac_mode": mode_western},
    )

    checks = {
        "importable": True,                          # passed the import above
        "none_prefs_returns_empty": result_none == "",
        "empty_prefs_returns_empty": result_no_mode == "",
        "western_mode_non_empty": bool(result_western),
        "western_mode_has_rocket": "🔮" in result_western,
    }

    failures = [k for k, v in checks.items() if not v]
    dbg.section("zodiac_public_export", {
        "checks": checks,
        "failures": failures,
        "result_western_snippet": result_western[:80] if result_western else None,
    })
    if failures:
        dbg.problem("zodiac_public_export_checks_failed", {"failures": failures})


# ---------------------------------------------------------------------------
# Section 2: user_prefs threading (Step 2)
# ---------------------------------------------------------------------------

def run_user_prefs_threading_checks(dbg: Any) -> None:
    """Verify format_detailed_card and get_info_text_and_kb accept user_prefs."""
    try:
        from modules.handlers.list_alerts import format_detailed_card, get_info_text_and_kb
    except ImportError as exc:
        dbg.section("user_prefs_threading", {"error": str(exc), "skipped": True})
        dbg.problem("user_prefs_threading_import_failed", {"error": str(exc)})
        return

    alert = _bday_alert_with_year()

    # Backward compat: no user_prefs arg → must not raise
    try:
        text_no_prefs = format_detailed_card(alert)
        no_prefs_ok = isinstance(text_no_prefs, str)
    except Exception as exc:
        no_prefs_ok = False
        dbg.section("user_prefs_threading", {"error": str(exc), "skipped": True})
        dbg.problem("user_prefs_threading_backward_compat_failed", {"error": str(exc)})
        return

    # Explicit None
    try:
        text_none = format_detailed_card(alert, user_prefs=None)
        none_ok = isinstance(text_none, str)
    except Exception as exc:
        none_ok = False

    # Empty dict
    try:
        text_empty = format_detailed_card(alert, user_prefs={})
        empty_ok = isinstance(text_empty, str)
    except Exception as exc:
        empty_ok = False

    # With zodiac prefs — should not raise (even though zodiac not yet rendered in detail,
    # which is Step 5; for now the prefs are accepted and have no visible effect)
    try:
        from modules import constants as C
        mode = C.BIRTHDAY_ZODIAC_MODE_WESTERN
    except Exception:
        mode = "western"
    try:
        text_prefs = format_detailed_card(alert, user_prefs={"birthday_zodiac_mode": mode})
        prefs_ok = isinstance(text_prefs, str)
    except Exception as exc:
        prefs_ok = False

    # Existing behaviour: age still shown for birthday with birth_year
    age_present = "Current age:" in text_no_prefs
    # Existing behaviour: no age for birthday without birth_year
    alert_no_year = _bday_alert_no_year()
    text_no_year = format_detailed_card(alert_no_year)
    no_age_when_no_year = "Current age:" not in text_no_year

    checks = {
        "backward_compat_no_arg": no_prefs_ok,
        "explicit_none_ok": none_ok,
        "empty_dict_ok": empty_ok,
        "with_zodiac_prefs_ok": prefs_ok,
        "age_shown_with_year": age_present,
        "no_age_without_year": no_age_when_no_year,
    }

    failures = [k for k, v in checks.items() if not v]
    dbg.section("user_prefs_threading", {
        "checks": checks,
        "failures": failures,
        "text_snippet": text_no_prefs[:120] if text_no_prefs else None,
    })
    if failures:
        dbg.problem("user_prefs_threading_checks_failed", {"failures": failures})


# ---------------------------------------------------------------------------
# Section 3: format_main_alert birthday new layout (Step 3)
# ---------------------------------------------------------------------------

def run_alert_message_layout_checks(dbg: Any) -> None:
    """Verify format_main_alert birthday path uses the new layout."""
    try:
        from modules.scheduler_messagelogic import format_main_alert
        from modules import constants as C
    except ImportError as exc:
        dbg.section("alert_message_layout", {"error": str(exc), "skipped": True})
        dbg.problem("alert_message_layout_import_failed", {"error": str(exc)})
        return

    scheduled = datetime(2025, 3, 21, 9, 0)
    scheduled_future = datetime(2026, 3, 21, 9, 0)

    bday_with_year = _bday_alert_with_year()
    bday_no_year = _bday_alert_no_year()
    bday_no_year_sched = datetime(2025, 6, 15, 9, 0)
    recurring = _recurring_alert()

    # --- birthday with known year, no zodiac ---
    msg_bday_known = format_main_alert(bday_with_year, scheduled_future, user_prefs={})

    # --- birthday without year, no zodiac ---
    msg_bday_unknown = format_main_alert(bday_no_year, bday_no_year_sched, user_prefs={})

    # --- birthday with year, western zodiac ---
    msg_bday_west = format_main_alert(
        bday_with_year, scheduled_future,
        user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_WESTERN},
    )

    # --- birthday with year, zodiac=none ---
    msg_bday_no_zodiac = format_main_alert(
        bday_with_year, scheduled_future,
        user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_NONE},
    )

    # --- non-birthday regression ---
    msg_recurring = format_main_alert(recurring, scheduled, user_prefs={})

    # --- birthday with scheduled_time=None (fallback from next_scheduled) ---
    bday_with_next_sched = dict(bday_with_year)
    bday_with_next_sched["next_scheduled"] = "2025-03-21T09:00:00"
    msg_bday_fallback = format_main_alert(bday_with_next_sched, None, user_prefs={})

    checks = {
        # New header structure present
        "bday_known_has_birthday_header": "🎂 BIRTHDAY" in msg_bday_known,
        "bday_known_has_of_line": "of `" in msg_bday_known,
        "bday_known_name_uppercased": "MARIO ROSSI" in msg_bday_known,
        # Age line: turns X
        "bday_known_has_turns": "turns" in msg_bday_known,
        "bday_known_no_year_unknown": "year unknown" not in msg_bday_known,
        # Tags still present
        "bday_known_has_tags": "🏷️ Tags:" in msg_bday_known,
        # Old format NOT present
        "bday_known_no_pin_emoji": "📌" not in msg_bday_known,
        "bday_known_no_type_label": "📑 Type" not in msg_bday_known,
        "bday_known_no_old_bold_header": "**BIRTHDAY**" not in msg_bday_known,

        # No-year birthday: mystery message
        "bday_unknown_has_birthday_header": "🎂 BIRTHDAY" in msg_bday_unknown,
        "bday_unknown_has_year_unknown": "year unknown" in msg_bday_unknown,
        "bday_unknown_has_happy_birthday": "Happy birthday" in msg_bday_unknown,
        "bday_unknown_no_turns": "turns" not in msg_bday_unknown,

        # Zodiac: western mode shows 🔮
        "bday_west_has_zodiac": "🔮" in msg_bday_west,
        "bday_west_no_eastern": "🐉" not in msg_bday_west,
        # Zodiac: none mode shows no zodiac
        "bday_no_zodiac_no_western": "🔮" not in msg_bday_no_zodiac,
        "bday_no_zodiac_no_eastern": "🐉" not in msg_bday_no_zodiac,

        # Non-birthday regression: old format must be preserved
        "recurring_has_alert_header": "🔔 **ALERT**" in msg_recurring,
        "recurring_has_pin": "📌" in msg_recurring,
        "recurring_no_birthday_header": "🎂 BIRTHDAY" not in msg_recurring,

        # Fallback from next_scheduled: no crash
        "bday_fallback_no_crash": isinstance(msg_bday_fallback, str),
        "bday_fallback_has_header": "🎂 BIRTHDAY" in msg_bday_fallback,
    }

    failures = [k for k, v in checks.items() if not v]
    dbg.section("alert_message_layout", {
        "checks": checks,
        "failures": failures,
        "msg_bday_known_snippet": msg_bday_known[:200] if msg_bday_known else None,
        "msg_bday_unknown_snippet": msg_bday_unknown[:200] if msg_bday_unknown else None,
        "msg_recurring_snippet": msg_recurring[:120] if msg_recurring else None,
    })
    if failures:
        dbg.problem("alert_message_layout_checks_failed", {"failures": failures})


# ---------------------------------------------------------------------------
# Section 4: format_main_alert tags at end — tag position regression
# ---------------------------------------------------------------------------

def run_alert_tags_position_checks(dbg: Any) -> None:
    """Verify tags line is last meaningful content in birthday alert messages."""
    try:
        from modules.scheduler_messagelogic import format_main_alert
        from modules import constants as C
    except ImportError as exc:
        dbg.section("alert_tags_position", {"error": str(exc), "skipped": True})
        dbg.problem("alert_tags_position_import_failed", {"error": str(exc)})
        return

    scheduled = datetime(2025, 3, 21, 9, 0)
    bday = _bday_alert_with_year()

    # No zodiac
    msg_no_zodiac = format_main_alert(bday, scheduled, user_prefs={})
    # With western zodiac
    msg_western = format_main_alert(
        bday, scheduled,
        user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_WESTERN},
    )

    def tags_after_age(msg):
        """Tags line must appear after the age/turns line."""
        tag_idx = msg.find("🏷️ Tags:")
        turns_idx = msg.find("turns")
        if tag_idx == -1 or turns_idx == -1:
            return False
        return tag_idx > turns_idx

    def tags_after_zodiac(msg):
        """Tags line must appear after zodiac emojis when present."""
        tag_idx = msg.find("🏷️ Tags:")
        zodiac_idx = msg.find("🔮")
        if tag_idx == -1 or zodiac_idx == -1:
            return True   # no zodiac, nothing to check
        return tag_idx > zodiac_idx

    checks = {
        "tags_after_age_no_zodiac": tags_after_age(msg_no_zodiac),
        "tags_after_age_with_zodiac": tags_after_age(msg_western),
        "tags_after_zodiac_block": tags_after_zodiac(msg_western),
    }

    failures = [k for k, v in checks.items() if not v]
    dbg.section("alert_tags_position", {"checks": checks, "failures": failures})
    if failures:
        dbg.problem("alert_tags_position_checks_failed", {"failures": failures})


# ---------------------------------------------------------------------------
# Section 5: format_pre_alert birthday new layout (Step 4)
# ---------------------------------------------------------------------------

def run_prealert_message_layout_checks(dbg: Any) -> None:
    """Verify format_pre_alert birthday path uses the new layout."""
    try:
        from modules.scheduler_messagelogic import format_pre_alert
        from modules import constants as C
    except ImportError as exc:
        dbg.section("prealert_message_layout", {"error": str(exc), "skipped": True})
        dbg.problem("prealert_message_layout_import_failed", {"error": str(exc)})
        return

    main_time = datetime(2026, 3, 21, 9, 0)
    pre_time = datetime(2026, 3, 19, 9, 0)
    bday_with_year = _bday_alert_with_year()
    bday_no_year = _bday_alert_no_year()
    recurring = _recurring_alert()

    # birthday with year, no zodiac
    msg_known = format_pre_alert(bday_with_year, main_time, pre_time, user_prefs={})
    # birthday without year, no zodiac
    msg_unknown = format_pre_alert(bday_no_year, main_time, pre_time, user_prefs={})
    # birthday with year, western zodiac
    msg_western = format_pre_alert(
        bday_with_year, main_time, pre_time,
        user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_WESTERN},
    )
    # birthday with year, zodiac=none
    msg_no_zodiac = format_pre_alert(
        bday_with_year, main_time, pre_time,
        user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_NONE},
    )
    # non-birthday regression (no user_prefs)
    msg_recurring = format_pre_alert(recurring, main_time, pre_time)
    # main_trigger_time=None: no crash
    msg_none_trigger = format_pre_alert(bday_with_year, None, pre_time, user_prefs={})

    checks = {
        # New header
        "known_has_upcoming_birthday_header": "🎂 UPCOMING BIRTHDAY" in msg_known,
        "known_has_of_line": "of `" in msg_known,
        "known_name_uppercased": "MARIO ROSSI" in msg_known,
        # Age line (use bold marker to distinguish from countdown "will be on")
        "known_has_will_be": "will be **" in msg_known,
        "known_no_mystery": "mystery" not in msg_known,
        # Countdown line
        "known_has_countdown": "The birthday will be on" in msg_known,
        "known_has_date_code": "`21/03`" in msg_known,
        # Tags
        "known_has_tags": "🏷️ Tags:" in msg_known,
        # Old format NOT present
        "known_no_old_upcoming_header": "**UPCOMING BIRTHDAY**" not in msg_known,
        "known_no_pin_emoji": "📌" not in msg_known,
        "known_no_old_due_in_line": "This alert is due in" not in msg_known,

        # No-year birthday: mystery line
        "unknown_has_mystery": "mystery" in msg_unknown,
        "unknown_no_will_be": "will be **" not in msg_unknown,
        "unknown_has_countdown": "The birthday will be on" in msg_unknown,

        # Zodiac: western mode shows 🔮
        "western_has_zodiac": "🔮" in msg_western,
        # Zodiac: none mode shows no zodiac
        "no_zodiac_no_western": "🔮" not in msg_no_zodiac,

        # Non-birthday regression: old upcoming format preserved
        "recurring_has_upcoming_alert_header": "⏳ **UPCOMING ALERT**" in msg_recurring,
        "recurring_has_due_in": "This alert is due in" in msg_recurring,
        "recurring_no_birthday_header": "🎂 UPCOMING BIRTHDAY" not in msg_recurring,

        # None trigger: no crash
        "none_trigger_no_crash": isinstance(msg_none_trigger, str),
        "none_trigger_has_header": "🎂 UPCOMING BIRTHDAY" in msg_none_trigger,
    }

    failures = [k for k, v in checks.items() if not v]
    dbg.section("prealert_message_layout", {
        "checks": checks,
        "failures": failures,
        "msg_known_snippet": msg_known[:200] if msg_known else None,
        "msg_unknown_snippet": msg_unknown[:200] if msg_unknown else None,
        "msg_recurring_snippet": msg_recurring[:120] if msg_recurring else None,
    })
    if failures:
        dbg.problem("prealert_message_layout_checks_failed", {"failures": failures})


# ---------------------------------------------------------------------------
# Section 6: _format_detailed_card birthday new layout (Step 5)
# ---------------------------------------------------------------------------

def run_detail_card_layout_checks(dbg: Any) -> None:
    """Verify format_detailed_card birthday path uses the new layout."""
    try:
        from modules.handlers.list_alerts import format_detailed_card
        from modules import constants as C
    except ImportError as exc:
        dbg.section("detail_card_layout", {"error": str(exc), "skipped": True})
        dbg.problem("detail_card_layout_import_failed", {"error": str(exc)})
        return

    bday_with_year = _bday_alert_with_year()
    bday_no_year = _bday_alert_no_year()
    bday_with_prealerts = dict(_bday_alert_with_year())
    bday_with_prealerts["pre_alerts"] = ["2d", "bday_evening_before"]

    recurring = _recurring_alert()

    # birthday with year, no zodiac
    card_known = format_detailed_card(bday_with_year, user_prefs={})
    # birthday no year, no zodiac
    card_no_year = format_detailed_card(bday_no_year, user_prefs={})
    # birthday with year, western zodiac
    card_western = format_detailed_card(
        bday_with_year,
        user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_WESTERN},
    )
    # birthday with pre-alerts
    card_prealerts = format_detailed_card(bday_with_prealerts, user_prefs={})
    # non-birthday regression (no user_prefs)
    card_recurring = format_detailed_card(recurring)

    checks = {
        # New header: status dot + NAME (no bold)
        "known_has_status_dot": "🟢" in card_known,
        "known_name_uppercased": "MARIO ROSSI" in card_known,
        "known_no_bold_name": "**MARIO ROSSI**" not in card_known,

        # Birth date line
        "known_has_birth_date": "Birth date:" in card_known,
        "known_has_birth_year": "1988" in card_known,
        "known_no_next_scheduled": "Next Scheduled:" not in card_known,

        # Current age shown
        "known_has_current_age": "🎂 Current age:" in card_known,
        # No backticks around age (new format)
        "known_age_no_backticks": "Current age: `" not in card_known,

        # Tags present
        "known_has_tags": "Family" in card_known,

        # Old format NOT present
        "known_no_type_label": "📑 Type" not in card_known,

        # No year: year unknown shown, no age
        "no_year_has_birth_date": "Birth date:" in card_no_year,
        "no_year_has_year_unknown": "year unknown" in card_no_year,
        "no_year_no_current_age": "🎂 Current age:" not in card_no_year,

        # Western zodiac shown in detail card
        "western_has_zodiac": "🔮" in card_western,

        # Pre-alerts shown for birthday
        "prealerts_has_prealert_line": "🔔 Pre-alert:" in card_prealerts,
        "prealerts_has_resolved_first_time": "09:00" in card_prealerts,
        "prealerts_has_resolved_evening_time": "21:00" in card_prealerts,
        "prealerts_uses_datetime_labels": "/" in card_prealerts,
        "prealerts_no_human_evening_label": "evening before" not in card_prealerts,
        "prealerts_no_human_duration_label": "2 days" not in card_prealerts,

        # Non-birthday regression: old format preserved
        "recurring_has_next_scheduled": "Next Scheduled:" in card_recurring,
        "recurring_has_type_label": "📑 Type" in card_recurring,
        "recurring_no_birth_date": "Birth date:" not in card_recurring,
        "recurring_no_birthday_age": "🎂 Current age:" not in card_recurring,
    }

    failures = [k for k, v in checks.items() if not v]
    dbg.section("detail_card_layout", {
        "checks": checks,
        "failures": failures,
        "card_known_snippet": card_known[:250] if card_known else None,
        "card_no_year_snippet": card_no_year[:200] if card_no_year else None,
        "card_recurring_snippet": card_recurring[:150] if card_recurring else None,
    })
    if failures:
        dbg.problem("detail_card_layout_checks_failed", {"failures": failures})


# ---------------------------------------------------------------------------
# Section 6: new format_pb / format_bb layout (Step 5 of plan_refactormessage)
# ---------------------------------------------------------------------------

def run_new_birthday_format_checks(dbg: Any) -> None:
    """Verify format_pb and format_bb from modules.ui.formatters.birthday_text."""
    try:
        from modules.ui.formatters.birthday_text import format_pb, format_bb
    except ImportError as exc:
        dbg.section("new_birthday_format", {"error": str(exc), "skipped": True})
        dbg.problem("new_birthday_format_import_failed", {"error": str(exc)})
        return

    fire_time = datetime(2025, 3, 21, 8, 0)

    bday = _bday_alert_with_year()
    bday_no_year = _bday_alert_no_year()

    pb_text = format_pb(bday, fire_time)
    pb_no_year_text = format_pb(bday_no_year, fire_time)
    bb_text = format_bb(bday, scheduled_time=fire_time)
    bb_no_year_text = format_bb(bday_no_year, scheduled_time=fire_time)

    checks = {
        # PB structural checks
        "pb_has_upcoming_header": "UPCOMING ALERT" in pb_text,
        "pb_has_countdown": "due in" in pb_text,
        "pb_has_scheduled": "Scheduled:" in pb_text,
        "pb_has_birthday_of": "Birthday of" in pb_text,
        "pb_has_name_caps": "MARIO ROSSI" in pb_text,
        "pb_has_will_turn": "will turn" in pb_text,
        "pb_no_zodiac": "🔮" not in pb_text and "🐉" not in pb_text,
        "pb_has_tags": "Family" in pb_text,
        "pb_mystery_when_no_year": "mystery" in pb_no_year_text.lower(),

        # BB structural checks
        "bb_has_birthday_of": "Birthday of" in bb_text,
        "bb_has_name_caps": "MARIO ROSSI" in bb_text,
        "bb_has_turns_today": "turns" in bb_text and "today" in bb_text,
        "bb_no_zodiac_without_prefs": "🔮" not in bb_text,
        "bb_has_tags": "Family" in bb_text,
        "bb_mystery_when_no_year": "mystery" in bb_no_year_text.lower(),

        # Wording distinction: PB uses 'will turn', BB uses 'turns today'
        "pb_no_turns_today": "turns" not in pb_text or "today" not in pb_text,
        "bb_no_will_turn": "will turn" not in bb_text,
    }

    failures = [k for k, v in checks.items() if not v]
    dbg.section("new_birthday_format", {
        "checks": checks,
        "failures": failures,
        "pb_snippet": pb_text[:250],
        "bb_snippet": bb_text[:250],
    })
    if failures:
        dbg.problem("new_birthday_format_checks_failed", {"failures": failures})
