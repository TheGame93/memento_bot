import asyncio
import json
import os
import sys
import tempfile
import types
from datetime import date, datetime, timedelta


def run_support_checks(utils_mod):
    checks = {
        "supports_type_1": utils_mod.is_repetition_supported(1),
        "supports_type_7": utils_mod.is_repetition_supported(7),
        "rejects_one_time": not utils_mod.is_repetition_supported(5),
        "rejects_birthday": not utils_mod.is_repetition_supported(6),
        "rejects_invalid": not utils_mod.is_repetition_supported("x"),
    }
    return {"checks": checks}


def run_default_payload_checks(utils_mod, constants_mod):
    recurring_payload = utils_mod.default_repetition_payload(1)
    unsupported_payload = utils_mod.default_repetition_payload(5)
    checks = {
        "default_exists_for_supported": isinstance(recurring_payload, dict),
        "default_mode_forever": isinstance(recurring_payload, dict) and recurring_payload.get("mode") == constants_mod.REPETITION_MODE_FOREVER,
        "default_until_none": isinstance(recurring_payload, dict) and recurring_payload.get("until_date") is None,
        "default_count_none": isinstance(recurring_payload, dict) and recurring_payload.get("count_remaining") is None,
        "unsupported_none": unsupported_payload is None,
    }
    return {
        "recurring_payload": recurring_payload,
        "unsupported_payload": unsupported_payload,
        "checks": checks,
    }


def run_parse_until_date_checks(utils_mod):
    ok = utils_mod.parse_until_date_strict("21/04/2027")
    bad_format = utils_mod.parse_until_date_strict("21/4/2027")
    bad_date = utils_mod.parse_until_date_strict("31/11/2027")
    leap_ok = utils_mod.parse_until_date_strict("29/02/2028")
    leap_bad = utils_mod.parse_until_date_strict("29/02/2027")
    checks = {
        "ok_parse": ok == date(2027, 4, 21),
        "reject_non_strict_format": bad_format is None,
        "reject_invalid_calendar_date": bad_date is None,
        "leap_day_ok": leap_ok == date(2028, 2, 29),
        "leap_day_invalid_non_leap": leap_bad is None,
    }
    return {
        "ok_parse": ok.isoformat() if ok else None,
        "leap_ok": leap_ok.isoformat() if leap_ok else None,
        "checks": checks,
    }


def run_parse_until_date_input_checks(utils_mod):
    ok_short, short_assumed = utils_mod.parse_until_date_input("3/4/27")
    ok_full, full_assumed = utils_mod.parse_until_date_input("03/04/2027")
    bad_format, _ = utils_mod.parse_until_date_input("03-04-2027")
    bad_date, _ = utils_mod.parse_until_date_input("31/11/2027")
    leap_short, leap_short_assumed = utils_mod.parse_until_date_input("29/2/28")
    leap_short_bad, _ = utils_mod.parse_until_date_input("29/2/27")
    checks = {
        "short_ok_parse": ok_short == date(2027, 4, 3),
        "short_marks_two_digit_year": short_assumed is True,
        "full_ok_parse": ok_full == date(2027, 4, 3),
        "full_marks_four_digit_year": full_assumed is False,
        "reject_bad_format": bad_format is None,
        "reject_bad_date": bad_date is None,
        "leap_short_ok": leap_short == date(2028, 2, 29),
        "leap_short_marks_two_digit_year": leap_short_assumed is True,
        "leap_short_bad_rejected": leap_short_bad is None,
    }
    return {
        "ok_short": ok_short.isoformat() if ok_short else None,
        "ok_full": ok_full.isoformat() if ok_full else None,
        "leap_short": leap_short.isoformat() if leap_short else None,
        "checks": checks,
    }


def run_normalize_payload_checks(utils_mod, constants_mod):
    normalized_forever = utils_mod.normalize_repetition_payload(1, {"mode": "forever"})
    normalized_until = utils_mod.normalize_repetition_payload(1, {"mode": "until_date", "until_date": "31/12/2027"})
    normalized_count = utils_mod.normalize_repetition_payload(1, {"mode": "count", "count_remaining": "3"})
    normalized_exhausted = utils_mod.normalize_repetition_payload(1, {"mode": "count", "count_remaining": 0})
    normalized_invalid = utils_mod.normalize_repetition_payload(1, {"mode": "count", "count_remaining": -1})
    unsupported = utils_mod.normalize_repetition_payload(6, {"mode": "count", "count_remaining": 5})
    checks = {
        "forever_mode_ok": normalized_forever.get("mode") == constants_mod.REPETITION_MODE_FOREVER,
        "until_mode_ok": normalized_until.get("mode") == constants_mod.REPETITION_MODE_UNTIL_DATE,
        "until_date_kept": normalized_until.get("until_date") == "31/12/2027",
        "count_mode_ok": normalized_count.get("mode") == constants_mod.REPETITION_MODE_COUNT,
        "count_value_coerced": normalized_count.get("count_remaining") == 3,
        "count_zero_preserved": normalized_exhausted.get("count_remaining") == 0,
        "invalid_falls_back_forever": normalized_invalid.get("mode") == constants_mod.REPETITION_MODE_FOREVER,
        "unsupported_is_none": unsupported is None,
    }
    return {
        "normalized_forever": normalized_forever,
        "normalized_until": normalized_until,
        "normalized_count": normalized_count,
        "normalized_exhausted": normalized_exhausted,
        "normalized_invalid": normalized_invalid,
        "unsupported": unsupported,
        "checks": checks,
    }


def run_format_human_checks(utils_mod):
    forever_text = utils_mod.format_repetition_human(1, {"mode": "forever"})
    until_text = utils_mod.format_repetition_human(1, {"mode": "until_date", "until_date": "31/12/2027"})
    count_text_single = utils_mod.format_repetition_human(1, {"mode": "count", "count_remaining": 1})
    count_text_plural = utils_mod.format_repetition_human(1, {"mode": "count", "count_remaining": 4})
    unsupported_text = utils_mod.format_repetition_human(5, {"mode": "count", "count_remaining": 4})
    checks = {
        "forever_text": forever_text == "Forever",
        "until_text": until_text == "Until 31/12/2027 (inclusive)",
        "count_singular_text": count_text_single == "Next 1 event",
        "count_plural_text": count_text_plural == "Next 4 events",
        "unsupported_text": unsupported_text == "N/A",
    }
    return {
        "forever_text": forever_text,
        "until_text": until_text,
        "count_text_single": count_text_single,
        "count_text_plural": count_text_plural,
        "unsupported_text": unsupported_text,
        "checks": checks,
    }


