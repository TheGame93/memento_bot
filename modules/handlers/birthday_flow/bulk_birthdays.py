import re
import html
from datetime import datetime

from modules.handlers.birthday_flow.search import rank_birthdays_by_name
from modules.tags_logic import contains_emoji, parse_tag

_DATE_SEPARATOR_RE = re.compile(r"[.,/_-]")
_DATE_NORMALIZE_RE = re.compile(r"\s*([.,/_-])\s*")
_SINGLE_COLON_RE = re.compile(r"(?<!:):(?!:)")
# Allow horizontal tab as whitespace for paste-friendly parsing; reject other controls.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")
_MULTI_SPACE_RE = re.compile(r"\s+")

YEAR_MIN = 1900
YEAR_MAX = 2100
DEFAULT_MAX_IMPORT_LINES = 300
DEFAULT_MAX_NAME_LEN = 80
DEFAULT_TAG_SUGGESTION_THRESHOLD = 80
DEFAULT_TEXT_CHUNK_SAFE_LIMIT = 3900
DEFAULT_INVALID_PREVIEW_LIMIT = 120


def collapse_internal_spaces(value):
    """Trim and collapse all internal whitespace runs to a single space."""
    text = "" if value is None else str(value)
    return _MULTI_SPACE_RE.sub(" ", text).strip()


def contains_disallowed_control_chars(value):
    """Return True if the input contains ASCII control characters."""
    if value is None:
        return False
    return bool(_CONTROL_CHAR_RE.search(str(value)))


def validate_bulk_separator_policy(line):
    """
    Validate strict `::` separator policy for one bulk-import line.

    Returns (is_valid, reason_code).
    reason_code is None when valid.
    """
    text = "" if line is None else str(line)
    if contains_disallowed_control_chars(text):
        return False, "control_chars"

    stripped = text.strip()
    if not stripped:
        return False, "empty_line"

    # Reject malformed multi-colon forms such as ::: or ::::
    if ":::" in stripped:
        return False, "invalid_colon_sequence"

    # Reject single ':' occurrences not part of a strict '::' separator.
    if _SINGLE_COLON_RE.search(stripped):
        return False, "single_colon_detected"

    if stripped.count("::") != 2:
        return False, "separator_count_invalid"

    parts = stripped.split("::")
    if len(parts) != 3:
        return False, "parts_count_invalid"

    return True, None


def split_bulk_line_sections(line):
    """Split a valid bulk-import line into three trimmed sections."""
    ok, reason = validate_bulk_separator_policy(line)
    if not ok:
        return None, reason

    parts = [segment.strip() for segment in str(line).strip().split("::")]
    if len(parts) != 3:
        return None, "parts_count_invalid"
    return parts, None


def normalize_date_separators(raw_date):
    """
    Normalize accepted date separators to '/'.

    Accepted separators: '.', ',', '/', '-', '_'.
    Returns normalized token (for example: '2/12/1993') or None when malformed.
    """
    if raw_date is None:
        return None

    text = str(raw_date)
    if contains_disallowed_control_chars(text):
        return None

    normalized = _DATE_NORMALIZE_RE.sub("/", text.strip())
    if not normalized:
        return None

    if _DATE_SEPARATOR_RE.search(normalized) is None:
        return None

    parts = normalized.split("/")
    if len(parts) not in (2, 3):
        return None
    if any(not token for token in parts):
        return None
    if not all(token.isdigit() for token in parts):
        return None

    return "/".join(parts)


def split_normalized_date_tokens(raw_date):
    """Return normalized numeric date tokens or None when date token is malformed."""
    normalized = normalize_date_separators(raw_date)
    if not normalized:
        return None
    return normalized.split("/")


