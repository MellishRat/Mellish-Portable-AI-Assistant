from __future__ import annotations

import json
import hashlib
import ctypes
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import winsound
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import soundfile as sf
from PIL import Image, ImageGrab, ImageTk

from . import __version__
from .analyzer import analyze_comic_image, analyze_text, extract_image_text
from .exporters import export_dialogue, export_srt
from .importers import IMAGE_EXTENSIONS, copy_source, read_document
from .paths import assistant_root, kokoro_files, ollama_url, projects_root
from .project import NarrationProject, new_line, safe_slug
from .reader import clean_spoken_text, text_chunks_with_ranges
from .tts import KOKORO_VOICES, TTSEngine, combine_part


def enable_per_monitor_dpi_awareness():
    """Keep Tk selection coordinates aligned with physical screenshot pixels."""
    if os.name != "nt":
        return "not-windows"
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "per-monitor-v2"
    except Exception:
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) in (0, -2147024891):
            return "per-monitor"
    except Exception:
        pass
    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            return "system"
    except Exception:
        pass
    return "unchanged"


DPI_AWARENESS_MODE = enable_per_monitor_dpi_awareness()


class TextImportDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Paste Text")
        self.geometry("800x600")
        self.transient(parent)
        self.result = None
        controls = ttk.Frame(self, padding=8)
        controls.pack(fill="x")
        ttk.Label(controls, text="Part").pack(side="left")
        self.part = tk.IntVar(value=1)
        ttk.Spinbox(controls, from_=1, to=9999, textvariable=self.part, width=8).pack(side="left", padx=6)
        self.use_llm = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="Identify speakers with local LLM", variable=self.use_llm).pack(side="left", padx=12)
        self.text = tk.Text(self, wrap="word", undo=True)
        self.text.pack(fill="both", expand=True, padx=8)
        buttons = ttk.Frame(self, padding=8)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Import", command=self.accept).pack(side="right", padx=8)
        self.grab_set()
        self.text.focus_set()

    def accept(self):
        text = self.text.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Paste Text", "Paste some text first.", parent=self)
            return
        self.result = (text, int(self.part.get()), bool(self.use_llm.get()))
        self.destroy()