def run_candidate_allowed_checks(utils_mod):
    recurring_allowed = utils_mod.candidate_allowed_by_repetition(
        1, {"mode": "forever"}, datetime(2027, 1, 1, 10, 0)
    )
    until_allowed = utils_mod.candidate_allowed_by_repetition(
        1, {"mode": "until_date", "until_date": "31/12/2027"}, datetime(2027, 12, 31, 23, 59)
    )
    until_blocked = utils_mod.candidate_allowed_by_repetition(
        1, {"mode": "until_date", "until_date": "31/12/2027"}, datetime(2028, 1, 1, 0, 0)
    )
    count_allowed = utils_mod.candidate_allowed_by_repetition(
        1, {"mode": "count", "count_remaining": 2}, datetime(2027, 1, 1, 10, 0)
    )
    count_blocked = utils_mod.candidate_allowed_by_repetition(
        1, {"mode": "count", "count_remaining": 0}, datetime(2027, 1, 1, 10, 0)
    )
    unsupported_passthrough = utils_mod.candidate_allowed_by_repetition(
        5, {"mode": "count", "count_remaining": 0}, datetime(2027, 1, 1, 10, 0)
    )
    checks = {
        "forever_allowed": recurring_allowed,
        "until_inclusive_allowed": until_allowed,
        "until_after_blocked": not until_blocked,
        "count_positive_allowed": count_allowed,
        "count_zero_blocked": not count_blocked,
        "unsupported_passthrough": unsupported_passthrough,
    }
    return {
        "checks": checks,
    }


def run_decrement_checks(utils_mod, constants_mod):
    normalized_1, before_1, after_1, exhausted_1 = utils_mod.decrement_count_if_needed(
        {"mode": "count", "count_remaining": 3}, should_count=True
    )
    normalized_2, before_2, after_2, exhausted_2 = utils_mod.decrement_count_if_needed(
        {"mode": "count", "count_remaining": 1}, should_count=True
    )
    normalized_3, before_3, after_3, exhausted_3 = utils_mod.decrement_count_if_needed(
        {"mode": "count", "count_remaining": 4}, should_count=False
    )
    normalized_4, before_4, after_4, exhausted_4 = utils_mod.decrement_count_if_needed(
        {"mode": "forever"}, should_count=True
    )
    checks = {
        "decrements_when_counted": before_1 == 3 and after_1 == 2 and not exhausted_1,
        "exhausts_at_zero": before_2 == 1 and after_2 == 0 and exhausted_2,
        "no_decrement_when_not_counted": before_3 == 4 and after_3 == 4 and not exhausted_3,
        "forever_passthrough_before_none": before_4 is None,
        "forever_passthrough_after_none": after_4 is None,
        "forever_not_exhausted": not exhausted_4,
        "mode_stays_count": normalized_1.get("mode") == constants_mod.REPETITION_MODE_COUNT,
        "mode_stays_forever": normalized_4.get("mode") == constants_mod.REPETITION_MODE_FOREVER,
    }
    return {
        "normalized_1": normalized_1,
        "normalized_2": normalized_2,
        "normalized_3": normalized_3,
        "normalized_4": normalized_4,
        "before_after": {
            "case1": [before_1, after_1, exhausted_1],
            "case2": [before_2, after_2, exhausted_2],
            "case3": [before_3, after_3, exhausted_3],
            "case4": [before_4, after_4, exhausted_4],
        },
        "checks": checks,
    }


def run_mathlogic_repetition_checks(math_mod, constants_mod):
    count_zero_next = math_mod.get_next_occurrence(
        {
            "type": 7,
            "schedule": {"time": "10:00", "interval": 1},
            "repetition": {"mode": constants_mod.REPETITION_MODE_COUNT, "count_remaining": 0},
        },
        datetime(2027, 1, 1, 9, 30),
    )
    count_positive_next = math_mod.get_next_occurrence(
        {
            "type": 7,
            "schedule": {"time": "10:00", "interval": 1},
            "repetition": {"mode": constants_mod.REPETITION_MODE_COUNT, "count_remaining": 2},
        },
        datetime(2027, 1, 1, 9, 30),
    )
    until_inclusive_next = math_mod.get_next_occurrence(
        {
            "type": 7,
            "schedule": {"time": "10:00", "interval": 1},
            "repetition": {"mode": constants_mod.REPETITION_MODE_UNTIL_DATE, "until_date": "01/01/2027"},
        },
        datetime(2027, 1, 1, 9, 30),
    )
    until_after_none = math_mod.get_next_occurrence(
        {
            "type": 7,
            "schedule": {"time": "10:00", "interval": 1},
            "repetition": {"mode": constants_mod.REPETITION_MODE_UNTIL_DATE, "until_date": "01/01/2027"},
        },
        datetime(2027, 1, 1, 10, 30),
    )
    yearly_inclusive_next = math_mod.get_next_occurrence(
        {
            "type": 4,
            "schedule": {"dates": ["01/01"], "time": "10:00", "interval": 1},
            "repetition": {"mode": constants_mod.REPETITION_MODE_UNTIL_DATE, "until_date": "01/01/2027"},
        },
        datetime(2026, 12, 31, 12, 0),
    )
    yearly_after_none = math_mod.get_next_occurrence(
        {
            "type": 4,
            "schedule": {"dates": ["01/01"], "time": "10:00", "interval": 1},
            "repetition": {"mode": constants_mod.REPETITION_MODE_UNTIL_DATE, "until_date": "01/01/2027"},
        },
        datetime(2027, 1, 1, 10, 30),
    )
    one_time_unaffected = math_mod.get_next_occurrence(
        {
            "type": 5,
            "schedule": {"date": "02/01/2027", "time": "10:00"},
            "repetition": {"mode": constants_mod.REPETITION_MODE_COUNT, "count_remaining": 0},
        },
        datetime(2027, 1, 1, 9, 0),
    )
    birthday_unaffected = math_mod.get_next_occurrence(
        {
            "type": 6,
            "schedule": {"date": "02/01", "time": "08:00"},
            "repetition": {"mode": constants_mod.REPETITION_MODE_COUNT, "count_remaining": 0},
        },
        datetime(2027, 1, 1, 9, 0),
    )

    checks = {
        "count_zero_returns_none": count_zero_next is None,
        "count_positive_returns_candidate": isinstance(count_positive_next, datetime)
        and count_positive_next == datetime(2027, 1, 1, 10, 0),
        "until_inclusive_allowed_same_date": isinstance(until_inclusive_next, datetime)
        and until_inclusive_next == datetime(2027, 1, 1, 10, 0),
        "until_after_date_returns_none": until_after_none is None,
        "yearly_inclusive_allowed": isinstance(yearly_inclusive_next, datetime)
        and yearly_inclusive_next == datetime(2027, 1, 1, 10, 0),
        "yearly_after_until_none": yearly_after_none is None,
        "one_time_unaffected": isinstance(one_time_unaffected, datetime)
        and one_time_unaffected == datetime(2027, 1, 2, 10, 0),
        "birthday_unaffected": isinstance(birthday_unaffected, datetime)
        and birthday_unaffected == datetime(2027, 1, 2, 8, 0),
    }
    return {
        "count_zero_next": count_zero_next.isoformat() if isinstance(count_zero_next, datetime) else None,
        "count_positive_next": count_positive_next.isoformat() if isinstance(count_positive_next, datetime) else None,
        "until_inclusive_next": until_inclusive_next.isoformat() if isinstance(until_inclusive_next, datetime) else None,
        "until_after_none": until_after_none.isoformat() if isinstance(until_after_none, datetime) else None,
        "yearly_inclusive_next": yearly_inclusive_next.isoformat() if isinstance(yearly_inclusive_next, datetime) else None,
        "yearly_after_none": yearly_after_none.isoformat() if isinstance(yearly_after_none, datetime) else None,
        "one_time_unaffected": one_time_unaffected.isoformat() if isinstance(one_time_unaffected, datetime) else None,
        "birthday_unaffected": birthday_unaffected.isoformat() if isinstance(birthday_unaffected, datetime) else None,
        "checks": checks,
    }


