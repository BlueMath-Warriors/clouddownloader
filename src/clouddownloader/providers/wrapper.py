"""Email security link wrappers.

Corporate mail gateways rewrite every link in an inbound message so clicks
route through their scanner first. A share arriving by email therefore does
not look like a share - the host is the scanner's, and host matching sends
it nowhere.

The fix is to let the browser follow the redirect chain (these wrappers use
JS interstitials and cookies, so an HTTP client following ``Location``
headers is not enough), then re-dispatch on the URL you land on.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..session import PageSession
from .base import Provider

logger = logging.getLogger(__name__)


class LinkWrapperProvider(Provider):
    """Unwrap a scanner URL and hand off to the real provider.

    ``resolve`` is injected by the downloader to avoid a circular import and
    to keep the recursion bounded - a wrapper that resolves to another
    wrapper is a redirect loop, and is refused.
    """

    name = "link-wrapper"
    priority = 10  # must beat every real provider
    match_hosts = (
        "safelinks.protection.outlook.com",  # Microsoft Defender
        "urldefense.com",  # Proofpoint
        "urldefense.proofpoint.com",
        "url-protection.com",  # Check Point / Avanan
        "clicktime.symantec.com",  # Symantec
        "protect-us.mimecast.com",  # Mimecast
        "protect-eu.mimecast.com",
        "linkprotect.cudasvc.com",  # Barracuda
    )

    def __init__(self) -> None:
        self._depth = 0

    async def fetch(self, session: PageSession, url: str) -> list[Path]:
        session.note("follow link-wrapper redirect chain")

        await session.goto(url)
        final = session.url

        if final == url:
            logger.warning("link wrapper did not redirect anywhere")
            return []

        logger.info("wrapper resolved to %s", final[:80])

        resolve = getattr(self, "resolve", None)
        if resolve is None:  # pragma: no cover - wired by the downloader
            logger.error("LinkWrapperProvider was not given a resolve callback")
            return []

        inner = resolve(final)
        if inner is None:
            logger.warning("no provider handles the unwrapped URL")
            return []
        if isinstance(inner, LinkWrapperProvider):
            logger.warning("wrapper resolved to another wrapper, refusing to recurse")
            return []

        return await inner.fetch(session, final)
