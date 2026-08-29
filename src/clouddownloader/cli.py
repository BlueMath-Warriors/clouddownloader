"""Command line interface.

    clouddownloader https://drive.google.com/file/d/... -o ./downloads -v
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from . import __version__
from .config import Limits
from .downloader import CloudDownloader
from .errors import CloudDownloadError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clouddownloader",
        description="Download files from cloud share links using a headless browser.",
    )
    parser.add_argument("url", nargs="?", help="the share URL to download")
    parser.add_argument(
        "-o", "--output", default=".", help="destination directory (default: current)"
    )
    parser.add_argument(
        "-a", "--all", action="store_true", help="download every file in a folder share"
    )
    parser.add_argument(
        "--max-size", type=int, default=100, metavar="MB", help="size cap per file (default: 100)"
    )
    parser.add_argument(
        "--timeout", type=float, default=120.0, metavar="SEC", help="total deadline (default: 120)"
    )
    parser.add_argument(
        "--max-files", type=int, default=25, metavar="N", help="folder file cap (default: 25)"
    )
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument(
        "--list-providers", action="store_true", help="print registered providers and exit"
    )
    parser.add_argument("--version", action="version", version=f"clouddownloader {__version__}")
    return parser


async def _run(args: argparse.Namespace) -> int:
    from .config import BrowserConfig

    limits = Limits(
        max_file_size_mb=args.max_size,
        total_timeout=args.timeout,
        max_files_per_folder=args.max_files,
    )
    browser = BrowserConfig(headless=not args.headed)

    async with CloudDownloader(limits=limits, browser=browser) as downloader:
        if args.list_providers:
            for provider in downloader.registry.providers:
                hosts = ", ".join(provider.match_hosts)
                print(f"  {provider.name:<14} {hosts}")
            return 0

        if not downloader.supports(args.url):
            print(f"error: no provider handles {args.url}", file=sys.stderr)
            print("       run --list-providers to see what is supported", file=sys.stderr)
            return 2

        try:
            if args.all:
                results = await downloader.download_all(args.url, destination=args.output)
            else:
                results = [await downloader.download(args.url, destination=args.output)]
        except CloudDownloadError as exc:
            print(f"error: {exc}", file=sys.stderr)
            attempts = getattr(exc, "attempts", None)
            if attempts:
                print("       tried: " + "; ".join(attempts), file=sys.stderr)
            return 1

    total = sum(r.size_bytes for r in results)
    for result in results:
        print(f"{result.path}  ({result.size_mb:.1f}MB)")
    if len(results) > 1:
        print(
            f"\n{len(results)} files, {total / 1024 / 1024:.1f}MB "
            f"in {results[0].elapsed_seconds:.1f}s"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s" if args.verbose else "%(message)s",
        stream=sys.stderr,
    )

    if not args.url and not args.list_providers:
        build_parser().print_usage(sys.stderr)
        return 2

    if args.output and not args.list_providers:
        Path(args.output).mkdir(parents=True, exist_ok=True)

    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
