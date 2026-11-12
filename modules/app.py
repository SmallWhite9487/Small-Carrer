import os
from dataclasses import dataclass
from pathlib import Path
import queue
import re
import sqlite3
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .activity_log import ActivityLog, development_console
from .core import (
    AppConfig, EvaluationError, load_config,
    JobRecord, load_jobs, open_database, pending_count, polish_requirements,
    process_pending, save_config, validate_config,
)
from .crawler import crawl_to_queue, normalize_url
from .data_paths import prepare_data_directory
from .evaluation_page import EvaluationPage
from .home_page import HomePage
from .i18n import Language, translate
from .settings_page import RequirementsPreview, SettingsPage
from .ui import configure_style


@dataclass(frozen=True)
class ProgressEvent:
    text: str


@dataclass(frozen=True)
class JobEvent:
    job: JobRecord


@dataclass(frozen=True)
class BatchDone:
    saved: int
    failures: list[str]
    stopped: bool = False


@dataclass(frozen=True)
class PolishDone:
    text: str


@dataclass(frozen=True)
class CrawlDone:
    saved: int
    failures: list[str]
    stopped: bool
    limited: bool


@dataclass(frozen=True)
class ErrorEvent:
    title: str
    detail: str
    code: str = "worker"
    log_detail: str = ""


AppEvent = ProgressEvent | JobEvent | BatchDone | CrawlDone | PolishDone | ErrorEvent