class NarrationStudio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Mellish Narration Studio {__version__}")
        self.geometry("1420x880")
        self.minsize(1050, 680)
        self.project: NarrationProject | None = None
        self.tts = TTSEngine()
        self.cancel_event = threading.Event()
        self.busy = False
        self._speaker_editor = None
        self._playback_after = None
        self._playback_active = False
        self._playback_lines = []
        self._playback_index = 0
        self._comic_image = None
        self._comic_photo = None
        self.reader_cancel_event = threading.Event()
        self._reader_after = None
        self._reader_active = False
        self._reader_items = []
        self._reader_index = 0
        self._reader_widget = None
        self._reader_status_var = None
        self.screen_image_path = None
        self._screen_image = None
        self._screen_photo = None
        self._build_style()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(200, self.component_status)

    def _build_style(self):
        self.option_add("*tearOff", False)
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Status.TLabel", padding=(8, 4))

    def _build_ui(self):
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu)
        file_menu.add_command(label="New Project…", command=self.new_project)
        file_menu.add_command(label="Open Project…", command=self.open_project)
        file_menu.add_command(label="Save", command=self.save_project, accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="Open Project Folder", command=self.open_project_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menu.add_cascade(label="File", menu=file_menu)
        import_menu = tk.Menu(menu)
        import_menu.add_command(label="Paste Text…", command=self.paste_text)
        import_menu.add_command(label="Document Files…", command=self.import_documents)
        import_menu.add_command(label="Comic Images…", command=self.import_images)
        menu.add_cascade(label="Import", menu=import_menu)
        self.config(menu=menu)
        self.bind_all("<Control-s>", lambda _event: self.save_project())

        toolbar = ttk.Frame(self, padding=6)
        toolbar.pack(fill="x")
        for text, command in (("New", self.new_project), ("Open", self.open_project), ("Save", self.save_project),
                              ("Paste Text", self.paste_text), ("Add Documents", self.import_documents),
                              ("Add Comic Pages", self.import_images)):
            ttk.Button(toolbar, text=text, command=command).pack(side="left", padx=2)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="Generate Selected", command=self.generate_selected).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Generate All", command=self.generate_all).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Stop", command=self.stop_work).pack(side="left", padx=2)
        self.project_label = ttk.Label(toolbar, text="No project open")
        self.project_label.pack(side="right", padx=8)

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True)
        self.script_tab = ttk.Frame(self.tabs)
        self.reader_tab = ttk.Frame(self.tabs)
        self.playback_tab = ttk.Frame(self.tabs)
        self.screen_reader_tab = ttk.Frame(self.tabs)
        self.cast_tab = ttk.Frame(self.tabs)
        self.export_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.script_tab, text="Script")
        self.tabs.add(self.reader_tab, text="Text Reader")
        self.tabs.add(self.screen_reader_tab, text="Screen Reader")
        self.tabs.add(self.playback_tab, text="Comic Reader")
        self.tabs.add(self.cast_tab, text="Cast & Pronunciation")
        self.tabs.add(self.export_tab, text="Generate & Export")
        self._build_script_tab()
        self._build_reader_tab()
        self._build_screen_reader_tab()
        self._build_playback_tab()
        self._build_cast_tab()
        self._build_export_tab()

        status = ttk.Frame(self)
        status.pack(fill="x")
        self.status_var = tk.StringVar(value="Ready")
        self.component_var = tk.StringVar(value="Checking components…")
        ttk.Label(status, textvariable=self.status_var, style="Status.TLabel").pack(side="left", fill="x", expand=True)
        ttk.Label(status, textvariable=self.component_var, style="Status.TLabel").pack(side="right")

    def _build_script_tab(self):
        pane = ttk.Panedwindow(self.script_tab, orient="vertical")
        pane.pack(fill="both", expand=True, padx=6, pady=6)
        table_frame = ttk.Frame(pane)
        editor = ttk.Frame(pane, padding=8)
        pane.add(table_frame, weight=3)
        pane.add(editor, weight=2)

        columns = ("part", "order", "speaker", "type", "text", "voice", "confidence", "status")
        self.line_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        widths = {"part": 55, "order": 60, "speaker": 140, "type": 90, "text": 610,
                  "voice": 115, "confidence": 85, "status": 90}
        for column in columns:
            self.line_tree.heading(column, text=column.title())
            self.line_tree.column(column, width=widths[column], stretch=column == "text")
        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.line_tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.line_tree.xview)
        self.line_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.line_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.line_tree.bind("<<TreeviewSelect>>", self.load_selected_line)
        self.line_tree.bind("<Double-1>", self.begin_speaker_edit)

        fields = ttk.Frame(editor)
        fields.pack(fill="x")
        self.edit_part = tk.IntVar(value=1)
        self.edit_speaker = tk.StringVar()
        self.edit_type = tk.StringVar()
        self.edit_voice = tk.StringVar()
        self.edit_speed = tk.StringVar()
        for index, (label, widget) in enumerate((
            ("Part", ttk.Spinbox(fields, from_=1, to=9999, textvariable=self.edit_part, width=7)),
            ("Speaker", ttk.Combobox(fields, textvariable=self.edit_speaker, width=22)),
            ("Type", ttk.Combobox(fields, textvariable=self.edit_type, values=("dialogue", "narration", "thought", "caption", "sound_effect"), state="readonly", width=14)),
            ("Voice override", ttk.Combobox(fields, textvariable=self.edit_voice, values=[""] + KOKORO_VOICES, width=18)),
            ("Speed override", ttk.Entry(fields, textvariable=self.edit_speed, width=10)),
        )):
            ttk.Label(fields, text=label).grid(row=0, column=index, sticky="w", padx=3)
            widget.grid(row=1, column=index, sticky="ew", padx=3)
        fields.columnconfigure(1, weight=1)
        ttk.Label(editor, text="Text").pack(anchor="w", pady=(8, 0))
        self.edit_text = tk.Text(editor, height=5, wrap="word", undo=True)
        self.edit_text.pack(fill="both", expand=True)
        direction_row = ttk.Frame(editor)
        direction_row.pack(fill="x", pady=(6, 0))
        ttk.Label(direction_row, text="Direction").pack(side="left")
        self.edit_direction = tk.StringVar()
        ttk.Entry(direction_row, textvariable=self.edit_direction).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(direction_row, text="Apply Changes", command=self.apply_line_changes).pack(side="left")
        ttk.Button(direction_row, text="Add Blank Line", command=self.add_blank_line).pack(side="left", padx=4)
        ttk.Button(direction_row, text="Delete Selected", command=self.delete_selected).pack(side="left")

        self.edit_speaker_combo = fields.grid_slaves(row=1, column=1)[0]
        ttk.Label(editor, text="Tip: double-click any Speaker cell above to reassign it from the cast list.").pack(anchor="w", pady=(5, 0))

    def _build_reader_tab(self):
        outer = ttk.Panedwindow(self.reader_tab, orient="horizontal")
        outer.pack(fill="both", expand=True, padx=8, pady=8)
        text_side = ttk.Frame(outer)
        voice_side = ttk.Frame(outer, padding=(10, 0, 0, 0))
        outer.add(text_side, weight=3)
        outer.add(voice_side, weight=2)

        heading = ttk.Frame(text_side)
        heading.pack(fill="x", pady=(0, 6))
        ttk.Label(heading, text="Paste text to read aloud", font=("Segoe UI", 12, "bold")).pack(side="left")
        self.reader_status = tk.StringVar(value="Choose a voice, paste text, then press Read Aloud.")
        ttk.Label(heading, textvariable=self.reader_status).pack(side="right")
        text_frame = ttk.Frame(text_side)
        text_frame.pack(fill="both", expand=True)
        self.reader_text = tk.Text(text_frame, wrap="word", undo=True, font=("Segoe UI", 11), padx=10, pady=10)
        reader_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.reader_text.yview)
        self.reader_text.configure(yscrollcommand=reader_scroll.set)
        self.reader_text.tag_configure("reading", background="#ffe08a", foreground="#111111")
        self.reader_text.grid(row=0, column=0, sticky="nsew")
        reader_scroll.grid(row=0, column=1, sticky="ns")
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        controls = ttk.Frame(text_side)
        controls.pack(fill="x", pady=(0, 8), before=text_frame)
        ttk.Button(controls, text="Read Aloud", command=self.start_text_reader).pack(side="left", padx=2)
        ttk.Button(controls, text="Stop", command=self.stop_text_reader).pack(side="left", padx=2)
        ttk.Button(controls, text="Paste", command=self.paste_reader_text).pack(side="left", padx=2)
        ttk.Button(controls, text="Clear", command=self.clear_text_reader).pack(side="left", padx=2)
        self.skip_symbols = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="Skip punctuation / special characters",
                        variable=self.skip_symbols).pack(side="left", padx=(12, 2))
        ttk.Label(controls, text="Speed").pack(side="left", padx=(16, 4))
        self.reader_speed = tk.DoubleVar(value=1.0)
        ttk.Spinbox(controls, from_=0.5, to=2.0, increment=0.05, textvariable=self.reader_speed, width=6).pack(side="left")
        self.reader_voice = tk.StringVar(value="af_sarah")
        ttk.Label(controls, text="Selected voice:").pack(side="left", padx=(16, 4))
        ttk.Label(controls, textvariable=self.reader_voice, font=("Segoe UI", 9, "bold")).pack(side="left")

        ttk.Label(voice_side, text="Choose a Voice", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(voice_side, text="Select a card. Preview says: “This is what the generated text sounds like.”",
                  wraplength=430).pack(anchor="w", pady=(2, 7))
        canvas_frame = ttk.Frame(voice_side)
        canvas_frame.pack(fill="both", expand=True)
        voice_canvas = tk.Canvas(canvas_frame, highlightthickness=0)
        voice_scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=voice_canvas.yview)
        voice_canvas.configure(yscrollcommand=voice_scroll.set)
        voice_canvas.grid(row=0, column=0, sticky="nsew")
        voice_scroll.grid(row=0, column=1, sticky="ns")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        cards = ttk.Frame(voice_canvas)
        cards_window = voice_canvas.create_window((0, 0), window=cards, anchor="nw")
        cards.bind("<Configure>", lambda _event: voice_canvas.configure(scrollregion=voice_canvas.bbox("all")))
        voice_canvas.bind("<Configure>", lambda event: voice_canvas.itemconfigure(cards_window, width=event.width))
        for index, voice in enumerate(KOKORO_VOICES):
            card = ttk.LabelFrame(cards, text=self.voice_description(voice), padding=6)
            card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=3, pady=3)
            ttk.Radiobutton(card, text=voice, variable=self.reader_voice, value=voice).pack(side="left", fill="x", expand=True)
            ttk.Button(card, text="Preview", command=lambda selected=voice: self.preview_reader_voice(selected)).pack(side="right", padx=(5, 0))
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)

    def _build_screen_reader_tab(self):
        outer = ttk.Frame(self.screen_reader_tab, padding=8)
        outer.pack(fill="both", expand=True)
        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(0, 7))
        ttk.Button(controls, text="Capture Screen Area", command=self.capture_screen_area).pack(side="left", padx=2)
        ttk.Button(controls, text="Paste Image", command=self.paste_screen_image).pack(side="left", padx=2)
        ttk.Button(controls, text="Extract Text", command=self.extract_screen_text).pack(side="left", padx=2)
        ttk.Button(controls, text="Read Aloud", command=self.start_screen_reader).pack(side="left", padx=(12, 2))
        ttk.Button(controls, text="Stop", command=self.stop_text_reader).pack(side="left", padx=2)
        self.screen_auto_read = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="Read automatically after OCR", variable=self.screen_auto_read).pack(side="left", padx=10)
        ttk.Checkbutton(controls, text="Skip symbols", variable=self.skip_symbols).pack(side="left", padx=4)
        ttk.Label(controls, text="Uses Text Reader voice:").pack(side="left", padx=(10, 3))
        ttk.Label(controls, textvariable=self.reader_voice, font=("Segoe UI", 9, "bold")).pack(side="left")
        self.screen_status = tk.StringVar(value="Capture an area or paste an image from the clipboard.")
        ttk.Label(controls, textvariable=self.screen_status).pack(side="right", padx=6)

        pane = ttk.Panedwindow(outer, orient="vertical")
        pane.pack(fill="both", expand=True)
        preview_frame = ttk.LabelFrame(pane, text="Captured Image", padding=5)
        text_frame = ttk.LabelFrame(pane, text="Extracted Text", padding=5)
        pane.add(preview_frame, weight=3)
        pane.add(text_frame, weight=2)
        self.screen_preview = ttk.Label(preview_frame, text="No image captured", anchor="center")
        self.screen_preview.pack(fill="both", expand=True)
        self.screen_preview.bind("<Configure>", self.resize_screen_preview)
        self.screen_text = tk.Text(text_frame, wrap="word", undo=True, font=("Segoe UI", 11), padx=10, pady=8)
        self.screen_text.tag_configure("reading", background="#ffe08a", foreground="#111111")
        screen_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.screen_text.yview)
        self.screen_text.configure(yscrollcommand=screen_scroll.set)
        self.screen_text.grid(row=0, column=0, sticky="nsew")
        screen_scroll.grid(row=0, column=1, sticky="ns")
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)

    @staticmethod
    def voice_description(voice):
        accent = {"a": "American", "b": "British"}.get(voice[:1], "")
        gender = {"f": "female", "m": "male"}.get(voice[1:2], "voice")
        name = voice.split("_", 1)[-1].replace("_", " ").title()
        return f"{name} — {accent} {gender}".strip()

    def _build_playback_tab(self):
        outer = ttk.Frame(self.playback_tab, padding=8)
        outer.pack(fill="both", expand=True)
        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Label(controls, text="Comic page").pack(side="left")
        self.playback_page = tk.StringVar()
        self.playback_page_combo = ttk.Combobox(controls, textvariable=self.playback_page, state="readonly", width=9)
        self.playback_page_combo.pack(side="left", padx=6)
        self.playback_page_combo.bind("<<ComboboxSelected>>", lambda _event: self.load_playback_page())
        ttk.Button(controls, text="Previous Page", command=lambda: self.change_playback_page(-1)).pack(side="left", padx=2)
        ttk.Button(controls, text="Next Page", command=lambda: self.change_playback_page(1)).pack(side="left", padx=2)
        ttk.Separator(controls, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(controls, text="Play Page", command=self.play_comic_page).pack(side="left", padx=2)
        ttk.Button(controls, text="Play Selected Line", command=self.play_selected_comic_line).pack(side="left", padx=2)
        ttk.Button(controls, text="Stop", command=self.stop_playback).pack(side="left", padx=2)
        self.playback_status = tk.StringVar(value="Open a project containing comic pages.")
        ttk.Label(controls, textvariable=self.playback_status).pack(side="right", padx=8)

        pane = ttk.Panedwindow(outer, orient="horizontal")
        pane.pack(fill="both", expand=True)
        image_frame = ttk.Frame(pane, relief="sunken")
        script_frame = ttk.Frame(pane)
        pane.add(image_frame, weight=3)
        pane.add(script_frame, weight=2)
        self.comic_image_label = ttk.Label(image_frame, text="No comic page selected", anchor="center")
        self.comic_image_label.pack(fill="both", expand=True)
        self.comic_image_label.bind("<Configure>", self.resize_comic_image)

        columns = ("speaker", "text", "status")
        self.playback_tree = ttk.Treeview(script_frame, columns=columns, show="headings", selectmode="browse")
        self.playback_tree.heading("speaker", text="Speaker")
        self.playback_tree.heading("text", text="Line")
        self.playback_tree.heading("status", text="Audio")
        self.playback_tree.column("speaker", width=125, stretch=False)
        self.playback_tree.column("text", width=420, stretch=True)
        self.playback_tree.column("status", width=85, stretch=False)
        scroll = ttk.Scrollbar(script_frame, orient="vertical", command=self.playback_tree.yview)
        self.playback_tree.configure(yscrollcommand=scroll.set)
        self.playback_tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        script_frame.rowconfigure(0, weight=1)
        script_frame.columnconfigure(0, weight=1)
        self.playback_tree.bind("<Double-1>", lambda _event: self.play_selected_comic_line())

    def _build_cast_tab(self):
        pane = ttk.Panedwindow(self.cast_tab, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8, pady=8)
        left, right = ttk.Frame(pane), ttk.Frame(pane, padding=12)
        pane.add(left, weight=2)
        pane.add(right, weight=3)
        self.cast_tree = ttk.Treeview(left, columns=("voice", "speed", "aliases"), show="tree headings")
        self.cast_tree.heading("#0", text="Character")
        for col in ("voice", "speed", "aliases"):
            self.cast_tree.heading(col, text=col.title())
        self.cast_tree.pack(fill="both", expand=True)
        self.cast_tree.bind("<<TreeviewSelect>>", self.load_cast)
        self.cast_name = tk.StringVar()
        self.cast_voice = tk.StringVar()
        self.cast_speed = tk.DoubleVar(value=1.0)
        self.cast_aliases = tk.StringVar()
        self.cast_notes = tk.StringVar()
        for row, (label, variable, values) in enumerate((
            ("Character", self.cast_name, None), ("Voice", self.cast_voice, KOKORO_VOICES),
            ("Speed", self.cast_speed, None), ("Aliases (comma separated)", self.cast_aliases, None),
            ("Acting notes", self.cast_notes, None),
        )):
            ttk.Label(right, text=label).grid(row=row * 2, column=0, sticky="w", pady=(4, 0))
            widget = ttk.Combobox(right, textvariable=variable, values=values) if values else ttk.Entry(right, textvariable=variable)
            widget.grid(row=row * 2 + 1, column=0, sticky="ew")
        ttk.Button(right, text="Save Character", command=self.save_cast).grid(row=10, column=0, sticky="ew", pady=12)
        ttk.Separator(right).grid(row=11, column=0, sticky="ew", pady=8)
        ttk.Label(right, text="Pronunciation Dictionary").grid(row=12, column=0, sticky="w")
        self.pronunciation_text = tk.Text(right, height=10, wrap="none")
        self.pronunciation_text.grid(row=13, column=0, sticky="nsew")
        ttk.Label(right, text="One entry per line: original = spoken form").grid(row=14, column=0, sticky="w")
        ttk.Button(right, text="Save Pronunciations", command=self.save_pronunciations).grid(row=15, column=0, sticky="ew", pady=6)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(13, weight=1)

    def _build_export_tab(self):
        frame = ttk.Frame(self.export_tab, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Voice Generation", font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w")
        self.overwrite_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Regenerate existing audio", variable=self.overwrite_var).grid(row=1, column=0, sticky="w", pady=6)
        ttk.Button(frame, text="Generate All Lines", command=self.generate_all).grid(row=2, column=0, sticky="ew", pady=3)
        ttk.Button(frame, text="Generate Selected Script Lines", command=self.generate_selected).grid(row=3, column=0, sticky="ew", pady=3)
        ttk.Button(frame, text="Combine Part…", command=self.combine_part_dialog).grid(row=4, column=0, sticky="ew", pady=3)
        ttk.Separator(frame).grid(row=5, column=0, sticky="ew", pady=16)
        ttk.Label(frame, text="Exports", font=("Segoe UI", 13, "bold")).grid(row=6, column=0, sticky="w")
        ttk.Button(frame, text="Export Unity / VRChat JSON + CSV", command=self.export_game).grid(row=7, column=0, sticky="ew", pady=3)
        ttk.Button(frame, text="Export Subtitles (.srt)", command=self.export_subtitles).grid(row=8, column=0, sticky="ew", pady=3)
        ttk.Button(frame, text="Open Output Folder", command=self.open_project_folder).grid(row=9, column=0, sticky="ew", pady=3)
        self.progress = ttk.Progressbar(frame, mode="determinate")
        self.progress.grid(row=10, column=0, sticky="ew", pady=(24, 4))
        self.generation_label = ttk.Label(frame, text="No generation running")
        self.generation_label.grid(row=11, column=0, sticky="w")
        frame.columnconfigure(0, weight=1)

    def require_project(self) -> NarrationProject | None:
        if self.project is None:
            messagebox.showinfo("Narration Studio", "Create or open a project first.")
        return self.project

    def new_project(self):
        title = simpledialog.askstring("New Project", "Project title:", parent=self)
        if not title:
            return
        folder = filedialog.askdirectory(title="Choose project folder", initialdir=str(projects_root()))
        if not folder:
            folder = str(projects_root() / safe_slug(title))
        target = Path(folder)
        if (target / "project.json").exists() and not messagebox.askyesno("Existing Project", "Open the existing project in this folder?"):
            return
        self.project = NarrationProject.load(target) if (target / "project.json").exists() else NarrationProject.create(target, title)
        self.refresh_all()

    def open_project(self):
        path = filedialog.askopenfilename(title="Open Narration Project", initialdir=str(projects_root()),
                                          filetypes=[("Narration project", "project.json"), ("JSON", "*.json")])
        if path:
            try:
                self.project = NarrationProject.load(Path(path))
                self.refresh_all()
            except Exception as exc:
                messagebox.showerror("Open Project", str(exc))

    def save_project(self):
        if self.project:
            self.project.save()
            self.status_var.set("Project saved")

    def refresh_all(self):
        if not self.project:
            return
        self.project_label.configure(text=f"{self.project.data['title']} — {self.project.folder}")
        self.refresh_lines()
        self.refresh_cast()
        self.refresh_pronunciations()
        self.refresh_playback()

    def refresh_lines(self):
        selected = set(self.line_tree.selection())
        children = self.line_tree.get_children()
        if children:
            self.line_tree.delete(*children)
        if not self.project:
            return
        for line in self.project.lines:
            voice, _ = self.project.effective_voice(line)
            values = (line["part"], int(line["order"]) + 1, line["speaker"], line["type"], line["text"],
                      voice, f"{float(line['confidence']):.0%}", line["status"])
            self.line_tree.insert("", "end", iid=line["id"], values=values)
        for iid in selected:
            if self.line_tree.exists(iid):
                self.line_tree.selection_add(iid)

    def refresh_cast(self):
        children = self.cast_tree.get_children()
        if children:
            self.cast_tree.delete(*children)
        if not self.project:
            return
        for speaker, details in sorted(self.project.data["cast"].items()):
            self.cast_tree.insert("", "end", iid=speaker, text=speaker,
                                  values=(details.get("voice", ""), details.get("speed", 1.0), ", ".join(details.get("aliases", []))))
        self.edit_speaker_combo.configure(values=self.speaker_choices())

    def speaker_choices(self):
        established = list(self.project.data["cast"]) if self.project else []
        return sorted(set(established + ["Narrator", "Unknown", "Man", "Woman"]), key=str.casefold)

    def begin_speaker_edit(self, event):
        if not self.project or self.line_tree.identify_column(event.x) != "#3":
            return
        line_id = self.line_tree.identify_row(event.y)
        if not line_id:
            return
        bounds = self.line_tree.bbox(line_id, "speaker")
        if not bounds:
            return
        if self._speaker_editor is not None:
            self._speaker_editor.destroy()
        self.line_tree.selection_set(line_id)
        x, y, width, height = bounds
        editor = ttk.Combobox(self.line_tree, values=self.speaker_choices(), state="normal")
        editor.set(self.project.line_by_id(line_id).get("speaker", "Unknown"))
        editor.place(x=x, y=y, width=width, height=height)
        self._speaker_editor = editor

        def commit(_event=None):
            if self._speaker_editor is not editor:
                return
            speaker = editor.get().strip() or "Unknown"
            self._speaker_editor = None
            editor.destroy()
            self.project.assign_speaker(line_id, speaker)
            self.project.save()
            self.refresh_all()
            if self.line_tree.exists(line_id):
                self.line_tree.selection_set(line_id)
                self.line_tree.see(line_id)

        editor.bind("<<ComboboxSelected>>", lambda event_: self.after_idle(commit, event_))
        editor.bind("<Return>", commit)
        editor.bind("<Escape>", lambda _event: (setattr(self, "_speaker_editor", None), editor.destroy()))
        editor.bind("<FocusOut>", commit)
        editor.focus_set()
        editor.selection_range(0, "end")

    def refresh_pronunciations(self):
        self.pronunciation_text.delete("1.0", "end")
        if self.project:
            self.pronunciation_text.insert("1.0", "\n".join(f"{key} = {value}" for key, value in self.project.data["pronunciations"].items()))

    def reader_cache_file(self, text, voice, speed, prefix="text"):
        digest = hashlib.sha256(f"{voice}\0{float(speed):.3f}\0{text}".encode("utf-8")).hexdigest()[:24]
        folder = assistant_root() / "cache" / "narration-studio" / "text-reader"
        return folder / f"{prefix}_{voice}_{digest}.wav"

    def start_text_reader(self):
        self._start_reading_widget(self.reader_text, self.reader_status, "Text Reader")

    def start_screen_reader(self):
        self._start_reading_widget(self.screen_text, self.screen_status, "Screen Reader")

    def _start_reading_widget(self, widget, status_var, title):
        if self.busy:
            status_var.set("Please wait for the current operation to finish.")
            return
        text = widget.get("1.0", "end-1c")
        chunks = text_chunks_with_ranges(text)
        if not chunks:
            messagebox.showinfo(title, "Paste or extract some text first.")
            return
        try:
            speed = float(self.reader_speed.get())
            if not 0.5 <= speed <= 2.0:
                raise ValueError
        except (TypeError, ValueError, tk.TclError):
            messagebox.showerror(title, "Speed must be between 0.5 and 2.0.")
            return
        voice = self.reader_voice.get() or "af_sarah"
        skip_symbols = bool(self.skip_symbols.get())
        self.stop_text_reader(update_status=False)
        self.stop_playback(update_status=False)
        self.reader_cancel_event.clear()
        self._reader_widget = widget
        self._reader_status_var = status_var
        widget.configure(state="disabled")
        self.busy = True
        status_var.set(f"Preparing {len(chunks)} section(s) with {voice}…")

        def worker():
            items = []
            error = None
            try:
                for number, (start, end, spoken) in enumerate(chunks, 1):
                    if self.reader_cancel_event.is_set():
                        break
                    speech = clean_spoken_text(spoken, skip_symbols)
                    if not speech:
                        continue
                    destination = self.reader_cache_file(speech, voice, speed)
                    if not destination.is_file():
                        self.tts.synthesize(speech, destination, voice=voice, speed=speed)
                    items.append((start, end, destination))
                    self.after(0, lambda done=number, total=len(chunks):
                               status_var.set(f"Prepared {done}/{total} section(s)…"))
            except Exception as exc:
                error = exc
            self.after(0, lambda: self._reader_generation_done(error, items, widget, status_var, title))

        threading.Thread(target=worker, daemon=True).start()

    def _reader_generation_done(self, error, items, widget, status_var, title):
        self.busy = False
        if error:
            widget.configure(state="normal")
            status_var.set("Text preparation failed")
            messagebox.showerror(title, str(error))
            return
        if self.reader_cancel_event.is_set():
            widget.configure(state="normal")
            status_var.set("Reading stopped")
            return
        if not items:
            widget.configure(state="normal")
            status_var.set("No readable text remained after filtering symbols.")
            return
        self._reader_items = items
        self._reader_index = 0
        self._reader_active = True
        self._text_reader_step()

    def _text_reader_step(self):
        if not self._reader_active or self._reader_index >= len(self._reader_items):
            self._reader_active = False
            self._reader_after = None
            self._reader_widget.configure(state="normal")
            self._reader_status_var.set("Reading finished")
            return
        start, end, audio_path = self._reader_items[self._reader_index]
        try:
            winsound.PlaySound(str(audio_path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            duration_ms = max(100, round(float(sf.info(str(audio_path)).duration) * 1000))
        except Exception as exc:
            self.stop_text_reader(update_status=False)
            messagebox.showerror("Text Reader", f"Could not play {audio_path.name}:\n{exc}")
            return
        self._reader_widget.tag_remove("reading", "1.0", "end")
        first = f"1.0+{start}c"
        last = f"1.0+{end}c"
        self._reader_widget.tag_add("reading", first, last)
        self._reader_widget.see(first)
        self._reader_status_var.set(f"Reading section {self._reader_index + 1}/{len(self._reader_items)}")
        self._reader_index += 1
        self._reader_after = self.after(duration_ms + 120, self._text_reader_step)

    def stop_text_reader(self, update_status=True):
        self.reader_cancel_event.set()
        self._reader_active = False
        if self._reader_after is not None:
            try:
                self.after_cancel(self._reader_after)
            except Exception:
                pass
            self._reader_after = None
        try:
            winsound.PlaySound(None, 0)
        except RuntimeError:
            pass
        if self._reader_widget is not None:
            self._reader_widget.configure(state="normal")
        if update_status:
            (self._reader_status_var or self.reader_status).set("Reading stopped")

    def clear_text_reader(self):
        self.stop_text_reader(update_status=False)
        self.reader_text.delete("1.0", "end")
        self.reader_text.tag_remove("reading", "1.0", "end")
        self.reader_status.set("Paste text to begin.")

    def paste_reader_text(self):
        try:
            value = self.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("Text Reader", "The clipboard does not contain text.")
            return
        self.reader_text.insert("insert", value)
        self.reader_text.focus_set()
        self.reader_status.set("Clipboard text pasted")

    def screen_cache_folder(self):
        folder = assistant_root() / "cache" / "narration-studio" / "screen-reader"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def capture_screen_area(self):
        if self.busy:
            self.screen_status.set("Please wait for the current operation to finish.")
            return
        self.stop_text_reader(update_status=False)
        self.stop_playback(update_status=False)
        self.withdraw()
        self.after(180, self._show_capture_overlay)

    def _show_capture_overlay(self):
        user32 = ctypes.windll.user32
        left = int(user32.GetSystemMetrics(76))
        top = int(user32.GetSystemMetrics(77))
        width = int(user32.GetSystemMetrics(78))
        height = int(user32.GetSystemMetrics(79))
        overlay = tk.Toplevel(self)
        overlay.overrideredirect(True)
        overlay.geometry(f"{width}x{height}{left:+d}{top:+d}")
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.28)
        overlay.configure(bg="black", cursor="crosshair")
        canvas = tk.Canvas(overlay, bg="black", highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)
        canvas.create_text(width // 2, 35,
                           text="Click one corner, then click the opposite corner. Press Esc to cancel.",
                           fill="white", font=("Segoe UI", 16, "bold"), tags="instructions")
        selection = {"start": None, "rectangle": None}

        def restore():
            if overlay.winfo_exists():
                overlay.destroy()
            self.deiconify()
            self.lift()
            self.focus_force()

        def cancel(_event=None):
            restore()
            self.screen_status.set("Screen capture cancelled")

        def motion(event):
            if selection["start"] is None:
                return
            x1, y1 = selection["start"]
            if selection["rectangle"] is not None:
                canvas.delete(selection["rectangle"])
            selection["rectangle"] = canvas.create_rectangle(
                x1 - left, y1 - top, event.x, event.y, outline="#ff4040", width=4)

        def click(event):
            point = (event.x_root, event.y_root)
            if selection["start"] is None:
                selection["start"] = point
                self.screen_status.set("Select the opposite corner")
                return
            x1, y1 = selection["start"]
            x2, y2 = point
            bbox = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
            if bbox[2] - bbox[0] < 5 or bbox[3] - bbox[1] < 5:
                selection["start"] = None
                self.screen_status.set("Selection was too small; choose two corners again")
                return
            overlay.destroy()
            self.after(160, lambda: self._finish_screen_capture(bbox))

        canvas.bind("<Button-1>", click)
        canvas.bind("<Motion>", motion)
        overlay.bind("<Escape>", cancel)
        overlay.focus_force()

    def _finish_screen_capture(self, bbox):
        image = None
        error = None
        try:
            image = ImageGrab.grab(bbox=bbox, all_screens=True)
        except Exception as exc:
            error = exc
        finally:
            self.deiconify()
            self.lift()
            self.focus_force()
        if error:
            self.screen_status.set("Screen capture failed")
            messagebox.showerror("Screen Reader", str(error))
        else:
            self.set_screen_image(image)

    def paste_screen_image(self):
        try:
            value = ImageGrab.grabclipboard()
            if isinstance(value, Image.Image):
                image = value.copy()
            elif isinstance(value, list) and value:
                with Image.open(value[0]) as opened:
                    image = opened.convert("RGB").copy()
            else:
                raise ValueError("The clipboard does not contain an image.")
            self.set_screen_image(image)
        except Exception as exc:
            messagebox.showinfo("Screen Reader", str(exc))

    def set_screen_image(self, image):
        destination = self.screen_cache_folder() / f"capture_{time.time_ns()}.png"
        image.convert("RGB").save(destination, format="PNG")
        self.screen_image_path = destination
        self._screen_image = image.convert("RGB").copy()
        self.resize_screen_preview()
        self.screen_status.set("Image captured — extracting text…")
        self.after(100, self.extract_screen_text)

    def resize_screen_preview(self, _event=None):
        if self._screen_image is None:
            return
        width = max(100, self.screen_preview.winfo_width() - 16)
        height = max(100, self.screen_preview.winfo_height() - 16)
        display = self._screen_image.copy()
        display.thumbnail((width, height), Image.Resampling.LANCZOS)
        self._screen_photo = ImageTk.PhotoImage(display)
        self.screen_preview.configure(image=self._screen_photo, text="")

    def extract_screen_text(self):
        if self.busy:
            self.screen_status.set("Please wait for the current operation to finish.")
            return
        if not self.screen_image_path or not self.screen_image_path.is_file():
            messagebox.showinfo("Screen Reader", "Capture or paste an image first.")
            return
        self.busy = True
        self.screen_status.set("Reading text from the image with local OCR…")

        def worker():
            text = None
            error = None
            try:
                text = extract_image_text(self.screen_image_path)
            except Exception as exc:
                error = exc
            self.after(0, lambda: self._screen_ocr_done(text, error))

        threading.Thread(target=worker, daemon=True).start()

    def _screen_ocr_done(self, text, error):
        self.busy = False
        if error:
            self.screen_status.set("OCR failed")
            messagebox.showerror("Screen Reader", str(error))
            return
        self.screen_text.configure(state="normal")
        self.screen_text.delete("1.0", "end")
        self.screen_text.insert("1.0", text)
        self.screen_status.set("Text extracted — review it or press Read Aloud")
        if self.screen_auto_read.get():
            self.after(100, self.start_screen_reader)

    def preview_reader_voice(self, voice):
        if self.busy:
            self.reader_status.set("Please wait for the current operation to finish.")
            return
        sample = "This is what the generated text sounds like."
        self.reader_voice.set(voice)
        self.stop_text_reader(update_status=False)
        self.stop_playback(update_status=False)
        destination = self.reader_cache_file(sample, voice, 1.0, prefix="preview")
        if destination.is_file():
            self._play_voice_preview(voice, destination)
            return
        self.busy = True
        self.reader_status.set(f"Generating {voice} preview…")

        def worker():
            error = None
            try:
                self.tts.synthesize(sample, destination, voice=voice, speed=1.0)
            except Exception as exc:
                error = exc
            self.after(0, lambda: self._voice_preview_done(voice, destination, error))

        threading.Thread(target=worker, daemon=True).start()

    def _voice_preview_done(self, voice, destination, error):
        self.busy = False
        if error:
            self.reader_status.set("Voice preview failed")
            messagebox.showerror("Voice Preview", str(error))
            return
        self._play_voice_preview(voice, destination)

    def _play_voice_preview(self, voice, destination):
        try:
            winsound.PlaySound(str(destination), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            self.reader_status.set(f"Playing {voice} preview")
        except Exception as exc:
            messagebox.showerror("Voice Preview", str(exc))

    def comic_sources(self):
        if not self.project:
            return {}
        return {int(source.get("page", 1)): source for source in self.project.data.get("sources", [])
                if source.get("type") == "comic_image" and source.get("path")}

    def refresh_playback(self):
        sources = self.comic_sources()
        pages = [str(page) for page in sorted(sources)]
        self.playback_page_combo.configure(values=pages)
        if not pages:
            self.playback_page.set("")
            self._comic_image = None
            self._comic_photo = None
            self.comic_image_label.configure(image="", text="This project has no imported comic pages.")
            for item in self.playback_tree.get_children():
                self.playback_tree.delete(item)
            self.playback_status.set("Add comic pages from the Import menu.")
            return
        if self.playback_page.get() not in pages:
            self.playback_page.set(pages[0])
        self.load_playback_page(stop_audio=False)

    def load_playback_page(self, stop_audio=True):
        if stop_audio:
            self.stop_playback()
        if not self.project or not self.playback_page.get():
            return
        page = int(self.playback_page.get())
        source = self.comic_sources().get(page)
        image_path = self.project.folder / source["path"] if source else None
        try:
            if not image_path or not image_path.is_file():
                raise FileNotFoundError(image_path or "No image source")
            with Image.open(image_path) as opened:
                self._comic_image = opened.convert("RGB").copy()
            self.resize_comic_image()
        except Exception as exc:
            self._comic_image = None
            self._comic_photo = None
            self.comic_image_label.configure(image="", text=f"Could not display page {page}:\n{exc}")

        for item in self.playback_tree.get_children():
            self.playback_tree.delete(item)
        lines = [line for line in self.project.lines if int(line.get("part", 1)) == page]
        for line in lines:
            audio = self.project.folder / line.get("audio", "") if line.get("audio") else None
            status = "Ready" if audio and audio.is_file() else "Not generated"
            self.playback_tree.insert("", "end", iid=line["id"],
                                      values=(line.get("speaker", "Unknown"), line.get("text", ""), status))
        ready = sum(1 for line in lines if line.get("audio") and (self.project.folder / line["audio"]).is_file())
        self.playback_status.set(f"Page {page}: {ready}/{len(lines)} voice lines ready")

    def resize_comic_image(self, _event=None):
        if self._comic_image is None:
            return
        width = max(100, self.comic_image_label.winfo_width() - 16)
        height = max(100, self.comic_image_label.winfo_height() - 16)
        display = self._comic_image.copy()
        display.thumbnail((width, height), Image.Resampling.LANCZOS)
        self._comic_photo = ImageTk.PhotoImage(display)
        self.comic_image_label.configure(image=self._comic_photo, text="")

    def change_playback_page(self, offset):
        pages = list(self.playback_page_combo.cget("values"))
        if not pages:
            return
        current = pages.index(self.playback_page.get()) if self.playback_page.get() in pages else 0
        self.playback_page.set(pages[max(0, min(len(pages) - 1, current + offset))])
        self.load_playback_page()

    def playable_page_lines(self):
        if not self.project or not self.playback_page.get():
            return []
        page = int(self.playback_page.get())
        return [line for line in self.project.lines if int(line.get("part", 1)) == page
                and line.get("audio") and (self.project.folder / line["audio"]).is_file()]

    def play_comic_page(self):
        lines = self.playable_page_lines()
        if not lines:
            messagebox.showinfo("Comic Reader", "Generate this page's voice lines first.")
            return
        self._begin_playback(lines, 0)

    def play_selected_comic_line(self):
        selected = self.playback_tree.selection()
        if not selected:
            messagebox.showinfo("Comic Reader", "Select a generated line first.")
            return
        lines = self.playable_page_lines()
        index = next((number for number, line in enumerate(lines) if line["id"] == selected[0]), None)
        if index is None:
            messagebox.showinfo("Comic Reader", "That line has not been generated yet.")
            return
        self._begin_playback(lines, index, single=True)

    def _begin_playback(self, lines, index, single=False):
        self.stop_playback(update_status=False)
        self._playback_lines = lines[index:index + 1] if single else lines[index:]
        self._playback_index = 0
        self._playback_active = True
        self._playback_step()

    def _playback_step(self):
        if not self._playback_active or self._playback_index >= len(self._playback_lines):
            self.stop_playback(update_status=False)
            self.playback_status.set("Playback finished")
            return
        line = self._playback_lines[self._playback_index]
        audio_path = self.project.folder / line["audio"]
        try:
            winsound.PlaySound(str(audio_path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            duration_ms = max(100, round(float(sf.info(str(audio_path)).duration) * 1000))
        except Exception as exc:
            self.stop_playback(update_status=False)
            messagebox.showerror("Comic Reader", f"Could not play {audio_path.name}:\n{exc}")
            return
        self.playback_tree.selection_set(line["id"])
        self.playback_tree.focus(line["id"])
        self.playback_tree.see(line["id"])
        self.playback_status.set(f"{line.get('speaker', 'Unknown')}: {line.get('text', '')[:90]}")
        self._playback_index += 1
        gap = int(self.project.data.get("settings", {}).get("gap_ms", 250))
        self._playback_after = self.after(duration_ms + gap, self._playback_step)

    def stop_playback(self, update_status=True):
        self._playback_active = False
        if self._playback_after is not None:
            try:
                self.after_cancel(self._playback_after)
            except Exception:
                pass
            self._playback_after = None
        try:
            winsound.PlaySound(None, 0)
        except RuntimeError:
            pass
        if update_status:
            self.playback_status.set("Playback stopped")

    def paste_text(self):
        project = self.require_project()
        if not project or self.busy:
            return
        dialog = TextImportDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            text, part, use_llm = dialog.result
            self.run_background("Analysing pasted text…", self._add_text, text, part, use_llm)

    def import_documents(self):
        project = self.require_project()
        if not project or self.busy:
            return
        paths = filedialog.askopenfilenames(title="Add Documents", filetypes=[
            ("Supported documents", "*.txt *.md *.markdown *.pdf *.docx *.epub"), ("All files", "*.*")])
        if not paths:
            return
        part = simpledialog.askinteger("Starting Part", "Part number for the first document:", initialvalue=1, minvalue=1, parent=self)
        if part:
            self.run_background("Importing documents…", self._add_documents, [Path(p) for p in paths], part)

    def _add_documents(self, paths, part):
        for offset, path in enumerate(paths):
            copied = copy_source(path, self.project.folder / "sources")
            text = read_document(copied)
            self.project.data["sources"].append({"type": "document", "path": str(copied.relative_to(self.project.folder)), "part": part + offset})
            self.project.add_lines(analyze_text(text, part=part + offset, use_llm=True, cast_context=list(self.project.data["cast"])))
        self.project.save()
        self.after(0, self.refresh_all)

    def _add_text(self, text, part, use_llm):
        self.project.add_lines(analyze_text(text, part=part, use_llm=use_llm, cast_context=list(self.project.data["cast"])))
        self.project.save()
        self.after(0, self.refresh_all)

    def import_images(self):
        project = self.require_project()
        if not project or self.busy:
            return
        paths = filedialog.askopenfilenames(title="Add Comic Pages", filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp")])
        if not paths:
            return
        start = simpledialog.askinteger("Starting Page", "Page/part number for the first image:", initialvalue=1, minvalue=1, parent=self)
        if start:
            self.run_background("Analysing comic pages…", self._add_images, [Path(p) for p in paths], start)

    def _add_images(self, paths, start):
        for offset, path in enumerate(paths):
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            copied = copy_source(path, self.project.folder / "sources")
            page = start + offset
            self.project.data["sources"].append({"type": "comic_image", "path": str(copied.relative_to(self.project.folder)), "page": page})
            self.project.add_lines(analyze_comic_image(copied, page=page))
            self.project.save()
        self.after(0, self.refresh_all)

    def load_selected_line(self, _event=None):
        if not self.project or len(self.line_tree.selection()) != 1:
            return
        line = self.project.line_by_id(self.line_tree.selection()[0])
        self.edit_part.set(line["part"])
        self.edit_speaker.set(line["speaker"])
        self.edit_type.set(line["type"])
        self.edit_voice.set(line.get("voice", ""))
        self.edit_speed.set("" if line.get("speed") is None else str(line["speed"]))
        self.edit_text.delete("1.0", "end")
        self.edit_text.insert("1.0", line["text"])
        self.edit_direction.set(line.get("direction", ""))

    def apply_line_changes(self):
        if not self.project or len(self.line_tree.selection()) != 1:
            return
        line = self.project.line_by_id(self.line_tree.selection()[0])
        line.update({"part": int(self.edit_part.get()), "speaker": self.edit_speaker.get().strip() or "Unknown",
                     "type": self.edit_type.get(), "voice": self.edit_voice.get().strip(),
                     "text": self.edit_text.get("1.0", "end").strip(), "direction": self.edit_direction.get().strip(),
                     "status": "changed" if line.get("audio") else "draft"})
        speed = self.edit_speed.get().strip()
        line["speed"] = float(speed) if speed else None
        self.project.rebuild_cast()
        self.project.save()
        self.refresh_all()

    def add_blank_line(self):
        if self.project:
            self.project.add_lines([new_line("", speaker="Unknown", kind="dialogue", part=int(self.edit_part.get()))])
            self.project.save()
            self.refresh_lines()

    def delete_selected(self):
        if not self.project:
            return
        selected = set(self.line_tree.selection())
        if selected and messagebox.askyesno("Delete Lines", f"Delete {len(selected)} selected line(s)?"):
            self.project.data["lines"] = [line for line in self.project.lines if line["id"] not in selected]
            self.project.save()
            self.refresh_lines()

    def load_cast(self, _event=None):
        if not self.project or len(self.cast_tree.selection()) != 1:
            return
        speaker = self.cast_tree.selection()[0]
        data = self.project.data["cast"][speaker]
        self.cast_name.set(speaker)
        self.cast_voice.set(data.get("voice", ""))
        self.cast_speed.set(float(data.get("speed", 1.0)))
        self.cast_aliases.set(", ".join(data.get("aliases", [])))
        self.cast_notes.set(data.get("notes", ""))

    def save_cast(self):
        if not self.project:
            return
        old = self.cast_tree.selection()[0] if len(self.cast_tree.selection()) == 1 else None
        name = self.cast_name.get().strip()
        if not name:
            return
        data = {"voice": self.cast_voice.get().strip() or "af_sarah", "speed": float(self.cast_speed.get()),
                "aliases": [item.strip() for item in self.cast_aliases.get().split(",") if item.strip()],
                "notes": self.cast_notes.get().strip()}
        if old and old != name:
            self.project.data["cast"].pop(old, None)
            for line in self.project.lines:
                if line["speaker"] == old:
                    line["speaker"] = name
        self.project.data["cast"][name] = data
        self.project.save()
        self.refresh_all()

    def save_pronunciations(self):
        if not self.project:
            return
        result = {}
        for number, raw in enumerate(self.pronunciation_text.get("1.0", "end").splitlines(), 1):
            if not raw.strip():
                continue
            if "=" not in raw:
                messagebox.showerror("Pronunciations", f"Line {number} needs an equals sign.")
                return
            source, spoken = raw.split("=", 1)
            result[source.strip()] = spoken.strip()
        self.project.data["pronunciations"] = result
        self.project.save()
        self.status_var.set("Pronunciation dictionary saved")

    def generate_selected(self):
        ids = list(self.line_tree.selection())
        if not ids:
            messagebox.showinfo("Generate", "Select one or more lines in the Script tab.")
            return
        self._start_generation(ids)

    def generate_all(self):
        if self.project:
            self._start_generation(None)

    def _start_generation(self, ids):
        if not self.require_project() or self.busy:
            return
        self.cancel_event.clear()
        self.progress.configure(value=0, maximum=1)

        def progress(index, total, line):
            self.after(0, lambda: self._generation_progress(index, total, line))

        self.run_background("Generating voice lines…", self.tts.generate_lines, self.project, ids,
                            overwrite=bool(self.overwrite_var.get()), progress=progress,
                            cancelled=self.cancel_event.is_set)

    def _generation_progress(self, index, total, line):
        self.progress.configure(maximum=max(1, total), value=index)
        self.generation_label.configure(text=f"{index}/{total}: {line.get('speaker')} — {line.get('text', '')[:80]}")
        self.refresh_lines()

    def stop_work(self):
        self.cancel_event.set()
        self.reader_cancel_event.set()
        self.stop_text_reader(update_status=False)
        self.stop_playback(update_status=False)
        self.status_var.set("Stopping after the current operation…")

    def combine_part_dialog(self):
        if not self.require_project() or self.busy:
            return
        part = simpledialog.askinteger("Combine Part", "Part number:", initialvalue=1, minvalue=1, parent=self)
        if part:
            self.run_background(f"Combining part {part}…", combine_part, self.project, part)

    def export_game(self):
        if self.project:
            try:
                paths = export_dialogue(self.project, self.project.folder / "exports" / "Unity")
                self.status_var.set("Exported " + ", ".join(path.name for path in paths))
            except Exception as exc:
                messagebox.showerror("Export", str(exc))

    def export_subtitles(self):
        if self.project:
            try:
                path = export_srt(self.project, self.project.folder / "exports" / "subtitles.srt")
                self.status_var.set(f"Exported {path.name}")
            except Exception as exc:
                messagebox.showerror("Export", str(exc))

    def run_background(self, label, function, *args, **kwargs):
        if self.busy:
            return
        self.busy = True
        self.status_var.set(label)

        def worker():
            error = None
            try:
                function(*args, **kwargs)
            except Exception as exc:
                error = exc
            self.after(0, lambda: self._work_finished(error))

        threading.Thread(target=worker, daemon=True).start()

    def _work_finished(self, error):
        self.busy = False
        if error:
            self.status_var.set("Operation failed")
            messagebox.showerror("Narration Studio", str(error))
        else:
            self.status_var.set("Stopped" if self.cancel_event.is_set() else "Ready")
            self.refresh_all()

    def component_status(self):
        model, voices = kokoro_files()
        tts = "TTS ready" if model.is_file() and voices.is_file() else "TTS missing"
        self.component_var.set(f"{tts} • Ollama {ollama_url()} • Root {assistant_root()}")

    def open_project_folder(self):
        path = self.project.folder if self.project else projects_root()
        try:
            os.startfile(path)
        except Exception:
            subprocess.Popen(["explorer.exe", str(path)])

    def on_close(self):
        if self.project:
            self.project.save()
        self.cancel_event.set()
        self.reader_cancel_event.set()
        self.stop_text_reader(update_status=False)
        self.stop_playback(update_status=False)
        self.destroy()


def main():
    app = NarrationStudio()
    app.mainloop()


if __name__ == "__main__":
    main()
