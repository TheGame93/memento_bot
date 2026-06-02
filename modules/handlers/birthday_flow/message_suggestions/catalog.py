import json
from pathlib import Path

BIRTHDAY_MESSAGE_MODES = ("polite", "boomer", "cringe")
TAG_GROUPS = {"work", "friends", "family", "love", "pet", "car", "others"}
GENDERS = {"any", "female", "male", "neutral"}
TITLE_HINTS = {
    "generic",
    "mom",
    "dad",
    "sister",
    "brother",
    "boss",
    "best_friend",
    "partner",
    "colleague",
    "child",
    "pet",
    "car",
}
_REQUIRED_FIELDS = ("id", "text", "tag_groups", "genders", "title_hints")
_DATA_DIR = Path(__file__).resolve().parent / "data"
_ARCHIVE_CACHE = {}


class ArchiveValidationError(ValueError):
    """Represent archive-validation failures with structured mode/index/field metadata."""
    def __init__(self, code, *, mode=None, index=None, field=None, detail=None):
        self.code = str(code)
        self.mode = mode
        self.index = index
        self.field = field
        self.detail = detail
        parts = [self.code]
        if mode is not None:
            parts.append(f"mode={mode}")
        if index is not None:
            parts.append(f"index={index}")
        if field is not None:
            parts.append(f"field={field}")
        if detail is not None:
            parts.append(f"detail={detail}")
        super().__init__(" | ".join(parts))


def _clone_entry(entry):
    return {
        "id": entry.get("id"),
        "text": entry.get("text"),
        "tag_groups": list(entry.get("tag_groups", [])),
        "age_min": entry.get("age_min"),
        "age_max": entry.get("age_max"),
        "genders": list(entry.get("genders", [])),
        "title_hints": list(entry.get("title_hints", [])),
        "weight": entry.get("weight"),
    }


def _clone_entries(entries):
    return [_clone_entry(item) for item in entries]


def get_archive_modes():
    """Return supported birthday message archive mode names."""
    return tuple(BIRTHDAY_MESSAGE_MODES)


def clear_archive_cache():
    """Clear the in-memory birthday message archive cache."""
    _ARCHIVE_CACHE.clear()


def _ensure_mode(mode):
    if mode not in BIRTHDAY_MESSAGE_MODES:
        raise ArchiveValidationError("invalid_mode", mode=mode)


def get_archive_path(mode):
    """Return the JSON archive path for the requested message mode."""
    _ensure_mode(mode)
    return _DATA_DIR / f"{mode}.json"


def _require_non_empty_str(value, *, mode, index, field):
    if not isinstance(value, str):
        raise ArchiveValidationError(
            "invalid_type", mode=mode, index=index, field=field, detail="expected_str"
        )
    normalized = value.strip()
    if not normalized:
        raise ArchiveValidationError(
            "empty_string", mode=mode, index=index, field=field
        )
    return normalized


def _normalize_string_enum_list(value, *, allowed, mode, index, field):
    if not isinstance(value, list):
        raise ArchiveValidationError(
            "invalid_type", mode=mode, index=index, field=field, detail="expected_list"
        )
    normalized = []
    for raw in value:
        item = _require_non_empty_str(raw, mode=mode, index=index, field=field).lower()
        if item not in allowed:
            raise ArchiveValidationError(
                "invalid_enum", mode=mode, index=index, field=field, detail=item
            )
        if item not in normalized:
            normalized.append(item)
    if not normalized:
        raise ArchiveValidationError("empty_list", mode=mode, index=index, field=field)
    return normalized


def _normalize_nullable_int(value, *, mode, index, field):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArchiveValidationError(
            "invalid_type", mode=mode, index=index, field=field, detail="expected_int_or_null"
        )
    if value < 0:
        raise ArchiveValidationError(
            "invalid_range", mode=mode, index=index, field=field, detail="must_be_gte_0"
        )
    return value


def _normalize_weight(value, *, mode, index):
    if value is None:
        return 1
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArchiveValidationError(
            "invalid_type", mode=mode, index=index, field="weight", detail="expected_int"
        )
    if value < 1 or value > 100:
        raise ArchiveValidationError(
            "invalid_range", mode=mode, index=index, field="weight", detail="must_be_1_100"
        )
    return value


