from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from modules import core, crawler
from modules.browser_crawler import BrowserCrawler


class BrowserTests(unittest.TestCase):
    def test_javascript_jobs_and_pagination_are_rendered(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/robots.txt":
                    body = "User-agent: *\nDisallow: /private/"
                    kind = "text/plain"
                else:
                    body = """<html><body><h1>Jobs</h1><script>
setTimeout(() => {
 const a = document.createElement('a');
 a.href = '/jobs/123'; a.textContent = 'Python developer'; document.body.append(a);
 const n = document.createElement('a');
 n.href = '/search?page=2'; n.textContent = 'Next'; document.body.append(n);
}, 600);
</script></body></html>"""
                    kind = "text/html"
                self.send_response(200)
                self.send_header("Content-Type", kind + "; charset=utf-8")
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        workspace = tempfile.TemporaryDirectory()
        client = BrowserCrawler(base + "/search", directory=Path(workspace.name))
        try:
            client.prepare()
            html, url = client._get(client.website)
            self.assertEqual(crawler.listing_links(html, url).links, [base + "/jobs/123"])
            self.assertEqual(crawler.next_page(html, url), base + "/search?page=2")
            self.assertTrue(Path(client.workspace.name).is_relative_to(Path(workspace.name) / "browser"))
            profile = Path(client.workspace.name)
            self.assertTrue((profile / "profile").is_dir())
            with self.assertRaises(core.EvaluationError):
                client._get(base + "/private/")
        finally:
            client.close()
            self.assertFalse(profile.exists())
            workspace.cleanup()
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertIsNone(client.runtime)

    def test_levtech_home_enters_page_one_and_closes_browser(self):
        home = "https://freelance.levtech.jp/"
        search = home + "project/search/p1/"
        job = home + "project/detail/1/"
        with tempfile.TemporaryDirectory() as directory, \
                patch("modules.browser_crawler.BrowserCrawler") as factory:
            client = factory.return_value
            client.website = home
            client._get.side_effect = [
                ('<a href="/project/search/">Search jobs</a>', home),
                ('<a href="/project/detail/1/">Job</a>', search),
            ]
            client.detail.return_value = (job, "Python developer")
            result = crawler.crawl_to_queue(
                home, Path(directory), "en", 1, threading.Event(), lambda text: None, browser=True)
            self.assertEqual(result, (1, [], False, False))
            self.assertEqual(client._get.call_args_list[1].args[0], search)
            client.close.assert_called_once()

    def test_unrelated_arrow_is_not_next_page(self):
        self.assertIsNone(crawler.next_page(
            '<a href="/register">→</a>', "https://example.com/search"))
        self.assertEqual(crawler.next_page(
            '<a href="?page=2">Next</a>', "https://example.com/search"),
            "https://example.com/search?page=2")

    def test_browser_403_reports_stage_without_retrying(self):
        client = BrowserCrawler("https://example.com/search")
        from urllib.robotparser import RobotFileParser

        client.robots = RobotFileParser()
        client.robots.parse(["User-agent: *", "Allow: /"])
        client.page = Mock()
        client.page.goto.return_value.status = 403
        client.delay = 0
        with self.assertRaises(core.EvaluationError) as error:
            client._get(client.website)
        self.assertEqual(error.exception.key, "error.website_forbidden")
        self.assertEqual(error.exception.values["stage"], "Chromium")
        client.page.goto.assert_called_once()


if __name__ == "__main__":
    unittest.main()
