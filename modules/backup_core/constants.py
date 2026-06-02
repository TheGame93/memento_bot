BACKUP_SCHEMA_VERSION = "1.0"

RETENTION_DAILY = 7
RETENTION_WEEKLY = 4
RETENTION_MONTHLY = 6
RETENTION_YEARLY = 10
PRE_IMPORT_RETENTION_DAILY = 3

LOCAL_BACKUP_HOUR = 2
LOCAL_BACKUP_MINUTE = 0

EMAIL_BACKUP_DAY = 28 #28
EMAIL_BACKUP_HOUR = 3 #3
EMAIL_BACKUP_MINUTE = 0 #0

# Monthly reminder for missing email backup configuration.
EMAIL_REMINDER_DAY = 20 #20
EMAIL_REMINDER_HOUR = 3 #3
EMAIL_REMINDER_MINUTE = 0 #0

# Maximum number of email send history entries retained per user.
# Covers 2 years of monthly sends (12 scheduled) with room for manual sends.
MAX_EMAIL_SEND_HISTORY = 24

# Import archive safety limits (zip bomb mitigation).
IMPORT_ARCHIVE_MAX_MEMBERS = 4096
IMPORT_ARCHIVE_MAX_MEMBER_BYTES = 128 * 1024 * 1024
IMPORT_ARCHIVE_MAX_TOTAL_BYTES = 512 * 1024 * 1024
