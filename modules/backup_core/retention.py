from datetime import datetime

from modules.backup_core.constants import (
    RETENTION_DAILY,
    RETENTION_WEEKLY,
    RETENTION_MONTHLY,
    RETENTION_YEARLY,
)


def _bucket_day(dt):
    return dt.date()


def _bucket_week(dt):
    iso = dt.isocalendar()
    return (iso.year, iso.week)


def _bucket_month(dt):
    return (dt.year, dt.month)


def _bucket_year(dt):
    return dt.year


def _pick_bucketed(items, bucket_fn, limit, newer_than, keep_idx):
    buckets = set()
    kept_indices = []
    for idx, item in enumerate(items):
        ts = item["timestamp"]
        if newer_than is not None and ts >= newer_than:
            continue
        if idx in keep_idx:
            continue
        bucket = bucket_fn(ts)
        if bucket in buckets:
            continue
        keep_idx.add(idx)
        kept_indices.append(idx)
        buckets.add(bucket)
        if len(buckets) >= limit:
            break

    oldest = None
    if kept_indices:
        oldest = min(items[idx]["timestamp"] for idx in kept_indices)
    return oldest, len(buckets)


def select_retention(items, now=None,
                     daily=RETENTION_DAILY,
                     weekly=RETENTION_WEEKLY,
                     monthly=RETENTION_MONTHLY,
                     yearly=RETENTION_YEARLY):
    """
    Select backups to keep based on tiered retention buckets.

    items: list of {"timestamp": datetime, ...}
    returns dict with keep/drop lists and bucket counts.
    """
    if now is None:
        now = datetime.now()

    items_sorted = sorted(items, key=lambda i: i["timestamp"], reverse=True)
    keep_idx = set()

    daily_floor, daily_count = _pick_bucketed(items_sorted, _bucket_day, daily, None, keep_idx)
    weekly_floor, weekly_count = _pick_bucketed(items_sorted, _bucket_week, weekly, daily_floor, keep_idx)
    monthly_floor, monthly_count = _pick_bucketed(items_sorted, _bucket_month, monthly, weekly_floor, keep_idx)
    _, yearly_count = _pick_bucketed(items_sorted, _bucket_year, yearly, monthly_floor, keep_idx)

    keep = [item for idx, item in enumerate(items_sorted) if idx in keep_idx]
    drop = [item for idx, item in enumerate(items_sorted) if idx not in keep_idx]

    return {
        "keep": keep,
        "drop": drop,
        "stats": {
            "daily": daily_count,
            "weekly": weekly_count,
            "monthly": monthly_count,
            "yearly": yearly_count,
            "total_keep": len(keep),
            "total_drop": len(drop),
            "total_items": len(items_sorted),
        },
    }