class CareerApp:
    def __init__(self, root: tk.Tk, directory: Path, activity_log: ActivityLog | None = None) -> None:
        self.root = root
        self.directory = directory
        self.activity_log = activity_log
        self.config = load_config(directory / "config.json")
        self.language = self.config["language"]
        self.running = False
        self.stop_event = threading.Event()
        self.activity = ""
        self.events: queue.Queue[AppEvent] = queue.Queue()
        self.preview: RequirementsPreview | None = None
        root.geometry("1180x820")
        root.minsize(980, 650)
        configure_style(root)
        root.protocol("WM_DELETE_WINDOW", self.close)
        sidebar = ttk.Frame(root, style="Sidebar.TFrame", width=210, padding=(16, 24))
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        ttk.Label(sidebar, text="Small Career", style="Brand.TLabel").pack(anchor="w", pady=(0, 32))
        self.nav_buttons: dict[str, ttk.Button] = {}
        for key in ("home", "settings", "evaluation"):
            button = ttk.Button(sidebar, style="Nav.TButton",
                                command=lambda page=key: self.show_page(page))
            button.pack(fill="x", pady=4)
            self.nav_buttons[key] = button
        sidebar_footer = ttk.Frame(sidebar, style="Sidebar.TFrame")
        sidebar_footer.pack(side="bottom", fill="x")
        self.language_button = ttk.Button(sidebar_footer, text="A/文", width=5,
                                         style="Language.TButton", command=self.toggle_language)
        self.language_button.pack(anchor="w", pady=(0, 12))
        self.signature = ttk.Label(sidebar_footer,
                                   text="Small Carrer v1.0\nBy SmallWhite Studio",
                                   style="SidebarFooter.TLabel", justify="left")
        self.signature.pack(anchor="w")
        right = ttk.Frame(root)
        right.pack(side="left", fill="both", expand=True)
        footer = ttk.Frame(right, padding=(12, 8))
        footer.pack(side="bottom", fill="x")
        self.page_host = ttk.Frame(right)
        self.page_host.pack(fill="both", expand=True)
        self.page_host.columnconfigure(0, weight=1)
        self.page_host.rowconfigure(0, weight=1)
        self.settings_page = SettingsPage(
            self.page_host, self.config, self.save, self.polish,
            lambda provider: self.log("INFO", "log_provider", provider=provider))
        self.evaluation_page = EvaluationPage(
            self.page_host, self.language, directory, self.start, self.stop_crawl,
            self.process, self.save_site, self.remove_site,
            lambda category: self.log("INFO", "log_filter", category=self.text(
                "filter_all" if category == "all" else category)),
        )
        self.evaluation_page.website_entry.configure(values=self.config["websites"])
        if self.config["websites"]:
            self.evaluation_page.website_entry.set(self.config["websites"][0])
        self.evaluation_page.page_limit.delete(0, "end")
        self.evaluation_page.page_limit.insert(0, str(self.config["max_pages"]))
        self.evaluation_page.set_busy(False)
        ttk.Label(footer, textvariable=self.evaluation_page.status, style="Subtitle.TLabel",
                  wraplength=810, padding=12).pack(side="left", fill="x", expand=True)
        self.home_page = HomePage(self.page_host, self.language,
                                  lambda: self.show_page("settings"),
                                  lambda: self.show_page("evaluation"),
                                  lambda category: self.log("INFO", "log_filter", category=self.text(
                                      "filter_all" if category == "all" else category)))
        self.pages = {"home": self.home_page, "settings": self.settings_page,
                      "evaluation": self.evaluation_page}
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")
        self.log("INFO", "log_started")
        self.refresh_language()
        self.show_page("home")
        self.reload_jobs()
        self.refresh_pending()
        self.poll_id = root.after(100, self.poll)
        root.bind("<Destroy>", self.on_destroy, add="+")

    def on_destroy(self, event: tk.Event) -> None:
        if event.widget == self.root:
            self.root.after_cancel(self.poll_id)
            self.log("INFO", "log_closed")
            if self.activity_log is not None:
                self.activity_log.close()

    def log(self, kind: str, key: str, **values: object) -> None:
        self.write_log(kind, self.text(key, **values))

    def write_log(self, kind: str, text: str) -> None:
        if self.activity_log is None:
            return
        try:
            self.activity_log.write(kind, text)
        except (OSError, UnicodeError) as exc:
            logger = self.activity_log
            self.activity_log = None
            try:
                logger.close()
            except OSError as close_error:
                detail = f"{exc}\n{close_error}"
            else:
                detail = str(exc)
            messagebox.showerror(self.text("log_failed"), self.text("log_failed_hint") + "\n" + detail,
                                 parent=self.root)

    def log_progress(self, text: str) -> None:
        safe_text = re.sub(r"https?://\S+", "[URL]", text, flags=re.IGNORECASE)
        self.write_log("INFO", safe_text)

    def log_failures(self, failures: list[str]) -> None:
        settings = self.settings_page.read_settings()
        secrets = {
            self.config["api_key"], settings["api_key"],
            *(profile["api_key"] for profile in self.config["profiles"].values()),
            *(profile["api_key"] for profile in settings["profiles"].values()),
            os.environ.get(settings["api_key_env"], ""),
        }
        for failure in failures:
            text = failure
            for secret in sorted(secrets - {""}, key=len, reverse=True):
                text = text.replace(secret, "[REDACTED]")
            text = re.sub(r"https?://\S+", "[URL]", text, flags=re.IGNORECASE)
            self.write_log("ERROR", text)

    def show_page(self, key: str) -> None:
        self.current_page = key
        for name, page in self.pages.items():
            if name == key:
                page.grid()
            else:
                page.grid_remove()
        self.pages[key].tkraise()
        for name, button in self.nav_buttons.items():
            button.configure(style="Active.Nav.TButton" if name == key else "Nav.TButton")
        self.log("INFO", "log_page", page=self.text(f"{key}_tab"))

    def toggle_language(self) -> None:
        self.change_language("en" if self.language == "zh-TW" else "zh-TW")

    def text(self, key: str, **values: object) -> str:
        return translate(self.language, key, **values)

    def error_detail(self, error: Exception) -> str:
        if isinstance(error, EvaluationError):
            return error.localized(self.language)
        return str(error)

    def show_error(self, title: str, error: Exception) -> None:
        self.log("ERROR", "log_error", action=self.text(title),
                 error=error.key if isinstance(error, EvaluationError) else type(error).__name__)
        if isinstance(error, EvaluationError):
            self.log_failures([error.localized(self.language)])
        messagebox.showerror(self.text(title), self.error_detail(error), parent=self.root)

    def worker_error(self, title: str, error: Exception) -> ErrorEvent:
        code = error.key if isinstance(error, EvaluationError) else type(error).__name__
        detail = self.error_detail(error)
        return ErrorEvent(title, detail, code, detail if isinstance(error, EvaluationError) else "")

    def refresh_language(self) -> None:
        self.root.title(self.text("app_title"))
        for key, button in self.nav_buttons.items():
            button.configure(text=self.text(f"{key}_tab"))
        for page in self.pages.values():
            page.refresh_language(self.language)

    def change_language(self, language: Language) -> None:
        if self.running:
            self.settings_page.refresh_language(self.language)
            return
        # Persist only the language; keep unsaved edits and the session key intact.
        config = self.config.copy()
        config["language"] = language
        try:
            save_config(self.directory / "config.json", config)
        except (EvaluationError, OSError) as exc:
            self.settings_page.refresh_language(self.language)
            self.show_error("language_failed", exc)
            return
        self.config = config
        self.language = language
        self.refresh_language()
        self.log("INFO", "log_language")

    def save(self) -> None:
        try:
            config = self.read_config()
            save_config(self.directory / "config.json", config)
        except (EvaluationError, OSError) as exc:
            self.show_error("save_failed", exc)
            return
        self.config = config
        self.evaluation_page.set_status("saved")
        self.log("INFO", "saved")

    def read_config(self) -> AppConfig:
        settings = self.settings_page.read_settings()
        settings["websites"] = self.config["websites"].copy()
        try:
            settings["max_pages"] = int(self.evaluation_page.page_limit.get())
        except ValueError as exc:
            raise EvaluationError("error.config_extras") from exc
        return validate_config(settings)

    def set_busy(self, busy: bool, activity: str = "") -> None:
        self.running = busy
        self.activity = activity if busy else ""
        self.settings_page.set_busy(busy)
        self.evaluation_page.set_busy(busy, activity == "crawl")
        self.language_button.state(["disabled"] if busy else ["!disabled"])

    def refresh_pending(self) -> None:
        path = self.directory / "jobs.sqlite3"
        if not path.exists():
            self.evaluation_page.update_pending(0)
            return
        try:
            connection = open_database(path)
            try:
                count = pending_count(connection)
            finally:
                connection.close()
        except (OSError, sqlite3.Error) as exc:
            self.show_error("load_failed", exc)
            return
        self.evaluation_page.update_pending(count)

    def save_site(self) -> None:
        try:
            url = normalize_url(self.evaluation_page.website_entry.get())
            config = self.config.copy()
            config["websites"] = list(dict.fromkeys([*self.config["websites"], url]))
            save_config(self.directory / "config.json", config)
        except (EvaluationError, OSError) as exc:
            self.show_error("save_failed", exc)
            return
        self.config = config
        self.evaluation_page.website_entry.configure(values=config["websites"])
        self.evaluation_page.website_entry.set(url)
        self.evaluation_page.set_status("site_saved")
        self.log("INFO", "site_saved")

    def remove_site(self) -> None:
        url = self.evaluation_page.website_entry.get().strip()
        if url not in self.config["websites"]:
            self.show_error("save_failed", EvaluationError("error.site_not_saved"))
            return
        config = self.config.copy()
        config["websites"] = [site for site in config["websites"] if site != url]
        try:
            save_config(self.directory / "config.json", config)
        except (EvaluationError, OSError) as exc:
            self.show_error("save_failed", exc)
            return
        self.config = config
        self.evaluation_page.website_entry.configure(values=config["websites"])
        self.evaluation_page.website_entry.set(config["websites"][0] if config["websites"] else "")
        self.evaluation_page.set_status("site_removed")
        self.log("INFO", "site_removed")

    def reload_jobs(self) -> None:
        path = self.directory / "jobs.sqlite3"
        if not path.exists():
            return
        try:
            connection = open_database(path)
            try:
                jobs = load_jobs(connection)
            finally:
                connection.close()
        except (EvaluationError, OSError, sqlite3.Error) as exc:
            self.show_error("load_failed", exc)
            return
        self.evaluation_page.set_jobs(jobs)
        self.home_page.update_jobs(jobs)

    def polish(self) -> None:
        if self.running:
            return
        settings = self.settings_page.read_settings()
        if not settings["user_requirements"]:
            self.show_error("polish_failed", EvaluationError("error.empty_requirements"))
            return
        try:
            config = self.read_config()
            key = config["api_key"]
            if not key and config["provider"] == "openai":
                key = os.environ.get(config["api_key_env"], "").strip()
            if not key and config["provider"] != "custom":
                raise EvaluationError("error.api_key")
        except EvaluationError as exc:
            self.show_error("polish_failed", exc)
            return
        if not messagebox.askyesno(self.text("polish"), self.text("polish_confirm"), parent=self.root):
            self.log("INFO", "log_polish_declined")
            return
        self.set_busy(True)
        self.evaluation_page.set_status("polishing")
        self.log("INFO", "polishing")

        def worker() -> None:
            try:
                text = polish_requirements(config["user_requirements"], config, key)
                self.events.put(PolishDone(text))
            except (EvaluationError, OSError, UnicodeError) as exc:
                self.events.put(self.worker_error("polish_failed", exc))

        threading.Thread(target=worker, daemon=True).start()

    def apply_polish(self, text: str) -> None:
        self.set_busy(False)
        self.settings_page.apply_requirements(text)
        self.evaluation_page.set_status("polish_applied")
        self.log("INFO", "polish_applied")
        self.preview = None

    def cancel_polish(self) -> None:
        self.set_busy(False)
        self.evaluation_page.set_status("polish_cancelled")
        self.log("INFO", "polish_cancelled")
        self.preview = None

    def start(self) -> None:
        if self.running:
            return
        website = self.evaluation_page.website_entry.get().strip()
        if not website:
            self.log("ERROR", "log_error", action=self.text("cannot_start"), error="error.website_url")
            messagebox.showerror(self.text("cannot_start"), self.text("select_first"), parent=self.root)
            return
        try:
            website = normalize_url(website)
            max_pages = int(self.evaluation_page.page_limit.get())
            if not 1 <= max_pages <= 100:
                raise ValueError
        except (EvaluationError, OSError) as exc:
            self.show_error("cannot_start", exc)
            return
        except ValueError:
            self.show_error("cannot_start", EvaluationError("error.config_extras"))
            return
        ai_config: AppConfig | None = None
        ai_key = ""
        if self.evaluation_page.ai_assist.get():
            answer = messagebox.askyesnocancel(
                self.text("ai_assist"), self.text("ai_crawl_confirm"), parent=self.root)
            if answer is None:
                self.log("INFO", "ai_crawl_cancelled")
                return
            if answer:
                try:
                    ai_config = self.read_config()
                    ai_key = ai_config["api_key"]
                    if not ai_key and ai_config["provider"] == "openai":
                        ai_key = os.environ.get(ai_config["api_key_env"], "").strip()
                    if not ai_key and ai_config["provider"] != "custom":
                        raise EvaluationError("error.api_key")
                except EvaluationError as exc:
                    self.show_error("cannot_start", exc)
                    return
                self.log("INFO", "ai_crawl_enabled")
            else:
                self.log("INFO", "ai_crawl_rules_only")
        self.stop_event.clear()
        self.set_busy(True, "crawl")
        self.evaluation_page.set_status("finding_jobs")
        self.log("INFO", "finding_jobs")
        self.show_page("evaluation")
        use_browser = self.evaluation_page.use_browser.get()
        if use_browser:
            self.log("INFO", "use_browser")

        def worker() -> None:
            try:
                args = (website, self.directory, self.language, max_pages,
                        self.stop_event, lambda text: self.events.put(ProgressEvent(text)))
                if use_browser:
                    result = crawl_to_queue(*args, ai_config=ai_config, ai_key=ai_key, browser=True)
                elif ai_config is None:
                    result = crawl_to_queue(*args)
                else:
                    result = crawl_to_queue(*args, ai_config=ai_config, ai_key=ai_key)
                self.events.put(CrawlDone(*result))
            except (EvaluationError, OSError, UnicodeError, sqlite3.Error) as exc:
                self.events.put(self.worker_error("processing_failed", exc))

        threading.Thread(target=worker, daemon=True).start()

    def stop_crawl(self) -> None:
        if self.running and self.activity == "crawl":
            self.stop_event.set()
            self.log("INFO", "log_stop_requested")
            self.evaluation_page.buttons["stop_crawl"].state(["disabled"])

    def process(self) -> None:
        if self.running:
            return
        try:
            config = self.read_config()
            key = config["api_key"]
            if not key and config["provider"] == "openai":
                key = os.environ.get(config["api_key_env"], "").strip()
            if not key and config["provider"] != "custom":
                raise EvaluationError("error.api_key")
            connection = open_database(self.directory / "jobs.sqlite3")
            try:
                if not pending_count(connection):
                    raise EvaluationError("error.no_pending")
            finally:
                connection.close()
        except (EvaluationError, OSError, sqlite3.Error) as exc:
            self.show_error("cannot_start", exc)
            return
        if not messagebox.askyesno(self.text("process_jobs"), self.text("processing_confirm"), parent=self.root):
            self.log("INFO", "log_process_declined")
            return
        try:
            save_config(self.directory / "config.json", config)
        except (EvaluationError, OSError) as exc:
            self.show_error("save_failed", exc)
            return
        self.config = config
        self.stop_event.clear()
        self.set_busy(True, "process")
        self.evaluation_page.set_status("connecting")
        self.log("INFO", "connecting")

        def worker() -> None:
            try:
                saved, failures, stopped = process_pending(
                    config, key, self.directory, self.stop_event,
                    lambda text: self.events.put(ProgressEvent(text)),
                    lambda job: self.events.put(JobEvent(job)))
                self.events.put(BatchDone(saved, failures, stopped))
            except (EvaluationError, OSError, UnicodeError, sqlite3.Error) as exc:
                self.events.put(self.worker_error("processing_failed", exc))

        threading.Thread(target=worker, daemon=True).start()

    def poll(self) -> None:
        self.root.after_cancel(self.poll_id)
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if isinstance(event, ProgressEvent):
                self.evaluation_page.set_progress(event.text)
                self.log_progress(event.text)
                continue
            if isinstance(event, JobEvent):
                self.evaluation_page.upsert_job(event.job)
                self.home_page.update_jobs(self.evaluation_page.jobs)
                self.log("INFO", "log_job_processed")
                continue
            if isinstance(event, PolishDone):
                self.log("INFO", "log_polish_ready")
                self.preview = RequirementsPreview(
                    self.root, event.text, self.language, self.apply_polish, self.cancel_polish)
                continue
            self.set_busy(False)
            self.refresh_pending()
            if isinstance(event, ErrorEvent):
                self.log("ERROR", "log_error", action=self.text(event.title), error=event.code)
                if event.log_detail:
                    self.log_failures([event.log_detail])
                if event.title == "processing_failed":
                    self.reload_jobs()
                self.evaluation_page.set_status(
                    "batch_failed" if event.title == "processing_failed" else "polish_cancelled")
                messagebox.showerror(self.text(event.title), event.detail, parent=self.root)
            elif isinstance(event, BatchDone):
                saved, failures = event.saved, event.failures
                self.log("ERROR" if failures else "INFO", "summary", saved=saved, failed=len(failures))
                self.evaluation_page.set_status("summary", saved=saved, failed=len(failures))
                notice = "\n\n" + self.text("processing_stopped") if event.stopped else ""
                if failures:
                    self.log_failures(failures)
                    messagebox.showerror(self.text("partial_failure"), "\n".join(failures) + notice,
                                         parent=self.root)
                else:
                    messagebox.showinfo(self.text("complete"), self.text("complete_message", saved=saved) + notice,
                                        parent=self.root)
            elif isinstance(event, CrawlDone):
                key = "crawl_stopped" if event.stopped else "crawl_complete"
                text = self.text(key, saved=event.saved, pending=self.evaluation_page.pending)
                if event.limited:
                    text += "\n" + self.text("page_limit_reached")
                if event.failures:
                    text += "\n\n" + "\n".join(event.failures)
                    self.log("ERROR", "log_crawl_failures", count=len(event.failures))
                    self.log_failures(event.failures)
                    messagebox.showerror(self.text("partial_failure"), text, parent=self.root)
                else:
                    messagebox.showinfo(self.text("complete"), text, parent=self.root)
                self.evaluation_page.status.set(text)
                self.log("INFO", key, saved=event.saved, pending=self.evaluation_page.pending)
                if event.limited:
                    self.log("INFO", "page_limit_reached")
        self.poll_id = self.root.after(100, self.poll)

    def close(self) -> None:
        if self.running:
            messagebox.showwarning(self.text("busy"), self.text("wait_close"), parent=self.root)
        else:
            self.root.destroy()


def run() -> None:
    if os.name == "nt":
        import ctypes

        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "SmallWhiteStudio.SmallCareer")
        if result != 0:
            raise OSError(f"Unable to set application identity: {result}")
    root = tk.Tk()
    activity_log = None
    try:
        directory = prepare_data_directory()
        activity_log = ActivityLog(directory, development_console())
        CareerApp(root, directory, activity_log)
    except (EvaluationError, OSError, UnicodeError, sqlite3.Error) as exc:
        if activity_log is not None:
            activity_log.close()
        detail = exc.localized("zh-TW") if isinstance(exc, EvaluationError) else str(exc)
        messagebox.showerror(translate("zh-TW", "startup_failed"), detail, parent=root)
        root.destroy()
        raise SystemExit(1) from exc
    root.mainloop()
