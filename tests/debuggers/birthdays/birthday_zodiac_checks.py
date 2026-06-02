"""birthday_zodiac_checks.py — Check logic for the zodiac feature (Steps 1-7c).

Covers: Western zodiac, Eastern zodiac, get_zodiac_info, format helpers,
zodiac mode constants, storage default/merge, scheduler zodiac block
(format_main_alert / format_pre_alert), birthday summary zodiac section
(format_birthday_summary), zodiac_assembler (assemble_zodiac_message),
and infer_zodiac_context.
"""
from __future__ import annotations

from typing import Any


def parse_unknown_args(args: list[str]) -> list[str]:
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


# ---------------------------------------------------------------------------
# Section: western zodiac
# ---------------------------------------------------------------------------

def run_western_zodiac_checks(dbg: Any, zodiac: Any) -> None:
    """Verify Western zodiac sign lookups including Capricorn wraparound."""

    cases = {
        # Sagittarius range
        "sagittario_nov23": (23, 11, "Sagittario"),
        "sagittario_dec21": (21, 12, "Sagittario"),
        # Capricorn wraparound
        "capricorno_dec22": (22, 12, "Capricorno"),
        "capricorno_jan01": (1,  1,  "Capricorno"),
        "capricorno_jan19": (19, 1,  "Capricorno"),
        # Aquarius boundary
        "acquario_jan20":   (20, 1,  "Acquario"),
        # Feb 29 (Pisces)
        "pesci_feb29":      (29, 2,  "Pesci"),
        # A few spot checks across the year
        "ariete_mar21":     (21, 3,  "Ariete"),
        "toro_apr20":       (20, 4,  "Toro"),
        "gemelli_may21":    (21, 5,  "Gemelli"),
        "cancro_jun21":     (21, 6,  "Cancro"),
        "leone_jul23":      (23, 7,  "Leone"),
        "vergine_aug23":    (23, 8,  "Vergine"),
        "bilancia_sep23":   (23, 9,  "Bilancia"),
        "scorpione_oct23":  (23, 10, "Scorpione"),
    }

    results = {}
    for name, (day, month, expected_sign) in cases.items():
        result = zodiac.get_western_zodiac(day, month)
        got = result["sign"] if result else None
        results[name] = {
            "day": day, "month": month,
            "expected": expected_sign, "got": got,
            "ok": got == expected_sign,
        }

    # Invalid inputs must return None
    invalid_cases = {
        "day_zero":    (0,  1),
        "day_32":      (32, 1),
        "month_zero":  (1,  0),
        "month_13":    (1, 13),
        "both_invalid": (0, 13),
    }
    invalid_results = {}
    for name, (day, month) in invalid_cases.items():
        result = zodiac.get_western_zodiac(day, month)
        invalid_results[name] = {"day": day, "month": month, "got": result, "ok": result is None}

    # Element mapping spot checks
    element_cases = {
        "capricorno_terra": (22, 12, "Terra"),
        "ariete_fuoco":     (21, 3,  "Fuoco"),
        "acquario_aria":    (20, 1,  "Aria"),
        "cancro_acqua":     (21, 6,  "Acqua"),
    }
    element_results = {}
    for name, (day, month, expected_elem) in element_cases.items():
        result = zodiac.get_western_zodiac(day, month)
        got = result["element"] if result else None
        element_results[name] = {"expected": expected_elem, "got": got, "ok": got == expected_elem}

    sign_failures = [k for k, v in results.items() if not v["ok"]]
    invalid_failures = [k for k, v in invalid_results.items() if not v["ok"]]
    element_failures = [k for k, v in element_results.items() if not v["ok"]]

    dbg.section("western_zodiac", {
        "sign_checks": results,
        "invalid_input_checks": invalid_results,
        "element_checks": element_results,
        "sign_failures": sign_failures,
        "invalid_failures": invalid_failures,
        "element_failures": element_failures,
    })

    if sign_failures or invalid_failures or element_failures:
        dbg.problem("western_zodiac_checks_failed", {
            "sign_failures": sign_failures,
            "invalid_failures": invalid_failures,
            "element_failures": element_failures,
        })


# ---------------------------------------------------------------------------
# Section: eastern zodiac
# ---------------------------------------------------------------------------

