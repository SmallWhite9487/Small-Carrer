import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from modules import core
from tests.test_app import response, result


class ProviderQueueTests(unittest.TestCase):
    def test_gemini_native_schema_and_response_for_jobs_and_polish(self):
        config = core.default_config()
        config["provider"] = "gemini"
        config["base_url"] = "https://generativelanguage.googleapis.com/v1beta"
        config["model"] = "gemini-2.5-flash"
        def native(value):
            return {"candidates": [{"finishReason": "STOP",
                                    "content": {"parts": [{"text": json.dumps(value, ensure_ascii=False)}]}}]}
        with patch("modules.core.urlopen") as url:
            url.return_value.__enter__.return_value.read.return_value = json.dumps(native(result())).encode()
            self.assertEqual(core.request_evaluation("Job", config, "gemini-test"), result())
            request = url.call_args.args[0]
            body = json.loads(request.data)
            self.assertTrue(request.full_url.endswith("/models/gemini-2.5-flash:generateContent"))
            self.assertEqual(request.get_header("X-goog-api-key"), "gemini-test")
            self.assertEqual(body["generationConfig"]["responseJsonSchema"], core.JOB_SCHEMA["schema"])
            self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
            self.assertIn("systemInstruction", body)
            url.return_value.__enter__.return_value.read.return_value = json.dumps(
                native({"requirements": "Python"})).encode()
            self.assertEqual(core.polish_requirements("Python", config, "gemini-test"), "Python")
            self.assertEqual(json.loads(url.call_args.args[0].data)["generationConfig"]["responseJsonSchema"],
                             core.POLISH_SCHEMA["schema"])
            url.return_value.__enter__.return_value.read.return_value = json.dumps(
                {"candidates": [{"finishReason": "MAX_TOKENS"}]}).encode()
            with self.assertRaises(core.EvaluationError):
                core.request_evaluation("Job", config, "gemini-test")

    def test_openai_and_custom_endpoints_and_key_isolation(self):
        for provider, key in (("openai", "openai-test"), ("custom", "")):
            config = core.default_config()
            config["provider"] = provider
            if provider == "custom":
                config["base_url"] = "http://localhost:11434/v1"
            with patch("modules.core.urlopen") as url:
                url.return_value.__enter__.return_value.read.return_value = json.dumps(response(result())).encode()
                self.assertEqual(core.request_evaluation("Job", config, key), result())
                request = url.call_args.args[0]
                self.assertTrue(request.full_url.endswith("/chat/completions"))
                if key:
                    self.assertEqual(request.get_header("Authorization"), "Bearer openai-test")
                else:
                    self.assertIsNone(request.get_header("Authorization"))

    def test_failed_pending_retries_and_success_is_not_reprocessed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            conn = core.open_database(path / "jobs.sqlite3")
            try:
                core.save_pending(conn, "https://example.com/jobs/1", "Job one")
                core.save_pending(conn, "https://example.com/jobs/2", "Job two")
            finally:
                conn.close()
            seen = []
            with patch("modules.core.request_evaluation",
                       side_effect=[result(), core.EvaluationError("error.refusal")]) as evaluate:
                saved, failures, stopped = core.process_pending(
                    core.default_config(), "key", path, threading.Event(), lambda text: None, seen.append)
            self.assertEqual((saved, len(failures), stopped), (1, 1, False))
            self.assertEqual(evaluate.call_count, 2)
            conn = core.open_database(path / "jobs.sqlite3")
            try:
                self.assertEqual(core.pending_count(conn), 1)
                self.assertTrue(conn.execute("SELECT error FROM pending_jobs WHERE status='pending'").fetchone()[0])
            finally:
                conn.close()
            with patch("modules.core.request_evaluation", return_value=result()) as evaluate:
                saved, failures, stopped = core.process_pending(
                    core.default_config(), "key", path, threading.Event(), lambda text: None, seen.append)
            self.assertEqual((saved, failures, stopped), (1, [], False))
            self.assertEqual(evaluate.call_count, 1)
            self.assertEqual(evaluate.call_args.args[0], "Job two")
            self.assertTrue((path / "csv" / "coincidence.csv").exists())

    def test_stop_processing_keeps_remaining_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            conn = core.open_database(path / "jobs.sqlite3")
            try:
                core.save_pending(conn, "one", "First")
                core.save_pending(conn, "two", "Second")
            finally:
                conn.close()
            stop = threading.Event()
            def finish(*args):
                stop.set()
                return result()
            with patch("modules.core.request_evaluation", side_effect=finish):
                saved, failures, stopped = core.process_pending(
                    core.default_config(), "key", path, stop, lambda text: None, lambda job: None)
            self.assertEqual((saved, failures, stopped), (1, [], True))
            conn = core.open_database(path / "jobs.sqlite3")
            try:
                self.assertEqual(core.pending_count(conn), 1)
                self.assertEqual(len(core.load_jobs(conn)), 1)
            finally:
                conn.close()