def run_actions_repetition_checks(actions_mod, constants_mod):
    fixed_now = datetime(2027, 1, 1, 10, 0, 0)
    next_occurrence = datetime(2027, 1, 2, 10, 0, 0)
    system_events = []
    compute_calls = []

    class _ActionStorageStub:
        def __init__(self, consume_results=None):
            self.consume_results = list(consume_results or [])
            self.consume_calls = []
            self.schedule_updates = []
            self.field_updates = []
            self.clear_snooze_calls = []
            self.mark_done_calls = []
            self.user_events = []

        def get_user_prefs(self, _user_id):
            return {}

        def consume_repetition_occurrence(self, user_id, alert_id, *, should_count=True):
            self.consume_calls.append({
                "user_id": str(user_id),
                "alert_id": alert_id,
                "should_count": bool(should_count),
            })
            if self.consume_results:
                return dict(self.consume_results.pop(0))
            return {
                "ok": True,
                "found": True,
                "changed": False,
                "alert_type": 7,
                "repetition": {
                    "mode": constants_mod.REPETITION_MODE_FOREVER,
                    "until_date": None,
                    "count_remaining": None,
                },
                "before": None,
                "after": None,
                "exhausted": False,
                "should_count": bool(should_count),
            }

        def clear_alert_snooze(self, user_id, alert_id):
            self.clear_snooze_calls.append({
                "user_id": str(user_id),
                "alert_id": alert_id,
            })
            return True

        def update_alert_schedule_state(self, user_id, alert_id, last_triggered=None, next_scheduled=None, snoozed_until=None):
            self.schedule_updates.append({
                "user_id": str(user_id),
                "alert_id": alert_id,
                "last_triggered": last_triggered,
                "next_scheduled": next_scheduled,
                "snoozed_until": snoozed_until,
            })
            return True

        def update_alert_fields(self, user_id, alert_id, updates):
            self.field_updates.append({
                "user_id": str(user_id),
                "alert_id": alert_id,
                "updates": dict(updates or {}),
            })
            return True

        def mark_alert_done(self, user_id, alert_id):
            self.mark_done_calls.append({
                "user_id": str(user_id),
                "alert_id": alert_id,
            })
            return True, True

        def log_user_event(self, user_id, event_type, payload=None):
            self.user_events.append({
                "user_id": str(user_id),
                "event_type": event_type,
                "payload": dict(payload or {}),
            })
            return True

    def _build_recurring_alert(alert_id, count_remaining):
        return {
            "id": alert_id,
            "title": f"Alert {alert_id}",
            "type": 7,
            "type_name": constants_mod.ALERT_TYPES.get(7, "Daily"),
            "schedule": {"time": "10:00", "interval": 1},
            "pre_alerts": [],
            "tags": [],
            "repetition": {
                "mode": constants_mod.REPETITION_MODE_COUNT,
                "until_date": None,
                "count_remaining": count_remaining,
            },
        }

    async def _fake_send_alert(
        _bot,
        _user_id,
        _alert,
        storage=None,
        alert_type=None,
        missed_time=None,
        scheduled_time=None,
        occurrence_time=None,
        postpone_count=0,
        **_kwargs,
    ):
        _ = (storage, alert_type, missed_time, scheduled_time, occurrence_time, postpone_count)
        return object()

    def _fake_compute_next_occurrence(alert, reference_time, user_prefs):
        compute_calls.append({
            "alert_id": alert.get("id"),
            "repetition": dict(alert.get("repetition") or {}) if isinstance(alert, dict) else None,
            "reference_time": reference_time,
            "user_prefs": dict(user_prefs or {}) if isinstance(user_prefs, dict) else user_prefs,
        })
        return next_occurrence, False

    def _fake_log_system(category, event_type, payload=None, level="INFO"):
        system_events.append({
            "category": category,
            "event_type": event_type,
            "payload": dict(payload or {}),
            "level": level,
        })

    original_send_alert = actions_mod.send_alert
    original_compute_next = actions_mod.compute_next_occurrence
    original_log_system = actions_mod.log_system
    original_now_server_naive = actions_mod.now_server_naive

    try:
        actions_mod.send_alert = _fake_send_alert
        actions_mod.compute_next_occurrence = _fake_compute_next_occurrence
        actions_mod.log_system = _fake_log_system
        actions_mod.now_server_naive = lambda: fixed_now

        # 1) Normal due: must decrement/count
        storage_normal = _ActionStorageStub([{
            "ok": True,
            "found": True,
            "changed": True,
            "alert_type": 7,
            "repetition": {
                "mode": constants_mod.REPETITION_MODE_COUNT,
                "until_date": None,
                "count_remaining": 1,
            },
            "before": 2,
            "after": 1,
            "exhausted": False,
            "should_count": True,
        }])
        normal_sent = asyncio.run(actions_mod.trigger_alert(
            object(),
            "101",
            _build_recurring_alert("r_normal", 2),
            constants_mod.ALERT_MSG_TYPE_MAIN,
            storage_normal,
            {},
            scheduled_time=fixed_now,
        ))

        # 2) Postponed due: must NOT decrement/count
        storage_postponed = _ActionStorageStub([{
            "ok": True,
            "found": True,
            "changed": False,
            "alert_type": 7,
            "repetition": {
                "mode": constants_mod.REPETITION_MODE_COUNT,
                "until_date": None,
                "count_remaining": 2,
            },
            "before": 2,
            "after": 2,
            "exhausted": False,
            "should_count": False,
        }])
        postponed_sent = asyncio.run(actions_mod.trigger_alert(
            object(),
            "102",
            _build_recurring_alert("r_postponed", 2),
            constants_mod.ALERT_MSG_TYPE_MAIN,
            storage_postponed,
            {},
            scheduled_time=fixed_now,
            postpone_count=1,
            postpone_id="pp_1",
            effective_fire_time=fixed_now,
        ))

        # 3) clear_snooze=True: must NOT decrement/count
        storage_clear_snooze = _ActionStorageStub([{
            "ok": True,
            "found": True,
            "changed": False,
            "alert_type": 7,
            "repetition": {
                "mode": constants_mod.REPETITION_MODE_COUNT,
                "until_date": None,
                "count_remaining": 2,
            },
            "before": 2,
            "after": 2,
            "exhausted": False,
            "should_count": False,
        }])
        clear_snooze_sent = asyncio.run(actions_mod.trigger_alert(
            object(),
            "103",
            _build_recurring_alert("r_clear", 2),
            constants_mod.ALERT_MSG_TYPE_MAIN,
            storage_clear_snooze,
            {},
            scheduled_time=fixed_now,
            clear_snooze=True,
        ))

        # 4) pre-alert path: must NOT decrement/count
        storage_pre = _ActionStorageStub([{
            "ok": True,
            "found": True,
            "changed": False,
            "alert_type": 7,
            "repetition": {
                "mode": constants_mod.REPETITION_MODE_COUNT,
                "until_date": None,
                "count_remaining": 3,
            },
            "before": 3,
            "after": 3,
            "exhausted": False,
            "should_count": False,
        }])
        pre_sent = asyncio.run(actions_mod.trigger_alert(
            object(),
            "104",
            _build_recurring_alert("r_pre", 3),
            constants_mod.ALERT_MSG_TYPE_PRE,
            storage_pre,
            {},
            scheduled_time=fixed_now,
        ))

        # 5) Exhaustion on true due event: must deactivate and avoid next-occurrence recompute
        compute_calls_before_exhausted = len(compute_calls)
        storage_exhausted = _ActionStorageStub([{
            "ok": True,
            "found": True,
            "changed": True,
            "alert_type": 7,
            "repetition": {
                "mode": constants_mod.REPETITION_MODE_COUNT,
                "until_date": None,
                "count_remaining": 0,
            },
            "before": 1,
            "after": 0,
            "exhausted": True,
            "should_count": True,
        }])
        exhausted_sent = asyncio.run(actions_mod.trigger_alert(
            object(),
            "105",
            _build_recurring_alert("r_exhausted", 1),
            constants_mod.ALERT_MSG_TYPE_MAIN,
            storage_exhausted,
            {},
            scheduled_time=fixed_now,
        ))
        compute_calls_after_exhausted = len(compute_calls)

        checks = {
            "normal_sent": bool(normal_sent),
            "normal_due_counts": bool(storage_normal.consume_calls) and storage_normal.consume_calls[0]["should_count"] is True,
            "normal_due_updates_schedule": len(storage_normal.schedule_updates) == 1 and storage_normal.schedule_updates[0].get("next_scheduled") == next_occurrence,
            "postponed_sent": bool(postponed_sent),
            "postponed_due_not_counted": bool(storage_postponed.consume_calls) and storage_postponed.consume_calls[0]["should_count"] is False,
            "postponed_due_not_deactivated": len(storage_postponed.field_updates) == 0,
            "clear_snooze_sent": bool(clear_snooze_sent),
            "clear_snooze_called": len(storage_clear_snooze.clear_snooze_calls) == 1,
            "clear_snooze_not_counted": bool(storage_clear_snooze.consume_calls) and storage_clear_snooze.consume_calls[0]["should_count"] is False,
            "pre_sent": bool(pre_sent),
            "pre_not_counted": bool(storage_pre.consume_calls) and storage_pre.consume_calls[0]["should_count"] is False,
            "exhausted_sent": bool(exhausted_sent),
            "exhausted_due_counted": bool(storage_exhausted.consume_calls) and storage_exhausted.consume_calls[0]["should_count"] is True,
            "exhausted_deactivates_alert": len(storage_exhausted.field_updates) == 1 and storage_exhausted.field_updates[0].get("updates", {}).get("active") is False,
            "exhausted_next_scheduled_cleared": len(storage_exhausted.field_updates) == 1 and storage_exhausted.field_updates[0].get("updates", {}).get("next_scheduled") is None,
            "exhausted_skips_compute_next": compute_calls_after_exhausted == compute_calls_before_exhausted,
            "exhaustion_user_event_logged": any(event.get("event_type") == "repetition_exhausted" for event in storage_exhausted.user_events),
            "exhaustion_system_event_logged": any(event.get("event_type") == "repetition_exhausted" for event in system_events),
        }
        return {
            "normal_consume_calls": storage_normal.consume_calls,
            "postponed_consume_calls": storage_postponed.consume_calls,
            "clear_snooze_consume_calls": storage_clear_snooze.consume_calls,
            "pre_consume_calls": storage_pre.consume_calls,
            "exhausted_consume_calls": storage_exhausted.consume_calls,
            "exhausted_field_updates": storage_exhausted.field_updates,
            "compute_calls_count": len(compute_calls),
            "system_events_count": len(system_events),
            "checks": checks,
        }
    finally:
        actions_mod.send_alert = original_send_alert
        actions_mod.compute_next_occurrence = original_compute_next
        actions_mod.log_system = original_log_system
        actions_mod.now_server_naive = original_now_server_naive