def run_eastern_zodiac_checks(dbg: Any, zodiac: Any) -> None:
    """Verify Eastern zodiac including CNY boundary cases and edge handling."""

    # CNY 2000 = Feb 5 (verified historical)
    # Boundary: Jan 1 → lunar 1999 (Rabbit), Feb 5 → lunar 2000 (Dragon)
    animal_cases = {
        "jan1_2000_rabbit":   (1,  1, 2000, "Coniglio"),  # before CNY 2000
        "feb5_2000_dragon":   (5,  2, 2000, "Drago"),     # on CNY 2000 boundary
        "feb4_2000_rabbit":   (4,  2, 2000, "Coniglio"),  # one day before CNY
        "rat_2020":           (25, 1, 2020, "Ratto"),     # on CNY 2020 = Jan 25
        "rat_2020_jan24":     (24, 1, 2020, "Maiale"),    # day before CNY 2020
        "ox_2021":            (12, 2, 2021, "Bue"),       # on CNY 2021 = Feb 12
        "dragon_2024":        (10, 2, 2024, "Drago"),     # on CNY 2024 = Feb 10
        "dragon_2024_late":   (15, 3, 2024, "Drago"),     # after CNY 2024
    }

    results = {}
    for name, (day, month, year, expected_animal) in animal_cases.items():
        result = zodiac.get_eastern_zodiac(day, month, year)
        got = result["animal"] if result else None
        results[name] = {
            "day": day, "month": month, "year": year,
            "expected": expected_animal, "got": got,
            "ok": got == expected_animal,
        }

    # Yin/Yang checks
    yy_cases = {
        "yang_2020_rat":  (25, 1, 2020, "Yang"),  # 2020 = even → Yang
        "yin_2021_ox":    (12, 2, 2021, "Yin"),   # 2021 = odd → Yin
        "yang_2024_drag": (10, 2, 2024, "Yang"),  # 2024 = even → Yang
    }
    yy_results = {}
    for name, (day, month, year, expected_yy) in yy_cases.items():
        result = zodiac.get_eastern_zodiac(day, month, year)
        got = result["yin_yang"] if result else None
        yy_results[name] = {"expected": expected_yy, "got": got, "ok": got == expected_yy}

    # Element checks
    elem_cases = {
        "metal_2020":  (25, 1, 2020, "Metallo"),  # chinese_year 2020, %10=0 → Metallo
        "wood_2024":   (10, 2, 2024, "Legno"),    # chinese_year 2024, %10=4 → Legno
        "earth_1999":  (16, 2, 1999, "Terra"),    # chinese_year 1999 (Rabbit year, after CNY), %10=9 → Terra
    }
    elem_results = {}
    for name, (day, month, year, expected_elem) in elem_cases.items():
        result = zodiac.get_eastern_zodiac(day, month, year)
        got = result["element"] if result else None
        elem_results[name] = {"expected": expected_elem, "got": got, "ok": got == expected_elem}

    # Out of range: must return None
    oor_cases = {
        "year_1800":   (1, 1, 1800),
        "year_2200":   (1, 1, 2200),
        "year_1899":   (1, 1, 1899),
        "year_2101":   (1, 1, 2101),
    }
    oor_results = {}
    for name, (day, month, year) in oor_cases.items():
        result = zodiac.get_eastern_zodiac(day, month, year)
        oor_results[name] = {"year": year, "got": result, "ok": result is None}

    # Invalid day/month with valid year must return None
    inv_cases = {
        "day_zero":   (0,  1, 2000),
        "month_13":   (1, 13, 2000),
    }
    inv_results = {}
    for name, (day, month, year) in inv_cases.items():
        result = zodiac.get_eastern_zodiac(day, month, year)
        inv_results[name] = {"got": result, "ok": result is None}

    animal_failures = [k for k, v in results.items() if not v["ok"]]
    yy_failures = [k for k, v in yy_results.items() if not v["ok"]]
    elem_failures = [k for k, v in elem_results.items() if not v["ok"]]
    oor_failures = [k for k, v in oor_results.items() if not v["ok"]]
    inv_failures = [k for k, v in inv_results.items() if not v["ok"]]

    dbg.section("eastern_zodiac", {
        "animal_checks": results,
        "yin_yang_checks": yy_results,
        "element_checks": elem_results,
        "out_of_range_checks": oor_results,
        "invalid_input_checks": inv_results,
        "animal_failures": animal_failures,
        "yy_failures": yy_failures,
        "elem_failures": elem_failures,
        "oor_failures": oor_failures,
        "inv_failures": inv_failures,
    })

    if animal_failures or yy_failures or elem_failures or oor_failures or inv_failures:
        dbg.problem("eastern_zodiac_checks_failed", {
            "animal_failures": animal_failures,
            "yy_failures": yy_failures,
            "elem_failures": elem_failures,
            "oor_failures": oor_failures,
            "inv_failures": inv_failures,
        })


# ---------------------------------------------------------------------------
# Section: get_zodiac_info
# ---------------------------------------------------------------------------

