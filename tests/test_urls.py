"""URL rewriting and id extraction."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from clouddownloader.providers.dropbox import force_download_url
from clouddownloader.providers.gdrive import extract_file_id, is_folder


class TestGoogleDriveIds:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://drive.google.com/file/d/1AbC_dEf-GhI/view", "1AbC_dEf-GhI"),
            ("https://drive.google.com/file/d/1AbC_dEf-GhI/view?usp=sharing", "1AbC_dEf-GhI"),
            ("https://drive.google.com/open?id=1AbC_dEf-GhI", "1AbC_dEf-GhI"),
            ("https://drive.google.com/uc?export=download&id=1AbC_dEf-GhI", "1AbC_dEf-GhI"),
            ("https://drive.google.com/drive/folders/1FolderIdHere_x", "1FolderIdHere_x"),
            ("https://docs.google.com/document/d/1AbC_dEf-GhI/edit", "1AbC_dEf-GhI"),
        ],
    )
    def test_extraction(self, url: str, expected: str) -> None:
        assert extract_file_id(url) == expected

    def test_no_id_present(self) -> None:
        assert extract_file_id("https://drive.google.com/") is None

    def test_short_ids_are_rejected(self) -> None:
        """Real Drive ids are long; a short /d/ segment is a different route."""
        assert extract_file_id("https://drive.google.com/file/d/abc/view") is None

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://drive.google.com/drive/folders/1AbC_dEf-GhI", True),
            ("https://drive.google.com/file/d/1AbC_dEf-GhI/view", False),
        ],
    )
    def test_folder_detection(self, url: str, expected: bool) -> None:
        assert is_folder(url) is expected


class TestDropboxRewrite:
    def _dl(self, url: str) -> list[str]:
        return parse_qs(urlparse(force_download_url(url)).query).get("dl", [])

    def test_dl_zero_becomes_one(self) -> None:
        assert self._dl("https://www.dropbox.com/s/abc/f.zip?dl=0") == ["1"]

    def test_dl_one_is_preserved(self) -> None:
        assert self._dl("https://www.dropbox.com/s/abc/f.zip?dl=1") == ["1"]

    def test_added_when_absent(self) -> None:
        assert self._dl("https://www.dropbox.com/s/abc/f.zip") == ["1"]

    def test_modern_rlkey_link(self) -> None:
        """The case a naive '?dl=0' -> '?dl=1' replace misses.

        Modern share links put rlkey first, so dl arrives as '&dl=0'.
        """
        url = "https://www.dropbox.com/scl/fi/abc/f.zip?rlkey=xyz123&st=abc&dl=0"
        assert self._dl(url) == ["1"]

    def test_other_params_survive(self) -> None:
        rewritten = force_download_url(
            "https://www.dropbox.com/scl/fi/abc/f.zip?rlkey=xyz123&st=q1w2&dl=0"
        )
        params = parse_qs(urlparse(rewritten).query)
        assert params["rlkey"] == ["xyz123"]
        assert params["st"] == ["q1w2"]
        assert params["dl"] == ["1"]

    def test_exactly_one_dl_param(self) -> None:
        rewritten = force_download_url("https://www.dropbox.com/s/abc/f.zip?dl=0&dl=0")
        assert parse_qs(urlparse(rewritten).query)["dl"] == ["1"]

    def test_path_is_untouched(self) -> None:
        rewritten = force_download_url("https://www.dropbox.com/scl/fi/abc/my file.zip?dl=0")
        assert urlparse(rewritten).path == "/scl/fi/abc/my file.zip"
