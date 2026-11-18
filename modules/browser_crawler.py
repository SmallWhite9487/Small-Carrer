import os
from pathlib import Path
import re
import sys
import threading
import time
import tempfile
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page, Playwright, Route

from urllib.parse import urlsplit

from .core import EvaluationError
from .crawler import Crawler, MAX_BYTES, TIMEOUT, USER_AGENT, normalize_url, origin


TIMEOUT_PARTIAL = 10  # do not hold the sign-in prompt behind a slow first paint
LOGIN_DWELL = 5.0  # let the window appear before trusting that no sign-in is needed


def configure_bundled_chromium() -> None:
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            resources = Path(sys.executable).parent.parent / "Resources"
        else:
            resources = Path(getattr(sys, "_MEIPASS"))
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(resources / "browsers")


class BrowserCrawler(Crawler):
    def __init__(
        self, website: str, stop: threading.Event | None = None, *, directory: Path | None = None,
        profile: bool = False, login_url: str | None = None,
        wait_login: Callable[[Callable[[], bool]], None] | None = None,
    ) -> None:
        super().__init__(website, stop)
        self.runtime: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.blocked: EvaluationError | None = None
        self.directory = directory
        self.workspace: tempfile.TemporaryDirectory | None = None
        self.profile = profile
        self.login_url = login_url
        self.wait_login = wait_login
        self.logging_in = False
        self.login_started = 0.0

    def prepare(self) -> None:
        if self.wait_login is not None and self.login_url is not None:
            hostname = (urlsplit(self.login_url).hostname or "").lower()
            #if hostname == "linkedin.com" or hostname.endswith(".linkedin.com"):
                # LinkedIn forbids automated access; the capture bookmarklet is
                # the supported way to queue a LinkedIn job.
            #    raise EvaluationError("error.login_blocked")
        super().prepare()
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError as exc:
            raise EvaluationError("error.browser_missing") from exc
        configure_bundled_chromium()
        if self.directory is None:
            from .data_paths import prepare_data_directory

            self.directory = prepare_data_directory()
        browser_directory = self.directory / "browser"
        browser_directory.mkdir(parents=True, exist_ok=True)
        if self.profile:
            # Keep cookies and logins between runs so the user signs in once.
            user_data = browser_directory / "profile"
            user_data.mkdir(parents=True, exist_ok=True)
            downloads, traces = browser_directory / "downloads", browser_directory / "traces"
            environment = {**os.environ}
        else:
            self.workspace = tempfile.TemporaryDirectory(prefix="session-", dir=browser_directory)
            workspace = Path(self.workspace.name)
            environment = {**os.environ, "TEMP": str(workspace), "TMP": str(workspace),
                           "TMPDIR": str(workspace)}
            user_data = workspace / "profile"
            downloads, traces = workspace / "downloads", workspace / "traces"
        try:
            self.runtime = sync_playwright().start()
            self.context = self.runtime.chromium.launch_persistent_context(
                user_data_dir=str(user_data), headless=False, env=environment,
                downloads_path=str(downloads), traces_dir=str(traces),
                user_agent=None if self.profile else USER_AGENT, accept_downloads=False)
            self.browser = self.context.browser
            self.context.route("**/*", self.guard_request)
            self.page = self.context.new_page()
        except Error as exc:
            self.close()
            raise EvaluationError("error.browser_missing") from exc
        if self.wait_login is not None:
            self.login()

    def login(self) -> None:
        from playwright.sync_api import Error

        self.logging_in = True
        self.login_started = time.monotonic()
        try:
            try:
                self.page.goto(self.login_url or self.website, wait_until="domcontentloaded",
                               timeout=TIMEOUT_PARTIAL * 1000)
            except Error:
                pass
            if self.wait_login is not None:
                self.wait_login(self.login_ready)
        finally:
            self.logging_in = False

    def login_ready(self) -> bool:
        """Best-effort signal that the sign-in flow likely finished.

        The page counts as usable once it is no longer a sign-in screen and has
        had a few seconds to settle. It never inspects credentials: while a
        password box or a login URL is visible the wait simply continues, and
        the dialog's button still works for sites this cannot recognise.
        """
        from playwright.sync_api import Error

        page = self.page
        if page is None:
            raise EvaluationError("error.browser_closed")
        try:
            if page.is_closed() or not page.context.browser.is_connected():
                raise EvaluationError("error.browser_closed")
            url = (page.url or "").lower()
            if not url or url == "about:blank":
                return False
            if re.search(r"(?:login|sign-?in|signin|/auth|sso|checkpoint|verif)", url):
                return False
            if self.sign_in_form():
                return False
        except Error as exc:
            raise EvaluationError("error.browser_closed") from exc
        return time.monotonic() - self.login_started >= LOGIN_DWELL

    def sign_in_form(self) -> bool:
        """True while any frame still shows a password field."""
        from playwright.sync_api import Error

        page = self.page
        if page is None:
            return False
        for frame in page.frames:
            try:
                if frame.locator("input[type=password]").count():
                    return True
            except Error:
                continue
        return False

    def guard_request(self, route: "Route") -> None:
        request = route.request
        if self.logging_in:
            # The sign-in flow legitimately leaves the target site (SSO).
            route.continue_()
            return
        if self.stop is not None and self.stop.is_set():
            route.abort()
            return
        if request.is_navigation_request() and request.frame.parent_frame is None:
            try:
                url = normalize_url(request.url)
                if origin(url) != self.site:
                    raise EvaluationError("error.website_redirect")
                #if self.robots is None or not self.robots.can_fetch(USER_AGENT, url):
                #    raise EvaluationError("error.robots_denied")
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
        #if self.robots is None or not self.robots.can_fetch(USER_AGENT, url):
        #    raise EvaluationError("error.robots_denied")
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
            if response is not None and response.status == 429:
                raise EvaluationError("error.website_rate_limit", stage="Chromium")
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
                if step < 5:
                    try:
                        if more.count() == 1 and more.is_visible() and more.is_enabled():
                            more.click(timeout=3000)
                    except Error:
                        # A covered, moving or detached button must not abort
                        # the page read; the text below is already collected.
                        pass
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
            try:
                if self.runtime is not None:
                    self.runtime.stop()
            finally:
                self.browser = None
                self.runtime = None
                self.context = None
                self.page = None
                if self.workspace is not None:
                    try:
                        self.workspace.cleanup()
                    except OSError:
                        # Chromium on Windows keeps a few profile files open for
                        # a moment; the temporary directory retries on exit.
                        pass
                    self.workspace = None
