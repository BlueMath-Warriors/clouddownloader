"""Box."""

from __future__ import annotations

from pathlib import Path

from ..session import PageSession
from .base import Provider


class BoxProvider(Provider):
    """Box public shared links, file or folder.

    Box is a single-page app: the toolbar mounts after ``networkidle``, so
    querying immediately finds nothing. For a folder share the same button
    streams the whole folder as a generated ZIP.
    """

    name = "box"
    match_hosts = ("box.com", "app.box.com", "boxcloud.com")

    _SELECTORS = (
        'button[aria-label="Download"]',
        'button[data-testid="download-button"]',
        'button[data-resin-target="bulkdownload"]',
        'button[data-resin-target="download"]',
        'button:has-text("Download")',
        'a:has-text("Download")',
    )

    async def fetch(self, session: PageSession, url: str) -> list[Path]:
        await session.goto(url)
        # Box renders a consent banner that overlays the toolbar. Left in
        # place it swallows the click and the failure looks like a timeout.
        await session.dismiss_consent()
        await session.settle()

        path = await session.click_any(self._SELECTORS)
        return [path] if path else []
