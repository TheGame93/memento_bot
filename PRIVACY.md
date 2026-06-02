# Privacy Notes

## What this project is

Memento is a self-hosted Telegram bot. It runs on infrastructure controlled by the person deploying it, not as a hosted cloud service operated by this repository.

## What data is stored

Depending on how the bot is used, local bot data can include:

- Telegram user identifiers needed to separate user data and manage access
- Alerts, birthdays, tags, and user preferences
- User-uploaded reminder images
- Backup metadata and generated backup archives
- Operational logs with metadata about bot activity

## Where data is stored

By default, runtime data is stored locally under:

- `data/<user_id>/` for per-user alert data and media
- `data/system/` for system-level state such as whitelist data
- `data/systemlog.d/` and `data/userlog.d/` for logs
- `backups/` for generated backup artifacts

These roots can be overridden by the bot operator with environment variables such as `BOT_DATA_DIR` and `BOT_BACKUP_DIR`.

## Backups and email

The bot can create local backup archives for user data. If email backup is configured, backup archives may also be sent through an SMTP provider to an email address chosen by the operator or user flow.

That means backup delivery can leave the local machine when email backup is enabled. SMTP credentials and email handling are part of the operator's environment, not managed by this repository.

For setup details, see [EMAIL_BACKUP_SETUP.md](EMAIL_BACKUP_SETUP.md).

## Logging and privacy

The project follows a privacy-first logging approach. Raw message text should not be written to logs. Where text needs to be tracked for diagnostics, the codebase uses metadata such as length and hashes instead of full message bodies.

For the technical logging rules, see [docs/truth/policy_log.md](docs/truth/policy_log.md).

## Operator responsibility

If you run this bot, you are responsible for protecting:

- `.env` secrets such as the Telegram token and SMTP credentials
- filesystem permissions for local data, backups, and logs
- backup retention and access to exported archives
- the host machine, network exposure, and any email infrastructure you configure

## For contributors

This file is a short public-facing guide, not the full implementation policy. If you are changing code that touches storage, backups, or logs, read:

- [PROJECT_RULES.md](PROJECT_RULES.md)
- [docs/truth/policy_log.md](docs/truth/policy_log.md)
- [docs/truth/policy_backup.md](docs/truth/policy_backup.md)
