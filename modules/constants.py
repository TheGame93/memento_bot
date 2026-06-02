# modules/constants.py

import time

BOT_START_MONO = time.monotonic()

# =============================================================================
# CONVERSATION STATES (for ConversationHandler)
# =============================================================================
(
    SELECT_TYPE,
    GET_TITLE,
    
    # Type Specific Configs
    TYPE_1_DAYS,      # Monthly: Get days (text)
    TYPE_2_ORDINAL,   # Monthly Rel: Get 1st, 2nd...
    TYPE_2_WEEKDAY,   # Monthly Rel: Get Mon, Tue...
    TYPE_3_WEEKDAYS,  # Weekly: Get Mon, Tue...
    TYPE_4_DATES,     # Yearly: Get DD/MM
    TYPE_5_DATE,      # Once: Get DD/MM/YYYY
    TYPE_6_DATE,      # Birthday: Get DD/MM
    
    GET_INTERVAL,     # For recurring types
    GET_START_DATE,   # If interval > 1
    
    GET_TIME,
    GET_PRE_ALERT,
    GET_TAGS,
    GET_PHOTO,
    MULTI_SETTINGS,
    CONFIRMATION,
    GET_CUSTOM_PRE_ALERT,
    CONFIRM_CUSTOM_PRE_ALERT,
    GET_ADDITIONAL_INFO,
    BDAY_NAME_CONFIRM,
    BDAY_SETTINGS,
    LIST_MENU,
    
    # Snooze custom input state
    SNOOZE_CUSTOM_INPUT,

    # Monthly relative 5th ordinal policy
    TYPE_2_FIFTH_POLICY,

    # Daily interval=1 confirmation
    DAILY_INTERVAL_CONFIRM,
    FUZZY_INTERVAL_MODE_CHOICE,
    FUZZY_MEAN_STD_INPUT,

    # Change-type and edit-flow states
    CHANGE_ALERT_TYPE,
    EDIT_DASHBOARD,
    EDIT_NAME,
    # Repetition flow states
    GET_REPETITION_MENU,
    GET_REPETITION_COUNT,
    GET_REPETITION_UNTIL_DATE,
) = range(34)

# =============================================================================
# CALLBACK DATA PREFIXES
# =============================================================================
CB_TYPE = "type_"
CB_ORDINAL = "ord_"
CB_WEEKDAY = "wk_"
CB_TAG = "tag_"
CB_ACTION = "act_"  # Save/Discard

# Scheduler/Snooze callbacks
CB_SNOOZE = "snooze_"       # snooze_1h_alertid, snooze_1d_alertid, etc.
CB_ALERT_DONE = "alertdone_"  # alertdone_alertid
CB_POSTPONE = "pp_"         # postpone callbacks
CB_ALERT_DELETE = "alertdel_"
CB_ALERT_TOGGLE = "alerttoggle_"
CB_FIFTH_POLICY = "fifth_"
CB_INTERVAL_FIXED = "intmode_fixed"
CB_INTERVAL_FUZZY = "intmode_fuzzy"
# Pre-alert info toggle
CB_PREALERT_INFO = "preinfo_"
CB_ALERT_INFO = "ainfo_"

# Placebo acknowledgment buttons
CB_PLACEBO_DONE = "pdone_"     # Regular alert main: "✅ DONE !"
CB_PLACEBO_NOTED = "pnote_"    # Pre-alert noted (all types): "👀 NOTED !"
CB_BDAY_NOTED = "bnote_"       # Birthday main alert noted: "👀 NOTED !" → birthday msg prompt
CB_BDAY_MSG = "bmsg_"          # Birthday message style selection
CB_NOTIF_BACK = "nback_"       # Back from notification-originated detail view

# =============================================================================
# LISTS
# =============================================================================
TAGS = [
    "🚗 Car", 
    "📂 Documents", 
    "👨‍👩‍👧 Family", 
    "🫂 Friends", 
    "🏥 Health", 
    "🏠 Home", 
    "❤️ Love", 
    "🐾 Pet", 
    "💼 Work"
]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
ORDINALS = ["1st", "2nd", "3rd", "4th", "5th", "Last"]

# =============================================================================
# ALERT TYPES
# =============================================================================
ALERT_TYPES = {
    1: "Monthly (Specific Day)",
    2: "Monthly (Relative)",
    3: "Weekly",
    4: "Yearly",
    5: "One Time",
    6: "Birthday",
    7: "Daily",
    8: "Empty"
}

# =============================================================================
# BIRTHDAY SETTINGS
# =============================================================================
# Fixed time for birthday alerts (not asked during creation)
BIRTHDAY_DEFAULT_TIME = "08:00"
# Configurable fire time for the "evening before" birthday pre-alert option.
BIRTHDAY_EVENING_BEFORE_DEFAULT_TIME = "21:00"
# Dedicated pre-alert token used by birthday "evening before" option.
BIRTHDAY_PREALERT_EVENING_BEFORE_TOKEN = "bday_evening_before"
# Feb 29 handling: "mar1" (Italy-style) or "feb28"
BIRTHDAY_FEB29_POLICY = "mar1"

