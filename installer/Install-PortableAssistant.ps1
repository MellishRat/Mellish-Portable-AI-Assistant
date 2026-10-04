[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$NoGui,
    [string]$InstallPath,
    [string[]]$ModelIds,
    [switch]$WithVoice,
    [switch]$WithNarrationStudio,
    [switch]$NoShortcuts,
    [switch]$GuiSmokeTest,
    [switch]$RuntimeSmokeTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptRoot
$PayloadRoot = Join-Path $RepoRoot 'payload'
$ManifestPath = Join-Path $ScriptRoot 'manifest.json'
$SelectionStatePath = Join-Path $ScriptRoot 'last-install-path.txt'
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$script:LogControl = $null
$script:ProgressBar = $null
$script:StatusLabel = $null

function Get-SavedInstallPath {
    if (-not (Test-Path -LiteralPath $SelectionStatePath)) { return $null }
    try {
        $saved = (Get-Content -LiteralPath $SelectionStatePath -Raw -Encoding UTF8).Trim()
        if ([string]::IsNullOrWhiteSpace($saved)) { return $null }
        return [IO.Path]::GetFullPath($saved)
    } catch {
        return $null
    }
}

function Save-InstallPath {
    param([string]$Path)
    Set-Content -LiteralPath $SelectionStatePath -Value $Path -Encoding UTF8
}

function Set-PortableProcessEnvironment {
    param([string]$Root)
    $env:PYTHONNOUSERSITE = '1'
    $env:PIP_USER = 'false'
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    $env:PIP_CACHE_DIR = Join-Path $Root 'cache\pip'
    $env:HF_HOME = Join-Path $Root 'cache\huggingface'
    $env:HUGGINGFACE_HUB_CACHE = Join-Path $Root 'cache\huggingface\hub'
    $env:TRANSFORMERS_CACHE = Join-Path $Root 'cache\huggingface\transformers'
    $env:XDG_CACHE_HOME = Join-Path $Root 'cache'
    $env:TORCH_HOME = Join-Path $Root 'cache\torch'
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
}

function Add-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $Message
    Write-Host $line
    if ($script:LogControl) {
        $script:LogControl.AppendText($line + [Environment]::NewLine)
        $script:LogControl.SelectionStart = $script:LogControl.TextLength
        $script:LogControl.ScrollToCaret()
        [System.Windows.Forms.Application]::DoEvents()
    }
}

function Set-InstallerStatus {
    param([string]$Text, [int]$Percent = -1)
    if ($script:StatusLabel) { $script:StatusLabel.Text = $Text }
    if ($script:ProgressBar) {
        if ($Percent -lt 0) {
            $script:ProgressBar.Style = 'Marquee'
        } else {
            $script:ProgressBar.Style = 'Continuous'
            $script:ProgressBar.Value = [Math]::Max(0, [Math]::Min(100, $Percent))
        }
    }
    if (-not $NoGui -and -not $RuntimeSmokeTest) { [System.Windows.Forms.Application]::DoEvents() }
}

function Get-HardwareInfo {
    $computer = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
    if (-not $computer) { $computer = Get-WmiObject Win32_ComputerSystem -ErrorAction SilentlyContinue }
    $ramBytes = if ($computer) { $computer.TotalPhysicalMemory } else { 0 }
    $ramGB = if ($ramBytes) { [Math]::Round($ramBytes / 1GB, 1) } else { 0 }
    $gpuNames = @()
    try {
        $gpuNames = @(Get-CimInstance Win32_VideoController | ForEach-Object Name | Where-Object { $_ })
    } catch {
        try { $gpuNames = @(Get-WmiObject Win32_VideoController | ForEach-Object Name | Where-Object { $_ }) } catch {}
    }
    $nvidiaName = $null
    $vramGB = 0
    $driver = $null
    $nvidiaSmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if ($nvidiaSmi) {
        try {
            $row = & $nvidiaSmi.Source --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null | Select-Object -First 1
            if ($row) {
                $parts = $row -split ',' | ForEach-Object Trim
                $nvidiaName = $parts[0]
                $vramGB = [Math]::Round(([double]$parts[1]) / 1024, 1)
                $driver = $parts[2]
            }
        } catch {}
    }
    [pscustomobject]@{
        RamGB = $ramGB
        GpuNames = $gpuNames
        NvidiaName = $nvidiaName
        VramGB = $vramGB
        NvidiaDriver = $driver
        Is64Bit = [Environment]::Is64BitOperatingSystem
        WindowsVersion = [Environment]::OSVersion.VersionString
    }
}

function Get-Recommendation {
    param($Hardware)
    if (-not $Hardware.Is64Bit) { return @() }
    if ($Hardware.RamGB -lt 12 -or $Hardware.VramGB -lt 4) {
        return @('small-uncensored', 'bonsai-small')
    }
    if ($Hardware.VramGB -lt 8 -or $Hardware.RamGB -lt 24) {
        return @('small-uncensored', 'general', 'ocr')
    }
    if ($Hardware.VramGB -lt 12) {
        return @('general', 'vision', 'creative', 'ocr', 'knowledge')
    }
    return @('general', 'vision', 'coder', 'creative', 'ocr', 'knowledge')
}

