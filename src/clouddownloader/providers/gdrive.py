"""Google Drive."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..session import PageSession
from .base import Provider

logger = logging.getLogger(__name__)

_FILE_ID_PATTERNS = (
    re.compile(r"/(?:file/)?d/([a-zA-Z0-9_-]{10,})"),
    re.compile(r"/folders/([a-zA-Z0-9_-]{10,})"),
)

# Drive IDs are long. Anything shorter is a UI element's data-id, not a file.
_MIN_ID_LENGTH = 20


def extract_file_id(url: str) -> str | None:
    """Pull the file or folder id out of any Drive URL shape."""
    for pattern in _FILE_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)

    params = parse_qs(urlparse(url).query)
    for key in ("id", "docid"):
        if key in params and params[key]:
            return params[key][0]
    return None


def is_folder(url: str) -> bool:
    return "/folders/" in url or "folderview" in url


def direct_url(file_id: str) -> str:
    return f"https://drive.google.com/uc?export=download&id={file_id}"


class GoogleDriveProvider(Provider):
    """Google Drive files and folders.

    Two wrinkles worth knowing:

    * Anything over ~100MB cannot be virus-scanned, so Drive serves an
      interstitial with a confirm form instead of the file. The direct URL
      silently returns HTML, not bytes.
    * Folder contents are rendered client-side. There is no public listing
      endpoint for an anonymous share, so the ids are scraped from the DOM.
    """

    name = "google-drive"
    match_hosts = ("drive.google.com", "docs.google.com", "drive.usercontent.google.com")

    _BUTTON_SELECTORS = (
        "#uc-download-link",
        'a:has-text("Download anyway")',
        '[aria-label="Download"]',
        '[data-tooltip="Download"]',
        'button:has-text("Download")',
    )

    _CONFIRM_FORM = "form#download-form"

    async def fetch(self, session: PageSession, url: str) -> list[Path]:
        if is_folder(url):
            return await self._fetch_folder(session, url)
        return await self._fetch_file(session, url)

    async def _fetch_file(self, session: PageSession, url: str) -> list[Path]:
        file_id = extract_file_id(url)

        if file_id:
            path = await self._try_direct(session, file_id)
            if path:
                return [path]

        session.note("fallback to share page buttons")
        await session.goto(url)
        path = await session.click_any(self._BUTTON_SELECTORS)
        return [path] if path else []

    async def _try_direct(self, session: PageSession, file_id: str) -> Path | None:
        """Direct URL first, then the scan-warning confirm form."""
        target = direct_url(file_id)
        session.note(f"direct uc?export=download for {file_id[:12]}...")

        # 'commit' rather than 'load': the response is a file, so the page
        # never fires a load event and waiting for one wastes the timeout.
        path = await session.capture_download(
            lambda: session.goto(target, wait_until="commit", timeout=10.0)
        )
        if path:
            return path

        session.note("virus-scan confirmation form")
        await session.goto(target)
        try:
            form = await session.page.query_selector(self._CONFIRM_FORM)
        except Exception:
            form = None

        if form:
            return await session.capture_download(
                lambda: session.page.click(f'{self._CONFIRM_FORM} input[type="submit"]')
            )
        return None

    async def _fetch_folder(self, session: PageSession, url: str) -> list[Path]:
        folder_id = extract_file_id(url)
        session.note(f"folder listing for {folder_id or 'unknown'}")

        await session.goto(url)
        await session.settle()

        file_ids = await self._scrape_file_ids(session, exclude=folder_id)
        if not file_ids:
            logger.warning("no files found in folder - empty, or it needs a login")
            return []

        cap = session.limits.max_files_per_folder
        selected = file_ids[:cap]
        if len(file_ids) > cap:
            logger.warning(
                "folder holds %d files, taking the first %d (raise max_files_per_folder)",
                len(file_ids),
                cap,
            )

        paths: list[Path] = []
        for index, file_id in enumerate(selected, 1):
            logger.info("folder file %d/%d", index, len(selected))
            try:
                path = await self._try_direct(session, file_id)
            except Exception as exc:
                # One bad file in a folder of 40 should not sink the batch.
                logger.warning("skipping %s: %s", file_id[:12], exc)
                continue
            if path:
                paths.append(path)

        return paths

    async def _scrape_file_ids(self, session: PageSession, *, exclude: str | None) -> list[str]:
        """Read child ids out of the rendered grid.

        ``data-id`` carries the Drive id on each tile. Deduplicated because
        the grid and the details pane both render one.
        """
        try:
            elements = await session.page.query_selector_all("[data-id]")
        except Exception:
            return []

        seen: dict[str, None] = {}
        for element in elements:
            try:
                value = await element.get_attribute("data-id")
            except Exception:
                continue
            if value and len(value) >= _MIN_ID_LENGTH and value != exclude:
                seen[value] = None

        return list(seen)
