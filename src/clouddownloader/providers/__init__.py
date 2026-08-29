"""Built-in providers."""

from __future__ import annotations

from .base import Provider
from .box import BoxProvider
from .dropbox import DropboxProvider
from .gdrive import GoogleDriveProvider
from .microsoft import OneDriveProvider, SharePointProvider
from .wetransfer import WeTransferProvider
from .wrapper import LinkWrapperProvider


def default_providers() -> list[Provider]:
    """Fresh instances of every built-in provider."""
    return [
        LinkWrapperProvider(),
        GoogleDriveProvider(),
        DropboxProvider(),
        SharePointProvider(),
        OneDriveProvider(),
        BoxProvider(),
        WeTransferProvider(),
    ]


__all__ = [
    "Provider",
    "BoxProvider",
    "DropboxProvider",
    "GoogleDriveProvider",
    "LinkWrapperProvider",
    "OneDriveProvider",
    "SharePointProvider",
    "WeTransferProvider",
    "default_providers",
]
