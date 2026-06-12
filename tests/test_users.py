"""Tests for AppUser identity model and UserStore."""

from __future__ import annotations

import stat
import sys

from arr_mcp.services.users import UserStore


def test_has_any_empty(tmp_path):
    store = UserStore(str(tmp_path))
    assert store.has_any() is False


def test_create_local_and_find(tmp_path):
    store = UserStore(str(tmp_path))
    user = store.create_local("alice", "password123", is_admin=True)
    assert user is not None
    assert user.display_name == "alice"
    assert user.is_admin is True
    assert store.has_any() is True

    found = store.find_by_username("alice")
    assert found is not None
    assert found.app_user_id == user.app_user_id


def test_create_local_case_insensitive_lookup(tmp_path):
    store = UserStore(str(tmp_path))
    store.create_local("Alice", "password123")
    assert store.find_by_username("alice") is not None
    assert store.find_by_username("ALICE") is not None


def test_create_local_duplicate_returns_none(tmp_path):
    store = UserStore(str(tmp_path))
    store.create_local("alice", "password123")
    dup = store.create_local("alice", "otherpassword")
    assert dup is None


def test_verify_password(tmp_path):
    store = UserStore(str(tmp_path))
    user = store.create_local("alice", "password123")
    assert user is not None
    assert store.verify_password(user.app_user_id, "password123") is True
    assert store.verify_password(user.app_user_id, "wrongpassword") is False


def test_verify_password_unknown_user(tmp_path):
    store = UserStore(str(tmp_path))
    assert store.verify_password("nonexistent", "password123") is False


def test_create_linked_and_find_by_linked_identity(tmp_path):
    store = UserStore(str(tmp_path))
    user = store.create_linked(
        "plex", "12345", "bob", is_admin=False, avatar_url="https://img"
    )
    assert user.linked_identities == {"plex": "12345"}
    assert user.avatar_url == "https://img"

    found = store.find_by_linked_identity("plex", "12345")
    assert found is not None
    assert found.app_user_id == user.app_user_id

    assert store.find_by_linked_identity("plex", "99999") is None
    assert store.find_by_linked_identity("jellyfin", "12345") is None


def test_link_identity(tmp_path):
    store = UserStore(str(tmp_path))
    user = store.create_local("alice", "password123")
    assert user is not None

    store.link_identity(user.app_user_id, "plex", "777")

    found = store.find_by_linked_identity("plex", "777")
    assert found is not None
    assert found.app_user_id == user.app_user_id


def test_link_identity_unknown_user_is_noop(tmp_path):
    store = UserStore(str(tmp_path))
    store.link_identity("nonexistent", "plex", "777")
    assert store.find_by_linked_identity("plex", "777") is None


def test_update_profile(tmp_path):
    store = UserStore(str(tmp_path))
    user = store.create_linked("plex", "1", "bob", is_admin=False)

    store.update_profile(
        user.app_user_id,
        display_name="bobby",
        avatar_url="https://new-avatar",
        is_admin=True,
    )

    updated = store.get(user.app_user_id)
    assert updated is not None
    assert updated.display_name == "bobby"
    assert updated.avatar_url == "https://new-avatar"
    assert updated.is_admin is True


def test_get_unknown_returns_none(tmp_path):
    store = UserStore(str(tmp_path))
    assert store.get("nonexistent") is None


def test_persistence_across_instances(tmp_path):
    store1 = UserStore(str(tmp_path))
    user = store1.create_local("alice", "password123", is_admin=True)
    assert user is not None

    store2 = UserStore(str(tmp_path))
    found = store2.find_by_username("alice")
    assert found is not None
    assert found.app_user_id == user.app_user_id
    assert found.is_admin is True


def test_password_hash_and_salt_not_none_for_local(tmp_path):
    store = UserStore(str(tmp_path))
    user = store.create_local("alice", "password123")
    assert user is not None
    assert user.password_hash is not None
    assert user.salt is not None


def test_linked_user_has_no_password(tmp_path):
    store = UserStore(str(tmp_path))
    user = store.create_linked("plex", "1", "bob")
    assert user.password_hash is None
    assert user.salt is None


def test_user_file_permissions(tmp_path):
    if sys.platform == "win32":
        return
    store = UserStore(str(tmp_path))
    store.create_local("alice", "password123")
    path = tmp_path / ".arr-mcp-users.json"
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
