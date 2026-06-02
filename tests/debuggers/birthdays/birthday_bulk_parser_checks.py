def run_whitespace_checks(module):
    samples = {
        "simple": module.collapse_internal_spaces("  Nadia   Ricci  "),
        "tabs": module.collapse_internal_spaces("Nadia\t\tRicci"),
        "already_clean": module.collapse_internal_spaces("Nadia Ricci"),
        "none": module.collapse_internal_spaces(None),
    }
    checks = {
        "simple_collapsed": samples["simple"] == "Nadia Ricci",
        "tabs_collapsed": samples["tabs"] == "Nadia Ricci",
        "clean_unchanged": samples["already_clean"] == "Nadia Ricci",
        "none_to_empty": samples["none"] == "",
    }
    return {"samples": samples, "checks": checks}


def run_control_char_checks(module):
    samples = {
        "clean": module.contains_disallowed_control_chars("Nadia Ricci"),
        "newline": module.contains_disallowed_control_chars("Nadia\nRicci"),
        "tab": module.contains_disallowed_control_chars("Nadia\tRicci"),
        "bell": module.contains_disallowed_control_chars("Nadia\x07Ricci"),
        "none": module.contains_disallowed_control_chars(None),
    }
    checks = {
        "clean_false": samples["clean"] is False,
        "newline_true": samples["newline"] is True,
        "tab_allowed": samples["tab"] is False,
        "bell_true": samples["bell"] is True,
        "none_false": samples["none"] is False,
    }
    return {"samples": samples, "checks": checks}


def run_separator_checks(module):
    valid_line = "Nadia Ricci :: 2/12/1993 :: Friends"
    valid_status = module.validate_bulk_separator_policy(valid_line)
    valid_parts, valid_parts_reason = module.split_bulk_line_sections(valid_line)

    single_colon = module.validate_bulk_separator_policy("Nadia : 2/12/1993 :: Friends")
    triple_colon = module.validate_bulk_separator_policy("Nadia ::: 2/12/1993 :: Friends")
    wrong_count = module.validate_bulk_separator_policy("Nadia :: 2/12/1993")
    control_char = module.validate_bulk_separator_policy("Nadia :: 2/12/1993 :: Frie\nnds")

    checks = {
        "valid_policy": valid_status == (True, None),
        "valid_parts_split": valid_parts == ["Nadia Ricci", "2/12/1993", "Friends"],
        "valid_parts_reason_none": valid_parts_reason is None,
        "single_colon_rejected": single_colon == (False, "single_colon_detected"),
        "triple_colon_rejected": triple_colon == (False, "invalid_colon_sequence"),
        "wrong_separator_count_rejected": wrong_count == (False, "separator_count_invalid"),
        "control_chars_rejected": control_char == (False, "control_chars"),
    }

    outputs = {
        "valid_status": valid_status,
        "valid_parts": valid_parts,
        "single_colon": single_colon,
        "triple_colon": triple_colon,
        "wrong_count": wrong_count,
        "control_char": control_char,
    }
    return {"outputs": outputs, "checks": checks}


def run_date_normalization_checks(module):
    samples = {
        "slashes": module.normalize_date_separators(" 2 / 12 / 1993 "),
        "dash": module.normalize_date_separators("04-04"),
        "underscore": module.normalize_date_separators("9_9"),
        "comma": module.normalize_date_separators("3,04"),
        "tabs": module.normalize_date_separators("2\t/\t12\t/\t1993"),
        "double_separator": module.normalize_date_separators("3..04"),
        "non_numeric": module.normalize_date_separators("3/a"),
        "single_token": module.normalize_date_separators("05042026"),
        "too_many_tokens": module.normalize_date_separators("1/2/3/4"),
        "control_chars": module.normalize_date_separators("2/12/1993\n"),
    }
    split_samples = {
        "valid": module.split_normalized_date_tokens(" 02 - 12 - 1993 "),
        "invalid": module.split_normalized_date_tokens("invalid"),
    }
    checks = {
        "slashes_ok": samples["slashes"] == "2/12/1993",
        "dash_ok": samples["dash"] == "04/04",
        "underscore_ok": samples["underscore"] == "9/9",
        "comma_ok": samples["comma"] == "3/04",
        "tabs_ok": samples["tabs"] == "2/12/1993",
        "double_separator_rejected": samples["double_separator"] is None,
        "non_numeric_rejected": samples["non_numeric"] is None,
        "single_token_rejected": samples["single_token"] is None,
        "too_many_tokens_rejected": samples["too_many_tokens"] is None,
        "control_chars_rejected": samples["control_chars"] is None,
        "split_valid_ok": split_samples["valid"] == ["02", "12", "1993"],
        "split_invalid_none": split_samples["invalid"] is None,
    }
    return {"samples": samples, "split_samples": split_samples, "checks": checks}


