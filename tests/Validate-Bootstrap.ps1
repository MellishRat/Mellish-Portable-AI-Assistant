[CmdletBinding()]
param(
    [switch]$IncludeRuntime,
    [switch]$IncludeDependencies,
    [string]$RuntimeTestRoot = "$env:TEMP\Mellish Portable Runtime Test"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$installer = Join-Path $root 'installer\Install-PortableAssistant.ps1'
$manifestPath = Join-Path $root 'installer\manifest.json'
$launcher = Join-Path $root 'Install Portable Assistant.bat'
$powershell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

$tokens = $null
$errors = $null
[void][Management.Automation.Language.Parser]::ParseFile($installer, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | ForEach-Object Message | Out-String) }

$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.python.url -notmatch 'python-build-standalone/.+/cpython-3\.11\..+-x86_64-pc-windows-msvc-install_only\.tar\.gz$') {
    throw 'Manifest does not pin a Windows x86-64 python-build-standalone install_only archive.'
}
if ($manifest.python.sha256 -notmatch '^[a-fA-F0-9]{64}$') { throw 'Standalone Python SHA-256 is missing or invalid.' }

$source = Get-Content -LiteralPath $installer -Raw -Encoding UTF8
$obsolete = @(
    'python.org/ftp', 'InstallAllUsers', 'Include_pip', 'TargetDir=',
    'Get-AuthenticodeSignature', 'Algorithm MD5', 'SetEnvironmentVariable',
    'reg.exe', 'assoc.exe', 'ftype.exe'
)
foreach ($term in $obsolete) {
    if ($source.Contains($term)) { throw "Obsolete registered-Python installer logic remains: $term" }
}
foreach ($required in @(
    "'-m', 'pip'", "import sys, pip, tkinter", '-InstallPath "%~dp0"',
    "`$env:PYTHONNOUSERSITE = '1'", "`$env:PIP_USER = 'false'"
)) {
    if (-not $source.Contains($required)) { throw "Required portability behavior is missing: $required" }
}

if (-not (Test-Path -LiteralPath $launcher)) { throw 'Bootstrap launcher is missing.' }
$dryRunPaths = @('C:\Mellish Portability Test', 'D:\Changed Mellish Destination')
foreach ($path in $dryRunPaths) {
    & $powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File $installer -NoGui -DryRun -InstallPath $path -ModelIds small-uncensored | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Dry run failed for destination: $path" }
}
$dyslexicDryRun = & $powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File $installer -NoGui -DryRun -InstallPath 'C:\Mellish Dyslexic Aid Test' -WithoutLocalAssistant -WithDyslexicAid -ModelIds ocr | ConvertFrom-Json
if (-not $dyslexicDryRun.DyslexicAid -or $dyslexicDryRun.LocalAssistant -or -not $dyslexicDryRun.Voice) {
    throw 'Dyslexic Aid-only dry run did not select the expected program and voice components.'
}
$dyslexicPayload = Join-Path $root 'payload\apps\dyslexic-aid\run_app.py'
if (-not (Test-Path -LiteralPath $dyslexicPayload)) { throw 'Dyslexic Aid payload is missing.' }
if (-not $source.Contains("'--tts-only'")) { throw 'Dyslexic Aid-only installation is not using the focused TTS dependency path.' }
$narrationDryRun = & $powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File $installer -NoGui -DryRun -InstallPath 'C:\Mellish Narration Only Test' -WithoutLocalAssistant -WithNarrationStudio -ModelIds general | ConvertFrom-Json
if (-not $narrationDryRun.NarrationStudio -or $narrationDryRun.LocalAssistant -or -not $narrationDryRun.Voice) {
    throw 'Narration Studio-only dry run did not select the expected program and voice components.'
}

if ($IncludeRuntime) {
    & $powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File $installer -RuntimeSmokeTest -InstallPath $RuntimeTestRoot
    if ($LASTEXITCODE -ne 0) { throw 'Standalone runtime smoke test failed.' }
    & $powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File $installer -RuntimeSmokeTest -InstallPath $RuntimeTestRoot
    if ($LASTEXITCODE -ne 0) { throw 'Repeated standalone runtime smoke test failed.' }
}

if ($IncludeDependencies) {
    if (-not $IncludeRuntime) { throw '-IncludeDependencies requires -IncludeRuntime.' }
    $python = Join-Path $RuntimeTestRoot 'runtime\python\python.exe'
    $env:PYTHONNOUSERSITE = '1'
    $env:PIP_USER = 'false'
    $env:PIP_CACHE_DIR = Join-Path $RuntimeTestRoot 'cache\pip'
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    foreach ($requirements in @('requirements-core.txt', 'requirements-voice.txt')) {
        & $python -m pip install --disable-pip-version-check --no-warn-script-location -r (Join-Path $root "payload\$requirements")
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed: $requirements" }
    }
    $imports = 'import site,sys,pip,tkinter,numpy,PIL,faster_whisper,kokoro_onnx,sounddevice,soundfile; assert not site.ENABLE_USER_SITE; modules=(pip,numpy,PIL,faster_whisper,kokoro_onnx,sounddevice,soundfile); assert all(m.__file__.lower().startswith(sys.prefix.lower()) for m in modules); print(sys.executable)'
    & $python -s -c $imports
    if ($LASTEXITCODE -ne 0) { throw 'Isolated core/voice import validation failed.' }
}

Write-Output 'BOOTSTRAP_VALIDATION_OK'