def run_missed_coordinator_repetition_checks(missed_mod, coordinator_mod, storage_mod, constants_mod):
    fixed_now = datetime(2027, 1, 10, 10, 0, 0)

    def _recurring_payload(title, repetition):
        return {
            "title": title,
            "type": 7,
            "type_name": constants_mod.ALERT_TYPES.get(7, "Daily"),
            "schedule": {"time": "10:00", "interval": 1},
            "pre_alerts": [],
            "additional_info": "",
            "tags": [],
            "repetition": repetition,
        }

    async def _fake_send_missed(_bot, _user_id, _missed_list):
        return object()

    with tempfile.TemporaryDirectory(prefix="rep_missed_coord_dbg_") as temp_dir:
        storage = storage_mod.StorageManager(base_data_dir=temp_dir, admin_id=None)
        user_id = "20001"
        captured_events = []

        def _capture_event(log_user_id, event_type, payload=None):
            captured_events.append({
                "user_id": str(log_user_id),
                "event_type": event_type,
                "payload": dict(payload or {}),
            })
            return True

        storage.log_user_event = _capture_event

        # --- Missed overdue path: consume/deactivate on count exhaustion ---
        alert_count_1 = storage.save_alert(
            user_id,
            _recurring_payload(
                "Missed Count 1",
                {"mode": constants_mod.REPETITION_MODE_COUNT, "count_remaining": 1},
            ),
        )
        alert_count_2 = storage.save_alert(
            user_id,
            _recurring_payload(
                "Missed Count 2",
                {"mode": constants_mod.REPETITION_MODE_COUNT, "count_remaining": 2},
            ),
        )
        past_due = fixed_now - timedelta(hours=2)
        storage.update_alert_schedule_state(user_id, alert_count_1, next_scheduled=past_due)
        storage.update_alert_schedule_state(user_id, alert_count_2, next_scheduled=past_due)

        original_derive_window = missed_mod.derive_startup_downtime_window
        try:
            missed_mod.derive_startup_downtime_window = lambda now_dt: {
                "window_start": now_dt - timedelta(days=2),
                "window_end": now_dt,
                "source": "test",
                "is_reliable": True,
                "reason_code": "ok_last_shutdown",
                "instance_tag_current": "test",
                "instance_tag_state": "test",
                "identity_match": True,
                "last_pid_alive": False,
            }
            asyncio.run(
                missed_mod.handle_missed_alerts(
                    object(),
                    storage,
                    now=fixed_now,
                    send_missed_func=_fake_send_missed,
                )
            )
        finally:
            missed_mod.derive_startup_downtime_window = original_derive_window

        after_count_1 = storage.get_alert_by_id(user_id, alert_count_1) or {}
        after_count_2 = storage.get_alert_by_id(user_id, alert_count_2) or {}

        # --- Coordinator startup/reschedule path: avoid re-queueing terminal repetition ---
        alert_stale_cached = storage.save_alert(
            user_id,
            _recurring_payload(
                "Stale Cached Count 0",
                {"mode": constants_mod.REPETITION_MODE_COUNT, "count_remaining": 0},
            ),
        )
        storage.update_alert_fields(user_id, alert_stale_cached, {
            "active": True,
            "next_scheduled": (fixed_now + timedelta(hours=5)).isoformat(),
        })

        previous_storage = coordinator_mod._storage
        previous_app = coordinator_mod._app
        try:
            coordinator_mod._storage = storage
            coordinator_mod._app = None
            asyncio.run(coordinator_mod.load_all_alerts())
        finally:
            coordinator_mod._storage = previous_storage
            coordinator_mod._app = previous_app

        after_stale_cached = storage.get_alert_by_id(user_id, alert_stale_cached) or {}

        alert_reschedule_until = storage.save_alert(
            user_id,
            _recurring_payload(
                "Reschedule Until Past",
                {"mode": constants_mod.REPETITION_MODE_UNTIL_DATE, "until_date": "01/01/2020"},
            ),
        )
        storage.update_alert_fields(user_id, alert_reschedule_until, {
            "active": True,
            "next_scheduled": (fixed_now + timedelta(hours=6)).isoformat(),
        })
        rescheduled_count = coordinator_mod.reschedule_user_alerts(user_id, storage=storage)
        after_reschedule_until = storage.get_alert_by_id(user_id, alert_reschedule_until) or {}

        checks = {
            "missed_count1_deactivated": after_count_1.get("active") is False,
            "missed_count1_next_cleared": after_count_1.get("next_scheduled") is None,
            "missed_count1_repetition_zero": (after_count_1.get("repetition") or {}).get("count_remaining") == 0,
            "missed_count2_stays_active": after_count_2.get("active", True) is True,
            "missed_count2_decremented": (after_count_2.get("repetition") or {}).get("count_remaining") == 1,
            "missed_count2_next_present": isinstance(after_count_2.get("next_scheduled"), str) and bool(after_count_2.get("next_scheduled")),
            "load_all_alerts_deactivates_stale_cached": after_stale_cached.get("active") is False and after_stale_cached.get("next_scheduled") is None,
            "reschedule_deactivates_until_past": after_reschedule_until.get("active") is False and after_reschedule_until.get("next_scheduled") is None,
            "reschedule_reports_updates": isinstance(rescheduled_count, int) and rescheduled_count >= 1,
            "repetition_exhausted_logged": any(event.get("event_type") == "repetition_exhausted" for event in captured_events),
        }
        return {
            "after_count_1": after_count_1,
            "after_count_2": after_count_2,
            "after_stale_cached": after_stale_cached,
            "after_reschedule_until": after_reschedule_until,
            "rescheduled_count": rescheduled_count,
            "captured_events_count": len(captured_events),
            "checks": checks,
        }