def run_date_parsing_checks(module):
    samples = {
        "full_year": module.parse_birthday_date_token("2/12/1993"),
        "no_year": module.parse_birthday_date_token("3/04"),
        "leap_recurring": module.parse_birthday_date_token("29/2"),
        "year_2_digits": module.parse_birthday_date_token("2/12/93"),
        "year_low": module.parse_birthday_date_token("2/12/1800"),
        "invalid_day": module.parse_birthday_date_token("31/11/1993"),
    }
    checks = {
        "full_year_ok": samples["full_year"] == ({"date_ddmm": "02/12", "birth_year": 1993}, None),
        "no_year_ok": samples["no_year"] == ({"date_ddmm": "03/04", "birth_year": None}, None),
        "leap_recurring_ok": samples["leap_recurring"] == ({"date_ddmm": "29/02", "birth_year": None}, None),
        "year_2_digits_rejected": samples["year_2_digits"] == (None, "year_must_be_4_digits"),
        "year_low_rejected": samples["year_low"] == (None, "year_out_of_range"),
        "invalid_day_rejected": samples["invalid_day"] == (None, "invalid_calendar_date"),
    }
    return {"samples": samples, "checks": checks}


def run_message_parser_checks(module):
    multiline = "\n".join([
        "Nadia Ricci :: 2/12/1993 :: Friends",
        "",
        "Paolo Paoloni :: 3/04 :: Friends",
        "Gianni Gianotti:: 04/04::Love",
        "Chiara Bianchi :: 17/05 :: Family, Work,   Friends  , ",
        "Bad colon : 04/04 :: Love",
        "Bad date :: 31/11/2020 :: Friends",
        "Name Year Short :: 1/1/99 :: Work",
        "Feb Leap Recurring :: 29/2 :: Friends",
    ])
    parsed = module.parse_bulk_birthday_message(multiline, max_lines=300, max_name_len=80)

    reason_counts = (parsed.get("summary") or {}).get("reason_counts") or {}
    valid_entries = parsed.get("valid_entries") or []
    invalid_entries = parsed.get("invalid_entries") or []
    first = valid_entries[0] if valid_entries else {}
    second = valid_entries[1] if len(valid_entries) > 1 else {}
    third = valid_entries[2] if len(valid_entries) > 2 else {}
    fourth = valid_entries[3] if len(valid_entries) > 3 else {}
    fifth = valid_entries[4] if len(valid_entries) > 4 else {}
    checks = {
        "nonempty_count": parsed.get("nonempty_lines") == 8,
        "empty_ignored_count": parsed.get("ignored_empty_lines") == 1,
        "can_continue_true": parsed.get("can_continue") is True,
        "limit_not_exceeded": parsed.get("lines_limit_exceeded") is False,
        "valid_lines_count": (parsed.get("summary") or {}).get("valid_lines") == 5,
        "invalid_lines_count": (parsed.get("summary") or {}).get("invalid_lines") == 3,
        "reason_single_colon": reason_counts.get("single_colon_detected") == 1,
        "reason_invalid_date": reason_counts.get("invalid_calendar_date") == 1,
        "reason_year_digits": reason_counts.get("year_must_be_4_digits") == 1,
        "first_date_normalized": first.get("date_ddmm") == "02/12" and first.get("birth_year") == 1993,
        "second_date_normalized": second.get("date_ddmm") == "03/04" and second.get("birth_year") is None,
        "third_date_normalized": third.get("date_ddmm") == "04/04" and third.get("birth_year") is None,
        "fourth_date_normalized": fourth.get("date_ddmm") == "17/05" and fourth.get("birth_year") is None,
        "multitag_tokens_split": fourth.get("provided_tags_raw") == ["Family", "Work", "Friends"],
        "legacy_single_tag_kept": fourth.get("provided_tag") == "Family",
        "leap_recurring_valid": fifth.get("date_ddmm") == "29/02" and fifth.get("birth_year") is None,
        "line_numbers_preserved": [item.get("line_no") for item in invalid_entries] == [6, 7, 8],
    }

    lines_301 = "\n".join(
        f"User {idx} :: 1/1/1990 :: Friends"
        for idx in range(1, 302)
    )
    limited = module.parse_bulk_birthday_message(lines_301, max_lines=300, max_name_len=80)
    limit_reason = (limited.get("summary") or {}).get("reason_counts") or {}
    limit_checks = {
        "limit_exceeded_flag": limited.get("lines_limit_exceeded") is True,
        "limit_continue_false": limited.get("can_continue") is False,
        "limit_valid_zero": (limited.get("summary") or {}).get("valid_lines") == 0,
        "limit_invalid_one": (limited.get("summary") or {}).get("invalid_lines") == 1,
        "limit_reason_present": limit_reason.get("lines_limit_exceeded") == 1,
    }

    return {
        "parsed": parsed,
        "checks": checks,
        "limited": limited,
        "limit_checks": limit_checks,
    }


