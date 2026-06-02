import calendar
import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from modules import constants as C
from modules.birthday_utils import calculate_turning_age
from modules.handlers.list_alerts import (
    LIST_CONTEXT_KEY,
    ORPHAN_FILTER_BUTTON_LABEL,
    ORPHAN_FILTER_VALUE,
)
from modules.handlers.birthday_flow.render import build_compact_birthday_lines
from modules.handlers.base import _birthday_default_time_from_prefs, normalize_time_input
from modules.scheduler_mathlogic import get_next_occurrence, resolve_pre_alert_fire_time
from modules.shared.callback_codec import (
    build_value_token_map,
    ensure_callback_fits,
    extract_callback_token,
    is_token_candidate,
)
from modules.tags_logic import (
    alert_has_any_orphan_tag,
    parse_tag,
    partition_used_tags_by_master_order,
)
from modules.shared.acting_as import (
    build_acting_as_banner,
    build_acting_as_payload,
    get_actor_user_id,
    get_target_user_id,
)
from modules.shared.runtime_context import get_runtime_storage

logger = logging.getLogger(__name__)

CB_BDAY_ACTION = "bday_"
BDAY_FILTER_TOKEN_PREFIX = "bday_filter_t"
BDAY_ORPHAN_FILTER_CALLBACK_VALUE = "ORPHAN"
BDAY_ORPHAN_FILTER_CALLBACK_DATA = f"bday_filter_{BDAY_ORPHAN_FILTER_CALLBACK_VALUE}"
BDAY_UNTAGGED_FILTER_CALLBACK_VALUE = "UNTAGGED"
BDAY_UNTAGGED_FILTER_VALUE = ("__bday_untagged_filter_state__",)
BDAY_UNTAGGED_FILTER_BUTTON_LABEL = "🏷️ Untagged"
BDAY_UNTAGGED_FILTER_CALLBACK_DATA = f"bday_filter_{BDAY_UNTAGGED_FILTER_CALLBACK_VALUE}"


def _resolve_ids(update, context):
    actor_id = get_actor_user_id(update)
    target_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)
    return actor_id, target_id, acting_payload


def _get_birthdays(storage, user_id, include_inactive=False):
    data = storage.get_all_alerts(user_id) or {}
    alerts = data.get("alerts", [])
    birthdays = [a for a in alerts if a.get("type") == 6]
    if not include_inactive:
        birthdays = [a for a in birthdays if a.get("active", True)]
    return birthdays


def _format_tags_icons(tags_list):
    icons = []
    for tag in tags_list or []:
        emoji, _ = parse_tag(tag)
        if emoji and emoji not in icons:
            icons.append(emoji)
    return "".join(icons)


def _birthday_occurrence_for_year(alert, year, default_time):
    sch = alert.get("schedule", {})
    date_str = sch.get("date", "")
    try:
        day, month = map(int, date_str.split("/"))
    except (ValueError, AttributeError):
        return None

    policy = (C.BIRTHDAY_FEB29_POLICY or "mar1").lower()
    if day == 29 and month == 2 and not calendar.isleap(year):
        if policy == "mar1":
            day, month = 1, 3
        else:
            day, month = 28, 2

    time_str = normalize_time_input(sch.get("time")) or normalize_time_input(default_time)
    if not time_str:
        time_str = normalize_time_input(C.BIRTHDAY_DEFAULT_TIME)
    t = datetime.strptime(time_str, "%H:%M").time()

    try:
        return datetime(year, month, day, t.hour, t.minute, 0, 0)
    except ValueError:
        return None


def _resolve_birthday_pre_alert_labels(alert, due_dt, user_prefs=None):
    """Return sorted unique pre-alert labels for one birthday due occurrence."""
    if due_dt is None or not isinstance(alert, dict):
        return []
    resolved = []
    for token in alert.get("pre_alerts", []) or []:
        pre_dt, _kind = resolve_pre_alert_fire_time(
            alert,
            token,
            due_dt,
            user_prefs=user_prefs,
        )
        if pre_dt is not None:
            resolved.append(pre_dt)
    return [dt.strftime("%a %d %b") for dt in sorted({dt for dt in resolved})]