class _StorageStub:
    def __init__(self):
        self.events = []

    def log_user_event(self, user_id, event_type, payload=None):
        self.events.append({
            "user_id": user_id,
            "event_type": event_type,
            "payload": dict(payload or {}),
        })
        return True

    def get_user_prefs(self, _user_id):
        return {
            "timezone_mode": "user",
            "timezone": {"name": "Europe/Rome"},
        }


class _DummyMessage:
    def __init__(self, text=None, message_id=100):
        self.text = text
        self.message_id = message_id
        self.replies = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None):
        self.replies.append({
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        })
        return self


class _DummyCallbackQuery:
    def __init__(self, data, message):
        self.data = data
        self.message = message
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=None):
        self.answers.append({
            "text": text,
            "show_alert": show_alert,
        })

    async def edit_message_text(self, text, parse_mode=None, reply_markup=None):
        self.edits.append({
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        })
        return self.message


class _DummyUpdate:
    def __init__(self, *, user_id=42, message=None, callback_query=None):
        self.message = message
        self.callback_query = callback_query
        self.effective_user = types.SimpleNamespace(id=user_id)


class _DummyContext:
    def __init__(self, user_data=None):
        self.user_data = dict(user_data or {})
        self.bot_data = {}


def _seed_runtime(context, storage):
    """Install runtime storage in context bot_data for handler-edge DI lookups."""

    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    set_bot_runtime(
        context.bot_data,
        BotRuntime(storage=storage, api_failure_tracker=None),
    )


