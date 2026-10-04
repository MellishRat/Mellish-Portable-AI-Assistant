from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import __version__
from .analyzer import analyze_comic_image, analyze_text
from .exporters import export_dialogue, export_srt
from .importers import IMAGE_EXTENSIONS, copy_source, read_document
from .paths import assistant_root, kokoro_files, ollama_url, projects_root
from .project import NarrationProject, new_line, safe_slug
from .tts import KOKORO_VOICES, TTSEngine, combine_part


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
        self.cast_tab = ttk.Frame(self.tabs)
        self.export_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.script_tab, text="Script")
        self.tabs.add(self.cast_tab, text="Cast & Pronunciation")
        self.tabs.add(self.export_tab, text="Generate & Export")
        self._build_script_tab()
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

        fields = ttk.Frame(editor)
        fields.pack(fill="x")
        self.edit_part = tk.IntVar(value=1)
        self.edit_speaker = tk.StringVar()
        self.edit_type = tk.StringVar()
        self.edit_voice = tk.StringVar()
        self.edit_speed = tk.StringVar()
        for index, (label, widget) in enumerate((
            ("Part", ttk.Spinbox(fields, from_=1, to=9999, textvariable=self.edit_part, width=7)),
            ("Speaker", ttk.Entry(fields, textvariable=self.edit_speaker, width=22)),
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

    def refresh_pronunciations(self):
        self.pronunciation_text.delete("1.0", "end")
        if self.project:
            self.pronunciation_text.insert("1.0", "\n".join(f"{key} = {value}" for key, value in self.project.data["pronunciations"].items()))

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
        self.destroy()


def main():
    app = NarrationStudio()
    app.mainloop()


if __name__ == "__main__":
    main()
