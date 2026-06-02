from typing import Any, Dict, Optional


def _build_display_name(user: Any) -> Optional[str]:
    if user is None:
        return None
    full_name = getattr(user, "full_name", None)
    if full_name:
        return str(full_name)
    first = getattr(user, "first_name", None)
    last = getattr(user, "last_name", None)
    parts = [part for part in [first, last] if part]
    if parts:
        return " ".join(str(part) for part in parts)
    return None


def extract_forward_identity(message: Any) -> Dict[str, Any]:
    """Extract forwarded sender identity and standardized failure reason codes."""
    result = {
        "user_id": None,
        "username": None,
        "display_name": None,
        "error": None,
    }
    if message is None:
        result["error"] = "missing_message"
        return result

    forward_user = getattr(message, "forward_from", None)
    if forward_user is not None:
        result["user_id"] = getattr(forward_user, "id", None)
        result["username"] = getattr(forward_user, "username", None)
        result["display_name"] = _build_display_name(forward_user)
        return result

    forward_origin = getattr(message, "forward_origin", None)
    if forward_origin is not None:
        sender_user = getattr(forward_origin, "sender_user", None)
        if sender_user is not None:
            result["user_id"] = getattr(sender_user, "id", None)
            result["username"] = getattr(sender_user, "username", None)
            result["display_name"] = _build_display_name(sender_user)
            return result
        sender_name = getattr(forward_origin, "sender_user_name", None)
        if sender_name:
            result["error"] = "hidden_sender"
            return result
        if getattr(forward_origin, "chat", None) is not None:
            result["error"] = "forwarded_chat"
            return result

    forward_sender_name = getattr(message, "forward_sender_name", None)
    if forward_sender_name:
        result["error"] = "hidden_sender"
        return result

    result["error"] = "no_forward"
    return result
