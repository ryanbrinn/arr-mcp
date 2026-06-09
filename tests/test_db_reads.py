"""Tests for SQLite DB read functions and DB-backed diagnostic checks."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from arr_mcp.tools.services import (
    read_download_clients,
    read_indexers,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(path: Path) -> None:
    """Create a minimal arr-style SQLite DB with DownloadClients and Indexers tables."""
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "CREATE TABLE DownloadClients "
            "(Id INTEGER PRIMARY KEY, Name TEXT, Implementation TEXT, "
            "Settings TEXT, Enable INTEGER)"
        )
        conn.execute(
            "CREATE TABLE Indexers "
            "(Id INTEGER PRIMARY KEY, Name TEXT, Implementation TEXT, Enable INTEGER)"
        )
        conn.commit()


def _insert_download_client(
    path: Path,
    name: str,
    impl: str = "Sabnzbd",
    settings: dict | None = None,
    enable: bool = True,
) -> None:
    s = json.dumps(settings or {"host": "sabnzbd", "port": 8080, "apiKey": "abc"})
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "INSERT INTO DownloadClients"
            " (Name, Implementation, Settings, Enable)"
            " VALUES (?,?,?,?)",
            (name, impl, s, int(enable)),
        )
        conn.commit()


def _insert_indexer(
    path: Path, name: str, impl: str = "Newznab", enable: bool = True
) -> None:
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "INSERT INTO Indexers (Name, Implementation, Enable) VALUES (?,?,?)",
            (name, impl, int(enable)),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# read_download_clients
# ---------------------------------------------------------------------------


def test_read_download_clients_empty_table(tmp_path: Path) -> None:
    db = tmp_path / "sonarr.db"
    _make_db(db)
    assert read_download_clients(db) == []


def test_read_download_clients_returns_records(tmp_path: Path) -> None:
    db = tmp_path / "sonarr.db"
    _make_db(db)
    _insert_download_client(db, "SABnzbd")
    clients = read_download_clients(db)
    assert len(clients) == 1
    assert clients[0].name == "SABnzbd"
    assert clients[0].implementation == "Sabnzbd"
    assert clients[0].enable is True
    assert clients[0].settings["host"] == "sabnzbd"


def test_read_download_clients_disabled(tmp_path: Path) -> None:
    db = tmp_path / "sonarr.db"
    _make_db(db)
    _insert_download_client(db, "SABnzbd", enable=False)
    clients = read_download_clients(db)
    assert clients[0].enable is False


def test_read_download_clients_missing_db(tmp_path: Path) -> None:
    assert read_download_clients(tmp_path / "nonexistent.db") == []


def test_read_download_clients_bad_settings_json(tmp_path: Path) -> None:
    db = tmp_path / "sonarr.db"
    _make_db(db)
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "INSERT INTO DownloadClients"
            " (Name, Implementation, Settings, Enable)"
            " VALUES (?,?,?,?)",
            ("Bad", "Sabnzbd", "not-json{{{", 1),
        )
        conn.commit()
    clients = read_download_clients(db)
    assert clients[0].settings == {}


# ---------------------------------------------------------------------------
# read_indexers
# ---------------------------------------------------------------------------


def test_read_indexers_empty_table(tmp_path: Path) -> None:
    db = tmp_path / "sonarr.db"
    _make_db(db)
    assert read_indexers(db) == []


def test_read_indexers_returns_records(tmp_path: Path) -> None:
    db = tmp_path / "sonarr.db"
    _make_db(db)
    _insert_indexer(db, "NZBgeek")
    indexers = read_indexers(db)
    assert len(indexers) == 1
    assert indexers[0].name == "NZBgeek"
    assert indexers[0].enable is True


def test_read_indexers_missing_db(tmp_path: Path) -> None:
    assert read_indexers(tmp_path / "nonexistent.db") == []


def test_read_indexers_no_table(tmp_path: Path) -> None:
    db = tmp_path / "sonarr.db"
    with sqlite3.connect(str(db)) as conn:
        conn.execute("CREATE TABLE Foo (Id INTEGER PRIMARY KEY)")
        conn.commit()
    assert read_indexers(db) == []
