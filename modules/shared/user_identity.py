from modules.shared.markdown_utils import md_escape as _md_escape


def _normalize_username(username):
    if username is None:
        return None
    text = str(username).strip()
    if not text:
        return None
    if text.startswith("@"):
        text = text[1:]
    return text or None


def _normalize_display_name(display_name):
    if display_name is None:
        return None
    text = str(display_name).strip()
    return text or None


def _maybe_escape(text, escape_markdown):
    raw = "" if text is None else " ".join(str(text).splitlines())
    return _md_escape(raw) if escape_markdown else raw


LABEL_ORDER_DEFAULT = ["custom_name", "username", "display_name", "user_id"]
LABEL_ORDER_TOKENS = {"custom_name", "username", "display_name", "user_id"}
LABEL_ORDER_ALIASES = {
    "full_name": "display_name",
    "name": "display_name",
    "id": "user_id",
}


def normalize_label_order(order):
    """Normalize configured label-order tokens and guarantee `user_id` fallback."""
    if order is None:
        return list(LABEL_ORDER_DEFAULT)
    tokens = []
    if isinstance(order, (list, tuple)):
        tokens = list(order)
    elif isinstance(order, str):
        raw = order.replace(">", ",").replace("|", ",")
        tokens = [item.strip() for item in raw.split(",")]
    else:
        return list(LABEL_ORDER_DEFAULT)

    normalized = []
    for token in tokens:
        if not token:
            continue
        key = str(token).strip().lower()
        key = LABEL_ORDER_ALIASES.get(key, key)
        if key in LABEL_ORDER_TOKENS and key not in normalized:
            normalized.append(key)
    if "user_id" not in normalized:
        normalized.append("user_id")
    if not normalized:
        return list(LABEL_ORDER_DEFAULT)
    return normalized


def format_label_order(order):
    """Render normalized label-order tokens in readable precedence format."""
    normalized = normalize_label_order(order)
    return " > ".join(normalized)


def _normalize_custom_name(custom_name):
    if custom_name is None:
        return None
    text = str(custom_name).strip()
    return text or None


def _pick_label_value(token, *, user_id, username, display_name, custom_name):
    if token == "custom_name":
        return _normalize_custom_name(custom_name)
    if token == "username":
        return _normalize_username(username)
    if token == "display_name":
        return _normalize_display_name(display_name)
    if token == "user_id":
        return str(user_id) if user_id is not None else None
    return None


def build_label_sort_key(user_id, username=None, display_name=None, custom_name=None, label_order=None):
    """Build a stable lowercase sort key using configured identity precedence."""
    order = normalize_label_order(label_order)
    for token in order:
        value = _pick_label_value(
            token,
            user_id=user_id,
            username=username,
            display_name=display_name,
            custom_name=custom_name,
        )
        if value:
            if token == "username" and isinstance(value, str) and value.startswith("@"):
                value = value[1:]
            return str(value).strip().lower()
    return str(user_id) if user_id is not None else "n/a"


def format_user_label(
    user_id,
    username=None,
    display_name=None,
    *,
    custom_name=None,
    label_order=None,
    escape_markdown=True,
):
    """Format a display label using configured identity precedence and escaping."""
    order = normalize_label_order(label_order)
    for token in order:
        value = _pick_label_value(
            token,
            user_id=user_id,
            username=username,
            display_name=display_name,
            custom_name=custom_name,
        )
        if not value:
            continue
        if token == "username":
            safe = _maybe_escape(value, escape_markdown)
            return f"@{safe}"
        safe = _maybe_escape(value, escape_markdown)
        return safe
    fallback = _maybe_escape(user_id, escape_markdown)
    return fallback or "n/a"


def format_user_label_from_meta(user_id, meta, *, escape_markdown=True):
    """Format a user label from metadata dict fields and label-order preferences."""
    meta = meta or {}
    return format_user_label(
        user_id,
        meta.get("username"),
        meta.get("display_name"),
        custom_name=meta.get("custom_name"),
        label_order=meta.get("label_order"),
        escape_markdown=escape_markdown,
    )
