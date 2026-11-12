from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

from .core import (
    AppConfig, EvaluationError, JobRecord, export_csv, open_database,
    request_evaluation, save_pending, store_job,
)
from .i18n import Language, translate


USER_AGENT = "SmallCareerBot"
MAX_JOBS = 20
MAX_BYTES = 3_000_000
TIMEOUT = 20
DELAY = 1.0


@dataclass(frozen=True)
class Listing:
    links: list[str]
    limited: bool


def normalize_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        if (parts.scheme.lower() not in ("http", "https") or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.port is not None and not 1 <= parts.port <= 65535):
            raise ValueError
    except ValueError as exc:
        raise EvaluationError("error.website_url") from exc
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))


def origin(url: str) -> tuple[str, str, int]:
    parts = urlsplit(url)
    return parts.scheme, parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.documents: list[str] = []
        self.next_links: list[str] = []
        self._json = False
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a" and attributes.get("href"):
            self.links.append(attributes["href"])
        if (tag in ("a", "link") and attributes.get("href")
                and "next" in (attributes.get("rel") or "").lower().split()):
            self.next_links.append(attributes["href"])
        if tag == "script" and (attributes.get("type") or "").lower() == "application/ld+json":
            self._json = True
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._json:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._json:
            self.documents.append("".join(self._chunks))
            self._json = False


class TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self.ignored += 1
        elif tag in ("br", "p", "div", "li", "h1", "h2", "h3", "h4", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self.ignored:
            self.ignored -= 1
        elif tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "tr"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)

    def text(self) -> str:
        return "\n".join(line.strip() for line in "".join(self.parts).splitlines() if line.strip())


def structured_objects(value: object) -> Iterator[dict]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from structured_objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from structured_objects(item)


def has_type(value: dict, expected: str) -> bool:
    types = value.get("@type", [])
    if isinstance(types, str):
        types = [types]
    return isinstance(types, list) and any(
        isinstance(item, str) and item.rsplit("/", 1)[-1] == expected for item in types)


def documents(parser: DocumentParser) -> Iterator[dict]:
    for raw in parser.documents:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        yield from structured_objects(value)


def listing_links(html: str, base_url: str, limit: int | None = MAX_JOBS) -> Listing:
    parser = DocumentParser()
    parser.feed(html)
    candidates: list[str] = []
    for obj in documents(parser):
        if has_type(obj, "ItemList"):
            items = obj.get("itemListElement")
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, str):
                    candidates.append(item)
                elif isinstance(item, dict):
                    target = item.get("item", item)
                    if isinstance(target, str):
                        candidates.append(target)
                    elif isinstance(target, dict):
                        link = target.get("url") or target.get("@id")
                        if isinstance(link, str):
                            candidates.append(link)
    for href in parser.links:
        path = urlsplit(href).path
        if re.search(r"/(?:project/detail|jobs?|careers?|vacanc(?:y|ies)|positions?|recruit(?:ment)?)/[^/]+", path, re.I):
            candidates.append(href)
    links: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            link = normalize_url(urljoin(base_url, candidate))
        except EvaluationError:
            continue
        if origin(link) == origin(base_url) and link != base_url and link not in seen:
            links.append(link)
            seen.add(link)
    if limit is None:
        return Listing(links, False)
    return Listing(links[:limit], len(links) > limit)


def next_page(html: str, base_url: str) -> str | None:
    from .ai_browse import LinkParser

    parser = DocumentParser()
    parser.feed(html)
    anchors = LinkParser()
    anchors.feed(html)
    candidates = parser.next_links + [
        href for href, label in anchors.links
        if re.fullmatch(r"\s*(?:next(?:\s+page)?|次(?:のページ|へ)?|下一頁|下一页)\s*",
                        label, re.I)
    ]
    for candidate in candidates:
        target = normalize_url(urljoin(base_url, candidate))
        if origin(target) != origin(base_url):
            raise EvaluationError("error.website_redirect")
        return target
    return None


def job_text(html: str) -> str:
    parser = DocumentParser()
    parser.feed(html)
    for obj in documents(parser):
        if not has_type(obj, "JobPosting"):
            continue
        title, description = obj.get("title"), obj.get("description")
        if not isinstance(title, str) or not isinstance(description, str) or not description.strip():
            continue
        text = TextParser()
        text.feed(description)
        body = text.text()
        if body:
            # Retain other structured fields such as location and salary without guessing.
            metadata = {k: v for k, v in obj.items() if k not in ("@context", "description")}
            return f"{title}\n\n{body}\n\n{json.dumps(metadata, ensure_ascii=False)}"
    raise EvaluationError("error.job_structure")