function Test-InstallerInputs {
    param([string]$Target, [object[]]$SelectedModels)
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'This release requires 64-bit Windows 10 or 11.'
    }
    if ([string]::IsNullOrWhiteSpace($Target)) { throw 'Choose an installation folder.' }
    $full = [IO.Path]::GetFullPath($Target)
    if ($full -eq [IO.Path]::GetPathRoot($full)) { throw 'Choose a folder on the drive, not the drive root itself.' }
    if (-not $SelectedModels -or $SelectedModels.Count -eq 0) { throw 'Select at least one chat model.' }
    if (-not ($SelectedModels | Where-Object kind -eq 'chat')) {
        throw 'Select at least one chat model. OCR, vision and project-search models cannot replace the main chatbot.'
    }
    foreach ($url in @($Manifest.python.url, $Manifest.ollama.url, $Manifest.ollama.checksumUrl)) {
        $uri = [Uri]$url
        if ($uri.Scheme -ne 'https') { throw "Refusing non-HTTPS download URL: $url" }
    }
    return $full.TrimEnd('\')
}

function Download-VerifiedFile {
    param([string]$Url, [string]$Destination, [string]$DisplayName)
    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    if (Test-Path -LiteralPath $Destination) {
        Add-Log "Using existing download: $DisplayName"
        return
    }
    Add-Log "Downloading $DisplayName"
    Set-InstallerStatus "Downloading $DisplayName..." -1
    try {
        Import-Module BitsTransfer -ErrorAction Stop
        $job = Start-BitsTransfer -Source $Url -Destination $Destination -DisplayName "Mellish AI: $DisplayName" -Asynchronous
        try {
            while ($job.JobState -in @('Connecting', 'Transferring', 'Queued', 'TransientError')) {
                if ($job.JobState -eq 'TransientError') { Start-Sleep -Seconds 3 } else { Start-Sleep -Milliseconds 400 }
                $job = Get-BitsTransfer -Id $job.Id
                if ($job.BytesTotal -gt 0) {
                    $pct = [int](100 * $job.BytesTransferred / $job.BytesTotal)
                    Set-InstallerStatus "Downloading $DisplayName - $pct%" $pct
                }
            }
            if ($job.JobState -ne 'Transferred') { throw "BITS download failed: $($job.JobState) $($job.ErrorDescription)" }
            Complete-BitsTransfer -BitsJob $job
        } catch {
            Remove-BitsTransfer -BitsJob $job -Confirm:$false -ErrorAction SilentlyContinue
            throw
        }
    } catch {
        Add-Log "BITS was unavailable; using the standard Windows downloader."
        Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
    }
    if (-not (Test-Path -LiteralPath $Destination)) { throw "Download did not create $Destination" }
}

