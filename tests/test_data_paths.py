from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from modules import core
from modules.data_paths import prepare_data_directory


class DataPathTests(unittest.TestCase):
    def test_new_and_frozen_install_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            with patch("modules.data_paths.app_directory", return_value=base):
                self.assertEqual(prepare_data_directory().resolve(), (base / "data").resolve())
            self.assertTrue((base / "data" / ".legacy-imported").is_file())
            with patch.object(core.sys, "frozen", True, create=True), \
                    patch.object(core.sys, "executable", str(base / "SmallCareer.exe")):
                self.assertEqual(prepare_data_directory().resolve(), (base / "data").resolve())

    def test_migration_preserves_existing_data_and_imports_only_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "config.json").write_text('{"legacy":true}', encoding="utf-8")
            (base / "csv").mkdir()
            (base / "csv" / "coincidence.csv").write_text("legacy csv", encoding="utf-8")
            (base / "log").mkdir()
            (base / "log" / "old.log").write_text("legacy log", encoding="utf-8")
            database = sqlite3.connect(base / "jobs.sqlite3")
            try:
                database.execute("PRAGMA journal_mode=WAL")
                database.execute("CREATE TABLE example (value TEXT)")
                database.execute("INSERT INTO example VALUES ('preserved')")
                database.commit()
                directory = base / "data"
                directory.mkdir()
                (directory / "config.json").write_text('{"new":true}', encoding="utf-8")
                self.assertEqual(prepare_data_directory(base), directory)
                self.assertEqual((directory / "config.json").read_text(), '{"new":true}')
                imported = sqlite3.connect(directory / "jobs.sqlite3")
                try:
                    self.assertEqual(imported.execute("SELECT value FROM example").fetchone()[0], "preserved")
                finally:
                    imported.close()
                self.assertEqual((directory / "csv" / "coincidence.csv").read_text(), "legacy csv")
                self.assertTrue((base / "config.json").exists())
                (directory / "config.json").unlink()
                prepare_data_directory(base)
                self.assertFalse((directory / "config.json").exists())
            finally:
                database.close()

    def test_failed_migration_can_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "config.json").write_text("legacy", encoding="utf-8")
            with patch("modules.data_paths.shutil.copyfile", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    prepare_data_directory(base)
            self.assertFalse((base / "data" / ".legacy-imported").exists())
            self.assertFalse((base / "data" / "config.json").exists())
            prepare_data_directory(base)
            self.assertEqual((base / "data" / "config.json").read_text(), "legacy")