def parse_birthday_date_token(raw_date):
    """
    Parse one birthday date token into storage-normalized values.

    Returns:
        (payload, reason_code)
        payload = {"date_ddmm": "DD/MM", "birth_year": int|None}
    """
    tokens = split_normalized_date_tokens(raw_date)
    if not tokens:
        return None, "date_format_invalid"

    if len(tokens) not in (2, 3):
        return None, "date_parts_invalid"

    day = int(tokens[0])
    month = int(tokens[1])

    if len(tokens) == 2:
        # Use leap year for recurring-date validation so 29/02 is accepted.
        try:
            datetime(2000, month, day)
        except ValueError:
            return None, "invalid_calendar_date"
        return {
            "date_ddmm": f"{day:02d}/{month:02d}",
            "birth_year": None,
        }, None

    year_token = tokens[2]
    if len(year_token) != 4:
        return None, "year_must_be_4_digits"

    year = int(year_token)
    if year < YEAR_MIN or year > YEAR_MAX:
        return None, "year_out_of_range"

    try:
        datetime(year, month, day)
    except ValueError:
        return None, "invalid_calendar_date"

    return {
        "date_ddmm": f"{day:02d}/{month:02d}",
        "birth_year": year,
    }, None


def parse_bulk_birthday_line(line_text, line_no, *, max_name_len=DEFAULT_MAX_NAME_LEN):
    """
    Parse one bulk birthday line after empty-line filtering.

    Returns:
        (parsed_entry, invalid_entry)
        exactly one item is None.
    """
    sections, reason = split_bulk_line_sections(line_text)
    if sections is None:
        return None, {
            "line_no": int(line_no),
            "reason_code": reason or "line_format_invalid",
        }

    raw_name, raw_date, raw_tag = sections
    name = collapse_internal_spaces(raw_name)
    if not name:
        return None, {
            "line_no": int(line_no),
            "reason_code": "name_empty",
        }

    if len(name) > int(max_name_len):
        return None, {
            "line_no": int(line_no),
            "reason_code": "name_too_long",
            "name_len": len(name),
            "max_name_len": int(max_name_len),
        }

    parsed_date, date_reason = parse_birthday_date_token(raw_date)
    if parsed_date is None:
        return None, {
            "line_no": int(line_no),
            "reason_code": date_reason or "date_invalid",
        }

    provided_tags_raw = []
    for raw_token in str(raw_tag).split(","):
        normalized = collapse_internal_spaces(raw_token)
        if normalized:
            provided_tags_raw.append(normalized)
    # Compatibility bridge for pre-multitag pipeline stages:
    # until analyzer/session schema is fully migrated, keep a single-tag field.
    provided_tag = provided_tags_raw[0] if provided_tags_raw else ""
    return {
        "line_no": int(line_no),
        "name": name,
        "date_ddmm": parsed_date["date_ddmm"],
        "birth_year": parsed_date["birth_year"],
        "provided_tag": provided_tag,
        "provided_tags_raw": provided_tags_raw,
    }, None


def count_invalid_reasons(invalid_entries):
    """Count invalid-entry reason codes from bulk birthday parse results."""
    counts = {}
    for item in invalid_entries or []:
        reason = (item or {}).get("reason_code") or "unknown"
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _normalized_birth_year(value):
    try:
        year = int(value)
    except Exception:
        return None
    if YEAR_MIN <= year <= YEAR_MAX:
        return year
    return None


def _normalize_stored_birthday_date(raw_date, birth_year):
    parsed_date, _reason = parse_birthday_date_token(raw_date)
    if parsed_date is None:
        return None, None

    resolved_year = _normalized_birth_year(birth_year)
    if resolved_year is None:
        resolved_year = _normalized_birth_year(parsed_date.get("birth_year"))
    return parsed_date.get("date_ddmm"), resolved_year


def _format_export_date(date_ddmm, birth_year):
    if not date_ddmm:
        return ""
    year = _normalized_birth_year(birth_year)
    if year is None:
        return str(date_ddmm)
    return f"{date_ddmm}/{year:04d}"


def _extract_plain_tag_names(tags, *, sort_output=True):
    seen = set()
    plain_tags = []
    for raw_tag in tags or []:
        tag_text = collapse_internal_spaces(raw_tag)
        if not tag_text:
            continue

        first_token = tag_text.split(" ", 1)[0]
        if contains_emoji(first_token):
            _emoji, plain = parse_tag(tag_text)
            plain_text = collapse_internal_spaces(plain)
        else:
            plain_text = tag_text

        if not plain_text:
            continue
        key = plain_text.lower()
        if key in seen:
            continue
        seen.add(key)
        plain_tags.append(plain_text)
    if sort_output:
        plain_tags.sort(key=lambda item: item.lower())
    return plain_tags


