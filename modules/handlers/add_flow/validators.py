import re


def normalize_pre_alert_unit(unit_text):
    """Normalize textual pre-alert units into canonical token suffixes."""
    unit_text = unit_text.strip().lower()
    unit_map = {
        "m": "m",
        "min": "m",
        "mins": "m",
        "minute": "m",
        "minutes": "m",
        "h": "h",
        "hour": "h",
        "hours": "h",
        "d": "d",
        "day": "d",
        "days": "d",
        "w": "w",
        "week": "w",
        "weeks": "w",
        "mo": "mo",
        "month": "mo",
        "months": "mo",
    }
    return unit_map.get(unit_text)


def parse_custom_pre_alerts(raw_text):
    """
    Parses comma-separated custom pre-alerts and normalizes them to tokens like:
    30m, 2h, 1d, 2w, 1mo
    Returns (tokens, invalid_parts).
    """
    parts = [p.strip() for p in raw_text.split(",")]
    tokens = []
    invalid = []
    for part in parts:
        if not part:
            continue
        match = re.match(r"^(\d+)\s*([a-zA-Z]+)$", part)
        if not match:
            invalid.append(part)
            continue
        val_text, unit_text = match.groups()
        unit = normalize_pre_alert_unit(unit_text)
        if not unit:
            invalid.append(part)
            continue
        value = int(val_text)
        # 0-unit pre-alerts collapse onto the main alert fire time and cause duplicate sends.
        if value <= 0:
            invalid.append(part)
            continue
        tokens.append(f"{value}{unit}")
    return tokens, invalid


def merge_pre_alerts(existing, new_items):
    """Merge pre-alert tokens while preserving order and removing duplicates."""
    existing = existing or []
    new_items = new_items or []
    merged = []
    seen = set()
    for item in existing + new_items:
        if item in seen:
            continue
        seen.add(item)
        merged.append(item)
    return merged