def run_zodiac_info_checks(dbg: Any, zodiac: Any) -> None:
    """Verify get_zodiac_info returns correct combined structure."""

    # With year: both western and eastern should be present
    info_with_year = zodiac.get_zodiac_info(10, 2, 2024)
    has_western = isinstance(info_with_year.get("western"), dict)
    has_eastern = isinstance(info_with_year.get("eastern"), dict)
    western_sign_ok = info_with_year.get("western", {}).get("sign") == "Acquario"
    eastern_animal_ok = info_with_year.get("eastern", {}).get("animal") == "Drago"

    # Without year: western present, eastern None
    info_no_year = zodiac.get_zodiac_info(15, 6)
    western_present = isinstance(info_no_year.get("western"), dict)
    eastern_none = info_no_year.get("eastern") is None

    # Invalid day: both None
    info_invalid = zodiac.get_zodiac_info(0, 1)
    both_none = info_invalid.get("western") is None and info_invalid.get("eastern") is None

    checks = {
        "with_year_has_western": has_western,
        "with_year_has_eastern": has_eastern,
        "with_year_western_sign_acquario": western_sign_ok,
        "with_year_eastern_animal_drago": eastern_animal_ok,
        "no_year_western_present": western_present,
        "no_year_eastern_is_none": eastern_none,
        "invalid_day_both_none": both_none,
    }

    failures = [k for k, v in checks.items() if not v]

    dbg.section("zodiac_info", {
        "with_year_result": {
            "western_sign": info_with_year.get("western", {}).get("sign"),
            "eastern_animal": info_with_year.get("eastern", {}).get("animal"),
        },
        "no_year_result": {
            "western_sign": info_no_year.get("western", {}).get("sign"),
            "eastern": info_no_year.get("eastern"),
        },
        "checks": checks,
        "failures": failures,
    })

    if failures:
        dbg.problem("zodiac_info_checks_failed", {"failures": failures})


# ---------------------------------------------------------------------------
# Section: format helpers
# ---------------------------------------------------------------------------

def run_format_checks(dbg: Any, zodiac: Any) -> None:
    """Verify format_western_line and format_eastern_line output shapes."""

    western = zodiac.get_western_zodiac(23, 11)  # Sagittario
    eastern = zodiac.get_eastern_zodiac(10, 2, 2024)  # Drago, Yang, Legno

    w_line = zodiac.format_western_line(western) if western else None
    e_line = zodiac.format_eastern_line(eastern) if eastern else None

    w_ok = isinstance(w_line, str) and "Sagittario" in w_line and "Fuoco" in w_line
    e_ok = isinstance(e_line, str) and "Drago" in e_line and "Yang" in e_line and "Legno" in e_line

    # Spot check separator character (middle dot · U+00B7)
    w_sep_ok = "\u00b7" in w_line if w_line else False
    e_sep_ok = "\u00b7" in e_line if e_line else False

    checks = {
        "western_line_is_str": isinstance(w_line, str),
        "western_line_has_sign": w_ok,
        "eastern_line_is_str": isinstance(e_line, str),
        "eastern_line_has_animal": e_ok,
        "western_uses_middle_dot": w_sep_ok,
        "eastern_uses_middle_dot": e_sep_ok,
    }

    failures = [k for k, v in checks.items() if not v]

    dbg.section("format_helpers", {
        "western_line": w_line,
        "eastern_line": e_line,
        "checks": checks,
        "failures": failures,
    })

    if failures:
        dbg.problem("format_checks_failed", {"failures": failures})


# ---------------------------------------------------------------------------
# Section: CNY table completeness
# ---------------------------------------------------------------------------

def run_cny_table_checks(dbg: Any, zodiac: Any) -> None:
    """Verify the CNY table has correct coverage and value ranges."""

    table = zodiac._CHINESE_NEW_YEAR
    years = sorted(table.keys())
    expected_min = 1900
    expected_max = 2100
    expected_count = expected_max - expected_min + 1

    has_min = years[0] == expected_min if years else False
    has_max = years[-1] == expected_max if years else False
    count_ok = len(table) == expected_count

    # All CNY dates should fall in [Jan 20, Feb 20]
    range_violations = []
    for yr, (m, d) in table.items():
        if not ((m == 1 and d >= 20) or (m == 2 and d <= 20)):
            range_violations.append((yr, m, d))

    # No gaps in the year sequence
    gaps = [y for i, y in enumerate(years[1:], 1) if y - years[i - 1] != 1]

    # Spot check known dates
    spot_checks = {
        "cny_2000_feb5":  table.get(2000) == (2, 5),
        "cny_2020_jan25": table.get(2020) == (1, 25),
        "cny_2021_feb12": table.get(2021) == (2, 12),
        "cny_2024_feb10": table.get(2024) == (2, 10),
        "cny_1900_jan31": table.get(1900) == (1, 31),
    }

    checks = {
        "starts_at_1900": has_min,
        "ends_at_2100": has_max,
        "count_201": count_ok,
        "no_gaps": len(gaps) == 0,
        "no_range_violations": len(range_violations) == 0,
    }
    checks.update(spot_checks)

    failures = [k for k, v in checks.items() if not v]

    dbg.section("cny_table", {
        "count": len(table),
        "first_year": years[0] if years else None,
        "last_year": years[-1] if years else None,
        "range_violations": range_violations[:5],  # show at most 5
        "gaps": gaps[:5],
        "spot_checks": spot_checks,
        "checks": checks,
        "failures": failures,
    })

    if failures:
        dbg.problem("cny_table_checks_failed", {
            "failures": failures,
            "range_violations_count": len(range_violations),
            "gaps": gaps,
        })


