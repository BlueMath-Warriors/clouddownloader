"""Dropbox."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ..session import PageSession
from .base import Provider


def force_download_url(url: str) -> str:
    """Rewrite a share URL to ``dl=1``.

    ``dl=0`` renders the preview page; ``dl=1`` streams the bytes. For a
    *folder* share it streams a generated ZIP, so one code path covers both.

    Parse the query properly rather than string-replacing ``dl=0``: modern
    links put ``rlkey`` first, so ``dl`` arrives as ``&dl=0`` and a naive
    ``?dl=0`` replace misses it entirely.
    """
    parts = urlparse(url)
    params = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "dl"]
    params.append(("dl", "1"))
    return urlunparse(parts._replace(query=urlencode(params)))


class DropboxProvider(Provider):
    """Dropbox shared files and folders."""

    name = "dropbox"
    # Listed before Box so intent is obvious to a reader, though host-boundary
    # matching means "dropbox.com" can no longer be caught by "box.com".
    priority = 50
    match_hosts = ("dropbox.com", "dropboxusercontent.com")

    _BUTTON_SELECTORS = (
        '[data-testid="download-button"]',
        'button:has-text("Download")',
        'a:has-text("Download")',
        ".download-button",
    )

    async def fetch(self, session: PageSession, url: str) -> list[Path]:
        target = force_download_url(url)
        session.note("dl=1 direct download")

        path = await session.capture_download(
            lambda: session.goto(target, wait_until="commit", timeout=15.0)
        )
        if path:
            return [path]

        session.note("fallback to preview page buttons")
        await session.goto(url)
        await session.dismiss_consent()
        path = await session.click_any(self._BUTTON_SELECTORS)
        return [path] if path else []
