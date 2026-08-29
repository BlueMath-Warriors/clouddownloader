"""Provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from ..session import PageSession


class Provider(ABC):
    """A strategy for getting files out of one cloud host.

    Subclass, set ``name`` and ``match_hosts``, implement ``fetch``, then
    register it::

        class MyHost(Provider):
            name = "myhost"
            match_hosts = ("files.myhost.com",)

            async def fetch(self, session, url):
                path = await session.click_any(['button.dl'])
                return [path] if path else []

        downloader.register(MyHost())
    """

    #: Short identifier, surfaced on ``DownloadResult.provider``.
    name: ClassVar[str] = "unknown"

    #: Substrings matched against the URL's *host* only. Matching against
    #: the whole URL is how you end up routing a Dropbox link containing
    #: "?redirect=box.com" to the wrong provider.
    match_hosts: ClassVar[tuple[str, ...]] = ()

    #: Lower runs first. Only matters for genuinely ambiguous hosts.
    priority: ClassVar[int] = 100

    def matches(self, host: str) -> bool:
        """True if this provider handles ``host`` (already lowercased).

        Matches on domain boundaries, so ``box.com`` does not swallow
        ``dropbox.com`` and ``notbox.com`` does not match either.
        """
        for candidate in self.match_hosts:
            if host == candidate or host.endswith("." + candidate):
                return True
        return False

    @abstractmethod
    async def fetch(self, session: PageSession, url: str) -> list[Path]:
        """Retrieve one or more files.

        Return an empty list if nothing could be downloaded; the caller
        turns that into ``DownloadFailed`` with the recorded attempts.
        Raise only for genuinely exceptional conditions.
        """
        raise NotImplementedError
