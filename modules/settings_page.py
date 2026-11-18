import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from .core import AppConfig
from .i18n import Language, translate
from .ui import BORDER, SURFACE, TEXT, ScrollArea, configure_window_icon

MODEL_CHOICES = {
    "openai": ("gpt-5.6-luna", "gpt-5.4-mini", "gpt-4o-mini"),
    "gemini": ("gemini-3.5-flash-lite", "gemini-4-hydrogen"),
    "custom": (),
}


class RequirementsPreview(tk.Toplevel):
    def __init__(
        self, parent: tk.Tk, text: str, language: Language,
        on_apply: Callable[[str], None], on_cancel: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        configure_window_icon(self)
        self.language = language
        self.on_apply, self.on_cancel = on_apply, on_cancel
        self.title(translate(language, "polish_preview"))
        self.geometry("720x540")
        self.minsize(520, 380)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda event: self.cancel())
        panel = ttk.Frame(self, padding=24)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text=translate(language, "polish_preview_hint"),
                  wraplength=650).pack(anchor="w", pady=(0, 12))
        editor = ttk.Frame(panel)
        editor.pack(fill="both", expand=True)
        self.editor = tk.Text(editor, wrap="word", padx=12, pady=12,
                              background=SURFACE, foreground=TEXT, relief="flat")
        scrollbar = ttk.Scrollbar(editor, command=self.editor.yview)
        self.editor.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.editor.pack(fill="both", expand=True)
        self.editor.insert("1.0", text)
        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", pady=(16, 0))
        ttk.Button(buttons, text=translate(language, "cancel"), command=self.cancel).pack(side="right")
        ttk.Button(buttons, text=translate(language, "apply"), style="Accent.TButton",
                   command=self.apply).pack(side="right", padx=8)
        self.grab_set()
        self.editor.focus_set()

    def apply(self) -> None:
        text = self.editor.get("1.0", "end-1c").strip()
        if not text or len(text) > 6000:
            messagebox.showerror(translate(self.language, "polish_failed"),
                                 translate(self.language, "error.polish_result"), parent=self)
            return
        self.on_apply(text)
        self.destroy()

    def cancel(self) -> None:
        self.on_cancel()
        self.destroy()


