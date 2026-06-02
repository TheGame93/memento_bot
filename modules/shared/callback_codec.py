import hashlib
import re

MAX_CALLBACK_BYTES = 64


def callback_bytes_len(callback_data):
    """Return callback payload length in UTF-8 bytes."""
    if callback_data is None:
        return 0
    return len(str(callback_data).encode("utf-8"))


def ensure_callback_fits(callback_data, limit=MAX_CALLBACK_BYTES):
    """Validate that callback payload length stays within Telegram byte limits."""
    return callback_bytes_len(callback_data) <= int(limit)


def _digest_token(value):
    raw = str(value).encode("utf-8")
    return hashlib.blake2s(raw, digest_size=16).hexdigest()


def build_value_token_map(values, min_len=8, max_len=24):
    """
    Builds a collision-free token->value mapping for the provided values.
    Token length expands when needed.
    """
    unique_values = []
    seen = set()
    for value in values or []:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)

    if not unique_values:
        return {}

    for token_len in range(int(min_len), int(max_len) + 1):
        mapping = {}
        collision = False
        for value in unique_values:
            token = _digest_token(value)[:token_len]
            existing = mapping.get(token)
            if existing is not None and existing != value:
                collision = True
                break
            mapping[token] = value
        if not collision:
            return mapping

    raise ValueError("Unable to build collision-free callback token map")


def extract_callback_token(callback_data, prefix):
    """Extract token suffix from a callback payload with the expected prefix."""
    if not isinstance(callback_data, str):
        return None
    if not callback_data.startswith(prefix):
        return None
    token = callback_data[len(prefix):]
    return token or None


def is_token_candidate(token, min_len=8, max_len=24):
    """Return whether a token matches the expected lowercase hex shape."""
    if not isinstance(token, str):
        return False
    pattern = rf"^[0-9a-f]{{{int(min_len)},{int(max_len)}}}$"
    return bool(re.match(pattern, token))
