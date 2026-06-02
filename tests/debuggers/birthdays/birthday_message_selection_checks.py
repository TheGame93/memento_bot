from __future__ import annotations

import random
from typing import Any


def parse_unknown_args(args: list[str]) -> list[str]:
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def run_inference_checks(dbg: Any, inference: Any) -> None:
    checks = {}

    rich_alert = {
        "id": "bday_rich",
        "title": "Best friend and boss celebration",
        "tags": ["🫂 Friends", "💼 Work"],
        "birth_year": 1995,
    }
    rich_ctx = inference.infer_message_context(rich_alert, occurrence_year=2026)
    checks["rich_has_work_tag_group"] = "work" in rich_ctx.get("tag_groups", [])
    checks["rich_has_friends_tag_group"] = "friends" in rich_ctx.get("tag_groups", [])
    checks["rich_has_best_friend_hint"] = "best_friend" in rich_ctx.get("title_hints", [])
    checks["rich_has_boss_hint"] = "boss" in rich_ctx.get("title_hints", [])
    checks["rich_turning_age"] = rich_ctx.get("turning_age") == 31
    checks["rich_turning_age_known"] = rich_ctx.get("turning_age_known") is True
    checks["rich_occurrence_year"] = rich_ctx.get("occurrence_year") == 2026

    sparse_alert = {"id": "bday_sparse", "title": None, "tags": None, "birth_year": "bad"}
    sparse_ctx = inference.infer_message_context(sparse_alert, occurrence_year=2026)
    checks["sparse_defaults_to_others"] = sparse_ctx.get("tag_groups") == ["others"]
    checks["sparse_defaults_to_generic_hint"] = sparse_ctx.get("title_hints") == ["generic"]
    checks["sparse_turning_age_none"] = sparse_ctx.get("turning_age") is None
    checks["sparse_gender_defaults_any"] = sparse_ctx.get("gender_hint") == "any"

    dbg.section(
        "inference_contract",
        {
            "rich_context": rich_ctx,
            "sparse_context": sparse_ctx,
            "checks": checks,
        },
    )
    if not all(checks.values()):
        dbg.problem("birthday_message_inference_failed", {"checks": checks})


def _entry(
    entry_id: str,
    *,
    tag_groups: list[str],
    genders: list[str],
    title_hints: list[str],
    age_min: int | None = None,
    age_max: int | None = None,
    weight: int = 1,
    text: str | None = None,
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "text": text or f"text for {entry_id}",
        "tag_groups": list(tag_groups),
        "age_min": age_min,
        "age_max": age_max,
        "genders": list(genders),
        "title_hints": list(title_hints),
        "weight": weight,
    }


def run_selector_stage_checks(dbg: Any, selector: Any) -> None:
    checks = {}

    strict_entries = [
        _entry(
            "strict_target",
            tag_groups=["work"],
            genders=["female"],
            title_hints=["boss"],
            age_min=30,
            age_max=40,
            weight=9,
        ),
        _entry(
            "strict_wrong_title",
            tag_groups=["work"],
            genders=["female"],
            title_hints=["colleague"],
            age_min=30,
            age_max=40,
            weight=1,
        ),
    ]
    strict_ctx = {
        "tag_groups": ["work"],
        "turning_age": 35,
        "gender_hint": "female",
        "title_hints": ["boss", "generic"],
    }
    strict_result = selector.select_template(strict_entries, strict_ctx, rng=random.Random(7))
    checks["strict_stage_selected"] = strict_result.get("fallback_stage") == "strict"
    checks["strict_target_selected"] = strict_result.get("template_id") == "strict_target"

    relax_title_entries = [
        _entry(
            "relax_title_pick",
            tag_groups=["work"],
            genders=["female"],
            title_hints=["generic"],
            age_min=30,
            age_max=40,
        ),
    ]
    relax_title_result = selector.select_template(relax_title_entries, strict_ctx, rng=random.Random(7))
    checks["relax_title_stage"] = relax_title_result.get("fallback_stage") == "relax_title_hint"

    relax_gender_entries = [
        _entry(
            "relax_gender_pick",
            tag_groups=["work"],
            genders=["male"],
            title_hints=["generic"],
            age_min=30,
            age_max=40,
        ),
    ]
    relax_gender_ctx = dict(strict_ctx)
    relax_gender_ctx["title_hints"] = ["generic"]
    relax_gender_result = selector.select_template(relax_gender_entries, relax_gender_ctx, rng=random.Random(7))
    checks["relax_gender_stage"] = relax_gender_result.get("fallback_stage") == "relax_gender"

    relax_age_entries = [
        _entry(
            "relax_age_pick",
            tag_groups=["work"],
            genders=["male"],
            title_hints=["generic"],
            age_min=10,
            age_max=20,
        ),
    ]
    relax_age_result = selector.select_template(relax_age_entries, relax_gender_ctx, rng=random.Random(7))
    checks["relax_age_stage"] = relax_age_result.get("fallback_stage") == "relax_age"

    relax_tags_entries = [
        _entry(
            "relax_tags_pick",
            tag_groups=["others"],
            genders=["any"],
            title_hints=["generic"],
        ),
    ]
    relax_tags_ctx = {"tag_groups": ["love"], "title_hints": ["generic"], "gender_hint": "any", "turning_age": None}
    relax_tags_result = selector.select_template(relax_tags_entries, relax_tags_ctx, rng=random.Random(7))
    checks["relax_tags_stage"] = relax_tags_result.get("fallback_stage") == "relax_tags"

    full_mode_entries = [
        _entry(
            "full_mode_pick",
            tag_groups=["work"],
            genders=["any"],
            title_hints=["generic"],
        ),
    ]
    full_mode_ctx = {"tag_groups": ["love"], "title_hints": ["generic"], "gender_hint": "any", "turning_age": None}
    full_mode_result = selector.select_template(full_mode_entries, full_mode_ctx, rng=random.Random(7))
    checks["full_mode_stage"] = full_mode_result.get("fallback_stage") == "full_mode"

    dbg.section(
        "selector_stages",
        {
            "strict_result": strict_result,
            "relax_title_result": relax_title_result,
            "relax_gender_result": relax_gender_result,
            "relax_age_result": relax_age_result,
            "relax_tags_result": relax_tags_result,
            "full_mode_result": full_mode_result,
            "checks": checks,
        },
    )
    if not all(checks.values()):
        dbg.problem("birthday_message_selector_stage_failed", {"checks": checks})


