from copy import deepcopy


def _birthday_alert_template(name, date_ddmm):
    return {
        "title": name,
        "type": 6,
        "type_name": "Birthday",
        "schedule": {"date": date_ddmm, "time": "08:00"},
        "pre_alerts": [],
        "additional_info": "",
        "tags": [],
    }


def _birthday_count(storage, user_id):
    data = storage.get_all_alerts(user_id) or {}
    alerts = data.get("alerts", []) if isinstance(data, dict) else []
    return sum(1 for item in alerts if isinstance(item, dict) and item.get("type") == 6)


def run_bulk_save_success_checks(storage, user_id):
    storage.setup_user_space(user_id)
    storage.update_user_prefs(user_id, {"birthday_default_time": "07:30"})

    entries = [
        {
            "name": "Alice Alloy",
            "date_ddmm": "03/01",
            "birth_year": 1990,
            "resolved_tags": ["👥 Friends", "Friends", "  💼   Work  ", "💼 Work"],
        },
        {"name": "Bruno Brown", "date_ddmm": "10/05", "birth_year": None, "resolved_tags": None},
        {"name": "Zed Zero", "date_ddmm": "29/02", "birth_year": None, "resolved_tag": "🐾 Pet"},
    ]
    result = storage.save_birthdays_bulk(user_id, deepcopy(entries), source="debug_success")
    data = storage.get_all_alerts(user_id) or {}
    alerts = data.get("alerts", []) if isinstance(data, dict) else []
    by_id = {
        item.get("id"): item
        for item in alerts
        if isinstance(item, dict) and item.get("id") in set(result.get("ids") or [])
    }
    by_title = {
        item.get("title"): item
        for item in by_id.values()
        if isinstance(item, dict)
    }
    shortcodes = [item.get("shortcode") for item in by_id.values()]

    checks = {
        "result_ok": result.get("ok") is True,
        "saved_count": result.get("saved_count") == 3,
        "ids_len": len(result.get("ids") or []) == 3,
        "failure_reason_none": result.get("failure_reason") is None,
        "rows_present": len(by_id) == 3,
        "all_type_birthday": all(item.get("type") == 6 for item in by_id.values()),
        "all_active_true": all(item.get("active") is True for item in by_id.values()),
        "all_time_from_prefs": all((item.get("schedule") or {}).get("time") == "07:30" for item in by_id.values()),
        "next_scheduled_present": all(bool(item.get("next_scheduled")) for item in by_id.values()),
        "shortcodes_unique": len(shortcodes) == len(set(shortcodes)),
        "birth_year_saved": any(item.get("birth_year") == 1990 for item in by_id.values()),
        "alice_multitag_saved": (by_title.get("Alice Alloy") or {}).get("tags") == ["👥 Friends", "💼 Work"],
        "untagged_saved": (by_title.get("Bruno Brown") or {}).get("tags") == [],
        "legacy_single_tag_saved": (by_title.get("Zed Zero") or {}).get("tags") == ["🐾 Pet"],
    }
    return {
        "result": result,
        "alerts_added": list(by_id.values()),
        "checks": checks,
    }


def run_bulk_save_limit_atomic_checks(storage, user_id, constants_mod):
    storage.setup_user_space(user_id)
    storage.save_alert(user_id, _birthday_alert_template("Seed One", "01/01"))
    storage.save_alert(user_id, _birthday_alert_template("Seed Two", "02/01"))
    before = _birthday_count(storage, user_id)

    old_limit = constants_mod.USER_MAX_ALERTS
    constants_mod.USER_MAX_ALERTS = 3
    try:
        result = storage.save_birthdays_bulk(user_id, [
            {"name": "Import One", "date_ddmm": "03/01", "birth_year": None, "resolved_tags": ["👥 Friends", "💼 Work"]},
            {"name": "Import Two", "date_ddmm": "04/01", "birth_year": None, "resolved_tag": "👥 Friends"},
        ], source="debug_limit")
    finally:
        constants_mod.USER_MAX_ALERTS = old_limit

    after = _birthday_count(storage, user_id)
    checks = {
        "result_not_ok": result.get("ok") is False,
        "reason_limit": result.get("failure_reason") == "limit_reached",
        "saved_count_zero": result.get("saved_count") == 0,
        "ids_empty": (result.get("ids") or []) == [],
        "no_partial_write": after == before,
    }
    return {
        "result": result,
        "before_count": before,
        "after_count": after,
        "checks": checks,
    }


