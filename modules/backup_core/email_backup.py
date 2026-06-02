import json
import os
import smtplib
import ssl
import re
from datetime import datetime, timedelta
from email.message import EmailMessage
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

from modules.backup_core.constants import (
    BACKUP_SCHEMA_VERSION,
    EMAIL_BACKUP_DAY,
    EMAIL_BACKUP_HOUR,
    EMAIL_BACKUP_MINUTE,
    EMAIL_REMINDER_DAY,
    EMAIL_REMINDER_HOUR,
    EMAIL_REMINDER_MINUTE,
    MAX_EMAIL_SEND_HISTORY,
)
from modules.backup_core.manifest import hash_bytes, hash_file, validate_manifest
from modules.constants import EMAIL_BACKUP_MAX_ATTACHMENT_BYTES
from modules.systemlog import log_system

EMAIL_LOCAL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$")
EMAIL_DOMAIN_RE = re.compile(r"^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")


def _smtp_config():
    raw_port = os.getenv("BOT_SMTP_PORT", "587")
    try:
        smtp_port = int(raw_port)
    except Exception:
        return None, "smtp_port_invalid"

    return {
        "host": os.getenv("BOT_SMTP_HOST"),
        "port": smtp_port,
        "user": os.getenv("BOT_SMTP_USER"),
        "password": os.getenv("BOT_SMTP_PASS"),
        "from_addr": os.getenv("BOT_SMTP_FROM"),
        "tls": os.getenv("BOT_SMTP_TLS", "1") == "1",
        "ssl": os.getenv("BOT_SMTP_SSL", "0") == "1",
    }, None


def _is_day_of_month(dt, day):
    try:
        target = int(day)
    except Exception:
        return False
    return int(dt.day) == target


def _month_key(dt):
    return (dt.year, dt.month)


def _month_slot_key(dt):
    return f"{dt.year}-{dt.month:02d}"


def _coerce_email_send_history(raw_history):
    """Return sanitized email history entries as a list of dict payloads."""
    if not isinstance(raw_history, list):
        return []
    return [entry for entry in raw_history if isinstance(entry, dict)]


def _slot_already_sent(history, slot_key):
    history = _coerce_email_send_history(history)
    return any(
        e.get("slot_key") == slot_key and e.get("reason") != "manual"
        for e in history
    )


def _make_history_entry(sent_at, to_email, from_email, size_bytes, reason, slot_dt=None):
    """Build one persisted email-send history entry with optional slot-month override."""
    slot_source = slot_dt if isinstance(slot_dt, datetime) else sent_at
    return {
        "sent_at": sent_at.isoformat(),
        "to_email": to_email,
        "from_email": from_email,
        "size_bytes": size_bytes,
        "reason": reason,
        "slot_key": _month_slot_key(slot_source),
    }


