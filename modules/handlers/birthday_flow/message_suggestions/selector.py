from __future__ import annotations

import random
from typing import Any

from modules.handlers.birthday_flow.message_suggestions.catalog import load_archive

SELECTION_STAGES = (
    "strict",
    "relax_title_hint",
    "relax_gender",
    "relax_age",
    "relax_tags",
    "full_mode",
)


def _normalize_context(context: dict[str, Any] | None) -> dict[str, Any]:
    context = context or {}

    tag_groups = []
    for value in context.get("tag_groups", []) or []:
        text = str(value or "").strip().lower()
        if text and text not in tag_groups:
            tag_groups.append(text)

    title_hints = []
    for value in context.get("title_hints", []) or []:
        text = str(value or "").strip().lower()
        if text and text not in title_hints:
            title_hints.append(text)
    if not title_hints:
        title_hints = ["generic"]

    gender_hint = str(context.get("gender_hint", "any") or "any").strip().lower()
    if gender_hint not in {"any", "female", "male", "neutral"}:
        gender_hint = "any"

    turning_age = context.get("turning_age")
    if isinstance(turning_age, bool):
        turning_age = None
    elif turning_age is not None:
        try:
            turning_age = int(turning_age)
        except (TypeError, ValueError):
            turning_age = None

    return {
        "tag_groups": tag_groups,
        "title_hints": title_hints,
        "gender_hint": gender_hint,
        "turning_age": turning_age,
    }


def _matches_age(entry: dict[str, Any], turning_age: int | None) -> bool:
    if turning_age is None:
        return True
    age_min = entry.get("age_min")
    age_max = entry.get("age_max")
    if isinstance(age_min, int) and turning_age < age_min:
        return False
    if isinstance(age_max, int) and turning_age > age_max:
        return False
    return True


def _matches_gender(entry: dict[str, Any], gender_hint: str) -> bool:
    if gender_hint in {"", "any"}:
        return True
    entry_genders = entry.get("genders", []) or []
    return "any" in entry_genders or gender_hint in entry_genders


def _matches_title_hints(entry: dict[str, Any], context_hints: list[str]) -> bool:
    if not context_hints:
        return True
    entry_hints = set(entry.get("title_hints", []) or [])
    specific_hints = {hint for hint in context_hints if hint != "generic"}
    if specific_hints:
        return bool(entry_hints.intersection(specific_hints))
    return bool(entry_hints.intersection(context_hints))


def _matches_tags(entry: dict[str, Any], context_groups: list[str], *, relax_to_others: bool = False) -> bool:
    if not context_groups:
        return True
    entry_groups = set(entry.get("tag_groups", []) or [])
    if not relax_to_others:
        return bool(entry_groups.intersection(context_groups))
    return "others" in entry_groups or bool(entry_groups.intersection(context_groups))


def _filter_candidates(
    entries: list[dict[str, Any]],
    context: dict[str, Any],
    *,
    apply_tags: bool,
    apply_age: bool,
    apply_gender: bool,
    apply_title_hints: bool,
    relax_tags_to_others: bool = False,
) -> list[dict[str, Any]]:
    candidates = []
    for entry in entries:
        if apply_tags and not _matches_tags(
            entry,
            context["tag_groups"],
            relax_to_others=relax_tags_to_others,
        ):
            continue
        if apply_age and not _matches_age(entry, context["turning_age"]):
            continue
        if apply_gender and not _matches_gender(entry, context["gender_hint"]):
            continue
        if apply_title_hints and not _matches_title_hints(entry, context["title_hints"]):
            continue
        candidates.append(entry)
    return candidates


def _pick_candidate(
    candidates: list[dict[str, Any]],
    *,
    rng: random.Random,
) -> tuple[dict[str, Any] | None, int, bool]:
    if not candidates:
        return None, 0, False

    valid_weighted = []
    invalid_weight_count = 0
    for entry in candidates:
        weight = entry.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, int) or weight < 1 or weight > 100:
            invalid_weight_count += 1
            continue
        valid_weighted.append((entry, weight))

    if not valid_weighted:
        return rng.choice(candidates), invalid_weight_count, False

    total_weight = sum(weight for _entry, weight in valid_weighted)
    slot = rng.randint(1, total_weight)
    running = 0
    for entry, weight in valid_weighted:
        running += weight
        if slot <= running:
            return entry, invalid_weight_count, True

    return valid_weighted[-1][0], invalid_weight_count, True


def select_template(
    entries: list[dict[str, Any]] | None,
    context: dict[str, Any] | None = None,
    *,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Select a template through staged fallback filters and weighted random choice.
    
    Apply strict-to-relaxed stages (`strict` through `full_mode`), return diagnostics
    for candidate counts/weight handling, and preserve deterministic behavior with a
    caller-provided RNG.
    """
    safe_entries = [entry for entry in (entries or []) if isinstance(entry, dict)]
    normalized_context = _normalize_context(context)
    stage_candidate_counts = {}
    if rng is None:
        rng = random.Random()

    stage_filters = (
        ("strict", dict(apply_tags=True, apply_age=True, apply_gender=True, apply_title_hints=True, relax_tags_to_others=False)),
        ("relax_title_hint", dict(apply_tags=True, apply_age=True, apply_gender=True, apply_title_hints=False, relax_tags_to_others=False)),
        ("relax_gender", dict(apply_tags=True, apply_age=True, apply_gender=False, apply_title_hints=False, relax_tags_to_others=False)),
        ("relax_age", dict(apply_tags=True, apply_age=False, apply_gender=False, apply_title_hints=False, relax_tags_to_others=False)),
        ("relax_tags", dict(apply_tags=True, apply_age=False, apply_gender=False, apply_title_hints=False, relax_tags_to_others=True)),
        ("full_mode", dict(apply_tags=False, apply_age=False, apply_gender=False, apply_title_hints=False, relax_tags_to_others=False)),
    )

    for stage_name, filter_kwargs in stage_filters:
        candidates = _filter_candidates(safe_entries, normalized_context, **filter_kwargs)
        stage_candidate_counts[stage_name] = len(candidates)
        if not candidates:
            continue
        selected, invalid_weight_count, used_weighted = _pick_candidate(candidates, rng=rng)
        selected_copy = dict(selected) if selected else None
        return {
            "selection_result": "selected" if selected_copy else "empty",
            "reason_code": None if selected_copy else "selection_empty",
            "template": selected_copy,
            "template_id": selected_copy.get("id") if selected_copy else None,
            "text": selected_copy.get("text") if selected_copy else None,
            "fallback_stage": stage_name,
            "candidate_count": len(candidates),
            "diagnostics": {
                "stage_candidate_counts": stage_candidate_counts,
                "invalid_weight_count": invalid_weight_count,
                "used_weighted_choice": used_weighted,
                "context": normalized_context,
            },
        }

    return {
        "selection_result": "empty",
        "reason_code": "selection_empty",
        "template": None,
        "template_id": None,
        "text": None,
        "fallback_stage": None,
        "candidate_count": 0,
        "diagnostics": {
            "stage_candidate_counts": stage_candidate_counts,
            "invalid_weight_count": 0,
            "used_weighted_choice": False,
            "context": normalized_context,
        },
    }


def select_template_from_mode(
    mode: str,
    context: dict[str, Any] | None = None,
    *,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Load mode archive entries and select a template via staged fallback rules."""
    entries = load_archive(mode, allow_empty=False, use_cache=True)
    return select_template(entries, context=context, rng=rng)
