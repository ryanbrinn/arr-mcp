"""Tests for download path verification (sonarr/radarr vs sabnzbd complete_dir)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp import FastMCP

from arr_mcp.config import Settings
from arr_mcp.tools.diagnostics import _check_download_path_match, register_diagnostic_tools
from arr_mcp.tools.services import DiagnosticReport, read_sabnzbd_complete_dir

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_sabnzbd_ini(path: Path, complete_dir: str) -> None:
    path.write_text(f"[misc]\ncomplete_dir = {complete_dir}\n")


def _make_db_with_sabnzbd_client(
    path: Path,
    tv_directory: str = "",
    movie_directory: str = "",
    enable: bool = True,
    with_indexer: bool = False,
) -> None:
    settings: dict[str, object] = {
        "host": "sabnzbd",
        "port": 8080,
        "apiKey": "testkey",
        "urlBase": "",
    }
    if tv_directory:
        settings["tvDirectory"] = tv_directory
    if movie_directory:
        settings["movieDirectory"] = movie_directory

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
        conn.execute(
            "INSERT INTO DownloadClients (Name, Implementation, Settings, Enable) VALUES (?,?,?,?)",
            ("SABnzbd", "Sabnzbd", json.dumps(settings), int(enable)),
        )
        if with_indexer:
            conn.execute(
                "INSERT INTO Indexers (Name, Implementation, Enable) VALUES (?,?,?)",
                ("NZBgeek", "Newznab", 1),
            )
        conn.commit()


def _make_report(service: str = "sonarr") -> DiagnosticReport:
    return DiagnosticReport(service=service, service_dir="/tmp", status="healthy")


# ---------------------------------------------------------------------------
# read_sabnzbd_complete_dir
# ---------------------------------------------------------------------------


def test_read_sabnzbd_complete_dir_success(tmp_path: Path) -> None:
    sabnzbd_dir = tmp_path / "sabnzbd"
    sabnzbd_dir.mkdir()
    _write_sabnzbd_ini(sabnzbd_dir / "sabnzbd.ini", "/downloads/complete")
    assert read_sabnzbd_complete_dir(sabnzbd_dir) == "/downloads/complete"


def test_read_sabnzbd_complete_dir_missing_file(tmp_path: Path) -> None:
    sabnzbd_dir = tmp_path / "sabnzbd"
    sabnzbd_dir.mkdir()
    assert read_sabnzbd_complete_dir(sabnzbd_dir) is None


def test_read_sabnzbd_complete_dir_empty_key(tmp_path: Path) -> None:
    sabnzbd_dir = tmp_path / "sabnzbd"
    sabnzbd_dir.mkdir()
    (sabnzbd_dir / "sabnzbd.ini").write_text("[misc]\ncomplete_dir =\n")
    assert read_sabnzbd_complete_dir(sabnzbd_dir) is None


# ---------------------------------------------------------------------------
# _check_download_path_match
# ---------------------------------------------------------------------------


def test_path_match_adds_ok_when_paths_match(tmp_path: Path) -> None:
    services_root = tmp_path / "services"
    services_root.mkdir()

    svc_dir = services_root / "sonarr"
    svc_dir.mkdir()
    _make_db_with_sabnzbd_client(svc_dir / "sonarr.db", tv_directory="/downloads/complete")

    sabnzbd_dir = services_root / "sabnzbd"
    sabnzbd_dir.mkdir()
    _write_sabnzbd_ini(sabnzbd_dir / "sabnzbd.ini", "/downloads/complete")

    report = _make_report()
    _check_download_path_match("sonarr", svc_dir, services_root, report)

    assert any("matches" in msg for msg in report.ok)
    assert report.warnings == []
    assert report.status == "healthy"


def test_path_match_warns_on_mismatch(tmp_path: Path) -> None:
    services_root = tmp_path / "services"
    services_root.mkdir()

    svc_dir = services_root / "sonarr"
    svc_dir.mkdir()
    _make_db_with_sabnzbd_client(svc_dir / "sonarr.db", tv_directory="/media/downloads/complete")

    sabnzbd_dir = services_root / "sabnzbd"
    sabnzbd_dir.mkdir()
    _write_sabnzbd_ini(sabnzbd_dir / "sabnzbd.ini", "/downloads/complete")

    report = _make_report()
    _check_download_path_match("sonarr", svc_dir, services_root, report)

    assert report.status == "degraded"
    assert any(w.category == "path" for w in report.warnings)
    assert any("mismatch" in w.message for w in report.warnings)
    assert any("Remote Path Mapping" in w.fix_hint for w in report.warnings)


def test_path_match_subpath_is_ok(tmp_path: Path) -> None:
    """arr dir is a subdirectory of sabnzbd complete_dir — acceptable."""
    services_root = tmp_path / "services"
    services_root.mkdir()

    svc_dir = services_root / "sonarr"
    svc_dir.mkdir()
    _make_db_with_sabnzbd_client(svc_dir / "sonarr.db", tv_directory="/downloads/complete/tv")

    sabnzbd_dir = services_root / "sabnzbd"
    sabnzbd_dir.mkdir()
    _write_sabnzbd_ini(sabnzbd_dir / "sabnzbd.ini", "/downloads/complete")

    report = _make_report()
    _check_download_path_match("sonarr", svc_dir, services_root, report)

    assert report.status == "healthy"
    assert report.warnings == []


def test_path_match_skips_if_no_directory_key(tmp_path: Path) -> None:
    """No tvDirectory set — using categories, can't compare paths."""
    services_root = tmp_path / "services"
    services_root.mkdir()

    svc_dir = services_root / "sonarr"
    svc_dir.mkdir()
    _make_db_with_sabnzbd_client(svc_dir / "sonarr.db")  # no tv_directory

    sabnzbd_dir = services_root / "sabnzbd"
    sabnzbd_dir.mkdir()
    _write_sabnzbd_ini(sabnzbd_dir / "sabnzbd.ini", "/downloads/complete")

    report = _make_report()
    _check_download_path_match("sonarr", svc_dir, services_root, report)

    assert report.ok == []
    assert report.warnings == []


