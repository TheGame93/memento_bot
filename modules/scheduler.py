"""
scheduler.py - THE COORDINATOR

Orchestrates the alert scheduling system.
- Initializes and manages APScheduler
- Loads alerts from storage on startup
- Checks for due alerts on each tick
- Handles missed alerts recovery
- Bridges mathlogic and messagelogic
"""

from modules.scheduler_core import coordinator as _coordinator
from modules.scheduler_core.coordinator import (
    scheduler,
    start_scheduler,
    stop_scheduler,
    load_all_alerts,
    queue_single_alert,
    remove_alert_from_queue,
    check_due_alerts,
    check_pre_alerts,
)
from modules.scheduler_core.actions import (
    trigger_alert as _trigger_alert,
    snooze_alert as _snooze_alert,
    mark_alert_done as _mark_alert_done,
)
from modules.scheduler_core.missed import handle_missed_alerts as _handle_missed_alerts
from modules.scheduler_core import state as scheduler_state
from modules.scheduler_messagelogic import send_missed_alerts_batch


_storage = None
_app = None


def init_scheduler(app, storage):
    """Initialize scheduler globals and delegate startup wiring to coordinator."""
    global _app, _storage
    _app = app
    _storage = storage
    return _coordinator.init_scheduler(app, storage)


async def trigger_alert(
    bot,
    user_id,
    alert,
    alert_type,
    missed_time=None,
    scheduled_time=None,
    clear_snooze=False,
    postpone_count=0,
    postpone_id=None,
    effective_fire_time=None,
):
    """Delegate alert triggering through the shared storage bridge state."""
    return await _trigger_alert(
        bot,
        user_id,
        alert,
        alert_type,
        _storage or _coordinator.get_storage(),
        scheduler_state.sent_pre_alerts,
        missed_time=missed_time,
        scheduled_time=scheduled_time,
        clear_snooze=clear_snooze,
        postpone_count=postpone_count,
        postpone_id=postpone_id,
        effective_fire_time=effective_fire_time,
    )


async def snooze_alert(user_id, alert_id, snooze_duration, storage=None):
    """Delegate snooze handling using caller-provided or coordinator-fallback storage."""
    resolved_storage = storage or _storage or _coordinator.get_storage()
    return await _snooze_alert(user_id, alert_id, snooze_duration, resolved_storage)


async def mark_alert_done(user_id, alert_id, storage=None):
    """Delegate completion handling using caller-provided or coordinator-fallback storage."""
    resolved_storage = storage or _storage or _coordinator.get_storage()
    return await _mark_alert_done(user_id, alert_id, resolved_storage)


async def handle_missed_alerts():
    """Send startup missed-alert summaries when app and storage are available."""
    storage = _storage or _coordinator.get_storage()
    app = _app or _coordinator.get_app()
    if not storage or not app:
        return
    await _handle_missed_alerts(app.bot, storage, send_missed_func=send_missed_alerts_batch)


def __getattr__(name):
    if name == "_storage":
        return _storage if _storage is not None else _coordinator.get_storage()
    if name == "_app":
        return _app if _app is not None else _coordinator.get_app()
    if name == "_sent_pre_alerts":
        return scheduler_state.sent_pre_alerts
    if name == "_last_tick_time":
        return scheduler_state.last_tick_time
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