# ---------------------------------------------------------------------------
# Section: zodiac constants (Step 2)
# ---------------------------------------------------------------------------

def run_zodiac_constants_checks(dbg: Any, constants: Any) -> None:
    """Verify BIRTHDAY_ZODIAC_MODE_* constants exist and are internally consistent."""

    checks = {
        "none_value":    getattr(constants, "BIRTHDAY_ZODIAC_MODE_NONE",    None) == "none",
        "western_value": getattr(constants, "BIRTHDAY_ZODIAC_MODE_WESTERN", None) == "western",
        "eastern_value": getattr(constants, "BIRTHDAY_ZODIAC_MODE_EASTERN", None) == "eastern",
        "both_value":    getattr(constants, "BIRTHDAY_ZODIAC_MODE_BOTH",    None) == "both",
    }

    # BIRTHDAY_ZODIAC_MODES tuple must contain all four values, no duplicates
    modes_tuple = getattr(constants, "BIRTHDAY_ZODIAC_MODES", None)
    checks["modes_tuple_exists"] = isinstance(modes_tuple, tuple)
    checks["modes_tuple_length_4"] = len(modes_tuple) == 4 if isinstance(modes_tuple, tuple) else False
    checks["modes_no_duplicates"] = (
        len(set(modes_tuple)) == len(modes_tuple) if isinstance(modes_tuple, tuple) else False
    )
    if isinstance(modes_tuple, tuple):
        expected_values = {"none", "western", "eastern", "both"}
        checks["modes_all_expected_values"] = set(modes_tuple) == expected_values
    else:
        checks["modes_all_expected_values"] = False

    # All four constants must be distinct strings
    all_vals = [
        getattr(constants, "BIRTHDAY_ZODIAC_MODE_NONE",    None),
        getattr(constants, "BIRTHDAY_ZODIAC_MODE_WESTERN", None),
        getattr(constants, "BIRTHDAY_ZODIAC_MODE_EASTERN", None),
        getattr(constants, "BIRTHDAY_ZODIAC_MODE_BOTH",    None),
    ]
    checks["all_four_distinct"] = len(set(all_vals)) == 4 and all(isinstance(v, str) for v in all_vals)

    failures = [k for k, v in checks.items() if not v]

    dbg.section("zodiac_constants", {
        "mode_none":    getattr(constants, "BIRTHDAY_ZODIAC_MODE_NONE",    None),
        "mode_western": getattr(constants, "BIRTHDAY_ZODIAC_MODE_WESTERN", None),
        "mode_eastern": getattr(constants, "BIRTHDAY_ZODIAC_MODE_EASTERN", None),
        "mode_both":    getattr(constants, "BIRTHDAY_ZODIAC_MODE_BOTH",    None),
        "modes_tuple":  list(modes_tuple) if isinstance(modes_tuple, tuple) else None,
        "checks": checks,
        "failures": failures,
    })

    if failures:
        dbg.problem("zodiac_constants_checks_failed", {"failures": failures})


# ---------------------------------------------------------------------------
# Section: storage default (Step 3)
# ---------------------------------------------------------------------------

