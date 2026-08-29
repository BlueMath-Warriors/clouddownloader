"""End-to-end tests against a real headless Chromium.

Everything else in this suite uses a fake browser. These drive the actual
Playwright path - launch, navigate, click a JS-rendered button, capture the
download event, enforce the size cap, tear down - against a local server, so
they are deterministic and need no network access.

    pytest -m browser

Skipped automatically when Playwright's Chromium is not installed.
"""

from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

from clouddownloader import CloudDownloader, FileTooLarge, Limits, Provider

pytestmark = pytest.mark.browser


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            browser.close()
        return True
    except Exception:
        return False


requires_chromium = pytest.mark.skipif(
    not _chromium_available(), reason="playwright chromium not installed"
)

PAGE = b"""<!doctype html>
<html><body>
  <h1>Share</h1>
  <div id="toolbar"></div>
  <script>
    // Mount the control late, the way a single-page app does. A provider
    // that queries immediately after networkidle finds nothing.
    setTimeout(function () {
      var b = document.createElement('button');
      b.setAttribute('data-testid', 'download-button');
      b.textContent = 'Download';
      b.onclick = function () { window.location = '/payload'; };
      document.getElementById('toolbar').appendChild(b);
    }, 300);
  </script>
</body></html>
"""


class _Handler(http.server.BaseHTTPRequestHandler):
    payload_size = 2048
    payload_name = "report.pdf"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)
            return

        if self.path == "/payload":
            body = b"x" * self.payload_size
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header(
                "Content-Disposition", f'attachment; filename="{self.payload_name}"'
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_error(404)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture()
def server():  # type: ignore[no-untyped-def]
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://localhost:{httpd.server_address[1]}/"
    httpd.shutdown()
    httpd.server_close()


class LocalProvider(Provider):
    """Exercises the same helpers a real provider uses."""

    name = "local"
    match_hosts = ("localhost",)

    async def fetch(self, session, url):  # type: ignore[no-untyped-def]
        await session.goto(url)
        await session.settle()
        return [p] if (p := await session.click_any(['[data-testid="download-button"]'])) else []


@requires_chromium
class TestRealBrowser:
    async def test_downloads_a_js_rendered_file(self, server: str, tmp_path: Path) -> None:
        async with CloudDownloader(providers=[LocalProvider()]) as downloader:
            result = await downloader.download(server, destination=tmp_path)

        assert result.filename == "report.pdf"
        assert result.size_bytes == 2048
        assert result.path.read_bytes() == b"x" * 2048
        assert result.provider == "local"

    async def test_size_cap_is_enforced_and_partial_removed(
        self, server: str, tmp_path: Path
    ) -> None:
        _Handler.payload_size = 3 * 1024 * 1024
        try:
            limits = Limits(max_file_size_mb=1, navigation_timeout=30, total_timeout=60)
            async with CloudDownloader(providers=[LocalProvider()], limits=limits) as downloader:
                with pytest.raises(FileTooLarge):
                    await downloader.download(server, destination=tmp_path)
        finally:
            _Handler.payload_size = 2048

        # The oversized file must not be left on disk.
        assert list(tmp_path.iterdir()) == []

    async def test_browser_is_reused_across_downloads(self, server: str, tmp_path: Path) -> None:
        async with CloudDownloader(providers=[LocalProvider()]) as downloader:
            first = await downloader.download(server, destination=tmp_path)
            second = await downloader.download(server, destination=tmp_path)

        # Same browser, and the collision got a suffix rather than clobbering.
        assert first.path.name == "report.pdf"
        assert second.path.name == "report-1.pdf"
        assert first.path.exists() and second.path.exists()

    async def test_close_is_clean(self, server: str, tmp_path: Path) -> None:
        downloader = CloudDownloader(providers=[LocalProvider()])
        await downloader.download(server, destination=tmp_path)
        await downloader.close()
        assert not downloader._pool.is_running
