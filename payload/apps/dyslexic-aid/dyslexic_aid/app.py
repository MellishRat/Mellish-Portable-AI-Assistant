from __future__ import annotations

import ctypes
import hashlib
import json
import os
import threading
import time
import tkinter as tk
import winsound
from pathlib import Path
from tkinter import messagebox, ttk

import soundfile as sf
from PIL import Image, ImageGrab, ImageTk

from . import __version__
from .ocr import extract_image_text
from .paths import assistant_root, cache_folder, kokoro_files, settings_file
from .reader import clean_spoken_text, text_chunks_with_ranges
from .tts import KOKORO_VOICES, TTSEngine


def enable_per_monitor_dpi_awareness():
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


class DyslexicAid(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Mellish Dyslexic Aid {__version__}")
        self.geometry("1320x820")
        self.minsize(980, 650)
        self.tts = TTSEngine()
        self.busy = False
        self.cancel_event = threading.Event()
        self._reader_after = None
        self._reader_items = []
        self._reader_index = 0
        self._reader_widget = None
        self._reader_status = None
        self.screen_image_path: Path | None = None
        self._screen_image = None
        self._screen_photo = None
        self._load_settings()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(200, self.component_status)

    def _load_settings(self):
        data = {}
        path = settings_file()
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception:
                data = {}
        self.voice = tk.StringVar(value=str(data.get("voice", "af_sarah")))
        self.speed = tk.DoubleVar(value=float(data.get("speed", 1.0)))
        self.skip_symbols = tk.BooleanVar(value=bool(data.get("skip_symbols", False)))
        self.auto_read = tk.BooleanVar(value=bool(data.get("auto_read", False)))

    def _save_settings(self):
        settings_file().write_text(json.dumps({
            "voice": self.voice.get(), "speed": float(self.speed.get()),
            "skip_symbols": bool(self.skip_symbols.get()), "auto_read": bool(self.auto_read.get()),
        }, indent=2) + "\n", encoding="utf-8")

    def _build_ui(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        toolbar = ttk.Frame(self, padding=7)
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="Mellish Dyslexic Aid", font=("Segoe UI", 14, "bold")).pack(side="left")
        ttk.Checkbutton(toolbar, text="Skip punctuation / special characters",
                        variable=self.skip_symbols).pack(side="left", padx=(24, 6))
        ttk.Label(toolbar, text="Speed").pack(side="left", padx=(12, 4))
        ttk.Spinbox(toolbar, from_=0.5, to=2.0, increment=0.05, textvariable=self.speed, width=6).pack(side="left")
        self.component_var = tk.StringVar(value="Checking local components…")
        ttk.Label(toolbar, textvariable=self.component_var).pack(side="right")

        main = ttk.Panedwindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=7, pady=(0, 7))
        work = ttk.Frame(main)
        voices = ttk.Frame(main, padding=(10, 0, 0, 0))
        main.add(work, weight=3)
        main.add(voices, weight=2)

        self.tabs = ttk.Notebook(work)
        self.tabs.pack(fill="both", expand=True)
        self.text_tab = ttk.Frame(self.tabs, padding=8)
        self.screen_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.text_tab, text="Text Reader")
        self.tabs.add(self.screen_tab, text="Screenshot Reader")
        self._build_text_tab()
        self._build_screen_tab()
        self._build_voice_cards(voices)

        self.status = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status, padding=(8, 4)).pack(fill="x")

    def _build_text_tab(self):
        buttons = ttk.Frame(self.text_tab)
        buttons.pack(fill="x", pady=(0, 7))
        ttk.Button(buttons, text="Paste", command=self.paste_text).pack(side="left", padx=2)
        ttk.Button(buttons, text="Read Aloud", command=lambda: self.start_reading(self.text_box)).pack(side="left", padx=2)
        ttk.Button(buttons, text="Stop", command=self.stop_reading).pack(side="left", padx=2)
        ttk.Button(buttons, text="Clear", command=self.clear_text).pack(side="left", padx=2)
        self.text_box = self._text_widget(self.text_tab)

    def _build_screen_tab(self):
        buttons = ttk.Frame(self.screen_tab)
        buttons.pack(fill="x", pady=(0, 7))
        ttk.Button(buttons, text="Capture Screen Area", command=self.capture_screen_area).pack(side="left", padx=2)
        ttk.Button(buttons, text="Paste Image", command=self.paste_image).pack(side="left", padx=2)
        ttk.Button(buttons, text="Extract Text", command=self.extract_text).pack(side="left", padx=2)
        ttk.Button(buttons, text="Read Aloud", command=lambda: self.start_reading(self.screen_text)).pack(side="left", padx=(12, 2))
        ttk.Button(buttons, text="Stop", command=self.stop_reading).pack(side="left", padx=2)
        ttk.Checkbutton(buttons, text="Read automatically after OCR", variable=self.auto_read).pack(side="left", padx=10)
        pane = ttk.Panedwindow(self.screen_tab, orient="vertical")
        pane.pack(fill="both", expand=True)
        preview = ttk.LabelFrame(pane, text="Captured Image", padding=5)
        extracted = ttk.LabelFrame(pane, text="Extracted Text", padding=5)
        pane.add(preview, weight=3)
        pane.add(extracted, weight=2)
        self.screen_preview = ttk.Label(preview, text="No screenshot captured", anchor="center")
        self.screen_preview.pack(fill="both", expand=True)
        self.screen_preview.bind("<Configure>", self.resize_preview)
        self.screen_text = self._text_widget(extracted)

    def _text_widget(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        widget = tk.Text(frame, wrap="word", undo=True, font=("Segoe UI", 12), padx=11, pady=10)
        widget.tag_configure("reading", background="#ffe08a", foreground="#111111")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
        widget.configure(yscrollcommand=scroll.set)
        widget.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return widget

    def _build_voice_cards(self, parent):
        ttk.Label(parent, text="Choose a Voice", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(parent, text="Preview: “This is what the generated text sounds like.”",
                  wraplength=430).pack(anchor="w", pady=(2, 7))
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(frame, highlightthickness=0)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        cards = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=cards, anchor="nw")
        cards.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        for index, voice in enumerate(KOKORO_VOICES):
            card = ttk.LabelFrame(cards, text=self.voice_description(voice), padding=6)
            card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=3, pady=3)
            ttk.Radiobutton(card, text=voice, variable=self.voice, value=voice).pack(side="left", fill="x", expand=True)
            ttk.Button(card, text="Preview", command=lambda value=voice: self.preview_voice(value)).pack(side="right", padx=(5, 0))
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)

    @staticmethod
    def voice_description(voice):
        accent = {"a": "American", "b": "British"}.get(voice[:1], "")
        gender = {"f": "female", "m": "male"}.get(voice[1:2], "voice")
        return f"{voice.split('_', 1)[-1].title()} — {accent} {gender}".strip()

    def audio_cache_file(self, text, voice, speed, prefix="text"):
        digest = hashlib.sha256(f"{voice}\0{float(speed):.3f}\0{text}".encode("utf-8")).hexdigest()[:24]
        return cache_folder("audio") / f"{prefix}_{voice}_{digest}.wav"

    def paste_text(self):
        try:
            value = self.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("Dyslexic Aid", "The clipboard does not contain text.")
            return
        self.text_box.insert("insert", value)
        self.text_box.focus_set()
        self.status.set("Clipboard text pasted")

    def clear_text(self):
        self.stop_reading(update_status=False)
        self.text_box.delete("1.0", "end")
        self.text_box.tag_remove("reading", "1.0", "end")
        self.status.set("Text cleared")

    def start_reading(self, widget):
        if self.busy:
            self.status.set("Please wait for the current operation to finish.")
            return
        source = widget.get("1.0", "end-1c")
        chunks = text_chunks_with_ranges(source)
        if not chunks:
            messagebox.showinfo("Dyslexic Aid", "Paste or extract some text first.")
            return
        try:
            speed = float(self.speed.get())
            if not 0.5 <= speed <= 2.0:
                raise ValueError
        except (TypeError, ValueError, tk.TclError):
            messagebox.showerror("Dyslexic Aid", "Speed must be between 0.5 and 2.0.")
            return
        voice = self.voice.get() or "af_sarah"
        skip = bool(self.skip_symbols.get())
        self.stop_reading(update_status=False)
        self.cancel_event.clear()
        self._reader_widget = widget
        self._reader_status = self.status
        widget.configure(state="disabled")
        self.busy = True
        self.status.set(f"Preparing {len(chunks)} sentence(s) with {voice}…")

        def worker():
            items, error = [], None
            try:
                for number, (start, end, spoken) in enumerate(chunks, 1):
                    if self.cancel_event.is_set():
                        break
                    speech = clean_spoken_text(spoken, skip)
                    if not speech:
                        continue
                    path = self.audio_cache_file(speech, voice, speed)
                    if not path.is_file():
                        self.tts.synthesize(speech, path, voice=voice, speed=speed)
                    items.append((start, end, path))
                    self.after(0, lambda done=number, total=len(chunks):
                               self.status.set(f"Prepared {done}/{total} sentence(s)…"))
            except Exception as exc:
                error = exc
            self.after(0, lambda: self._generation_done(error, items, widget))

        threading.Thread(target=worker, daemon=True).start()

    def _generation_done(self, error, items, widget):
        self.busy = False
        if error:
            widget.configure(state="normal")
            self.status.set("Speech preparation failed")
            messagebox.showerror("Dyslexic Aid", str(error))
            return
        if self.cancel_event.is_set():
            widget.configure(state="normal")
            self.status.set("Reading stopped")
            return
        if not items:
            widget.configure(state="normal")
            self.status.set("No readable text remained after filtering symbols")
            return
        self._reader_items = items
        self._reader_index = 0
        self._play_next()

    def _play_next(self):
        if self.cancel_event.is_set() or self._reader_index >= len(self._reader_items):
            self._reader_after = None
            self._reader_widget.configure(state="normal")
            self.status.set("Reading finished" if not self.cancel_event.is_set() else "Reading stopped")
            return
        start, end, path = self._reader_items[self._reader_index]
        try:
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            duration = max(100, round(float(sf.info(str(path)).duration) * 1000))
        except Exception as exc:
            self.stop_reading(update_status=False)
            messagebox.showerror("Dyslexic Aid", f"Could not play {path.name}:\n{exc}")
            return
        self._reader_widget.tag_remove("reading", "1.0", "end")
        first, last = f"1.0+{start}c", f"1.0+{end}c"
        self._reader_widget.tag_add("reading", first, last)
        self._reader_widget.see(first)
        self.status.set(f"Reading sentence {self._reader_index + 1}/{len(self._reader_items)}")
        self._reader_index += 1
        self._reader_after = self.after(duration + 120, self._play_next)

    def stop_reading(self, update_status=True):
        self.cancel_event.set()
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
            self.status.set("Reading stopped")

    def preview_voice(self, voice):
        if self.busy:
            self.status.set("Please wait for the current operation to finish.")
            return
        self.stop_reading(update_status=False)
        self.voice.set(voice)
        sample = "This is what the generated text sounds like."
        path = self.audio_cache_file(sample, voice, 1.0, prefix="preview")
        if path.is_file():
            self._play_preview(voice, path)
            return
        self.busy = True
        self.status.set(f"Generating {voice} preview…")

        def worker():
            error = None
            try:
                self.tts.synthesize(sample, path, voice=voice, speed=1.0)
            except Exception as exc:
                error = exc
            self.after(0, lambda: self._preview_done(voice, path, error))

        threading.Thread(target=worker, daemon=True).start()

    def _preview_done(self, voice, path, error):
        self.busy = False
        if error:
            self.status.set("Voice preview failed")
            messagebox.showerror("Voice Preview", str(error))
        else:
            self._play_preview(voice, path)

    def _play_preview(self, voice, path):
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        self.status.set(f"Playing {voice} preview")

    def capture_screen_area(self):
        if self.busy:
            self.status.set("Please wait for the current operation to finish.")
            return
        self.stop_reading(update_status=False)
        self.withdraw()
        self.after(180, self._show_capture_overlay)

    def _show_capture_overlay(self):
        user32 = ctypes.windll.user32
        left, top = int(user32.GetSystemMetrics(76)), int(user32.GetSystemMetrics(77))
        width, height = int(user32.GetSystemMetrics(78)), int(user32.GetSystemMetrics(79))
        overlay = tk.Toplevel(self)
        overlay.overrideredirect(True)
        overlay.geometry(f"{width}x{height}{left:+d}{top:+d}")
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.28)
        canvas = tk.Canvas(overlay, bg="black", highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)
        canvas.create_text(width // 2, 35, text="Click one corner, then the opposite corner. Esc cancels.",
                           fill="white", font=("Segoe UI", 16, "bold"))
        state = {"start": None, "rectangle": None}

        def restore():
            if overlay.winfo_exists():
                overlay.destroy()
            self.deiconify()
            self.lift()
            self.focus_force()

        def cancel(_event=None):
            restore()
            self.status.set("Screen capture cancelled")

        def motion(event):
            if state["start"] is None:
                return
            if state["rectangle"] is not None:
                canvas.delete(state["rectangle"])
            x1, y1 = state["start"]
            state["rectangle"] = canvas.create_rectangle(
                x1 - left, y1 - top, event.x, event.y, outline="#ff4040", width=4)

        def click(event):
            point = (event.x_root, event.y_root)
            if state["start"] is None:
                state["start"] = point
                return
            x1, y1 = state["start"]
            x2, y2 = point
            bbox = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
            if bbox[2] - bbox[0] < 5 or bbox[3] - bbox[1] < 5:
                state["start"] = None
                self.status.set("Selection was too small; choose two corners again")
                return
            overlay.destroy()
            self.after(160, lambda: self._finish_capture(bbox))

        canvas.bind("<Button-1>", click)
        canvas.bind("<Motion>", motion)
        overlay.bind("<Escape>", cancel)
        overlay.focus_force()

    def _finish_capture(self, bbox):
        image, error = None, None
        try:
            image = ImageGrab.grab(bbox=bbox, all_screens=True)
        except Exception as exc:
            error = exc
        self.deiconify()
        self.lift()
        self.focus_force()
        if error:
            messagebox.showerror("Screenshot Reader", str(error))
        else:
            self.set_screen_image(image)

    def paste_image(self):
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
            messagebox.showinfo("Screenshot Reader", str(exc))

    def set_screen_image(self, image):
        path = cache_folder("screenshots") / f"capture_{time.time_ns()}.png"
        image.convert("RGB").save(path, format="PNG")
        self.screen_image_path = path
        self._screen_image = image.convert("RGB").copy()
        self.resize_preview()
        self.status.set("Image ready — extracting text locally…")
        self.tabs.select(self.screen_tab)
        self.after(100, self.extract_text)

    def resize_preview(self, _event=None):
        if self._screen_image is None:
            return
        width = max(100, self.screen_preview.winfo_width() - 16)
        height = max(100, self.screen_preview.winfo_height() - 16)
        display = self._screen_image.copy()
        display.thumbnail((width, height), Image.Resampling.LANCZOS)
        self._screen_photo = ImageTk.PhotoImage(display)
        self.screen_preview.configure(image=self._screen_photo, text="")

    def extract_text(self):
        if self.busy:
            self.status.set("Please wait for the current operation to finish.")
            return
        if not self.screen_image_path or not self.screen_image_path.is_file():
            messagebox.showinfo("Screenshot Reader", "Capture or paste an image first.")
            return
        self.busy = True
        self.status.set("Extracting text with local OCR…")

        def worker():
            text, error = None, None
            try:
                text = extract_image_text(self.screen_image_path)
            except Exception as exc:
                error = exc
            self.after(0, lambda: self._ocr_done(text, error))

        threading.Thread(target=worker, daemon=True).start()

    def _ocr_done(self, text, error):
        self.busy = False
        if error:
            self.status.set("OCR failed")
            messagebox.showerror("Screenshot Reader", str(error))
            return
        self.screen_text.configure(state="normal")
        self.screen_text.delete("1.0", "end")
        self.screen_text.insert("1.0", text)
        self.status.set("Text extracted — review it or press Read Aloud")
        if self.auto_read.get():
            self.after(100, lambda: self.start_reading(self.screen_text))

    def component_status(self):
        model, voices = kokoro_files()
        voice_status = "Voices ready" if model.is_file() and voices.is_file() else "Voice files missing"
        self.component_var.set(f"{voice_status} • DPI {DPI_AWARENESS_MODE} • Root {assistant_root()}")

    def on_close(self):
        self.stop_reading(update_status=False)
        self._save_settings()
        self.destroy()


def main():
    app = DyslexicAid()
    app.mainloop()


if __name__ == "__main__":
    main()

