# Mellish Portable AI Assistant

A friendly Windows bootstrap for running private AI tools on your own computer.
Choose the programs you want, choose a folder, and the bootstrap downloads the
contained Python runtime, Ollama, models and voice components for you. It does
not require an existing Python installation and does not add Python to PATH.

> **Current platform:** Windows 10/11 x64. An NVIDIA GPU with 8–12 GB VRAM is
> recommended for the larger models, although small models and CPU operation
> are available.

## Download

Download **Mellish-Portable-AI-Assistant-Bootstrap.zip** from the
[latest GitHub release](https://github.com/MellishRat/Mellish-Portable-AI-Assistant/releases/latest).
The ZIP is deliberately small: models and runtimes are downloaded only after
you choose them in setup.

## Which program should I choose?

| Program | Best for | Focused installation includes |
| --- | --- | --- |
| **Local AI Assistant** | General chat, writing, coding, image understanding, saved conversations and MCP tools | Selected chat/vision/coding models; optional microphone transcription and spoken replies |
| **Narration Studio** | Audiobooks, comics, multiple characters, voice-line production and Unity/VRChat dialogue | Text/vision/OCR models, document importers, Kokoro voices and narration MCP tools |
| **Dyslexic Aid** | Reading pasted text or text captured from the screen | GLM-OCR, Kokoro voices, sentence highlighting and only its required packages |

Install one program or any combination. Changing a program checkbox
automatically recalculates its required models. Shared components are installed
once and reused. Leaving an existing program unticked during a later repair does
**not** uninstall it or delete its data.

## Quick installation

1. Download the latest `Mellish-Portable-AI-Assistant-Bootstrap.zip` from the
   repository's **Releases** page.
2. Extract the ZIP completely.
3. Double-click **Install Portable Assistant.bat**.
4. Choose a folder on a drive with enough free space.
5. Choose one or more programs: Local AI Assistant, Narration Studio, or the
   focused Dyslexic Aid text/screenshot reader.
6. Keep the recommended models or change the selection, then click **Install**.
7. Launch with the generated program batch file or Desktop shortcut.

Windows may show a SmartScreen warning because the bootstrap is not
code-signed. Use **More info → Run anyway** only if the download came from this
repository and its SHA-256 matches the value attached to the release.

Open **USER GUIDE.html** for a visual model-selection guide, model-routing
explanations, voice and Project Knowledge instructions, and the current MCP/tool
limitations. The installed app also has a **User Guide** button.

The installer can be run again through **Repair or Add Models.bat** to repair
dependencies, add a program, or add another model. It reuses a verified
contained Python runtime, installed packages, Ollama runtime, models and voice
caches. Unticking a program does not uninstall it or delete its data, and
interrupted Ollama model downloads resume.

## What the bootstrap handles

- Hardware detection for NVIDIA GPU/VRAM, total RAM and 64-bit Windows.
- Hardware-based model recommendations with download sizes shown before setup.
- A low-spec unrestricted Qwen 1.7B option and an experimental 248 MB Bonsai
  1.7B option for older computers.
- The 9B general/vision, 14B coding, 12B creative, OCR and BGE-M3 models used by
  the full assistant, plus optional Bonsai 27B.
- A pinned Python 3.11 `python-build-standalone` install-only runtime, extracted
  directly under the selected folder with pip, Tkinter/Tcl and the standard
  library included.
- A pinned standalone Ollama runtime whose official SHA-256 checksum is verified.
- Optional faster-whisper speech recognition and Kokoro text-to-speech.
- Optional Mellish Narration Studio for accessible books/comics, editable
  multi-speaker narration, audiobook parts, and Unity/VRChat voice-line exports.
- Optional Mellish Dyslexic Aid for large pasted text and two-click screenshot
  reading, sentence highlighting, OCR and selectable offline Kokoro voices.
- Eleven Narration Studio MCP tools for project inspection, speaker correction,
  cast voices, generation, part combination and export.
- Dedicated loopback port `11437`, avoiding conflicts with a normal Ollama app.
- Portable launch, console, repair and diagnostics batch files.
- Optional Desktop and Start Menu shortcuts.
- Named conversations with automatic history, resume, rename and JSON export.
- An MCP 2.x client for local stdio/Streamable HTTP tools, per-action approval,
  and a bundled Unity Python bridge.
- A Mellish Local AI Bridge MCP server with 13 tools for local-model second
  opinions, bounded code audits, background jobs, VRAM unloading, WAV voice
  lines and Unity-friendly dialogue packs. Narration Studio adds another 11
  project-oriented voice tools.

## Connecting the local tools to Codex

After installing the Local AI Assistant, run **Register AI Bridge with
Codex.bat** from the installation folder. It uses the supported `codex mcp add`
command to register the contained Python executable and MCP server. Start a new
Codex task/session afterward; an already-running task cannot gain newly added
tools.

The bridge reads files only below roots listed in `config\ai-bridge.json`. The
Mellish installation folder is the sole default. Add a Unity, Blender or other
project folder there before requesting a file audit. Generated audio, dialogue
manifests and persistent job records are written beneath `mcp-output`.

## Important expectations

- Windows 10/11 x64 is required.
- A recent NVIDIA driver is the only normal machine-level prerequisite for
  NVIDIA acceleration. AMD/CPU operation depends on Ollama's supported backend.
- The bootstrap itself is small, but selected downloads range from roughly 3 GB
  for a minimal installation to more than 40 GB for every option.
- Installation time depends heavily on the selected models and internet speed.
- Image analysis and OCR are supported. Local image generation is intentionally
  not bundled because its storage and VRAM cost did not justify the output
  quality for this package.
- MCP support requires the matching Blender, GIMP or Unity connector to be
  installed and running in the target application.
- `uncensored`, `unrestricted`, `abliterated` and `HERETIC` are claims made by
  community model publishers. They reduce refusals but are not guarantees about
  every response or an endorsement of model output.
- Bonsai 1.7B and Bonsai 27B are not abliterated. They are optional experiments.

## Standalone Python runtime

The bootstrap does not run the normal python.org Windows installer. It pins the
Windows x86-64 `python-build-standalone` CPython 3.11.9 install-only archive from
release `20240814` and verifies its SHA-256 before extraction. The archive is
normalized so the interpreter is always `runtime\python\python.exe`, then the
installer immediately verifies `sys`, `pip` and `tkinter` with that exact file.

Dependencies are installed only through `runtime\python\python.exe -m pip`.
Mellish does not request PATH changes, file associations, the Python launcher,
Windows Installer registration or an existing system Python. An incomplete
runtime is replaced using a staged extraction and rollback backup; a verified
runtime is reused on repair runs.

`python-build-standalone` is maintained by Astral and packages CPython plus
third-party components. The extracted distribution includes its license files
and component licensing metadata. Review those notices and the upstream
project before redistribution:
https://github.com/astral-sh/python-build-standalone

The last selected destination is stored beside the extracted bootstrap so a
retry does not silently return to `%LOCALAPPDATA%`. The installed repair batch
always supplies its own containing directory explicitly.

## Security and privacy

Downloads use HTTPS. The pinned standalone Python archive is checked against
the SHA-256 recorded in the manifest. The Ollama ZIP is checked against the
SHA-256 file published with its pinned GitHub release. Model weights are
downloaded by Ollama from their listed publishers and are not redistributed in
this repository.

After installation, prompts and inference remain on the local PC. The assistant
binds to `127.0.0.1`; it is not exposed to the local network by default.

Personal chats, settings, recordings, caches, model weights and API credentials
are excluded by `.gitignore` and must never be committed.

## Repairing or adding features later

Run **Repair or Add Models.bat** from the selected installation folder. Repair
remembers that exact folder and reuses valid Python, packages, Ollama model
layers, Kokoro voices, Whisper files and Hugging Face caches. It downloads or
repairs only components that are missing or selected for addition.

If the whole folder is copied to another compatible PC, run the repair tool to
redetect the GPU and recreate shortcuts. NVIDIA drivers, microphone permission
and working audio devices remain machine-specific.

## Troubleshooting

- Fully extract the bootstrap ZIP before running it.
- Use a folder such as `C:\LocalAI` or `D:\Mellish AI`, rather than a drive root.
- Leave enough free space for both model downloads and temporary extraction.
- Run **Run Diagnostics.bat** inside the installation folder when reporting a
  problem.
- The release ZIP contains no models, conversations, credentials or personal
  data, so the same bootstrap ZIP can be passed to another person.

## Maintainer workflow

Run `build_release.ps1` to create the small release ZIP and checksum under
`dist/`. The script audits the staging list so runtime state cannot enter the
archive. Tagging a version such as `v0.5.1` runs the GitHub release workflow.

Target applications still need their own MCP add-on. See
[docs/MCP_SETUP.md](docs/MCP_SETUP.md) for Unity, Blender and GIMP setup,
connector trust boundaries, and local-model limitations.

Run `tests\Validate-Bootstrap.ps1`; add `-IncludeRuntime` for a real extraction,
pip/Tkinter verification and repeated-repair test. Add `-IncludeDependencies`
to install and isolate-check both core and voice requirements. The remaining
clean-machine cases are listed in
[docs/PORTABILITY_TEST_MATRIX.md](docs/PORTABILITY_TEST_MATRIX.md).

Before publishing a release, review
[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md). No model licence is transferred by
this repository. Unless a source file states otherwise, no open-source licence
is currently granted for this repository's original code.
