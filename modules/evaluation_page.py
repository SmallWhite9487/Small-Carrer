from pathlib import Path
import tkinter as tk
from tkinter import ttk
from typing import Callable
from urllib.parse import urlsplit
import webbrowser

from .core import JobRecord
from .i18n import Language, translate
from .job_list import CARD_GAP, CARD_HEIGHT, CARD_WIDTH, JobListPage
from .ui import configure_window_icon


def abbreviated(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


class JobCard(ttk.Frame):
    def __init__(self, parent: ttk.Frame, job: JobRecord, language: Language) -> None:
        super().__init__(parent, style="Card.TFrame", width=CARD_WIDTH, height=CARD_HEIGHT, padding=16)
        self.pack_propagate(False)
        self.grid_propagate(False)
        self.job = job
        self.language = language
        self.details_button = ttk.Button(self, command=self.show_details)
        self.details_button.pack(side="bottom", anchor="w")
        self.badge = ttk.Label(self, padding=(8, 4))
        self.badge.pack(anchor="w", pady=(0, 8))
        self.title_label = ttk.Label(self, text=abbreviated(job.result["title"], 36),
                                     style="CardTitle.TLabel", wraplength=CARD_WIDTH - 32)
        self.title_label.pack(anchor="w")
        self.pay = ttk.Label(self, text=abbreviated(job.result["unit_price"], 32),
                             style="CardHeading.TLabel", wraplength=CARD_WIDTH - 32)
        self.pay.pack(anchor="w", pady=(8, 2))
        self.arrangement = ttk.Label(self, text=abbreviated(
            f'{job.result["remote_type"]} · {job.result["location"]}', 32),
            style="CardMuted.TLabel", wraplength=CARD_WIDTH - 32)
        self.arrangement.pack(anchor="w")
        self.skills = ttk.Label(self, text=abbreviated(job.result["tech_stack"], 36),
                                style="CardMuted.TLabel", wraplength=CARD_WIDTH - 32)
        self.skills.pack(anchor="w", pady=(6, 0))
        self.reason = ttk.Label(self, text=abbreviated(job.result["ai_reason"], 42),
                                style="Card.TLabel", wraplength=CARD_WIDTH - 32)
        self.reason.pack(anchor="w", pady=(10, 0))
        self.refresh_language(language)

    def refresh_language(self, language: Language) -> None:
        self.language = language
        category = self.job.result["category"]
        colors = {"coincidence": ("#E1F5EB", "#24774C"),
                  "propinquity": ("#FFF1D6", "#94621A"),
                  "inconsistent": ("#FCE7E9", "#AE3D4C")}
        background, foreground = colors[category]
        self.badge.configure(text=translate(language, category), background=background, foreground=foreground)
        self.details_button.configure(text=translate(language, "view_details"))
        self.pay.configure(text=abbreviated(
            f'{translate(language, "card_salary")}：{self.job.result["unit_price"]}', 32))
        self.skills.configure(text=abbreviated(
            f'{translate(language, "card_skills")}：{self.job.result["tech_stack"]}', 36))
        self.reason.configure(text=abbreviated(
            f'{translate(language, "card_reason")}：{self.job.result["ai_reason"]}', 42))

    def show_details(self) -> None:
        window = tk.Toplevel(self.winfo_toplevel())
        configure_window_icon(window)
        window.title(translate(self.language, "job_details"))
        window.geometry("720x640")
        panel = ttk.Frame(window, padding=20)
        panel.pack(fill="both", expand=True)
        fields = (
            ("card_salary", self.job.result["unit_price"]),
            ("card_remote", self.job.result["remote_type"]),
            ("card_location", self.job.result["location"]),
            ("card_skills", self.job.result["tech_stack"]),
            ("card_reason", self.job.result["ai_reason"]),
            ("card_source", self.job.source),
        )
        ttk.Label(panel, text=self.job.result["title"], style="Title.TLabel",
                  wraplength=650).pack(anchor="w")
        editor_frame = ttk.Frame(panel)
        editor_frame.pack(fill="both", expand=True, pady=14)
        text = tk.Text(editor_frame, wrap="word", relief="flat", padx=12, pady=12)
        scrollbar = ttk.Scrollbar(editor_frame, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        text.tag_configure("heading", font=("Microsoft JhengHei UI", 12, "bold"),
                           spacing1=12, spacing3=6)
        text.tag_configure("body", spacing3=8)
        for key, value in fields:
            text.insert("end", translate(self.language, key) + "\n", "heading")
            text.insert("end", value + "\n\n", "body")
        text.configure(state="disabled")
        if urlsplit(self.job.source).scheme in ("http", "https"):
            ttk.Button(panel, text=translate(self.language, "open_listing"),
                       command=lambda: webbrowser.open(self.job.source)).pack(anchor="w")


class EvaluationPage(JobListPage):
    def __init__(
        self, parent: ttk.Frame, language: Language, directory: Path,
        on_start: Callable[[], None], on_stop: Callable[[], None],
        on_process: Callable[[], None], on_save_site: Callable[[], None],
        on_remove_site: Callable[[], None], on_filter: Callable[[str], None],
    ) -> None:
        super().__init__(parent, padding=28)
        self.language = language
        self.status_key = "output_directory"
        self.status_values: dict[str, object] = {"directory": directory}
        self.status = tk.StringVar()
        self.title_label = ttk.Label(self, style="Title.TLabel")
        self.title_label.pack(anchor="w")
        self.intro = ttk.Label(self, style="Subtitle.TLabel", wraplength=850)
        self.intro.pack(anchor="w", pady=(6, 12))
        self.website_label = ttk.Label(self)
        self.website_label.pack(anchor="w")
        search = ttk.Frame(self)
        search.pack(fill="x", pady=(5, 0))
        self.website_entry = ttk.Combobox(search)
        self.website_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.buttons = {"start": ttk.Button(search, style="Accent.TButton", command=on_start)}
        self.buttons["start"].pack(side="right")
        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(8, 0))
        for key, command in (("save_site", on_save_site), ("remove_site", on_remove_site),
                             ("stop_crawl", on_stop), ("process_jobs", on_process)):
            self.buttons[key] = ttk.Button(controls, command=command,
                                           style="Accent.TButton" if key == "process_jobs" else "TButton")
            self.buttons[key].pack(side="left", padx=(0, 6))
        self.page_limit_label = ttk.Label(controls)
        self.page_limit_label.pack(side="left", padx=(10, 4))
        self.page_limit = ttk.Spinbox(controls, from_=1, to=100, width=4)
        self.page_limit.insert(0, "10")
        self.page_limit.pack(side="left")
        self.pending_label = ttk.Label(self, style="Subtitle.TLabel")
        self.pending_label.pack(anchor="w", pady=(6, 0))
        self.pending = 0
        self.ai_assist = tk.BooleanVar(value=True)
        self.ai_assist_button = ttk.Checkbutton(self, variable=self.ai_assist)
        self.ai_assist_button.pack(anchor="w", pady=(4, 0))
        self.use_browser = tk.BooleanVar(value=True)
        self.browser_button = ttk.Checkbutton(self, variable=self.use_browser)
        self.browser_button.pack(anchor="w", pady=(4, 0))
        self.website_hint = ttk.Label(self, style="Subtitle.TLabel", wraplength=850)
        self.website_hint.pack(anchor="w", pady=(6, 12))
        self.initialize_job_list(language, on_filter)
        self.privacy_label = ttk.Label(self, style="Subtitle.TLabel", wraplength=850)
        self.privacy_label.pack(anchor="w", pady=(10, 0))
        self.refresh_language(language)

    def set_status(self, key: str, **values: object) -> None:
        self.status_key, self.status_values = key, values
        self.status.set(translate(self.language, key, **values))

    def set_progress(self, text: str) -> None:
        self.status.set(text)

    def refresh_language(self, language: Language) -> None:
        self.language = language
        self.title_label.configure(text=translate(language, "evaluation_tab"))
        self.intro.configure(text=translate(language, "evaluation_intro"))
        self.website_label.configure(text=translate(language, "website_label"))
        self.website_hint.configure(text=translate(language, "website_hint"))
        for key, button in self.buttons.items():
            button.configure(text=translate(language, key))
        self.page_limit_label.configure(text=translate(language, "page_limit"))
        self.ai_assist_button.configure(text=translate(language, "ai_assist"))
        self.browser_button.configure(text=translate(language, "use_browser"))
        self.update_pending(self.pending)
        self.refresh_job_language(language)
        self.privacy_label.configure(text=translate(language, "privacy_note"))
        self.status.set(translate(language, self.status_key, **self.status_values))

    def update_pending(self, count: int) -> None:
        self.pending = count
        self.pending_label.configure(text=translate(self.language, "pending_count", count=count))

    def set_busy(self, busy: bool, crawling: bool = False) -> None:
        self.website_entry.configure(state="disabled" if busy else "normal")
        self.page_limit.configure(state="disabled" if busy else "normal")
        self.ai_assist_button.state(["disabled"] if busy else ["!disabled"])
        self.browser_button.state(["disabled"] if busy else ["!disabled"])
        for key, button in self.buttons.items():
            enabled = (key == "stop_crawl" and crawling) or (key != "stop_crawl" and not busy)
            button.state(["!disabled"] if enabled else ["disabled"])
