"""Tunable limits and browser configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Chromium refuses to start in most containers without these. --no-sandbox is
# the one people hit first; the shm flag matters because Docker's default
# /dev/shm is 64MB and Chromium will crash mid-download without it.
CONTAINER_BROWSER_ARGS = (
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
)


@dataclass(frozen=True)
class Limits:
    """Deadlines and size caps.

    Three separate timeouts, because they fail for different reasons:

    * ``launch_timeout`` - Chromium itself is wedged. Rare, but when it
      happens every subsequent call hangs unless you bound it.
    * ``navigation_timeout`` - one page load or one button click.
    * ``total_timeout`` - the whole ``download()`` call, including every
      fallback strategy the provider tries. This is the one that stops a
      worker task hanging forever; the per-step timeouts do not compose
      into a bound you can reason about.
    """

    max_file_size_mb: int = 100
    navigation_timeout: float = 60.0
    total_timeout: float = 120.0
    launch_timeout: float = 15.0
    close_timeout: float = 5.0

    #: Files to pull from a folder share before stopping.
    max_files_per_folder: int = 25

    #: Seconds to let a single-page app finish rendering its toolbar before
    #: looking for a download control. Pure heuristic, but SPAs like Box and
    #: SharePoint mount their command bar after ``networkidle``.
    spa_settle_delay: float = 2.0

    def __post_init__(self) -> None:
        if self.max_file_size_mb <= 0:
            raise ValueError("max_file_size_mb must be positive")
        if self.total_timeout < self.navigation_timeout:
            raise ValueError(
                "total_timeout must be >= navigation_timeout, otherwise the "
                "overall deadline fires before a single navigation can finish"
            )
        if self.max_files_per_folder <= 0:
            raise ValueError("max_files_per_folder must be positive")

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


@dataclass(frozen=True)
class BrowserConfig:
    """How Chromium is launched."""

    headless: bool = True
    user_agent: str = DEFAULT_USER_AGENT
    args: tuple[str, ...] = field(default=CONTAINER_BROWSER_ARGS)
    executable_path: str | None = None

    #: Extra HTTP headers applied to every context.
    extra_headers: tuple[tuple[str, str], ...] = ()

    def headers_dict(self) -> dict[str, str]:
        return dict(self.extra_headers)
