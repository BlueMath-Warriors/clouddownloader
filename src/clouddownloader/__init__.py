"""CloudDownloader - headless-browser file retrieval from cloud share links.

Cloud share links are single-page apps, not files. ``requests.get()`` on a
Google Drive link returns HTML; the bytes are behind a JavaScript-rendered
button, a consent interstitial or a redirect chain that needs cookies. This
library drives a real headless Chromium and captures the browser's own
download event.

    from clouddownloader import CloudDownloader

    async with CloudDownloader() as dl:
        result = await dl.download(url, destination="./downloads")
        print(result.path, result.size_mb)

Supports Google Drive, Dropbox, SharePoint, OneDrive, Box and WeTransfer,
plus corporate email link wrappers. Add your own with ``Provider``.
"""

from __future__ import annotations

import logging

from .browser import BrowserPool
from .config import BrowserConfig, Limits
from .downloader import CloudDownloader, download, download_all
from .errors import (
    BrowserLaunchError,
    CloudDownloadError,
    DownloadFailed,
    DownloadTimeout,
    FileTooLarge,
    UnsupportedProviderError,
)
from .providers import (
    BoxProvider,
    DropboxProvider,
    GoogleDriveProvider,
    LinkWrapperProvider,
    OneDriveProvider,
    Provider,
    SharePointProvider,
    WeTransferProvider,
    default_providers,
)
from .registry import ProviderRegistry
from .result import DownloadResult
from .session import PageSession

__version__ = "0.1.0"

# A library should not configure logging for its host application.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "__version__",
    # main API
    "CloudDownloader",
    "download",
    "download_all",
    "DownloadResult",
    # config
    "Limits",
    "BrowserConfig",
    # errors
    "CloudDownloadError",
    "UnsupportedProviderError",
    "DownloadTimeout",
    "FileTooLarge",
    "DownloadFailed",
    "BrowserLaunchError",
    # extension points
    "Provider",
    "ProviderRegistry",
    "PageSession",
    "BrowserPool",
    "default_providers",
    "BoxProvider",
    "DropboxProvider",
    "GoogleDriveProvider",
    "LinkWrapperProvider",
    "OneDriveProvider",
    "SharePointProvider",
    "WeTransferProvider",
]
