from pathlib import Path
import shutil
import sqlite3

from .core import app_directory, atomic_write


def prepare_data_directory(base: Path | None = None) -> Path:
    base = app_directory() if base is None else base
    directory = base / "data"
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / ".legacy-imported"
    if marker.exists():
        return directory
    for name in ("config.json",):
        source, target = base / name, directory / name
        if source.is_file() and not target.exists():
            atomic_write(target, lambda temporary: shutil.copyfile(source, temporary))
    source, target = base / "jobs.sqlite3", directory / "jobs.sqlite3"
    if source.is_file() and not target.exists():
        def copy_database(temporary: Path) -> None:
            original = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
            backup = sqlite3.connect(temporary)
            try:
                original.backup(backup)
            finally:
                backup.close()
                original.close()
        atomic_write(target, copy_database)
    for name in ("csv", "log"):
        source = base / name
        if source.is_dir():
            for item in source.iterdir():
                target = directory / name / item.name
                if item.is_file() and not target.exists():
                    atomic_write(target, lambda temporary: shutil.copyfile(item, temporary))
    atomic_write(marker, lambda temporary: temporary.write_text("1\n", encoding="ascii"))
    return directory