def run_storage_default_checks(dbg: Any) -> None:
    """Verify birthday_zodiac_mode is present in _default_user_prefs and merges correctly."""
    import os
    import json
    import tempfile

    try:
        from modules import constants as C
        from modules.storage import StorageManager
    except ModuleNotFoundError as exc:
        dbg.section("storage_default", {"error": str(exc), "skipped": True})
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(base_data_dir=os.path.join(tmpdir, "data"), admin_id=None)

        # Fresh user: must have zodiac_mode default
        user_id = 77
        storage.setup_user_space(user_id)
        prefs = storage.get_user_prefs(user_id)

        fresh_checks = {
            "key_present": "birthday_zodiac_mode" in prefs,
            "default_is_none": prefs.get("birthday_zodiac_mode") == C.BIRTHDAY_ZODIAC_MODE_NONE,
            "default_value_is_str": isinstance(prefs.get("birthday_zodiac_mode"), str),
        }

        # Legacy user (prefs without zodiac key): merge must inject default
        legacy_path = os.path.join(tmpdir, "data", "88", "alerts.json")
        os.makedirs(os.path.dirname(legacy_path), exist_ok=True)
        with open(legacy_path, "w", encoding="utf-8") as fh:
            json.dump({
                "tags": [], "alerts": [], "postpone_queue": [],
                "user_prefs": {"timezone_mode": "server"},
            }, fh)

        legacy_prefs = storage.get_user_prefs(88)
        merge_checks = {
            "legacy_zodiac_key_present": "birthday_zodiac_mode" in legacy_prefs,
            "legacy_zodiac_default_value": (
                legacy_prefs.get("birthday_zodiac_mode") == C.BIRTHDAY_ZODIAC_MODE_NONE
            ),
            "legacy_timezone_preserved": legacy_prefs.get("timezone_mode") == "server",
        }

        # update_user_prefs: setting a non-default value must persist
        storage.update_user_prefs(user_id, {"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_WESTERN})
        updated_prefs = storage.get_user_prefs(user_id)
        update_checks = {
            "update_persisted": (
                updated_prefs.get("birthday_zodiac_mode") == C.BIRTHDAY_ZODIAC_MODE_WESTERN
            ),
        }

    all_checks = {}
    all_checks.update(fresh_checks)
    all_checks.update(merge_checks)
    all_checks.update(update_checks)
    failures = [k for k, v in all_checks.items() if not v]

    dbg.section("storage_default", {
        "fresh_prefs_zodiac_mode": prefs.get("birthday_zodiac_mode"),
        "legacy_prefs_zodiac_mode": legacy_prefs.get("birthday_zodiac_mode"),
        "updated_prefs_zodiac_mode": updated_prefs.get("birthday_zodiac_mode"),
        "fresh_checks": fresh_checks,
        "merge_checks": merge_checks,
        "update_checks": update_checks,
        "failures": failures,
    })

    if failures:
        dbg.problem("storage_default_checks_failed", {"failures": failures})


# ---------------------------------------------------------------------------
# Section: scheduler zodiac block (Steps 5)
# ---------------------------------------------------------------------------

def run_scheduler_zodiac_checks(dbg: Any) -> None:
    """Verify append_zodiac_block output via format_main_alert and format_pre_alert."""
    from datetime import datetime as _dt

    try:
        from modules import constants as C
        from modules.scheduler_messagelogic import format_main_alert, format_pre_alert
    except ModuleNotFoundError as exc:
        dbg.section("scheduler_zodiac", {"error": str(exc), "skipped": True})
        return

    bday_alert = {
        "type": 6,
        "title": "Test Person",
        "birth_year": 1988,
        "tags": [],
        "schedule": {"date": "23/11", "time": "09:00"},
    }
    scheduled = _dt(2025, 11, 23, 9, 0)

    # mode=none: no zodiac block
    msg_none = format_main_alert(bday_alert, scheduled, user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_NONE})
    # mode=western: western sign present
    msg_west = format_main_alert(bday_alert, scheduled, user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_WESTERN})
    # mode=eastern: eastern animal present (1988 = Dragon year, Nov 23 after CNY)
    msg_east = format_main_alert(bday_alert, scheduled, user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_EASTERN})
    # mode=both: both present
    msg_both = format_main_alert(bday_alert, scheduled, user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_BOTH})
    # user_prefs=None: no zodiac block
    msg_no_prefs = format_main_alert(bday_alert, scheduled, user_prefs=None)

    # Pre-alert equivalents
    pre_none = format_pre_alert(bday_alert, scheduled, user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_NONE})
    pre_west = format_pre_alert(bday_alert, scheduled, user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_WESTERN})
    pre_both = format_pre_alert(bday_alert, scheduled, user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_BOTH})

    # Birthday without birth_year: eastern returns None, western still works
    bday_no_year = dict(bday_alert)
    bday_no_year.pop("birth_year", None)
    msg_east_no_year = format_main_alert(bday_no_year, scheduled, user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_EASTERN})
    msg_both_no_year = format_main_alert(bday_no_year, scheduled, user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_BOTH})

    # Non-birthday alert: zodiac block must never appear regardless of prefs
    regular_alert = {"type": 1, "title": "Meeting", "tags": [], "schedule": {"date": "23/11", "time": "09:00"}}
    msg_regular = format_main_alert(regular_alert, scheduled, user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_BOTH})

    checks = {
        # mode=none produces no zodiac emoji
        "none_no_western_emoji": "🔮" not in msg_none,
        "none_no_eastern_emoji": "🐉" not in msg_none,
        # mode=western has 🔮 but not 🐉
        "west_has_western_emoji": "🔮" in msg_west,
        "west_no_eastern_emoji": "🐉" not in msg_west,
        "west_has_sagittario": "Sagittario" in msg_west,
        # mode=eastern has 🐉 but not 🔮
        "east_has_eastern_emoji": "🐉" in msg_east,
        "east_no_western_emoji": "🔮" not in msg_east,
        # mode=both has both
        "both_has_western_emoji": "🔮" in msg_both,
        "both_has_eastern_emoji": "🐉" in msg_both,
        # user_prefs=None: no zodiac block
        "no_prefs_no_western": "🔮" not in msg_no_prefs,
        # eastern mode without birth_year: no eastern emoji (graceful skip)
        "east_no_year_no_eastern_emoji": "🐉" not in msg_east_no_year,
        # both mode without birth_year: western still shown
        "both_no_year_has_western": "🔮" in msg_both_no_year,
        "both_no_year_no_eastern": "🐉" not in msg_both_no_year,
        # non-birthday alert never gets zodiac block
        "regular_no_zodiac": "🔮" not in msg_regular and "🐉" not in msg_regular,
        # pre-alert: same logic applies
        "pre_none_no_zodiac": "🔮" not in pre_none,
        "pre_west_has_western": "🔮" in pre_west,
        "pre_both_has_both": "🔮" in pre_both and "🐉" in pre_both,
        # birthday header still present
        "main_birthday_header": "BIRTHDAY" in msg_west,
        "pre_birthday_header": "UPCOMING BIRTHDAY" in pre_west,
    }

    failures = [k for k, v in checks.items() if not v]
    dbg.section("scheduler_zodiac", {
        "checks": checks,
        "failures": failures,
        "msg_west_snippet": msg_west[:120] if msg_west else None,
        "msg_both_snippet": msg_both[:120] if msg_both else None,
    })
    if failures:
        dbg.problem("scheduler_zodiac_checks_failed", {"failures": failures})


