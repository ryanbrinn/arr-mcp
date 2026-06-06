"""Plex API client for reading watch history and library data."""

from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = 10.0


@dataclass
class PlexEpisode:
    """A single episode with its watch state across users."""

    rating_key: str
    title: str
    series_title: str
    season_number: int
    episode_number: int
    watched_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "rating_key": self.rating_key,
            "title": self.title,
            "series_title": self.series_title,
            "season_number": self.season_number,
            "episode_number": self.episode_number,
            "watched_by": self.watched_by,
        }


@dataclass
class PlexMovie:
    """A single movie with its watch state across users."""

    rating_key: str
    title: str
    year: int | None
    watched_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "rating_key": self.rating_key,
            "title": self.title,
            "year": self.year,
            "watched_by": self.watched_by,
        }


@dataclass
class PlexUser:
    """A Plex home user or managed account."""

    user_id: str
    username: str
    token: str


def read_plex_token(plex_dir: Path) -> str | None:
    """Return the Plex token from Preferences.xml or PLEX_TOKEN env var.

    Env var takes precedence over the config file value.
    """
    env_token = os.environ.get("PLEX_TOKEN", "").strip()
    if env_token:
        return env_token

    prefs_path = plex_dir / "Preferences.xml"
    if not prefs_path.exists():
        return None

    try:
        root = ET.parse(str(prefs_path)).getroot()
        token = root.attrib.get("PlexOnlineToken", "").strip()
        return token or None
    except ET.ParseError:
        log.warning("Could not parse Plex Preferences.xml")
        return None


async def _get_json(client: httpx.AsyncClient, url: str, token: str) -> dict:  # type: ignore[type-arg]
    resp = await client.get(
        url,
        headers={"X-Plex-Token": token, "Accept": "application/json"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


async def get_home_users(base_url: str, token: str) -> list[PlexUser]:
    """Return all users in the Plex home (owner + managed accounts).

    Falls back to a single entry for the owner if the home users endpoint
    is unavailable (e.g. unclaimed server).
    """
    async with httpx.AsyncClient() as client:
        try:
            data = await _get_json(client, "https://plex.tv/api/v2/home/users", token)
            users = []
            for u in data.get("users", []):
                user_token = u.get("authToken") or token
                users.append(
                    PlexUser(
                        user_id=str(u.get("id", "")),
                        username=u.get("username") or u.get("title") or "unknown",
                        token=user_token,
                    )
                )
            if users:
                return users
        except (httpx.HTTPError, KeyError):
            pass

        # Fallback: owner only
        try:
            resp = await client.get(
                f"{base_url}/",
                headers={"X-Plex-Token": token, "Accept": "application/json"},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            info = resp.json().get("MediaContainer", {})
            owner = info.get("myPlexUsername") or "owner"
            return [PlexUser(user_id="owner", username=owner, token=token)]
        except httpx.HTTPError:
            return [PlexUser(user_id="owner", username="owner", token=token)]


async def get_watched_episodes(base_url: str, token: str) -> list[dict[str, object]]:
    """Return all watched episodes for a single user token.

    Each entry is a flat dict with series_title, season_number,
    episode_number, rating_key, title.
    """
    async with httpx.AsyncClient() as client:
        try:
            data = await _get_json(
                client,
                f"{base_url}/library/all?type=4&viewCount>=1&X-Plex-Token={token}",
                token,
            )
        except httpx.HTTPError as exc:
            log.warning("Failed to fetch watched episodes: %s", exc)
            return []

    episodes = []
    for item in data.get("MediaContainer", {}).get("Metadata", []):
        episodes.append(
            {
                "rating_key": str(item.get("ratingKey", "")),
                "title": item.get("title", ""),
                "series_title": item.get("grandparentTitle", ""),
                "season_number": int(item.get("parentIndex", 0)),
                "episode_number": int(item.get("index", 0)),
            }
        )
    return episodes


async def get_watched_movies(base_url: str, token: str) -> list[dict[str, object]]:
    """Return all watched movies for a single user token."""
    async with httpx.AsyncClient() as client:
        try:
            data = await _get_json(
                client,
                f"{base_url}/library/all?type=1&viewCount>=1&X-Plex-Token={token}",
                token,
            )
        except httpx.HTTPError as exc:
            log.warning("Failed to fetch watched movies: %s", exc)
            return []

    movies = []
    for item in data.get("MediaContainer", {}).get("Metadata", []):
        movies.append(
            {
                "rating_key": str(item.get("ratingKey", "")),
                "title": item.get("title", ""),
                "year": item.get("year"),
            }
        )
    return movies


async def get_all_watched_episodes(base_url: str, users: list[PlexUser]) -> list[PlexEpisode]:
    """Aggregate watched episodes across all users.

    Returns a list of PlexEpisode where watched_by contains the usernames
    of everyone who has watched that episode.
    """
    seen: dict[str, PlexEpisode] = {}

    for user in users:
        episodes = await get_watched_episodes(base_url, user.token)
        for ep in episodes:
            key = str(ep["rating_key"])
            if key not in seen:
                seen[key] = PlexEpisode(
                    rating_key=key,
                    title=str(ep["title"]),
                    series_title=str(ep["series_title"]),
                    season_number=int(ep["season_number"]),  # type: ignore[arg-type]
                    episode_number=int(ep["episode_number"]),  # type: ignore[arg-type]
                )
            seen[key].watched_by.append(user.username)

    return list(seen.values())


async def get_all_watched_movies(base_url: str, users: list[PlexUser]) -> list[PlexMovie]:
    """Aggregate watched movies across all users."""
    seen: dict[str, PlexMovie] = {}

    for user in users:
        movies = await get_watched_movies(base_url, user.token)
        for mv in movies:
            key = str(mv["rating_key"])
            if key not in seen:
                year_raw = mv.get("year")
                seen[key] = PlexMovie(
                    rating_key=key,
                    title=str(mv["title"]),
                    year=int(year_raw) if year_raw is not None else None,
                )
            seen[key].watched_by.append(user.username)

    return list(seen.values())
