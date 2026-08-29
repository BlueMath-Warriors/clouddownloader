"""Provider resolution."""

from __future__ import annotations

import pytest

from clouddownloader.providers import Provider, default_providers
from clouddownloader.registry import ProviderRegistry, host_of


class TestHostOf:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://drive.google.com/file/d/abc/view", "drive.google.com"),
            ("https://www.dropbox.com/s/x/y.zip?dl=0", "dropbox.com"),
            ("https://app.box.com/s/abc", "app.box.com"),
            ("HTTPS://DRIVE.GOOGLE.COM/x", "drive.google.com"),
            ("https://example.com:8443/f", "example.com"),
            ("not-a-url", ""),
            ("", ""),
            ("ftp://files.example.com/x", ""),
            ("file:///etc/passwd", ""),
            ("javascript:alert(1)", ""),
        ],
    )
    def test_host_extraction(self, url: str, expected: str) -> None:
        assert host_of(url) == expected


class TestResolution:
    @pytest.fixture()
    def registry(self) -> ProviderRegistry:
        return ProviderRegistry()

    @pytest.mark.parametrize(
        ("url", "provider"),
        [
            ("https://drive.google.com/file/d/1a2b3c4d5e6f/view", "google-drive"),
            ("https://docs.google.com/spreadsheets/d/abc/edit", "google-drive"),
            ("https://www.dropbox.com/scl/fi/x/y.zip?rlkey=k&dl=0", "dropbox"),
            ("https://contoso.sharepoint.com/:b:/g/personal/x", "sharepoint"),
            ("https://1drv.ms/b/s!abc", "onedrive"),
            ("https://app.box.com/s/abcdef", "box"),
            ("https://we.tl/t-abc123", "wetransfer"),
            ("https://wetransfer.com/downloads/abc", "wetransfer"),
        ],
    )
    def test_known_hosts(self, registry: ProviderRegistry, url: str, provider: str) -> None:
        resolved = registry.resolve(url)
        assert resolved is not None
        assert resolved.name == provider

    def test_dropbox_is_not_captured_by_box(self, registry: ProviderRegistry) -> None:
        """'dropbox.com' ends with 'box.com' as a substring.

        Naive substring matching routes every Dropbox link to Box. Host
        matching is on domain boundaries so this cannot happen regardless of
        provider ordering.
        """
        resolved = registry.resolve("https://www.dropbox.com/s/abc/file.zip?dl=0")
        assert resolved is not None
        assert resolved.name == "dropbox"

    def test_lookalike_domains_do_not_match(self, registry: ProviderRegistry) -> None:
        for url in (
            "https://notbox.com/s/abc",
            "https://box.com.evil.net/s/abc",
            "https://mydropbox.com/s/abc",
            "https://drive.google.com.phish.io/file/d/abc",
        ):
            assert registry.resolve(url) is None, url

    def test_unknown_host(self, registry: ProviderRegistry) -> None:
        assert registry.resolve("https://example.com/file.zip") is None
        assert not registry.supports("https://example.com/file.zip")

    def test_wrapper_wins_over_real_providers(self, registry: ProviderRegistry) -> None:
        resolved = registry.resolve("https://eu.url-protection.com/v1/url?o=https%3A//box.com/s/x")
        assert resolved is not None
        assert resolved.name == "link-wrapper"


class TestRegistration:
    def test_custom_provider(self) -> None:
        class Custom(Provider):
            name = "custom"
            match_hosts = ("files.example.com",)

            async def fetch(self, session, url):  # type: ignore[no-untyped-def]
                return []

        registry = ProviderRegistry()
        registry.register(Custom())

        resolved = registry.resolve("https://files.example.com/x")
        assert resolved is not None
        assert resolved.name == "custom"

    def test_reregistering_a_name_replaces(self) -> None:
        class V1(Provider):
            name = "dropbox"
            match_hosts = ("dropbox.com",)

            async def fetch(self, session, url):  # type: ignore[no-untyped-def]
                return []

        registry = ProviderRegistry()
        before = len(registry)
        registry.register(V1())

        assert len(registry) == before
        assert registry.names().count("dropbox") == 1

    def test_priority_ordering_is_independent_of_insertion_order(self) -> None:
        class Late(Provider):
            name = "late"
            priority = 1
            match_hosts = ("drive.google.com",)

            async def fetch(self, session, url):  # type: ignore[no-untyped-def]
                return []

        registry = ProviderRegistry()
        registry.register(Late())

        resolved = registry.resolve("https://drive.google.com/file/d/abc/view")
        assert resolved is not None
        assert resolved.name == "late"

    def test_unregister(self) -> None:
        registry = ProviderRegistry()
        assert registry.unregister("box") is True
        assert registry.resolve("https://app.box.com/s/x") is None
        assert registry.unregister("box") is False

    def test_defaults_are_independent_instances(self) -> None:
        a, b = default_providers(), default_providers()
        assert a[0] is not b[0]
