import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.robotparser import RobotFileParser

from modules import core, crawler
from tests.test_app import result


def detail(title="Python", description="Python 開發<br>フルリモート可"):
    data = {"@context": "https://schema.org", "@type": "JobPosting",
            "title": title, "description": description,
            "jobLocation": {"address": "東京都"}}
    return ('<script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False).replace("<", "\\u003c") + "</script>")


class CrawlerTests(unittest.TestCase):
    def test_listing_links_deduplicates_limits_and_confines_origin(self):
        base = "https://example.com/search"
        links = "".join(f'<a href="/jobs/{index}">Job</a>' for index in range(25))
        html = (links + '<a href="/jobs/0#top">duplicate</a>'
                '<a href="https://elsewhere.com/jobs/123">external</a>'
                '<a href="javascript:alert(1)">bad</a>')
        found = crawler.listing_links(html, base)
        self.assertEqual(len(found.links), 20)
        self.assertTrue(found.limited)
        self.assertEqual(found.links[0], "https://example.com/jobs/0")
        self.assertEqual(found.links[-1], "https://example.com/jobs/19")
        self.assertEqual(len(set(found.links)), 20)

    def test_itemlist_and_malformed_structured_data(self):
        html = ('<script type="application/ld+json">{bad}</script>'
                '<script type="application/ld+json">'
                '{"@type":"ItemList","itemListElement":null}</script>'
                '<script type="application/ld+json">'
                '{"@type":"ItemList","itemListElement":['
                '{"item":{"url":"/roles/101"}},{"item":"/roles/102"}]}</script>')
        self.assertEqual(crawler.listing_links(html, "https://example.com/search").links,
                         ["https://example.com/roles/101", "https://example.com/roles/102"])

    def test_job_posting_only_and_html_cleaning(self):
        text = crawler.job_text(detail(description="Python<br>遠端<script>ignore</script><p>東京都</p>"))
        self.assertIn("Python\n遠端\n東京都", text)
        self.assertNotIn("ignore", text)
        self.assertIn('"jobLocation"', text)
        for html in ("<h1>Job</h1>", '<script type="application/ld+json">{"@type":"Organization"}</script>',
                     detail(description="")):
            with self.subTest(html=html), self.assertRaises(core.EvaluationError):
                crawler.job_text(html)

    def test_url_validation(self):
        for value in ("", "file:///C:/test", "https://user:pass@example.com/", "http://example.com:bad"):
            with self.subTest(value=value), self.assertRaises(core.EvaluationError):
                crawler.normalize_url(value)
        self.assertEqual(crawler.normalize_url(" https://example.com/jobs#top "), "https://example.com/jobs")

    def test_robot_rules_and_redirects(self):
        instance = crawler.Crawler("https://example.com/search")
        parser = RobotFileParser()
        parser.parse(["User-agent: *", "Disallow: /private/"])
        instance.robots = parser
        instance.delay = 0
        with patch.object(instance.opener, "open") as opener:
            with self.assertRaisesRegex(core.EvaluationError, "robots.txt"):
                instance._get("https://example.com/private/jobs")
            opener.assert_not_called()
        redirect = HTTPError("https://example.com/search", 302, "redirect",
                             {"Location": "https://other.example/jobs/1"}, None)
        with patch.object(instance.opener, "open", side_effect=redirect) as opener:
            with self.assertRaises(core.EvaluationError) as error:
                instance._get("https://example.com/search")
            self.assertEqual(error.exception.key, "error.website_redirect")
            self.assertEqual(opener.call_count, 1)

    def test_missing_robots_and_network_errors(self):
        instance = crawler.Crawler("https://example.com/search")
        instance.delay = 0
        missing = HTTPError("https://example.com/robots.txt", 404, "missing", {}, None)
        with patch.object(instance.opener, "open", side_effect=missing):
            instance.prepare()
        self.assertTrue(instance.robots.can_fetch(crawler.USER_AGENT, instance.website))
        with patch.object(instance.opener, "open", side_effect=URLError("offline")):
            with self.assertRaises(core.EvaluationError) as error:
                instance._get(instance.website)
        self.assertEqual(error.exception.key, "error.website_network")

    def test_robots_403_reports_stage_and_does_not_ignore_policy(self):
        instance = crawler.Crawler("https://example.com/search")
        denied = HTTPError(instance.website, 403, "denied", {}, None)
        with patch.object(instance.opener, "open", side_effect=denied) as request:
            with self.assertRaises(core.EvaluationError) as error:
                instance.prepare()
        self.assertEqual(error.exception.key, "error.website_forbidden")
        self.assertEqual(error.exception.values["stage"], "robots.txt")
        self.assertEqual(request.call_count, 1)
        self.assertIsNone(instance.robots)

    def test_detail_403_stops_batch_without_repeated_requests(self):
        url = "https://example.com/search"
        with tempfile.TemporaryDirectory() as directory, patch("modules.crawler.Crawler") as factory:
            client = factory.return_value
            client.website = url
            client._get.return_value = ('<a href="/jobs/1">One</a><a href="/jobs/2">Two</a>', url)
            client.detail.side_effect = core.EvaluationError("error.website_forbidden", stage="HTML")
            with self.assertRaises(core.EvaluationError):
                crawler.crawl_to_queue(url, Path(directory), "en", 1, threading.Event(), lambda text: None)
            self.assertEqual(client.detail.call_count, 1)

    def test_website_batch_partial_failure_and_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            links = ["https://example.com/jobs/1", "https://example.com/jobs/2"]
            published = []
            progress = []
            config = core.default_config()
            config["language"] = "en"
            with patch("modules.crawler.Crawler") as client, \
                    patch("modules.crawler.request_evaluation", return_value=result()):
                client.return_value.listing.return_value = crawler.Listing(links, True)
                client.return_value.detail.side_effect = [(links[0], "Python remote"),
                                                         core.EvaluationError("error.job_structure")]
                saved, failures, limited = crawler.run_website(
                    "https://example.com/search", config, "key", path, progress.append, published.append)
            self.assertEqual(saved, 1)
            self.assertTrue(limited)
            self.assertEqual(len(failures), 1)
            self.assertIn("no recognizable JobPosting data", failures[0])
            self.assertEqual(published, [core.JobRecord(links[0], result())])
            connection = core.open_database(path / "jobs.sqlite3")
            try:
                self.assertEqual(core.load_jobs(connection), published)
            finally:
                connection.close()
            self.assertTrue((path / "csv" / "coincidence.csv").exists())

    def test_paginated_queue_respects_duplicates_and_limit(self):
        first = "https://example.com/search"
        second = "https://example.com/search?p=2"
        third = "https://example.com/search?p=3"
        html1 = '<a href="/jobs/1">A</a><link rel="next" href="?p=2">'
        html2 = '<a href="/jobs/1">A</a><a href="/jobs/2">B</a><link rel="next" href="?p=3">'
        pages = {first: html1, second: html2}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with patch("modules.crawler.Crawler") as client:
                client.return_value.website = first
                client.return_value._get.side_effect = lambda url: (pages[url], url)
                client.return_value.detail.side_effect = lambda url: (url, "job " + url)
                saved, failures, stopped, limited = crawler.crawl_to_queue(
                    first, path, "en", 2, threading.Event(), lambda text: None)
            self.assertEqual((saved, failures, stopped, limited), (2, [], False, True))
            self.assertEqual(client.return_value.detail.call_count, 2)
            connection = core.open_database(path / "jobs.sqlite3")
            try:
                self.assertEqual(core.pending_count(connection), 2)
            finally:
                connection.close()

    def test_stop_keeps_committed_jobs_and_repeated_crawl_preserves_status(self):
        url = "https://example.com/search"
        job = "https://example.com/jobs/1"
        stop = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with patch("modules.crawler.Crawler") as client:
                client.return_value.website = url
                client.return_value._get.return_value = ('<a href="/jobs/1">A</a><a href="/jobs/2">B</a>', url)
                def fetch(link):
                    stop.set()
                    return link, "job text"
                client.return_value.detail.side_effect = fetch
                saved, failures, stopped, limited = crawler.crawl_to_queue(
                    url, path, "zh-TW", 10, stop, lambda text: None)
            self.assertEqual((saved, failures, stopped, limited), (1, [], True, False))
            connection = core.open_database(path / "jobs.sqlite3")
            try:
                self.assertEqual(core.pending_count(connection), 1)
                connection.execute("UPDATE pending_jobs SET status='processed' WHERE source=?", (job,))
                connection.commit()
                self.assertFalse(core.save_pending(connection, job, "job text"))
                self.assertEqual(core.pending_count(connection), 0)
                self.assertTrue(core.save_pending(connection, job, "updated job text"))
                self.assertEqual(core.pending_count(connection), 1)
            finally:
                connection.close()

    def test_pagination_loop_and_cross_origin_blocked(self):
        url = "https://example.com/search"
        with self.assertRaises(core.EvaluationError):
            crawler.next_page('<link rel="next" href="https://other.example/search">', url)
        with tempfile.TemporaryDirectory() as directory, patch("modules.crawler.Crawler") as client:
            client.return_value.website = url
            client.return_value._get.return_value = ('<a href="/jobs/1">A</a><link rel="next" href="/search">', url)
            client.return_value.detail.return_value = ("https://example.com/jobs/1", "job text")
            with self.assertRaises(core.EvaluationError) as error:
                crawler.crawl_to_queue(url, Path(directory), "en", 10, threading.Event(), lambda text: None)
            self.assertEqual(error.exception.key, "error.pagination_loop")
            connection = core.open_database(Path(directory) / "jobs.sqlite3")
            try:
                self.assertEqual(core.pending_count(connection), 1)
            finally:
                connection.close()

    def test_recrawl_checks_for_updates_but_unchanged_jobs_stay_processed(self):
        url = "https://example.com/search"
        job = "https://example.com/jobs/1"
        with tempfile.TemporaryDirectory() as directory, patch("modules.crawler.Crawler") as client:
            path = Path(directory)
            client.return_value.website = url
            client.return_value._get.return_value = ('<a href="/jobs/1">A</a>', url)
            client.return_value.detail.return_value = (job, "unchanged")
            progress = []
            crawler.crawl_to_queue(url, path, "en", 10, threading.Event(), progress.append)
            connection = core.open_database(path / "jobs.sqlite3")
            try:
                connection.execute("UPDATE pending_jobs SET status='processed' WHERE source=?", (job,))
                connection.commit()
            finally:
                connection.close()
            saved, failures, stopped, limited = crawler.crawl_to_queue(
                url, path, "en", 10, threading.Event(), progress.append)
            self.assertEqual((saved, failures, stopped, limited), (0, [], False, False))
            self.assertEqual(client.return_value.detail.call_count, 2)
            self.assertTrue(any("unchanged" in item.lower() for item in progress))
            connection = core.open_database(path / "jobs.sqlite3")
            try:
                self.assertEqual(core.pending_count(connection), 0)
            finally:
                connection.close()
