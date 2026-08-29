"""Filename sanitising and collision handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from clouddownloader.session import safe_filename, unique_path


class TestSafeFilename:
    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("report.pdf", "report.pdf"),
            ("Album Cover.JPG", "Album Cover.jpg"),
            ("archive.tar.gz", "archive.tar.gz"),
        ],
    )
    def test_ordinary_names_survive(self, given: str, expected: str) -> None:
        assert safe_filename(given) == expected

    @pytest.mark.parametrize(
        "attack",
        [
            "../../../etc/passwd",
            "..\\..\\windows\\system32\\config",
            "/etc/cron.d/backdoor",
            "....//....//etc/shadow",
        ],
    )
    def test_path_traversal_is_stripped(self, attack: str) -> None:
        """A server-supplied filename must not escape the destination."""
        result = safe_filename(attack)
        assert "/" not in result
        assert "\\" not in result
        assert not result.startswith(".")

    def test_control_characters_removed(self) -> None:
        assert "\x00" not in safe_filename("evil\x00name.pdf")
        assert "\n" not in safe_filename("two\nlines.pdf")

    @pytest.mark.parametrize("given", ["", None, "   ", "...", "/"])
    def test_empty_names_get_a_fallback(self, given: str | None) -> None:
        assert safe_filename(given) == "download.bin"

    def test_extensionless_gets_bin(self) -> None:
        assert safe_filename("README") == "README.bin"

    def test_absurd_extension_is_not_treated_as_one(self) -> None:
        result = safe_filename("file.thisisnotanextension")
        assert result.endswith(".bin")

    def test_long_names_are_bounded(self) -> None:
        result = safe_filename("a" * 500 + ".pdf")
        assert len(result) < 200
        assert result.endswith(".pdf")

    def test_custom_fallback_stem(self) -> None:
        assert safe_filename(None, fallback_stem="gdrive") == "gdrive.bin"


class TestUniquePath:
    def test_free_name_used_directly(self, tmp_path: Path) -> None:
        assert unique_path(tmp_path, "a.jpg") == tmp_path / "a.jpg"

    def test_collision_gets_a_suffix(self, tmp_path: Path) -> None:
        (tmp_path / "cover.jpg").write_text("first")
        assert unique_path(tmp_path, "cover.jpg") == tmp_path / "cover-1.jpg"

    def test_repeated_collisions_keep_counting(self, tmp_path: Path) -> None:
        (tmp_path / "cover.jpg").write_text("x")
        (tmp_path / "cover-1.jpg").write_text("x")
        (tmp_path / "cover-2.jpg").write_text("x")
        assert unique_path(tmp_path, "cover.jpg") == tmp_path / "cover-3.jpg"

    def test_existing_file_is_never_overwritten(self, tmp_path: Path) -> None:
        """Folder shares routinely contain several 'cover.jpg'."""
        original = tmp_path / "cover.jpg"
        original.write_text("do not lose me")
        resolved = unique_path(tmp_path, "cover.jpg")
        assert resolved != original
        assert original.read_text() == "do not lose me"