def _build_export_rows(birthdays):
    rows = []
    for alert in birthdays or []:
        if not isinstance(alert, dict):
            continue
        schedule = alert.get("schedule") or {}
        date_ddmm, birth_year = _normalize_stored_birthday_date(
            schedule.get("date"),
            alert.get("birth_year"),
        )
        if not date_ddmm:
            continue

        name = collapse_internal_spaces(alert.get("title")) or "Untitled"
        plain_tags = _extract_plain_tag_names(alert.get("tags"))
        if not plain_tags:
            plain_tags = ["Untagged"]

        rows.append({
            "name": name,
            "name_sort_key": name.lower(),
            "date_ddmm": date_ddmm,
            "birth_year": birth_year,
            "date_label": _format_export_date(date_ddmm, birth_year),
            "tags_label": ", ".join(plain_tags),
            # By-tag mode fans out one row into each available tag.
            "plain_tags": plain_tags,
        })

    rows.sort(key=lambda row: (row["name_sort_key"], row["date_ddmm"], row["birth_year"] or 0))
    return rows


def build_bulk_export_lines(birthdays, *, mode="everything"):
    """
    Build text blocks for bulk birthday export.

    Returns a dict:
      - mode
      - birthdays_count
      - rows_count
      - tags_nonempty_count
      - blocks (semantic blocks, not chunked)
      - empty (bool)
    """
    selected_mode = collapse_internal_spaces(mode).lower()
    if selected_mode not in {"everything", "by_tag"}:
        selected_mode = "everything"

    rows = _build_export_rows(birthdays)
    if not rows:
        return {
            "mode": selected_mode,
            "birthdays_count": 0,
            "rows_count": 0,
            "tags_nonempty_count": 0,
            "blocks": [
                "Birthday bulk export\n\nNo birthdays found for export.",
            ],
            "empty": True,
        }

    if selected_mode == "everything":
        export_lines = [
            f"{row['name']} :: {row['date_label']} :: {row['tags_label']}"
            for row in rows
        ]
        block = (
            "Birthday bulk export - Everything\n\n"
            "Format: Name :: Date :: Tag[, Tag2, ...]\n"
            f"Birthdays: {len(rows)}\n\n"
            + "\n".join(export_lines)
        )
        nonempty_tags = {
            plain_tag.lower()
            for row in rows
            for plain_tag in (row.get("plain_tags") or [])
            if plain_tag.strip().lower() != "untagged"
        }
        return {
            "mode": selected_mode,
            "birthdays_count": len(rows),
            "rows_count": len(export_lines),
            "tags_nonempty_count": len(nonempty_tags),
            "blocks": [block],
            "empty": False,
        }

    grouped = {}
    for row in rows:
        for tag_name in row.get("plain_tags") or ["Untagged"]:
            grouped.setdefault(tag_name, []).append(row)

    blocks = []
    rows_count = 0
    for tag_name in sorted(grouped.keys(), key=lambda item: item.lower()):
        tag_rows = sorted(
            grouped[tag_name],
            key=lambda row: (row["name_sort_key"], row["date_ddmm"], row["birth_year"] or 0),
        )
        lines = [
            f"{row['name']} :: {row['date_label']} :: {row['tags_label']}"
            for row in tag_rows
        ]
        rows_count += len(lines)
        blocks.append(
            "Birthday bulk export - By tag\n\n"
            f"Tag: {tag_name}\n"
            f"Birthdays: {len(lines)}\n\n"
            + "\n".join(lines)
        )

    nonempty_tags = {
        tag_name.lower()
        for tag_name in grouped.keys()
        if tag_name.strip().lower() != "untagged"
    }
    return {
        "mode": selected_mode,
        "birthdays_count": len(rows),
        "rows_count": rows_count,
        "tags_nonempty_count": len(nonempty_tags),
        "blocks": blocks,
        "empty": False,
    }


