"""Tests for the user interest model (InterestStore + MCP tools)."""

from __future__ import annotations

import json

import pytest

from arr_mcp.services.interests import ContentInterest, InterestState, InterestStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return InterestStore(services_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# InterestStore.get — default state
# ---------------------------------------------------------------------------


def test_get_returns_interested_when_no_record(store: InterestStore) -> None:
    record = store.get("ep-1", "user-a")
    assert record.state == InterestState.interested
    assert record.content_id == "ep-1"
    assert record.user_id == "user-a"


# ---------------------------------------------------------------------------
# InterestStore.set / get round-trip
# ---------------------------------------------------------------------------


def test_set_and_get_round_trip(store: InterestStore) -> None:
    store.set("ep-1", "user-a", InterestState.watched, username="Alice", content_type="episode")
    record = store.get("ep-1", "user-a")
    assert record.state == InterestState.watched
    assert record.username == "Alice"
    assert record.content_type == "episode"


def test_set_overwrites_existing_state(store: InterestStore) -> None:
    store.set("ep-1", "user-a", InterestState.watched)
    store.set("ep-1", "user-a", InterestState.marked_deletion)
    assert store.get("ep-1", "user-a").state == InterestState.marked_deletion


def test_set_returns_record(store: InterestStore) -> None:
    record = store.set("ep-1", "user-a", InterestState.interested)
    assert isinstance(record, ContentInterest)
    assert record.state == InterestState.interested


# ---------------------------------------------------------------------------
# InterestStore.get_all_for_content
# ---------------------------------------------------------------------------


def test_get_all_for_content_returns_matching(store: InterestStore) -> None:
    store.set("ep-1", "user-a", InterestState.watched)
    store.set("ep-1", "user-b", InterestState.marked_deletion)
    store.set("ep-2", "user-a", InterestState.watched)
    records = store.get_all_for_content("ep-1")
    assert len(records) == 2
    assert all(r.content_id == "ep-1" for r in records)


def test_get_all_for_content_empty_when_none(store: InterestStore) -> None:
    assert store.get_all_for_content("ep-999") == []


# ---------------------------------------------------------------------------
# InterestStore.is_deletion_eligible
# ---------------------------------------------------------------------------


def test_eligible_all_watched(store: InterestStore) -> None:
    store.set("ep-1", "user-a", InterestState.watched)
    store.set("ep-1", "user-b", InterestState.watched)
    assert store.is_deletion_eligible("ep-1", ["user-a", "user-b"]) is True


def test_eligible_all_marked_deletion(store: InterestStore) -> None:
    store.set("ep-1", "user-a", InterestState.marked_deletion)
    store.set("ep-1", "user-b", InterestState.marked_deletion)
    assert store.is_deletion_eligible("ep-1", ["user-a", "user-b"]) is True


def test_eligible_mixed_watched_and_marked(store: InterestStore) -> None:
    store.set("ep-1", "user-a", InterestState.watched)
    store.set("ep-1", "user-b", InterestState.marked_deletion)
    assert store.is_deletion_eligible("ep-1", ["user-a", "user-b"]) is True


def test_not_eligible_one_interested(store: InterestStore) -> None:
    store.set("ep-1", "user-a", InterestState.watched)
    store.set("ep-1", "user-b", InterestState.interested)
    assert store.is_deletion_eligible("ep-1", ["user-a", "user-b"]) is False


def test_not_eligible_missing_user_defaults_to_interested(store: InterestStore) -> None:
    store.set("ep-1", "user-a", InterestState.watched)
    # user-b has no record — defaults to interested
    assert store.is_deletion_eligible("ep-1", ["user-a", "user-b"]) is False


def test_not_eligible_empty_user_list(store: InterestStore) -> None:
    assert store.is_deletion_eligible("ep-1", []) is False


# ---------------------------------------------------------------------------
# InterestStore.get_eligible_for_deletion
# ---------------------------------------------------------------------------


def test_get_eligible_returns_all_non_interested(store: InterestStore) -> None:
    store.set("ep-1", "user-a", InterestState.watched)
    store.set("ep-1", "user-b", InterestState.marked_deletion)
    store.set("ep-2", "user-a", InterestState.interested)
    eligible = store.get_eligible_for_deletion()
    assert "ep-1" in eligible
    assert "ep-2" not in eligible


def test_get_eligible_empty_when_no_records(store: InterestStore) -> None:
    assert store.get_eligible_for_deletion() == []


# ---------------------------------------------------------------------------
# InterestStore.get_pending_review
# ---------------------------------------------------------------------------


def test_pending_review_mixed_states(store: InterestStore) -> None:
    store.set("ep-1", "user-a", InterestState.marked_deletion)
    store.set("ep-1", "user-b", InterestState.interested)
    assert "ep-1" in store.get_pending_review()


def test_not_pending_all_marked_deletion(store: InterestStore) -> None:
    store.set("ep-1", "user-a", InterestState.marked_deletion)
    store.set("ep-1", "user-b", InterestState.marked_deletion)
    assert "ep-1" not in store.get_pending_review()


def test_not_pending_only_interested(store: InterestStore) -> None:
    store.set("ep-1", "user-a", InterestState.interested)
    assert "ep-1" not in store.get_pending_review()


# ---------------------------------------------------------------------------
# InterestStore.sync_watched
# ---------------------------------------------------------------------------


def test_sync_watched_sets_watched(store: InterestStore) -> None:
    store.sync_watched("ep-1", "user-a", "Alice", "episode")
    assert store.get("ep-1", "user-a").state == InterestState.watched


def test_sync_watched_does_not_overwrite_marked_deletion(store: InterestStore) -> None:
    store.set("ep-1", "user-a", InterestState.marked_deletion)
    store.sync_watched("ep-1", "user-a", "Alice", "episode")
    assert store.get("ep-1", "user-a").state == InterestState.marked_deletion


def test_sync_watched_preserves_explicit_interested(store: InterestStore) -> None:
    # Explicit 'interested' protection must survive watch-history sync.
    store.set("ep-1", "user-a", InterestState.interested)
    store.sync_watched("ep-1", "user-a", "Alice", "episode")
    assert store.get("ep-1", "user-a").state == InterestState.interested


# ---------------------------------------------------------------------------
# InterestStore.get_all
# ---------------------------------------------------------------------------


def test_get_all_returns_all_records(store: InterestStore) -> None:
    store.set("ep-1", "user-a", InterestState.watched)
    store.set("ep-2", "user-b", InterestState.interested)
    records = store.get_all()
    assert len(records) == 2


# ---------------------------------------------------------------------------
# Persistence across store instances
# ---------------------------------------------------------------------------


def test_persists_across_instances(tmp_path) -> None:
    store1 = InterestStore(services_dir=str(tmp_path))
    store1.set("ep-1", "user-a", InterestState.marked_deletion, username="Alice")
    store2 = InterestStore(services_dir=str(tmp_path))
    record = store2.get("ep-1", "user-a")
    assert record.state == InterestState.marked_deletion
    assert record.username == "Alice"


# ---------------------------------------------------------------------------
# MCP tool integration
# ---------------------------------------------------------------------------


async def test_interest_set_tool_valid_state(tmp_path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.interests import register_interest_tools

    mcp = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))
    register_interest_tools(mcp, settings)

    result = await mcp.call_tool(
        "interest_set",
        {
            "content_id": "ep-42",
            "user_id": "user-x",
            "state": "watched",
            "username": "Xavier",
            "content_type": "episode",
        },
    )
    payload = json.loads(result[0][0].text)
    assert payload["state"] == "watched"
    assert payload["content_id"] == "ep-42"


