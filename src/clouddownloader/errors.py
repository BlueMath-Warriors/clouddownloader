"""Exception hierarchy.

Every failure mode gets a distinct type so callers can decide what is
retryable. A pipeline that just wants "file or nothing" should call
``download_or_none()`` rather than blanket-catching ``Exception``.
"""

from __future__ import annotations


class CloudDownloadError(Exception):
    """Base class for every error raised by this library."""

    def __init__(self, message: str, *, url: str | None = None) -> None:
        super().__init__(message)
        self.url = url


class UnsupportedProviderError(CloudDownloadError):
    """No registered provider recognised the URL.

    Not retryable. Register a custom provider if you need this host.
    """


class BrowserLaunchError(CloudDownloadError):
    """Chromium could not be started.

    Usually means ``playwright install chromium`` was never run, or the
    container lacks the shared libraries Chromium needs.
    """


class DownloadTimeout(CloudDownloadError):
    """A deadline elapsed before the file arrived.

    Retryable. The browser is torn down before this is raised, so no
    process is left behind.
    """

    def __init__(
        self, message: str, *, url: str | None = None, seconds: float | None = None
    ) -> None:
        super().__init__(message, url=url)
        self.seconds = seconds


class FileTooLarge(CloudDownloadError):
    """The transfer exceeded ``Limits.max_file_size_mb``.

    The partial file is deleted before this is raised.
    """

    def __init__(
        self, message: str, *, url: str | None = None, size_bytes: int | None = None
    ) -> None:
        super().__init__(message, url=url)
        self.size_bytes = size_bytes


class DownloadFailed(CloudDownloadError):
    """The provider was recognised but no file could be retrieved.

    Typically a share that has expired, been revoked, or requires a login
    this library does not have. Check ``.attempts`` for what was tried.
    """

    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        provider: str | None = None,
        attempts: list[str] | None = None,
    ) -> None:
        super().__init__(message, url=url)
        self.provider = provider
        self.attempts = attempts or []