def _split_oversized_text_block(block_text, safe_limit):
    text = str(block_text).strip()
    if not text:
        return []
    if len(text) <= safe_limit:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > safe_limit:
        split_at = remaining.rfind("\n", 0, safe_limit + 1)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, safe_limit + 1)
        if split_at <= 0:
            split_at = safe_limit
        piece = remaining[:split_at].strip()
        if not piece:
            piece = remaining[:safe_limit]
            split_at = len(piece)
        chunks.append(piece)
        remaining = remaining[split_at:].lstrip("\n ")
    if remaining:
        chunks.append(remaining)
    return chunks


def chunk_text_blocks(blocks, *, safe_limit=DEFAULT_TEXT_CHUNK_SAFE_LIMIT):
    """
    Chunk semantic text blocks into Telegram-safe message chunks.

    - Preserves semantic blocks whenever possible.
    - Splits oversized single blocks by newline/space boundaries.
    """
    try:
        limit = int(safe_limit)
    except Exception:
        limit = DEFAULT_TEXT_CHUNK_SAFE_LIMIT
    limit = max(80, limit)

    normalized_blocks = []
    for item in blocks or []:
        text = "" if item is None else str(item).strip()
        if text:
            normalized_blocks.append(text)

    if not normalized_blocks:
        return []

    chunks = []
    current = ""
    for block in normalized_blocks:
        if len(block) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_oversized_text_block(block, limit))
            continue

        if not current:
            current = block
            continue

        candidate = f"{current}\n\n{block}"
        if len(candidate) <= limit:
            current = candidate
        else:
            chunks.append(current)
            current = block

    if current:
        chunks.append(current)
    return chunks


def _display_date_label(entry):
    date_ddmm = collapse_internal_spaces((entry or {}).get("date_ddmm"))
    if not date_ddmm:
        return "N/A"
    birth_year = _normalized_birth_year((entry or {}).get("birth_year"))
    if birth_year is None:
        return date_ddmm
    return f"{date_ddmm}/{birth_year:04d}"