class Crawler:
    def __init__(self, website: str, stop: threading.Event | None = None) -> None:
        self.website = normalize_url(website)
        self.site = origin(self.website)
        self.opener = build_opener(NoRedirect())
        self.robots: RobotFileParser | None = None
        self.last_request = 0.0
        self.delay = DELAY
        self.stop = stop

    def _get(self, url: str, *, robots: bool = False) -> tuple[str, str]:
        for _ in range(4):
            url = normalize_url(url)
            if origin(url) != self.site:
                raise EvaluationError("error.website_redirect")
            if not robots and (self.robots is None or not self.robots.can_fetch(USER_AGENT, url)):
                raise EvaluationError("error.robots_denied")
            wait = self.delay - (time.monotonic() - self.last_request)
            if wait > 0:
                if self.stop is not None:
                    if self.stop.wait(wait):
                        raise EvaluationError("error.stopped")
                else:
                    time.sleep(wait)
            if self.stop is not None and self.stop.is_set():
                raise EvaluationError("error.stopped")
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"})
            self.last_request = time.monotonic()
            try:
                with self.opener.open(request, timeout=TIMEOUT) as response:
                    data = response.read(MAX_BYTES + 1)
                    if len(data) > MAX_BYTES:
                        raise EvaluationError("error.website_large")
                    content_type = response.headers.get_content_type()
                    if content_type not in (("text/plain",) if robots else ("text/html", "application/xhtml+xml")):
                        raise EvaluationError("error.website_content")
                    encoding = response.headers.get_content_charset() or "utf-8"
                    try:
                        return data.decode(encoding), url
                    except (UnicodeDecodeError, LookupError) as exc:
                        raise EvaluationError("error.website_encoding") from exc
            except HTTPError as exc:
                try:
                    if exc.code in (301, 302, 303, 307, 308) and exc.headers.get("Location"):
                        url = urljoin(url, exc.headers["Location"])
                        continue
                    if robots and exc.code in (404, 410):
                        return "", url
                    if exc.code == 403:
                        raise EvaluationError(
                            "error.website_forbidden", stage="robots.txt" if robots else "HTML") from exc
                    raise EvaluationError("error.website_http", code=exc.code) from exc
                finally:
                    exc.close()
            except (URLError, TimeoutError, OSError) as exc:
                raise EvaluationError("error.website_network") from exc
        raise EvaluationError("error.website_redirect")

    def prepare(self) -> None:
        parts = urlsplit(self.website)
        robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        raw, _ = self._get(robots_url, robots=True)
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(raw.splitlines())
        self.robots = parser
        self.delay = max(DELAY, float(parser.crawl_delay(USER_AGENT) or 0))

    def listing(self) -> Listing:
        self.prepare()
        html, final_url = self._get(self.website)
        listing = listing_links(html, final_url)
        if not listing.links:
            raise EvaluationError("error.no_jobs")
        return listing

    def detail(self, url: str) -> tuple[str, str]:
        html, final_url = self._get(url)
        return final_url, job_text(html)


