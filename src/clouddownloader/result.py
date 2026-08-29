"""Return types."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DownloadResult:
    """One file that made it to disk.

    The original filename is preserved in ``filename``. ``path`` may differ
    (collisions get a numeric suffix, and unsafe names are sanitised), so
    always use ``path`` to open the file and ``filename`` to display it.
    """

    path: Path
    filename: str
    size_bytes: int
    provider: str
    source_url: str
    elapsed_seconds: float

    @property
    def size_mb(self) -> float:
        return self.size_bytes / 1024 / 1024

    @property
    def suffix(self) -> str:
        return self.path.suffix

    def unlink(self, missing_ok: bool = True) -> None:
        """Delete the downloaded file."""
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            if not missing_ok:
                raise

    def __str__(self) -> str:
        return f"{self.filename} ({self.size_mb:.1f}MB from {self.provider})"
