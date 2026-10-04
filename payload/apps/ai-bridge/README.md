# Mellish Local AI Bridge MCP

This local stdio MCP server lets compatible clients use the contained Ollama
models and Kokoro voices. It exposes model status and second opinions, bounded
code/file audits, persistent background-job records, VRAM unloading, single WAV
generation and Unity-friendly dialogue packs. Narration Studio remains enabled
alongside it and contributes its 11 project-based narration tools.

Run `Register with Codex.cmd` after installation to add the bridge to the local
Codex configuration. When Narration Studio is installed, the script also adds
its 11 project tools as `mellish-narration`. Start a new Codex task/session
afterward; an already-open session cannot acquire newly configured tools.

File audits are limited by `config\ai-bridge.json`. Its default `allowed_roots`
contains only the Mellish installation folder. Add an absolute Unity, Blender or
other project folder manually before asking the MCP server to read it. Supplying
code directly to `review_code_text` does not require filesystem permission.

Generated files and job records are stored under `mcp-output`. Background jobs
continue only while the MCP server process remains running; unfinished jobs are
marked interrupted when it starts again.
