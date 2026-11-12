from tkinter import ttk
from typing import Callable

from .core import CATEGORIES, JobRecord
from .i18n import Language, translate
from .job_list import JobListPage


class HomePage(JobListPage):
    def __init__(
        self, parent: ttk.Frame, language: Language,
        on_settings: Callable[[], None], on_evaluation: Callable[[], None],
        on_filter: Callable[[str], None],
    ) -> None:
        super().__init__(parent, padding=28)
        self.language = language
        self.labels: dict[str, ttk.Label] = {}
        self.counts: dict[str, ttk.Label] = {}
        self.title_label = ttk.Label(self, style="Title.TLabel")
        self.title_label.pack(anchor="w")
        self.intro = ttk.Label(self, style="Subtitle.TLabel", wraplength=720)
        self.intro.pack(anchor="w", pady=(8, 12))
        hero = ttk.Frame(self)
        hero.pack(fill="x", pady=(0, 12))
        self.settings_button = ttk.Button(hero, style="Accent.TButton", command=on_settings)
        self.settings_button.pack(side="left", padx=(0, 12))
        self.evaluation_button = ttk.Button(hero, command=on_evaluation)
        self.evaluation_button.pack(side="left")
        stats = ttk.Frame(self)
        stats.pack(fill="x", pady=(0, 12))
        for index, key in enumerate(("total_jobs", *CATEGORIES)):
            card = ttk.Frame(stats, style="Card.TFrame", padding=10)
            card.grid(row=0, column=index, sticky="nsew", padx=3)
            stats.columnconfigure(index, weight=1, uniform="stats")
            label = ttk.Label(card, style="CardMuted.TLabel")
            label.pack(anchor="w")
            count = ttk.Label(card, text="0", style="CardTitle.TLabel")
            count.pack(anchor="w", pady=(4, 0))
            self.labels[key] = label
            self.counts[key] = count
        self.initialize_job_list(language, on_filter)
        self.refresh_language(language)

    def update_jobs(self, jobs: list[JobRecord]) -> None:
        self.set_jobs(jobs)
        self.counts["total_jobs"].configure(text=str(len(jobs)))
        for category in CATEGORIES:
            self.counts[category].configure(
                text=str(sum(job.result["category"] == category for job in jobs)))

    def refresh_language(self, language: Language) -> None:
        self.language = language
        self.title_label.configure(text=translate(language, "home_title"))
        self.intro.configure(text=translate(language, "home_intro"))
        for key, label in self.labels.items():
            label.configure(text=translate(language, key))
        self.settings_button.configure(text=translate(language, "go_settings"))
        self.evaluation_button.configure(text=translate(language, "go_evaluation"))
        self.refresh_job_language(language)
