import hashlib


def hash_text(value, length=12):
    """Return a short SHA256 prefix for privacy-safe text correlation."""
    if value is None:
        return None
    text = str(value)
    if not text:
        return None
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest[:length]


def text_meta(value):
    """Return privacy-safe text metadata with length and hashed fingerprint."""
    if value is None:
        return {"len": 0, "hash": None}
    text = str(value)
    return {"len": len(text), "hash": hash_text(text)}
