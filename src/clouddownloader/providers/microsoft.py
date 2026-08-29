"""SharePoint and OneDrive.

Both are the same Microsoft front-end with different chrome, so they share
selectors and a base implementation.
"""

from __future__ import annotations

from pathlib import Path

from ..session import PageSession
from .base import Provider

# Ordered most to least specific. The aria-label variants carry the full
# sentence Microsoft uses on the file preview page; the data-automationid
# ones survive re-skins better. Keep both - which UI you land on depends on
# file type, tenant settings and view mode.
_SELECTORS = (
    'button[aria-label="Download this file to your device"]',
    'button[data-automationid="downloadCommand"]',
    '[data-automationid="DownloadCommand"]',
    'button[name="Download"]',
    '[aria-label="Download"]',
    'button[aria-label*="Download" i]',
    'button:has-text("Download")',
    '[data-icon-name="Download"]',
    '.ms-CommandBar button:has([data-icon-name="Download"])',
    '.od-CommandBar button[name="Download"]',
)

# The preview page embeds a pre-signed URL in inline script state. Works when
# the button is present but disabled behind a sign-in check.
_URL_PATTERNS = (
    r'"@content\.downloadUrl"\s*:\s*"([^"]+)"',
    r'"downloadUrl"\s*:\s*"([^"]+)"',
    r'"@content\.mediaUrl"\s*:\s*"([^"]+)"',
)


class _MicrosoftProvider(Provider):
    async def fetch(self, session: PageSession, url: str) -> list[Path]:
        await session.goto(url)
        await session.settle()
        await session.dismiss_consent()

        path = await session.click_any(_SELECTORS)
        if path:
            return [path]

        session.note("scrape pre-signed downloadUrl from page state")
        embedded = await session.find_in_page_source(_URL_PATTERNS)
        if embedded:
            path = await session.capture_download(
                lambda: session.goto(embedded, wait_until="commit", timeout=15.0)
            )
            if path:
                return [path]

        return []


class SharePointProvider(_MicrosoftProvider):
    """SharePoint document library shares."""

    name = "sharepoint"
    match_hosts = ("sharepoint.com",)


class OneDriveProvider(_MicrosoftProvider):
    """OneDrive personal and business shares."""

    name = "onedrive"
    match_hosts = ("onedrive.live.com", "1drv.ms", "onedrive.com")
