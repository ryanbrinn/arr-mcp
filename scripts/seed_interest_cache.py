"""Generate a realistic ``.arr-mcp-media-interest-cache.json`` fixture.

Builds cache data matching the schema written by ``MediaInterestStore``
(see ``arr_mcp.tasks.media_interest``), covering the shows and movies
seeded into the dev test stack by ``test-stack/seed-media.sh``, with
multiple users and a realistic mix of per-user interest states.

Usage::

    uv run python scripts/seed_interest_cache.py
    uv run python scripts/seed_interest_cache.py --output PATH --seed 7
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

from arr_mcp.services.interests import InterestState

DEFAULT_OUTPUT = Path("test-stack/data/.arr-mcp-media-interest-cache.json")

USERS = [
    {"id": "1", "username": "ryan", "title": "Ryan"},
    {"id": "2", "username": "sarah", "title": "Sarah"},
    {"id": "3", "username": "alex", "title": "Alex"},
]

_STATE_CHOICES = [
    InterestState.interested.value,
    InterestState.watched.value,
    InterestState.marked_deletion.value,
]
_STATE_WEIGHTS = [0.35, 0.5, 0.15]

SERIES: dict[str, dict[str, Any]] = {
    "1": {
        "title": "Breaking Bad",
        "seasons": {
            "1": [
                "Pilot",
                "Cat's in the Bag...",
                "...And the Bag's in the River",
                "Cancer Man",
                "Gray Matter",
                "Crazy Handful of Nothin'",
                "A No-Rough-Stuff-Type Deal",
            ],
            "2": [f"Episode {n}" for n in range(1, 14)],
        },
        "size_range": (350_000_000, 900_000_000),
    },
    "2": {
        "title": "The Office (US)",
        "seasons": {
            "1": [
                "Pilot",
                "Diversity Day",
                "Health Care",
                "The Alliance",
                "Basketball",
                "Hot Girl",
            ],
            "2": [f"Episode {n}" for n in range(1, 23)],
        },
        "size_range": (200_000_000, 450_000_000),
    },
    "3": {
        "title": "Planet Earth",
        "seasons": {
            "1": [
                "From Pole to Pole",
                "Mountains",
                "Fresh Water",
                "Caves",
                "Deserts",
                "Ice Worlds",
                "Great Plains",
                "Jungles",
                "Shallow Seas",
                "Seasonal Forests",
                "Ocean Deep",
            ],
        },
        "size_range": (1_200_000_000, 2_500_000_000),
    },
}

MOVIES: dict[str, str] = {
    "9101": "The Shawshank Redemption",
    "9102": "Inception",
    "9103": "Oppenheimer",
}


def _random_dots(rng: random.Random) -> dict[str, str]:
    return {
        user["id"]: rng.choices(_STATE_CHOICES, weights=_STATE_WEIGHTS)[0]
        for user in USERS
    }


def _build_series(rng: random.Random) -> dict[str, dict[str, list[dict[str, Any]]]]:
    series_cache: dict[str, dict[str, list[dict[str, Any]]]] = {}
    next_file_id = 9001
    for series_id, series in SERIES.items():
        size_low, size_high = series["size_range"]
        season_map: dict[str, list[dict[str, Any]]] = {}
        for season_number, titles in series["seasons"].items():
            episodes = []
            for episode_number, title in enumerate(titles, start=1):
                episodes.append(
                    {
                        "episode_number": episode_number,
                        "title": title,
                        "has_file": True,
                        "episode_file_id": next_file_id,
                        "size_bytes": rng.randint(size_low, size_high),
                        "dots": _random_dots(rng),
                    }
                )
                next_file_id += 1
            season_map[season_number] = episodes
        series_cache[series_id] = season_map
    return series_cache


def _build_movies(rng: random.Random) -> dict[str, dict[str, str]]:
    return {movie_file_id: _random_dots(rng) for movie_file_id in MOVIES}


def build_cache(seed: int) -> dict[str, Any]:
    """Return a cache dict matching the ``MediaInterestStore`` schema."""
    rng = random.Random(seed)
    return {
        "users": USERS,
        "movies": _build_movies(rng),
        "series": _build_series(rng),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output path for the cache file (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for reproducible output (default: 42)",
    )
    args = parser.parse_args()

    cache = build_cache(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cache, indent=2))
    print(f"Wrote interest cache fixture to {args.output}")


if __name__ == "__main__":
    main()