def build_import_preview_blocks(
    parsed_result,
    tag_analysis=None,
    *,
    safe_limit=DEFAULT_TEXT_CHUNK_SAFE_LIMIT,
    max_invalid_preview=DEFAULT_INVALID_PREVIEW_LIMIT,
):
    """
    Build HTML preview blocks for the parsed bulk-import payload.

    The output is metadata-forward and never includes raw source lines.
    """
    parsed = parsed_result or {}
    analysis = tag_analysis or {}
    parsed_summary = parsed.get("summary") or {}
    analysis_summary = analysis.get("summary") or {}

    valid_entries = analysis.get("entries")
    if valid_entries is None:
        valid_entries = parsed.get("valid_entries") or []

    invalid_entries = parsed.get("invalid_entries") or []
    invalid_sorted = sorted(
        invalid_entries,
        key=lambda item: (
            (item or {}).get("line_no") is None,
            (item or {}).get("line_no") or 0,
        ),
    )

    header_lines = [
        "<b>Birthday Bulk Import Preview</b>",
        "",
        f"Non-empty lines: <b>{int(parsed.get('nonempty_lines') or 0)}</b> / max <b>{int(parsed.get('max_lines') or 0)}</b>",
        f"Valid lines: <b>{int(parsed_summary.get('valid_lines') or 0)}</b>",
        f"Invalid lines: <b>{int(parsed_summary.get('invalid_lines') or 0)}</b>",
        f"Unresolved tags: <b>{int(analysis_summary.get('unresolved_tags') or 0)}</b>",
        f"Suggestions over threshold: <b>{int(analysis_summary.get('suggestions_over_threshold') or 0)}</b>",
    ]
    if parsed.get("lines_limit_exceeded"):
        header_lines.extend([
            "",
            "<b>Import blocked:</b> line limit exceeded. Split the payload and retry.",
        ])

    reason_counts = parsed_summary.get("reason_counts") or {}
    if reason_counts:
        reason_parts = [f"{html.escape(str(key))}:{int(value)}" for key, value in sorted(reason_counts.items())]
        header_lines.extend([
            "",
            "Invalid reason counts: <code>" + ", ".join(reason_parts) + "</code>",
        ])

    blocks = ["\n".join(header_lines)]

    if valid_entries:
        lines = []
        sorted_valid = sorted(
            valid_entries,
            key=lambda item: (
                (item or {}).get("line_no") or 0,
                collapse_internal_spaces((item or {}).get("name")).lower(),
            ),
        )
        for entry in sorted_valid:
            line_no = (entry or {}).get("line_no")
            name = html.escape(collapse_internal_spaces((entry or {}).get("name")) or "Untitled")
            date_label = html.escape(_display_date_label(entry))
            lines.append(
                f"line {int(line_no) if line_no is not None else '?'}: "
                f"<code>{name} | {date_label}</code>"
            )

            matches = (entry or {}).get("tag_matches")
            if not isinstance(matches, list) or not matches:
                # Legacy compatibility for older session schema (single-tag shape).
                matches = [{
                    "provided_tag": (entry or {}).get("provided_tag"),
                    "suggested_tag_plain": (entry or {}).get("suggested_tag_plain"),
                    "suggested_tag_score": (entry or {}).get("suggested_tag_score"),
                    "resolved_tag": (entry or {}).get("resolved_tag"),
                }]

            for match in matches:
                provided_tag = html.escape(collapse_internal_spaces((match or {}).get("provided_tag")) or "-")
                suggested_plain = collapse_internal_spaces((match or {}).get("suggested_tag_plain"))
                suggested_score = int((match or {}).get("suggested_tag_score") or 0)
                if suggested_plain and suggested_score > 0:
                    suggested = html.escape(f"{suggested_plain} ({suggested_score})")
                else:
                    suggested = "-"

                import_tag = collapse_internal_spaces((match or {}).get("resolved_tag")) or "Untagged"
                import_tag = html.escape(import_tag)
                lines.append(
                    f"━ {provided_tag} | {suggested} | "
                    f"{import_tag}"
                )
        blocks.append("<b>Valid entries preview</b>\n\n(Tag: <code>provided</code> | <code>suggested</code> | <code>will be implemented</code>)\n\n" + "\n".join(lines))

    if invalid_sorted:
        limit = max(1, int(max_invalid_preview))
        shown = invalid_sorted[:limit]
        invalid_lines = []
        for item in shown:
            line_no = (item or {}).get("line_no")
            reason = html.escape(str((item or {}).get("reason_code") or "unknown"))
            invalid_lines.append(f"line {line_no if line_no is not None else '?'}: <code>{reason}</code>")
        if len(invalid_sorted) > len(shown):
            invalid_lines.append(f"... and {len(invalid_sorted) - len(shown)} more invalid lines")
        blocks.append("<b>Invalid lines</b>\n\n" + "\n".join(invalid_lines))

    if not valid_entries:
        blocks.append("No valid entries available yet. Edit the message and retry.")

    return chunk_text_blocks(blocks, safe_limit=safe_limit)


def build_import_final_confirmation_blocks(entries, *, safe_limit=DEFAULT_TEXT_CHUNK_SAFE_LIMIT):
    """
    Build HTML final-confirmation blocks for entries about to be imported.
    """
    normalized_entries = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        name = collapse_internal_spaces(entry.get("name")) or "Untitled"
        resolved_tags = []
        raw_resolved_tags = entry.get("resolved_tags")
        if isinstance(raw_resolved_tags, (list, tuple)):
            resolved_tags = list(raw_resolved_tags)
        if not resolved_tags:
            legacy_tag = entry.get("resolved_tag")
            if legacy_tag is not None:
                resolved_tags = [legacy_tag]

        plain_tags = _extract_plain_tag_names(resolved_tags, sort_output=False)
        if plain_tags:
            tags_label = ", ".join(plain_tags)
            untagged = False
        else:
            tags_label = "Untagged"
            untagged = True

        normalized_entries.append({
            "name": name,
            "name_sort_key": name.lower(),
            "date_label": _display_date_label(entry),
            "tags_label": tags_label,
            "untagged": untagged,
        })

    normalized_entries.sort(key=lambda item: (item["name_sort_key"], item["date_label"], item["tags_label"].lower()))

    header = [
        "<b>Birthday Bulk Import - Final Confirmation</b>",
        "",
        f"Entries to import: <b>{len(normalized_entries)}</b>",
        f"Untagged entries: <b>{sum(1 for item in normalized_entries if item['untagged'])}</b>",
    ]

    lines = [
        f"{html.escape(item['name'])} :: "
        f"{html.escape(item['date_label'])} :: "
        f"{html.escape(item['tags_label'])}"
        for item in normalized_entries
    ]

    blocks = ["\n".join(header)]
    if lines:
        blocks.append("<b>Import list</b>\n\n" + "\n".join(lines))
    else:
        blocks.append("No entries selected for import.")

    return chunk_text_blocks(blocks, safe_limit=safe_limit)