# ---------------------------------------------------------------------------
# Section: birthday summary zodiac block (Step 6)
# ---------------------------------------------------------------------------

def run_birthday_summary_zodiac_checks(dbg: Any) -> None:
    """Verify format_birthday_summary includes zodiac lines when mode is set."""
    try:
        from modules import constants as C
        from modules.handlers.birthday_flow.render import (
            format_bday_pre_alerts,
            format_birthday_summary,
        )
    except ModuleNotFoundError as exc:
        dbg.section("birthday_summary_zodiac", {"error": str(exc), "skipped": True})
        return

    data = {
        "title": "Mario Rossi",
        "schedule": {"date": "23/11", "time": "09:00"},
        "birth_year": 1988,
        "pre_alerts": [],
        "additional_info": "",
        "tags": [],
    }

    # mode=none: no zodiac lines
    summary_none = format_birthday_summary(data, user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_NONE})
    # mode=western: western line present
    summary_west = format_birthday_summary(data, user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_WESTERN})
    # mode=eastern: eastern line present
    summary_east = format_birthday_summary(data, user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_EASTERN})
    # mode=both: both lines present
    summary_both = format_birthday_summary(data, user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_BOTH})
    # user_prefs=None: no zodiac (backward-compat)
    summary_no_prefs = format_birthday_summary(data, user_prefs=None)
    # alert_id provided: success banner present and zodiac still shown
    summary_saved = format_birthday_summary(data, alert_id="abc123", user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_WESTERN})
    # legacy-invalid/non-renderable pre-alert tokens must resolve to explicit None.
    legacy_pre_fallback = format_bday_pre_alerts({"pre_alerts": [None, "", "   "]})
    data_legacy_invalid_pre = dict(data)
    data_legacy_invalid_pre["pre_alerts"] = [None, "", "   "]
    summary_legacy_invalid_pre = format_birthday_summary(
        data_legacy_invalid_pre,
        user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_NONE},
    )

    # No birth_year: eastern returns None, eastern mode skips gracefully
    data_no_year = dict(data)
    data_no_year.pop("birth_year", None)
    summary_east_no_year = format_birthday_summary(data_no_year, user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_EASTERN})
    summary_both_no_year = format_birthday_summary(data_no_year, user_prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_BOTH})

    checks = {
        "none_no_zodiac_label": "Zodiac" not in summary_none,
        "west_has_zodiac_label": "Zodiac" in summary_west,
        "west_has_sagittario": "Sagittario" in summary_west,
        "west_no_chinese_label": "Chinese Zodiac" not in summary_west,
        "east_has_chinese_label": "Chinese Zodiac" in summary_east,
        "east_no_western_label": "**Zodiac:**" not in summary_east,
        "both_has_zodiac": "**Zodiac:**" in summary_both,
        "both_has_chinese_zodiac": "Chinese Zodiac" in summary_both,
        "no_prefs_no_zodiac": "Zodiac" not in summary_no_prefs,
        "saved_has_success_banner": "Birthday Saved Successfully" in summary_saved,
        "saved_has_zodiac": "Zodiac" in summary_saved,
        "legacy_pre_fallback_none": legacy_pre_fallback == "None",
        "legacy_summary_prealerts_none": "**Pre-Alerts:** `None`" in summary_legacy_invalid_pre,
        "east_no_year_no_chinese": "Chinese Zodiac" not in summary_east_no_year,
        "both_no_year_west_shown": "**Zodiac:**" in summary_both_no_year,
        "both_no_year_no_chinese": "Chinese Zodiac" not in summary_both_no_year,
    }

    failures = [k for k, v in checks.items() if not v]
    dbg.section("birthday_summary_zodiac", {
        "checks": checks,
        "failures": failures,
        "summary_west_snippet": summary_west[:150] if summary_west else None,
        "summary_both_snippet": summary_both[:150] if summary_both else None,
        "summary_legacy_invalid_pre_snippet": (
            summary_legacy_invalid_pre[:150] if summary_legacy_invalid_pre else None
        ),
    })
    if failures:
        dbg.problem("birthday_summary_zodiac_checks_failed", {"failures": failures})


