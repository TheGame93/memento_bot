from __future__ import annotations

import copy
from typing import Any

REQUIRED_TAG_GROUPS = (
    "work",
    "friends",
    "family",
    "love",
    "pet",
    "car",
    "others",
)


def parse_unknown_args(args: list[str]) -> list[str]:
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def run_bootstrap_checks(dbg: Any, catalog: Any) -> None:
    modes = catalog.get_archive_modes()
    checks = {
        "modes_exact": tuple(modes) == ("polite", "boomer", "cringe"),
    }

    file_checks = {}
    load_checks = {}
    strict_non_empty_checks = {}
    for mode in modes:
        path = catalog.get_archive_path(mode)
        file_checks[f"{mode}_file_exists"] = bool(path.exists() and path.is_file())

        loaded = catalog.load_archive(mode, allow_empty=True, use_cache=False)
        load_checks[f"{mode}_loads_as_list"] = isinstance(loaded, list)
        load_checks[f"{mode}_allow_empty_load_ok"] = len(loaded) >= 0

        strict_ok = False
        try:
            strict_loaded = catalog.load_archive(mode, allow_empty=False, use_cache=False)
            strict_ok = isinstance(strict_loaded, list) and len(strict_loaded) > 0
        except catalog.ArchiveValidationError:
            strict_ok = False
        strict_non_empty_checks[f"{mode}_strict_load_non_empty"] = strict_ok

    checks.update(file_checks)
    checks.update(load_checks)
    checks.update(strict_non_empty_checks)

    dbg.section(
        "bootstrap_archives",
        {
            "modes": list(modes),
            "checks": checks,
        },
    )
    if not all(checks.values()):
        dbg.problem("birthday_message_archive_bootstrap_failed", {"checks": checks})


def _expect_validation_error(catalog: Any, mode: str, entries: Any, expected_code: str) -> bool:
    try:
        catalog.validate_archive_entries(entries, mode, allow_empty=False)
    except catalog.ArchiveValidationError as exc:
        return getattr(exc, "code", None) == expected_code
    return False


def run_validation_guard_checks(dbg: Any, catalog: Any) -> None:
    valid = {
        "id": "polite_001",
        "text": "Happy birthday and best wishes.",
        "tag_groups": ["friends"],
        "age_min": 18,
        "age_max": 30,
        "genders": ["any"],
        "title_hints": ["generic"],
        "weight": 1,
    }

    checks = {
        "entries_must_be_list": _expect_validation_error(catalog, "polite", {"bad": True}, "invalid_type"),
        "missing_required_fields": _expect_validation_error(
            catalog,
            "polite",
            [{"id": "x", "text": "y", "tag_groups": ["friends"], "genders": ["any"]}],
            "missing_required_fields",
        ),
        "duplicate_id_rejected": _expect_validation_error(catalog, "polite", [dict(valid), dict(valid)], "duplicate_id"),
        "invalid_tag_group_rejected": _expect_validation_error(
            catalog,
            "polite",
            [dict(valid, tag_groups=["unknown"])],
            "invalid_enum",
        ),
        "invalid_gender_rejected": _expect_validation_error(
            catalog,
            "polite",
            [dict(valid, genders=["robot"])],
            "invalid_enum",
        ),
        "invalid_title_hint_rejected": _expect_validation_error(
            catalog,
            "polite",
            [dict(valid, title_hints=["alien"])],
            "invalid_enum",
        ),
        "weight_zero_rejected": _expect_validation_error(
            catalog,
            "polite",
            [dict(valid, weight=0)],
            "invalid_range",
        ),
        "invalid_age_interval_rejected": _expect_validation_error(
            catalog,
            "polite",
            [dict(valid, age_min=50, age_max=30)],
            "invalid_age_interval",
        ),
    }

    dbg.section("validation_guards", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("birthday_message_archive_validation_guards_failed", {"checks": checks})


def run_population_checks(dbg: Any, catalog: Any) -> None:
    checks = {}
    distribution = {}
    mode_sizes = {}

    for mode in catalog.get_archive_modes():
        entries = catalog.load_archive(mode, allow_empty=False, use_cache=False)
        mode_sizes[mode] = len(entries)
        checks[f"{mode}_non_empty"] = len(entries) > 0

        per_group = {key: 0 for key in REQUIRED_TAG_GROUPS}
        for entry in entries:
            for group in entry.get("tag_groups", []):
                if group in per_group:
                    per_group[group] += 1

        distribution[mode] = per_group

        for group in REQUIRED_TAG_GROUPS:
            checks[f"{mode}_has_group_{group}"] = per_group.get(group, 0) > 0

    dbg.section(
        "population_contract",
        {
            "required_mode_non_empty": True,
            "required_tag_groups_per_mode": list(REQUIRED_TAG_GROUPS),
            "mode_sizes": mode_sizes,
            "distribution": distribution,
            "checks": checks,
        },
    )
    if not all(checks.values()):
        dbg.problem("birthday_message_archive_population_failed", {"checks": checks})


def run_cache_copy_checks(dbg: Any, catalog: Any) -> None:
    checks = {}
    cache_attr = "_ARCHIVE_CACHE"
    checks["cache_attr_available"] = hasattr(catalog, cache_attr)
    if not checks["cache_attr_available"]:
        dbg.section("cache_copy_guards", {"checks": checks})
        dbg.problem("birthday_message_archive_cache_copy_failed", {"checks": checks})
        return

    original_cache = copy.deepcopy(getattr(catalog, cache_attr))
    try:
        catalog.clear_archive_cache()
        valid = {
            "id": "polite_cache_guard",
            "text": "Happy birthday and many returns.",
            "tag_groups": ["friends"],
            "age_min": None,
            "age_max": None,
            "genders": ["any"],
            "title_hints": ["generic"],
            "weight": 1,
        }
        normalized = catalog.validate_archive_entries([valid], "polite", allow_empty=False)
        getattr(catalog, cache_attr)["polite"] = normalized

        first_read = catalog.load_archive("polite", allow_empty=False, use_cache=True)
        first_read[0]["tag_groups"].append("work")
        first_read[0]["genders"].append("male")
        first_read[0]["title_hints"].append("boss")

        second_read = catalog.load_archive("polite", allow_empty=False, use_cache=True)
        checks["tag_groups_isolated"] = second_read[0]["tag_groups"] == ["friends"]
        checks["genders_isolated"] = second_read[0]["genders"] == ["any"]
        checks["title_hints_isolated"] = second_read[0]["title_hints"] == ["generic"]
    finally:
        catalog.clear_archive_cache()
        getattr(catalog, cache_attr).update(original_cache)

    dbg.section("cache_copy_guards", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("birthday_message_archive_cache_copy_failed", {"checks": checks})