def _chunk_message_by_lines(text, max_chars=4096):
    """Split long text into newline-aware chunks that fit Telegram limits."""
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    limit = max(256, int(max_chars))
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            split_at = text.rfind("\n", start, end)
            if split_at > start:
                end = split_at + 1
        chunks.append(text[start:end])
        start = end
    return chunks


def _build_next_birthday_item_line(alias, tags_icons, safe_title, is_today=False):
    """Build one lead row for next-birthday sections with section-specific prefix style."""
    prefix = f"🔥 /{alias} : " if is_today else f"/{alias} : "
    if tags_icons:
        return f"{prefix}{tags_icons} : {safe_title}"
    return f"{prefix}{safe_title}"


def _resolve_birthday_default_time(storage, user_id):
    prefs = storage.get_user_prefs(user_id)
    return _birthday_default_time_from_prefs(prefs)


def _next_birthday_occurrence(alert, default_time):
    if not isinstance(alert, dict):
        return None
    schedule = alert.get("schedule") or {}
    time_str = normalize_time_input(schedule.get("time")) or normalize_time_input(default_time)
    if not time_str:
        time_str = normalize_time_input(C.BIRTHDAY_DEFAULT_TIME)
    if schedule.get("time") == time_str:
        return get_next_occurrence(alert)
    cloned = dict(alert)
    cloned_schedule = dict(schedule)
    cloned_schedule["time"] = time_str
    cloned["schedule"] = cloned_schedule
    return get_next_occurrence(cloned)


def _collect_birthday_tags(birthdays, master_tags):
    used_known_tags, _orphan_tags = partition_used_tags_by_master_order(
        birthdays,
        master_tags,
    )
    return used_known_tags


def _collect_birthday_orphan_tags(birthdays, master_tags):
    _used_known_tags, orphan_tags = partition_used_tags_by_master_order(
        birthdays,
        master_tags,
    )
    return orphan_tags


def _build_birthday_filter_token_map(birthdays, master_tags):
    return build_value_token_map(_collect_birthday_tags(birthdays, master_tags))


def _is_birthday_orphan_filter_callback(callback_data):
    return callback_data == BDAY_ORPHAN_FILTER_CALLBACK_DATA


def _is_birthday_untagged_filter_callback(callback_data):
    return callback_data == BDAY_UNTAGGED_FILTER_CALLBACK_DATA


def _render_birthday_filter_label(tag_filter):
    if tag_filter == ORPHAN_FILTER_VALUE:
        return ORPHAN_FILTER_BUTTON_LABEL
    if tag_filter == BDAY_UNTAGGED_FILTER_VALUE:
        return BDAY_UNTAGGED_FILTER_BUTTON_LABEL
    return tag_filter


def _coerce_filter_tag_value(raw_tag):
    if raw_tag is None:
        return None
    if isinstance(raw_tag, str):
        return raw_tag
    return str(raw_tag)


def _birthday_matches_known_tag_filter(alert, tag_filter):
    expected = _coerce_filter_tag_value(tag_filter)
    if expected is None or not isinstance(alert, dict):
        return False
    raw_tags = alert.get("tags")
    if not isinstance(raw_tags, list):
        return False
    for raw_tag in raw_tags:
        if _coerce_filter_tag_value(raw_tag) == expected:
            return True
    return False


def _birthday_is_untagged(alert) -> bool:
    """Return whether a birthday entry has no usable tags for tag-filter views."""
    if not isinstance(alert, dict):
        return True
    raw_tags = alert.get("tags")
    if not isinstance(raw_tags, list):
        return True
    for raw_tag in raw_tags:
        normalized = _coerce_filter_tag_value(raw_tag)
        if isinstance(normalized, str) and normalized.strip():
            return False
    return True


