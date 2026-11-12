from datetime import datetime
from pathlib import Path
import re
import sys
from typing import TextIO
from uuid import uuid4


LOG_NAME = re.compile(r"small-career-\d{8}-\d{6}-\d{6}-[0-9a-f]{32}\.log\Z")


class ActivityLog:
    def __init__(self, directory: Path, console: TextIO | None) -> None:
        log_directory = directory / "log"
        log_directory.mkdir(parents=True, exist_ok=True)
        name = f"small-career-{datetime.now():%Y%m%d-%H%M%S-%f}-{uuid4().hex}.log"
        self.path = log_directory / name
        self.stream = self.path.open("x", encoding="utf-8", buffering=1)
        self.console = console
        try:
            files = sorted(
                (path for path in log_directory.iterdir()
                 if path != self.path and path.is_file() and LOG_NAME.fullmatch(path.name)),
                key=lambda path: path.name, reverse=True,
            )
            for path in files[4:]:
                path.unlink()
        except OSError:
            self.stream.close()
            raise

    def write(self, kind: str, message: str) -> None:
        now = datetime.now()
        timestamp = f"{now:%H:%M:%S}:{now.microsecond // 10000:02d}"
        text = " ".join(message.split())
        line = f"[{timestamp} - {kind}] {text}\n"
        self.stream.write(line)
        self.stream.flush()
        if self.console is not None:
            try:
                self.console.write(line)
            except UnicodeEncodeError:
                encoding = self.console.encoding or "utf-8"
                self.console.write(line.encode(encoding, errors="backslashreplace").decode(encoding))
            self.console.flush()

    def close(self) -> None:
        self.stream.close()


def development_console() -> TextIO | None:
    return None if getattr(sys, "frozen", False) else sys.stdout
