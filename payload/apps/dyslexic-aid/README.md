# Mellish Dyslexic Aid

A focused, entirely local Windows reading aid. It installs inside Mellish
Portable AI Assistant and reuses the contained Python runtime, Kokoro voices,
Ollama, GLM-OCR and model/cache folders without duplicating them.

## Features

- Paste large amounts of text and read them aloud sentence by sentence.
- Highlight the current sentence while it is spoken.
- Select from 28 visible Kokoro voice cards and cache spoken previews.
- Adjustable speed and optional punctuation/special-character filtering.
- DPI-correct two-click screen-area capture on scaled or mixed-monitor desktops.
- Paste screenshots directly from the clipboard.
- Local GLM-OCR transcription with Qwen Vision fallback when installed.
- Editable extracted text and optional automatic read-aloud after OCR.
- Settings, screenshots and generated audio remain under the selected Mellish root.

The easiest installation method is the Mellish Portable AI Assistant bootstrap:
select **Mellish Dyslexic Aid**. The installer automatically includes the
contained voice runtime, Kokoro files, Ollama and GLM-OCR model.

Run `Start Dyslexic Aid.cmd` from `apps\dyslexic-aid` after installation.

Windows 10/11 x64 is required. OCR quality depends on image clarity and may need
manual correction. Sentence highlighting is synchronized to generated WAV
durations; it does not provide per-word timestamps.

