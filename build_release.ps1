[CmdletBinding()]
param([string]$Version = '0.2.1')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$dist = Join-Path $root 'dist'
$staging = Join-Path $dist 'Mellish-Portable-AI-Assistant-Bootstrap'
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
    'docs\MODELS.md',
    'docs\PORTABILITY_TEST_MATRIX.md',
    'docs\USER_GUIDE.md',
    'docs\QUICK_MODEL_GUIDE.svg'
)

foreach ($relative in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $relative))) {
        throw "Release input is missing: $relative"
    }
}

if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
New-Item -ItemType Directory -Force -Path $staging | Out-Null

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
Write-Output "Built version $Version"
Write-Output $archive
Write-Output "SHA256 $hash"
