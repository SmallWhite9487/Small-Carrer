import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modules import core, sources


def listing(url: str, title: str = "Business Analyst", body: str = "Remote role") -> sources.JobListing:
    return sources.JobListing(url=url, title=title, company="Acme",
                              location="Remote", body=body)


class SourceSpecTests(unittest.TestCase):
    def test_accepts_supported_providers(self) -> None:
        for spec in ("greenhouse:stripe", "lever:netflix", "ashby:openai",
                     "workable:acme_1", "remotive:software-dev", "remotive:all"):
            with self.subTest(spec=spec):
                self.assertEqual(sources.parse_source(spec)[0], spec.split(":")[0])

    def test_rejects_unknown_or_malformed_specs(self) -> None:
        for spec in ("", "linkedin:jobs", "greenhouse", "greenhouse:", "greenhouse:a b",
                     "greenhouse:-x", "indeed:acme", "greenhouse:" + "a" * 80):
            with self.subTest(spec=spec), self.assertRaises(core.EvaluationError):
                sources.parse_source(spec)
        with self.assertRaises(core.EvaluationError):
            sources.parse_payload("indeed", "acme", {})

    def test_endpoints(self) -> None:
        self.assertEqual(
            sources.endpoint("greenhouse", "stripe"),
            "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true")
        self.assertEqual(sources.endpoint("lever", "netflix"),
                         "https://api.lever.co/v0/postings/netflix?mode=json")
        self.assertEqual(sources.endpoint("remotive", "all"),
                         "https://remotive.com/api/remote-jobs?limit=100")
        self.assertTrue(sources.endpoint("remotive", "software-dev").endswith(
            "&category=software-dev"))


class ParserTests(unittest.TestCase):
    def test_greenhouse(self) -> None:
        payload = {"jobs": [{
            "title": "Business Analyst", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
            "company_name": "Acme", "location": {"name": "Remote - US"},
            "content": "&lt;p&gt;Python &amp; SQL&lt;/p&gt;",
        }, {"title": "", "absolute_url": "https://boards.greenhouse.io/acme/jobs/2"}]}
        found = sources.parse_payload("greenhouse", "acme", payload)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].location, "Remote - US")
        self.assertIn("Python & SQL", found[0].body)
        self.assertIn("Company: Acme", found[0].markdown())

    def test_lever(self) -> None:
        payload = [{
            "text": "Data Analyst", "hostedUrl": "https://jobs.lever.co/acme/1",
            "categories": {"location": "Remote"},
            "descriptionPlain": "Own reporting dashboards",
            "lists": [{"text": "Requirements", "content": "<li>SQL</li><li>Excel</li>"}],
        }]
        found = sources.parse_payload("lever", "acme", payload)
        self.assertEqual(len(found), 1)
        self.assertIn("Own reporting", found[0].body)
        self.assertIn("SQL", found[0].body)
        self.assertEqual(found[0].company, "acme")

    def test_ashby_workable_remotive(self) -> None:
        ashby = {"jobs": [{"title": "Ops Analyst", "jobUrl": "https://jobs.ashbyhq.com/acme/1",
                           "location": "Remote", "descriptionHtml": "<p>Looker</p>",
                           "organizationName": "Acme"}]}
        workable = {"name": "Acme", "jobs": [{
            "title": "Analyst", "url": "https://apply.workable.com/acme/j/1/",
            "location": {"location_str": "Remote"}, "description": "<div>Tableau</div>"}]}
        remotive = {"jobs": [{"title": "Analyst", "url": "https://remotive.com/jobs/1",
                              "company_name": "Acme", "candidate_required_location": "Worldwide",
                              "description": "<p>Remote only</p>"}]}
        for provider, payload, token, marker in (
                ("ashby", ashby, "acme", "Looker"),
                ("workable", workable, "acme", "Tableau"),
                ("remotive", remotive, "all", "Remote only")):
            with self.subTest(provider=provider):
                found = sources.parse_payload(provider, token, payload)
                self.assertEqual(len(found), 1)
                self.assertIn(marker, found[0].body)
                self.assertEqual(found[0].location, found[0].location.strip())

    def test_bad_payloads_raise(self) -> None:
        for provider in sources.PROVIDERS:
            with self.subTest(provider=provider), self.assertRaises(core.EvaluationError):
                sources.parse_payload(provider, "acme", {"unexpected": []})
        self.assertEqual(sources.parse_payload("greenhouse", "acme", {"jobs": []}), [])

    def test_entries_without_body_or_url_are_skipped(self) -> None:
        payload = {"jobs": [
            {"title": "No body", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
             "content": ""},
            {"title": "No url", "content": "<p>Body</p>"},
            {"title": "Relative", "absolute_url": "/jobs/3", "content": "<p>Body</p>"},
        ]}
        self.assertEqual(sources.parse_payload("greenhouse", "acme", payload), [])


