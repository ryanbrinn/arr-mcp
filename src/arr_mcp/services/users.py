"""Internal application user identity — AppUser store with linked providers."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

_USERS_FILE = ".arr-mcp-users.json"
_PBKDF2_ITERATIONS = 260_000


@dataclass
class AppUser:
    """An internal application user, optionally linked to provider identities."""

    app_user_id: str
    display_name: str
    is_admin: bool = False
    avatar_url: str | None = None
    password_hash: str | None = None
    salt: str | None = None
    linked_identities: dict[str, str] = field(default_factory=dict)
    created_at: str = ""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS
    ).hex()


class UserStore:
    """Persisted application user identities with linked provider accounts.

    Storage: JSON file at ``{services_dir}/.arr-mcp-users.json``, keyed by
    ``app_user_id`` (uuid4).
    """

    def __init__(self, services_dir: str) -> None:
        self._path = Path(services_dir) / _USERS_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def has_any(self) -> bool:
        """Return True if at least one AppUser exists."""
        return len(self._read()) > 0

    def get(self, app_user_id: str) -> AppUser | None:
        """Return the AppUser with the given id, or None if not found."""
        record = self._read().get(app_user_id)
        if record is None:
            return None
        return _from_dict(record)

    def find_by_linked_identity(
        self, provider: str, provider_id: str
    ) -> AppUser | None:
        """Return the AppUser linked to a given provider identity, if any."""
        for record in self._read().values():
            if record.get("linked_identities", {}).get(provider) == provider_id:
                return _from_dict(record)
        return None

    def find_by_username(self, display_name: str) -> AppUser | None:
        """Return the AppUser with a matching display name (case-insensitive)."""
        target = display_name.lower()
        for record in self._read().values():
            if record.get("display_name", "").lower() == target:
                return _from_dict(record)
        return None

    def create_local(
        self, display_name: str, password: str, *, is_admin: bool = False
    ) -> AppUser | None:
        """Create a new AppUser with a local password.

        Returns None if an AppUser with this display name already exists.
        """
        if self.find_by_username(display_name) is not None:
            return None
        salt = secrets.token_hex(16)
        user = AppUser(
            app_user_id=str(uuid.uuid4()),
            display_name=display_name,
            is_admin=is_admin,
            password_hash=_hash_password(password, salt),
            salt=salt,
            created_at=_now_iso(),
        )
        self._save(user)
        return user

    def create_linked(
        self,
        provider: str,
        provider_id: str,
        display_name: str,
        *,
        is_admin: bool = False,
        avatar_url: str | None = None,
    ) -> AppUser:
        """Create a new AppUser linked to an external provider identity."""
        user = AppUser(
            app_user_id=str(uuid.uuid4()),
            display_name=display_name,
            is_admin=is_admin,
            avatar_url=avatar_url,
            linked_identities={provider: provider_id},
            created_at=_now_iso(),
        )
        self._save(user)
        return user

    def verify_password(self, app_user_id: str, password: str) -> bool:
        """Check a password against the stored hash for an AppUser."""
        user = self.get(app_user_id)
        if user is None or user.password_hash is None or user.salt is None:
            return False
        return _hash_password(password, user.salt) == user.password_hash

    def link_identity(self, app_user_id: str, provider: str, provider_id: str) -> None:
        """Link an external provider identity to an existing AppUser."""
        data = self._read()
        record = data.get(app_user_id)
        if record is None:
            return
        record.setdefault("linked_identities", {})[provider] = provider_id
        self._write(data)

    def update_profile(
        self,
        app_user_id: str,
        *,
        display_name: str | None = None,
        avatar_url: str | None = None,
        is_admin: bool | None = None,
    ) -> None:
        """Refresh profile fields for an AppUser (e.g. from provider login)."""
        data = self._read()
        record = data.get(app_user_id)
        if record is None:
            return
        if display_name is not None:
            record["display_name"] = display_name
        if avatar_url is not None:
            record["avatar_url"] = avatar_url
        if is_admin is not None:
            record["is_admin"] = is_admin
        self._write(data)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _save(self, user: AppUser) -> None:
        data = self._read()
        data[user.app_user_id] = asdict(user)
        self._write(data)

    def _read(self) -> dict[str, dict]:  # type: ignore[type-arg]
        if not self._path.exists():
            return {}
        try:
            raw = self._path.read_text()
            if not raw.strip():
                return {}
            loaded: dict[str, dict] = json.loads(raw)  # type: ignore[type-arg]
            return loaded
        except Exception:
            log.warning("Failed to read user store at %s", self._path)
            return {}

    def _write(self, data: dict[str, dict]) -> None:  # type: ignore[type-arg]
        try:
            self._path.write_text(json.dumps(data, indent=2))
            self._path.chmod(0o600)
        except OSError:
            log.error("Failed to write user store at %s", self._path)


def _from_dict(record: dict) -> AppUser:  # type: ignore[type-arg]
    return AppUser(
        app_user_id=record["app_user_id"],
        display_name=record.get("display_name", ""),
        is_admin=record.get("is_admin", False),
        avatar_url=record.get("avatar_url"),
        password_hash=record.get("password_hash"),
        salt=record.get("salt"),
        linked_identities=record.get("linked_identities", {}),
        created_at=record.get("created_at", ""),
    )
