"""User interest model — per-user content interest state for deletion eligibility."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

log = logging.getLogger(__name__)

_INTERESTS_FILE = ".arr-mcp-interests.json"


class InterestState(StrEnum):
    """Three-state interest model for a piece of content."""

    interested = "interested"
    watched = "watched"
    marked_deletion = "marked_deletion"


@dataclass
class ContentInterest:
    """A single user's interest state for a piece of content."""

    content_id: str
    content_type: str  # "episode" | "movie"
    user_id: str
    username: str
    state: InterestState
    updated_at: str  # ISO 8601


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _record_key(content_id: str, user_id: str) -> str:
    return f"{content_id}:{user_id}"


class InterestStore:
    """Persisted per-user content interest states.

    Storage: JSON file at ``{services_dir}/.arr-mcp-interests.json``.
    Keys are ``content_id:user_id``; values are serialized ``ContentInterest``
    dicts.

    The default state for any user who has no record is ``interested`` —
    unset interest is always protective.
    """

    def __init__(self, services_dir: str) -> None:
        self._path = Path(services_dir) / _INTERESTS_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, content_id: str, user_id: str) -> ContentInterest:
        """Return the interest record for a user/content pair.

        Returns a synthetic ``interested`` record when none exists — the
        default is always protective.
        """
        data = self._read()
        key = _record_key(content_id, user_id)
        record = data.get(key)
        if record is None:
            return ContentInterest(
                content_id=content_id,
                content_type="unknown",
                user_id=user_id,
                username=user_id,
                state=InterestState.interested,
                updated_at=_now_iso(),
            )
        return _from_dict(record)

    def set(
        self,
        content_id: str,
        user_id: str,
        state: InterestState,
        *,
        username: str = "",
        content_type: str = "unknown",
    ) -> ContentInterest:
        """Persist a user's interest state for a piece of content.

        Watch history sync uses this to set ``watched`` without overwriting
        ``marked_deletion`` — callers that want to preserve an existing state
        should check first via ``get()``.
        """
        data = self._read()
        key = _record_key(content_id, user_id)
        record = ContentInterest(
            content_id=content_id,
            content_type=content_type,
            user_id=user_id,
            username=username or user_id,
            state=state,
            updated_at=_now_iso(),
        )
        data[key] = asdict(record)
        data[key]["state"] = state.value
        self._write(data)
        return record

    def get_all_for_content(self, content_id: str) -> list[ContentInterest]:
        """Return all interest records for a given content ID."""
        data = self._read()
        return [
            _from_dict(v) for k, v in data.items() if v.get("content_id") == content_id
        ]

    def is_deletion_eligible(self, content_id: str, all_user_ids: list[str]) -> bool:
        """Return True when no user has ``interested`` state for *content_id*.

        Any user not present in the store defaults to ``interested`` — so
        content is only eligible when every user in *all_user_ids* has an
        explicit non-interested record.  Returns False if *all_user_ids* is
        empty.
        """
        if not all_user_ids:
            return False
        data = self._read()
        for user_id in all_user_ids:
            key = _record_key(content_id, user_id)
            record = data.get(key)
            if record is None:
                return False  # unset → interested → protected
            if record.get("state") == InterestState.interested.value:
                return False
        return True

    def get_eligible_for_deletion(self) -> list[str]:
        """Return content IDs where all stored records are non-interested.

        Only considers users who have an explicit record — use
        ``is_deletion_eligible(content_id, all_user_ids)`` for a complete
        check against a known user list.
        """
        data = self._read()
        by_content: dict[str, list[str]] = {}
        for record in data.values():
            cid = record["content_id"]
            by_content.setdefault(cid, []).append(record["state"])

        return [
            cid
            for cid, states in by_content.items()
            if states and all(s != InterestState.interested.value for s in states)
        ]

    def get_pending_review(self) -> list[str]:
        """Return content IDs with mixed states (some marked_deletion, some interested).

        These are candidates for admin review: someone wants to delete but
        at least one other user is still ``interested``.
        """
        data = self._read()
        by_content: dict[str, list[str]] = {}
        for record in data.values():
            cid = record["content_id"]
            by_content.setdefault(cid, []).append(record["state"])

        return [
            cid
            for cid, states in by_content.items()
            if InterestState.marked_deletion.value in states
            and InterestState.interested.value in states
        ]

    def get_all(self) -> list[ContentInterest]:
        """Return all interest records."""
        return [_from_dict(v) for v in self._read().values()]

    def sync_watched(
        self,
        content_id: str,
        user_id: str,
        username: str,
        content_type: str,
    ) -> None:
        """Seed ``watched`` state on first encounter.

        Never overwrites an existing record.

        Safe to call from watch-history sync — if the user has any prior
        explicit record (``interested``, ``watched``, or ``marked_deletion``),
        their state is left unchanged.
        """
        data = self._read()
        key = _record_key(content_id, user_id)
        if key in data:
            return
        self.set(
            content_id,
            user_id,
            InterestState.watched,
            username=username,
            content_type=content_type,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read(self) -> dict[str, dict[str, str]]:
        if not self._path.exists():
            return {}
        try:
            raw = self._path.read_text()
            if not raw.strip():
                return {}
            loaded: dict[str, dict[str, str]] = json.loads(raw)
            return loaded
        except Exception:
            log.warning("Failed to read interest store at %s", self._path)
            return {}

    def _write(self, data: dict[str, dict[str, str]]) -> None:
        try:
            self._path.write_text(json.dumps(data, indent=2))
        except Exception:
            log.error("Failed to write interest store at %s", self._path)


def _from_dict(record: dict[str, str]) -> ContentInterest:
    return ContentInterest(
        content_id=record["content_id"],
        content_type=record.get("content_type", "unknown"),
        user_id=record["user_id"],
        username=record.get("username", record["user_id"]),
        state=InterestState(record["state"]),
        updated_at=record.get("updated_at", ""),
    )