def _extract_rows(markup):
    rows = []
    for row in getattr(markup, "inline_keyboard", []) or []:
        rows.append([getattr(btn, "callback_data", None) for btn in row])
    return rows


def _event_count(storage, event_type):
    return len([event for event in storage.events if event.get("event_type") == event_type])


def _events_by_type(storage, event_type):
    return [event for event in storage.events if event.get("event_type") == event_type]


def _meta_payload_ok(payload):
    if not isinstance(payload, dict):
        return False
    return isinstance(payload.get("len"), int) and "hash" in payload


def _payload_has_forbidden_text_keys(payload):
    if not isinstance(payload, dict):
        return False
    forbidden = {
        "text",
        "raw_text",
        "title",
        "message",
        "until_input",
        "count_input",
    }
    return any(key in payload for key in forbidden)


def run_handler_checks(flow_mod, constants_mod):
    storage_stub = _StorageStub()
    original_mainbot = sys.modules.get("mainbot")
    original_now_server_naive = getattr(flow_mod, "now_server_naive", None)
    fake_mainbot = types.ModuleType("mainbot")
    fake_mainbot.storage = storage_stub
    sys.modules["mainbot"] = fake_mainbot
    flow_mod.now_server_naive = lambda: datetime(2026, 3, 20, 12, 0, 0)

    try:
        context = _DummyContext({
            "temp_alert": {
                "type": 3,
                "type_name": "Weekly",
                "schedule": {"time": "10:00", "interval": 1},
                "pre_alerts": [],
                "repetition": {"mode": constants_mod.REPETITION_MODE_FOREVER},
            },
            "settings_return": "alert",
        })
        _seed_runtime(context, storage_stub)

        # Menu rendering
        menu_query = _DummyCallbackQuery("ms_repetition", _DummyMessage())
        menu_update = _DummyUpdate(callback_query=menu_query)
        menu_state = asyncio.run(flow_mod.show_repetition_menu(menu_update, context))
        menu_edit = menu_query.edits[-1] if menu_query.edits else {}
        menu_rows = _extract_rows(menu_edit.get("reply_markup"))

        # Choice -> forever
        async def _return_to_settings(_update, _context):
            return constants_mod.MULTI_SETTINGS

        async def _prompt_until(_update, _context):
            return constants_mod.GET_REPETITION_UNTIL_DATE

        async def _prompt_count(_update, _context):
            return constants_mod.GET_REPETITION_COUNT

        forever_query = _DummyCallbackQuery("rep_forever", _DummyMessage())
        forever_update = _DummyUpdate(callback_query=forever_query)
        forever_state = asyncio.run(
            flow_mod.handle_repetition_choice(
                forever_update,
                context,
                _return_to_settings,
                _prompt_until,
                _prompt_count,
            )
        )

        # Choice -> until prompt
        until_query = _DummyCallbackQuery("rep_until", _DummyMessage())
        until_update = _DummyUpdate(callback_query=until_query)
        until_state = asyncio.run(
            flow_mod.handle_repetition_choice(
                until_update,
                context,
                _return_to_settings,
                _prompt_until,
                _prompt_count,
            )
        )

        # Invalid until input
        until_invalid_message = _DummyMessage(text="31-01-2030")
        until_invalid_update = _DummyUpdate(message=until_invalid_message)
        until_invalid_state = asyncio.run(
            flow_mod.handle_repetition_until_date_input(
                until_invalid_update,
                context,
                _return_to_settings,
            )
        )

        # Valid short-format until input (D/M/YY)
        until_short_message = _DummyMessage(text="1/1/30")
        until_short_update = _DummyUpdate(message=until_short_message)
        until_short_state = asyncio.run(
            flow_mod.handle_repetition_until_date_input(
                until_short_update,
                context,
                _return_to_settings,
            )
        )
        until_short_repetition = dict((context.user_data.get("temp_alert", {}) or {}).get("repetition", {}))

        # Past-date until input (must be rejected against local date)
        until_past_message = _DummyMessage(text="19/03/2026")
        until_past_update = _DummyUpdate(message=until_past_message)
        until_past_state = asyncio.run(
            flow_mod.handle_repetition_until_date_input(
                until_past_update,
                context,
                _return_to_settings,
            )
        )

        # Choice -> count prompt
        count_query = _DummyCallbackQuery("rep_count", _DummyMessage())
        count_update = _DummyUpdate(callback_query=count_query)
        count_state = asyncio.run(
            flow_mod.handle_repetition_choice(
                count_update,
                context,
                _return_to_settings,
                _prompt_until,
                _prompt_count,
            )
        )

        # Invalid count input
        count_invalid_message = _DummyMessage(text="0")
        count_invalid_update = _DummyUpdate(message=count_invalid_message)
        count_invalid_state = asyncio.run(
            flow_mod.handle_repetition_count_input(
                count_invalid_update,
                context,
                _return_to_settings,
            )
        )

        # Valid count input
        count_valid_message = _DummyMessage(text="5")
        count_valid_update = _DummyUpdate(message=count_valid_message)
        count_valid_state = asyncio.run(
            flow_mod.handle_repetition_count_input(
                count_valid_update,
                context,
                _return_to_settings,
            )
        )

        final_repetition = context.user_data.get("temp_alert", {}).get("repetition", {})
        until_invalid_events = _events_by_type(storage_stub, "repetition_until_invalid")
        until_past_event = next(
            (
                event for event in until_invalid_events
                if (event.get("payload") or {}).get("reason_code") == "past_date"
            ),
            None,
        )
        until_format_event = next(
            (
                event for event in until_invalid_events
                if (event.get("payload") or {}).get("reason_code") == "invalid_format_or_date"
            ),
            None,
        )
        count_invalid_events = _events_by_type(storage_stub, "repetition_count_invalid")
        repetition_events = [
            event for event in storage_stub.events
            if str(event.get("event_type", "")).startswith("repetition_")
        ]

        checks = {
            "menu_state": menu_state == constants_mod.GET_REPETITION_MENU,
            "menu_has_forever": any("rep_forever" in row for row in menu_rows),
            "menu_has_until": any("rep_until" in row for row in menu_rows),
            "menu_has_count": any("rep_count" in row for row in menu_rows),
            "menu_has_back": any("rep_back" in row for row in menu_rows),
            "menu_open_logged": _event_count(storage_stub, "repetition_menu_opened") >= 1,
            "forever_choice_state": forever_state == constants_mod.MULTI_SETTINGS,
            "forever_choice_single_answer": len(forever_query.answers) == 1,
            "forever_set_logged": _event_count(storage_stub, "repetition_forever_set") >= 1,
            "until_choice_state": until_state == constants_mod.GET_REPETITION_UNTIL_DATE,
            "until_choice_single_answer": len(until_query.answers) == 1,
            "until_invalid_state": until_invalid_state == constants_mod.GET_REPETITION_UNTIL_DATE,
            "until_invalid_reply": bool(until_invalid_message.replies),
            "until_invalid_logged": _event_count(storage_stub, "repetition_until_invalid") >= 1,
            "until_short_state": until_short_state == constants_mod.MULTI_SETTINGS,
            "until_short_normalized": until_short_repetition.get("until_date") == "01/01/2030",
            "until_set_mode": until_short_repetition.get("mode") == constants_mod.REPETITION_MODE_UNTIL_DATE,
            "until_set_logged": _event_count(storage_stub, "repetition_until_set") >= 1,
            "until_past_state": until_past_state == constants_mod.GET_REPETITION_UNTIL_DATE,
            "until_past_reply": bool(until_past_message.replies),
            "until_past_reason_logged": isinstance(until_past_event, dict),
            "until_invalid_format_reason_logged": isinstance(until_format_event, dict),
            "count_choice_state": count_state == constants_mod.GET_REPETITION_COUNT,
            "count_choice_single_answer": len(count_query.answers) == 1,
            "count_invalid_state": count_invalid_state == constants_mod.GET_REPETITION_COUNT,
            "count_invalid_reply": bool(count_invalid_message.replies),
            "count_invalid_logged": _event_count(storage_stub, "repetition_count_invalid") >= 1,
            "count_set_state": count_valid_state == constants_mod.MULTI_SETTINGS,
            "count_set_logged": _event_count(storage_stub, "repetition_count_set") >= 1,
            "final_repetition_count_mode": final_repetition.get("mode") == constants_mod.REPETITION_MODE_COUNT,
            "final_repetition_count_value": final_repetition.get("count_remaining") == 5,
            "until_invalid_meta_payload_only": bool(until_invalid_events) and all(
                _meta_payload_ok((event.get("payload") or {}).get("until_input_meta"))
                for event in until_invalid_events
            ),
            "until_invalid_no_raw_text": bool(until_invalid_events) and all(
                not _payload_has_forbidden_text_keys(event.get("payload") or {})
                for event in until_invalid_events
            ),
            "count_invalid_meta_payload_only": bool(count_invalid_events) and _meta_payload_ok((count_invalid_events[-1].get("payload") or {}).get("count_input_meta")),
            "count_invalid_no_raw_text": bool(count_invalid_events) and not _payload_has_forbidden_text_keys(count_invalid_events[-1].get("payload") or {}),
            "all_repetition_events_metadata_only": all(not _payload_has_forbidden_text_keys(event.get("payload") or {}) for event in repetition_events),
        }
        return {
            "menu_rows": menu_rows,
            "menu_text": menu_edit.get("text"),
            "events": storage_stub.events,
            "final_repetition": final_repetition,
            "checks": checks,
        }
    finally:
        if callable(original_now_server_naive):
            flow_mod.now_server_naive = original_now_server_naive
        if original_mainbot is None:
            sys.modules.pop("mainbot", None)
        else:
            sys.modules["mainbot"] = original_mainbot


