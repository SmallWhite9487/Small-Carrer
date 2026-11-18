"""Collect job listings from public, documented job-board APIs.

LinkedIn has no public search or apply API and its user agreement forbids
automated access, so this module only talks to services that publish their
openings for machine reading: Greenhouse, Lever, Ashby, Workable and Remotive.
Everything collected here is written to ``pending_jobs`` and then flows through
the same AI evaluation and card rendering as a manually crawled page.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from .core import SOURCE_PATTERN, EvaluationError, open_database, save_pending
from .i18n import Language, translate


USER_AGENT = "SmallCareerBot/1.0 (+personal job search)"
TIMEOUT = 25
MAX_BYTES = 4_000_000
MAX_JOBS = 100
PAUSE = 0.3

PROVIDERS = ("greenhouse", "lever", "ashby", "workable", "remotive")


@dataclass(frozen=True)
class JobListing:
    url: str
    title: str
    company: str
    location: str
    body: str

    def markdown(self) -> str:
        lines = [self.title, ""]
        if self.company:
            lines.append(f"Company: {self.company}")
        if self.location:
            lines.append(f"Location: {self.location}")
        lines.extend(["", self.body])
        return "\n".join(lines).strip() + "\n"


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self.ignored += 1
        elif tag in ("br", "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "tr", "ul", "ol"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self.ignored:
            self.ignored -= 1
        elif tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "h5", "tr", "ul", "ol"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)

    def text(self) -> str:
        return "\n".join(
            line.strip() for line in "".join(self.parts).splitlines() if line.strip())


def html_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    parser = TextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except (ValueError, AssertionError):
        return " ".join(value.split())
    return parser.text()


def plain_text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def pick(item: dict, *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        text = plain_text(value)
        if text:
            return text
    return ""


def nested(item: dict, key: str, field: str) -> str:
    value = item.get(key)
    if isinstance(value, dict):
        return plain_text(value.get(field))
    return plain_text(value)


def parse_source(value: str) -> tuple[str, str]:
    text = value.strip()
    if not SOURCE_PATTERN.fullmatch(text):
        raise EvaluationError("error.sources")
    provider, token = text.split(":", 1)
    return provider, token


def endpoint(provider: str, token: str) -> str:
    name = quote(token, safe="")
    if provider == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{name}/jobs?content=true"
    if provider == "lever":
        return f"https://api.lever.co/v0/postings/{name}?mode=json"
    if provider == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true"
    if provider == "workable":
        return f"https://apply.workable.com/api/v1/widget/accounts/{name}?details=true"
    return f"https://remotive.com/api/remote-jobs?limit={MAX_JOBS}" + (
        "" if token == "all" else f"&category={name}")


def parse_greenhouse(payload: object, token: str) -> list[JobListing]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        raise EvaluationError("error.source_response")
    listings: list[JobListing] = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        url = pick(item, "absolute_url")
        title = pick(item, "title")
        if not url.startswith(("http://", "https://")) or not title:
            continue
        listings.append(JobListing(
            url=url,
            title=title,
            company=pick(item, "company_name") or token,
            location=nested(item, "location", "name"),
            body=html_text(item.get("content")),
        ))
    return listings


def parse_lever(payload: object, token: str) -> list[JobListing]:
    if not isinstance(payload, list):
        raise EvaluationError("error.source_response")
    listings: list[JobListing] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        url = pick(item, "hostedUrl")
        title = pick(item, "text")
        if not url.startswith(("http://", "https://")) or not title:
            continue
        body = plain_text(item.get("descriptionPlain")) or html_text(item.get("description"))
        lists = item.get("lists")
        if isinstance(lists, list):
            for block in lists:
                if isinstance(block, dict):
                    heading = plain_text(block.get("text"))
                    content = html_text(block.get("content"))
                    if heading or content:
                        body = f"{body}\n{heading}\n{content}".strip()
        listings.append(JobListing(
            url=url,
            title=title,
            company=token,
            location=nested(item, "categories", "location"),
            body=body,
        ))
    return listings


def parse_ashby(payload: object, token: str) -> list[JobListing]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        raise EvaluationError("error.source_response")
    listings: list[JobListing] = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        url = pick(item, "jobUrl", "applyUrl")
        title = pick(item, "title")
        if not url.startswith(("http://", "https://")) or not title:
            continue
        listings.append(JobListing(
            url=url,
            title=title,
            company=pick(item, "organizationName") or token,
            location=pick(item, "location"),
            body=html_text(item.get("descriptionHtml")) or plain_text(item.get("descriptionPlain")),
        ))
    return listings


def parse_workable(payload: object, token: str) -> list[JobListing]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        raise EvaluationError("error.source_response")
    listings: list[JobListing] = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        url = pick(item, "url", "shortlink")
        title = pick(item, "title")
        if not url.startswith(("http://", "https://")) or not title:
            continue
        listings.append(JobListing(
            url=url,
            title=title,
            company=pick(payload, "name") if isinstance(payload, dict) else token,
            location=nested(item, "location", "location_str")
            or nested(item, "location", "city"),
            body=html_text(item.get("description")) or plain_text(item.get("requirements")),
        ))
    return listings


def parse_remotive(payload: object, token: str) -> list[JobListing]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        raise EvaluationError("error.source_response")
    listings: list[JobListing] = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        url = pick(item, "url")
        title = pick(item, "title")
        if not url.startswith(("http://", "https://")) or not title:
            continue
        listings.append(JobListing(
            url=url,
            title=title,
            company=pick(item, "company_name"),
            location=pick(item, "candidate_required_location"),
            body=html_text(item.get("description")),
        ))
    return listings


PARSERS: dict[str, Callable[[object, str], list[JobListing]]] = {
    "greenhouse": parse_greenhouse,
    "lever": parse_lever,
    "ashby": parse_ashby,
    "workable": parse_workable,
    "remotive": parse_remotive,
}


def parse_payload(provider: str, token: str, payload: object) -> list[JobListing]:
    parser = PARSERS.get(provider)
    if parser is None:
        raise EvaluationError("error.sources")
    listings = parser(payload, token)
    checked: list[JobListing] = []
    seen: set[str] = set()
    for listing in listings:
        key = urlsplit(listing.url).path
        if (not listing.body.strip() or key in seen
                or urlsplit(listing.url).scheme not in ("http", "https")):
            continue
        seen.add(key)
        checked.append(listing)
    return checked[:MAX_JOBS]


def fetch_payload(url: str) -> object:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            data = response.read(MAX_BYTES + 1)
    except HTTPError as exc:
        exc.close()
        raise EvaluationError("error.source_http", code=exc.code) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise EvaluationError("error.source_network") from exc
    if len(data) > MAX_BYTES:
        raise EvaluationError("error.source_response")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluationError("error.source_response") from exc


def fetch_listings(spec: str) -> list[JobListing]:
    provider, token = parse_source(spec)
    return parse_payload(provider, token, fetch_payload(endpoint(provider, token)))


def collect(
    sources: list[str], directory: Path, language: Language = "zh-TW",
    stop: threading.Event | None = None, progress: Callable[[str], None] | None = None,
) -> tuple[int, list[str]]:
    """Fetch every configured source and queue new jobs for AI evaluation."""
    stop = threading.Event() if stop is None else stop
    progress = (lambda text: None) if progress is None else progress
    saved = 0
    failures: list[str] = []
    connection = open_database(directory / "jobs.sqlite3")
    try:
        for index, raw in enumerate(sources, 1):
            if stop.is_set():
                break
            spec = raw.strip()
            if not spec:
                continue
            progress(translate(language, "source_fetching", index=index,
                               total=len(sources), name=spec))
            try:
                listings = fetch_listings(spec)
            except (EvaluationError, OSError) as exc:
                detail = exc.localized(language) if isinstance(exc, EvaluationError) else type(exc).__name__
                failures.append(f"{spec}: {detail}")
            else:
                for listing in listings:
                    if stop.is_set():
                        break
                    try:
                        if save_pending(connection, listing.url, listing.markdown()):
                            saved += 1
                    except (EvaluationError, sqlite3.Error) as exc:
                        detail = (exc.localized(language) if isinstance(exc, EvaluationError)
                                  else type(exc).__name__)
                        failures.append(f"{listing.url}: {detail}")
                progress(translate(language, "source_collected",
                                   name=spec, count=len(listings)))
            if not stop.is_set():
                stop.wait(PAUSE)
    finally:
        connection.close()
    return saved, failures