# Zodiac mode for birthday info/reminders.
BIRTHDAY_ZODIAC_MODE_NONE = "none"
BIRTHDAY_ZODIAC_MODE_WESTERN = "western"
BIRTHDAY_ZODIAC_MODE_EASTERN = "eastern"
BIRTHDAY_ZODIAC_MODE_BOTH = "both"
BIRTHDAY_ZODIAC_MODES = (
    BIRTHDAY_ZODIAC_MODE_NONE,
    BIRTHDAY_ZODIAC_MODE_WESTERN,
    BIRTHDAY_ZODIAC_MODE_EASTERN,
    BIRTHDAY_ZODIAC_MODE_BOTH,
)

# Birthday fuzzy-search configuration
BIRTHDAY_SEARCH_MIN_SCORE = 75
BIRTHDAY_SEARCH_TOP_N = 5
# Shows score/debug data in birthday-search output (set False to hide details)
BIRTHDAY_SEARCH_SHOW_DEBUG = True
# Window for /birthdays next view
BIRTHDAY_NEXT_PAST_DAYS = 10
BIRTHDAY_NEXT_FUTURE_DAYS = 30

# =============================================================================
# ALERT SETTINGS
# =============================================================================

# Alert fuzzy-search configuration
ALERT_SEARCH_MIN_SCORE = 75
ALERT_SEARCH_TOP_N = 5
# Shows score/debug data in alert-search output (set False to hide details)
ALERT_SEARCH_SHOW_DEBUG = True
FUZZY_INTERVAL_MIN_DAYS = 1

# Repetition modes (supported only for recurring non-birthday alerts).
REPETITION_MODE_FOREVER = "forever"
REPETITION_MODE_UNTIL_DATE = "until_date"
REPETITION_MODE_COUNT = "count"
REPETITION_SUPPORTED_TYPES = {1, 2, 3, 4, 7}

# =============================================================================
# DEBUG SETTINGS
# =============================================================================

# /status rendering: prefix each status line with scope markers like (U)/(A)/(D).
# Visible only to developers when enabled by caller-side gating.
STATUS_DEBUG_LABELS_ENABLED = True

# =============================================================================
# TIMEZONE CONFIGURATION
# =============================================================================
# Server timezone (DST-aware). Use IANA name, not fixed GMT offsets.
SERVER_TZ = "Europe/Rome"
TIMEZONE_MODE_SERVER = "server"
TIMEZONE_MODE_USER = "user"
TIMEZONE_DEFAULT_MODE = TIMEZONE_MODE_SERVER
TIMEZONE_SOURCE_DEFAULT = "default"
TIMEZONE_SOURCE_MANUAL = "manual"
TIMEZONE_SOURCE_AUTO = "auto"
TIMEZONE_SUGGESTION_LIMIT = 5

# =============================================================================
# ACTING-AS LOCKS
# =============================================================================
# When a developer is acting as a user, block that user's mutating actions.
# The lock auto-expires to avoid permanent freezes after crashes.
ACTING_AS_LOCK_TTL_SECONDS = 30 * 60

# =============================================================================
# SCHEDULER CONFIGURATION
# =============================================================================

# How often the scheduler checks for due alerts (in seconds)
# Default: 60 seconds
# Minimum safe: 10 seconds (Telegram rate limits: ~30 msg/sec global, 1 msg/sec per chat)
# For debugging, you can lower this to 10-15 seconds
SCHEDULER_INTERVAL_SECONDS = 20

# Alert message types (for formatting)
ALERT_MSG_TYPE_MAIN = "main"           # Regular scheduled alert
ALERT_MSG_TYPE_PRE = "pre_alert"       # Advance warning
ALERT_MSG_TYPE_MISSED = "missed"       # Delivered late (bot was offline)

# Missed alerts notification mode on bot restart.
# "once"   → notify only on the FIRST restart after the bot was offline.
#             Due alerts already work this way (next_scheduled advances on first detection).
#             Pre-alerts: tracked via notified_missed_pre state to prevent re-reporting.
# "always" → notify on EVERY restart until the alert fires normally via the scheduler.
MISSED_ALERTS_NOTIFY_MODE = "once"

# Snooze durations (label, timedelta kwargs)
SNOOZE_OPTIONS = {
    "1h": {"hours": 1},
    "1d": {"days": 1},
    "1w": {"weeks": 1},
}

# Shared quick-duration labels/tokens for postpone and ghost time picker keyboards.
QUICK_DURATION_OPTIONS = [
    ("⏰ +1h", "1h"),
    ("📅 +1d", "1d"),
    ("📆 +1w", "1w"),
]

# Pre-alert time parsing (matches add_alert.py format)
# Format: number + unit (m=minutes, h=hours, d=days, w=weeks, mo=months)
PRE_ALERT_UNITS = {
    'm': 'minutes',
    'h': 'hours', 
    'd': 'days',
    'w': 'weeks',
    'mo': 'months',
}

