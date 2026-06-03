"""Tests for arr-agent input validation."""

from __future__ import annotations

import pytest

from arr_helper.validation import (
    MAX_CONTENT_BYTES,
    validate_content,
    validate_quadlet_name,
    validate_stack_name,
    validate_unit_name,
)


class TestStackName:
    def test_valid_simple(self) -> None:
        assert validate_stack_name("media") == "media"

    def test_valid_with_dash(self) -> None:
        assert validate_stack_name("my-stack") == "my-stack"

    def test_valid_with_underscore(self) -> None:
        assert validate_stack_name("my_stack") == "my_stack"

    def test_valid_alphanumeric(self) -> None:
        assert validate_stack_name("stack123") == "stack123"

    def test_rejects_slash(self) -> None:
        with pytest.raises(ValueError, match="Invalid stack name"):
            validate_stack_name("../../etc")

    def test_rejects_dot(self) -> None:
        with pytest.raises(ValueError, match="Invalid stack name"):
            validate_stack_name("my.stack")

    def test_rejects_space(self) -> None:
        with pytest.raises(ValueError, match="Invalid stack name"):
            validate_stack_name("my stack")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="Invalid stack name"):
            validate_stack_name("")

    def test_rejects_semicolon(self) -> None:
        with pytest.raises(ValueError, match="Invalid stack name"):
            validate_stack_name("media; rm -rf /")


class TestUnitName:
    def test_valid_service(self) -> None:
        assert validate_unit_name("plex.service") == "plex.service"

    def test_valid_container(self) -> None:
        assert validate_unit_name("plex.container") == "plex.container"

    def test_valid_with_at(self) -> None:
        assert validate_unit_name("arr@sonarr.service") == "arr@sonarr.service"

    def test_rejects_no_extension(self) -> None:
        with pytest.raises(ValueError, match="Invalid unit name"):
            validate_unit_name("plex")

    def test_rejects_wrong_extension(self) -> None:
        with pytest.raises(ValueError, match="Invalid unit name"):
            validate_unit_name("plex.timer")

    def test_rejects_slash(self) -> None:
        with pytest.raises(ValueError, match="Invalid unit name"):
            validate_unit_name("../etc/plex.service")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="Invalid unit name"):
            validate_unit_name("")


class TestQuadletName:
    def test_valid_simple(self) -> None:
        assert validate_quadlet_name("plex") == "plex"

    def test_valid_with_dash(self) -> None:
        assert validate_quadlet_name("my-service") == "my-service"

    def test_rejects_dot(self) -> None:
        with pytest.raises(ValueError, match="Invalid quadlet name"):
            validate_quadlet_name("plex.container")

    def test_rejects_slash(self) -> None:
        with pytest.raises(ValueError, match="Invalid quadlet name"):
            validate_quadlet_name("../plex")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="Invalid quadlet name"):
            validate_quadlet_name("")


class TestContent:
    def test_valid_content(self) -> None:
        assert validate_content("hello") == "hello"

    def test_empty_content(self) -> None:
        assert validate_content("") == ""

    def test_rejects_oversized(self) -> None:
        big = "x" * (MAX_CONTENT_BYTES + 1)
        with pytest.raises(ValueError, match="maximum size"):
            validate_content(big)

    def test_accepts_at_limit(self) -> None:
        at_limit = "x" * MAX_CONTENT_BYTES
        assert validate_content(at_limit) == at_limit
