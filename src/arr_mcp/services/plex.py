"""PlexClient — Plex Media Server watch-history API."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import cast

import anyio
import httpx

from arr_mcp.services.base import ApiResult, BaseServiceClient

log = logging.getLogger(__name__)

_PLEX_TV_USERS_URL = "https://plex.tv/api/v2/home/users"
_PLEX_TV_SWITCH_URL = "https://plex.tv/api/home/users/{user_id}/switch"


@dataclass
class PlexUser:
    """A Plex home user with their own watch state token."""

    id: str
    username: str
    title: str
    token: str


@dataclass
class PlexEpisode:
    """A watched episode from Plex."""

    rating_key: str
    series_title: str
    season_number: int
    episode_number: int
    title: str
    watched_by: list[str] = field(default_factory=list)


@dataclass
class PlexMovie:
    """A watched movie from Plex."""

    rating_key: str
    title: str
    year: int
    watched_by: list[str] = field(default_factory=list)


class PlexClient(BaseServiceClient):
    """HTTP client for Plex Media Server.

    Uses ``X-Plex-Token`` for authentication. The main token is used for
    server-level calls and for fetching the user list from plex.tv.
    Per-user tokens are used for watch history queries.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(base_url, token, http=http)
        self._auth_header = "X-Plex-Token"

    def _health_path(self) -> str:
        return "/"

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------

    async def get_home_users(self) -> ApiResult:
        """Fetch the list of Plex home users with their watch-history tokens.

        Calls plex.tv/api/v2/home/users to enumerate home users, then
        switches into each one via plex.tv/api/home/users/{id}/switch to
        obtain a per-user access token — the home users endpoint does not
        return one directly. When the server is unclaimed or plex.tv is
        unreachable, falls back to a synthetic single-user list containing
        only the server owner (main token).
        """
        url = _PLEX_TV_USERS_URL
        headers = {
            "X-Plex-Token": self._api_key,
            "Accept": "application/json",
            "X-Plex-Client-Identifier": "arr-mcp",
        }

        async def _fetch(client: httpx.AsyncClient) -> ApiResult:
            try:
                resp = await client.get(url, headers=headers, timeout=10.0)
                if resp.is_success:
                    payload = resp.json()
                    users = _parse_home_users(payload)
                    await self._resolve_user_tokens(client, users)
                    return ApiResult(ok=True, status_code=resp.status_code, data=users)
            except Exception as exc:
                log.warning("plex.tv users endpoint unavailable (%s) — using owner only", exc)

            # Fallback: single owner entry using the main server token
            owner = PlexUser(
                id="owner",
                username="owner",
                title="Server Owner",
                token=self._api_key,
            )
            return ApiResult(ok=True, data=[owner])

        if self._http is not None:
            return await _fetch(self._http)
        async with httpx.AsyncClient() as client:
            return await _fetch(client)

    async def _resolve_user_tokens(self, client: httpx.AsyncClient, users: list[PlexUser]) -> None:
        """Switch into each home user concurrently to populate their token.

        The "switch" calls are independent round-trips to plex.tv, so running
        them concurrently keeps user discovery to roughly one round-trip's
        worth of latency instead of N sequential ones.
        """

        async def _resolve(user: PlexUser) -> None:
            user.token = await self._switch_home_user(client, user.id) or ""

        async with anyio.create_task_group() as tg:
            for user in users:
                tg.start_soon(_resolve, user)

    async def _switch_home_user(self, client: httpx.AsyncClient, user_id: str) -> str | None:
        """Switch into a home user and return their personal access token.

        Returns ``None`` (and logs a warning) if the switch fails — e.g. the
        user's profile is PIN-protected and the admin token can't bypass it.
        """
        url = _PLEX_TV_SWITCH_URL.format(user_id=user_id)
        headers = {
            "X-Plex-Token": self._api_key,
            "X-Plex-Client-Identifier": "arr-mcp",
        }
        try:
            resp = await client.post(url, headers=headers, timeout=10.0)
            if not resp.is_success:
                log.warning("Could not switch to home user %s: HTTP %s", user_id, resp.status_code)
                return None
            root = ET.fromstring(resp.text)
            return root.get("authToken") or None
        except Exception as exc:
            log.warning("Could not switch to home user %s: %s", user_id, exc)
            return None

    # ------------------------------------------------------------------
    # Watch history
    # ------------------------------------------------------------------

    async def get_watched_episodes(self, user_token: str) -> ApiResult:
        """Fetch watched episodes for a single user token."""
        result = await self._get_with_token(
            "/library/all",
            user_token,
            type="4",
            viewCount__gte="1",
        )
        if result.ok:
            result.data = _parse_episodes(result.data)  # type: ignore[arg-type]
        return result

    async def get_watched_movies(self, user_token: str) -> ApiResult:
        """Fetch watched movies for a single user token."""
        result = await self._get_with_token(
            "/library/all",
            user_token,
            type="1",
            viewCount__gte="1",
        )
        if result.ok:
            result.data = _parse_movies(result.data)  # type: ignore[arg-type]
        return result

    async def get_all_watched_episodes(self, users: list[PlexUser] | None = None) -> ApiResult:
        """Aggregate watched episodes across all home users.

        Each episode carries a ``watched_by`` list of display names. Pass
        ``users`` (e.g. from a prior ``get_home_users()`` call) to skip
        re-resolving the user list and per-user tokens.
        """
        if users is None:
            users_result = await self.get_home_users()
            if not users_result.ok:
                return users_result
            users = cast("list[PlexUser]", users_result.data)
        resolved_users: list[PlexUser] = users

        aggregated: dict[str, PlexEpisode] = {}

        for user in resolved_users:
            result = await self.get_watched_episodes(user.token)
            if not result.ok:
                log.warning("Could not fetch episodes for user %s: %s", user.title, result.error)
                continue
            for ep in result.data:  # type: ignore[union-attr]
                key = ep.rating_key
                if key in aggregated:
                    aggregated[key].watched_by.append(user.title)
                else:
                    ep.watched_by = [user.title]
                    aggregated[key] = ep

        return ApiResult(ok=True, data=list(aggregated.values()))

    async def get_all_watched_movies(self, users: list[PlexUser] | None = None) -> ApiResult:
        """Aggregate watched movies across all home users.

        Each movie carries a ``watched_by`` list of display names. Pass
        ``users`` (e.g. from a prior ``get_home_users()`` call) to skip
        re-resolving the user list and per-user tokens.
        """
        if users is None:
            users_result = await self.get_home_users()
            if not users_result.ok:
                return users_result
            users = cast("list[PlexUser]", users_result.data)
        resolved_users: list[PlexUser] = users

        aggregated: dict[str, PlexMovie] = {}

        for user in resolved_users:
            result = await self.get_watched_movies(user.token)
            if not result.ok:
                log.warning("Could not fetch movies for user %s: %s", user.title, result.error)
                continue
            for movie in result.data:  # type: ignore[union-attr]
                key = movie.rating_key
                if key in aggregated:
                    aggregated[key].watched_by.append(user.title)
                else:
                    movie.watched_by = [user.title]
                    aggregated[key] = movie

        return ApiResult(ok=True, data=list(aggregated.values()))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_with_token(self, path: str, token: str, **params: str) -> ApiResult:
        """Issue a GET to the local Plex server using a specific user token."""
        url = self._base_url + path
        headers = {
            "X-Plex-Token": token,
            "Accept": "application/json",
        }
        params_dict = dict(params)

        async def _send(client: httpx.AsyncClient) -> ApiResult:
            try:
                resp = await client.get(url, headers=headers, params=params_dict, timeout=10.0)
            except Exception as exc:
                return ApiResult(ok=False, error=str(exc))

            if not resp.is_success:
                return ApiResult(
                    ok=False, status_code=resp.status_code, error=f"HTTP {resp.status_code}"
                )

            try:
                data = resp.json()
            except Exception:
                data = {}
            return ApiResult(ok=True, status_code=resp.status_code, data=data)

        if self._http is not None:
            return await _send(self._http)
        async with httpx.AsyncClient() as client:
            return await _send(client)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _parse_home_users(payload: dict) -> list[PlexUser]:  # type: ignore[type-arg]
    users = []
    for u in payload.get("users", []):
        users.append(
            PlexUser(
                id=str(u.get("id", "")),
                username=u.get("username", ""),
                title=u.get("title", u.get("username", "")),
                token=u.get("authToken", ""),
            )
        )
    return users


def _parse_episodes(payload: dict) -> list[PlexEpisode]:  # type: ignore[type-arg]
    items = []
    for item in payload.get("MediaContainer", {}).get("Metadata", []):
        items.append(
            PlexEpisode(
                rating_key=str(item.get("ratingKey", "")),
                series_title=item.get("grandparentTitle", ""),
                season_number=item.get("parentIndex", 0),
                episode_number=item.get("index", 0),
                title=item.get("title", ""),
            )
        )
    return items


def _parse_movies(payload: dict) -> list[PlexMovie]:  # type: ignore[type-arg]
    items = []
    for item in payload.get("MediaContainer", {}).get("Metadata", []):
        items.append(
            PlexMovie(
                rating_key=str(item.get("ratingKey", "")),
                title=item.get("title", ""),
                year=item.get("year", 0),
            )
        )
    return items
