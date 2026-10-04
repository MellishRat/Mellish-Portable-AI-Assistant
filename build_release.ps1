[CmdletBinding()]
param([string]$Version = '0.4.0')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$dist = Join-Path $root 'dist'
$scratch = Join-Path ([IO.Path]::GetTempPath()) ('Mellish-Portable-AI-Assistant-' + [guid]::NewGuid().ToString('N'))
$staging = Join-Path $scratch 'Mellish-Portable-AI-Assistant-Bootstrap'
$archive = Join-Path $dist 'Mellish-Portable-AI-Assistant-Bootstrap.zip'

$required = @(
    'Install Portable Assistant.bat',
    'USER GUIDE.html',
    'README.md',
    'RELEASE_CHECKLIST.md',
    'installer\Install-PortableAssistant.ps1',
    'installer\manifest.json',
    'payload\QwenChat.py',
    'payload\requirements-core.txt',
    'payload\requirements-voice.txt',
    'payload\tools\bootstrap_voice_models.py',
    'payload\tools\diagnostics.py',
    'payload\tools\__init__.py',
    'payload\tools\chat_store.py',
    'payload\tools\mcp_client.py',
    'payload\apps\narration-studio\run_app.py',
    'payload\apps\narration-studio\run_mcp.py',
    'payload\apps\narration-studio\requirements-documents.txt',
    'payload\apps\narration-studio\Start Narration Studio.cmd',
    'payload\apps\narration-studio\Start Narration Studio (Console).cmd',
    'payload\apps\narration-studio\README.txt',
    'payload\apps\narration-studio\LICENSE',
    'payload\apps\narration-studio\THIRD_PARTY_NOTICES.txt',
    'payload\apps\narration-studio\narration_studio\__init__.py',
    'payload\apps\narration-studio\narration_studio\analyzer.py',
    'payload\apps\narration-studio\narration_studio\app.py',
    'payload\apps\narration-studio\narration_studio\exporters.py',
    'payload\apps\narration-studio\narration_studio\importers.py',
    'payload\apps\narration-studio\narration_studio\mcp_server.py',
    'payload\apps\narration-studio\narration_studio\merge_mcp.py',
    'payload\apps\narration-studio\narration_studio\paths.py',
    'payload\apps\narration-studio\narration_studio\project.py',
    'payload\apps\narration-studio\narration_studio\reader.py',
    'payload\apps\narration-studio\narration_studio\tts.py',
    'payload\apps\dyslexic-aid\run_app.py',
    'payload\apps\dyslexic-aid\requirements.txt',
    'payload\apps\dyslexic-aid\Start Dyslexic Aid.cmd',
    'payload\apps\dyslexic-aid\README.txt',
    'payload\apps\dyslexic-aid\README.md',
    'payload\apps\dyslexic-aid\LICENSE',
    'payload\apps\dyslexic-aid\THIRD_PARTY_NOTICES.txt',
    'payload\apps\dyslexic-aid\dyslexic_aid\__init__.py',
    'payload\apps\dyslexic-aid\dyslexic_aid\app.py',
    'payload\apps\dyslexic-aid\dyslexic_aid\ocr.py',
    'payload\apps\dyslexic-aid\dyslexic_aid\paths.py',
    'payload\apps\dyslexic-aid\dyslexic_aid\reader.py',
    'payload\apps\dyslexic-aid\dyslexic_aid\tts.py',
    'docs\MODELS.md',
    'docs\PORTABILITY_TEST_MATRIX.md',
    'docs\USER_GUIDE.md',
    'docs\QUICK_MODEL_GUIDE.svg',
    'docs\MCP_SETUP.md'
)

foreach ($relative in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $relative))) {
        throw "Release input is missing: $relative"
    }
}

if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
New-Item -ItemType Directory -Force -Path $dist, $staging | Out-Null

foreach ($relative in $required) {
    $source = Join-Path $root $relative
    $destination = Join-Path $staging $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

$forbidden = @('settings.json', 'install-manifest.json', '*.gguf', '*.bin', '*.onnx', '*.npz', '*.pyc')
foreach ($pattern in $forbidden) {
    $found = @(Get-ChildItem -LiteralPath $staging -Recurse -File -Filter $pattern -ErrorAction SilentlyContinue)
    if ($found) { throw "Forbidden runtime/personal file entered release staging: $($found[0].FullName)" }
}

Compress-Archive -LiteralPath $staging -DestinationPath $archive -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath (Join-Path $dist 'SHA256SUMS.txt') -Value "$hash  $(Split-Path -Leaf $archive)" -Encoding ASCII
if (Test-Path -LiteralPath $scratch) {
    $resolvedScratch = [IO.Path]::GetFullPath($scratch)
    if ((Split-Path -Leaf $resolvedScratch) -notlike 'Mellish-Portable-AI-Assistant-*') { throw "Unsafe cleanup path: $resolvedScratch" }
    Remove-Item -LiteralPath $resolvedScratch -Recurse -Force
}
Write-Output "Built version $Version"
Write-Output $archive
Write-Output "SHA256 $hash"
