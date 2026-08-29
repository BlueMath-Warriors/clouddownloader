"""Runnable examples.

    python examples/basic.py <share-url>
"""

from __future__ import annotations

import asyncio
import logging
import sys

from clouddownloader import (
    CloudDownloader,
    DownloadFailed,
    DownloadTimeout,
    FileTooLarge,
    Limits,
    UnsupportedProviderError,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")


async def single_file(url: str) -> None:
    async with CloudDownloader() as downloader:
        result = await downloader.download(url, destination="./downloads")
        print(f"{result.filename}  {result.size_mb:.1f}MB  {result.elapsed_seconds:.1f}s")


async def whole_folder(url: str) -> None:
    """Folder shares yield every file, not just the first."""
    limits = Limits(max_files_per_folder=50, max_file_size_mb=250)

    async with CloudDownloader(limits=limits) as downloader:
        results = await downloader.download_all(url, destination="./downloads")
        for result in results:
            print(f"  {result}")
        print(f"{len(results)} files")


async def many_urls(urls: list[str]) -> None:
    """Reuse one browser across a batch - launching costs ~1s each time.

    ``download_or_none`` keeps one dead link from sinking the batch.
    """
    async with CloudDownloader() as downloader:
        for url in urls:
            result = await downloader.download_or_none(url, destination="./downloads")
            print(f"{'ok  ' if result else 'skip'} {url[:60]}")


async def handling_errors(url: str) -> None:
    """Each failure mode is a distinct type, because they need different responses."""
    async with CloudDownloader() as downloader:
        try:
            result = await downloader.download(url, destination="./downloads")
        except UnsupportedProviderError:
            print("unknown host - register a custom Provider")
        except DownloadTimeout:
            print("timed out - retryable, browser was torn down cleanly")
        except FileTooLarge as exc:
            print(f"too big: {exc.size_bytes / 1024 / 1024:.0f}MB - raise Limits.max_file_size_mb")
        except DownloadFailed as exc:
            print(f"share unavailable. tried: {'; '.join(exc.attempts)}")
        else:
            print(f"got {result.path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    asyncio.run(handling_errors(sys.argv[1]))
