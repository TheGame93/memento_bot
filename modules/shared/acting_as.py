from typing import Any, Optional


def _coerce_user_id(value: Any) -> Optional[int | str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lstrip("-").isdigit():
        try:
            return int(text)
        except ValueError:
            return text
    return text


def get_actor_user_id(update) -> Optional[int | str]:
    """Return the effective actor user id from the update payload."""
    user = getattr(update, "effective_user", None)
    if not user:
        return None
    return _coerce_user_id(getattr(user, "id", None))


def get_target_user_id(update, context) -> Optional[int | str]:
    """Resolve the active target user id, falling back to the actor id."""
    actor_id = get_actor_user_id(update)
    if context is None:
        return actor_id
    target = context.user_data.get("acting_as_user_id")
    target_id = _coerce_user_id(target)
    if target_id is None:
        return actor_id
    return target_id


def is_acting_as(update, context) -> bool:
    """Return whether the current context targets a user different from the actor."""
    actor_id = get_actor_user_id(update)
    target_id = get_target_user_id(update, context)
    return actor_id is not None and target_id is not None and str(actor_id) != str(target_id)


def build_acting_as_payload(update, context) -> dict:
    """Build acting-as telemetry payload using actor and resolved target ids."""
    actor_id = get_actor_user_id(update)
    target_id = get_target_user_id(update, context)
    return build_acting_as_payload_for(actor_id, target_id)


def build_acting_as_payload_for(actor_id, target_id) -> dict:
    """Build normalized acting-as payload for explicit actor and target ids."""
    if actor_id is None or target_id is None:
        return {}
    if str(actor_id) == str(target_id):
        return {}
    return {
        "acting_as": {
            "actor_id": str(actor_id),
            "target_id": str(target_id),
        }
    }


def build_acting_as_banner(update, context, *, parse_mode: str | None = "Markdown") -> str:
    """Build the acting-as banner for the current update context."""
    actor_id = get_actor_user_id(update)
    target_id = get_target_user_id(update, context)
    return build_acting_as_banner_for(actor_id, target_id, parse_mode=parse_mode)


def build_acting_as_banner_for(actor_id, target_id, *, parse_mode: str | None = "Markdown") -> str:
    """Render the acting-as banner with formatting for the selected parse mode."""
    if actor_id is None or target_id is None:
        return ""
    if str(actor_id) == str(target_id):
        return ""
    mode = str(parse_mode or "").lower()
    if "html" in mode:
        return f"🧑‍💻 Acting as: <code>{target_id}</code>\n\n"
    return f"🧑‍💻 Acting as: `{target_id}`\n\n"


def set_acting_as(context, target_id: Any) -> Optional[int | str]:
    """Persist acting-as target state in conversation user_data."""
    if context is None:
        return None
    coerced = _coerce_user_id(target_id)
    context.user_data["acting_as_user_id"] = coerced
    return coerced


def clear_acting_as(context) -> None:
    """Remove acting-as target state from conversation user_data."""
    if context is None:
        return
    context.user_data.pop("acting_as_user_id", None)
