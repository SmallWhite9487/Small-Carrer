import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from modules import capture, core


PAYLOAD = {
    "url": "https://www.linkedin.com/jobs/view/analyst-12345/",
    "title": "Business Analyst",
    "company": "Acme",
    "location": "Remote - US",
    "text": "We need SQL and Looker.\nRemote within the United States.",
}


class MarkdownTests(unittest.TestCase):
    def test_markdown_keeps_source_and_fields(self) -> None:
        url, content = capture.job_markdown(PAYLOAD)
        self.assertEqual(url, PAYLOAD["url"])
        self.assertIn("Company: Acme", content)
        self.assertIn("Location: Remote - US", content)
        self.assertIn("We need SQL and Looker.", content)
        self.assertNotIn("<", content)

    def test_invalid_payloads(self) -> None:
        for value in ({}, {**PAYLOAD, "url": "file:///etc/passwd"},
                      {**PAYLOAD, "url": "javascript:alert(1)"},
                      {**PAYLOAD, "title": ""}, {**PAYLOAD, "text": "  "},
                      {**PAYLOAD, "title": 3}):
            with self.subTest(value=value), self.assertRaises(core.EvaluationError):
                capture.job_markdown(value)

    def test_bookmarklet_is_encoded_and_targets_loopback(self) -> None:
        value = capture.bookmarklet(4321, "tok")
        self.assertTrue(value.startswith("javascript:"))
        self.assertIn("127.0.0.1%3A4321", value)
        self.assertIn("tok", value)
        self.assertNotIn(" ", value)


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)
        self.server = capture.CaptureServer(self.path)
        self.server.start()

    def tearDown(self) -> None:
        self.server.close()
        self.directory.cleanup()

    def post(self, payload: object, token: str | None = None,
             path: str = "/job") -> tuple[int, object]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(f"{self.server.url}{path}?token={token or self.server.token}",
                          data=body, headers={"Content-Type": "application/json"},
                          method="POST")
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            exc.close()
            return exc.code, {}

    def pending(self) -> int:
        connection = core.open_database(self.path / "jobs.sqlite3")
        try:
            return core.pending_count(connection)
        finally:
            connection.close()

    def test_capture_queues_and_deduplicates(self) -> None:
        status, body = self.post(PAYLOAD)
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(body["added"])
        self.assertEqual(self.pending(), 1)
        self.assertEqual(self.server.drain(), 1)
        status, body = self.post(PAYLOAD)
        self.assertEqual(status, 200)
        self.assertFalse(body["added"])
        self.assertEqual(self.pending(), 1)

    def test_requires_token_and_valid_body(self) -> None:
        self.assertEqual(self.post(PAYLOAD, token="wrong")[0], 403)
        self.assertEqual(self.post({"title": "x"})[0], 400)
        self.assertEqual(self.post([1, 2])[0], 400)
        self.assertEqual(self.pending(), 0)

    def test_ping_and_options(self) -> None:
        with urlopen(f"{self.server.url}/ping", timeout=5) as response:
            self.assertEqual(json.loads(response.read().decode("utf-8")), {"ok": True})
        request = Request(f"{self.server.url}/job", method="OPTIONS")
        with urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 204)
            self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")

    def test_clipboard_import(self) -> None:
        ok, title, key = capture.import_text(self.server, json.dumps(PAYLOAD))
        self.assertEqual((ok, title, key), (True, "Business Analyst", "captured_added"))
        ok, _, key = capture.import_text(self.server, json.dumps(PAYLOAD))
        self.assertEqual((ok, key), (True, "captured_duplicate"))
        self.assertEqual(capture.import_text(self.server, "not json"),
                         (False, "", "error.capture"))
        self.assertEqual(capture.import_text(self.server, "[]"),
                         (False, "", "error.capture"))


if __name__ == "__main__":
    unittest.main()