def _serialize_birthday_filter_for_log(tag_filter):
    if tag_filter == ORPHAN_FILTER_VALUE:
        return "__ORPHAN__"
    if tag_filter == BDAY_UNTAGGED_FILTER_VALUE:
        return "__UNTAGGED__"
    return str(tag_filter)


def _build_birthday_orphan_warning_text(orphan_tags, max_chars=3900):
    intro = (
        "⚠️ *Orphan tags found*\n"
        "Some birthdays use tags that are missing from your master tag list (/tags).\n"
        "Use *🧩 Orphan tag* to review those birthdays.\n\n"
        "*Orphan tags in use:*\n"
    )
    safe_tags = [_md_escape(tag) for tag in orphan_tags]
    limit = max(512, int(max_chars))
    lines = []

    for idx, tag in enumerate(safe_tags):
        line = f"• {tag}"
        remaining = len(safe_tags) - idx - 1
        suffix = (
            f"\n… and {remaining} more orphan tag(s)."
            if remaining > 0
            else ""
        )
        candidate = intro + "\n".join(lines + [line]) + suffix
        if len(candidate) > limit:
            omitted = remaining + 1
            if not lines:
                return (
                    intro
                    + f"… and {omitted} orphan tag(s). Open /birthdays and filter to inspect them."
                )
            return intro + "\n".join(lines) + f"\n… and {omitted} more orphan tag(s)."
        lines.append(line)

    return intro + "\n".join(lines)


async def _send_birthday_orphan_warning_message(context, update, actor_id, orphan_tags):
    if not orphan_tags:
        return
    banner = build_acting_as_banner(update, context, parse_mode=ParseMode.MARKDOWN)
    available_chars = max(512, 4096 - len(banner) - 16)
    warning_text = _build_birthday_orphan_warning_text(
        orphan_tags,
        max_chars=available_chars,
    )
    await context.bot.send_message(
        chat_id=actor_id,
        text=f"{banner}{warning_text}",
        parse_mode=ParseMode.MARKDOWN,
    )


def _decode_birthday_filter_value(callback_data, token_map):
    if not isinstance(callback_data, str) or not callback_data.startswith("bday_filter_"):
        return None
    raw = callback_data.replace("bday_filter_", "", 1)
    if raw == "ALL":
        return "ALL"
    if raw == BDAY_ORPHAN_FILTER_CALLBACK_VALUE:
        return ORPHAN_FILTER_VALUE
    if raw == BDAY_UNTAGGED_FILTER_CALLBACK_VALUE:
        return BDAY_UNTAGGED_FILTER_VALUE

    token = extract_callback_token(callback_data, BDAY_FILTER_TOKEN_PREFIX)
    if token and is_token_candidate(token):
        resolved = token_map.get(token)
        # Tokenized callback from stale keyboards should fail closed.
        if resolved is None:
            return None
        return resolved
    # Legacy fallback: full tag name in callback.
    return raw


from modules.shared.markdown_utils import md_escape as _md_escape


