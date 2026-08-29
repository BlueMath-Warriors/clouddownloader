"""Chromium lifecycle.

The whole point of this module is that a browser is a *process*, not an
object. If you let an exception escape without tearing it down you leak a
Chromium and its renderer children, and a long-lived worker will run the
host out of memory over days. Every path out of here closes the browser.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .config import BrowserConfig, Limits
from .errors import BrowserLaunchError

logger = logging.getLogger(__name__)


class BrowserPool:
    """Owns one Chromium instance and hands out fresh contexts.

    Reusing the browser across downloads saves ~300-500ms per call. Each
    download still gets its own *context* so cookies from one share cannot
    leak into another - contexts are cheap, browsers are not.

    Not safe to share across event loops. One pool per loop.
    """

    def __init__(self, config: BrowserConfig | None = None, limits: Limits | None = None) -> None:
        self._config = config or BrowserConfig()
        self._limits = limits or Limits()
        self._playwright: Any = None
        self._browser: Any = None
        self._lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return self._browser is not None

    async def browser(self) -> Any:
        """Return the live browser, launching it on first use.

        The lock matters: without it, N concurrent downloads on a cold pool
        each launch their own Chromium and all but one leak.
        """
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            if self._browser is not None:
                # Crashed out from under us; drop the handle and relaunch.
                logger.warning("browser disconnected, relaunching")
                self._browser = None
            await self._launch()
            return self._browser

    async def _launch(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - import guard
            raise BrowserLaunchError(
                "playwright is not installed. Run: pip install clouddownloader[browser]"
            ) from exc

        launch_kwargs: dict[str, Any] = {
            "headless": self._config.headless,
            "args": list(self._config.args),
        }
        if self._config.executable_path:
            launch_kwargs["executable_path"] = self._config.executable_path

        try:
            self._playwright = await asyncio.wait_for(
                async_playwright().start(), timeout=self._limits.launch_timeout
            )
            self._browser = await asyncio.wait_for(
                self._playwright.chromium.launch(**launch_kwargs),
                timeout=self._limits.launch_timeout,
            )
            logger.debug("chromium launched")
        except asyncio.TimeoutError as exc:
            await self.force_close()
            raise BrowserLaunchError(
                f"chromium did not start within {self._limits.launch_timeout}s"
            ) from exc
        except Exception as exc:
            await self.force_close()
            raise BrowserLaunchError(
                f"could not launch chromium: {exc}. If this is a container, check that "
                "'playwright install --with-deps chromium' has been run."
            ) from exc

    async def new_context(self) -> Any:
        """A fresh, isolated browsing context with downloads enabled."""
        browser = await self.browser()
        kwargs: dict[str, Any] = {
            "accept_downloads": True,
            "user_agent": self._config.user_agent,
        }
        headers = self._config.headers_dict()
        if headers:
            kwargs["extra_http_headers"] = headers
        return await browser.new_context(**kwargs)

    async def close(self) -> None:
        """Graceful shutdown."""
        await self.force_close()

    async def force_close(self) -> None:
        """Tear down unconditionally, swallowing every error.

        Called from timeout handlers, where the browser is by definition
        already misbehaving. A failure to close is not worth masking the
        original error, but the handles must still be dropped so the next
        call relaunches cleanly rather than reusing a corpse.
        """
        browser, self._browser = self._browser, None
        playwright, self._playwright = self._playwright, None

        if browser is not None:
            try:
                await asyncio.wait_for(browser.close(), timeout=self._limits.close_timeout)
            except Exception as exc:
                logger.debug("browser close failed, abandoning handle: %s", exc)

        if playwright is not None:
            try:
                await asyncio.wait_for(playwright.stop(), timeout=self._limits.close_timeout)
            except Exception as exc:
                logger.debug("playwright stop failed, abandoning handle: %s", exc)
