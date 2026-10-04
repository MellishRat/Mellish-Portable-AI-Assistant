# MCP application setup

## Mellish Local AI Bridge

Installing the Local AI Assistant also installs `apps\ai-bridge`. Run
`Register AI Bridge with Codex.bat` from the installation root to register two
local stdio servers when available:

- `mellish-ai`: 13 tools for installed-model status, second opinions, bounded
  file/code audits, persistent background jobs, VRAM unloading, individual WAV
  generation and Unity-ready dialogue packs.
- `mellish-narration`: Narration Studio's 11 project, cast, generation, combine
  and export tools. This entry is added only when Narration Studio is installed.

The registration uses the contained `runtime\python\python.exe`; it does not use
system Python or PATH. Start a new Codex task/session after registration.

`audit_local_files` can read only paths below `allowed_roots` in
`config\ai-bridge.json`. The installation root is the only default. Add project
roots deliberately and do not add broad locations such as an entire system
drive. Direct text supplied to `review_code_text` does not require path access.
Generated artifacts and job records remain beneath `mcp-output`.

Mellish 0.3 includes an MCP client. It discovers tools from enabled MCP
servers, gives their schemas to Ollama, and returns tool results to the
conversation. **Every proposed tool call requires separate confirmation.**

The client supports local `stdio` servers and Streamable HTTP endpoints. Server
definitions live in `config\mcp_servers.json`. The default file is created on
first launch with disabled Unity, Blender and GIMP templates. Open it from
**MCP Tools > Open Config**, enable only the connector you intend to use, save,
then press **Refresh Tools**.

## Unity

Portable requirements include `unity-mcp-server` 1.0.11. Unity still needs the
matching Editor package:

1. In Unity, open **Window > Package Manager**.
2. Choose **+ > Add package from git URL**.
3. Enter `https://github.com/mzbswh/unity-mcp.git?path=unity-mcp`.
4. Open **Window > Unity MCP**, confirm port `51279`, and start the server.
5. Enable `unity` in `mcp_servers.json`, then refresh tools.

The template launches
`runtime\python\Scripts\unity-mcp-server.exe`; it needs no system Python, PATH
entry or `uvx`. Unity 2021.2+ is required by this connector. Upstream:
<https://github.com/mzbswh/unity-mcp>

## Blender

Blender needs both a Blender-side add-on and its matching MCP server. They are
not bundled because connectors differ in Blender version support and security.

For Blender 5.1+, Blender publishes an experimental Lab guide:
<https://www.blender.org/lab/mcp-server/>. Install its add-on/server and put the
resulting stdio command in the `blender` template. For a Streamable HTTP bridge:

```json
"blender": {
  "enabled": true,
  "transport": "streamable-http",
  "url": "http://127.0.0.1:PORT/mcp"
}
```

Blender's Lab page warns that its bridge can execute generated Python without
guards. Work on copies/backups and inspect every approval.

## GIMP

The configuration template targets community connector `maorcc/gimp-mcp`,
which currently requires GIMP 3.2+: <https://github.com/maorcc/gimp-mcp>

1. Clone/unpack it into `integrations\gimp-mcp` inside the Mellish folder.
2. Install its dependencies into a contained environment under that folder,
   following its upstream instructions.
3. Copy `gimp-mcp-plugin.py` into GIMP's current per-user plug-in folder.
4. In GIMP, open an image and choose **Tools > MCP > Start MCP Server**. Its
   GIMP-side bridge listens on localhost port `9877`.
5. Point the `gimp` command at the contained connector runner, enable it, and
   refresh tools.

GIMP integration is community software, not an official GIMP component. Keep
its version and dependencies isolated under `integrations\gimp-mcp`.

## How a request runs

1. Enable **Allow connected MCP tools**.
2. Select **Game Development and Coding** for Unity/Blender scripting work.
3. Ask for one specific, verifiable action.
4. The model may propose a named tool and arguments.
5. Mellish displays those arguments. Approve only if they are safe.
6. The connector runs the tool and returns its result to the model.

Local models vary in structured tool-call reliability. Qwen Coder is the first
model to try, but it can still choose the wrong tool or arguments. Confident
text is not proof an application changed. Check the target app and keep source
control/backups.

This initial client passes text and structured results back to Ollama. Binary
image/audio blocks are identified but omitted from model context; attach an
exported screenshot in Chat when the model needs visual review.