def run_selector_randomness_checks(dbg: Any, selector: Any) -> None:
    checks = {}

    deterministic_entries = [
        _entry("det_weight_9", tag_groups=["work"], genders=["any"], title_hints=["generic"], weight=9),
        _entry("det_weight_1", tag_groups=["work"], genders=["any"], title_hints=["generic"], weight=1),
    ]
    context = {"tag_groups": ["work"], "title_hints": ["generic"], "gender_hint": "any", "turning_age": None}
    r1 = selector.select_template(deterministic_entries, context, rng=random.Random(12345))
    r2 = selector.select_template(deterministic_entries, context, rng=random.Random(12345))
    checks["seeded_random_deterministic"] = r1.get("template_id") == r2.get("template_id")

    malformed_weight_entries = [
        _entry("valid_weight_pick", tag_groups=["work"], genders=["any"], title_hints=["generic"], weight=2),
        _entry("bad_weight_pick", tag_groups=["work"], genders=["any"], title_hints=["generic"], weight=0),
    ]
    malformed = selector.select_template(malformed_weight_entries, context, rng=random.Random(1))
    diag = malformed.get("diagnostics", {})
    checks["invalid_weight_count_tracked"] = diag.get("invalid_weight_count") == 1
    checks["invalid_weight_skipped"] = malformed.get("template_id") == "valid_weight_pick"
    checks["weighted_choice_used"] = bool(diag.get("used_weighted_choice"))

    dbg.section(
        "selector_randomness",
        {
            "deterministic_result_1": r1,
            "deterministic_result_2": r2,
            "malformed_weight_result": malformed,
            "checks": checks,
        },
    )
    if not all(checks.values()):
        dbg.problem("birthday_message_selector_randomness_failed", {"checks": checks})


def run_archive_integration_checks(dbg: Any, selector: Any, catalog: Any) -> None:
    checks = {}
    archive_sizes = {}
    selected_ids = {}

    context = {
        "tag_groups": ["friends"],
        "title_hints": ["best_friend", "generic"],
        "gender_hint": "any",
        "turning_age": 30,
    }

    for mode in catalog.get_archive_modes():
        entries = catalog.load_archive(mode, allow_empty=False, use_cache=False)
        archive_sizes[mode] = len(entries)
        result = selector.select_template(entries, context, rng=random.Random(99))
        selected_ids[mode] = result.get("template_id")
        checks[f"{mode}_selected"] = result.get("selection_result") == "selected"
        checks[f"{mode}_has_stage"] = result.get("fallback_stage") in selector.SELECTION_STAGES
        checks[f"{mode}_candidate_count_positive"] = int(result.get("candidate_count", 0) or 0) > 0
        checks[f"{mode}_template_present"] = isinstance(result.get("template"), dict)

    dbg.section(
        "archive_integration",
        {
            "archive_sizes": archive_sizes,
            "selected_ids": selected_ids,
            "checks": checks,
        },
    )
    if not all(checks.values()):
        dbg.problem("birthday_message_selector_archive_integration_failed", {"checks": checks})