function Quote-ProcessArgument {
    param([string]$Value)
    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + ($Value -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"'
}

function Invoke-ProcessCapture {
    param([string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory)
    $psi = [Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $FilePath
    $psi.Arguments = (($Arguments | ForEach-Object { Quote-ProcessArgument $_ }) -join ' ')
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $psi
    try {
        if (-not $process.Start()) { throw 'Process.Start returned false.' }
    } catch {
        return [pscustomobject]@{ ExitCode = -1; StdOut = ''; StdErr = $_.Exception.Message; Command = "$FilePath $($psi.Arguments)" }
    }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    while (-not $process.HasExited) {
        if (-not $NoGui -and -not $RuntimeSmokeTest) { [System.Windows.Forms.Application]::DoEvents() }
        Start-Sleep -Milliseconds 200
    }
    $stdout = $stdoutTask.Result
    $stderr = $stderrTask.Result
    return [pscustomobject]@{ ExitCode = $process.ExitCode; StdOut = $stdout; StdErr = $stderr; Command = "$FilePath $($psi.Arguments)" }
}

function Invoke-ProcessChecked {
    param([string]$FilePath, [string[]]$Arguments, [string]$Description, [string]$WorkingDirectory)
    Add-Log $Description
    Set-InstallerStatus $Description -1
    $result = Invoke-ProcessCapture $FilePath $Arguments $WorkingDirectory
    if ($result.ExitCode -ne 0) {
        throw "$Description failed with exit code $($result.ExitCode).`n$($result.StdErr)`n$($result.StdOut)"
    }
    if ($result.StdOut.Trim()) { Add-Log (($result.StdOut.Trim() -split "`r?`n" | Select-Object -Last 1) -join '') }
}

function Test-PythonRuntime {
    param([string]$PythonExe)
    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        return [pscustomobject]@{ Valid = $false; ExitCode = -1; StdOut = ''; StdErr = "Executable does not exist: $PythonExe" }
    }
    $code = 'import sys, pip, tkinter; print(sys.executable)'
    $result = Invoke-ProcessCapture $PythonExe @('-c', $code) (Split-Path -Parent $PythonExe)
    return [pscustomobject]@{
        Valid = ($result.ExitCode -eq 0)
        ExitCode = $result.ExitCode
        StdOut = $result.StdOut
        StdErr = $result.StdErr
    }
}

function Get-ExtractionLayout {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return '<extraction directory does not exist>' }
    $items = @(Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue | Select-Object -First 80)
    if (-not $items) { return '<extraction directory is empty>' }
    return (($items | ForEach-Object { $_.FullName.Substring($Path.Length).TrimStart('\') }) -join "`n")
}

function New-PythonRuntimeFailure {
    param([string]$PythonExe, [string]$LayoutRoot, $Verification)
    $layout = Get-ExtractionLayout $LayoutRoot
    return @"
Standalone Python verification failed.
Executable: $PythonExe
Archive URL: $($Manifest.python.url)
Expected SHA-256: $($Manifest.python.sha256)
Extraction layout (first 80 entries):
$layout
Exit code: $($Verification.ExitCode)
Standard output:
$($Verification.StdOut)
Standard error:
$($Verification.StdErr)
"@
}

function Install-PythonRuntime {
    param([string]$Root, [string]$Downloads)
    $runtimeDir = Join-Path $Root 'runtime'
    $pythonDir = Join-Path $runtimeDir 'python'
    $pythonExe = Join-Path $pythonDir 'python.exe'
    $existing = Test-PythonRuntime $pythonExe
    if ($existing.Valid) {
        Add-Log "Reusing verified standalone Python: $pythonExe"
        return $pythonExe
    }
    if (Test-Path -LiteralPath $pythonDir) {
        Add-Log "Existing Python runtime is incomplete and will be replaced: $($existing.StdErr)"
    }

    New-Item -ItemType Directory -Force -Path $runtimeDir, $Downloads | Out-Null
    $archive = Join-Path $Downloads $Manifest.python.archiveName
    $expectedHash = $Manifest.python.sha256.ToLowerInvariant()
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        if (Test-Path -LiteralPath $archive) {
            $currentHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($currentHash -ne $expectedHash) {
                Add-Log "Discarding incomplete or invalid standalone Python archive (SHA-256 $currentHash)."
                Remove-Item -LiteralPath $archive -Force
            }
        }
        if (-not (Test-Path -LiteralPath $archive)) {
            Download-VerifiedFile $Manifest.python.url $archive "standalone Python $($Manifest.python.version)"
        }
        $actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -eq $expectedHash) { break }
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
        if ($attempt -eq 2) {
            throw "Standalone Python archive SHA-256 mismatch after retry. URL: $($Manifest.python.url) Expected: $expectedHash Actual: $actualHash"
        }
    }

    $stageRoot = Join-Path $runtimeDir ('.python-stage-' + [Guid]::NewGuid().ToString('N'))
    $backupDir = Join-Path $runtimeDir ('.python-backup-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stageRoot | Out-Null
    try {
        $tarExe = Join-Path $env:SystemRoot 'System32\tar.exe'
        if (-not (Test-Path -LiteralPath $tarExe)) { throw "Windows tar.exe is required but was not found at $tarExe" }
        $extract = Invoke-ProcessCapture $tarExe @('-xzf', $archive, '-C', $stageRoot) $Downloads
        if ($extract.ExitCode -ne 0) {
            $failed = [pscustomobject]@{ ExitCode = $extract.ExitCode; StdOut = $extract.StdOut; StdErr = $extract.StdErr }
            throw (New-PythonRuntimeFailure '<not extracted>' $stageRoot $failed)
        }

        $candidate = @(Get-ChildItem -LiteralPath $stageRoot -Filter python.exe -Recurse -File | Where-Object {
            (Test-Path -LiteralPath (Join-Path $_.DirectoryName 'Lib')) -and
            (Test-Path -LiteralPath (Join-Path $_.DirectoryName 'tcl'))
        }) | Select-Object -First 1
        if (-not $candidate) {
            $failed = [pscustomobject]@{ ExitCode = -1; StdOut = ''; StdErr = 'No python.exe with adjacent Lib and tcl directories was found.' }
            throw (New-PythonRuntimeFailure '<not found>' $stageRoot $failed)
        }
        $candidateDir = $candidate.DirectoryName
        $candidateCheck = Test-PythonRuntime $candidate.FullName
        if (-not $candidateCheck.Valid) { throw (New-PythonRuntimeFailure $candidate.FullName $stageRoot $candidateCheck) }

        if (Test-Path -LiteralPath $pythonDir) { Move-Item -LiteralPath $pythonDir -Destination $backupDir }
        try {
            Move-Item -LiteralPath $candidateDir -Destination $pythonDir
            $installedCheck = Test-PythonRuntime $pythonExe
            if (-not $installedCheck.Valid) { throw (New-PythonRuntimeFailure $pythonExe $pythonDir $installedCheck) }
        } catch {
            if (Test-Path -LiteralPath $pythonDir) { Remove-Item -LiteralPath $pythonDir -Recurse -Force }
            if (Test-Path -LiteralPath $backupDir) { Move-Item -LiteralPath $backupDir -Destination $pythonDir }
            throw
        }
        if (Test-Path -LiteralPath $backupDir) { Remove-Item -LiteralPath $backupDir -Recurse -Force }
        Add-Log "Standalone Python verified: $($installedCheck.StdOut.Trim())"
        return $pythonExe
    } finally {
        if (Test-Path -LiteralPath $stageRoot) { Remove-Item -LiteralPath $stageRoot -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

function Install-OllamaRuntime {
    param([string]$Root, [string]$Downloads)
    $ollamaDir = Join-Path $Root 'ollama'
    $ollamaExe = Join-Path $ollamaDir 'ollama.exe'
    if (Test-Path -LiteralPath $ollamaExe) {
        Add-Log 'Portable Ollama is already installed.'
        return $ollamaExe
    }
    $archive = Join-Path $Downloads $Manifest.ollama.archiveName
    $checksumFile = Join-Path $Downloads 'ollama-sha256sum.txt'
    Download-VerifiedFile $Manifest.ollama.url $archive "Ollama $($Manifest.ollama.version)"
    Download-VerifiedFile $Manifest.ollama.checksumUrl $checksumFile 'Ollama checksum list'
    $line = Get-Content -LiteralPath $checksumFile | Where-Object { $_ -match [regex]::Escape($Manifest.ollama.archiveName) } | Select-Object -First 1
    if (-not $line -or $line -notmatch '^([a-fA-F0-9]{64})\s+') { throw 'The official Ollama checksum list did not contain the Windows archive.' }
    $expected = $Matches[1].ToLowerInvariant()
    $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw 'Ollama archive checksum did not match the official release.' }
    New-Item -ItemType Directory -Force -Path $ollamaDir | Out-Null
    Set-InstallerStatus 'Extracting Ollama...' -1
    Expand-Archive -LiteralPath $archive -DestinationPath $ollamaDir -Force
    if (-not (Test-Path -LiteralPath $ollamaExe)) { throw 'Ollama extraction completed but ollama.exe is missing.' }
    return $ollamaExe
}

function Copy-AppPayload {
    param([string]$Root)
    Add-Log 'Copying the assistant application...'
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    Copy-Item -Path (Join-Path $PayloadRoot '*') -Destination $Root -Recurse -Force
    $targetInstaller = Join-Path $Root 'installer'
    New-Item -ItemType Directory -Force -Path $targetInstaller | Out-Null
    Copy-Item -Path (Join-Path $ScriptRoot '*') -Destination $targetInstaller -Recurse -Force
    $guide = Join-Path $RepoRoot 'USER GUIDE.html'
    if (Test-Path -LiteralPath $guide) { Copy-Item -LiteralPath $guide -Destination $Root -Force }
    $docsSource = Join-Path $RepoRoot 'docs'
    if (Test-Path -LiteralPath $docsSource) {
        $targetDocs = Join-Path $Root 'docs'
        New-Item -ItemType Directory -Force -Path $targetDocs | Out-Null
        Copy-Item -Path (Join-Path $docsSource '*') -Destination $targetDocs -Recurse -Force
    }
}

function Write-LaunchFiles {
    param([string]$Root, [int]$Port)
    $start = @"
@echo off
setlocal
cd /d "%~dp0"
set "HF_HOME=%~dp0cache\huggingface"
set "HUGGINGFACE_HUB_CACHE=%~dp0cache\huggingface\hub"
set "TRANSFORMERS_CACHE=%~dp0cache\huggingface\transformers"
set "XDG_CACHE_HOME=%~dp0cache"
set "TORCH_HOME=%~dp0cache\torch"
set "PIP_CACHE_DIR=%~dp0cache\pip"
set "PYTHONNOUSERSITE=1"
set "OLLAMA_MODELS=%~dp0models"
set "OLLAMA_HOST=127.0.0.1:$Port"
set "MELLISH_OLLAMA_HOST=127.0.0.1:$Port"
set "OLLAMA_KEEP_ALIVE=-1"
start "Mellish Portable AI Assistant" /d "%~dp0" "%~dp0runtime\python\pythonw.exe" "%~dp0QwenChat.py"
"@
    $console = @"
@echo off
setlocal
cd /d "%~dp0"
set "HF_HOME=%~dp0cache\huggingface"
set "HUGGINGFACE_HUB_CACHE=%~dp0cache\huggingface\hub"
set "TRANSFORMERS_CACHE=%~dp0cache\huggingface\transformers"
set "XDG_CACHE_HOME=%~dp0cache"
set "TORCH_HOME=%~dp0cache\torch"
set "PIP_CACHE_DIR=%~dp0cache\pip"
set "PYTHONNOUSERSITE=1"
set "OLLAMA_MODELS=%~dp0models"
set "OLLAMA_HOST=127.0.0.1:$Port"
set "MELLISH_OLLAMA_HOST=127.0.0.1:$Port"
set "OLLAMA_KEEP_ALIVE=-1"
"%~dp0runtime\python\python.exe" "%~dp0QwenChat.py"
if errorlevel 1 pause
"@
    $repair = @"
@echo off
setlocal
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\Install-PortableAssistant.ps1" -InstallPath "%~dp0"
if errorlevel 1 pause
"@
    $diagnostics = @"
@echo off
setlocal
cd /d "%~dp0"
set "OLLAMA_MODELS=%~dp0models"
set "OLLAMA_HOST=127.0.0.1:$Port"
set "MELLISH_OLLAMA_HOST=127.0.0.1:$Port"
"%~dp0runtime\python\python.exe" "%~dp0tools\diagnostics.py"
pause
"@
    Set-Content -LiteralPath (Join-Path $Root 'Start Assistant.bat') -Value $start -Encoding ASCII
    Set-Content -LiteralPath (Join-Path $Root 'Start Assistant (Console).bat') -Value $console -Encoding ASCII
    Set-Content -LiteralPath (Join-Path $Root 'Repair or Add Models.bat') -Value $repair -Encoding ASCII
    Set-Content -LiteralPath (Join-Path $Root 'Run Diagnostics.bat') -Value $diagnostics -Encoding ASCII
}

function Write-InstallConfiguration {
    param([string]$Root, [object[]]$SelectedModels, [bool]$Voice, [bool]$NarrationStudio, $Hardware)
    $chatModels = @($SelectedModels | Where-Object kind -eq 'chat')
    $preferred = @('general', 'small-uncensored', 'bonsai-small', 'creative', 'coder')
    $default = $null
    foreach ($id in $preferred) {
        $default = $chatModels | Where-Object id -eq $id | Select-Object -First 1
        if ($default) { break }
    }
    if (-not $default) { $default = $chatModels[0] }
    $configDir = Join-Path $Root 'config'
    New-Item -ItemType Directory -Force -Path $configDir | Out-Null
    $settingsPath = Join-Path $configDir 'settings.json'
    if (-not (Test-Path -LiteralPath $settingsPath)) {
        @{
            model = $default.ollama
            assistant_profile = 'Custom'
            system_prompt = 'You are a helpful private local AI assistant. Give clear, practical answers and follow the user''s requested tone.'
            context = if ($Hardware.VramGB -ge 12) { 16384 } else { 8192 }
            temperature = 0.7
            theme = 'dark'
            tts_enabled = $false
        } | ConvertTo-Json | Set-Content -LiteralPath $settingsPath -Encoding UTF8
    }
    @{
        schemaVersion = 1
        installedAt = (Get-Date).ToString('o')
        appVersion = $Manifest.appVersion
        portablePort = $Manifest.portablePort
        voiceInstalled = $Voice
        narrationStudioInstalled = $NarrationStudio
        hardware = $Hardware
        models = @($SelectedModels | Select-Object id, name, ollama, sizeGB, kind, uncensoredClaim)
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $configDir 'install-manifest.json') -Encoding UTF8
}

function Start-PortableOllama {
    param([string]$Root, [string]$OllamaExe, [int]$Port)
    $env:OLLAMA_MODELS = Join-Path $Root 'models'
    $env:OLLAMA_HOST = "127.0.0.1:$Port"
    $env:MELLISH_OLLAMA_HOST = "127.0.0.1:$Port"
    $env:OLLAMA_KEEP_ALIVE = '-1'
    New-Item -ItemType Directory -Force -Path $env:OLLAMA_MODELS | Out-Null
    $uri = "http://127.0.0.1:$Port/api/tags"
    try {
        Invoke-RestMethod -Uri $uri -TimeoutSec 2 | Out-Null
        Add-Log "Portable Ollama is already running on port $Port."
        return $null
    } catch {}
    $process = Start-Process -FilePath $OllamaExe -ArgumentList 'serve' -WorkingDirectory (Split-Path $OllamaExe) -WindowStyle Hidden -PassThru
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            Invoke-RestMethod -Uri $uri -TimeoutSec 2 | Out-Null
            Add-Log "Portable Ollama started on port $Port."
            return $process
        } catch {}
        if ($process.HasExited) { throw "Ollama exited during startup with code $($process.ExitCode)." }
    }
    throw 'Portable Ollama did not become ready within 30 seconds.'
}

function Add-Shortcuts {
    param([string]$Root, [bool]$DesktopShortcut)
    if (-not $DesktopShortcut) { return }
    $shell = New-Object -ComObject WScript.Shell
    $targets = @(
        (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Mellish Portable AI Assistant.lnk'),
        (Join-Path ([Environment]::GetFolderPath('Programs')) 'Mellish Portable AI Assistant.lnk')
    )
    foreach ($shortcutPath in $targets) {
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = Join-Path $Root 'Start Assistant.bat'
        $shortcut.WorkingDirectory = $Root
        $shortcut.Description = 'Launch the private local AI assistant'
        $shortcut.Save()
    }
}

function Invoke-Installation {
    param([string]$Target, [object[]]$SelectedModels, [bool]$Voice, [bool]$NarrationStudio, [bool]$Shortcuts, $Hardware)
    $Target = Test-InstallerInputs $Target $SelectedModels
    if ($NarrationStudio) { $Voice = $true }
    if (-not $DryRun) {
        Save-InstallPath $Target
        Set-PortableProcessEnvironment $Target
    }
    $requiredGB = 3.5 + (($SelectedModels | Measure-Object sizeGB -Sum).Sum) + $(if ($Voice) { 1.2 } else { 0.2 }) + $(if ($NarrationStudio) { 0.1 } else { 0 })
    $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($Target))
    if (($drive.AvailableFreeSpace / 1GB) -lt ($requiredGB + 3)) {
        throw ("Not enough free space. Selected components need about {0:N1} GB plus working space; {1:N1} GB is free." -f $requiredGB, ($drive.AvailableFreeSpace / 1GB))
    }
    if ($DryRun) {
        [pscustomobject]@{ InstallPath = $Target; RequiredGB = [Math]::Round($requiredGB, 1); Hardware = $Hardware; Models = $SelectedModels; Voice = $Voice; NarrationStudio = $NarrationStudio } | ConvertTo-Json -Depth 6
        return
    }
    $downloads = Join-Path $Target 'downloads'
    New-Item -ItemType Directory -Force -Path $downloads | Out-Null
    Copy-AppPayload $Target
    $narrationPath = Join-Path $Target 'apps\narration-studio'
    if (-not $NarrationStudio -and (Test-Path -LiteralPath $narrationPath)) {
        Remove-Item -LiteralPath $narrationPath -Recurse -Force
    }
    Write-LaunchFiles $Target ([int]$Manifest.portablePort)
    $python = Install-PythonRuntime $Target $downloads
    Invoke-ProcessChecked $python @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-warn-script-location', '-r', (Join-Path $Target 'requirements-core.txt')) 'Installing core Python packages...' $Target
    if ($Voice) {
        Invoke-ProcessChecked $python @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-warn-script-location', '-r', (Join-Path $Target 'requirements-voice.txt')) 'Installing local voice packages...' $Target
        Invoke-ProcessChecked $python @((Join-Path $Target 'tools\bootstrap_voice_models.py')) 'Downloading local speech models...' $Target
    }
    if ($NarrationStudio) {
        Invoke-ProcessChecked $python @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-warn-script-location', '-r', (Join-Path $Target 'apps\narration-studio\requirements-documents.txt')) 'Installing Narration Studio document importers...' $Target
        Invoke-ProcessChecked $python @('-m', 'py_compile', (Join-Path $Target 'apps\narration-studio\run_app.py'), (Join-Path $Target 'apps\narration-studio\narration_studio\app.py'), (Join-Path $Target 'apps\narration-studio\narration_studio\mcp_server.py')) 'Checking Narration Studio...' $Target
        $mcpConfig = Join-Path $Target 'config\mcp_servers.json'
        Invoke-ProcessChecked $python @((Join-Path $Target 'apps\narration-studio\narration_studio\merge_mcp.py'), '--config', $mcpConfig) 'Registering Narration Studio MCP tools...' $Target
    }
    $ollama = Install-OllamaRuntime $Target $downloads
    $server = Start-PortableOllama $Target $ollama ([int]$Manifest.portablePort)
    try {
        $index = 0
        foreach ($model in $SelectedModels) {
            $index++
            Set-InstallerStatus ("Downloading model {0} of {1}: {2}" -f $index, $SelectedModels.Count, $model.name) ([int](100 * ($index - 1) / $SelectedModels.Count))
            Invoke-ProcessChecked $ollama @('pull', $model.ollama) "Downloading $($model.name)..." $Target
        }
    } finally {
        if ($server -and -not $server.HasExited) {
            Stop-Process -Id $server.Id -ErrorAction SilentlyContinue
            Wait-Process -Id $server.Id -Timeout 10 -ErrorAction SilentlyContinue
        }
    }
    Write-InstallConfiguration $Target $SelectedModels $Voice $NarrationStudio $Hardware
    Add-Shortcuts $Target $Shortcuts
    Remove-Item -LiteralPath $downloads -Recurse -Force -ErrorAction SilentlyContinue
    Set-InstallerStatus 'Installation complete.' 100
    Add-Log "Installation complete: $Target"
}

$hardware = Get-HardwareInfo
$recommendedIds = @(Get-Recommendation $hardware)

if ($RuntimeSmokeTest) {
    if (-not $InstallPath) { throw '-RuntimeSmokeTest requires -InstallPath.' }
    $runtimeRoot = [IO.Path]::GetFullPath($InstallPath).TrimEnd('\')
    if ($runtimeRoot -eq [IO.Path]::GetPathRoot($runtimeRoot)) { throw 'Runtime smoke-test path cannot be a drive root.' }
    $runtimeDownloads = Join-Path $runtimeRoot 'downloads'
    New-Item -ItemType Directory -Force -Path $runtimeDownloads | Out-Null
    Set-PortableProcessEnvironment $runtimeRoot
    $verifiedPython = Install-PythonRuntime $runtimeRoot $runtimeDownloads
    Write-Output "RUNTIME_SMOKE_TEST_OK=$verifiedPython"
    exit 0
}

if ($NoGui) {
    if (-not $InstallPath) {
        $InstallPath = Get-SavedInstallPath
        if (-not $InstallPath) { $InstallPath = Join-Path $env:LOCALAPPDATA 'Mellish Portable AI Assistant' }
    }
    if (-not $ModelIds -or $ModelIds.Count -eq 0) { $ModelIds = $recommendedIds }
    $selected = @($Manifest.models | Where-Object { $ModelIds -contains $_.id })
    Invoke-Installation $InstallPath $selected ([bool]$WithVoice) ([bool]$WithNarrationStudio) (-not $NoShortcuts) $hardware
    exit 0
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Mellish Portable AI Assistant Setup'
$form.Size = New-Object Drawing.Size(860, 820)
$form.MinimumSize = New-Object Drawing.Size(760, 700)
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object Drawing.Font('Segoe UI', 9)

$title = New-Object System.Windows.Forms.Label
$title.Text = 'Mellish Portable AI Assistant'
$title.Font = New-Object Drawing.Font('Segoe UI', 16, [Drawing.FontStyle]::Bold)
$title.AutoSize = $true
$title.Location = New-Object Drawing.Point(18, 15)
$form.Controls.Add($title)

$hardwareBox = New-Object System.Windows.Forms.TextBox
$hardwareBox.ReadOnly = $true
$hardwareBox.Multiline = $true
$hardwareBox.BackColor = [Drawing.Color]::FromArgb(245,245,245)
$hardwareBox.Location = New-Object Drawing.Point(20, 53)
$hardwareBox.Size = New-Object Drawing.Size(800, 65)
$hardwareBox.Anchor = 'Top,Left,Right'
$gpuText = if ($hardware.NvidiaName) { "$($hardware.NvidiaName) - $($hardware.VramGB) GB VRAM - driver $($hardware.NvidiaDriver)" } elseif ($hardware.GpuNames.Count) { $hardware.GpuNames -join '; ' } else { 'No GPU information detected; CPU mode will be available.' }
$hardwareBox.Text = "Detected hardware:`r`nGPU: $gpuText`r`nSystem memory: $($hardware.RamGB) GB    Windows: $($hardware.WindowsVersion)"
$form.Controls.Add($hardwareBox)

$folderLabel = New-Object System.Windows.Forms.Label
$folderLabel.Text = 'Install everything under this folder:'
$folderLabel.AutoSize = $true
$folderLabel.Location = New-Object Drawing.Point(20, 132)
$form.Controls.Add($folderLabel)

$folderText = New-Object System.Windows.Forms.TextBox
$folderText.Location = New-Object Drawing.Point(20, 153)
$folderText.Size = New-Object Drawing.Size(690, 25)
$folderText.Anchor = 'Top,Left,Right'
$savedInstallPath = Get-SavedInstallPath
$folderText.Text = if ($InstallPath) { $InstallPath } elseif ($savedInstallPath) { $savedInstallPath } else { Join-Path $env:LOCALAPPDATA 'Mellish Portable AI Assistant' }
$form.Controls.Add($folderText)

$browse = New-Object System.Windows.Forms.Button
$browse.Text = 'Browse...'
$browse.Location = New-Object Drawing.Point(720, 151)
$browse.Size = New-Object Drawing.Size(100, 28)
$browse.Anchor = 'Top,Right'
$browse.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = 'Choose or create the assistant installation folder'
    $dialog.SelectedPath = $folderText.Text
    $dialog.ShowNewFolderButton = $true
    if ($dialog.ShowDialog() -eq 'OK') { $folderText.Text = $dialog.SelectedPath }
})
$form.Controls.Add($browse)

$modelsLabel = New-Object System.Windows.Forms.Label
$modelsLabel.Text = 'Choose models (hardware recommendations are preselected):'
$modelsLabel.AutoSize = $true
$modelsLabel.Location = New-Object Drawing.Point(20, 193)
$form.Controls.Add($modelsLabel)

$modelList = New-Object System.Windows.Forms.CheckedListBox
$modelList.CheckOnClick = $true
$modelList.Location = New-Object Drawing.Point(20, 216)
$modelList.Size = New-Object Drawing.Size(800, 245)
$modelList.Anchor = 'Top,Left,Right'
for ($i = 0; $i -lt $Manifest.models.Count; $i++) {
    $model = $Manifest.models[$i]
    [void]$modelList.Items.Add(("{0}  [{1:N2} GB]`r`n    {2}" -f $model.name, $model.sizeGB, $model.description))
    if ($recommendedIds -contains $model.id) { $modelList.SetItemChecked($i, $true) }
}
$form.Controls.Add($modelList)

$recommendedButton = New-Object System.Windows.Forms.Button
$recommendedButton.Text = 'Recommended'
$recommendedButton.Location = New-Object Drawing.Point(20, 470)
$recommendedButton.Size = New-Object Drawing.Size(115, 29)
$recommendedButton.Add_Click({ for ($i=0;$i -lt $Manifest.models.Count;$i++){ $modelList.SetItemChecked($i, ($recommendedIds -contains $Manifest.models[$i].id)) } })
$form.Controls.Add($recommendedButton)

$lowButton = New-Object System.Windows.Forms.Button
$lowButton.Text = 'Low-spec'
$lowButton.Location = New-Object Drawing.Point(142, 470)
$lowButton.Size = New-Object Drawing.Size(95, 29)
$lowButton.Add_Click({ for ($i=0;$i -lt $Manifest.models.Count;$i++){ $modelList.SetItemChecked($i, (@('small-uncensored','bonsai-small') -contains $Manifest.models[$i].id)) } })
$form.Controls.Add($lowButton)

$allButton = New-Object System.Windows.Forms.Button
$allButton.Text = 'Everything'
$allButton.Location = New-Object Drawing.Point(244, 470)
$allButton.Size = New-Object Drawing.Size(95, 29)
$allButton.Add_Click({ for ($i=0;$i -lt $Manifest.models.Count;$i++){ $modelList.SetItemChecked($i, $true) } })
$form.Controls.Add($allButton)

$voiceCheck = New-Object System.Windows.Forms.CheckBox
$voiceCheck.Text = 'Install offline speech-to-text and text-to-speech (about 1.2 GB)'
$voiceCheck.AutoSize = $true
$voiceCheck.Checked = ($hardware.RamGB -ge 16)
$voiceCheck.Location = New-Object Drawing.Point(365, 475)
$form.Controls.Add($voiceCheck)

$narrationCheck = New-Object System.Windows.Forms.CheckBox
$narrationCheck.Text = 'Install Narration Studio (books, comics and Unity/VRChat voice lines)'
$narrationCheck.AutoSize = $true
$narrationCheck.Checked = ($hardware.RamGB -ge 16)
$narrationCheck.Location = New-Object Drawing.Point(365, 502)
$narrationCheck.Add_CheckedChanged({ if ($narrationCheck.Checked) { $voiceCheck.Checked = $true } })
$form.Controls.Add($narrationCheck)

$shortcutCheck = New-Object System.Windows.Forms.CheckBox
$shortcutCheck.Text = 'Create Desktop and Start Menu shortcuts'
$shortcutCheck.AutoSize = $true
$shortcutCheck.Checked = $true
$shortcutCheck.Location = New-Object Drawing.Point(20, 525)
$form.Controls.Add($shortcutCheck)

$notice = New-Object System.Windows.Forms.Label
$notice.Text = 'Models labelled unrestricted/abliterated use community publisher claims, not a guarantee. The installer downloads model weights from their original hosts and keeps all runtime files, models, caches, chats and settings inside the selected folder.'
$notice.Location = New-Object Drawing.Point(20, 555)
$notice.Size = New-Object Drawing.Size(800, 43)
$notice.Anchor = 'Top,Left,Right'
$form.Controls.Add($notice)

$script:StatusLabel = New-Object System.Windows.Forms.Label
$script:StatusLabel.Text = 'Ready to install.'
$script:StatusLabel.Location = New-Object Drawing.Point(20, 605)
$script:StatusLabel.Size = New-Object Drawing.Size(800, 20)
$form.Controls.Add($script:StatusLabel)

$script:ProgressBar = New-Object System.Windows.Forms.ProgressBar
$script:ProgressBar.Location = New-Object Drawing.Point(20, 628)
$script:ProgressBar.Size = New-Object Drawing.Size(800, 18)
$script:ProgressBar.Anchor = 'Top,Left,Right'
$form.Controls.Add($script:ProgressBar)

$script:LogControl = New-Object System.Windows.Forms.TextBox
$script:LogControl.ReadOnly = $true
$script:LogControl.Multiline = $true
$script:LogControl.ScrollBars = 'Vertical'
$script:LogControl.Location = New-Object Drawing.Point(20, 655)
$script:LogControl.Size = New-Object Drawing.Size(680, 105)
$script:LogControl.Anchor = 'Top,Bottom,Left,Right'
$form.Controls.Add($script:LogControl)

$installButton = New-Object System.Windows.Forms.Button
$installButton.Text = 'Install'
$installButton.Font = New-Object Drawing.Font('Segoe UI', 10, [Drawing.FontStyle]::Bold)
$installButton.Location = New-Object Drawing.Point(715, 655)
$installButton.Size = New-Object Drawing.Size(105, 48)
$installButton.Anchor = 'Top,Right'
$form.Controls.Add($installButton)

$closeButton = New-Object System.Windows.Forms.Button
$closeButton.Text = 'Close'
$closeButton.Location = New-Object Drawing.Point(715, 712)
$closeButton.Size = New-Object Drawing.Size(105, 35)
$closeButton.Anchor = 'Top,Right'
$closeButton.Add_Click({ $form.Close() })
$form.Controls.Add($closeButton)

$installButton.Add_Click({
    try {
        $selected = @()
        for ($i=0; $i -lt $Manifest.models.Count; $i++) {
            if ($modelList.GetItemChecked($i)) { $selected += $Manifest.models[$i] }
        }
        $installButton.Enabled = $false
        $browse.Enabled = $false
        $modelList.Enabled = $false
        Invoke-Installation $folderText.Text $selected $voiceCheck.Checked $narrationCheck.Checked $shortcutCheck.Checked $hardware
        [System.Windows.Forms.MessageBox]::Show("Installation completed successfully.`r`n`r`n$($folderText.Text)", 'Mellish Portable AI Assistant', 'OK', 'Information') | Out-Null
    } catch {
        Add-Log "ERROR: $($_.Exception.Message)"
        Set-InstallerStatus 'Installation stopped because of an error.' 0
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Installation error', 'OK', 'Error') | Out-Null
    } finally {
        $installButton.Enabled = $true
        $browse.Enabled = $true
        $modelList.Enabled = $true
    }
})

if ($GuiSmokeTest) {
    $form.Add_Shown({
        Add-Log 'GUI smoke test passed: installer window and controls were created.'
        $form.BeginInvoke([Action]{ $form.Close() }) | Out-Null
    })
}

[void]$form.ShowDialog()
