"""Provider lookup."""

from __future__ import annotations

from urllib.parse import urlparse

from .providers import Provider, default_providers


def host_of(url: str) -> str:
    """Lowercased hostname, ``www.`` stripped, port removed.

    Returns "" for anything that is not a parseable http(s) URL, which makes
    every provider decline rather than crash.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""

    if parsed.scheme not in ("http", "https"):
        return ""

    host = (parsed.hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


class ProviderRegistry:
    """Ordered collection of providers, resolved by URL host."""

    def __init__(self, providers: list[Provider] | None = None) -> None:
        self._providers: list[Provider] = []
        for provider in providers if providers is not None else default_providers():
            self.register(provider)

    def register(self, provider: Provider) -> None:
        """Add a provider. Re-registering a name replaces the old one.

        Kept sorted by priority so resolution order does not depend on the
        order calls happened to be made in.
        """
        self._providers = [p for p in self._providers if p.name != provider.name]
        self._providers.append(provider)
        self._providers.sort(key=lambda p: p.priority)

    def unregister(self, name: str) -> bool:
        before = len(self._providers)
        self._providers = [p for p in self._providers if p.name != name]
        return len(self._providers) != before

    def resolve(self, url: str) -> Provider | None:
        """First provider matching the URL's host, or None."""
        host = host_of(url)
        if not host:
            return None
        for provider in self._providers:
            if provider.matches(host):
                return provider
        return None

    def supports(self, url: str) -> bool:
        return self.resolve(url) is not None

    @property
    def providers(self) -> tuple[Provider, ...]:
        return tuple(self._providers)

    def names(self) -> list[str]:
        return [p.name for p in self._providers]

    def __len__(self) -> int:
        return len(self._providers)
