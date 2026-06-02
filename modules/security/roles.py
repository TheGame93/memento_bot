ROLE_USER = "user"
ROLE_ADMIN = "admin"
ROLE_DEVELOPER = "developer"

VALID_ROLES = {ROLE_USER, ROLE_ADMIN, ROLE_DEVELOPER}
ROLE_PRIORITY = {
    ROLE_USER: 1,
    ROLE_ADMIN: 2,
    ROLE_DEVELOPER: 3,
}


def normalize_role(raw_role):
    """Normalize raw role labels to supported canonical roles."""
    value = (raw_role or "").strip().lower()
    if value in VALID_ROLES:
        return value
    if value in {"dev", "developer", "owner"}:
        return ROLE_DEVELOPER
    return ROLE_USER


def pick_stronger_role(role_a, role_b):
    """Return the stronger role according to configured privilege priority."""
    ra = normalize_role(role_a)
    rb = normalize_role(role_b)
    return ra if ROLE_PRIORITY.get(ra, 0) >= ROLE_PRIORITY.get(rb, 0) else rb


def build_status_role_counts(role_map):
    """
    Build role counters used by status views.

    Contract:
    - users: only identities with normalized role "user"
    - admins: normalized role "admin"
    - developers: normalized role "developer"
    """
    counts = {
        "users": 0,
        "admins": 0,
        "developers": 0,
    }
    if not isinstance(role_map, dict):
        return counts

    for raw_role in role_map.values():
        role = normalize_role(raw_role)
        if role == ROLE_DEVELOPER:
            counts["developers"] += 1
        elif role == ROLE_ADMIN:
            counts["admins"] += 1
        else:
            counts["users"] += 1
    return counts