def _normalized_email_address(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        text.encode("ascii")
    except UnicodeEncodeError:
        return None
    if "@" not in text:
        return None
    local, domain = text.rsplit("@", 1)
    if not local or not domain:
        return None
    if not EMAIL_LOCAL_RE.match(local):
        return None
    if not EMAIL_DOMAIN_RE.match(domain):
        return None
    labels = domain.split(".")
    if len(labels) < 2:
        return None
    if any(not label or label.startswith("-") or label.endswith("-") for label in labels):
        return None
    if len(labels[-1]) < 2:
        return None
    return f"{local}@{domain.lower()}"


def describe_monthly_backup_schedule():
    """Human-readable recurring schedule derived from active scheduler constants."""
    return (
        f"Day {int(EMAIL_BACKUP_DAY)} of every month at "
        f"{int(EMAIL_BACKUP_HOUR):02d}:{int(EMAIL_BACKUP_MINUTE):02d} "
        "(server time)"
    )


def describe_monthly_reminder_schedule():
    """Human-readable reminder schedule derived from active scheduler constants."""
    try:
        day = int(EMAIL_REMINDER_DAY)
    except Exception:
        day = 1
    try:
        hour = int(EMAIL_REMINDER_HOUR)
    except Exception:
        hour = 0
    try:
        minute = int(EMAIL_REMINDER_MINUTE)
    except Exception:
        minute = 0
    return f"Day {day} of every month at {hour:02d}:{minute:02d} (server time)"


def _parse_iso(ts):
    try:
        return datetime.fromisoformat(str(ts))
    except Exception:
        return None


def _coerce_naive(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    try:
        from modules.timezone_utils import get_server_tz
        return dt.astimezone(get_server_tz()).replace(tzinfo=None)
    except Exception:
        return dt.replace(tzinfo=None)


def _expected_monthly_datetime(now, day, hour, minute):
    try:
        day = int(day)
        hour = int(hour)
        minute = int(minute)
    except Exception:
        return None
    try:
        candidate = now.replace(
            day=day,
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
    except ValueError:
        return None
    if now >= candidate:
        return candidate
    year = now.year
    month = now.month - 1
    if month == 0:
        month = 12
        year -= 1
    try:
        return datetime(year, month, day, hour, minute, 0, 0)
    except ValueError:
        return None


def normalize_email_address(value):
    """Return a normalized deliverable email address or None when invalid."""
    return _normalized_email_address(value)


def smtp_service_status():
    """Returns SMTP configuration diagnostic (no secrets exposed)."""
    config, config_error = _smtp_config()
    if config_error:
        return {"configured": False, "reason": config_error, "from_addr": None}
    if not config["host"]:
        return {"configured": False, "reason": "smtp_host_missing", "from_addr": None}
    from_addr = config["from_addr"] or config["user"] or None
    if isinstance(from_addr, str) and not from_addr.strip():
        from_addr = None
    return {"configured": True, "reason": None, "from_addr": from_addr}


def last_expected_backup_time(now):
    """Return the most recent scheduled monthly-backup timestamp."""
    return _expected_monthly_datetime(
        now,
        EMAIL_BACKUP_DAY,
        EMAIL_BACKUP_HOUR,
        EMAIL_BACKUP_MINUTE,
    )


def last_expected_reminder_time(now):
    """Return the most recent scheduled monthly-reminder timestamp."""
    return _expected_monthly_datetime(
        now,
        EMAIL_REMINDER_DAY,
        EMAIL_REMINDER_HOUR,
        EMAIL_REMINDER_MINUTE,
    )


def should_send_startup_backup(now, prefs):
    """Decide whether a startup catch-up backup should be sent now.

    Returns `(should_send, reason_code, expected_datetime)` so callers can
    log deterministic skip reasons without recalculating schedule context.
    Checks sanitized `email_send_history` first (durable); falls back to
    `last_email_sent` only when sanitized history is empty.
    """
    prefs = prefs or {}
    if not prefs.get("email_enabled"):
        return False, "disabled", None
    expected = last_expected_backup_time(now)
    if expected is None:
        return False, "schedule_invalid", None
    if expected > now:
        return False, "not_due", expected
    history = _coerce_email_send_history(prefs.get("email_send_history"))
    if _slot_already_sent(history, _month_slot_key(expected)):
        return False, "already_sent", expected
    # Backward compat: honour last_email_sent only when durable history is absent.
    if not history:
        last_sent = _coerce_naive(_parse_iso(prefs.get("last_email_sent")))
        if last_sent and last_sent >= expected:
            return False, "already_sent", expected
    return True, "ok", expected


def should_send_startup_reminder(now, prefs):
    """Decide whether a startup catch-up reminder should be sent now.

    Returns `(should_send, reason_code, expected_datetime)` for clear scheduler
    telemetry and consistent startup skip semantics.
    """
    prefs = prefs or {}
    expected = last_expected_reminder_time(now)
    if expected is None:
        return False, "schedule_invalid", None
    if expected > now:
        return False, "not_due", expected
    if prefs.get("email_enabled"):
        return False, "backup_enabled", expected
    snooze_until = _coerce_naive(_parse_iso(prefs.get("email_reminder_snooze_until")))
    if snooze_until and now < snooze_until:
        return False, "snoozed", expected
    if _normalized_email_address(prefs.get("email_address")):
        return False, "has_email", expected
    if prefs.get("email_reminder_disabled"):
        return False, "disabled", expected
    last_sent = _coerce_naive(_parse_iso(prefs.get("last_email_reminder_sent")))
    if last_sent and last_sent >= expected:
        return False, "already_sent", expected
    return True, "ok", expected


def should_send_monthly(now, prefs):
    """Return whether this month still requires a scheduled backup send.

    Checks sanitized `email_send_history` first (durable, survives log
    deletion); falls back to `last_email_sent` only when sanitized history
    is empty.
    """
    if not _is_day_of_month(now, EMAIL_BACKUP_DAY):
        return False
    prefs = prefs or {}
    history = _coerce_email_send_history(prefs.get("email_send_history"))
    if _slot_already_sent(history, _month_slot_key(now)):
        return False
    # Durable history exists and does not cover this slot: do not consult fallback.
    if history:
        return True
    # Backward compat: honour last_email_sent only when durable history is absent.
    last_sent_iso = prefs.get("last_email_sent")
    if not last_sent_iso:
        return True
    try:
        last_sent = datetime.fromisoformat(last_sent_iso)
    except Exception:
        return True
    return _month_key(last_sent) != _month_key(now)


def should_send_monthly_reminder(now, prefs):
    """Return whether this month still requires a scheduled reminder send."""
    prefs = prefs or {}
    if not _is_day_of_month(now, EMAIL_REMINDER_DAY):
        return False, "not_day"
    if prefs.get("email_enabled"):
        return False, "backup_enabled"
    snooze_until = _coerce_naive(_parse_iso(prefs.get("email_reminder_snooze_until")))
    if snooze_until and now < snooze_until:
        return False, "snoozed"
    if _normalized_email_address(prefs.get("email_address")):
        return False, "has_email"
    if prefs.get("email_reminder_disabled"):
        return False, "disabled"
    last_sent = _parse_iso(prefs.get("last_email_reminder_sent"))
    if last_sent and _month_key(last_sent) == _month_key(now):
        return False, "already_sent"
    return True, "ok"


def build_email_backup_archive(snapshot, now=None):
    """Build ZIP payload bytes and manifest data for one email backup send.

    Returns `(archive_bytes, manifest_data)` for subsequent size checks,
    signature/hash validation, and transport through SMTP.
    """
    if now is None:
        now = datetime.now()

    alerts_text = json.dumps(snapshot["alerts_data"], indent=2, ensure_ascii=False)
    alerts_bytes = alerts_text.encode("utf-8")

    base_dir = snapshot["base_dir"]
    image_files = snapshot["files"].get("images", [])
    source_map = snapshot.get("source_map") or {}

    manifest_entries = [
        {
            "path": "alerts.json",
            "size": len(alerts_bytes),
            "sha256": hash_bytes(alerts_bytes),
        }
    ]

    for rel_path in image_files:
        abs_path = source_map.get(rel_path) or os.path.join(base_dir, rel_path)
        if not os.path.isfile(abs_path):
            continue
        manifest_entries.append({
            "path": rel_path,
            "size": os.path.getsize(abs_path),
            "sha256": hash_file(abs_path),
        })

    manifest_data = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "created_at": now.isoformat(),
        "user_id": str(snapshot["user_id"]),
        "includes": {
            "alerts": True,
            "logs": False,
            "images": True,
        },
        "files": manifest_entries,
    }

    zip_buffer = BytesIO()
    with ZipFile(zip_buffer, "w", compression=ZIP_DEFLATED) as handle:
        handle.writestr("alerts.json", alerts_text)
        handle.writestr("manifest.json", json.dumps(manifest_data, indent=2, ensure_ascii=False))
        for rel_path in image_files:
            abs_path = source_map.get(rel_path) or os.path.join(base_dir, rel_path)
            if os.path.isfile(abs_path):
                handle.write(abs_path, arcname=rel_path)

    payload = zip_buffer.getvalue()
    return payload, manifest_data


def estimate_email_backup_size_bytes(storage, user_id, now=None):
    """Estimate serialized backup attachment size for a user email backup."""
    if now is None:
        now = datetime.now()
    try:
        snapshot = storage.get_user_snapshot(
            user_id,
            include_images=True,
            include_logs=False,
            ensure_space=True,
        )
        payload, _manifest = build_email_backup_archive(snapshot, now=now)
        return len(payload)
    except Exception:
        return None


def _build_email_message(to_email, subject, body, attachments):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["To"] = to_email
    msg.set_content(body)

    for attachment in attachments:
        msg.add_attachment(
            attachment["data"],
            maintype=attachment.get("maintype", "application"),
            subtype=attachment.get("subtype", "zip"),
            filename=attachment.get("filename"),
        )
    return msg


def _send_email(message, config):
    context = ssl.create_default_context()
    host = config["host"]
    port = config["port"]
    user = config["user"]
    password = config["password"]
    use_tls = config["tls"]
    use_ssl = config["ssl"]

    if use_ssl:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as client:
            if user and password:
                client.login(user, password)
            client.send_message(message)
        return

    with smtplib.SMTP(host, port, timeout=20) as client:
        if use_tls:
            client.starttls(context=context)
        if user and password:
            client.login(user, password)
        client.send_message(message)


def send_backup_email(storage, user_id, to_email, now=None, reason="manual", *, history_slot_dt=None):
    """Send one backup email and return structured delivery outcome metadata.

    On success the payload contains `sent`, `bytes`, `from_email`, `to_email`,
    `sent_at` (ISO string), and `reason` so callers can build notifications
    and dedupe records without additional storage reads.
    On failure the payload contains `sent=False` plus `error` and optionally
    `details`.
    A history entry is written to `backup_prefs.email_send_history` on every
    successful send (with malformed history entries sanitized first);
    `last_email_sent` is also updated for backward compat. `history_slot_dt`
    only controls the persisted history `slot_key`, not send timestamps.
    """
    if now is None:
        now = datetime.now()
    to_email = _normalized_email_address(to_email)
    if not to_email:
        return {"sent": False, "error": "email_missing"}

    config, config_error = _smtp_config()
    if config_error:
        return {"sent": False, "error": config_error}
    if not config["host"]:
        return {"sent": False, "error": "smtp_host_missing"}

    snapshot = storage.get_user_snapshot(
        user_id,
        include_images=True,
        include_logs=False,
        ensure_space=True,
    )

    archive_bytes, manifest_data = build_email_backup_archive(snapshot, now=now)
    if len(archive_bytes) > EMAIL_BACKUP_MAX_ATTACHMENT_BYTES:
        top_images = []
        source_map = snapshot.get("source_map") or {}
        for rel_path in snapshot.get("files", {}).get("images", []):
            abs_path = source_map.get(rel_path) or os.path.join(snapshot.get("base_dir", ""), rel_path)
            if not os.path.isfile(abs_path):
                continue
            top_images.append({
                "filename": str(rel_path),
                "size_bytes": os.path.getsize(abs_path),
            })
        top_images = sorted(top_images, key=lambda item: item["size_bytes"], reverse=True)[:10]
        log_system("backup", "email_backup_too_large", {
            "user_id": str(user_id),
            "bytes": len(archive_bytes),
            "limit_bytes": int(EMAIL_BACKUP_MAX_ATTACHMENT_BYTES),
            "top_image_count": len(top_images),
        }, level="ERROR")
        storage.log_user_event(str(user_id), "backup_create_failed", {
            "source": reason,
            "reason_code": "email_too_large",
            "size_bytes": int(len(archive_bytes)),
            "limit_bytes": int(EMAIL_BACKUP_MAX_ATTACHMENT_BYTES),
            "top_image_count": len(top_images),
        })
        return {"sent": False, "error": "attachment_too_large", "top_images": top_images}

    valid, errors = validate_manifest(manifest_data)
    if not valid:
        return {"sent": False, "error": "manifest_invalid", "details": errors}

    filename = f"alerts_backup_{user_id}_{now.strftime('%Y%m%d')}.zip"
    subject = f"Smart Alerts Backup - {now.strftime('%Y-%m-%d')}"
    body = (
        "Your Smart Alerts backup is attached.\n\n"
        f"User ID: {user_id}\n"
        f"Created at: {now.isoformat()}\n"
        f"Reason: {reason}\n"
    )

    msg = _build_email_message(
        to_email,
        subject,
        body,
        [{
            "filename": filename,
            "data": archive_bytes,
            "maintype": "application",
            "subtype": "zip",
        }],
    )

    from_addr = config["from_addr"] or config["user"] or "no-reply@localhost"
    msg["From"] = from_addr

    try:
        _send_email(msg, config)
        log_system("backup", "email_backup_sent", {
            "user_id": str(user_id),
            "to": to_email,
            "bytes": len(archive_bytes),
            "reason": reason,
        })
        try:
            prefs = storage.get_backup_prefs(user_id)
            raw_history = prefs.get("email_send_history") if isinstance(prefs, dict) else None
            history = _coerce_email_send_history(raw_history)
            history.append(_make_history_entry(
                now,
                to_email,
                from_addr,
                len(archive_bytes),
                reason,
                slot_dt=history_slot_dt,
            ))
            if len(history) > MAX_EMAIL_SEND_HISTORY:
                history = history[-MAX_EMAIL_SEND_HISTORY:]
            storage.update_backup_prefs(user_id, {
                "email_send_history": history,
                "last_email_sent": now.isoformat(),
            })
        except Exception as hist_exc:
            log_system("backup", "email_backup_history_write_failed", {
                "user_id": str(user_id),
                "reason_code": "history_write_failed",
                "error_class": type(hist_exc).__name__,
            }, level="WARNING")
        return {
            "sent": True,
            "bytes": len(archive_bytes),
            "from_email": from_addr,
            "to_email": to_email,
            "sent_at": now.isoformat(),
            "reason": reason,
        }
    except Exception as exc:
        log_system("backup", "email_backup_failed", {
            "user_id": str(user_id),
            "to": to_email,
            "error": str(exc),
        }, level="ERROR")
        return {"sent": False, "error": str(exc)}


def run_monthly_email_backups(storage, now=None):
    """Run scheduled monthly email backups for all eligible users."""
    if now is None:
        now = datetime.now()

    results = []
    for user_id in storage.get_all_users():
        prefs = storage.get_backup_prefs(user_id)
        if not prefs.get("email_enabled"):
            continue
        to_email = _normalized_email_address(prefs.get("email_address"))
        if not to_email:
            continue
        if not should_send_monthly(now, prefs):
            continue

        result = send_backup_email(storage, user_id, to_email, now=now, reason="monthly")
        if result.get("sent"):
            archive_id = f"alerts_backup_{user_id}_{now.strftime('%Y%m%d')}"
            storage.log_user_event(str(user_id), "backup_created", {
                "source": "monthly",
                "archive_id": archive_id,
                "size_bytes": int(result.get("bytes") or 0),
            })
            storage.log_user_event(str(user_id), "backup_exported", {
                "source": "monthly",
                "target": "mail",
                "archive_id": archive_id,
                "size_bytes": int(result.get("bytes") or 0),
            })
        results.append({"user_id": str(user_id), "result": result})

    return results
