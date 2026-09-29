# Mellish Portable AI Assistant

A small Windows bootstrap installer for a private, local AI assistant. The ZIP
contains no model weights and no personal data. On first run it detects the PC,
lets the user choose an installation folder and model set, and downloads every
runtime, model and optional voice component into that folder.

## For friends who just want to install it

1. Download the latest `Mellish-Portable-AI-Assistant-Bootstrap.zip` from the
   repository's **Releases** page.
2. Extract the ZIP completely.
3. Double-click **Install Portable Assistant.bat**.
4. Choose a folder on a drive with enough free space.
5. Keep the recommended models or change the selection, then click **Install**.
6. Launch with the generated **Start Assistant.bat** or Desktop shortcut.

Open **USER GUIDE.html** for a visual model-selection guide, model-routing
explanations, voice and Project Knowledge instructions, and the current MCP/tool
limitations. The installed app also has a **User Guide** button.

The installer can be run again through **Repair or Add Models.bat** to repair
dependencies or add another model. Interrupted Ollama model downloads resume.

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
- Dedicated loopback port `11437`, avoiding conflicts with a normal Ollama app.
- Portable launch, console, repair and diagnostics batch files.
- Optional Desktop and Start Menu shortcuts.

## Important expectations

- Windows 10/11 x64 is required.
- A recent NVIDIA driver is the only normal machine-level prerequisite for
  NVIDIA acceleration. AMD/CPU operation depends on Ollama's supported backend.
- The bootstrap itself is small, but selected downloads range from roughly 3 GB
  for a minimal installation to more than 40 GB for every option.
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

## Maintainer workflow

Run `build_release.ps1` to create the small release ZIP and checksum under
`dist/`. The script audits the staging list so runtime state cannot enter the
archive. Tagging a version such as `v0.2.1` runs the GitHub release workflow.

Run `tests\Validate-Bootstrap.ps1`; add `-IncludeRuntime` for a real extraction,
pip/Tkinter verification and repeated-repair test. Add `-IncludeDependencies`
to install and isolate-check both core and voice requirements. The remaining
clean-machine cases are listed in
[docs/PORTABILITY_TEST_MATRIX.md](docs/PORTABILITY_TEST_MATRIX.md).

Before publishing publicly, review [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)
and choose a source-code licence. No model licence is transferred by this repo.