def _extract_plain_tag_name(tag_value):
    """Normalize tag name for matching, accepting both plain and icon-prefixed forms."""
    text = collapse_internal_spaces(tag_value)
    if not text:
        return ""
    first_token = text.split(" ", 1)[0]
    if contains_emoji(first_token):
        _, plain = parse_tag(text)
        return collapse_internal_spaces(plain).lower()
    return text.lower()


def _normalize_provided_tag_tokens(entry):
    """Return normalized provided-tag tokens for one parsed entry."""
    row = entry or {}
    tokens = []
    raw_tokens = row.get("provided_tags_raw")
    if isinstance(raw_tokens, (list, tuple)):
        for raw in raw_tokens:
            normalized = collapse_internal_spaces(raw)
            if normalized:
                tokens.append(normalized)

    if not tokens:
        fallback = collapse_internal_spaces(row.get("provided_tag"))
        if fallback:
            tokens.append(fallback)
    return tokens


def analyze_import_tags(
    valid_entries,
    user_tags,
    *,
    suggestion_threshold=DEFAULT_TAG_SUGGESTION_THRESHOLD,
):
    """
    Resolve provided import tags against user tags and compute fuzzy suggestions.

    Returns a dict with enriched entries and summary counters.
    """
    try:
        threshold = int(suggestion_threshold)
    except Exception:
        threshold = DEFAULT_TAG_SUGGESTION_THRESHOLD
    threshold = max(0, min(100, threshold))
    tags_catalog = []
    exact_map = {}

    for raw_tag in user_tags or []:
        tag_text = collapse_internal_spaces(raw_tag)
        if not tag_text:
            continue

        first_token = tag_text.split(" ", 1)[0]
        if contains_emoji(first_token):
            emoji, plain = parse_tag(tag_text)
            plain_text = collapse_internal_spaces(plain)
        else:
            emoji = "🏷️"
            plain_text = tag_text

        plain_norm = plain_text.lower()
        if not plain_norm:
            continue

        catalog_item = {
            "full_tag": tag_text,
            "tag_emoji": emoji,
            "tag_plain": plain_text,
            "tag_plain_norm": plain_norm,
        }
        tags_catalog.append(catalog_item)
        # Keep first-seen tag for deterministic exact-match resolution.
        exact_map.setdefault(plain_norm, catalog_item)

    ranked_candidates = [
        {
            "title": item["tag_plain"],
            "_catalog_item": item,
        }
        for item in tags_catalog
    ]

    analyzed_entries = []
    unresolved_entries = []
    suggested_entries = []
    resolved_item_count = 0
    unresolved_item_count = 0
    missing_item_count = 0
    provided_item_count = 0

    for entry in valid_entries or []:
        row = dict(entry or {})
        provided_tokens = _normalize_provided_tag_tokens(row)
        row["provided_tags_raw"] = list(provided_tokens)
        if provided_tokens:
            provided_item_count += len(provided_tokens)

        tag_matches = []
        resolved_tags = []
        resolved_tags_plain = []
        resolved_plain_seen = set()

        has_unresolved = False
        has_suggestion = False
        has_missing = False
        first_suggestion = None

        if not provided_tokens:
            missing_match = {
                "provided_tag": "",
                "provided_tag_plain": "",
                "resolved_tag": None,
                "resolved_tag_plain": "",
                "tag_resolution": "missing",
                "suggested_tag": None,
                "suggested_tag_plain": "",
                "suggested_tag_score": 0,
            }
            tag_matches.append(missing_match)
            has_unresolved = True
            has_missing = True
            unresolved_item_count += 1
            missing_item_count += 1
        else:
            for token in provided_tokens:
                match = {
                    "provided_tag": token,
                    "provided_tag_plain": _extract_plain_tag_name(token),
                    "resolved_tag": None,
                    "resolved_tag_plain": "",
                    "tag_resolution": "missing",
                    "suggested_tag": None,
                    "suggested_tag_plain": "",
                    "suggested_tag_score": 0,
                }

                if match["provided_tag_plain"]:
                    exact_item = exact_map.get(match["provided_tag_plain"])
                    if exact_item is not None:
                        match["resolved_tag"] = exact_item["full_tag"]
                        match["resolved_tag_plain"] = exact_item["tag_plain"]
                        match["tag_resolution"] = "exact"

                        dedupe_key = match["resolved_tag_plain"].lower()
                        if dedupe_key not in resolved_plain_seen:
                            resolved_plain_seen.add(dedupe_key)
                            resolved_tags.append(match["resolved_tag"])
                            resolved_tags_plain.append(match["resolved_tag_plain"])
                            resolved_item_count += 1
                    else:
                        match["tag_resolution"] = "unresolved"
                        has_unresolved = True
                        unresolved_item_count += 1
                        if ranked_candidates:
                            _, ranked = rank_birthdays_by_name(match["provided_tag_plain"], ranked_candidates)
                            if ranked:
                                best = ranked[0]
                                best_score = int(best.get("score") or 0)
                                if best_score > threshold:
                                    best_item = (best.get("alert") or {}).get("_catalog_item") or {}
                                    match["tag_resolution"] = "unresolved_with_suggestion"
                                    match["suggested_tag"] = best_item.get("full_tag")
                                    match["suggested_tag_plain"] = best_item.get("tag_plain", "")
                                    match["suggested_tag_score"] = best_score
                                    has_suggestion = True

                                    suggestion_row = {
                                        "line_no": row.get("line_no"),
                                        "provided_tag": match["provided_tag"],
                                        "provided_tag_plain": match["provided_tag_plain"],
                                        "suggested_tag": match["suggested_tag"],
                                        "suggested_tag_plain": match["suggested_tag_plain"],
                                        "suggested_tag_score": match["suggested_tag_score"],
                                    }
                                    suggested_entries.append(suggestion_row)
                                    if first_suggestion is None:
                                        first_suggestion = suggestion_row
                else:
                    has_unresolved = True
                    has_missing = True
                    unresolved_item_count += 1
                    missing_item_count += 1

                tag_matches.append(match)

        # Keep legacy single-tag fields for existing preview/flow wiring until full migration.
        primary_provided = tag_matches[0] if tag_matches else {}
        row["provided_tag"] = primary_provided.get("provided_tag", "")
        row["provided_tag_plain"] = primary_provided.get("provided_tag_plain", "")

        row["tag_matches"] = tag_matches
        row["resolved_tags"] = resolved_tags
        row["resolved_tags_plain"] = resolved_tags_plain
        row["resolved_tag"] = resolved_tags[0] if resolved_tags else None
        row["resolved_tag_plain"] = resolved_tags_plain[0] if resolved_tags_plain else ""
        row["suggested_tag"] = first_suggestion.get("suggested_tag") if first_suggestion else None
        row["suggested_tag_plain"] = first_suggestion.get("suggested_tag_plain", "") if first_suggestion else ""
        row["suggested_tag_score"] = int(first_suggestion.get("suggested_tag_score") or 0) if first_suggestion else 0

        if has_missing and not provided_tokens:
            row["tag_resolution"] = "missing"
        elif has_unresolved:
            row["tag_resolution"] = "unresolved_with_suggestion" if has_suggestion else "unresolved"
        elif resolved_tags:
            row["tag_resolution"] = "exact"
        else:
            row["tag_resolution"] = "missing"

        if has_unresolved:
            unresolved_entries.append(row)

        analyzed_entries.append(row)

    summary = {
        "entries_total": len(analyzed_entries),
        "provided_tag_items": provided_item_count,
        "resolved_tags": resolved_item_count,
        "unresolved_tags": unresolved_item_count,
        "unresolved_missing_tag": missing_item_count,
        "suggestions_over_threshold": len(suggested_entries),
        "entries_with_unresolved_tags": len(unresolved_entries),
        "available_user_tags": len(tags_catalog),
        "suggestion_threshold": threshold,
    }

    return {
        "entries": analyzed_entries,
        "unresolved_entries": unresolved_entries,
        "suggested_entries": suggested_entries,
        "summary": summary,
    }


