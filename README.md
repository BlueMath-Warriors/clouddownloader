# CloudDownloader

Retrieve files from cloud share links using a headless browser.

`requests.get()` on a Google Drive link returns HTML. Cloud share pages are
single-page apps: the bytes sit behind a JavaScript-rendered button, a consent
interstitial, a virus-scan warning, or a redirect chain that only works with
cookies. CloudDownloader drives a real headless Chromium and captures the
browser's own download event, so it gets the same file a human would.

```python
from clouddownloader import CloudDownloader

async with CloudDownloader() as downloader:
    result = await downloader.download(url, destination="./downloads")
    print(result.path, result.size_mb)
```

**Supported:** Google Drive (files and folders) · Dropbox (files and folders)
· SharePoint · OneDrive · Box (files and folders) · WeTransfer · corporate
email link wrappers (Defender Safe Links, Proofpoint, Mimecast, Barracuda,
Symantec, Check Point).

---

## Install

```bash
pip install clouddownloader
playwright install --with-deps chromium
```

The second command is not optional — it downloads the browser binary.

## Use

### Async (preferred)

```python
from clouddownloader import CloudDownloader, Limits

limits = Limits(max_file_size_mb=250, total_timeout=180)

async with CloudDownloader(limits=limits) as downloader:
    # One file
    result = await downloader.download(url, destination="./downloads")

    # Every file in a folder share
    for result in await downloader.download_all(folder_url, destination="./downloads"):
        print(result)
```

Reuse one instance across a batch. Launching Chromium costs about a second;
downloading with a warm browser does not.

### Sync

```python
from clouddownloader import download

result = download(url, destination="./downloads")
```

Launches and tears down a browser per call. Fine for scripts, wrong for a
service. Raises if called from inside a running event loop.

### CLI

```bash
clouddownloader "https://drive.google.com/file/d/.../view" -o ./downloads
clouddownloader "https://www.dropbox.com/scl/fo/.../folder?rlkey=..." --all -v
clouddownloader --list-providers
```

---

## What it returns

```python
@dataclass(frozen=True)
class DownloadResult:
    path: Path            # where it landed (sanitised, collision-free)
    filename: str         # original name, for display
    size_bytes: int
    provider: str
    source_url: str
    elapsed_seconds: float
```

`path` and `filename` differ when a name needed sanitising or a collision
resolving. Open `path`, show `filename`.

## Errors

Each failure mode is a distinct type because each needs a different response:

| Exception | Meaning | Retry? |
|---|---|---|
| `UnsupportedProviderError` | No provider matched the host | No — register one |
| `BrowserLaunchError` | Chromium wouldn't start | No — fix the install |
| `DownloadTimeout` | Deadline elapsed | Yes |
| `FileTooLarge` | Over `max_file_size_mb` | No — raise the cap |
| `DownloadFailed` | Share expired, revoked, or needs a login | Sometimes |

`DownloadFailed.attempts` lists every strategy that was tried, which is what
you want in a log when a provider changes its markup.

For pipelines where one bad link must not fail a batch:

```python
result = await downloader.download_or_none(url)   # None instead of raising
```

That swallows library errors only. A `RuntimeError` from a provider is a bug
and still propagates — blanket-catching `Exception` is how bugs become silent
data loss.

---

## Running it in production

The interesting part of this library is not clicking buttons. It's that a
browser is a *process*, and a long-lived worker that leaks them dies.

**Three separate timeouts.** Per-navigation deadlines don't compose into a
bound you can reason about — a provider that tries four fallback strategies at
60s each hangs for four minutes. `Limits.total_timeout` wraps the entire
`download()` call, including every fallback.

**Force-close on timeout.** When the total deadline fires, Chromium is by
definition misbehaving. It gets killed rather than returned to the pool;
otherwise every later call inherits the wedged process. This is the single
most important behaviour here and the one most implementations miss.

**One browser, many contexts.** The browser is reused across downloads. Each
download gets a fresh *context*, so cookies from one share can't leak into the
next. Contexts are cheap; browsers are not.

**Container flags by default.** `--no-sandbox` and `--disable-dev-shm-usage`
are on out of the box. Docker's default `/dev/shm` is 64MB and Chromium
crashes mid-download without the second one — an intermittent failure that
looks like a network problem.

**Filenames are untrusted input.** A share advertising
`../../../etc/cron.d/x` should not be able to write there. Names are stripped
of directory components, control characters and reserved characters, and
length-bounded. Collisions get a numeric suffix rather than overwriting —
folder shares routinely contain several `cover.jpg`.

**Host matching on domain boundaries.** `dropbox.com` ends with `box.com`.
Substring matching sends every Dropbox link to the Box provider, and
`box.com.evil.net` to Box as well. Matching is on the parsed hostname with
domain-boundary checks, so neither is possible regardless of provider order.

## Provider-specific behaviour worth knowing

- **Google Drive** serves an HTML interstitial instead of the file when it's
  too large to virus-scan. The confirm form is submitted automatically.
- **Google Drive folders** have no public listing API for anonymous shares, so
  contents are scraped from the rendered grid. Capped by
  `Limits.max_files_per_folder` (default 25) and logged when it truncates.
- **Dropbox** links are rewritten to `dl=1` by parsing the query, not string
  replacement — modern links put `rlkey` first, so `dl` arrives as `&dl=0` and
  a naive `?dl=0` → `?dl=1` replace misses it silently.
- **Box and SharePoint** mount their toolbar *after* `networkidle`, so there's
  a short settle delay before looking for controls.
- **Consent banners** don't hide a download button, they intercept the click —
  which surfaces as a timeout, not "not found". They're dismissed first.

---

## Custom providers

```python
from clouddownloader import CloudDownloader, Provider

class InternalShare(Provider):
    name = "internal"
    match_hosts = ("files.example.com",)

    async def fetch(self, session, url):
        await session.goto(url)
        await session.dismiss_consent()
        path = await session.click_any([
            'button[data-testid="download"]',
            'button:has-text("Download")',
        ])
        return [path] if path else []

downloader = CloudDownloader()
downloader.register(InternalShare())
```

`PageSession` provides `goto`, `settle`, `dismiss_consent`, `click_any`,
`capture_download`, `save` and `find_in_page_source`. Providers never touch
tempfiles, size checks or timeouts.

Registering a name that already exists replaces it — that's how you patch a
built-in provider's selectors without waiting for a release.

## Limitations

Stated plainly, because these will bite someone:

- **No authentication.** Public and unlisted share links only. Anything behind
  a login needs a `storage_state` you supply yourself.
- **The size cap is enforced after transfer, not during.** Playwright's
  download API doesn't expose `Content-Length` before the file lands, so an
  oversized file is downloaded and *then* deleted. The cap protects your disk,
  not your bandwidth.
- **Selectors rot.** These are third-party UIs with no contract. Each provider
  tries several selectors and falls back to scraping embedded state, but a
  redesign will eventually break one. That's what `DownloadFailed.attempts` is
  for.
- **One instance per event loop.** Not safe to share across loops or threads.
- **Folder support varies.** Drive enumerates children; Dropbox and Box return
  a server-generated ZIP; SharePoint, OneDrive and WeTransfer are single-file.

## Development

```bash
pip install -e ".[dev]"
playwright install chromium

pytest              # unit tests, no browser needed
ruff check .
mypy src
```

The test suite runs without a browser — orchestration is tested against a fake
pool, and URL handling, filename sanitising and provider resolution are pure
functions. That's deliberate: the parts that break in production are testable
without network access.

## License

MIT
