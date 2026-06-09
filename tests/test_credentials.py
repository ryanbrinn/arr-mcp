"""Tests for CredentialStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from arr_mcp.services.credentials import (
    CredentialStore,
    ServiceCredential,
    _decrypt,
    _encrypt,
)

# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_roundtrip() -> None:
    original = '{"sonarr": {"api_key": "abc123"}}'
    secret = "my-secret"
    assert _decrypt(_encrypt(original, secret), secret) == original


def test_encrypt_different_secrets_differ() -> None:
    data = "hello world this is a longer string"
    assert _encrypt(data, "secret1") != _encrypt(data, "totally-different-secret")


# ---------------------------------------------------------------------------
# CredentialStore — env var tier (tier 1)
# ---------------------------------------------------------------------------


def test_get_returns_env_var_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SONARR_API_KEY", "env-key-123")
    store = CredentialStore(str(tmp_path))
    cred = store.get("sonarr")
    assert cred is not None
    assert cred.api_key == "env-key-123"


def test_env_var_takes_priority_over_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SONARR_API_KEY", "env-key")
    store = CredentialStore(str(tmp_path))
    store.set("sonarr", ServiceCredential(api_key="file-key"))
    cred = store.get("sonarr")
    assert cred is not None
    assert cred.api_key == "env-key"


# ---------------------------------------------------------------------------
# CredentialStore — stored file tier (tier 2)
# ---------------------------------------------------------------------------


def test_set_and_get_stored_credential(tmp_path: Path) -> None:
    store = CredentialStore(str(tmp_path))
    store.set(
        "radarr", ServiceCredential(api_key="radarr-key", base_url="http://radarr:7878")
    )
    cred = store.get("radarr")
    assert cred is not None
    assert cred.api_key == "radarr-key"
    assert cred.base_url == "http://radarr:7878"


def test_stored_credential_persists_across_store_instances(tmp_path: Path) -> None:
    store1 = CredentialStore(str(tmp_path))
    store1.set("lidarr", ServiceCredential(api_key="lidarr-key"))

    store2 = CredentialStore(str(tmp_path))
    cred = store2.get("lidarr")
    assert cred is not None
    assert cred.api_key == "lidarr-key"


def test_delete_removes_stored_credential(tmp_path: Path) -> None:
    store = CredentialStore(str(tmp_path))
    store.set("prowlarr", ServiceCredential(api_key="key"))
    store.delete("prowlarr")
    assert store.get("prowlarr") is None


def test_delete_nonexistent_service_is_noop(tmp_path: Path) -> None:
    store = CredentialStore(str(tmp_path))
    store.delete("doesnotexist")  # Should not raise


@pytest.mark.skipif(
    __import__("sys").platform == "win32",
    reason="chmod 0o600 is not enforced on Windows",
)
def test_credential_file_created_with_restricted_permissions(tmp_path: Path) -> None:
    store = CredentialStore(str(tmp_path))
    store.set("sonarr", ServiceCredential(api_key="key"))
    cred_file = tmp_path / ".arr-mcp-credentials.json"
    assert cred_file.exists()
    mode = oct(cred_file.stat().st_mode)[-3:]
    assert mode == "600"


# ---------------------------------------------------------------------------
# CredentialStore — XML autodiscovery tier (tier 3)
# ---------------------------------------------------------------------------


def test_autodiscover_api_key_from_xml(tmp_path: Path) -> None:
    svc_dir = tmp_path / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text(
        "<Config><ApiKey>discovered-key</ApiKey><Port>8989</Port></Config>"
    )
    store = CredentialStore(str(tmp_path))
    cred = store.get("sonarr")
    assert cred is not None
    assert cred.api_key == "discovered-key"


def test_autodiscover_missing_config_returns_none(tmp_path: Path) -> None:
    store = CredentialStore(str(tmp_path))
    assert store.get("sonarr") is None


def test_autodiscover_malformed_xml_returns_none(tmp_path: Path) -> None:
    svc_dir = tmp_path / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>not-closed</Config")
    store = CredentialStore(str(tmp_path))
    assert store.get("sonarr") is None


def test_stored_takes_priority_over_autodiscover(tmp_path: Path) -> None:
    svc_dir = tmp_path / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>xml-key</ApiKey></Config>")

    store = CredentialStore(str(tmp_path))
    store.set("sonarr", ServiceCredential(api_key="stored-key"))
    cred = store.get("sonarr")
    assert cred is not None
    assert cred.api_key == "stored-key"


# ---------------------------------------------------------------------------
# CredentialStore — list_configured
# ---------------------------------------------------------------------------


def test_list_configured_includes_env_var_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RADARR_API_KEY", "key")
    store = CredentialStore(str(tmp_path))
    assert "radarr" in store.list_configured()


def test_list_configured_includes_stored_services(tmp_path: Path) -> None:
    store = CredentialStore(str(tmp_path))
    store.set("lidarr", ServiceCredential(api_key="key"))
    assert "lidarr" in store.list_configured()


def test_list_configured_includes_autodiscovered_services(tmp_path: Path) -> None:
    svc_dir = tmp_path / "sonarr"
    svc_dir.mkdir()
    (svc_dir / "config.xml").write_text("<Config><ApiKey>key</ApiKey></Config>")
    store = CredentialStore(str(tmp_path))
    assert "sonarr" in store.list_configured()


def test_list_configured_never_returns_key_values(tmp_path: Path) -> None:
    store = CredentialStore(str(tmp_path))
    store.set("sonarr", ServiceCredential(api_key="super-secret-key"))
    for item in store.list_configured():
        assert "super-secret-key" not in item


# ---------------------------------------------------------------------------
# Encryption path
# ---------------------------------------------------------------------------


def test_encrypted_storage_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARR_MCP_SECRET", "test-secret-key")
    store = CredentialStore(str(tmp_path))
    store.set("sonarr", ServiceCredential(api_key="secret-key"))

    # Raw file should not contain plaintext key
    raw = (tmp_path / ".arr-mcp-credentials.json").read_text()
    assert "secret-key" not in raw

    # But retrieval should work
    cred = store.get("sonarr")
    assert cred is not None
    assert cred.api_key == "secret-key"


def test_plaintext_storage_when_no_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ARR_MCP_SECRET", raising=False)
    store = CredentialStore(str(tmp_path))
    store.set("sonarr", ServiceCredential(api_key="plainkey"))

    raw = (tmp_path / ".arr-mcp-credentials.json").read_text()
    assert "plainkey" in raw