def parse_bulk_birthday_message(
    raw_text,
    *,
    max_lines=DEFAULT_MAX_IMPORT_LINES,
    max_name_len=DEFAULT_MAX_NAME_LEN,
):
    """
    Parse a multi-line bulk birthday payload.

    Empty lines are ignored.
    """
    text = "" if raw_text is None else str(raw_text)
    all_lines = text.splitlines()
    indexed_nonempty = [
        (idx + 1, line)
        for idx, line in enumerate(all_lines)
        if str(line).strip()
    ]
    nonempty_lines = len(indexed_nonempty)

    if nonempty_lines > int(max_lines):
        invalid_entries = [{
            "line_no": None,
            "reason_code": "lines_limit_exceeded",
            "max_lines": int(max_lines),
            "nonempty_lines": nonempty_lines,
        }]
        reason_counts = count_invalid_reasons(invalid_entries)
        return {
            "input_line_count": len(all_lines),
            "ignored_empty_lines": len(all_lines) - nonempty_lines,
            "nonempty_lines": nonempty_lines,
            "max_lines": int(max_lines),
            "lines_limit_exceeded": True,
            "can_continue": False,
            "valid_entries": [],
            "invalid_entries": invalid_entries,
            "summary": {
                "valid_lines": 0,
                "invalid_lines": 1,
                "reason_counts": reason_counts,
                "lines_limit_exceeded": True,
            },
        }

    valid_entries = []
    invalid_entries = []
    for line_no, line in indexed_nonempty:
        parsed, invalid = parse_bulk_birthday_line(
            line,
            line_no,
            max_name_len=max_name_len,
        )
        if invalid is not None:
            invalid_entries.append(invalid)
            continue
        valid_entries.append(parsed)

    reason_counts = count_invalid_reasons(invalid_entries)
    return {
        "input_line_count": len(all_lines),
        "ignored_empty_lines": len(all_lines) - nonempty_lines,
        "nonempty_lines": nonempty_lines,
        "max_lines": int(max_lines),
        "lines_limit_exceeded": False,
        "can_continue": bool(valid_entries),
        "valid_entries": valid_entries,
        "invalid_entries": invalid_entries,
        "summary": {
            "valid_lines": len(valid_entries),
            "invalid_lines": len(invalid_entries),
            "reason_counts": reason_counts,
            "lines_limit_exceeded": False,
        },
    }


__all__ = [
    "YEAR_MIN",
    "YEAR_MAX",
    "DEFAULT_MAX_IMPORT_LINES",
    "DEFAULT_MAX_NAME_LEN",
    "DEFAULT_TAG_SUGGESTION_THRESHOLD",
    "DEFAULT_TEXT_CHUNK_SAFE_LIMIT",
    "DEFAULT_INVALID_PREVIEW_LIMIT",
    "collapse_internal_spaces",
    "contains_disallowed_control_chars",
    "validate_bulk_separator_policy",
    "split_bulk_line_sections",
    "normalize_date_separators",
    "split_normalized_date_tokens",
    "parse_birthday_date_token",
    "parse_bulk_birthday_line",
    "count_invalid_reasons",
    "analyze_import_tags",
    "parse_bulk_birthday_message",
    "build_bulk_export_lines",
    "chunk_text_blocks",
    "build_import_preview_blocks",
    "build_import_final_confirmation_blocks",
]
