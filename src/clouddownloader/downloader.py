"""Public API."""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path
from types import TracebackType
from typing import Any

from .browser import BrowserPool
from .config import BrowserConfig, Limits
from .errors import (
    CloudDownloadError,
    DownloadFailed,
    DownloadTimeout,
    UnsupportedProviderError,
)
from .providers import Provider
from .providers.wrapper import LinkWrapperProvider
from .registry import ProviderRegistry
from .result import DownloadResult
from .session import PageSession

logger = logging.getLogger(__name__)


class CloudDownloader:
    """Download files from cloud share links using a headless browser.

    ::

        async with CloudDownloader() as downloader:
            result = await downloader.download(url, destination="./files")
            print(result.path)

    One instance holds one Chromium and reuses it. Create it once and keep
    it; construction is cheap, launching is not.

    Not safe to share across event loops or threads. For a multi-worker
    service, one instance per worker.
    """

    def __init__(
        self,
        *,
        limits: Limits | None = None,
        browser: BrowserConfig | None = None,
        providers: list[Provider] | None = None,
    ) -> None:
        self.limits = limits or Limits()
        self.registry = ProviderRegistry(providers)
        self._pool = BrowserPool(browser or BrowserConfig(), self.limits)
        self._wire_wrappers()

    def _wire_wrappers(self) -> None:
        """Give wrapper providers a way back into the registry."""
        for provider in self.registry.providers:
            if isinstance(provider, LinkWrapperProvider):
                provider.resolve = self.registry.resolve  # type: ignore[attr-defined]

    # -- registration ----------------------------------------------------

    def register(self, provider: Provider) -> None:
        """Add or replace a provider."""
        self.registry.register(provider)
        self._wire_wrappers()

    def supports(self, url: str) -> bool:
        """True if some provider claims this URL. No network access."""
        return self.registry.supports(url)

    # -- downloading -----------------------------------------------------

    async def download(self, url: str, *, destination: str | Path | None = None) -> DownloadResult:
        """Download a single file.

        For a folder share this returns the first file; use
        ``download_all()`` to get everything.

        Raises ``UnsupportedProviderError``, ``DownloadTimeout``,
        ``FileTooLarge``, ``BrowserLaunchError`` or ``DownloadFailed``.
        """
        results = await self.download_all(url, destination=destination)
        return results[0]

    async def download_all(
        self, url: str, *, destination: str | Path | None = None
    ) -> list[DownloadResult]:
        """Download every file behind ``url``.

        A file share yields one result; a folder share yields up to
        ``Limits.max_files_per_folder``. Never returns an empty list -
        nothing found is a ``DownloadFailed``.
        """
        provider = self.registry.resolve(url)
        if provider is None:
            raise UnsupportedProviderError(
                f"no provider handles this URL. Registered: {', '.join(self.registry.names())}",
                url=url,
            )

        target_dir = Path(destination) if destination else Path(tempfile.mkdtemp(prefix="clouddl-"))
        target_dir.mkdir(parents=True, exist_ok=True)

        started = time.monotonic()
        logger.info("[%s] %s", provider.name, url[:100])

        try:
            paths, attempts = await asyncio.wait_for(
                self._run(provider, url, target_dir),
                timeout=self.limits.total_timeout,
            )
        except asyncio.TimeoutError as exc:
            # The browser is mid-hang. Kill it rather than returning it to
            # the pool, or every later call inherits the wedged process.
            await self._pool.force_close()
            raise DownloadTimeout(
                f"exceeded the {self.limits.total_timeout}s total deadline",
                url=url,
                seconds=self.limits.total_timeout,
            ) from exc

        if not paths:
            raise DownloadFailed(
                "provider found no downloadable file - the share may have expired, "
                "been revoked, or require a sign-in",
                url=url,
                provider=provider.name,
                attempts=attempts,
            )

        elapsed = time.monotonic() - started
        return [
            DownloadResult(
                path=path,
                filename=path.name,
                size_bytes=path.stat().st_size,
                provider=provider.name,
                source_url=url,
                elapsed_seconds=elapsed,
            )
            for path in paths
        ]

    async def download_or_none(
        self, url: str, *, destination: str | Path | None = None
    ) -> DownloadResult | None:
        """``download()`` that returns None instead of raising.

        For pipelines where one bad link must not fail the batch. Errors are
        logged at WARNING. Programming errors still propagate.
        """
        try:
            return await self.download(url, destination=destination)
        except CloudDownloadError as exc:
            logger.warning("download failed for %s: %s", url[:80], exc)
            return None

    async def _run(
        self, provider: Provider, url: str, destination: Path
    ) -> tuple[list[Path], list[str]]:
        """One download attempt in a throwaway browser context."""
        context = await self._pool.new_context()
        try:
            page = await context.new_page()
            session = PageSession(page, destination=destination, limits=self.limits)
            paths = await provider.fetch(session, url)
            return paths, session.attempts
        finally:
            # Contexts are cheap but not free - an unclosed one keeps its
            # renderer alive for the life of the browser.
            try:
                await context.close()
            except Exception as exc:
                logger.debug("context close failed: %s", exc)

    # -- lifecycle -------------------------------------------------------

    async def close(self) -> None:
        """Shut down the browser. Safe to call more than once."""
        await self._pool.close()

    async def __aenter__(self) -> CloudDownloader:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()


# -- synchronous facade --------------------------------------------------


def download(url: str, *, destination: str | Path | None = None, **kwargs: Any) -> DownloadResult:
    """Blocking one-shot download.

    Launches and tears down a browser per call, so it costs ~1s more than
    the async API. Fine for scripts and CLIs; use ``CloudDownloader``
    directly in a service.

    Raises RuntimeError if called from inside a running event loop - use
    ``await CloudDownloader().download(...)`` there instead.
    """
    return _run_sync(_download_once(url, destination, kwargs))


def download_all(
    url: str, *, destination: str | Path | None = None, **kwargs: Any
) -> list[DownloadResult]:
    """Blocking version of ``CloudDownloader.download_all``."""
    return _run_sync(_download_all_once(url, destination, kwargs))


async def _download_once(
    url: str, destination: str | Path | None, kwargs: dict[str, Any]
) -> DownloadResult:
    async with CloudDownloader(**kwargs) as downloader:
        return await downloader.download(url, destination=destination)


async def _download_all_once(
    url: str, destination: str | Path | None, kwargs: dict[str, Any]
) -> list[DownloadResult]:
    async with CloudDownloader(**kwargs) as downloader:
        return await downloader.download_all(url, destination=destination)


def _run_sync(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    coro.close()
    raise RuntimeError(
        "the synchronous API cannot be called from a running event loop. "
        "Use 'await CloudDownloader().download(...)' instead."
    )
