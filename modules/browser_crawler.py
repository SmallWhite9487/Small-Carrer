import os
from pathlib import Path
import re
import sys
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page, Playwright, Route

from .core import EvaluationError
from .crawler import Crawler, MAX_BYTES, TIMEOUT, USER_AGENT, normalize_url, origin


class BrowserCrawler(Crawler):
    def __init__(self, website: str, stop: threading.Event | None = None) -> None:
        super().__init__(website, stop)
        self.runtime: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.blocked: EvaluationError | None = None

    def prepare(self) -> None:
        super().prepare()
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError as exc:
            raise EvaluationError("error.browser_missing") from exc
        if getattr(sys, "frozen", False):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(
                Path(getattr(sys, "_MEIPASS")) / "browsers")
        try:
            self.runtime = sync_playwright().start()
            self.browser = self.runtime.chromium.launch(headless=False)
            self.context = self.browser.new_context(user_agent=USER_AGENT, accept_downloads=False)
            self.context.route("**/*", self.guard_request)
            self.page = self.context.new_page()
        except Error as exc:
            self.close()
            raise EvaluationError("error.browser_missing") from exc

    def guard_request(self, route: "Route") -> None:
        request = route.request
        if self.stop is not None and self.stop.is_set():
            route.abort()
            return
        if request.is_navigation_request() and request.frame.parent_frame is None:
            try:
                url = normalize_url(request.url)
                if origin(url) != self.site:
                    raise EvaluationError("error.website_redirect")
                if self.robots is None or not self.robots.can_fetch(USER_AGENT, url):
                    raise EvaluationError("error.robots_denied")
            except EvaluationError as exc:
                self.blocked = exc
                route.abort()
                return
        route.continue_()

    def _get(self, url: str, *, robots: bool = False) -> tuple[str, str]:
        if robots:
            return super()._get(url, robots=True)
        from playwright.sync_api import Error

        url = normalize_url(url)
        if origin(url) != self.site:
            raise EvaluationError("error.website_redirect")
        if self.robots is None or not self.robots.can_fetch(USER_AGENT, url):
            raise EvaluationError("error.robots_denied")
        if self.page is None:
            raise EvaluationError("error.browser_missing")
        wait = max(0, self.delay - (time.monotonic() - self.last_request))
        if self.stop is None:
            time.sleep(wait)
        elif self.stop.wait(wait):
            raise EvaluationError("error.stopped")
        self.last_request = time.monotonic()
        self.blocked = None
        try:
            response = self.page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT * 1000)
            if response is not None and response.status == 403:
                raise EvaluationError("error.website_forbidden", stage="Chromium")
            if response is not None and response.status >= 400:
                raise EvaluationError("error.website_http", code=response.status)
            # Give hydration and scroll-triggered content bounded time to settle.
            previous = ""
            for step in range(12):
                if self.stop is not None and self.stop.is_set():
                    raise EvaluationError("error.stopped")
                self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                more = self.page.get_by_role("button", name=re.compile(
                    r"^(?:Load more|Show more|もっと見る|さらに表示|載入更多|加载更多)$", re.I))
                if step < 5 and more.count() == 1 and more.is_visible() and more.is_enabled():
                    more.click(timeout=3000)
                self.page.wait_for_timeout(500)
                current = self.page.locator("body").inner_text(timeout=3000)
                if step >= 3 and current == previous:
                    break
                previous = current
            if self.blocked is not None:
                raise self.blocked
            final_url = normalize_url(self.page.url)
            if origin(final_url) != self.site:
                raise EvaluationError("error.website_redirect")
            html = self.page.content()
            if len(html.encode("utf-8")) > MAX_BYTES:
                raise EvaluationError("error.website_large")
            return html, final_url
        except Error as exc:
            if self.stop is not None and self.stop.is_set():
                raise EvaluationError("error.stopped") from exc
            if self.blocked is not None:
                raise self.blocked from exc
            raise EvaluationError("error.browser_read") from exc

    def close(self) -> None:
        try:
            if self.browser is not None:
                self.browser.close()
        finally:
            if self.runtime is not None:
                self.runtime.stop()
            self.browser = None
            self.runtime = None
            self.context = None
            self.page = None
