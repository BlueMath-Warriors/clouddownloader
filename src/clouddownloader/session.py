"""Page-level helpers shared by every provider.

Providers differ only in *which* selectors and URLs to try. The mechanics of
capturing a download, naming it safely and enforcing the size cap are
identical, and live here so a new provider is ~30 lines.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from .config import Limits
from .errors import FileTooLarge

logger = logging.getLogger(__name__)

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_STEM = 120


def safe_filename(suggested: str | None, *, fallback_stem: str = "download") -> str:
    """Turn a server-supplied filename into something safe to write.

    Server-controlled strings reaching ``open()`` is a path traversal waiting
    to happen - a share advertising ``../../../etc/cron.d/x`` should not be
    able to escape the destination directory. Strip directory components,
    drop control and reserved characters, and bound the length.
    """
    name = (suggested or "").strip()
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE_CHARS.sub("_", name).strip(". ")

    if not name:
        return f"{fallback_stem}.bin"

    if "." in name:
        stem, _, ext = name.rpartition(".")
        ext = ext.lower()
        # A 30-character "extension" is not an extension.
        if not ext or len(ext) > 12 or not ext.isalnum():
            stem, ext = name, "bin"
    else:
        stem, ext = name, "bin"

    stem = stem[:_MAX_STEM] or fallback_stem
    return f"{stem}.{ext}"


def unique_path(directory: Path, filename: str) -> Path:
    """Resolve a collision-free path inside ``directory``.

    Folder shares routinely contain several ``cover.jpg``. Overwriting is
    silent data loss, so append ``-1``, ``-2``, ... instead.
    """
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    stem, _, ext = filename.rpartition(".")
    for n in range(1, 1000):
        candidate = directory / f"{stem}-{n}.{ext}"
        if not candidate.exists():
            return candidate

    raise FileExistsError(f"could not find a free filename for {filename} in {directory}")


class PageSession:
    """A page plus the helpers providers need.

    Wraps one Playwright page. Providers never touch tempfiles, size checks
    or timeouts directly.
    """

    def __init__(self, page: Any, *, destination: Path, limits: Limits) -> None:
        self.page = page
        self.destination = destination
        self.limits = limits
        self.attempts: list[str] = []

    def note(self, what: str) -> None:
        """Record a strategy attempt, surfaced on ``DownloadFailed``."""
        self.attempts.append(what)
        logger.debug("attempt: %s", what)

    @property
    def url(self) -> str:
        return self.page.url

    async def goto(
        self, url: str, *, wait_until: str = "networkidle", timeout: float | None = None
    ) -> bool:
        """Navigate, returning False instead of raising on failure.

        ``networkidle`` legitimately times out on pages holding a long-poll
        open; the page is usually still usable, so a timeout here is not
        fatal on its own.
        """
        ms = int((timeout if timeout is not None else self.limits.navigation_timeout) * 1000)
        try:
            await self.page.goto(url, wait_until=wait_until, timeout=ms)
            return True
        except Exception as exc:
            logger.debug("navigation to %s did not settle: %s", url[:80], exc)
            return False

    async def settle(self) -> None:
        """Give a single-page app time to mount its toolbar."""
        await asyncio.sleep(self.limits.spa_settle_delay)

    async def dismiss_consent(self, selectors: Sequence[str] = ()) -> None:
        """Click away a cookie banner if one is covering the UI.

        An overlay does not hide the download button, it *intercepts the
        click* - which surfaces as a timeout rather than "not found", so it
        is worth ruling out before blaming selectors.
        """
        candidates = list(selectors) or [
            "#onetrust-accept-btn-handler",
            'button:has-text("Accept all")',
            'button:has-text("Accept")',
            'button:has-text("I agree")',
            'button:has-text("Agree")',
        ]
        for selector in candidates:
            try:
                button = await self.page.query_selector(selector)
                if button and await button.is_visible():
                    await button.click(timeout=5000)
                    logger.debug("dismissed consent banner via %s", selector)
                    await self.page.wait_for_load_state("networkidle", timeout=10000)
                    return
            except Exception:
                continue

    async def capture_download(self, action: Any, *, timeout: float | None = None) -> Path | None:
        """Run ``action`` and save whatever download it triggers.

        ``action`` is a zero-arg coroutine function. The listener is armed
        *before* it runs - a fast server can start the transfer before a
        ``click()`` call has even returned, and arming afterwards loses it.
        """
        ms = int((timeout if timeout is not None else self.limits.navigation_timeout) * 1000)
        try:
            async with self.page.expect_download(timeout=ms) as info:
                try:
                    await action()
                except Exception as exc:
                    # Navigating to a direct-download URL aborts the page load
                    # by design - the browser gets Content-Disposition instead
                    # of a document. That is success, not failure, so keep
                    # waiting for the download event.
                    logger.debug("action raised while waiting for download: %s", exc)
            download = await info.value
        except Exception as exc:
            logger.debug("no download captured: %s", exc)
            return None

        return await self.save(download)

    async def save(self, download: Any) -> Path:
        """Persist a Playwright download, enforcing the size cap."""
        filename = safe_filename(download.suggested_filename)
        target = unique_path(self.destination, filename)

        await download.save_as(target)

        size = os.path.getsize(target)
        if size > self.limits.max_file_size_bytes:
            os.unlink(target)
            raise FileTooLarge(
                f"{filename} is {size / 1024 / 1024:.1f}MB, over the "
                f"{self.limits.max_file_size_mb}MB limit",
                size_bytes=size,
            )

        logger.info("saved %s (%d bytes)", target.name, size)
        return target

    async def click_any(
        self, selectors: Iterable[str], *, timeout: float | None = None
    ) -> Path | None:
        """Try each selector until one yields a download.

        Providers ship a list because these UIs are A/B tested and
        re-skinned without notice; a single selector is a support ticket
        waiting to happen. Ordered most to least specific.
        """
        for selector in selectors:
            try:
                button = await self.page.query_selector(selector)
            except Exception:
                continue
            if not button:
                continue

            self.note(f"click {selector}")
            path = await self.capture_download(button.click, timeout=timeout)
            if path is not None:
                return path

        return None

    async def find_in_page_source(self, patterns: Sequence[str]) -> str | None:
        """Pull a URL out of the page's embedded JSON.

        Last resort for apps that render the real download URL into inline
        script state but only wire up the button after a signed-in check.
        """
        try:
            content = await self.page.content()
        except Exception:
            return None

        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                raw = match.group(1)
                try:
                    # Inline JSON escapes non-ASCII as \uXXXX.
                    return raw.encode("utf-8", "surrogatepass").decode("unicode_escape")
                except (UnicodeDecodeError, UnicodeEncodeError):
                    return raw
        return None
