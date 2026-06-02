# Email Backup Setup (Gmail)

This guide explains how to configure the bot to send monthly backup emails using Gmail, and how users can control it via commands.

## 1) Gmail prerequisites

You must use a Gmail account with **2‑Step Verification** enabled and an **App Password** generated for the bot.

Steps:
1. Enable 2‑Step Verification on the Gmail account you want to use.
2. Create an App Password for "Mail" (or a custom label like "My Custom Label Bot").
3. Use that App Password as the SMTP password (not your normal Gmail password).

## 2) Environment variables

Add these to your `.env` file:

```
BOT_SMTP_HOST=smtp.gmail.com
BOT_SMTP_PORT=587
BOT_SMTP_USER=yourbot@gmail.com
BOT_SMTP_PASS=your_app_password_here
BOT_SMTP_FROM=yourbot@gmail.com
BOT_SMTP_TLS=1
BOT_SMTP_SSL=0
```

Notes:
- Use port **587 + TLS** (recommended for Gmail).
- If you prefer SSL on port 465, set:
  - `BOT_SMTP_PORT=465`
  - `BOT_SMTP_SSL=1`
  - `BOT_SMTP_TLS=0`

## 3) What gets emailed

The ZIP attachment contains:
- `alerts.json` — the user's full alert and birthday database
- All image files stored under the user's `images/` folder
- `manifest.json` — archive metadata and integrity hashes

Log files are **not** included (the archive is built with `include_logs=False`).

Attachment size is capped at **20 MB** (`EMAIL_BACKUP_MAX_ATTACHMENT_BYTES` in `modules/constants.py`). Archives that exceed this limit are not sent.

## 4) Schedule behavior

- **Monthly backup** runs on day **28** of every month at **03:00 server time**.
- **Reminder email** (sent when no backup address is configured) runs on day **20** of every month at **03:00 server time**.
- You can also trigger an immediate send from the bot settings (see section 5).

## 5) How to configure

All email-backup settings are managed through the bot's menu — there are no slash commands for this feature.

1. Open `/settings` in the bot.
2. Navigate to **Backups → Mail Backup**.
3. From the menu you can:
   - **Enable** monthly email backups and set the destination address.
   - **Disable** monthly email backups.
   - **Send now** — trigger an immediate backup email to the configured address.

## 6) Quick troubleshooting

- If sending fails:
  - Check SMTP credentials and App Password.
  - Verify network access to `smtp.gmail.com`.
  - Review `data/systemlog.d/backup.log` for error details.

- If the email is missing attachments:
  - Verify the user has `alerts.json` and any image files under `images/`.
  - Ensure the combined archive is under 20 MB.

## 7) Optional: change schedule

Both the backup and reminder schedule are controlled in `modules/backup_core/constants.py`:

```python
EMAIL_BACKUP_DAY     # day of month for the backup send (default: 28)
EMAIL_BACKUP_HOUR    # hour of the backup send, server time (default: 3)
EMAIL_BACKUP_MINUTE  # minute of the backup send (default: 0)

EMAIL_REMINDER_DAY   # day of month for the reminder send (default: 20)
EMAIL_REMINDER_HOUR  # hour of the reminder send, server time (default: 3)
EMAIL_REMINDER_MINUTE # minute of the reminder send (default: 0)
```

Change the values and restart the bot to apply.
