import difflib
import re
import unicodedata

try:
    from rapidfuzz import fuzz as rf_fuzz
except Exception:
    rf_fuzz = None


def _normalize_search_text(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _safe_score(value: float) -> int:
    try:
        v = float(value)
    except Exception:
        return 0
    return max(0, min(100, int(round(v))))


def _fallback_ratio(a: str, b: str) -> int:
    return _safe_score(difflib.SequenceMatcher(None, a, b).ratio() * 100)


def _fallback_partial_ratio(query: str, target: str) -> int:
    if not query or not target:
        return 0
    if len(query) > len(target):
        query, target = target, query
    best = 0
    qlen = len(query)
    for i in range(0, len(target) - qlen + 1):
        candidate = target[i:i + qlen]
        best = max(best, _fallback_ratio(query, candidate))
        if best == 100:
            break
    return best


def _fallback_token_set_ratio(query: str, target: str) -> int:
    q_tokens = sorted(set(query.split()))
    t_tokens = sorted(set(target.split()))
    if not q_tokens or not t_tokens:
        return 0
    q_join = " ".join(q_tokens)
    t_join = " ".join(t_tokens)
    common = " ".join(sorted(set(q_tokens) & set(t_tokens)))
    if common:
        return max(
            _fallback_ratio(common, q_join),
            _fallback_ratio(common, t_join),
            _fallback_ratio(q_join, t_join),
        )
    return _fallback_ratio(q_join, t_join)


def _pairwise_word_similarity(query_tokens, target_tokens) -> int:
    if not query_tokens or not target_tokens:
        return 0
    scores = []
    for q in query_tokens:
        best = 0
        for t in target_tokens:
            if rf_fuzz:
                s = _safe_score(rf_fuzz.ratio(q, t))
            else:
                s = _fallback_ratio(q, t)
            if s > best:
                best = s
        scores.append(best)
    return int(round(sum(scores) / len(scores))) if scores else 0


def _score_name_match(query_norm: str, title_norm: str):
    if not query_norm or not title_norm:
        return 0, {}

    if rf_fuzz:
        full = _safe_score(rf_fuzz.WRatio(query_norm, title_norm))
        partial = _safe_score(rf_fuzz.partial_ratio(query_norm, title_norm))
        token = _safe_score(rf_fuzz.token_set_ratio(query_norm, title_norm))
    else:
        full = _fallback_ratio(query_norm, title_norm)
        partial = _fallback_partial_ratio(query_norm, title_norm)
        token = _fallback_token_set_ratio(query_norm, title_norm)

    query_tokens = query_norm.split()
    target_tokens = title_norm.split()
    token_coverage = _pairwise_word_similarity(query_tokens, target_tokens)
    best_word = _pairwise_word_similarity(query_tokens[:1], target_tokens) if query_tokens else 0
    contains = query_norm in title_norm
    starts = bool(target_tokens and query_tokens and target_tokens[0].startswith(query_tokens[0]))

    score = (
        0.35 * full +
        0.35 * token +
        0.20 * partial +
        0.10 * token_coverage
    )
    if contains:
        score += 5
    if starts:
        score += 3
    # If the query is a single token, let word-level similarity drive tolerance.
    if len(query_tokens) == 1:
        score = max(score, 0.65 * best_word + 0.35 * partial)
    final = _safe_score(score)

    details = {
        "full": full,
        "partial": partial,
        "token": token,
        "coverage": token_coverage,
        "best_word": best_word,
        "contains": contains,
        "starts": starts,
    }
    return final, details


def rank_birthdays_by_name(query_text, birthdays):
    """Rank birthdays by normalized title similarity against the query text."""
    query_norm = _normalize_search_text(query_text)
    results = []
    for alert in birthdays:
        title = alert.get("title", "")
        title_norm = _normalize_search_text(title)
        score, details = _score_name_match(query_norm, title_norm)
        results.append({
            "alert": alert,
            "score": score,
            "details": details,
            "title_norm": title_norm,
        })
    results.sort(key=lambda r: (-r["score"], r["alert"].get("title", "").lower()))
    return query_norm, results
