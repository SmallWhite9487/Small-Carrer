import gc
import io
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from modules.activity_log import ActivityLog
from modules.app import BatchDone, CareerApp, CrawlDone, ErrorEvent, ProgressEvent


class ActivityLogTests(unittest.TestCase):
    def test_format_console_and_rotation_preserve_unrelated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            output = io.StringIO()
            logs = []
            for number in range(6):
                log = ActivityLog(path, output)
                log.write("INFO", f"run {number}\ncontinued")
                logs.append(log.path)
                log.close()
                if number == 0:
                    (path / "log" / "notes.log").write_text("keep", encoding="utf-8")
            self.assertFalse(logs[0].exists())
            self.assertTrue(all(item.exists() for item in logs[1:]))
            self.assertTrue((path / "log" / "notes.log").exists())
            line = logs[-1].read_text(encoding="utf-8")
            self.assertRegex(line, r"^\[\d{2}:\d{2}:\d{2}:\d{2} - INFO\] run 5 continued\n$")
            self.assertTrue(output.getvalue().endswith(line))

    def test_desktop_events_are_logged_without_keys_urls_or_raw_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            output = io.StringIO()
            log = ActivityLog(path, output)
            root = tk.Tk()
            root.withdraw()
            try:
                app = CareerApp(root, path, log)
                app.settings_page.key_entry.insert(0, "private-key-example")
                app.settings_page.apply_requirements("private-requirements-example")
                app.save()
                app.settings_page.provider_box.current(1)
                app.settings_page.switch_provider(None)
                app.evaluation_page.filter.set("inconsistent")
                app.evaluation_page.apply_filter()
                app.events.put(ProgressEvent("Processing https://example.com/job?token=private-url-secret"))
                app.events.put(ErrorEvent("processing_failed", "private-error", "error.network"))
                with patch("modules.app.messagebox.showerror"):
                    app.poll()
                text = log.path.read_text(encoding="utf-8")
                for secret in ("private-key-example", "private-requirements-example",
                               "private-url-secret", "private-error", "example.com"):
                    self.assertNotIn(secret, text)
                self.assertIn("[URL]", text)
                self.assertIn("error.network", text)
                self.assertIn("gemini", text)
                self.assertIn("不適合", text)
                self.assertIn(" - ERROR]", text)
            finally:
                root.destroy()
            self.assertTrue(log.stream.closed)
            self.assertIn("程式已關閉", output.getvalue())
            del app, root
            gc.collect()

    def test_write_failure_is_visible_and_disables_logging(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            log = ActivityLog(path, io.StringIO())
            root = tk.Tk()
            root.withdraw()
            try:
                app = CareerApp(root, path, log)
                with patch.object(log, "write", side_effect=OSError("disk full")), \
                        patch("modules.app.messagebox.showerror") as error:
                    app.show_page("settings")
                error.assert_called_once()
                self.assertIn("disk full", error.call_args.args[1])
                self.assertIsNone(app.activity_log)
                self.assertTrue(log.stream.closed)
            finally:
                root.destroy()
            del app, root
            gc.collect()

    def test_partial_failures_include_reasons_without_urls_or_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            output = io.StringIO()
            log = ActivityLog(path, output)
            root = tk.Tk()
            root.withdraw()
            try:
                app = CareerApp(root, path, log)
                app.settings_page.key_entry.insert(0, "private-key-example")
                app.events.put(BatchDone(0, [
                    "https://example.com/job?token=private-url: ai_reason 超過60字",
                ]))
                app.events.put(CrawlDone(0, [
                    "https://example.com/job: private-key-example browser error",
                ], False, False))
                with patch("modules.app.messagebox.showerror"):
                    app.poll()
                text = log.path.read_text(encoding="utf-8")
                self.assertIn("ai_reason 超過60字", text)
                self.assertIn("browser error", text)
                self.assertNotIn("private-key-example", text)
                self.assertNotIn("private-url", text)
                self.assertNotIn("example.com", text)
                self.assertIn("[REDACTED]", text)
                self.assertIn(" - ERROR]", text)
                self.assertEqual(text, output.getvalue())
            finally:
                root.destroy()
            del app, root
            gc.collect()

    def test_worker_http_failure_logs_status_and_stage(self):
        from modules.core import EvaluationError

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            output = io.StringIO()
            log = ActivityLog(path, output)
            root = tk.Tk()
            root.withdraw()
            try:
                app = CareerApp(root, path, log)
                error = EvaluationError("error.website_forbidden", stage="robots.txt")
                app.events.put(app.worker_error("processing_failed", error))
                with patch("modules.app.messagebox.showerror") as dialog:
                    app.poll()
                self.assertIn("HTTP 403", output.getvalue())
                self.assertIn("robots.txt", output.getvalue())
                self.assertIn("HTTP 403", dialog.call_args.args[1])
                self.assertEqual(log.path.read_text(encoding="utf-8"), output.getvalue())
            finally:
                root.destroy()
            del app, root
            gc.collect()


if __name__ == "__main__":
    unittest.main()