async def test_interest_set_tool_invalid_state(tmp_path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.interests import register_interest_tools

    mcp = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))
    register_interest_tools(mcp, settings)

    result = await mcp.call_tool(
        "interest_set",
        {"content_id": "ep-42", "user_id": "user-x", "state": "invalid"},
    )
    assert "Invalid state" in result[0][0].text


async def test_interest_list_tool_all(tmp_path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.interests import register_interest_tools

    mcp = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))
    register_interest_tools(mcp, settings)

    store = InterestStore(services_dir=str(tmp_path))
    store.set("ep-1", "user-a", InterestState.watched)
    store.set("ep-2", "user-b", InterestState.interested)

    result = await mcp.call_tool("interest_list", {})
    payload = json.loads(result[0][0].text)
    assert payload["count"] == 2


async def test_interest_pending_review_tool(tmp_path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.interests import register_interest_tools

    mcp = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))
    register_interest_tools(mcp, settings)

    store = InterestStore(services_dir=str(tmp_path))
    store.set("ep-1", "user-a", InterestState.marked_deletion)
    store.set("ep-1", "user-b", InterestState.interested)

    result = await mcp.call_tool("interest_pending_review", {})
    payload = json.loads(result[0][0].text)
    assert payload["pending_count"] == 1
    assert payload["candidates"][0]["content_id"] == "ep-1"


async def test_interest_pending_review_empty(tmp_path) -> None:
    from mcp.server.fastmcp import FastMCP

    from arr_mcp.config import Settings
    from arr_mcp.tools.interests import register_interest_tools

    mcp = FastMCP("test")
    settings = Settings(services_dir=str(tmp_path))
    register_interest_tools(mcp, settings)

    result = await mcp.call_tool("interest_pending_review", {})
    assert "No content pending" in result[0][0].text
