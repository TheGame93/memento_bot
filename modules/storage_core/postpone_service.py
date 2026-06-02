"""Postpone queue storage mutations."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.storage import StorageManager


class PostponeService:
    """Manage postpone queue add/update/remove/cleanup/expire mutations."""

    def __init__(self, store: "StorageManager"):
        self._store = store

    def add_postpone_instance(self, user_id, instance):
        """Append a postpone instance and emit the corresponding user event."""
        def _mutator(data):
            queue = data.get("postpone_queue")
            if not isinstance(queue, list):
                queue = []
                data["postpone_queue"] = queue
            queue.append(instance)
            return True, True

        ok, _ = self._store._mutate_user_data(user_id, _mutator, ensure_space=True)
        if not ok:
            return
        self._store.log_user_event(user_id, "postpone_created", {
            "postpone_id": instance.get("id"),
            "alert_id": instance.get("alert_id"),
            "kind": instance.get("kind"),
            "fire_at": instance.get("fire_at"),
            "original_time": instance.get("original_time"),
        })

    def update_postpone_instance(self, user_id, instance_id, updates):
        """Update one postpone instance and report whether it was found."""
        def _mutator(data):
            queue = data.get("postpone_queue")
            if not isinstance(queue, list):
                return False, False

            for item in queue:
                if item.get("id") == instance_id:
                    item.update(updates or {})
                    return True, True
            return False, False

        ok, updated = self._store._mutate_user_data(user_id, _mutator, ensure_space=True)
        if not ok:
            return False
        return bool(updated)

    def remove_postpone_instance(self, user_id, instance_id):
        """Remove one postpone instance and report whether removal occurred."""
        def _mutator(data):
            queue = data.get("postpone_queue")
            if not isinstance(queue, list):
                return False, False
            original_len = len(queue)
            data["postpone_queue"] = [p for p in queue if p.get("id") != instance_id]
            removed = len(data["postpone_queue"]) < original_len
            return removed, removed

        ok, removed = self._store._mutate_user_data(user_id, _mutator, ensure_space=True)
        if not ok:
            return False
        return bool(removed)

    def cleanup_postpone_queue(self, user_id, now_iso=None):
        """
        Removes any postpone instances that are not pending.
        Returns count of removed items.
        """
        def _mutator(data):
            queue = data.get("postpone_queue")
            if not isinstance(queue, list):
                return False, 0
            before = len(queue)
            data["postpone_queue"] = [
                p for p in queue
                if p.get("status") == "pending"
            ]
            removed = before - len(data["postpone_queue"])
            return removed > 0, removed

        ok, removed = self._store._mutate_user_data(user_id, _mutator, ensure_space=True)
        if not ok:
            return 0
        if removed:
            self._store.log_user_event(user_id, "postpone_cleanup", {
                "removed": removed,
                "at": now_iso,
            })
        return removed

    def expire_pending_postpones_for_alert(self, user_id, alert_id):
        """
        Marks pending postpone items for a given alert as expired.

        Returns count of items transitioned from pending -> expired.
        """
        target_alert_id = str(alert_id)

        def _mutator(data):
            queue = data.get("postpone_queue")
            if not isinstance(queue, list):
                return False, 0

            expired_count = 0
            for item in queue:
                if not isinstance(item, dict):
                    continue
                if str(item.get("alert_id")) != target_alert_id:
                    continue
                if item.get("status") != "pending":
                    continue
                item["status"] = "expired"
                item["reason"] = "alert_edited"
                expired_count += 1
            return expired_count > 0, expired_count

        ok, expired_count = self._store._mutate_user_data(user_id, _mutator, ensure_space=True)
        if not ok:
            return 0

        count = int(expired_count or 0)
        self._store.log_user_event(user_id, "postpone_expired_bulk", {
            "alert_id": target_alert_id,
            "count": count,
        })
        return count
