def md_escape(value):
    """Escape user-provided text for Telegram legacy Markdown parse mode.

    Handles: backslash, backtick, asterisk, underscore, open bracket.
    Collapses newlines into spaces (Telegram legacy Markdown does not support
    multiline in most inline contexts).
    """
    text = "" if value is None else str(value)
    if not text:
        return text
    text = " ".join(text.splitlines())
    text = text.replace("\\", "\\\\")
    for ch in ("`", "*", "_", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


def md_escape_inline_code(value):
    """Sanitize dynamic text interpolated inside Markdown inline-code spans."""
    text = "" if value is None else str(value)
    if not text:
        return text
    text = " ".join(text.splitlines())
    return text.replace("`", "'")


def md_escape_multiline_text(value):
    """Escape multiline Markdown text while preserving original line boundaries."""
    text = "" if value is None else str(value)
    if not text:
        return text
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(md_escape(line) for line in normalized.split("\n"))


def md_escape_fence_content(value):
    """Escape user text intended for inside a ``` code fence.

    Only need to prevent the user from closing the fence.
    Replaces ``` with ''' to prevent fence breakout.
    """
    text = "" if value is None else str(value)
    if not text:
        return text
    text = text.replace("```", "'''")
    return text
