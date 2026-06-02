"""User tag storage mutations."""

from typing import TYPE_CHECKING

from modules import constants as C
from modules.shared.logging_utils import hash_text
from modules.tags_logic import extract_tag_name

if TYPE_CHECKING:
    from modules.storage import StorageManager


class TagService:
    """Manage tag add/delete/rename mutations in user storage payloads."""

    def __init__(self, store: "StorageManager"):
        self._store = store

    def add_user_tag(self, user_id, tag_name):
        """
        Adds a new tag to the user's master list.
        Returns: (success: bool, error_reason: str or None)

        Checks for:
        - Exact duplicate (same emoji + name)
        - Name duplicate (different emoji, same name)
        """
        def _mutator(data):
            tags = data.get("tags")
            if not isinstance(tags, list):
                tags = list(C.TAGS)
                data["tags"] = tags

            max_tags = getattr(C, "USER_MAX_TAGS", 0)
            if max_tags > 0 and len(tags) >= max_tags:
                return False, f"limit_reached:You have reached the maximum of {max_tags} tags. Delete some tags first."

            if tag_name in tags:
                return False, "exact_duplicate"

            new_tag_name = extract_tag_name(tag_name)
            for existing_tag in tags:
                existing_name = extract_tag_name(existing_tag)
                if new_tag_name == existing_name:
                    return False, f"name_duplicate:{existing_tag}"

            tags.append(tag_name)
            tags.sort(key=extract_tag_name)
            return True, None

        ok, reason = self._store._mutate_user_data(user_id, _mutator, ensure_space=True)
        if not ok:
            return False, "storage_unavailable"
        if reason:
            return False, reason
        self._store.log_user_event(user_id, "tag_added", {
            "tag_len": len(tag_name),
            "tag_hash": hash_text(tag_name),
        })
        return True, None

    def delete_user_tag(self, user_id, tag_to_del):
        """Removes a tag from the master list and all alerts."""
        def _mutator(data):
            tags = data.get("tags")
            if not isinstance(tags, list) or tag_to_del not in tags:
                return False, False

            tags.remove(tag_to_del)

            for alert in data.get("alerts", []):
                if tag_to_del in alert.get("tags", []):
                    alert["tags"].remove(tag_to_del)
            return True, True

        ok, changed = self._store._mutate_user_data(user_id, _mutator, ensure_space=True)
        if not ok:
            return False
        if changed:
            self._store.log_user_event(user_id, "tag_deleted", {
                "tag_len": len(tag_to_del),
                "tag_hash": hash_text(tag_to_del),
            })
        return bool(changed)

    def rename_user_tag(self, user_id, old_tag, new_tag):
        """
        Rename old_tag to new_tag in the master list and propagate to every alert that carries it.

        Returns (success: bool, error_reason: str | None).
        error_reason values: 'not_found', 'same_tag', 'exact_duplicate',
        'name_duplicate:<existing_tag>', 'storage_unavailable'.
        Tag order within each alert's tags list is preserved.
        """
        def _mutator(data):
            tags = data.get("tags")
            if not isinstance(tags, list) or old_tag not in tags:
                return False, "not_found"

            if new_tag == old_tag:
                return False, "same_tag"

            if new_tag in tags:
                return False, "exact_duplicate"

            new_name = extract_tag_name(new_tag)
            for t in tags:
                if t == old_tag:
                    continue
                if extract_tag_name(t) == new_name:
                    return False, f"name_duplicate:{t}"

            tags[tags.index(old_tag)] = new_tag
            tags.sort(key=extract_tag_name)

            for alert in data.get("alerts", []):
                alert_tags = alert.get("tags", [])
                for i, t in enumerate(alert_tags):
                    if t == old_tag:
                        alert_tags[i] = new_tag
            return True, None

        ok, reason = self._store._mutate_user_data(user_id, _mutator, ensure_space=True)
        if not ok:
            return False, "storage_unavailable"
        if reason:
            return False, reason
        self._store.log_user_event(user_id, "tag_renamed", {
            "old_tag_len": len(old_tag),
            "old_tag_hash": hash_text(old_tag),
            "new_tag_len": len(new_tag),
            "new_tag_hash": hash_text(new_tag),
        })
        return True, None