def run_tag_analysis_checks(module):
    valid_entries = [
        {
            "line_no": 1,
            "name": "Nadia Ricci",
            "date_ddmm": "02/12",
            "birth_year": 1993,
            "provided_tag": "Friends",
            "provided_tags_raw": ["Friends", "Love"],
        },
        {
            "line_no": 2,
            "name": "Paolo Paoloni",
            "date_ddmm": "03/04",
            "birth_year": None,
            "provided_tag": "friendss",
            "provided_tags_raw": ["friendss", "Work Projects"],
        },
        {
            "line_no": 3,
            "name": "Gianni Gianotti",
            "date_ddmm": "04/04",
            "birth_year": None,
            "provided_tag": "",
            "provided_tags_raw": [],
        },
        {
            "line_no": 4,
            "name": "Piso Pisolo Pisano",
            "date_ddmm": "09/09",
            "birth_year": None,
            "provided_tag": "UnknownGroup",
            "provided_tags_raw": ["UnknownGroup", "pet"],
        },
        {
            "line_no": 5,
            "name": "Tag With Emoji Input",
            "date_ddmm": "10/10",
            "birth_year": None,
            "provided_tag": "👥 Friends",
            "provided_tags_raw": ["👥 Friends", "friends"],
        },
    ]
    user_tags = ["👥 Friends", "❤️ Love", "🐾 Pet", "💼 Work Projects"]
    analyzed = module.analyze_import_tags(valid_entries, user_tags, suggestion_threshold=90)

    entries = analyzed.get("entries") or []
    by_line = {item.get("line_no"): item for item in entries}
    summary = analyzed.get("summary") or {}
    unresolved = analyzed.get("unresolved_entries") or []
    suggested = analyzed.get("suggested_entries") or []

    checks = {
        "entries_count": len(entries) == 5,
        "line1_exact_resolved": by_line[1].get("tag_resolution") == "exact" and by_line[1].get("resolved_tags") == ["👥 Friends", "❤️ Love"],
        "line2_mixed_suggested": by_line[2].get("tag_resolution") == "unresolved_with_suggestion",
        "line2_suggested_tag": by_line[2].get("suggested_tag") == "👥 Friends" and by_line[2].get("suggested_tag_score", 0) > 90,
        "line3_missing": by_line[3].get("tag_resolution") == "missing" and by_line[3].get("suggested_tag") is None,
        "line4_mixed_unresolved": by_line[4].get("tag_resolution") == "unresolved" and by_line[4].get("resolved_tags") == ["🐾 Pet"],
        "line5_exact_with_dedupe": by_line[5].get("tag_resolution") == "exact" and by_line[5].get("resolved_tags") == ["👥 Friends"],
        "line5_tag_matches_count": len(by_line[5].get("tag_matches") or []) == 2,
        "summary_provided_items": summary.get("provided_tag_items") == 8,
        "summary_resolved_count": summary.get("resolved_tags") == 5,
        "summary_unresolved_count": summary.get("unresolved_tags") == 3,
        "summary_missing_count": summary.get("unresolved_missing_tag") == 1,
        "summary_suggested_count": summary.get("suggestions_over_threshold") == 1,
        "summary_unresolved_entries_count": summary.get("entries_with_unresolved_tags") == 3,
        "summary_threshold": summary.get("suggestion_threshold") == 90,
        "unresolved_size": len(unresolved) == 3,
        "suggested_size": len(suggested) == 1,
    }

    return {
        "analyzed": analyzed,
        "checks": checks,
    }


