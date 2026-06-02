"""Provide shared allocation helpers and sentinel values for storage services."""

import re
import uuid

from modules import constants as C


_UNSET = object()


def _base_n_fixed(value, alphabet, fixed_len):
    """Encode an integer into a fixed-length base-N string using the given alphabet."""
    base = len(alphabet)
    chars = []
    remaining = int(value)
    for _ in range(fixed_len):
        chars.append(alphabet[remaining % base])
        remaining //= base
    chars.reverse()
    return "".join(chars)


def _shortcode_from_seq(seq):
    """Encode a sequence number into a shortcode string with a letter prefix and base62 tail.

    Tail length starts at SHORTCODE_MIN_TAIL_LEN and grows by one each time the
    current letter×tail space is exhausted, making the encoding unbounded and
    monotonically increasing within each tail-length block.
    """
    letters = C.SHORTCODE_LETTERS
    base62 = C.SHORTCODE_BASE62
    min_tail = int(getattr(C, "SHORTCODE_MIN_TAIL_LEN", 2))
    if seq < 0:
        raise ValueError("seq must be >= 0")

    remaining = int(seq)
    tail_len = min_tail
    letter_count = len(letters)
    base_count = len(base62)

    while True:
        block_size = letter_count * (base_count ** tail_len)
        if remaining < block_size:
            break
        remaining -= block_size
        tail_len += 1

    tail_block = base_count ** tail_len
    letter_idx = remaining // tail_block
    tail_idx = remaining % tail_block
    return letters[letter_idx] + _base_n_fixed(tail_idx, base62, tail_len)


def _is_shortcode_valid(code):
    if not isinstance(code, str):
        return False
    if not re.match(r"^[A-Za-z][A-Za-z0-9]{2,}$", code):
        return False
    if code.lower() in set(getattr(C, "SHORTCODE_RESERVED_COMMANDS", set())):
        return False
    return True


def _allocate_next_shortcode(next_seq, used_codes):
    seq = int(next_seq)
    used_lower = {c.lower() for c in used_codes}
    reserved = set(getattr(C, "SHORTCODE_RESERVED_COMMANDS", set()))

    while True:
        code = _shortcode_from_seq(seq)
        seq += 1
        lower = code.lower()
        if lower in reserved:
            continue
        if lower in used_lower:
            continue
        return code, seq


def _allocate_unique_alert_id(used_ids):
    for _ in range(128):
        candidate = str(uuid.uuid4())[:8]
        if candidate not in used_ids:
            return candidate
    raise RuntimeError("id_allocation_exhausted")

