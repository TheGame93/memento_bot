import re
import logging

logger = logging.getLogger(__name__)
MARKDOWN_UNSAFE_TAG_CHARS = ("_", "*", "`", "[", "]")

# Unicode regex pattern for emoji detection
# Covers most common emoji ranges from Telegram keyboard
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F300-\U0001F5FF"  # Misc Symbols and Pictographs
    "\U0001F680-\U0001F6FF"  # Transport and Map
    "\U0001F700-\U0001F77F"  # Alchemical Symbols
    "\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
    "\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
    "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
    "\U0001FA00-\U0001FA6F"  # Chess Symbols
    "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
    "\U00002702-\U000027B0"  # Dingbats
    "\U00002300-\U000023FF"  # Misc Technical
    "\U00002600-\U000026FF"  # Misc Symbols
    "\U00002700-\U000027BF"  # Dingbats
    "\U0000FE00-\U0000FE0F"  # Variation Selectors
    "\U0001F000-\U0001F02F"  # Mahjong Tiles
    "\U0001F0A0-\U0001F0FF"  # Playing Cards
    "]+", 
    flags=re.UNICODE
)

def contains_emoji(text):
    """Check if text contains at least one emoji."""
    return bool(EMOJI_PATTERN.search(text))

def parse_tag(tag_string):
    """
    Splits a tag string into (emoticon, name).
    Example: "🏷️ Work" -> ("🏷️", "Work")
    """
    if not tag_string:
        return "🏷️", "None"
    
    # Regex splits by first space: everything before is 'emoji', after is 'name'
    match = re.match(r'^(\S+)\s+(.*)$', tag_string.strip())
    
    if match:
        return match.group(1), match.group(2)
    else:
        # Fallback if no space/emoji found
        return "🏷️", tag_string.strip()

def extract_tag_name(tag_string):
    """
    Extracts just the name portion from a tag string.
    Example: "🏷️ Work" -> "work" (lowercase for comparison)
    """
    if not tag_string:
        return ""
    
    _, name = parse_tag(tag_string)
    return name.strip().lower()

def validate_tag_format(tag_string):
    """
    Validates that a tag follows the format: "emoji name"
    Returns: (is_valid: bool, error_message: str)
    
    Rules:
    - Must have an emoji at the start
    - Must have a space separating emoji and name
    - Must have text after the emoji (at least 1 character)
    """
    if not tag_string or not tag_string.strip():
        return False, "Tag cannot be empty."
    
    tag_string = tag_string.strip()

    # Reject control characters anywhere in the tag (newlines, null bytes, etc.)
    if any(c < ' ' and c not in (' ',) for c in tag_string):
        return False, "Tag cannot contain special control characters."

    # Check for space (separator between emoji and name)
    if ' ' not in tag_string:
        return False, "Tag must have format: emoji + space + name\nExample: 🍕 Food"
    
    # Split by first space
    parts = tag_string.split(' ', 1)
    emoji_part = parts[0]
    name_part = parts[1] if len(parts) > 1 else ""
    
    # Check emoji exists in first part
    if not contains_emoji(emoji_part):
        return False, "Tag must start with an emoji.\nExample: 🍕 Food"
    
    # Check name exists and has content
    if not name_part or not name_part.strip():
        return False, "Tag must have a name after the emoji.\nExample: 🍕 Food"

    clean_name = name_part.strip()

    # Enforce max length
    if len(clean_name) > 64:
        return False, "Tag name is too long (max 64 characters)."

    # Prevent markdown control chars that can break Telegram Markdown menus.
    found_unsafe = [ch for ch in MARKDOWN_UNSAFE_TAG_CHARS if ch in clean_name]
    if found_unsafe:
        found_list = ", ".join(found_unsafe)
        return False, (
            "Tag name cannot contain markdown control characters: "
            f"{found_list}"
        )

    # Check name has at least one letter/number
    if not any(c.isalnum() for c in clean_name):
        return False, "Tag name must contain at least one letter or number."

    return True, ""

def normalize_tag_input(tag_string):
    """Strip and collapse all internal whitespace runs to a single space.

    Applies to user-supplied tag text before validation and storage, ensuring
    inputs like "🍕  Food  Bar" or "🍕\tFood\nBar" are stored as "🍕 Food Bar".
    Returns an empty string for None or empty input.
    """
    if not tag_string:
        return ""
    return re.sub(r'\s+', ' ', tag_string).strip()


def get_tag_stats(user_data):
    """
    Counts alerts per tag and identifies untagged alerts.
    """
    if not user_data:
        return {}, 0
        
    alerts = user_data.get("alerts", [])
    available_tags = user_data.get("tags", [])
    
    # Initialize counts for all known user tags
    stats = {tag: 0 for tag in available_tags}
    untagged_count = 0
    
    for alert in alerts:
        if alert.get("type") == 6:
            continue
        alert_tags = alert.get("tags", [])
        if not alert_tags:
            untagged_count += 1
        else:
            for t in alert_tags:
                if t in stats:
                    stats[t] += 1
                else:
                    # In case an alert has a legacy tag not in the master list
                    stats[t] = 1
                    
    return stats, untagged_count


def _coerce_tag_value(raw_tag):
    if raw_tag is None:
        return None
    if isinstance(raw_tag, str):
        return raw_tag
    return str(raw_tag)


def partition_used_tags_by_master_order(alerts, master_tags):
    """Return used master tags in master-list order plus first-seen orphan tags."""
    ordered_master = []
    master_set = set()
    if isinstance(master_tags, list):
        for raw_tag in master_tags:
            tag = _coerce_tag_value(raw_tag)
            if tag is None or tag in master_set:
                continue
            ordered_master.append(tag)
            master_set.add(tag)

    used_master_set = set()
    orphan_tags = []
    orphan_set = set()
    if isinstance(alerts, list):
        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            raw_tags = alert.get("tags")
            if not isinstance(raw_tags, list):
                continue
            for raw_tag in raw_tags:
                tag = _coerce_tag_value(raw_tag)
                if tag is None:
                    continue
                if tag in master_set:
                    used_master_set.add(tag)
                elif tag not in orphan_set:
                    orphan_tags.append(tag)
                    orphan_set.add(tag)

    used_master_tags = [tag for tag in ordered_master if tag in used_master_set]
    return used_master_tags, orphan_tags


def alert_has_any_orphan_tag(alert, master_tags):
    """Return whether an alert contains at least one tag absent from the master list."""
    master_set = set()
    if isinstance(master_tags, list):
        for raw_tag in master_tags:
            tag = _coerce_tag_value(raw_tag)
            if tag is not None:
                master_set.add(tag)

    if not isinstance(alert, dict):
        return False
    raw_tags = alert.get("tags")
    if not isinstance(raw_tags, list):
        return False

    for raw_tag in raw_tags:
        tag = _coerce_tag_value(raw_tag)
        if tag is None:
            continue
        if tag not in master_set:
            return True
    return False
