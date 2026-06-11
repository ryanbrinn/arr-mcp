"""MediaInterestCache — periodic cache of per-user watch/interest state.

Bridges Plex watch history and the ``InterestStore`` into a per-episode and
per-movie cache that the dashboard can render without making per-request
calls to Sonarr/Radarr/Plex (which would be an N+1 fetch per series).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import anyio

from arr_mcp.services.interests import InterestStore

if TYPE_CHECKING:
    from arr_mcp.config import Settings
    from arr_mcp.services.plex import PlexUser

log = logging.getLogger(__name__)

_CACHE_FILE = ".arr-mcp-media-interest-cache.json"
_POLL_INTERVAL_SECONDS = 1800  # 30 minutes


class MediaInterestStore:
    """Reads/writes the cached per-user media interest data."""

    def __init__(self, services_dir: str) -> None:
        self._path = Path(services_dir) / _CACHE_FILE

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text())
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def save(self, data: dict[str, Any]) -> None:
        try:
            self._path.write_text(json.dumps(data, indent=2))
        except Exception:
            log.error("Failed to write media interest cache at %s", self._path)


class MediaInterestChecker:
    """Background task that syncs Plex watch history into the interest cache.

    For each configured Plex home user, syncs watched movies/episodes into
    the ``InterestStore`` (seeding ``watched`` state without overwriting
    explicit choices), then snapshots every user's current interest state per
    movie and episode into a cache file the dashboard can read directly.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._store = MediaInterestStore(settings.services_dir)

    async def run(self) -> None:
        """Run the periodic poll loop until cancelled."""
        log.info("MediaInterestChecker started (interval=30m)")
        while True:
            try:
                await self._poll()
            except Exception:
                log.exception("MediaInterestChecker poll error")
            await anyio.sleep(_POLL_INTERVAL_SECONDS)

    async def _poll(self) -> None:
        from arr_mcp.services.base import ServiceNotConfiguredError
        from arr_mcp.services.plex import PlexClient
        from arr_mcp.services.radarr import RadarrClient
        from arr_mcp.services.registry import ServiceRegistry
        from arr_mcp.services.sonarr import SonarrClient

        registry = ServiceRegistry(self._settings.services_dir)
        interest_store = InterestStore(self._settings.services_dir)

        try:
            plex = cast(PlexClient, registry.get_client("plex"))
        except ServiceNotConfiguredError:
            return

        users_result = await plex.get_home_users()
        if not users_result.ok:
            return
        users = cast("list[PlexUser]", users_result.data)

        cache: dict[str, Any] = {
            "users": [
                {"id": u.id, "username": u.username, "title": u.title} for u in users
            ],
            "movies": {},
            "series": {},
        }

        try:
            radarr = cast(RadarrClient, registry.get_client("radarr"))
            movies_result = await radarr.get_movies()
            watched_movies_result = await plex.get_all_watched_movies(users)
            if movies_result.ok and watched_movies_result.ok:
                cache["movies"] = _sync_movies(
                    movies_result.data,  # type: ignore[arg-type]
                    watched_movies_result.data,  # type: ignore[arg-type]
                    users,
                    interest_store,
                )
        except ServiceNotConfiguredError:
            pass

        try:
            sonarr = cast(SonarrClient, registry.get_client("sonarr"))
            series_result = await sonarr.get_series()
            watched_episodes_result = await plex.get_all_watched_episodes(users)
            if series_result.ok and watched_episodes_result.ok:
                cache["series"] = await _sync_series(
                    sonarr,
                    series_result.data,  # type: ignore[arg-type]
                    watched_episodes_result.data,  # type: ignore[arg-type]
                    users,
                    interest_store,
                )
        except ServiceNotConfiguredError:
            pass

        self._store.save(cache)
        log.info(
            "MediaInterestChecker updated cache (%d movies, %d series)",
            len(cache["movies"]),
            len(cache["series"]),
        )


def _user_dots(
    content_id: str, users: list[PlexUser], store: InterestStore
) -> dict[str, str]:
    return {user.id: store.get(content_id, user.id).state.value for user in users}


def _sync_movies(
    movies: list[Any],
    watched_movies: list[Any],
    users: list[PlexUser],
    store: InterestStore,
) -> dict[str, dict[str, str]]:
    """Sync watched movies into the store and snapshot per-user dots."""
    title_to_user = {u.title: u for u in users}
    watched_by_key: dict[tuple[str, int], list[str]] = {
        (m.title.lower(), m.year): m.watched_by for m in watched_movies
    }

    result: dict[str, dict[str, str]] = {}
    for movie in movies:
        if movie.movie_file_id is None:
            continue
        content_id = str(movie.movie_file_id)
        watched_by = watched_by_key.get((movie.title.lower(), movie.year), [])
        for title in watched_by:
            user = title_to_user.get(title)
            if user:
                store.sync_watched(content_id, user.id, user.title, "movie")
        result[content_id] = _user_dots(content_id, users, store)

    return result


async def _sync_series(
    sonarr: Any,
    series_list: list[Any],
    watched_episodes: list[Any],
    users: list[PlexUser],
    store: InterestStore,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Sync watched episodes into the store and snapshot per-episode dots.

    Returns ``{series_id: {season_number: [episode_entry, ...]}}`` where each
    episode entry carries the data needed to render the drawer's expandable
    season/episode lists alongside per-user interest dots.
    """
    title_to_user = {u.title: u for u in users}
    plex_lookup: dict[tuple[str, int, int], list[str]] = {
        (ep.series_title.lower(), ep.season_number, ep.episode_number): ep.watched_by
        for ep in watched_episodes
    }

    series_map: dict[str, dict[str, list[dict[str, Any]]]] = {}

    for s in series_list:
        ep_result = await sonarr.get_episodes(s.id)
        ef_result = await sonarr.get_episode_files(s.id)
        if not ep_result.ok or not ef_result.ok:
            continue
        files_by_id = {ef.id: ef for ef in ef_result.data}

        season_map: dict[str, list[dict[str, Any]]] = {}
        for episode in sorted(
            ep_result.data, key=lambda e: (e.season_number, e.episode_number)
        ):
            if episode.season_number == 0:
                continue

            entry: dict[str, Any] = {
                "episode_number": episode.episode_number,
                "title": episode.title,
                "has_file": episode.has_file,
                "episode_file_id": episode.episode_file_id,
                "size_bytes": 0,
                "dots": {},
            }

            if episode.has_file and episode.episode_file_id is not None:
                ef = files_by_id.get(episode.episode_file_id)
                entry["size_bytes"] = ef.size if ef else 0

                content_id = str(episode.episode_file_id)
                key = (s.title.lower(), episode.season_number, episode.episode_number)
                for title in plex_lookup.get(key, []):
                    user = title_to_user.get(title)
                    if user:
                        store.sync_watched(content_id, user.id, user.title, "episode")
                entry["dots"] = _user_dots(content_id, users, store)

            season_map.setdefault(str(episode.season_number), []).append(entry)

        series_map[str(s.id)] = season_map

    return series_map