def _find_alert_by_id(alerts, alert_id):
    for alert in alerts or []:
        if isinstance(alert, dict) and alert.get("id") == alert_id:
            return alert
    return None


def _daily_payload(constants_mod, title, repetition=None):
    payload = {
        "title": title,
        "type": 7,
        "type_name": constants_mod.ALERT_TYPES.get(7, "Daily"),
        "schedule": {"time": "10:00", "interval": 1},
        "pre_alerts": [],
        "additional_info": "",
        "tags": [],
    }
    if repetition is not None:
        payload["repetition"] = repetition
    return payload


def _one_time_payload(constants_mod, title, repetition=None):
    payload = {
        "title": title,
        "type": 5,
        "type_name": constants_mod.ALERT_TYPES.get(5, "One Time"),
        "schedule": {"date": "31/12/2099", "time": "10:00"},
        "pre_alerts": [],
        "additional_info": "",
        "tags": [],
    }
    if repetition is not None:
        payload["repetition"] = repetition
    return payload


def run_storage_checks(storage_mod, constants_mod):
    with tempfile.TemporaryDirectory(prefix="rep_storage_dbg_") as temp_dir:
        storage = storage_mod.StorageManager(base_data_dir=temp_dir, admin_id=None)
        captured_events = []

        def _capture_event(user_id, event_type, payload=None):
            captured_events.append({
                "user_id": str(user_id),
                "event_type": event_type,
                "payload": dict(payload or {}),
            })
            return True

        storage.log_user_event = _capture_event
        user_id = "10001"

        # save_alert normalization for supported and unsupported types
        recurring_id = storage.save_alert(user_id, _daily_payload(constants_mod, "recurring_default"))
        recurring_alert = storage.get_alert_by_id(user_id, recurring_id) if recurring_id else None

        one_time_id = storage.save_alert(
            user_id,
            _one_time_payload(
                constants_mod,
                "one_time_no_repetition",
                repetition={"mode": constants_mod.REPETITION_MODE_COUNT, "count_remaining": 3},
            ),
        )
        one_time_alert = storage.get_alert_by_id(user_id, one_time_id) if one_time_id else None

        # update_alert_fields normalization with type changes
        update_to_one_time_ok = storage.update_alert_fields(
            user_id,
            recurring_id,
            {
                "type": 5,
                "type_name": constants_mod.ALERT_TYPES.get(5, "One Time"),
                "schedule": {"date": "31/12/2099", "time": "10:00"},
            },
        )
        recurring_after_type5 = storage.get_alert_by_id(user_id, recurring_id) if recurring_id else None

        update_back_supported_ok = storage.update_alert_fields(
            user_id,
            recurring_id,
            {
                "type": 7,
                "type_name": constants_mod.ALERT_TYPES.get(7, "Daily"),
                "schedule": {"time": "10:00", "interval": 1},
            },
        )
        recurring_after_back = storage.get_alert_by_id(user_id, recurring_id) if recurring_id else None

        # consume helper contract
        storage.update_alert_fields(
            user_id,
            recurring_id,
            {
                "repetition": {"mode": constants_mod.REPETITION_MODE_COUNT, "count_remaining": 2},
            },
        )
        consume_counted = storage.consume_repetition_occurrence(user_id, recurring_id, should_count=True)
        consume_not_counted = storage.consume_repetition_occurrence(user_id, recurring_id, should_count=False)
        consume_to_zero = storage.consume_repetition_occurrence(user_id, recurring_id, should_count=True)
        consume_stays_zero = storage.consume_repetition_occurrence(user_id, recurring_id, should_count=True)
        consume_unsupported = storage.consume_repetition_occurrence(user_id, one_time_id, should_count=True)
        consume_missing = storage.consume_repetition_occurrence(user_id, "missing", should_count=True)

        # migration normalization via get_all_alerts()
        migration_user = "10002"
        migration_dir = os.path.join(temp_dir, migration_user)
        os.makedirs(migration_dir, exist_ok=True)
        migration_path = os.path.join(migration_dir, "alerts.json")
        migration_payload = {
            "tags": [],
            "alerts": [
                {
                    "id": "a1",
                    "title": "Recurring",
                    "type": 3,
                    "type_name": constants_mod.ALERT_TYPES.get(3, "Weekly"),
                    "schedule": {"weekdays": ["Mon"], "time": "10:00", "interval": 1},
                    "active": True,
                    "repetition": {"mode": "count", "count_remaining": "3"},
                },
                {
                    "id": "a2",
                    "title": "One Time",
                    "type": 5,
                    "type_name": constants_mod.ALERT_TYPES.get(5, "One Time"),
                    "schedule": {"date": "31/12/2099", "time": "10:00"},
                    "active": True,
                    "repetition": {"mode": "count", "count_remaining": 2},
                },
            ],
            "postpone_queue": [],
            "shortcut_meta": {"next_seq": 0},
            "backup_prefs": storage._default_backup_prefs(),
            "user_prefs": storage._default_user_prefs(),
            "user_meta": storage._default_user_meta(),
        }
        with open(migration_path, "w", encoding="utf-8") as handle:
            json.dump(migration_payload, handle, indent=2)

        normalized_migration = storage.get_all_alerts(migration_user) or {}
        normalized_alert_a1 = _find_alert_by_id(normalized_migration.get("alerts"), "a1")
        normalized_alert_a2 = _find_alert_by_id(normalized_migration.get("alerts"), "a2")

        recurring_saved_event = next(
            (
                item
                for item in captured_events
                if item.get("event_type") == "alert_saved"
                and item.get("payload", {}).get("alert_id") == recurring_id
            ),
            None,
        )
        one_time_saved_event = next(
            (
                item
                for item in captured_events
                if item.get("event_type") == "alert_saved"
                and item.get("payload", {}).get("alert_id") == one_time_id
            ),
            None,
        )

        checks = {
            "save_supported_default_forever": isinstance(recurring_alert, dict) and recurring_alert.get("repetition", {}).get("mode") == constants_mod.REPETITION_MODE_FOREVER,
            "save_unsupported_clears_repetition": isinstance(one_time_alert, dict) and "repetition" not in one_time_alert,
            "alert_saved_event_has_repetition_fields_supported": isinstance(recurring_saved_event, dict) and "repetition_mode" in recurring_saved_event.get("payload", {}) and "repetition_count_remaining" in recurring_saved_event.get("payload", {}),
            "alert_saved_mode_supported_forever": isinstance(recurring_saved_event, dict) and recurring_saved_event.get("payload", {}).get("repetition_mode") == constants_mod.REPETITION_MODE_FOREVER,
            "alert_saved_mode_unsupported_none": isinstance(one_time_saved_event, dict) and one_time_saved_event.get("payload", {}).get("repetition_mode") is None,
            "update_type_to_unsupported_clears": update_to_one_time_ok and isinstance(recurring_after_type5, dict) and "repetition" not in recurring_after_type5,
            "update_type_back_supported_defaults": update_back_supported_ok and isinstance(recurring_after_back, dict) and recurring_after_back.get("repetition", {}).get("mode") == constants_mod.REPETITION_MODE_FOREVER,
            "consume_counted_decrements": consume_counted.get("ok") and consume_counted.get("before") == 2 and consume_counted.get("after") == 1 and not consume_counted.get("exhausted"),
            "consume_not_counted_keeps": consume_not_counted.get("ok") and consume_not_counted.get("before") == 1 and consume_not_counted.get("after") == 1 and not consume_not_counted.get("exhausted"),
            "consume_to_zero_exhausts": consume_to_zero.get("ok") and consume_to_zero.get("before") == 1 and consume_to_zero.get("after") == 0 and consume_to_zero.get("exhausted"),
            "consume_zero_stays_exhausted": consume_stays_zero.get("ok") and consume_stays_zero.get("before") == 0 and consume_stays_zero.get("after") == 0 and consume_stays_zero.get("exhausted"),
            "consume_unsupported_passthrough": consume_unsupported.get("ok") and consume_unsupported.get("found") and consume_unsupported.get("repetition") is None and consume_unsupported.get("before") is None and consume_unsupported.get("after") is None,
            "consume_missing_not_found": consume_missing.get("ok") and not consume_missing.get("found"),
            "migration_supported_count_normalized": isinstance(normalized_alert_a1, dict) and normalized_alert_a1.get("repetition", {}).get("mode") == constants_mod.REPETITION_MODE_COUNT and normalized_alert_a1.get("repetition", {}).get("count_remaining") == 3,
            "migration_unsupported_repetition_removed": isinstance(normalized_alert_a2, dict) and "repetition" not in normalized_alert_a2,
        }
        return {
            "recurring_id": recurring_id,
            "one_time_id": one_time_id,
            "consume_counted": consume_counted,
            "consume_not_counted": consume_not_counted,
            "consume_to_zero": consume_to_zero,
            "consume_stays_zero": consume_stays_zero,
            "consume_unsupported": consume_unsupported,
            "consume_missing": consume_missing,
            "migration_alert_a1": normalized_alert_a1,
            "migration_alert_a2": normalized_alert_a2,
            "captured_events_count": len(captured_events),
            "checks": checks,
        }