def crawl_to_queue(
    website: str, directory: Path, language: Language, max_pages: int,
    stop: threading.Event, progress: Callable[[str], None],
    *, ai_config: AppConfig | None = None, ai_key: str = "", browser: bool = False,
) -> tuple[int, list[str], bool, bool]:
    from .ai_browse import analyze_detail, analyze_listing

    if browser:
        from .browser_crawler import BrowserCrawler

        crawler = BrowserCrawler(website, stop)
    else:
        crawler = Crawler(website, stop)
    connection = open_database(directory / "jobs.sqlite3")
    failures: list[str] = []
    saved = 0
    pages = 0
    current: str | None = crawler.website
    visited: set[str] = set()
    jobs_seen: set[str] = set()
    try:
        crawler.prepare()
        while current and pages < max_pages and not stop.is_set():
            if current in visited:
                raise EvaluationError("error.pagination_loop")
            visited.add(current)
            progress(translate(language, "crawling_page", page=pages + 1))
            html, final_url = crawler._get(current)
            if stop.is_set():
                break
            if final_url != current and final_url in visited:
                raise EvaluationError("error.pagination_loop")
            visited.add(final_url)
            # Levtech's homepage contains recommendations, not the complete search results.
            if (urlsplit(final_url).hostname == "freelance.levtech.jp"
                    and urlsplit(final_url).path == "/"):
                parser = DocumentParser()
                parser.feed(html)
                search = normalize_url(urljoin(final_url, "/project/search/"))
                if any(normalize_url(urljoin(final_url, href)) == search
                       for href in parser.links if href.startswith(("/", "https://"))):
                    progress(translate(language, "opening_job_search"))
                    current = normalize_url(urljoin(final_url, "/project/search/p1/"))
                    continue
            pages += 1
            listing = listing_links(html, final_url, limit=None)
            if (not listing.links and urlsplit(final_url).hostname == "freelance.levtech.jp"
                    and urlsplit(final_url).path == "/project/search/"):
                progress(translate(language, "opening_job_search"))
                current = normalize_url(urljoin(final_url, "/project/search/p1/"))
                pages -= 1
                continue
            following = next_page(html, final_url)
            if ai_config is not None and (not listing.links or following is None):
                progress(translate(language, "ai_analyzing_page"))
                ai_links, ai_next = analyze_listing(html, final_url, ai_config, ai_key)
                if stop.is_set():
                    break
                if not listing.links:
                    listing = Listing(ai_links, False)
                if following is None:
                    following = ai_next
            if not listing.links:
                raise EvaluationError("error.no_jobs")
            for link in listing.links:
                if stop.is_set():
                    break
                if link in jobs_seen:
                    continue
                jobs_seen.add(link)
                try:
                    progress(translate(language, "checking_job"))
                    if ai_config is None:
                        source, text = crawler.detail(link)
                    else:
                        detail_html, source = crawler._get(link)
                        if stop.is_set():
                            break
                        try:
                            text = job_text(detail_html)
                        except EvaluationError as exc:
                            if exc.key != "error.job_structure":
                                raise
                            progress(translate(language, "ai_analyzing_detail"))
                            text = analyze_detail(detail_html, ai_config, ai_key)
                        if stop.is_set():
                            break
                    if save_pending(connection, source, text):
                        saved += 1
                        progress(translate(language, "crawled_count", count=saved))
                    else:
                        progress(translate(language, "job_unchanged"))
                except (EvaluationError, OSError, UnicodeError, sqlite3.Error) as exc:
                    if stop.is_set():
                        break
                    if isinstance(exc, EvaluationError) and exc.key == "error.website_forbidden":
                        raise
                    detail = exc.localized(language) if isinstance(exc, EvaluationError) else str(exc)
                    failures.append(f"{link}: {detail}")
            if stop.is_set():
                break
            current = following
        limited = bool(current and pages >= max_pages and not stop.is_set())
    except EvaluationError:
        if not stop.is_set():
            raise
        limited = False
    finally:
        connection.close()
        if browser:
            crawler.close()
    return saved, failures, stop.is_set(), limited


def run_website(
    website: str, config: AppConfig, api_key: str, directory: Path,
    progress: Callable[[str], None], on_job: Callable[[JobRecord], None],
) -> tuple[int, list[str], bool]:
    crawler = Crawler(website)
    progress(translate(config["language"], "finding_jobs"))
    listing = crawler.listing()
    failures: list[str] = []
    saved = 0
    connection = open_database(directory / "jobs.sqlite3")
    try:
        for index, link in enumerate(listing.links, 1):
            progress(translate(config["language"], "processing",
                               index=index, total=len(listing.links), name=link))
            try:
                source, text = crawler.detail(link)
                result = request_evaluation(text, config, api_key)
                store_job(connection, source, result)
            except (EvaluationError, OSError, UnicodeError, sqlite3.Error) as exc:
                detail = exc.localized(config["language"]) if isinstance(exc, EvaluationError) else str(exc)
                failures.append(f"{link}: {detail}")
                progress(translate(config["language"], "job_failed", name=link))
            else:
                saved += 1
                on_job(JobRecord(source, result))
        export_csv(connection, directory / "csv")
    finally:
        connection.close()
    return saved, failures, listing.limited
