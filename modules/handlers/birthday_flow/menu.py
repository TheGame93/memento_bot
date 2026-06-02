from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from modules import constants as C
from modules.tags_logic import parse_tag
from modules.shared.markdown_utils import md_escape as _md_escape


def get_birthday_tag_stats(user_data):
    """Return birthday tag usage stats and untagged count from user data."""
    tags = user_data.get("tags", []) or list(C.TAGS)
    stats = {tag: 0 for tag in tags}
    untagged = 0
    for alert in user_data.get("alerts", []):
        if alert.get("type") != 6:
            continue
        alert_tags = alert.get("tags", [])
        if not alert_tags:
            untagged += 1
        else:
            for tag in alert_tags:
                if tag in stats:
                    stats[tag] += 1
                else:
                    stats[tag] = 1
    return tags, stats, untagged


def build_birthday_home_text(tags, stats, untagged):
    """Build birthday home text with per-tag birthday counts."""
    lines = [
        "🎂 **Birthdays**",
        "",
        "Your Tags:",
    ]
    tag_lines_budget = 3600 - sum(len(l) for l in lines)
    tag_lines_len = 0
    shown = 0
    for tag in tags:
        emoji, name = parse_tag(tag)
        safe_name = _md_escape(name)
        count = stats.get(tag, 0)
        line = f"• {emoji} {safe_name}: {count} bdays"
        if tag_lines_len + len(line) > tag_lines_budget:
            lines.append(f"_… and {len(tags) - shown} more tags_")
            break
        lines.append(line)
        tag_lines_len += len(line)
        shown += 1
    lines.append(f"• ⚪️ Untagged birthdays: {untagged}")
    lines.append("")
    lines.append("Choose an action:")
    return "\n".join(lines)


def build_birthday_home_keyboard(action_prefix="bday_"):
    """Build the birthday home action keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Birthday", callback_data=f"{action_prefix}add"),
            InlineKeyboardButton("📅 Next Birthdays", callback_data=f"{action_prefix}next"),
        ],
        [
            InlineKeyboardButton("🔎 Search", callback_data=f"{action_prefix}search"),
            InlineKeyboardButton("📋 Show ALL Birthdays", callback_data=f"{action_prefix}list"),
        ],
    ])


def build_toggle_keyboard(items, selected_items, callback_prefix, cols=2):
    """Build a birthday toggle keyboard with a DONE action."""
    keyboard = []
    row = []
    for item in items:
        label = f"{item} ✅" if item in selected_items else item
        callback_data = f"{callback_prefix}{item}"
        row.append(InlineKeyboardButton(label, callback_data=callback_data))
        if len(row) == cols:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("DONE", callback_data=f"{callback_prefix}DONE")])
    return InlineKeyboardMarkup(keyboard)
