"""Tests for the pure service registry and diagnostic logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from arr_mcp.tools.services import (
    KNOWN_SERVICES,
    DiagnosticReport,
    Issue,
    ScannedService,
    check_api_key_present,
    check_port_binding,
    parse_ini_config,
    parse_json_config,
    parse_xml_config,
    run_diagnostics,
    scan_log_errors,
)

# ---------------------------------------------------------------------------
# Config parsers
# ---------------------------------------------------------------------------


def test_parse_xml_config_valid(tmp_path: Path) -> None:
    cfg = tmp_path / "config.xml"
    cfg.write_text("<Config><ApiKey>abc123</ApiKey><Port>8989</Port></Config>")
    result = parse_xml_config(cfg)
    assert result["ApiKey"] == "abc123"
    assert result["Port"] == "8989"


def test_parse_xml_config_malformed(tmp_path: Path) -> None:
    cfg = tmp_path / "config.xml"
    cfg.write_text("<Config><ApiKey>not closed</Config")
    with pytest.raises(ValueError, match="Malformed XML"):
        parse_xml_config(cfg)


def test_parse_xml_config_empty_text_becomes_empty_string(tmp_path: Path) -> None:
    cfg = tmp_path / "config.xml"
    cfg.write_text("<Config><ApiKey></ApiKey></Config>")
    result = parse_xml_config(cfg)
    assert result["ApiKey"] == ""


def test_parse_ini_config_valid(tmp_path: Path) -> None:
    cfg = tmp_path / "sabnzbd.ini"
    cfg.write_text("[misc]\nport = 8080\nhost = 0.0.0.0\n")
    result = parse_ini_config(cfg)
    assert result["misc"]["port"] == "8080"
    assert result["misc"]["host"] == "0.0.0.0"


def test_parse_json_config_valid(tmp_path: Path) -> None:
    cfg = tmp_path / "settings.json"
    cfg.write_text('{"port": 5055, "main": {"initialized": true}}')
    result = parse_json_config(cfg)
    assert result["port"] == 5055


def test_parse_json_config_malformed(tmp_path: Path) -> None:
    cfg = tmp_path / "settings.json"
    cfg.write_text("{not valid json}")
    with pytest.raises(ValueError, match="Malformed JSON"):
        parse_json_config(cfg)


# ---------------------------------------------------------------------------
# check_api_key_present
# ---------------------------------------------------------------------------


def test_check_api_key_present_valid() -> None:
    assert check_api_key_present({"ApiKey": "a" * 32}) is True


def test_check_api_key_present_empty() -> None:
    assert check_api_key_present({"ApiKey": ""}) is False


def test_check_api_key_present_missing() -> None:
    assert check_api_key_present({}) is False


def test_check_api_key_present_whitespace_only() -> None:
    assert check_api_key_present({"ApiKey": "   "}) is False


# ---------------------------------------------------------------------------
# check_port_binding
# ---------------------------------------------------------------------------


def test_check_port_binding_all_interfaces() -> None:
    port, is_localhost = check_port_binding({"Port": "8989", "BindAddress": ""}, "Port")
    assert port == "8989"
    assert is_localhost is False


def test_check_port_binding_localhost_127() -> None:
    port, is_localhost = check_port_binding({"Port": "8989", "BindAddress": "127.0.0.1"}, "Port")
    assert is_localhost is True


def test_check_port_binding_localhost_name() -> None:
    _, is_localhost = check_port_binding({"Port": "8989", "BindAddress": "localhost"}, "Port")
    assert is_localhost is True


def test_check_port_binding_ipv6_loopback() -> None:
    _, is_localhost = check_port_binding({"Port": "8989", "BindAddress": "::1"}, "Port")
    assert is_localhost is True


def test_check_port_binding_no_bind_address_key() -> None:
    _, is_localhost = check_port_binding({"Port": "8989"}, "Port")
    assert is_localhost is False


# ---------------------------------------------------------------------------
# scan_log_errors
# ---------------------------------------------------------------------------


def test_scan_log_errors_returns_matching_lines(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "app.txt").write_text(
        "normal line\n[Error] something broke\nnormal again\n[Fatal] crash\n"
    )
    matches = scan_log_errors(log_dir)
    assert len(matches) == 2
    assert any("[Error]" in m for m in matches)
    assert any("[Fatal]" in m for m in matches)


def test_scan_log_errors_no_matches(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "app.txt").write_text("all fine\neverything ok\n")
    matches = scan_log_errors(log_dir)
    assert matches == []


def test_scan_log_errors_missing_log_dir(tmp_path: Path) -> None:
    result = scan_log_errors(tmp_path / "nonexistent")
    assert result == []


def test_scan_log_errors_empty_dir(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    result = scan_log_errors(log_dir)
    assert result == []


def test_scan_log_errors_custom_patterns(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "app.txt").write_text("WARN low disk\nINFO startup\nERROR disk full\n")
    matches = scan_log_errors(log_dir, patterns=["warn"])
    assert len(matches) == 1
    assert "WARN" in matches[0]


# ---------------------------------------------------------------------------
# run_diagnostics — full integration of the pure logic
# ---------------------------------------------------------------------------


def _write_sonarr_config(path: Path, api_key: str = "abc123def456abc1", bind: str = "") -> None:
    path.write_text(
        f"<Config>"
        f"<ApiKey>{api_key}</ApiKey>"
        f"<Port>8989</Port>"
        f"<BindAddress>{bind}</BindAddress>"
        f"</Config>"
    )


def test_run_diagnostics_missing_config(tmp_path: Path) -> None:
    info = KNOWN_SERVICES["sonarr"]
    report = run_diagnostics("sonarr", tmp_path, info)
    assert report.status == "critical"
    assert any(i.category == "missing" for i in report.issues)


def test_run_diagnostics_sonarr_healthy(tmp_path: Path) -> None:
    info = KNOWN_SERVICES["sonarr"]
    _write_sonarr_config(tmp_path / "config.xml")
    (tmp_path / "logs").mkdir()
    report = run_diagnostics("sonarr", tmp_path, info)
    assert report.status == "healthy"
    assert report.issues == []
    assert report.warnings == []
    assert any("ApiKey" in ok for ok in report.ok)


def test_run_diagnostics_localhost_binding_produces_warning(tmp_path: Path) -> None:
    info = KNOWN_SERVICES["sonarr"]
    _write_sonarr_config(tmp_path / "config.xml", bind="127.0.0.1")
    (tmp_path / "logs").mkdir()
    report = run_diagnostics("sonarr", tmp_path, info)
    assert report.status == "degraded"
    assert any(w.category == "port" for w in report.warnings)


def test_run_diagnostics_missing_api_key_is_error(tmp_path: Path) -> None:
    info = KNOWN_SERVICES["sonarr"]
    _write_sonarr_config(tmp_path / "config.xml", api_key="")
    (tmp_path / "logs").mkdir()
    report = run_diagnostics("sonarr", tmp_path, info)
    assert report.status == "critical"
    assert any(i.category == "config" for i in report.issues)


def test_run_diagnostics_malformed_xml_returns_unknown(tmp_path: Path) -> None:
    info = KNOWN_SERVICES["sonarr"]
    (tmp_path / "config.xml").write_text("<Config><bad")
    report = run_diagnostics("sonarr", tmp_path, info)
    assert report.status == "unknown"


def test_run_diagnostics_log_errors_produce_warning(tmp_path: Path) -> None:
    info = KNOWN_SERVICES["sonarr"]
    _write_sonarr_config(tmp_path / "config.xml")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "sonarr.txt").write_text("[Error] database locked\n")
    report = run_diagnostics("sonarr", tmp_path, info)
    assert any(w.category == "logs" for w in report.warnings)


def test_run_diagnostics_radarr_healthy(tmp_path: Path) -> None:
    info = KNOWN_SERVICES["radarr"]
    (tmp_path / "config.xml").write_text(
        "<Config><ApiKey>radarrkey12345678</ApiKey><Port>7878</Port></Config>"
    )
    (tmp_path / "logs").mkdir()
    report = run_diagnostics("radarr", tmp_path, info)
    assert report.status == "healthy"


def test_run_diagnostics_sabnzbd_valid_ini(tmp_path: Path) -> None:
    info = KNOWN_SERVICES["sabnzbd"]
    (tmp_path / "sabnzbd.ini").write_text("[misc]\nport = 8080\n")
    (tmp_path / "logs").mkdir()
    report = run_diagnostics("sabnzbd", tmp_path, info)
    assert report.status == "healthy"
    assert any("parsed" in ok for ok in report.ok)


def test_run_diagnostics_overseerr_valid_json(tmp_path: Path) -> None:
    info = KNOWN_SERVICES["overseerr"]
    (tmp_path / "settings.json").write_text('{"port": 5055}')
    (tmp_path / "logs").mkdir()
    report = run_diagnostics("overseerr", tmp_path, info)
    assert report.status == "healthy"


# ---------------------------------------------------------------------------
# Registry completeness
# ---------------------------------------------------------------------------


def test_known_services_all_have_config_file() -> None:
    for name, info in KNOWN_SERVICES.items():
        assert info.config_file, f"{name}: config_file is empty"


def test_known_services_all_have_log_dir() -> None:
    for name, info in KNOWN_SERVICES.items():
        assert info.log_dir, f"{name}: log_dir is empty"


def test_known_services_all_have_valid_format() -> None:
    valid_formats = {"xml", "ini", "json", "yaml"}
    for name, info in KNOWN_SERVICES.items():
        assert info.config_format in valid_formats, f"{name}: unknown format {info.config_format}"


# ---------------------------------------------------------------------------
# Data model serialisation
# ---------------------------------------------------------------------------


def test_issue_to_dict() -> None:
    issue = Issue(severity="error", category="config", message="bad", fix_hint="fix it")
    d = issue.to_dict()
    assert d["severity"] == "error"
    assert d["fix_hint"] == "fix it"


def test_diagnostic_report_to_dict() -> None:
    report = DiagnosticReport(
        service="sonarr",
        service_dir="/srv/sonarr",
        status="healthy",
        ok=["all good"],
    )
    d = report.to_dict()
    assert d["service"] == "sonarr"
    assert d["status"] == "healthy"
    assert d["issues"] == []
    assert d["ok"] == ["all good"]


def test_scanned_service_to_dict() -> None:
    svc = ScannedService(
        name="sonarr",
        service_dir="/srv/sonarr",
        known=True,
        has_config=True,
        container_running=False,
    )
    d = svc.to_dict()
    assert d["known"] is True
    assert d["container_running"] is False
