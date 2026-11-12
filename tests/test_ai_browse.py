import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.robotparser import RobotFileParser

from modules import ai_browse, core, crawler
from tests.test_crawler import detail
from tests.test_app import response


class AIBrowseTests(unittest.TestCase):
    def setUp(self):
        self.config = core.default_config()
        self.url = "https://example.com/search"

    def test_listing_uses_only_actual_same_origin_links_and_valid_indices(self):
        html = ('<h1>Search jobs</h1><a href="/roles/123">Python developer</a>'
                '<a href="?page=2">Next</a><a href="https://evil.example/roles/1">bad</a>'
                '<script>private script</script>')
        with patch("modules.ai_browse.request_json",
                   return_value={"job_indices": [0, 0], "next_index": 1}) as request:
            jobs, following = ai_browse.analyze_listing(html, self.url, self.config, "test-key")
        self.assertEqual(jobs, ["https://example.com/roles/123"])
        self.assertEqual(following, "https://example.com/search?page=2")
        payload = request.call_args.args[0]
        data = json.loads(payload["messages"][1]["content"])
        self.assertEqual(len(data["links"]), 2)
        self.assertNotIn("private script", data["page_text"])
        self.assertEqual(payload["response_format"]["json_schema"], ai_browse.LIST_SCHEMA)
        for result in ({"job_indices": [2], "next_index": -1},
                       {"job_indices": [True], "next_index": -1},
                       {"job_indices": [0], "next_index": 0},
                       {"job_indices": [], "next_index": -2},
                       {"job_indices": [], "next_index": -1, "extra": 1}):
            with self.subTest(result=result), patch("modules.ai_browse.request_json", return_value=result):
                with self.assertRaises(core.EvaluationError):
                    ai_browse.analyze_listing(html, self.url, self.config, "test-key")

    def test_detail_validation_and_input_limit(self):
        html = "<h1>Engineer</h1><p>Build Python services</p><script>do not send</script>"
        with patch("modules.ai_browse.request_json", return_value={"is_job": True}) as request:
            text = ai_browse.analyze_detail(html, self.config, "key")
        self.assertIn("Build Python services", text)
        self.assertNotIn("do not send", text)
        self.assertEqual(request.call_args.args[0]["response_format"]["json_schema"], ai_browse.DETAIL_SCHEMA)
        for result in ({"is_job": False}, {"is_job": "true"}, {}, {"is_job": True, "extra": 1}):
            with self.subTest(result=result), patch("modules.ai_browse.request_json", return_value=result):
                with self.assertRaises(core.EvaluationError):
                    ai_browse.analyze_detail(html, self.config, "key")
        with patch("modules.ai_browse.request_json") as request:
            with self.assertRaises(core.EvaluationError):
                ai_browse.analyze_detail("<p>" + "x" * (ai_browse.MAX_PAGE_CHARS + 1) + "</p>",
                                         self.config, "key")
            request.assert_not_called()

    def test_ai_fallback_discovers_pages_and_plain_detail_into_persistent_queue(self):
        second = "https://example.com/search?page=2"
        first_job = "https://example.com/roles/1"
        second_job = "https://example.com/roles/2"
        pages = {
            self.url: '<h1>Results</h1><a href="/roles/1">Developer</a><a href="?page=2">Next</a>',
            second: '<h1>Results page 2</h1><a href="/roles/2">Developer</a>',
            first_job: "<h1>Python Developer</h1><p>Build Python services</p>",
            second_job: detail(),
        }
        replies = [{"job_indices": [0], "next_index": 1}, {"is_job": True},
                   {"job_indices": [0], "next_index": -1}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with patch("modules.crawler.Crawler") as client, \
                    patch("modules.ai_browse.request_json", side_effect=replies) as request:
                client.return_value.website = self.url
                client.return_value._get.side_effect = lambda url: (pages[url], url)
                result = crawler.crawl_to_queue(self.url, path, "en", 10, threading.Event(),
                                                 lambda text: None, ai_config=self.config, ai_key="key")
            self.assertEqual(result, (2, [], False, False))
            self.assertEqual(request.call_count, 3)
            connection = core.open_database(path / "jobs.sqlite3")
            try:
                rows = dict(connection.execute("SELECT source, content FROM pending_jobs"))
                self.assertEqual(set(rows), {first_job, second_job})
                self.assertIn("Build Python services", rows[first_job])
                self.assertEqual(core.pending_count(connection), 2)
            finally:
                connection.close()

    def test_no_ai_calls_when_existing_rules_cover_page_and_detail(self):
        first_job = "https://example.com/jobs/1"
        html = '<a href="/jobs/1">job</a><link rel="next" href="?page=2">'
        with tempfile.TemporaryDirectory() as directory, \
                patch("modules.crawler.Crawler") as client, \
                patch("modules.ai_browse.request_json") as request:
            client.return_value.website = self.url
            client.return_value._get.side_effect = [(html, self.url), (detail(), first_job)]
            self.assertEqual(crawler.crawl_to_queue(
                self.url, Path(directory), "en", 1, threading.Event(), lambda text: None,
                ai_config=self.config, ai_key="key"), (1, [], False, True))
            request.assert_not_called()

    def test_stop_after_fetch_does_not_send_page_to_ai(self):
        stop = threading.Event()
        def fetch(url):
            stop.set()
            return "<h1>Results</h1>", url
        with tempfile.TemporaryDirectory() as directory, \
                patch("modules.crawler.Crawler") as client, \
                patch("modules.ai_browse.request_json") as request:
            client.return_value.website = self.url
            client.return_value._get.side_effect = fetch
            result = crawler.crawl_to_queue(self.url, Path(directory), "en", 10, stop,
                                            lambda text: None, ai_config=self.config, ai_key="key")
            self.assertEqual(result, (0, [], True, False))
            request.assert_not_called()

    def test_native_and_compatible_providers_receive_navigation_schema(self):
        html = '<h1>Results</h1><a href="/roles/1">Developer</a>'
        value = {"job_indices": [0], "next_index": -1}
        for provider in ("openai", "gemini", "custom"):
            config = core.default_config()
            config["provider"] = provider
            if provider == "gemini":
                config["base_url"] = "https://generativelanguage.googleapis.com/v1beta"
                config["model"] = "gemini-2.5-flash"
                api_response = {"candidates": [{"finishReason": "STOP",
                                                "content": {"parts": [{"text": json.dumps(value)}]}}]}
            else:
                api_response = response(value)
            with self.subTest(provider=provider), patch("modules.core.urlopen") as url:
                url.return_value.__enter__.return_value.read.return_value = json.dumps(api_response).encode()
                jobs, next_url = ai_browse.analyze_listing(html, self.url, config, "test-key")
                self.assertEqual((jobs, next_url), (["https://example.com/roles/1"], None))
                body = json.loads(url.call_args.args[0].data)
                if provider == "gemini":
                    self.assertEqual(body["generationConfig"]["responseJsonSchema"],
                                     ai_browse.LIST_SCHEMA["schema"])
                else:
                    self.assertEqual(body["response_format"]["json_schema"], ai_browse.LIST_SCHEMA)

    def test_ai_selected_link_obeys_robots(self):
        instance = crawler.Crawler(self.url)
        robot = RobotFileParser()
        robot.parse(["User-agent: *", "Disallow: /roles/"])
        instance.robots = robot
        instance.delay = 0
        html = '<h1>Results</h1><a href="/roles/1">Developer</a>'
        with tempfile.TemporaryDirectory() as directory, \
                patch("modules.crawler.Crawler", return_value=instance), \
                patch.object(instance, "prepare"), \
                patch.object(instance.opener, "open") as opener, \
                patch("modules.ai_browse.request_json",
                      return_value={"job_indices": [0], "next_index": -1}):
            response_mock = opener.return_value.__enter__.return_value
            response_mock.read.return_value = html.encode("utf-8")
            response_mock.headers.get_content_type.return_value = "text/html"
            response_mock.headers.get_content_charset.return_value = "utf-8"
            saved, failures, stopped, limited = crawler.crawl_to_queue(
                self.url, Path(directory), "en", 10, threading.Event(), lambda text: None,
                ai_config=self.config, ai_key="key")
            self.assertEqual((saved, len(failures), stopped, limited), (0, 1, False, False))
            self.assertIn("robots.txt", failures[0])
            self.assertEqual(opener.call_count, 1)


if __name__ == "__main__":
    unittest.main()
