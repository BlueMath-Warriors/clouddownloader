"""WeTransfer."""

from __future__ import annotations

from pathlib import Path

from ..session import PageSession
from .base import Provider


class WeTransferProvider(Provider):
    """WeTransfer transfer pages.

    Gated behind a terms/consent interstitial that must be cleared before
    the download control exists in the DOM at all.
    """

    name = "wetransfer"
    match_hosts = ("wetransfer.com", "we.tl", "wetransfer.zendesk.com")

    _SELECTORS = (
        '[data-testid="transfer__download"]',
        ".transfer__download",
        'button:has-text("Download")',
        'a:has-text("Download")',
    )

    async def fetch(self, session: PageSession, url: str) -> list[Path]:
        await session.goto(url)
        await session.dismiss_consent(
            (
                'button:has-text("I agree")',
                'button:has-text("Accept all")',
                "#onetrust-accept-btn-handler",
                'button:has-text("Accept")',
            )
        )
        await session.settle()

        path = await session.click_any(self._SELECTORS)
        return [path] if path else []