class SettingsPage(ttk.Frame):
    def __init__(
        self, parent: ttk.Frame, config: AppConfig,
        on_save: Callable[[], None], on_polish: Callable[[], None],
        on_provider: Callable[[str], None], on_reset: Callable[[], None],
        on_models: Callable[[bool], None],
    ) -> None:
        super().__init__(parent, padding=28)
        self.language = config["language"]
        self.provider = config["provider"]
        self.on_provider = on_provider
        self.profiles = {name: profile.copy() for name, profile in config["profiles"].items()}
        self.profiles[self.provider] = {
            "base_url": config["base_url"], "model": config["model"], "api_key": config["api_key"],
        }
        self.models = {
            name: list(dict.fromkeys(filter(None, [
                self.profiles.get(name, {}).get("model", MODEL_CHOICES[name][0] if MODEL_CHOICES[name] else ""),
                *config.get("backup_models", {}).get(name, []),
            ]))) for name in MODEL_CHOICES
        }
        self.catalog: dict[str, list[str]] = {}
        self.model_drafts: dict[str, str] = {}
        self.labels: dict[str, ttk.Label] = {}
        self.entries: dict[str, ttk.Entry] = {}
        self.title_label = ttk.Label(self, style="Title.TLabel")
        self.title_label.pack(anchor="w")
        self.intro = ttk.Label(self, style="Subtitle.TLabel", wraplength=720)
        self.intro.pack(anchor="w", pady=(8, 20))
        self.scroll = ScrollArea(self)
        self.scroll.pack(fill="both", expand=True)
        requirements_card = ttk.Frame(self.scroll.body, style="Card.TFrame", padding=20)
        requirements_card.pack(fill="x", pady=(0, 16))
        self.add_label(requirements_card, "requirements", title=True)
        self.add_label(requirements_card, "requirements_hint")
        editor = ttk.Frame(requirements_card, style="Card.TFrame")
        editor.pack(fill="x", pady=12)
        self.requirements = tk.Text(
            editor, height=8, wrap="word", padx=12, pady=12, relief="flat",
            background="#F7F9FE", foreground=TEXT, insertbackground=TEXT,
            highlightthickness=1, highlightbackground=BORDER,
        )
        scrollbar = ttk.Scrollbar(editor, command=self.requirements.yview)
        self.requirements.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.requirements.pack(fill="x")
        self.requirements.insert("1.0", config["user_requirements"])
        self.polish_button = ttk.Button(requirements_card, command=on_polish)
        self.polish_button.pack(anchor="w")
        self.add_label(requirements_card, "language_note")
        service = ttk.Frame(self.scroll.body, style="Card.TFrame", padding=20)
        service.pack(fill="x", pady=(0, 16))
        self.add_label(service, "provider", title=True)
        tabs = ttk.Frame(service, style="Card.TFrame")
        tabs.pack(fill="x", pady=(6, 0))
        self.provider_buttons: dict[str, ttk.Button] = {}
        for provider in ("openai", "gemini", "custom"):
            button = ttk.Button(tabs, style="ProviderTab.TButton",
                                command=lambda name=provider: self.switch_provider(name))
            button.pack(side="left", padx=(0, 4))
            self.provider_buttons[provider] = button
        ttk.Separator(service).pack(fill="x", pady=(0, 12))
        self.add_label(service, "api_key", title=True)
        self.key_entry = ttk.Entry(service, show="*")
        self.key_entry.insert(0, config["api_key"])
        self.key_entry.bind("<<Copy>>", self.copy_key)
        self.key_entry.bind("<<Cut>>", self.cut_key)
        self.key_entry.pack(fill="x", pady=(8, 4))
        self.add_label(service, "key_hint")
        self.add_label(service, "base_url")
        endpoint = ttk.Entry(service)
        endpoint.insert(0, config["base_url"])
        endpoint.pack(fill="x", pady=(4, 8))
        self.entries["base_url"] = endpoint
        self.add_label(service, "model", title=True)
        self.add_label(service, "model_hint")
        model_row = ttk.Frame(service, style="Card.TFrame")
        model_row.pack(fill="x", pady=(4, 8))
        self.choose_models = ttk.Menubutton(model_row)
        self.choose_models.pack(side="left")
        self.model_menu = tk.Menu(self.choose_models, tearoff=False, postcommand=lambda: on_models(False))
        self.choose_models.configure(menu=self.model_menu)
        self.fetch_models = ttk.Button(model_row, command=lambda: on_models(True))
        self.fetch_models.pack(side="left", padx=4)
        draft = ttk.Entry(model_row, width=20)
        draft.pack(side="left", fill="x", expand=True, padx=4)
        self.entries["model"] = draft
        draft.bind("<Return>", self.add_custom_model)
        self.add_model_button = ttk.Button(model_row, command=self.add_custom_model)
        self.add_model_button.pack(side="right")
        self.model_chips = ttk.Frame(service, style="Card.TFrame")
        self.model_chips.pack(fill="x")
        self.distribute_models = tk.BooleanVar(value=config.get("distribute_models", False))
        self.distribute_button = ttk.Checkbutton(service, variable=self.distribute_models)
        self.distribute_button.pack(anchor="w", pady=4)
        self.add_label(service, "service_hint")
        self.advanced_button = ttk.Button(service, command=self.toggle_advanced)
        self.advanced_button.pack(anchor="w", pady=(12, 0))
        self.advanced = ttk.Frame(service, style="Card.TFrame")
        self.add_label(self.advanced, "api_key_env")
        env = ttk.Entry(self.advanced)
        env.insert(0, config["api_key_env"])
        env.pack(fill="x", pady=(4, 0))
        self.entries["api_key_env"] = env
        self.advanced_visible = False
        self.save_button = ttk.Button(self, style="Accent.TButton", command=on_save)
        self.save_button.pack(anchor="w", pady=(16, 0))
        self.reset_button = ttk.Button(service, command=on_reset)
        self.reset_button.pack(anchor="w", pady=(8, 0))
        self.refresh_language(self.language)

    def add_custom_model(self, event: tk.Event | None = None) -> None:
        entry = self.entries["model"]
        if entry.instate(["disabled"]):
            return
        name = entry.get().strip()
        if name and name not in self.models[self.provider]:
            self.toggle_model(name)
        entry.delete(0, "end")

    def toggle_model(self, name: str) -> None:
        if self.choose_models.instate(["disabled"]):
            return
        selected = self.models[self.provider]
        if name in selected:
            selected.remove(name)
        else:
            selected.append(name)
        self.refresh_models()

    def set_model_catalog(self, provider: str, models: list[str] | None) -> None:
        if models is None:
            self.catalog.pop(provider, None)
        else:
            self.catalog[provider] = models
        if self.provider == provider:
            self.refresh_models()

    def refresh_models(self) -> None:
        selected = self.models[self.provider]
        self.model_menu.delete(0, "end")
        available = self.catalog.get(self.provider, MODEL_CHOICES[self.provider])
        for model in dict.fromkeys([*available, *selected]):
            self.model_menu.add_command(label=("✓ " if model in selected else "    ") + model,
                                        command=lambda name=model: self.toggle_model(name))
        for chip in self.model_chips.winfo_children():
            chip.destroy()
        for index, model in enumerate(selected):
            label = model if len(model) <= 23 else model[:22] + "…"
            chip = ttk.Button(self.model_chips, text=f"{index + 1}. {label}  ×",
                              command=lambda name=model: self.toggle_model(name))
            chip.grid(row=index // 3, column=index % 3, sticky="w", padx=(0, 4), pady=2)

    def switch_provider(self, provider: str) -> None:
        if provider == self.provider:
            return
        self.model_drafts[self.provider] = self.entries["model"].get()
        self.profiles[self.provider] = {
            "base_url": self.entries["base_url"].get(),
            "model": next(iter(self.models[self.provider]), ""),
            "api_key": self.key_entry.get(),
        }
        self.provider = provider
        defaults = {
            "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "api_key": ""},
            "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta",
                       "model": MODEL_CHOICES["gemini"][0], "api_key": ""},
            "custom": {"base_url": "http://localhost:11434/v1", "model": "", "api_key": ""},
        }
        profile = self.profiles.get(self.provider, defaults[self.provider])
        self.entries["base_url"].delete(0, "end")
        self.entries["base_url"].insert(0, profile["base_url"])
        self.entries["model"].delete(0, "end")
        self.entries["model"].insert(0, self.model_drafts.get(provider, ""))
        self.key_entry.delete(0, "end")
        self.key_entry.insert(0, profile["api_key"])
        self.refresh_provider_tabs()
        self.refresh_models()
        self.on_provider(self.provider)

    def refresh_provider_tabs(self) -> None:
        for provider, button in self.provider_buttons.items():
            button.configure(
                text=(translate(self.language, "provider_custom") if provider == "custom"
                      else {"openai": "OpenAI", "gemini": "Gemini"}[provider]),
                style=("Selected.ProviderTab.TButton" if provider == self.provider
                       else "ProviderTab.TButton"))

    def copy_key(self, event: tk.Event) -> str:
        if self.key_entry.selection_present():
            start = self.key_entry.index("sel.first")
            end = self.key_entry.index("sel.last")
            selected = self.key_entry.tk.call(
                "string", "range", self.key_entry.get(), start, end - 1)
            self.key_entry.clipboard_clear()
            self.key_entry.clipboard_append(selected)
        return "break"

    def cut_key(self, event: tk.Event) -> str:
        if (self.key_entry.selection_present()
                and not self.key_entry.instate(["disabled"])
                and not self.key_entry.instate(["readonly"])):
            start = self.key_entry.index("sel.first")
            end = self.key_entry.index("sel.last")
            self.copy_key(event)
            self.key_entry.delete(start, end)
        return "break"

    def add_label(self, parent: ttk.Frame, key: str, title: bool = False) -> None:
        label = ttk.Label(parent, wraplength=710,
                          style="CardTitle.TLabel" if title else "CardMuted.TLabel")
        label.pack(anchor="w", pady=(4, 2))
        self.labels[key] = label

    def toggle_advanced(self) -> None:
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced.pack(fill="x", pady=(12, 0))
        else:
            self.advanced.pack_forget()

    def refresh_language(self, language: Language) -> None:
        self.language = language
        self.refresh_provider_tabs()
        self.refresh_models()
        self.title_label.configure(text=translate(language, "settings_tab"))
        self.intro.configure(text=translate(language, "settings_intro"))
        for key, label in self.labels.items():
            label.configure(text=translate(language, key))
        for key, button in (("save", self.save_button), ("polish", self.polish_button),
                            ("advanced", self.advanced_button), ("reset_db", self.reset_button),
                            ("choose_models", self.choose_models), ("add_model", self.add_model_button),
                            ("fetch_models", self.fetch_models), ("distribute_models", self.distribute_button)):
            button.configure(text=translate(language, key))

    def read_settings(self) -> AppConfig:
        selected = self.models[self.provider]
        primary = next(iter(selected), "")
        profiles = {name: profile.copy() for name, profile in self.profiles.items()}
        profiles[self.provider] = {
            "base_url": self.entries["base_url"].get().strip(),
            "model": primary,
            "api_key": self.key_entry.get().strip(),
        }
        return AppConfig(
            base_url=self.entries["base_url"].get().strip(),
            model=primary,
            api_key_env=self.entries["api_key_env"].get().strip(),
            user_requirements=self.requirements.get("1.0", "end-1c").strip(),
            language=self.language,
            provider=self.provider,
            api_key=self.key_entry.get().strip(),
            websites=[],
            max_pages=10,
            profiles=profiles,
            backup_models={name: models[1:] for name, models in self.models.items() if len(models) > 1},
            distribute_models=self.distribute_models.get(),
        )

    def apply_requirements(self, text: str) -> None:
        self.requirements.delete("1.0", "end")
        self.requirements.insert("1.0", text)

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for entry in (*self.entries.values(), self.key_entry):
            entry.configure(state=state)
        self.requirements.configure(state=state)
        for button in (self.save_button, self.polish_button, self.advanced_button,
                       self.reset_button, self.choose_models, self.fetch_models, self.add_model_button,
                       self.distribute_button,
                       *self.provider_buttons.values()):
            button.state(["disabled"] if busy else ["!disabled"])