def _export_lines_from_block(block_text):
    lines = []
    for raw in str(block_text).splitlines():
        text = raw.strip()
        if " :: " in text and not text.startswith("Format:"):
            lines.append(text)
    return lines


def run_export_render_checks(module):
    birthdays = [
        {
            "title": "Zed",
            "schedule": {"date": "2/2"},
            "birth_year": None,
            "tags": [],
        },
        {
            "title": "alice",
            "schedule": {"date": "03/01"},
            "birth_year": 1990,
            "tags": ["👥 Friends", "❤️ Love"],
        },
        {
            "title": "Bruno",
            "schedule": {"date": "10/5"},
            "birth_year": None,
            "tags": ["❤️ Love"],
        },
        {
            "title": "Carla",
            "schedule": {"date": "1/12/2001"},
            "birth_year": None,
            "tags": ["💼 Work"],
        },
        {
            "title": "Skipped Invalid Date",
            "schedule": {"date": "32/12"},
            "birth_year": None,
            "tags": ["💼 Work"],
        },
    ]

    everything = module.build_bulk_export_lines(birthdays, mode="everything")
    by_tag = module.build_bulk_export_lines(birthdays, mode="by_tag")

    everything_blocks = everything.get("blocks") or []
    by_tag_blocks = by_tag.get("blocks") or []
    everything_lines = _export_lines_from_block(everything_blocks[0] if everything_blocks else "")
    by_tag_lines = []
    for block in by_tag_blocks:
        by_tag_lines.extend(_export_lines_from_block(block))

    checks = {
        "everything_mode_selected": everything.get("mode") == "everything",
        "everything_birthdays_count": everything.get("birthdays_count") == 4,
        "everything_rows_count": everything.get("rows_count") == 4,
        "everything_sorted_by_name": everything_lines[:4] == [
            "alice :: 03/01/1990 :: Friends, Love",
            "Bruno :: 10/05 :: Love",
            "Carla :: 01/12/2001 :: Work",
            "Zed :: 02/02 :: Untagged",
        ],
        "by_tag_mode_selected": by_tag.get("mode") == "by_tag",
        "by_tag_blocks_count": len(by_tag_blocks) == 4,
        "by_tag_rows_count": by_tag.get("rows_count") == 5,
        "by_tag_nonempty_tags_count": by_tag.get("tags_nonempty_count") == 3,
        "by_tag_multitag_fanout": sum(1 for row in by_tag_lines if row.startswith("alice ::")) == 2,
        "by_tag_uses_multitag_column": "alice :: 03/01/1990 :: Friends, Love" in by_tag_lines,
        "by_tag_no_empty_blocks": all(bool(str(block).strip()) for block in by_tag_blocks),
    }

    return {
        "everything": everything,
        "by_tag": by_tag,
        "everything_lines": everything_lines,
        "by_tag_lines": by_tag_lines,
        "checks": checks,
    }


