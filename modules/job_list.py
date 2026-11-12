import tkinter as tk
from tkinter import ttk
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .evaluation_page import JobCard

from .core import JobRecord
from .i18n import Language, translate
from .ui import ScrollArea


CARD_WIDTH = 270
CARD_HEIGHT = 300
CARD_GAP = 14
FILTERS = ("all", "inconsistent", "propinquity", "coincidence")


class JobListPage(ttk.Frame):
    def initialize_job_list(self, language: Language, on_filter: Callable[[str], None]) -> None:
        self.language = language
        self.on_filter = on_filter
        self.cards: dict[str, JobCard] = {}
        self._jobs: dict[str, JobRecord] = {}
        self._visible: list[str] = []
        self._virtual = False
        self._viewport_id: str | None = None
        self.columns = 0
        self._layout_id: str | None = None
        self._pending_columns = 1
        self._positions: dict[str, tuple[int, int]] = {}
        self.filter = tk.StringVar(value="all")
        self.results_count = tk.StringVar()
        filters = ttk.Frame(self)
        filters.pack(fill="x", pady=(0, 8))
        self.filter_buttons = {}
        for key in FILTERS:
            button = ttk.Radiobutton(filters, variable=self.filter, value=key,
                                     style="Filter.TRadiobutton", command=self.apply_filter)
            button.pack(side="left", padx=(0, 8))
            self.filter_buttons[key] = button
        ttk.Label(filters, textvariable=self.results_count, style="Subtitle.TLabel").pack(side="right")
        self.scroll = ScrollArea(self, stretch_body=False)
        self.scroll.on_view = self._schedule_viewport
        self.scroll.pack(fill="both", expand=True)
        self.scroll.canvas.bind("<Configure>", self.reflow, add="+")
        self.empty = ttk.Frame(self.scroll.body, style="Card.TFrame", padding=30)
        self.empty_title = ttk.Label(self.empty, style="CardTitle.TLabel")
        self.empty_title.pack(anchor="w")
        self.empty_hint = ttk.Label(self.empty, style="CardMuted.TLabel", wraplength=500)
        self.empty_hint.pack(anchor="w", pady=(12, 0))
        self.bind("<Destroy>", self._cancel_layout, add="+")

    @property
    def jobs(self) -> list[JobRecord]:
        return list(self._jobs.values())

    def set_jobs(self, jobs: list[JobRecord]) -> None:
        self._jobs = {job.source: job for job in jobs}
        for source in list(self.cards):
            if self._jobs.get(source) != self.cards[source].job:
                self.cards.pop(source).destroy()
                self._positions.pop(source, None)
        self.layout_cards(reset=True)

    def upsert_job(self, job: JobRecord) -> None:
        self._jobs.pop(job.source, None)
        self._jobs = {job.source: job, **self._jobs}
        old = self.cards.pop(job.source, None)
        if old is not None:
            old.destroy()
        self._positions.pop(job.source, None)
        self.layout_cards()

    def reflow(self, event: tk.Event) -> None:
        columns = max(1, (event.width + CARD_GAP) // (CARD_WIDTH + CARD_GAP))
        self._pending_columns = columns
        if self._layout_id is not None:
            self.after_cancel(self._layout_id)
            self._layout_id = None
        if self.columns == 0:
            self.columns = columns
            self.layout_cards()
        elif columns != self.columns:
            self._layout_id = self.after(100, self._finish_reflow)

    def _finish_reflow(self) -> None:
        self._layout_id = None
        if self.columns != self._pending_columns:
            self.columns = self._pending_columns
            self.layout_cards()

    def _cancel_layout(self, event: tk.Event) -> None:
        if event.widget == self:
            for callback in (self._layout_id, self._viewport_id):
                if callback is not None:
                    self.after_cancel(callback)
            self._layout_id = self._viewport_id = None
            self.scroll.on_view = None

    def _schedule_viewport(self) -> None:
        if self._virtual and self._viewport_id is None:
            self._viewport_id = self.after_idle(self._render_viewport)

    def _render_viewport(self) -> None:
        from .evaluation_page import JobCard

        if self._viewport_id is not None:
            self.after_cancel(self._viewport_id)
        self._viewport_id = None
        if not self._virtual:
            return
        columns = max(1, self.columns)
        row_height = CARD_HEIGHT + CARD_GAP
        first_row = max(0, int(self.scroll.canvas.canvasy(0)) // row_height - 1)
        last_row = first_row + max(1, self.scroll.canvas.winfo_height() // row_height) + 4
        self.scroll.canvas.coords(self.scroll.window, 0, first_row * row_height)
        self.scroll.body.configure(height=(last_row - first_row) * row_height)
        wanted = self._visible[first_row * columns:last_row * columns]
        for source in self.cards.keys() - set(wanted):
            self.cards.pop(source).destroy()
        for index, source in enumerate(wanted, first_row * columns):
            if source not in self.cards:
                self.cards[source] = JobCard(self.scroll.body, self._jobs[source], self.language)
            row, column = divmod(index, columns)
            position = (row - first_row, column)
            if self._positions.get(source) != position:
                self.cards[source].place(x=column * (CARD_WIDTH + CARD_GAP),
                                         y=(row - first_row) * row_height)
        self._positions = {source: (index // columns - first_row, index % columns)
                           for index, source in enumerate(wanted, first_row * columns)}

    def apply_filter(self) -> None:
        self.layout_cards(reset=True)
        self.on_filter(self.filter.get())

    def layout_cards(self, reset: bool = False) -> None:
        from .evaluation_page import JobCard

        selected = self.filter.get()
        visible = [source for source, job in self._jobs.items()
                   if selected == "all" or job.result["category"] == selected]
        self._visible = visible
        columns = max(1, self.columns)
        virtual = len(self._jobs) > 60
        if virtual != self._virtual:
            for card in self.cards.values():
                card.destroy()
            self.cards.clear()
            self._positions.clear()
        self._virtual = virtual
        if reset:
            self.scroll.reset_position()
        if virtual:
            self.empty.grid_forget()
            self.scroll.body.grid_propagate(False)
            self.scroll.content_size = (
                columns * (CARD_WIDTH + CARD_GAP),
                max(CARD_HEIGHT, ((len(visible) + columns - 1) // columns) * (CARD_HEIGHT + CARD_GAP)))
            self.scroll.body.configure(width=self.scroll.content_size[0])
            self.scroll.update_region()
            self._render_viewport()
        else:
            self.scroll.content_size = None
            self.scroll.canvas.coords(self.scroll.window, 0, 0)
            self.scroll.body.grid_propagate(True)
            for source, job in self._jobs.items():
                if source not in self.cards:
                    self.cards[source] = JobCard(self.scroll.body, job, self.language)
            self._layout_grid(visible, columns)
        if not visible:
            self.empty.grid(row=0, column=0, columnspan=columns, sticky="ew")
        self.empty_title.configure(text=translate(
            self.language, "empty_jobs" if not self._jobs else "no_matching_jobs"))
        self.empty_hint.configure(text=translate(
            self.language, "empty_jobs_hint") if not self._jobs else "")
        self.results_count.set(translate(self.language, "results_count", count=len(visible)))

    def _layout_grid(self, visible: list[str], columns: int) -> None:
        positions = {source: divmod(index, columns) for index, source in enumerate(visible)}
        for source in self._positions.keys() - positions.keys():
            if source in self.cards:
                self.cards[source].grid_forget()
        for source, (row, column) in positions.items():
            if self._positions.get(source) != (row, column):
                self.cards[source].grid(row=row, column=column,
                                        padx=(0, CARD_GAP), pady=(0, CARD_GAP), sticky="nw")
        self._positions = positions
        if visible:
            self.empty.grid_forget()

    def refresh_job_language(self, language: Language) -> None:
        self.language = language
        for key, button in self.filter_buttons.items():
            button.configure(text=translate(language, "filter_all" if key == "all" else key))
        for card in self.cards.values():
            card.refresh_language(language)
        self.layout_cards()