def validate_archive_entries(entries, mode, *, allow_empty=True):
    """Validate and normalize archive entries against schema and enum/range constraints.
    
    Enforce required fields, unique IDs, normalized enum lists, and age/weight bounds,
    then return canonicalized entries suitable for cached selection pipelines.
    """
    _ensure_mode(mode)
    if not isinstance(entries, list):
        raise ArchiveValidationError(
            "invalid_type", mode=mode, field="entries", detail="expected_list"
        )
    if not entries and not allow_empty:
        raise ArchiveValidationError("archive_empty", mode=mode)

    normalized = []
    seen_ids = set()

    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            raise ArchiveValidationError(
                "invalid_type", mode=mode, index=index, field="entry", detail="expected_dict"
            )

        missing = [key for key in _REQUIRED_FIELDS if key not in item]
        if missing:
            raise ArchiveValidationError(
                "missing_required_fields",
                mode=mode,
                index=index,
                field="entry",
                detail=",".join(missing),
            )

        entry_id = _require_non_empty_str(item.get("id"), mode=mode, index=index, field="id")
        if entry_id in seen_ids:
            raise ArchiveValidationError(
                "duplicate_id", mode=mode, index=index, field="id", detail=entry_id
            )
        seen_ids.add(entry_id)

        text = _require_non_empty_str(item.get("text"), mode=mode, index=index, field="text")
        tag_groups = _normalize_string_enum_list(
            item.get("tag_groups"),
            allowed=TAG_GROUPS,
            mode=mode,
            index=index,
            field="tag_groups",
        )
        genders = _normalize_string_enum_list(
            item.get("genders"),
            allowed=GENDERS,
            mode=mode,
            index=index,
            field="genders",
        )
        title_hints = _normalize_string_enum_list(
            item.get("title_hints"),
            allowed=TITLE_HINTS,
            mode=mode,
            index=index,
            field="title_hints",
        )
        age_min = _normalize_nullable_int(item.get("age_min"), mode=mode, index=index, field="age_min")
        age_max = _normalize_nullable_int(item.get("age_max"), mode=mode, index=index, field="age_max")
        if age_min is not None and age_max is not None and age_min > age_max:
            raise ArchiveValidationError(
                "invalid_age_interval",
                mode=mode,
                index=index,
                field="age_min",
                detail="age_min_gt_age_max",
            )
        weight = _normalize_weight(item.get("weight"), mode=mode, index=index)

        normalized.append(
            {
                "id": entry_id,
                "text": text,
                "tag_groups": tag_groups,
                "age_min": age_min,
                "age_max": age_max,
                "genders": genders,
                "title_hints": title_hints,
                "weight": weight,
            }
        )

    return normalized


def load_archive(mode, *, allow_empty=True, use_cache=True):
    """Load, validate, cache, and clone archive entries for the requested message mode.
    
    Use cache when available, fail with structured `ArchiveValidationError` codes on IO
    or schema issues, and always return defensive copies to callers.
    """
    _ensure_mode(mode)
    if use_cache and mode in _ARCHIVE_CACHE:
        cached = _ARCHIVE_CACHE[mode]
        if not cached and not allow_empty:
            raise ArchiveValidationError("archive_empty", mode=mode)
        return _clone_entries(cached)

    path = get_archive_path(mode)
    if not path.exists() or not path.is_file():
        raise ArchiveValidationError("archive_file_missing", mode=mode, detail=str(path))

    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ArchiveValidationError(
            "archive_json_decode_failed", mode=mode, detail=f"{exc.msg}@{exc.lineno}:{exc.colno}"
        ) from exc
    except OSError as exc:
        raise ArchiveValidationError("archive_file_read_failed", mode=mode, detail=str(exc)) from exc

    normalized = validate_archive_entries(raw, mode, allow_empty=allow_empty)
    _ARCHIVE_CACHE[mode] = _clone_entries(normalized)
    return _clone_entries(_ARCHIVE_CACHE[mode])