# =============================================================================
# SHORTCUTS / PAGINATION
# =============================================================================
# Global shortcut format: /<letter><base62><base62>... (tail grows when needed).
SHORTCODE_LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"  # 52
SHORTCODE_BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
SHORTCODE_MIN_TAIL_LEN = 2
SHORTCODE_RESERVED_COMMANDS = {
    "start", "help", "alerts", "birthdays",
    "tags", "status", "settings", "cancel", "manage",
}

# Compact list page size for /alerts and /birthdays lists.
LIST_PAGE_SIZE = 20

# Backup/export size limits.
USER_BACKUP_QUOTA_BYTES = 100 * 1024 * 1024
EMAIL_BACKUP_MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
TELEGRAM_EXPORT_MAX_BYTES = 45 * 1024 * 1024
IMPORT_SESSION_TTL_SECONDS = 600

# =============================================================================
# /next DISPLAY CONFIGURATION
# =============================================================================
# Priority icon threshold for /next (examples: "1 h", "3d", "4w", "1m", "5y")
# Note: "d" uses calendar-day rounding; months/years are not rounded.
NEXT_PRIORITY_THRESHOLD = "2d"

# =============================================================================
# RESILIENCE CONFIGURATION
# =============================================================================
# Telegram API retry policy
TELEGRAM_RETRY_ATTEMPTS = 3
TELEGRAM_RETRY_MAX_WINDOW_SECONDS = 15
TELEGRAM_RETRY_BASE_DELAY_SECONDS = 0.6
TELEGRAM_RETRY_MAX_DELAY_SECONDS = 4.0

# API degraded-mode thresholds over a sliding time window
API_FAILURE_WINDOW_SECONDS = 600  # 10 minutes
API_FAILURE_USER_THRESHOLD = 5
API_FAILURE_GLOBAL_THRESHOLD = 25

# Slow-path warning thresholds (explicit telemetry).
API_SLOW_CALL_THRESHOLD_MS = 2000
SCHEDULER_TICK_SLOW_THRESHOLD_MS = 1000

# Polling-network warning noise control (error_handler).
# Keep first warnings visible, then roll up repetitive noise.
POLLING_NETWORK_ERROR_WINDOW_SECONDS = 300
POLLING_NETWORK_MAX_IMMEDIATE_WARNINGS = 3
POLLING_NETWORK_ROLLUP_MIN_INTERVAL_SECONDS = 60
POLLING_NETWORK_RECOVERY_QUIET_SECONDS = 180

# Dedicated exit code for singleton lock conflicts.
# startbot.sh resolves this constant to avoid Python/shell drift.
MAINBOT_EXIT_LOCK_CONFLICT = 73

# Startup user-scope telemetry: warning when many dataset users are excluded by
# whitelist/auth filtering.
STARTUP_SCOPE_WARNING_EXCLUDED_USERS = 5
STARTUP_SCOPE_EXCLUDED_SAMPLE_SIZE = 5

# Storage safety policy
STORAGE_ENABLE_FSYNC = False  # Optional durability boost, may slow writes
STORAGE_AUTO_RECOVER_CORRUPTED_JSON = True

# =============================================================================
# USER DATA SECURITY LIMITS
# =============================================================================
# Maximum size of a single alerts.json file (bytes)
USER_ALERTS_JSON_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
# Maximum total size of a user's data folder (bytes)
USER_FOLDER_MAX_BYTES = 50 * 1024 * 1024  # 50 MB
# Maximum number of tags per user
USER_MAX_TAGS = 50
# Maximum number of alerts per user
USER_MAX_ALERTS = 500
# Free-text input length limits (code injection resilience)
TITLE_MAX_LEN = 200
ADDITIONAL_INFO_MAX_LEN = 2000
CUSTOM_NAME_MAX_LEN = 100
START_REQUEST_MAX_MESSAGE_CHARS = 500
# Import download pre-check: reject files larger than 2x user folder limit
IMPORT_DOWNLOAD_MAX_BYTES = 2 * USER_FOLDER_MAX_BYTES  # 100 MB

# =============================================================================
# USER ACTIVITY TRACKING
# =============================================================================
# Thresholds for activity indicator icons in admin user list
ACTIVITY_PURPLE_SECONDS = 60 * 10          # 10 minutes  → 🟣
ACTIVITY_GREEN_SECONDS =  60 * 60 * 6      # 6 hours     → 🟢
ACTIVITY_ORANGE_SECONDS = 60 * 60 * 24 * 1 # 1 days      → 🟠
# Anything beyond ACTIVITY_ORANGE_SECONDS (or null)      → 🔴
ACTIVITY_YELLOW_SECONDS = ACTIVITY_GREEN_SECONDS  # legacy (unused)
ACTIVITY_ICON_PURPLE = "🟣"
ACTIVITY_ICON_GREEN  = "🟢"
ACTIVITY_ICON_YELLOW = "🟡"
ACTIVITY_ICON_ORANGE = "🟠"
ACTIVITY_ICON_RED    = "🔴"

# Throttle: skip disk write if last_seen is fresher than this
ACTIVITY_WRITE_THROTTLE_SECONDS = 5 * 60  # 5 minutes