def run_bulk_save_invalid_atomic_checks(storage, user_id):
    storage.setup_user_space(user_id)
    before = _birthday_count(storage, user_id)
    result = storage.save_birthdays_bulk(user_id, [
        {"name": "Valid Name", "date_ddmm": "03/01", "birth_year": 1990, "resolved_tags": ["👥 Friends"]},
        {"name": "Invalid Date", "date_ddmm": "31/11", "birth_year": 1990, "resolved_tags": ["👥 Friends"]},
    ], source="debug_invalid")
    after = _birthday_count(storage, user_id)
    checks = {
        "result_not_ok": result.get("ok") is False,
        "invalid_reason": result.get("failure_reason") == "invalid_calendar_date",
        "saved_count_zero": result.get("saved_count") == 0,
        "no_partial_write": after == before,
    }
    return {
        "result": result,
        "before_count": before,
        "after_count": after,
        "checks": checks,
    }


def run_bulk_save_invalid_tags_atomic_checks(storage, user_id):
    storage.setup_user_space(user_id)
    before = _birthday_count(storage, user_id)

    bad_type = storage.save_birthdays_bulk(user_id, [
        {"name": "Type Crash", "date_ddmm": "03/01", "birth_year": 1990, "resolved_tags": "👥 Friends"},
    ], source="debug_invalid_tags_type")
    after_bad_type = _birthday_count(storage, user_id)

    bad_item = storage.save_birthdays_bulk(user_id, [
        {"name": "Item Crash", "date_ddmm": "04/01", "birth_year": 1990, "resolved_tags": ["👥 Friends", 123]},
    ], source="debug_invalid_tags_item")
    after_bad_item = _birthday_count(storage, user_id)

    empty_item = storage.save_birthdays_bulk(user_id, [
        {"name": "Empty Crash", "date_ddmm": "05/01", "birth_year": 1990, "resolved_tags": ["  "]},
    ], source="debug_invalid_tags_empty")
    after_empty_item = _birthday_count(storage, user_id)

    checks = {
        "bad_type_not_ok": bad_type.get("ok") is False,
        "bad_type_reason": bad_type.get("failure_reason") == "invalid_entry_resolved_tags_not_list",
        "bad_item_not_ok": bad_item.get("ok") is False,
        "bad_item_reason": bad_item.get("failure_reason") == "invalid_entry_resolved_tag_not_string",
        "empty_item_not_ok": empty_item.get("ok") is False,
        "empty_item_reason": empty_item.get("failure_reason") == "invalid_entry_resolved_tag_empty",
        "no_partial_after_bad_type": after_bad_type == before,
        "no_partial_after_bad_item": after_bad_item == before,
        "no_partial_after_empty_item": after_empty_item == before,
    }
    return {
        "bad_type_result": bad_type,
        "bad_item_result": bad_item,
        "empty_item_result": empty_item,
        "before_count": before,
        "after_bad_type": after_bad_type,
        "after_bad_item": after_bad_item,
        "after_empty_item": after_empty_item,
        "checks": checks,
    }


def run_bulk_save_empty_checks(storage, user_id):
    storage.setup_user_space(user_id)
    result = storage.save_birthdays_bulk(user_id, [], source="debug_empty")
    checks = {
        "result_not_ok": result.get("ok") is False,
        "reason_entries_empty": result.get("failure_reason") == "entries_empty",
        "saved_count_zero": result.get("saved_count") == 0,
        "ids_empty": (result.get("ids") or []) == [],
    }
    return {
        "result": result,
        "checks": checks,
    }
