"""Shared domain dataclasses for all service API responses."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SeasonSummary:
    """Season-level summary within a Series."""

    season_number: int
    episode_count: int
    episode_file_count: int


@dataclass
class Series:
    """A TV series from Sonarr."""

    id: int
    title: str
    path: str
    seasons: list[SeasonSummary] = field(default_factory=list)


@dataclass
class Episode:
    """A single episode from Sonarr."""

    id: int
    series_id: int
    season_number: int
    episode_number: int
    title: str
    has_file: bool
    episode_file_id: int | None = None


@dataclass
class EpisodeFile:
    """An on-disk episode file tracked by Sonarr."""

    id: int
    series_id: int
    season_number: int
    path: str
    size: int


@dataclass
class Movie:
    """A movie from Radarr."""

    id: int
    title: str
    path: str
    has_file: bool
    movie_file_id: int | None = None


@dataclass
class MovieFile:
    """An on-disk movie file tracked by Radarr."""

    id: int
    movie_id: int
    path: str
    size: int
