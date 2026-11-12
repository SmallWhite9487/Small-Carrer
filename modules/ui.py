import tkinter as tk
from tkinter import ttk
from typing import Callable


BG = "#F4F6FB"
SURFACE = "#FFFFFF"
TEXT = "#172339"
MUTED = "#65738A"
ACCENT = "#4969E8"
SIDEBAR = "#172339"
BORDER = "#E2E7F0"


def configure_style(root: tk.Tk) -> None:
    root.configure(background=BG)
    root.option_add("*Text.Font", ("Microsoft JhengHei UI", 10))
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=("Microsoft JhengHei UI", 10), foreground=TEXT)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=SURFACE)
    style.configure("Sidebar.TFrame", background=SIDEBAR)
    style.configure("Brand.TLabel", background=SIDEBAR, foreground=SURFACE,
                    font=("Segoe UI", 16, "bold"))
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Title.TLabel", font=("Microsoft JhengHei UI", 22, "bold"))
    style.configure("Subtitle.TLabel", foreground=MUTED)
    style.configure("Card.TLabel", background=SURFACE)
    style.configure("CardHeading.TLabel", background=SURFACE,
                    font=("Microsoft JhengHei UI", 10, "bold"))
    style.configure("CardTitle.TLabel", background=SURFACE, font=("Microsoft JhengHei UI", 13, "bold"))
    style.configure("CardMuted.TLabel", background=SURFACE, foreground=MUTED)
    style.configure("TButton", background=SURFACE, borderwidth=0, padding=(16, 10))
    style.map("TButton", background=[("active", "#E9EEFC")], foreground=[("disabled", MUTED)])
    style.configure("Accent.TButton", background=ACCENT, foreground=SURFACE)
    style.map("Accent.TButton", background=[("disabled", "#B4BFED"), ("active", "#3855C9")],
              foreground=[("disabled", SURFACE), ("!disabled", SURFACE)])
    style.configure("Language.TButton", padding=(10, 6))
    style.configure("Nav.TButton", background=SIDEBAR, foreground="#BDC9DF",
                    anchor="w", padding=(18, 14))
    style.map("Nav.TButton", background=[("active", "#253854")],
              foreground=[("active", SURFACE)])
    style.configure("Active.Nav.TButton", background="#2A4164", foreground=SURFACE)
    style.map("Active.Nav.TButton", background=[("active", "#2A4164")], foreground=[("active", SURFACE)])
    style.configure("TEntry", fieldbackground=SURFACE, bordercolor=BORDER, padding=8)
    style.configure("Filter.TRadiobutton", background=BG, foreground=TEXT, padding=(6, 5))
    style.map("Filter.TRadiobutton", foreground=[("selected", ACCENT)])
    style.configure("Vertical.TScrollbar", background=BORDER, troughcolor=BG, borderwidth=0)


class ScrollArea(ttk.Frame):
    def __init__(self, parent: tk.Misc, *, stretch_body: bool = True) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, background=BG, highlightthickness=0, yscrollincrement=24)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.scroll_view)
        self.on_view: Callable[[], None] | None = None

        def update_scrollbar(first: str, last: str) -> None:
            scrollbar.set(first, last)
            if self.on_view is not None:
                self.on_view()

        self.canvas.configure(yscrollcommand=update_scrollbar)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.keep_at_top = True
        self.stretch_body = stretch_body
        self.content_size: tuple[int, int] | None = None
        self.body.bind("<Configure>", self.update_region)
        self.canvas.bind("<Configure>", self.resize)
        self.top = self.winfo_toplevel()
        self.wheel_binding = self.top.bind("<MouseWheel>", self.on_wheel, add="+")

    def update_region(self, event: tk.Event | None = None) -> None:
        region = ((0, 0, *self.content_size) if self.content_size is not None
                  else self.canvas.bbox("all"))
        self.canvas.configure(scrollregion=region)
        if self.keep_at_top:
            self.canvas.yview_moveto(0)

    def scroll_view(self, *args: str) -> None:
        self.keep_at_top = False
        self.canvas.yview(*args)

    def reset_position(self) -> None:
        self.keep_at_top = True
        self.canvas.yview_moveto(0)

    def resize(self, event: tk.Event) -> None:
        if self.stretch_body:
            self.canvas.itemconfigure(self.window, width=event.width)

    def on_wheel(self, event: tk.Event) -> str | None:
        widget = event.widget
        # Scope wheel handling to this list; text editors retain native scrolling.
        if isinstance(widget, (tk.Text, ttk.Combobox)):
            return None
        while widget is not None and widget != self:
            widget = getattr(widget, "master", None)
        if widget != self or not self.winfo_ismapped() or not event.delta:
            return None
        units = -int(event.delta / 120)
        if not units:
            units = -1 if event.delta > 0 else 1
        self.keep_at_top = False
        self.canvas.yview_scroll(units, "units")
        return "break"

    def destroy(self) -> None:
        if self.wheel_binding:
            self.top.unbind("<MouseWheel>", self.wheel_binding)
        super().destroy()
