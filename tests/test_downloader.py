"""Downloader orchestration, using a fake browser.

These cover the parts that actually break in production - timeout teardown,
error typing, context cleanup - without needing a real Chromium.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from clouddownloader import (
    CloudDownloader,
    DownloadFailed,
    DownloadTimeout,
    Limits,
    Provider,
    UnsupportedProviderError,
)
from clouddownloader.config import BrowserConfig


class FakeContext:
    def __init__(self, owner: FakeBrowserPool) -> None:
        self._owner = owner
        self.closed = False

    async def new_page(self) -> object:
        return object()

    async def close(self) -> None:
        self.closed = True
        self._owner.closed_contexts += 1


class FakeBrowserPool:
    """Stands in for BrowserPool without launching anything."""

    def __init__(self) -> None:
        self.contexts: list[FakeContext] = []
        self.closed_contexts = 0
        self.force_closed = 0
        self.closed = 0

    async def new_context(self) -> FakeContext:
        context = FakeContext(self)
        self.contexts.append(context)
        return context

    async def force_close(self) -> None:
        self.force_closed += 1

    async def close(self) -> None:
        self.closed += 1


def make_downloader(
    provider: Provider, **kwargs: object
) -> tuple[CloudDownloader, FakeBrowserPool]:
    downloader = CloudDownloader(providers=[provider], **kwargs)  # type: ignore[arg-type]
    pool = FakeBrowserPool()
    downloader._pool = pool  # type: ignore[assignment]
    return downloader, pool


class SucceedingProvider(Provider):
    name = "fake"
    match_hosts = ("example.com",)

    def __init__(self, files: list[str]) -> None:
        self.files = files

    async def fetch(self, session, url):  # type: ignore[no-untyped-def]
        paths = []
        for name in self.files:
            path = session.destination / name
            path.write_bytes(b"x" * 1024)
            paths.append(path)
        return paths


class EmptyProvider(Provider):
    name = "fake"
    match_hosts = ("example.com",)

    async def fetch(self, session, url):  # type: ignore[no-untyped-def]
        session.note("tried selector A")
        session.note("tried selector B")
        return []


class HangingProvider(Provider):
    name = "fake"
    match_hosts = ("example.com",)

    async def fetch(self, session, url):  # type: ignore[no-untyped-def]
        await asyncio.sleep(60)
        return []


class ExplodingProvider(Provider):
    name = "fake"
    match_hosts = ("example.com",)

    async def fetch(self, session, url):  # type: ignore[no-untyped-def]
        raise RuntimeError("provider blew up")


class TestSuccess:
    async def test_single_file(self, tmp_path: Path) -> None:
        downloader, _ = make_downloader(SucceedingProvider(["a.pdf"]))
        result = await downloader.download("https://example.com/x", destination=tmp_path)

        assert result.filename == "a.pdf"
        assert result.size_bytes == 1024
        assert result.provider == "fake"
        assert result.source_url == "https://example.com/x"
        assert result.elapsed_seconds >= 0

    async def test_download_returns_first_of_many(self, tmp_path: Path) -> None:
        downloader, _ = make_downloader(SucceedingProvider(["a.pdf", "b.pdf", "c.pdf"]))
        result = await downloader.download("https://example.com/x", destination=tmp_path)
        assert result.filename == "a.pdf"

    async def test_download_all_returns_everything(self, tmp_path: Path) -> None:
        """The original pipeline version discarded all but the first file."""
        downloader, _ = make_downloader(SucceedingProvider(["a.pdf", "b.pdf", "c.pdf"]))
        results = await downloader.download_all("https://example.com/x", destination=tmp_path)
        assert [r.filename for r in results] == ["a.pdf", "b.pdf", "c.pdf"]

    async def test_destination_is_created(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "deep"
        downloader, _ = make_downloader(SucceedingProvider(["a.pdf"]))
        result = await downloader.download("https://example.com/x", destination=target)
        assert result.path.parent == target

    async def test_size_helpers(self, tmp_path: Path) -> None:
        downloader, _ = make_downloader(SucceedingProvider(["a.pdf"]))
        result = await downloader.download("https://example.com/x", destination=tmp_path)
        assert result.size_mb == pytest.approx(1024 / 1024 / 1024)
        assert result.suffix == ".pdf"


class TestFailures:
    async def test_unsupported_url(self, tmp_path: Path) -> None:
        downloader, _ = make_downloader(SucceedingProvider(["a.pdf"]))
        with pytest.raises(UnsupportedProviderError) as exc:
            await downloader.download("https://nope.invalid/x", destination=tmp_path)
        assert exc.value.url == "https://nope.invalid/x"

    async def test_nothing_found_reports_attempts(self, tmp_path: Path) -> None:
        downloader, _ = make_downloader(EmptyProvider())
        with pytest.raises(DownloadFailed) as exc:
            await downloader.download("https://example.com/x", destination=tmp_path)

        assert exc.value.provider == "fake"
        assert exc.value.attempts == ["tried selector A", "tried selector B"]

    async def test_timeout_is_typed_and_bounded(self, tmp_path: Path) -> None:
        downloader, _ = make_downloader(HangingProvider())
        downloader.limits = Limits(total_timeout=0.2, navigation_timeout=0.1)

        with pytest.raises(DownloadTimeout) as exc:
            await downloader.download("https://example.com/x", destination=tmp_path)
        assert exc.value.seconds == 0.2

    async def test_timeout_force_closes_the_browser(self, tmp_path: Path) -> None:
        """A wedged Chromium must not be handed to the next caller."""
        downloader, pool = make_downloader(HangingProvider())
        downloader.limits = Limits(total_timeout=0.2, navigation_timeout=0.1)

        with pytest.raises(DownloadTimeout):
            await downloader.download("https://example.com/x", destination=tmp_path)
        assert pool.force_closed == 1

    async def test_context_closed_even_when_provider_raises(self, tmp_path: Path) -> None:
        downloader, pool = make_downloader(ExplodingProvider())

        with pytest.raises(RuntimeError, match="blew up"):
            await downloader.download("https://example.com/x", destination=tmp_path)
        assert pool.closed_contexts == 1

    async def test_context_closed_on_success(self, tmp_path: Path) -> None:
        downloader, pool = make_downloader(SucceedingProvider(["a.pdf"]))
        await downloader.download("https://example.com/x", destination=tmp_path)
        assert pool.closed_contexts == 1

    async def test_download_or_none_swallows_library_errors(self, tmp_path: Path) -> None:
        downloader, _ = make_downloader(EmptyProvider())
        result = await downloader.download_or_none("https://example.com/x", destination=tmp_path)
        assert result is None

    async def test_download_or_none_lets_bugs_through(self, tmp_path: Path) -> None:
        """A RuntimeError in a provider is a bug, not a bad link."""
        downloader, _ = make_downloader(ExplodingProvider())
        with pytest.raises(RuntimeError):
            await downloader.download_or_none("https://example.com/x", destination=tmp_path)


class TestLifecycle:
    async def test_context_manager_closes_pool(self, tmp_path: Path) -> None:
        downloader, pool = make_downloader(SucceedingProvider(["a.pdf"]))
        async with downloader:
            await downloader.download("https://example.com/x", destination=tmp_path)
        assert pool.closed == 1

    async def test_close_is_idempotent(self) -> None:
        downloader, pool = make_downloader(SucceedingProvider([]))
        await downloader.close()
        await downloader.close()
        assert pool.closed == 2

    async def test_browser_reused_across_downloads(self, tmp_path: Path) -> None:
        downloader, pool = make_downloader(SucceedingProvider(["a.pdf"]))
        for _ in range(3):
            await downloader.download("https://example.com/x", destination=tmp_path)
        # Three isolated contexts, one browser.
        assert len(pool.contexts) == 3
        assert pool.force_closed == 0

    def test_supports_needs_no_network(self) -> None:
        downloader, _ = make_downloader(SucceedingProvider([]))
        assert downloader.supports("https://example.com/x")
        assert not downloader.supports("https://other.invalid/x")


class TestSyncFacade:
    async def test_refuses_to_run_inside_a_loop(self) -> None:
        from clouddownloader import download as sync_download

        with pytest.raises(RuntimeError, match="running event loop"):
            sync_download("https://example.com/x")


class TestConfigValidation:
    def test_rejects_zero_size_cap(self) -> None:
        with pytest.raises(ValueError, match="max_file_size_mb"):
            Limits(max_file_size_mb=0)

    def test_rejects_total_below_navigation(self) -> None:
        """Otherwise the overall deadline fires before one page can load."""
        with pytest.raises(ValueError, match="total_timeout"):
            Limits(navigation_timeout=60, total_timeout=30)

    def test_rejects_zero_folder_cap(self) -> None:
        with pytest.raises(ValueError, match="max_files_per_folder"):
            Limits(max_files_per_folder=0)

    def test_byte_conversion(self) -> None:
        assert Limits(max_file_size_mb=2).max_file_size_bytes == 2 * 1024 * 1024

    def test_container_args_present_by_default(self) -> None:
        """Chromium will not start in most containers without these."""
        args = BrowserConfig().args
        assert "--no-sandbox" in args
        assert "--disable-dev-shm-usage" in args