def run_chunking_checks(module):
    blocks = [
        "block-one " + ("A" * 130),
        "block-two short",
        "block-three\n" + ("C" * 145),
    ]
    chunks = module.chunk_text_blocks(blocks, safe_limit=100)
    joined = "\n\n".join(chunks)
    checks = {
        "chunks_nonempty": len(chunks) > 0,
        "chunks_within_limit": all(len(chunk) <= 100 for chunk in chunks),
        "chunks_split_happened": len(chunks) >= 3,
        "contains_block_two": "block-two short" in joined,
        "contains_block_three_prefix": "block-three" in joined,
    }
    return {
        "chunks": chunks,
        "joined": joined,
        "checks": checks,
    }


def run_preview_render_checks(module):
    raw_text = "\n".join([
        "Nadia Ricci :: 2/12/1993 :: Friends",
        "Paolo Paoloni :: 3/04 :: friendss",
        "Bad colon : 04/04 :: Love",
        "Bad date :: 31/11/2020 :: Friends",
    ])
    parsed = module.parse_bulk_birthday_message(raw_text, max_lines=300, max_name_len=80)
    user_tags = ["👥 Friends", "❤️ Love"]
    analysis = module.analyze_import_tags(parsed.get("valid_entries") or [], user_tags, suggestion_threshold=90)
    blocks = module.build_import_preview_blocks(parsed, analysis, safe_limit=260, max_invalid_preview=10)
    joined = "\n\n".join(blocks)
    checks = {
        "preview_blocks_nonempty": len(blocks) > 0,
        "preview_chunks_within_limit": all(len(block) <= 260 for block in blocks),
        "preview_header_present": "Birthday Bulk Import Preview" in joined,
        "preview_valid_section_present": "Valid entries preview" in joined,
        "preview_invalid_section_present": "Invalid lines" in joined,
        "preview_reason_count_present": "single_colon_detected" in joined,
        "preview_name_date_line_present": "line 1: <code>Nadia Ricci | 02/12/1993</code>" in joined,
        "preview_tag_row_indent_present": "" in joined,
        "preview_import_as_present": "will be implemented" in joined,
        "preview_no_inline_tag_in_name_line": "line 1: <code>Nadia Ricci | 02/12/1993</code> | provided=" not in joined,
        "preview_does_not_echo_invalid_raw_line": "Bad colon : 04/04 :: Love" not in joined,
    }
    return {
        "parsed": parsed,
        "analysis": analysis,
        "blocks": blocks,
        "joined": joined,
        "checks": checks,
    }


def run_final_confirmation_checks(module):
    entries = [
        {
            "name": "Paolo Paoloni",
            "date_ddmm": "03/04",
            "birth_year": None,
            "resolved_tags": ["👥 Friends", "💼 Work"],
        },
        {
            "name": "Nadia Ricci",
            "date_ddmm": "02/12",
            "birth_year": 1993,
            "resolved_tag": "👥 Friends",
        },
        {
            "name": "Gianni Gianotti",
            "date_ddmm": "04/04",
            "birth_year": None,
            "resolved_tag": None,
        },
    ]
    blocks = module.build_import_final_confirmation_blocks(entries, safe_limit=220)
    joined = "\n\n".join(blocks)
    gianni_pos = joined.find("Gianni Gianotti")
    nadia_pos = joined.find("Nadia Ricci")
    checks = {
        "final_blocks_nonempty": len(blocks) > 0,
        "final_chunks_within_limit": all(len(block) <= 220 for block in blocks),
        "final_header_present": "Final Confirmation" in joined,
        "final_multitag_plain_present": "Friends, Work" in joined,
        "final_untagged_present": "Untagged" in joined,
        "final_sorted_by_name": gianni_pos >= 0 and nadia_pos >= 0 and gianni_pos < nadia_pos,
    }
    return {
        "blocks": blocks,
        "joined": joined,
        "checks": checks,
    }