# ---------------------------------------------------------------------------
# Section: zodiac assembler (Step 7a)
# ---------------------------------------------------------------------------

def run_zodiac_assembler_checks(dbg: Any) -> None:
    """Verify assemble_zodiac_message builds Italian messages from zodiac info."""
    import random as _random

    try:
        from modules import zodiac as _zodiac
        from modules.handlers.birthday_flow.message_suggestions.zodiac_assembler import (
            assemble_zodiac_message,
        )
    except ModuleNotFoundError as exc:
        dbg.section("zodiac_assembler", {"error": str(exc), "skipped": True})
        return

    western_info = _zodiac.get_western_zodiac(23, 11)   # Sagittario
    eastern_info = _zodiac.get_eastern_zodiac(10, 2, 2024)  # Drago, Yang, Legno

    # Basic success cases
    result_west = assemble_zodiac_message(western_info, None, use_western=True, use_eastern=False)
    result_east = assemble_zodiac_message(None, eastern_info, use_western=False, use_eastern=True)
    result_both = assemble_zodiac_message(western_info, eastern_info, use_western=True, use_eastern=True)
    result_none_none = assemble_zodiac_message(None, None, use_western=True, use_eastern=True)

    # With turning_age and title
    result_with_meta = assemble_zodiac_message(
        western_info, None,
        use_western=True, use_eastern=False,
        turning_age=35, title="Mario",
    )

    # Determinism: same seed → same result
    rng_a = _random.Random(42)
    rng_b = _random.Random(42)
    det_a = assemble_zodiac_message(western_info, eastern_info, use_western=True, use_eastern=True, rng=rng_a)
    det_b = assemble_zodiac_message(western_info, eastern_info, use_western=True, use_eastern=True, rng=rng_b)

    # Randomness: 10 samples with different seeds should yield at least 2 distinct outputs
    rng_samples = [
        assemble_zodiac_message(western_info, None, use_western=True, rng=_random.Random(i))
        for i in range(10)
    ]
    has_variation = len(set(rng_samples)) > 1

    # use_western=False with western_info provided: western content must not appear
    result_east_only = assemble_zodiac_message(western_info, eastern_info, use_western=False, use_eastern=True)

    checks = {
        "west_only_is_str": isinstance(result_west, str),
        "west_only_non_empty": bool(result_west),
        "east_only_is_str": isinstance(result_east, str),
        "east_only_non_empty": bool(result_east),
        "both_is_str": isinstance(result_both, str),
        "both_non_empty": bool(result_both),
        "none_none_returns_none": result_none_none is None,
        "west_has_sagittario": bool(result_west) and "Sagittario" in result_west,
        "east_has_drago": bool(result_east) and "Drago" in result_east,
        "both_has_sagittario": bool(result_both) and "Sagittario" in result_both,
        "both_has_drago": bool(result_both) and "Drago" in result_both,
        "with_age_contains_35": bool(result_with_meta) and "35" in result_with_meta,
        "with_title_contains_mario": bool(result_with_meta) and "Mario" in result_with_meta,
        "determinism_same_seed": det_a == det_b,
        "randomness_across_seeds": has_variation,
        "east_only_no_sagittario": bool(result_east_only) and "Sagittario" not in result_east_only,
        "east_only_has_drago": bool(result_east_only) and "Drago" in result_east_only,
    }

    failures = [k for k, v in checks.items() if not v]
    dbg.section("zodiac_assembler", {
        "checks": checks,
        "failures": failures,
        "result_west_snippet": result_west[:120] if result_west else None,
        "result_east_snippet": result_east[:120] if result_east else None,
        "result_both_snippet": result_both[:180] if result_both else None,
    })

    if failures:
        dbg.problem("zodiac_assembler_checks_failed", {"failures": failures})