async def birthday_list_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the birthday tag filter menu with orphan-aware guidance when needed."""
    storage = get_runtime_storage(context)
    actor_id, user_id, acting_payload = _resolve_ids(update, context)
    context.user_data.pop("expecting_birthday_search", None)
    context.user_data.pop("expecting_alert_search", None)
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except Exception:
            pass
        if query.data in {f"{CB_BDAY_ACTION}list", "bday_filter_back"}:
            try:
                await query.message.delete()
            except Exception:
                pass

    user_data = storage.get_all_alerts(user_id)
    if not user_data or not user_data.get("alerts"):
        await context.bot.send_message(
            chat_id=actor_id,
            text="🎂 You don't have any birthdays yet. Use /birthdays to add one.",
        )
        return

    birthdays_all = [a for a in user_data.get("alerts", []) if a.get("type") == 6]
    if not birthdays_all:
        await context.bot.send_message(
            chat_id=actor_id,
            text="🎂 You don't have any birthdays yet. Use /birthdays to add one.",
        )
        return

    master_tags = storage.get_user_tags(user_id)
    used_known_tags = _collect_birthday_tags(birthdays_all, master_tags)
    orphan_tags = _collect_birthday_orphan_tags(birthdays_all, master_tags)
    has_untagged_birthdays = any(_birthday_is_untagged(bday) for bday in birthdays_all)

    # Build tag filter keyboard.
    keyboard = [[InlineKeyboardButton("📋 ALL TAGS", callback_data="bday_filter_ALL")]]
    tag_token_map = _build_birthday_filter_token_map(birthdays_all, master_tags)
    context.user_data["birthdays_filter_token_map"] = tag_token_map
    tag_buttons = []
    tag_to_token = {tag: token for token, tag in tag_token_map.items()}
    for tag in used_known_tags:
        token = tag_to_token.get(tag)
        if not token:
            continue
        callback_data = f"{BDAY_FILTER_TOKEN_PREFIX}{token}"
        if not ensure_callback_fits(callback_data):
            logger.warning(f"Skipping oversized birthday filter callback for tag: {tag}")
            continue
        tag_buttons.append(InlineKeyboardButton(tag, callback_data=callback_data))
    for i in range(0, len(tag_buttons), 2):
        keyboard.append(tag_buttons[i:i + 2])
    if orphan_tags:
        if ensure_callback_fits(BDAY_ORPHAN_FILTER_CALLBACK_DATA):
            keyboard.append([
                InlineKeyboardButton(
                    ORPHAN_FILTER_BUTTON_LABEL,
                    callback_data=BDAY_ORPHAN_FILTER_CALLBACK_DATA,
                )
            ])
        else:
            logger.warning("Skipping birthday orphan filter button due oversized callback payload")
    if has_untagged_birthdays:
        if ensure_callback_fits(BDAY_UNTAGGED_FILTER_CALLBACK_DATA):
            keyboard.append([
                InlineKeyboardButton(
                    BDAY_UNTAGGED_FILTER_BUTTON_LABEL,
                    callback_data=BDAY_UNTAGGED_FILTER_CALLBACK_DATA,
                )
            ])
        else:
            logger.warning("Skipping birthday untagged filter button due oversized callback payload")

    text = "🔍 **Filter Birthdays by Tag:**\nSelect a category to view:"
    await context.bot.send_message(
        chat_id=actor_id,
        text=f"{build_acting_as_banner(update, context, parse_mode=ParseMode.MARKDOWN)}{text}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )
    await _send_birthday_orphan_warning_message(context, update, actor_id, orphan_tags)


async def show_birthdays_list(update: Update, context: ContextTypes.DEFAULT_TYPE, manual_tag=None, manual_page=None):
    """Show a paginated birthday list for the selected tag filter, including orphan mode."""
    query = update.callback_query
    if query and isinstance(query.data, str) and (
        query.data.startswith("bday_filter_") or query.data.startswith("bday_page_")
    ):
        await query.answer()

    current_page = int(manual_page or 1)
    if query and query.data.startswith("bday_page_"):
        if query.data == "bday_page_noop":
            return
        current_page = context.user_data.get("birthdays_current_page", 1)
        if query.data.endswith("next"):
            current_page += 1
        elif query.data.endswith("prev"):
            current_page -= 1

    actor_id, user_id, acting_payload = _resolve_ids(update, context)
    storage = get_runtime_storage(context)
    user_prefs = storage.get_user_prefs(user_id) or {}
    default_time = _birthday_default_time_from_prefs(user_prefs)
    data = storage.get_all_alerts(user_id) or {"alerts": []}
    birthdays_all = [a for a in data.get("alerts", []) if a.get("type") == 6]
    master_tags = storage.get_user_tags(user_id)
    orphan_tags = _collect_birthday_orphan_tags(birthdays_all, master_tags)
    has_untagged_birthdays = any(_birthday_is_untagged(bday) for bday in birthdays_all)
    tag_token_map = _build_birthday_filter_token_map(birthdays_all, master_tags)
    context.user_data["birthdays_filter_token_map"] = tag_token_map

    if manual_tag is not None:
        tag_filter = manual_tag
    elif query and query.data.startswith("bday_filter_"):
        decoded = _decode_birthday_filter_value(query.data, tag_token_map)
        if decoded is None:
            stale_text = "⚠️ This birthday filter is no longer available. Open /birthdays and try again."
            if _is_birthday_orphan_filter_callback(query.data):
                stale_text = "⚠️ Birthday orphan filter is no longer available. Open /birthdays and try again."
            elif _is_birthday_untagged_filter_callback(query.data):
                stale_text = "⚠️ Birthday untagged filter is no longer available. Open /birthdays and try again."
            await context.bot.send_message(
                chat_id=actor_id,
                text=stale_text,
            )
            return
        tag_filter = decoded
    else:
        tag_filter = context.user_data.get("birthday_current_filter", "ALL")

    if tag_filter == ORPHAN_FILTER_VALUE and not orphan_tags:
        await context.bot.send_message(
            chat_id=actor_id,
            text="⚠️ Birthday orphan filter is no longer available. Open /birthdays and try again.",
        )
        return
    if tag_filter == BDAY_UNTAGGED_FILTER_VALUE and not has_untagged_birthdays:
        await context.bot.send_message(
            chat_id=actor_id,
            text="⚠️ Birthday untagged filter is no longer available. Open /birthdays and try again.",
        )
        return

    context.user_data["birthday_current_filter"] = tag_filter
    context.user_data["manage_source"] = "birthdays"

    birthdays = list(birthdays_all)
    if tag_filter == ORPHAN_FILTER_VALUE:
        birthdays = [a for a in birthdays if alert_has_any_orphan_tag(a, master_tags)]
    elif tag_filter == BDAY_UNTAGGED_FILTER_VALUE:
        birthdays = [a for a in birthdays if _birthday_is_untagged(a)]
    elif tag_filter != "ALL":
        birthdays = [
            a
            for a in birthdays
            if _birthday_matches_known_tag_filter(a, tag_filter)
        ]
    filter_label = _render_birthday_filter_label(tag_filter)

    payload = {
        "count": len(birthdays),
        "tag_filter": _serialize_birthday_filter_for_log(tag_filter),
    }
    payload.update(acting_payload)
    storage.log_user_event(user_id, "birthdays_list_view", payload)

    if not birthdays:
        await context.bot.send_message(
            chat_id=actor_id,
            text=f"🎂 No birthdays found for: {filter_label}",
        )
        return

    birthdays.sort(key=lambda a: (_next_birthday_occurrence(a, default_time) or datetime.max, a.get("created_at", "")))
    per_page = int(getattr(C, "LIST_PAGE_SIZE", 20))
    total_pages = max(1, (len(birthdays) + per_page - 1) // per_page)
    current_page = max(1, min(total_pages, current_page))
    context.user_data["birthdays_current_page"] = current_page

    start = (current_page - 1) * per_page
    end = start + per_page
    page_items = birthdays[start:end]
    lines, alias_map = build_compact_birthday_lines(
        page_items,
        default_time=default_time,
        user_prefs=user_prefs,
    )

    context.user_data[LIST_CONTEXT_KEY] = {
        "source": "birthdays",
        "tag_filter": tag_filter,
        "page": current_page,
        "alias_map": alias_map,
        "saved_at": datetime.now().isoformat(),
    }

    header = f"🎂 Birthdays | Tag: {filter_label} | Page {current_page}/{total_pages}"
    text = header + "\n(press the number for INFO)\n\n" + "\n".join(lines)
    banner = build_acting_as_banner(update, context, parse_mode=ParseMode.MARKDOWN)
    if banner:
        text = f"{banner}{text}"
    nav_row = [
        InlineKeyboardButton("⬅️ Prev", callback_data="bday_page_prev"),
        InlineKeyboardButton(f"{current_page}/{total_pages}", callback_data="bday_page_noop"),
        InlineKeyboardButton("Next ➡️", callback_data="bday_page_next"),
    ]
    if current_page <= 1:
        nav_row[0] = InlineKeyboardButton("·", callback_data="bday_page_noop")
    if current_page >= total_pages:
        nav_row[2] = InlineKeyboardButton("·", callback_data="bday_page_noop")

    keyboard = InlineKeyboardMarkup([
        nav_row,
        [InlineKeyboardButton("⬅️ Back to tag search", callback_data="bday_filter_back")],
    ])

    if query:
        try:
            await query.message.delete()
        except Exception:
            pass
    await context.bot.send_message(chat_id=actor_id, text=text, reply_markup=keyboard)


async def show_next_birthdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render next birthdays in LAST/TODAY/NEXT sections with alias and pre-alert rows."""
    query = update.callback_query
    if query:
        await query.answer()

    actor_id, user_id, acting_payload = _resolve_ids(update, context)
    storage = get_runtime_storage(context)
    default_time = _resolve_birthday_default_time(storage, user_id)
    user_prefs = storage.get_user_prefs(user_id) or {}
    now = datetime.now()
    now_date = now.date()
    window_start = now_date - timedelta(days=C.BIRTHDAY_NEXT_PAST_DAYS)
    window_end = now_date + timedelta(days=C.BIRTHDAY_NEXT_FUTURE_DAYS)

    birthdays = _get_birthdays(storage, user_id, include_inactive=False)
    upcoming = []

    seen = set()
    for alert in birthdays:
        for year in (now.year - 1, now.year, now.year + 1):
            occ = _birthday_occurrence_for_year(alert, year, default_time)
            if not occ:
                continue
            occ_date = occ.date()
            if window_start <= occ_date <= window_end:
                key = (alert.get("id"), occ_date)
                if key in seen:
                    continue
                seen.add(key)
                upcoming.append(
                    {
                        "time": occ,
                        "title": alert.get("title", "Untitled"),
                        "alert_id": alert.get("id"),
                        "tags": alert.get("tags", []),
                        "birth_year": alert.get("birth_year"),
                        "alert": alert,
                    }
                )

    payload = {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "count": len(upcoming),
    }
    payload.update(acting_payload)
    storage.log_user_event(user_id, "birthdays_next_view", payload)

    if not upcoming:
        await context.bot.send_message(
            chat_id=actor_id,
            text=(
                "🎂 No birthdays scheduled in the last "
                f"{C.BIRTHDAY_NEXT_PAST_DAYS} days or next "
                f"{C.BIRTHDAY_NEXT_FUTURE_DAYS} days."
            ),
        )
        return

    upcoming.sort(key=lambda x: x["time"])
    alias_map = {}
    alias_idx = 0

    today_items = [item for item in upcoming if item["time"].date() == now_date]
    past_items = [item for item in upcoming if item["time"].date() < now_date]
    future_items = [item for item in upcoming if item["time"].date() > now_date]

    msg_lines = [
        "⏩ Next Birthdays",
        "━━━━━━━━━━━━━━",
        "(press the number for INFO)",
        "",
        f"━━━━━━    LAST {C.BIRTHDAY_NEXT_PAST_DAYS} DAYS",
    ]
    banner = build_acting_as_banner(update, context, parse_mode=ParseMode.MARKDOWN)
    if not past_items:
        msg_lines.append(f"no birthday in the previous {C.BIRTHDAY_NEXT_PAST_DAYS} days")
        msg_lines.append("")
    else:
        for item in past_items:
            alias_idx += 1
            alias = f"{alias_idx:02d}"
            if item.get("alert_id"):
                alias_map[alias] = item.get("alert_id")
            date_str = item["time"].strftime("%a %d %b")
            days_left = (item["time"].date() - now_date).days
            when_str = f"{abs(days_left)}d ago"
            tags_icons = _format_tags_icons(item.get("tags"))
            safe_title = _md_escape(item["title"])
            turning = calculate_turning_age(item.get("birth_year"), item["time"].year)
            msg_lines.append(_build_next_birthday_item_line(alias, tags_icons, safe_title))

            pre_labels = _resolve_birthday_pre_alert_labels(
                item.get("alert"),
                item.get("time"),
                user_prefs=user_prefs,
            )
            if pre_labels:
                msg_lines.append(f"├─ 🔔 {', '.join(pre_labels)}")
            if turning is not None:
                msg_lines.append(f"╰─ 🎂 turned {turning} on {date_str} ({when_str})")
            else:
                msg_lines.append(f"╰─ 🎂 {date_str} ({when_str})")
            msg_lines.append("")

    msg_lines.append("🔥🔥🔥🔥   TODAY   🔥🔥🔥🔥")
    if not today_items:
        msg_lines.append("no birthdays today")
        msg_lines.append("")
    else:
        total_today = len(today_items)
        for idx, item in enumerate(today_items):
            alias_idx += 1
            alias = f"{alias_idx:02d}"
            if item.get("alert_id"):
                alias_map[alias] = item.get("alert_id")
            tags_icons = _format_tags_icons(item.get("tags"))
            safe_title = _md_escape(item["title"])
            turning = calculate_turning_age(item.get("birth_year"), item["time"].year)
            msg_lines.append(
                _build_next_birthday_item_line(
                    alias,
                    tags_icons,
                    safe_title,
                    is_today=True,
                )
            )

            pre_labels = _resolve_birthday_pre_alert_labels(
                item.get("alert"),
                item.get("time"),
                user_prefs=user_prefs,
            )
            if pre_labels:
                msg_lines.append(f"🔥 ├─ 🔔 {', '.join(pre_labels)}")
            if turning is not None:
                msg_lines.append(f"🔥 ╰─ 🎂 turns {turning} today!")
            else:
                msg_lines.append("🔥 ╰─ 🎂 ?? (mysterious age, discover it!)")
            if idx < total_today - 1:
                msg_lines.append("🔥")
        msg_lines.append("")

    msg_lines.append(f"━━━━━━    NEXT {C.BIRTHDAY_NEXT_FUTURE_DAYS} DAYS")
    if not future_items:
        msg_lines.append(f"no birthday in the next {C.BIRTHDAY_NEXT_FUTURE_DAYS} days")
    else:
        for item in future_items:
            alias_idx += 1
            alias = f"{alias_idx:02d}"
            if item.get("alert_id"):
                alias_map[alias] = item.get("alert_id")
            date_str = item["time"].strftime("%a %d %b")
            days_left = (item["time"].date() - now_date).days
            when_str = f"in {days_left}d"
            tags_icons = _format_tags_icons(item.get("tags"))
            safe_title = _md_escape(item["title"])
            turning = calculate_turning_age(item.get("birth_year"), item["time"].year)
            msg_lines.append(_build_next_birthday_item_line(alias, tags_icons, safe_title))

            pre_labels = _resolve_birthday_pre_alert_labels(
                item.get("alert"),
                item.get("time"),
                user_prefs=user_prefs,
            )
            if pre_labels:
                msg_lines.append(f"├─ 🔔 {', '.join(pre_labels)}")
            if turning is not None:
                msg_lines.append(f"╰─ 🎂 turns {turning} on {date_str} ({when_str})")
            else:
                msg_lines.append(f"╰─ 🎂 {date_str} ({when_str})")
            msg_lines.append("")

    context.user_data[LIST_CONTEXT_KEY] = {
        "source": "next_birthdays",
        "alias_map": alias_map,
        "saved_at": datetime.now().isoformat(),
    }

    body_text = "\n".join(msg_lines).rstrip() + "\n"
    full_text = f"{banner}{body_text}" if banner else body_text
    for chunk in _chunk_message_by_lines(full_text, max_chars=4096):
        await context.bot.send_message(
            chat_id=actor_id,
            text=chunk,
            parse_mode=ParseMode.MARKDOWN,
        )
