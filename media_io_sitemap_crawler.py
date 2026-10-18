#!/usr/bin/env python3
"""Monitor newly published English Media.io sitemap pages."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

ROOT_SITEMAP = "https://www.media.io/sitemap.xml"
ROBOTS_URL = "https://www.media.io/robots.txt"
TARGET_HOST = "www.media.io"
BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "state/known_urls.txt"
REPORTS_DIR = BASE_DIR / "reports"
USER_AGENT = "media-io-sitemap-crawler/1.0 (+https://github.com/MrRoboTaxi/media_io_sitemap_crawler)"


class PageMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title_parts: list[str] = []
        self.metadata: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "title":
            self.in_title = True
        if tag.lower() == "meta":
            key = (attributes.get("name") or attributes.get("property") or "").lower()
            if key in {"description", "og:title", "og:description", "og:image"}:
                self.metadata[key] = attributes.get("content", "")
        if tag.lower() == "link" and attributes.get("rel", "").lower() == "canonical":
            self.metadata["canonical"] = attributes.get("href", "")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)

    def result(self) -> dict[str, str]:
        return {
            "title": " ".join("".join(self.title_parts).split()),
            "description": self.metadata.get("description", ""),
            "og_title": self.metadata.get("og:title", ""),
            "og_description": self.metadata.get("og:description", ""),
            "og_image": self.metadata.get("og:image", ""),
            "canonical": self.metadata.get("canonical", ""),
        }


def fetch(url: str, timeout: int = 30) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), response.headers.get_content_type()


def discover_root_sitemaps() -> list[str]:
    try:
        content, _ = fetch(ROBOTS_URL)
    except (urllib.error.URLError, TimeoutError) as error:
        logging.warning("Could not retrieve robots.txt: %s", error)
        return [ROOT_SITEMAP]

    urls = []
    for line in content.decode("utf-8", errors="replace").splitlines():
        match = re.match(r"\s*sitemap\s*:\s*(\S+)", line, flags=re.IGNORECASE)
        if match:
            urls.append(match.group(1))
    # robots.txt also lists eleven translated sites. The main sitemap is English.
    english = [url for url in urls if urllib.parse.urlsplit(url).netloc.lower() == TARGET_HOST and urllib.parse.urlsplit(url).path == "/sitemap.xml"]
    return english or [ROOT_SITEMAP]


def parse_sitemap(url: str, visited: set[str]) -> set[str]:
    if url in visited:
        return set()
    visited.add(url)
    logging.info("Fetching sitemap: %s", url)
    try:
        raw, _ = fetch(url)
        root = ET.fromstring(raw)
    except (urllib.error.URLError, TimeoutError, ET.ParseError) as error:
        raise RuntimeError(f"Could not parse sitemap {url}: {error}") from error

    tag = root.tag.rsplit("}", 1)[-1]
    namespace = "{" + root.tag.split("}", 1)[0].lstrip("{") + "}" if "}" in root.tag else ""
    if tag == "sitemapindex":
        urls: set[str] = set()
        for item in root.findall(f"{namespace}sitemap"):
            loc = item.findtext(f"{namespace}loc")
            if loc:
                urls.update(parse_sitemap(loc.strip(), visited))
        return urls
    if tag != "urlset":
        raise RuntimeError(f"Unexpected XML root {tag} from {url}")
    return {
        loc.strip()
        for item in root.findall(f"{namespace}url")
        if (loc := item.findtext(f"{namespace}loc"))
    }


def normalize_target(url: str) -> str | None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != TARGET_HOST:
        return None
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit(("https", TARGET_HOST, path, "", ""))


def collect_urls() -> list[str]:
    all_urls: set[str] = set()
    visited: set[str] = set()
    for sitemap in discover_root_sitemaps():
        all_urls.update(parse_sitemap(sitemap, visited))
    target_urls = {normalized for url in all_urls if (normalized := normalize_target(url))}
    if not target_urls:
        raise RuntimeError("No Media.io URLs found; refusing to overwrite state.")
    return sorted(target_urls)


def load_known_urls() -> set[str]:
    if not STATE_FILE.exists():
        return set()
    return {line.strip() for line in STATE_FILE.read_text(encoding="utf-8").splitlines() if line.strip()}


def get_metadata(url: str) -> dict[str, str]:
    record: dict[str, str] = {"url": url, "slug": urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]}
    try:
        raw, _ = fetch(url)
        parser = PageMetadataParser()
        parser.feed(raw.decode("utf-8", errors="replace"))
        record.update(parser.result())
    except (urllib.error.URLError, TimeoutError) as error:
        record["fetch_error"] = str(error)
    return record


def write_report(new_urls: list[str]) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_dir = REPORTS_DIR / timestamp
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "new_urls.txt").write_text("\n".join(new_urls) + ("\n" if new_urls else ""), encoding="utf-8")
    details = [get_metadata(url) for url in new_urls]
    (report_dir / "new_pages.json").write_text(
        json.dumps({"generated_at": timestamp, "count": len(details), "pages": details}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report_dir


def send_bark(new_urls: list[str], require_notification: bool = False) -> None:
    key = os.environ.get("BARK_DEVICE_KEY")
    if not new_urls:
        return
    if not key:
        if require_notification:
            raise RuntimeError("BARK_DEVICE_KEY is required for scheduled monitoring")
        logging.warning("BARK_DEVICE_KEY is unset; skipping notification")
        return
    base_url = (os.environ.get("BARK_SERVER_URL") or "https://api.day.app").rstrip("/")
    preview = "\n".join(url.rsplit("/", 1)[-1] for url in new_urls[:12])
    suffix = f"\n…及另外 {len(new_urls) - 12} 条" if len(new_urls) > 12 else ""
    payload = json.dumps(
        {
            "title": f"Media.io 新增 {len(new_urls)} 个英文页面",
            "body": preview + suffix,
            "group": "media-io-sitemap",
            "sound": "minuet",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    endpoint = f"{base_url}/{urllib.parse.quote(key, safe='')}"
    request = urllib.request.Request(endpoint, data=payload, headers={"Content-Type": "application/json", "User-Agent": USER_AGENT}, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"Bark returned HTTP {response.status}")
    logging.info("Bark notification sent")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", action="store_true", help="Write baseline state without generating a notification.")
    parser.add_argument("--require-notification", action="store_true", help="Fail if the Bark key is missing when new URLs appear.")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    current_urls = collect_urls()
    known_urls = load_known_urls()
    if arguments.bootstrap or not known_urls:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text("\n".join(current_urls) + "\n", encoding="utf-8")
        logging.info("Baseline recorded: %d URLs", len(current_urls))
        return 0

    new_urls = sorted(set(current_urls) - known_urls)
    logging.info("Current: %d; new: %d", len(current_urls), len(new_urls))
    if new_urls:
        report = write_report(new_urls)
        logging.info("New-page report: %s", report)
        send_bark(new_urls, arguments.require_notification)
    STATE_FILE.write_text("\n".join(current_urls) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        logging.exception("Crawler failed: %s", error)
        raise SystemExit(1)