# ---------------------------------------------------------------------------
# Section: infer_zodiac_context (Step 7c)
# ---------------------------------------------------------------------------

def run_infer_zodiac_context_checks(dbg: Any) -> None:
    """Verify infer_zodiac_context returns correct use_* flags for each zodiac mode."""
    try:
        from modules import constants as C
        from modules.handlers.birthday_flow.message_suggestions.inference import (
            infer_zodiac_context,
        )
    except ModuleNotFoundError as exc:
        dbg.section("infer_zodiac_context", {"error": str(exc), "skipped": True})
        return

    alert_with_year = {
        "type": 6,
        "title": "Test",
        "birth_year": 1988,
        "schedule": {"date": "23/11", "time": "09:00"},
    }
    alert_no_year = {
        "type": 6,
        "title": "Test",
        "schedule": {"date": "23/11", "time": "09:00"},
    }

    def ctx(alert, mode):
        return infer_zodiac_context(alert, {"birthday_zodiac_mode": mode})

    west = ctx(alert_with_year, C.BIRTHDAY_ZODIAC_MODE_WESTERN)
    east_with_year = ctx(alert_with_year, C.BIRTHDAY_ZODIAC_MODE_EASTERN)
    east_no_year = ctx(alert_no_year, C.BIRTHDAY_ZODIAC_MODE_EASTERN)
    both = ctx(alert_with_year, C.BIRTHDAY_ZODIAC_MODE_BOTH)
    none_with_year = ctx(alert_with_year, C.BIRTHDAY_ZODIAC_MODE_NONE)
    none_no_year = ctx(alert_no_year, C.BIRTHDAY_ZODIAC_MODE_NONE)
    no_prefs = infer_zodiac_context(alert_with_year, None)

    checks = {
        # mode=western
        "western_use_western": west.get("use_western") is True,
        "western_no_eastern": west.get("use_eastern") is False,
        "western_western_info_present": isinstance(west.get("western_info"), dict),
        # mode=eastern with birth_year
        "eastern_with_year_use_eastern": east_with_year.get("use_eastern") is True,
        "eastern_with_year_no_western": east_with_year.get("use_western") is False,
        "eastern_with_year_eastern_info_present": isinstance(east_with_year.get("eastern_info"), dict),
        # mode=eastern without birth_year → fallback to western
        "eastern_no_year_fallback_western": east_no_year.get("use_western") is True,
        "eastern_no_year_no_eastern": east_no_year.get("use_eastern") is False,
        "eastern_no_year_missing_flag": east_no_year.get("eastern_missing_year") is True,
        # mode=both
        "both_use_western": both.get("use_western") is True,
        "both_use_eastern": both.get("use_eastern") is True,
        "both_eastern_info_present": isinstance(both.get("eastern_info"), dict),
        # mode=none with birth_year → some zodiac chosen
        "none_with_year_some_chosen": bool(none_with_year.get("use_western") or none_with_year.get("use_eastern")),
        # mode=none without birth_year → use western (eastern unavailable)
        "none_no_year_use_western": none_no_year.get("use_western") is True,
        # no prefs → treated as none mode
        "no_prefs_zodiac_mode_none": no_prefs.get("zodiac_mode") == C.BIRTHDAY_ZODIAC_MODE_NONE,
        # zodiac_mode field is always present and a string
        "west_mode_field": west.get("zodiac_mode") == C.BIRTHDAY_ZODIAC_MODE_WESTERN,
        "east_mode_field": east_with_year.get("zodiac_mode") == C.BIRTHDAY_ZODIAC_MODE_EASTERN,
        "both_mode_field": both.get("zodiac_mode") == C.BIRTHDAY_ZODIAC_MODE_BOTH,
    }

    failures = [k for k, v in checks.items() if not v]
    dbg.section("infer_zodiac_context", {
        "checks": checks,
        "failures": failures,
        "west_snippet": {k: west.get(k) for k in ("zodiac_mode", "use_western", "use_eastern", "eastern_missing_year")},
        "east_no_year_snippet": {k: east_no_year.get(k) for k in ("use_western", "use_eastern", "eastern_missing_year")},
        "both_snippet": {k: both.get(k) for k in ("use_western", "use_eastern")},
    })

    if failures:
        dbg.problem("infer_zodiac_context_checks_failed", {"failures": failures})