def test_path_match_skips_if_no_sabnzbd_dir(tmp_path: Path) -> None:
    services_root = tmp_path / "services"
    services_root.mkdir()

    svc_dir = services_root / "sonarr"
    svc_dir.mkdir()
    _make_db_with_sabnzbd_client(svc_dir / "sonarr.db", tv_directory="/downloads/complete")
    # No sabnzbd directory

    report = _make_report()
    _check_download_path_match("sonarr", svc_dir, services_root, report)

    assert report.ok == []
    assert report.warnings == []


def test_path_match_skips_no_db_file(tmp_path: Path) -> None:
    services_root = tmp_path / "services"
    services_root.mkdir()
    svc_dir = services_root / "plex"
    svc_dir.mkdir()

    report = _make_report("plex")
    _check_download_path_match("plex", svc_dir, services_root, report)

    assert report.ok == []
    assert report.warnings == []


def test_path_match_trailing_slash_normalized(tmp_path: Path) -> None:
    services_root = tmp_path / "services"
    services_root.mkdir()

    svc_dir = services_root / "sonarr"
    svc_dir.mkdir()
    _make_db_with_sabnzbd_client(svc_dir / "sonarr.db", tv_directory="/downloads/complete/")

    sabnzbd_dir = services_root / "sabnzbd"
    sabnzbd_dir.mkdir()
    _write_sabnzbd_ini(sabnzbd_dir / "sabnzbd.ini", "/downloads/complete")

    report = _make_report()
    _check_download_path_match("sonarr", svc_dir, services_root, report)

    assert report.status == "healthy"
    assert report.warnings == []


# ---------------------------------------------------------------------------
# service_diagnose integration
# ---------------------------------------------------------------------------


@pytest.fixture
def server(settings: Settings, mock_client: MagicMock) -> FastMCP:
    s = FastMCP("test")
    register_diagnostic_tools(s, settings, mock_client)
    return s


async def test_service_diagnose_flags_path_mismatch(server: FastMCP, settings: Settings) -> None:
    services_root = Path(settings.services_dir)

    svc_dir = services_root / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>abc</ApiKey><Port>8989</Port></Config>")
    (svc_dir / "logs").mkdir()
    _make_db_with_sabnzbd_client(svc_dir / "sonarr.db", tv_directory="/media/downloads/complete")

    sabnzbd_dir = services_root / "sabnzbd"
    sabnzbd_dir.mkdir()
    _write_sabnzbd_ini(sabnzbd_dir / "sabnzbd.ini", "/downloads/complete")

    result = await server.call_tool(
        "service_diagnose", {"service": "sonarr", "service_dir": str(svc_dir)}
    )
    data = json.loads(result[0][0].text)
    assert data["status"] == "degraded"
    assert any(w["category"] == "path" for w in data["warnings"])


async def test_service_diagnose_healthy_path_match(server: FastMCP, settings: Settings) -> None:
    services_root = Path(settings.services_dir)

    svc_dir = services_root / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>abc</ApiKey><Port>8989</Port></Config>")
    (svc_dir / "logs").mkdir()
    _make_db_with_sabnzbd_client(
        svc_dir / "sonarr.db", tv_directory="/downloads/complete", with_indexer=True
    )

    sabnzbd_dir = services_root / "sabnzbd"
    sabnzbd_dir.mkdir()
    _write_sabnzbd_ini(sabnzbd_dir / "sabnzbd.ini", "/downloads/complete")

    result = await server.call_tool(
        "service_diagnose", {"service": "sonarr", "service_dir": str(svc_dir)}
    )
    data = json.loads(result[0][0].text)
    assert data["status"] == "healthy"
    assert any("matches" in msg for msg in data["ok"])