class CollectTests(unittest.TestCase):
    def test_collect_queues_jobs_and_skips_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            batch = [listing("https://boards.greenhouse.io/acme/jobs/1"),
                     listing("https://boards.greenhouse.io/acme/jobs/2")]
            with patch("modules.sources.fetch_listings", return_value=batch) as fetch:
                saved, failures = sources.collect(["greenhouse:acme"], path, "en")
            self.assertEqual((saved, failures), (2, []))
            fetch.assert_called_once_with("greenhouse:acme")
            connection = core.open_database(path / "jobs.sqlite3")
            try:
                self.assertEqual(core.pending_count(connection), 2)
            finally:
                connection.close()
            with patch("modules.sources.fetch_listings", return_value=batch):
                saved, failures = sources.collect(["greenhouse:acme"], path, "en")
            self.assertEqual((saved, failures), (0, []))

    def test_one_broken_source_does_not_stop_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)

            def fetch(spec):
                if spec == "lever:gone":
                    raise core.EvaluationError("error.source_http", code=404)
                if spec == "bad-spec":
                    raise core.EvaluationError("error.sources")
                return [listing("https://jobs.lever.co/acme/1")]

            with patch("modules.sources.fetch_listings", side_effect=fetch):
                saved, failures = sources.collect(
                    ["lever:gone", "lever:acme", "bad-spec"], path, "en")
            self.assertEqual(saved, 1)
            self.assertEqual(len(failures), 2)
            self.assertIn("lever:gone", failures[0])
            self.assertIn("404", failures[0])

    def test_stop_event_halts_collection(self) -> None:
        import threading
        with tempfile.TemporaryDirectory() as directory:
            stop = threading.Event()
            stop.set()
            with patch("modules.sources.fetch_listings") as fetch:
                saved, failures = sources.collect(["lever:acme"], Path(directory),
                                                  "en", stop)
            self.assertEqual((saved, failures), (0, []))
            fetch.assert_not_called()


class ConfigTests(unittest.TestCase):
    def test_job_source_settings_round_trip(self) -> None:
        config = core.default_config()
        self.assertEqual(config["job_sources"], [])
        self.assertEqual(config["auto_collect_hours"], 0)
        config["job_sources"] = ["greenhouse:stripe", "greenhouse:stripe", "lever:netflix"]
        config["auto_collect_hours"] = 12
        config["auto_process"] = False
        checked = core.validate_config(config)
        self.assertEqual(checked["job_sources"], ["greenhouse:stripe", "lever:netflix"])
        self.assertEqual(checked["auto_collect_hours"], 12)
        self.assertFalse(checked["auto_process"])

    def test_invalid_job_source_settings(self) -> None:
        config = core.default_config()
        for value in ({"job_sources": ["linkedin:jobs"]},
                      {"job_sources": "greenhouse:stripe"},
                      {"job_sources": [1]},
                      {"auto_collect_hours": -1},
                      {"auto_collect_hours": 169},
                      {"auto_collect_hours": "12"},
                      {"auto_process": "yes"}):
            with self.subTest(value=value), self.assertRaises(core.EvaluationError):
                core.validate_config({**config, **value})

    def test_config_file_without_new_fields_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            legacy = dict(core.default_config())
            for key in ("job_sources", "auto_collect_hours", "auto_process"):
                legacy.pop(key)
            path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
            loaded = core.load_config(path)
            self.assertEqual(loaded["job_sources"], [])
            self.assertEqual(loaded["auto_collect_hours"], 0)
            self.assertTrue(loaded["auto_process"])


if __name__ == "__main__":
    unittest.main()
