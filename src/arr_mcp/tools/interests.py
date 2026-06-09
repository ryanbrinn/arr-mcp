"""MCP tools for per-user content interest state management."""

from __future__ import annotations

import json
from dataclasses import asdict

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from arr_mcp.config import Settings
from arr_mcp.services.interests import InterestState, InterestStore


def register_interest_tools(server: FastMCP, settings: Settings) -> None:
    """Register interest state management tools with the MCP server."""
    store = InterestStore(settings.services_dir)

    @server.tool()
    async def interest_set(
        content_id: str,
        user_id: str,
        state: str,
        username: str = "",
        content_type: str = "unknown",
    ) -> list[TextContent]:
        """Set a user's interest state for a piece of content.

        States:
        - interested: default — protects content from deletion
        - watched: user has seen it; does not block deletion on its own
        - marked_deletion: user explicitly approves removal

        Args:
            content_id: Sonarr episode_file_id or Radarr movie_file_id.
            user_id: Plex user ID of the user whose state to set.
            state: One of: interested, watched, marked_deletion.
            username: Display name for the user (optional).
            content_type: "episode" or "movie" (optional, for display).
        """
        try:
            interest = InterestState(state)
        except ValueError:
            valid = [s.value for s in InterestState]
            return [
                TextContent(
                    type="text",
                    text=f"Invalid state {state!r}. Valid values: {', '.join(valid)}",
                )
            ]

        record = store.set(
            content_id,
            user_id,
            interest,
            username=username,
            content_type=content_type,
        )
        result = {
            "content_id": record.content_id,
            "user_id": record.user_id,
            "username": record.username,
            "state": record.state.value,
            "updated_at": record.updated_at,
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    @server.tool()
    async def interest_list(
        filter: str = "",
        content_id: str = "",
    ) -> list[TextContent]:
        """List content interest states.

        Args:
            filter: Optional state filter — one of: interested, watched,
                    marked_deletion, eligible. Leave empty for all records.
            content_id: If set, show only records for this content ID.
        """
        if content_id:
            records = store.get_all_for_content(content_id)
        else:
            records = store.get_all()

        if filter:
            if filter == "eligible":
                eligible_ids = set(store.get_eligible_for_deletion())
                records = [r for r in records if r.content_id in eligible_ids]
            else:
                try:
                    state_filter = InterestState(filter)
                    records = [r for r in records if r.state == state_filter]
                except ValueError:
                    valid = [s.value for s in InterestState] + ["eligible"]
                    return [
                        TextContent(
                            type="text",
                            text=(
                                f"Invalid filter {filter!r}."
                                f" Valid values: {', '.join(valid)}"
                            ),
                        )
                    ]

        if not records:
            return [TextContent(type="text", text="No interest records found.")]

        result = {
            "count": len(records),
            "records": [
                {**asdict(r), "state": r.state.value}
                for r in sorted(records, key=lambda x: (x.content_id, x.user_id))
            ],
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    @server.tool()
    async def interest_pending_review() -> list[TextContent]:
        """List content with mixed interest states that requires admin review.

        Returns content where at least one user has marked_deletion and at
        least one other user still has interested state. These are candidates
        for admin override — the admin can approve deletion, dismiss (keep),
        or update the interested user's state on their behalf.
        """
        pending_ids = store.get_pending_review()
        if not pending_ids:
            return [TextContent(type="text", text="No content pending admin review.")]

        candidates = []
        for cid in pending_ids:
            records = store.get_all_for_content(cid)
            candidates.append(
                {
                    "content_id": cid,
                    "records": [
                        {
                            "user_id": r.user_id,
                            "username": r.username,
                            "state": r.state.value,
                            "updated_at": r.updated_at,
                            "content_type": r.content_type,
                        }
                        for r in records
                    ],
                }
            )

        result = {
            "pending_count": len(candidates),
            "candidates": candidates,
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
