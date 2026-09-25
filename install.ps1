# ==============================================================================
# Trace -- Automated Windows Installer
# Sets up Python virtual environment, dependencies, settings, and exposes 'trace'
# ==============================================================================

[CmdletBinding()]
param (
    [string]$Version = "",
    [switch]$ListVersions,
    [switch]$Reinstall,
    [switch]$Uninstall,
    [switch]$PurgeData,
    [switch]$VerboseOutput,
    [switch]$SkipDbMigration,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

foreach ($rawArg in $args) {
    if ($rawArg -match '^--version=(.+)$') {
        $Version = $Matches[1]
    } elseif ($rawArg -eq '--list-versions') {
        $ListVersions = $true
    } elseif ($rawArg -eq '--reinstall') {
        $Reinstall = $true
    } elseif ($rawArg -eq '--uninstall') {
        $Uninstall = $true
    } elseif ($rawArg -eq '--purge-data') {
        $PurgeData = $true
    } elseif ($rawArg -eq '--verbose') {
        $VerboseOutput = $true
    } elseif ($rawArg -eq '--help' -or $rawArg -eq '-h') {
        $Help = $true
    }
}

$TraceHomeDir = Join-Path $Home ".trace"
$InstallLog = Join-Path $TraceHomeDir "install.log"
$PhaseTotal = 6
$script:PhaseDone = 0
$script:DownloadShown = 0
$script:Shown = 0
$script:SpinIdx = 0
$VerboseMode = [bool]$VerboseOutput
if ($env:TRACE_VERBOSE -eq "1") {
    $VerboseMode = $true
}

function Write-TraceLog {
    param([string]$Text)
    try {
        Add-Content -Path $InstallLog -Value $Text -ErrorAction SilentlyContinue
    } catch {
    }
}

function Show-TraceUsage {
    Write-Host "Usage: install.ps1 [--version <tag>] [--list-versions] [--reinstall] [--uninstall [--purge-data]] [--verbose] [--help]"
    Write-Host ""
    Write-Host "  (none)              Quiet install of main (or TRACE_REF when set)"
    Write-Host "  --version <tag>     Install that release instead"
    Write-Host "  --list-versions     List releases; TTY offers pick-and-install"
    Write-Host "  --reinstall         Wipe app code first, then install"
    Write-Host "  --uninstall         Remove launcher + app + config; keeps storage and database"
    Write-Host "  --uninstall --purge-data  Also remove storage; confirms first"
    Write-Host "  --verbose           Full step-by-step output"
    Write-Host "  --help              Usage; exit 0"
}

function Get-TraceBar {
    param([int]$Pct)
    $filled = [math]::Floor($Pct * 20 / 100)
    $empty = 20 - $filled
    $full = [string]([char]0x2588)
    $lite = [string]([char]0x2591)
    ("$full" * $filled) + ("$lite" * $empty)
}

function Show-Bar {
    param([int]$Pct)
    $bar = Get-TraceBar $Pct
    $ver = if ($script:DisplayVersion) { $script:DisplayVersion } else { "install" }
    if ($VerboseMode) {
        return
    }
    $isTty = -not [Console]::IsOutputRedirected
    if (-not $isTty) {
        if ($Pct -ne 100 -or $script:DownloadShown -eq 1) {
            return
        }
        $script:DownloadShown = 1
        Write-Host ("Downloading Trace {0}..." -f $ver)
        Write-Host ""
        Write-Host (("[{0}] 100%" -f $bar))
        Write-Host ""
        return
    }
    if ($script:DownloadShown -eq 0) {
        $script:DownloadShown = 1
        Write-Host ("Downloading Trace {0}..." -f $ver) -ForegroundColor Green
        Write-Host ""
    }
    Write-Host -NoNewline ("`r[{0}] {1}%   " -f $bar, $Pct) -ForegroundColor Green
    if ($Pct -eq 100) {
        Write-Host ""
        Write-Host ""
    }
}

function Show-Spin {
    if ($VerboseMode) {
        return
    }
    if ([Console]::IsOutputRedirected) {
        return
    }
    if ($script:Shown -lt 0) {
        $script:Shown = 0
    }
    $script:SpinIdx += 1
    $frames = @('|', '/', '-', '\')
    $frame = $frames[$script:SpinIdx % 4]
    $bar = Get-TraceBar $script:Shown
    Write-Host -NoNewline ("`r[{0}] {1}% {2}   " -f $bar, $script:Shown, $frame) -ForegroundColor Green
}

function Step-One {
    $script:Shown += 1
    Show-Bar $script:Shown
}

function Step-To {
    param([int]$Target)
    if ($VerboseMode) {
        $script:Shown = $Target
        return
    }
    while ($script:Shown -lt $Target) {
        Step-One
        Start-Sleep -Milliseconds 50
    }
}

function Step-TracePhase {
    param([string]$Label)
    $script:PhaseDone += 1
    Step-To ([int][math]::Floor($script:PhaseDone * 100 / $PhaseTotal))
}

function Write-Trace {
    param([string]$Text)
    if ($VerboseMode) {
        Write-Host $Text
    }
    Write-TraceLog $Text
}

function Write-TempLog {
    param([string]$Tmp)
    Get-Content -Path $Tmp -ErrorAction SilentlyContinue | ForEach-Object { Write-TraceLog $_ }
    if ($VerboseMode) {
        Get-Content -Path $Tmp -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
    }
}

function Invoke-LoggedCommand {
    param([scriptblock]$Action, [object[]]$ActionArgs = @())
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("trace-install-" + [Guid]::NewGuid().ToString("N") + ".log")
    try {
        & $Action @ActionArgs > $tmp 2>&1
        $code = $LASTEXITCODE
        if ($null -eq $code) {
            $code = 0
        }
        Write-TempLog $tmp
        if ($code -ne 0) {
            throw "exit code $code"
        }
    } finally {
        Remove-Item -Force $tmp -ErrorAction SilentlyContinue
    }
}

function Invoke-LiveCommand {
    param([int]$Target, [scriptblock]$Action, [object[]]$ActionArgs = @())
    if ($VerboseMode -or [Console]::IsOutputRedirected) {
        Invoke-LoggedCommand $Action -ActionArgs $ActionArgs
        $script:Shown = $Target
        return
    }
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("trace-install-" + [Guid]::NewGuid().ToString("N") + ".log")
    $here = (Get-Location).Path
    $job = Start-Job -ScriptBlock {
        param($inner, $inArgs, $tmpPath, $workDir)
        Set-Location $workDir
        $live = [scriptblock]::Create($inner.ToString())
        & $live @inArgs > $tmpPath 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "exit code $LASTEXITCODE"
        }
    } -ArgumentList @($Action, $ActionArgs, $tmp, $here)
    try {
        while (($job.State -eq 'Running') -or ($job.State -eq 'NotStarted')) {
            if ($script:Shown -lt $Target) {
                Step-One
                Start-Sleep -Seconds 1
            } else {
                Show-Spin
                Start-Sleep -Seconds 1
            }
        }
        Write-TempLog $tmp
        if ($job.State -eq 'Failed') {
            throw "exit code 1"
        }
    } finally {
        try { Stop-Job $job -ErrorAction SilentlyContinue } catch { }
        try { Remove-Job $job -Force -ErrorAction SilentlyContinue } catch { }
        Remove-Item -Force $tmp -ErrorAction SilentlyContinue
    }
    Step-To $Target
}

function Stop-TraceInstall {
    param([string]$Step)
    if ((-not [Console]::IsOutputRedirected) -and (-not $VerboseMode)) {
        Write-Host ""
    }
    try {
        Write-Progress -Activity "Installing Trace" -Completed -ErrorAction SilentlyContinue
    } catch {
    }
    Write-Host "Install failed at '$Step' - see $InstallLog" -ForegroundColor Red
    try {
        Get-Content -Path $InstallLog -Tail 12 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
    } catch {
    }
    exit 1
}

function Show-Success {
    param([string]$Ver)
    $tick = [string]([char]0x2713)
    $isTty = -not [Console]::IsOutputRedirected
    if ($isTty -and -not $VerboseMode) {
        Write-Host ""
    }
    if ($isTty) {
        Write-Host ("{0} Installation complete" -f $tick) -ForegroundColor Green
        Write-Host ("Trace {0} installed successfully." -f $Ver) -ForegroundColor Green
    } else {
        Write-Host "Installation complete"
        Write-Host ("Trace {0} installed successfully." -f $Ver)
    }
}

function Test-ReleaseTag {
    param([string]$Tag)
    $gitCmd = Get-Command "git" -ErrorAction SilentlyContinue
    if ($gitCmd) {
        $out = & git ls-remote --tags https://github.com/nirjxr26/Trace.git $Tag 2>&1
        if ($out -match [regex]::Escape($Tag)) {
            return
        }
        Write-Host "Unknown tag '$Tag'. Run with --list-versions to see releases." -ForegroundColor Red
        exit 1
    }
    try {
        Invoke-WebRequest -Uri "https://api.github.com/repos/nirjxr26/Trace/releases/tags/$Tag" -UseBasicParsing -ErrorAction Stop | Out-Null
    } catch {
        Write-Host "Unknown tag '$Tag'. Run with --list-versions to see releases." -ForegroundColor Red
        exit 1
    }
}

function Show-ReleaseList {
    try {
        $releases = Invoke-RestMethod -Uri "https://api.github.com/repos/nirjxr26/Trace/releases?per_page=20" -ErrorAction Stop
    } catch {
        Write-Host "Could not list releases (offline?). Try --version vX.Y.Z explicitly."
        exit 1
    }
    $tags = @($releases | ForEach-Object { $_.tag_name } | Where-Object { $_ })
    if ($tags.Count -eq 0) {
        Write-Host "No releases found. Try --version vX.Y.Z explicitly."
        exit 0
    }
    $isTty = -not [Console]::IsInputRedirected -and -not [Console]::IsOutputRedirected
    if (-not $isTty) {
        $tags | ForEach-Object { Write-Host $_ }
        exit 0
    }
    Write-Host "Available releases:"
    for ($i = 0; $i -lt $tags.Count; $i++) {
        Write-Host ("  [{0}] {1}" -f ($i + 1), $tags[$i])
    }
    $pick = Read-Host "Enter number to install (empty to exit)"
    if ([string]::IsNullOrWhiteSpace($pick)) {
        exit 0
    }
    $idx = 0
    if (-not [int]::TryParse($pick, [ref]$idx) -or $idx -lt 1 -or $idx -gt $tags.Count) {
        Write-Host "Invalid selection." -ForegroundColor Red
        exit 1
    }
    $sel = $tags[$idx - 1]
    $env:TRACE_REF = $sel
    $extra = @()
    if ($Reinstall) {
        $extra += "--reinstall"
    }
    if ($VerboseMode) {
        $extra += "--verbose"
    }
    & $PSCommandPath --version $sel @extra
    exit $LASTEXITCODE
}

function Uninstall-TraceApp {
    param([string]$RepoRoot)
    $appDir = Join-Path $Home ".trace\app"
    $shim = Join-Path $Home ".local\bin\trace.cmd"
    $envFile = ""
    if ($RepoRoot -and (Test-Path (Join-Path $RepoRoot ".env"))) {
        $envFile = Join-Path $RepoRoot ".env"
    }
    if ([bool]$PurgeData) {
        $confirm = Read-Host "Remove storage and config? Database server is kept. Confirm y/N"
        if ($confirm -ne "y" -and $confirm -ne "Y") {
            Write-Host "Cancelled."
            exit 0
        }
    }
    Remove-Item -Force $shim -ErrorAction SilentlyContinue
    if (Test-Path $appDir) {
        Remove-Item -Recurse -Force $appDir -ErrorAction SilentlyContinue
    }
    if ($envFile -and (Test-Path $envFile)) {
        Remove-Item -Force $envFile -ErrorAction SilentlyContinue
    }
    $appEnv = Join-Path $Home ".trace\app\.env"
    if (Test-Path $appEnv) {
        Remove-Item -Force $appEnv -ErrorAction SilentlyContinue
    }
    if ([bool]$PurgeData) {
        Remove-Item -Recurse -Force (Join-Path $Home ".trace\trust") -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force (Join-Path $Home ".trace\storage") -ErrorAction SilentlyContinue
        Write-Host "Removed launcher, app, config, trust, storage."
        Write-Host "Kept: PostgreSQL server. To drop data run: DROP DATABASE trace;"
    } else {
        Write-Host "Removed launcher, app, config."
        Write-Host "Kept: storage (~/.trace/storage), trust keys, PostgreSQL database."
    }
    exit 0
}

if ([bool]$Help) {
    Show-TraceUsage
    exit 0
}

try {
    New-Item -ItemType Directory -Force -Path $TraceHomeDir | Out-Null
    "" | Add-Content -Path $InstallLog -ErrorAction SilentlyContinue
} catch {
}

Write-TraceLog ("install started verbose={0} reinstall={1} uninstall={2}" -f $VerboseMode, [bool]$Reinstall, [bool]$Uninstall)

if ($Version -ne "") {
    $env:TRACE_REF = $Version
    Test-ReleaseTag -Tag $Version
}

if ([bool]$ListVersions) {
    Show-ReleaseList
}

$RepoRoot = $PSScriptRoot
if (-not $RepoRoot -or -not (Test-Path (Join-Path $RepoRoot "pyproject.toml"))) {
    if (Test-Path "pyproject.toml") {
        $RepoRoot = (Get-Location).Path
    } else {
        $TraceHome = Join-Path $Home ".trace"
        $RepoRoot = Join-Path $TraceHome "app"
        if ($VerboseMode) {
            Write-Host "Remote installation detected. Setting up Trace in '$RepoRoot'..." -ForegroundColor Cyan
        }
        Write-TraceLog ("remote install root {0} ref {1}" -f $RepoRoot, ${env:TRACE_REF})
        if (-not (Test-Path (Join-Path $RepoRoot "pyproject.toml"))) {
            if (-not (Test-Path $TraceHome)) {
                New-Item -ItemType Directory -Force -Path $TraceHome | Out-Null
            }
            $Token = $env:GH_TOKEN
            if (-not $Token) { $Token = $env:GITHUB_TOKEN }
            $TraceRef = if ($env:TRACE_REF) { $env:TRACE_REF } else { "main" }
            $RefKind = if ($TraceRef -like "v*") { "tags" } else { "heads" }
            $ArchiveUrl = "https://github.com/nirjxr26/Trace/archive/refs/$RefKind/$TraceRef.zip"
            $WebHeaders = if ($Token) { @{ Authorization = "Bearer $Token" } } else { @{} }

            $GitCmd = Get-Command "git" -ErrorAction SilentlyContinue
            if ($GitCmd) {
                Write-Trace ("Cloning repository via git (ref: {0})..." -f $TraceRef)
                try {
                    if ($Token) {
                        $AskPass = Join-Path ([IO.Path]::GetTempPath()) ("trace-askpass-" + [Guid]::NewGuid().ToString("N") + ".cmd")
                        Set-Content -Path $AskPass -Value "@echo off`r`n@echo %TRACE_GIT_TOKEN%"
                        $OldAskPass = $env:GIT_ASKPASS
                        try {
                            $env:TRACE_GIT_TOKEN = $Token
                            $env:GIT_ASKPASS = $AskPass
                            $env:GIT_TERMINAL_PROMPT = "0"
                            Invoke-LoggedCommand { & git clone --depth 1 --branch $TraceRef https://github.com/nirjxr26/Trace.git $RepoRoot }
                        } finally {
                            Remove-Item -Force $AskPass -ErrorAction SilentlyContinue
                            Remove-Item Env:\TRACE_GIT_TOKEN -ErrorAction SilentlyContinue
                            if ($null -eq $OldAskPass) { Remove-Item Env:\GIT_ASKPASS -ErrorAction SilentlyContinue }
                            else { $env:GIT_ASKPASS = $OldAskPass }
                            Remove-Item Env:\GIT_TERMINAL_PROMPT -ErrorAction SilentlyContinue
                        }
                    } else {
                        Invoke-LoggedCommand { & git clone --depth 1 --branch $TraceRef https://github.com/nirjxr26/Trace.git $RepoRoot }
                    }
                } catch {
                    Stop-TraceInstall "source"
                }
            } else {
                Write-Trace "Downloading repository archive..."
                $ZipPath = Join-Path $TraceHome "trace-main.zip"
                $TempExtract = Join-Path $TraceHome "trace-temp"
                try {
                    Invoke-WebRequest -Uri $ArchiveUrl -Headers $WebHeaders -OutFile $ZipPath
                } catch {
                    Stop-TraceInstall "source"
                }
                if ($env:TRACE_RELEASE_SHA256) {
                    $ActualSha = (Get-FileHash -Path $ZipPath -Algorithm SHA256).Hash.ToLower()
                    if ($ActualSha -ne $env:TRACE_RELEASE_SHA256.ToLower()) {
                        Write-Host "  [!] Release digest mismatch: refusing to install." -ForegroundColor Red
                        Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue
                        exit 1
                    }
                    if ($env:TRACE_COSIGN_BUNDLE_URL -and (Get-Command "cosign" -ErrorAction SilentlyContinue)) {
                        $BundlePath = "$ZipPath.sigstore.json"
                        Invoke-WebRequest -Uri $env:TRACE_COSIGN_BUNDLE_URL -Headers $WebHeaders -OutFile $BundlePath
                        $OidcIssuer = if ($env:TRACE_COSIGN_OIDC_ISSUER) { $env:TRACE_COSIGN_OIDC_ISSUER } else { "https://token.actions.githubusercontent.com" }
                        if (-not $env:TRACE_COSIGN_IDENTITY) { Write-Host "  [!] Set TRACE_COSIGN_IDENTITY to verify." -ForegroundColor Red; exit 1 }
                        & cosign verify-blob --bundle $BundlePath --certificate-identity $env:TRACE_COSIGN_IDENTITY --certificate-oidc-issuer $OidcIssuer $ZipPath
                        Remove-Item -Force $BundlePath -ErrorAction SilentlyContinue
                    }
                } else {
                    Write-Trace ("  [!] No TRACE_RELEASE_SHA256 pinned: installing unverified {0}." -f $TraceRef)
                }
                Expand-Archive -Path $ZipPath -DestinationPath $TempExtract -Force
                $ExtractedFolder = (Get-ChildItem -Directory -Path $TempExtract | Select-Object -First 1).FullName
                if (Test-Path $RepoRoot) { Remove-Item -Recurse -Force $RepoRoot }
                Move-Item -Path $ExtractedFolder -Destination $RepoRoot
                Remove-Item -Force $ZipPath
                Remove-Item -Recurse -Force $TempExtract
            }
        }
    }
}

if ([bool]$Uninstall) {
    Uninstall-TraceApp -RepoRoot $RepoRoot
}

if ([bool]$Reinstall) {
    $defaultApp = Join-Path $Home ".trace\app"
    try {
        if ($RepoRoot -eq $defaultApp) {
            if (Test-Path $RepoRoot) {
                Remove-Item -Recurse -Force $RepoRoot
            }
        } else {
            $venvPath = Join-Path $RepoRoot ".venv"
            if (Test-Path $venvPath) {
                Remove-Item -Recurse -Force $venvPath
            }
            if (Test-Path $defaultApp) {
                Remove-Item -Recurse -Force $defaultApp
            }
        }
    } catch {
        Stop-TraceInstall "source"
    }
    if (-not (Test-Path (Join-Path $RepoRoot "pyproject.toml"))) {
        Write-Host "Reinstall requested but source is gone. Re-run without --reinstall or pass --version." -ForegroundColor Red
        exit 1
    }
}

Set-Location $RepoRoot

$script:DisplayVersion = ""
$pyproj = Join-Path $RepoRoot "pyproject.toml"
if (Test-Path $pyproj) {
    $m = Select-String -Path $pyproj -Pattern '^version = "(.*)"' | Select-Object -First 1
    if ($m) {
        $script:DisplayVersion = $m.Matches[0].Groups[1].Value
    }
}
if (-not $script:DisplayVersion) {
    $script:DisplayVersion = if ($env:TRACE_REF) { $env:TRACE_REF } else { "main" }
}

if ($VerboseMode) {
    Write-Host ""
    Write-Host "  ================================================================" -ForegroundColor Cyan
    Write-Host "         TRACE -- Forensic Data Imaging and Retrieval Tool        " -ForegroundColor Cyan
    Write-Host "                           Windows Installer                      " -ForegroundColor Cyan
    Write-Host "  ================================================================" -ForegroundColor Cyan
    Write-Host ""
}

Step-TracePhase "python"
if ($VerboseMode) {
    Write-Host "[1/6] Searching for Python 3.12+..." -ForegroundColor Yellow
}
$PythonCandidates = @("py", "python3.12", "python3", "python")
$FoundPython = $null

foreach ($cmd in $PythonCandidates) {
    try {
        $check = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($check) {
            $versionOutput = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($versionOutput) {
                $parts = $versionOutput.Trim().Split(".")
                $major = [int]$parts[0]
                $minor = [int]$parts[1]
                if ($major -ge 3 -and $minor -ge 12) {
                    $FoundPython = $cmd
                    Write-Trace ("  [OK] Found Python {0} using '{1}'" -f $versionOutput, $cmd)
                    break
                }
            }
        }
    } catch {
        continue
    }
}

if (-not $FoundPython) {
    Write-Host ""
    Write-Host "  [!] Error: Python 3.12 or higher was not found on your system." -ForegroundColor Red
    Write-Host "  Please install Python 3.12+ from https://www.python.org/downloads/ and ensure" -ForegroundColor Yellow
    Write-Host "  'Add python.exe to PATH' is checked during installation." -ForegroundColor Yellow
    Stop-TraceInstall "python"
}

Step-TracePhase "source"
Write-Trace ("Source ready at {0}" -f $RepoRoot)

$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

Step-TracePhase "venv"
if ($VerboseMode) {
    Write-Host "[2/6] Configuring virtual environment..." -ForegroundColor Yellow
}
if (-not (Test-Path $VenvPython)) {
    Write-Trace ("  Creating virtual environment at '{0}'..." -f $VenvDir)
    try {
        Invoke-LiveCommand -Target 50 -Action { param($py, $vd) & $py -m venv $vd } -ActionArgs @($FoundPython, $VenvDir)
    } catch {
        Stop-TraceInstall "venv"
    }
} else {
    Write-Trace "  [OK] Existing virtual environment detected."
}

Step-TracePhase "dependencies"
if ($VerboseMode) {
    Write-Host "[3/6] Installing locked dependencies..." -ForegroundColor Yellow
    Write-Host "  Using pip with cryptographic hash verification..."
}
try {
    Invoke-LiveCommand -Target 66 -Action { param($py) & $py -m pip install --quiet "pip==26.2.1" } -ActionArgs @($VenvPython)
    Invoke-LiveCommand -Target 66 -Action { param($py) & $py -m pip install --quiet --require-hashes --only-binary :all: -r requirements.txt } -ActionArgs @($VenvPython)
    Invoke-LiveCommand -Target 66 -Action { param($py) & $py -m pip install --quiet --no-deps -e . } -ActionArgs @($VenvPython)
} catch {
    Stop-TraceInstall "dependencies"
}
Write-Trace "  [OK] Dependencies installed successfully."

Step-TracePhase "config"
if ($VerboseMode) {
    Write-Host "[4/6] Verifying environment and storage directories..." -ForegroundColor Yellow
}
$EnvFile = Join-Path $RepoRoot ".env"
$EnvExample = Join-Path $RepoRoot ".env.example"

if (-not (Test-Path $EnvFile)) {
    if (Test-Path $EnvExample) {
        Copy-Item $EnvExample $EnvFile
        if (-not (Select-String -Path $EnvFile -Pattern "^TRACE_UPDATE_MANIFEST=" -Quiet)) {
            Add-Content -Path $EnvFile -Value "TRACE_UPDATE_MANIFEST=https://github.com/nirjxr26/Trace/releases/latest/download/stable.json"
        }
        Write-Trace "  [OK] Created .env from template (.env.example)."
        Write-Trace "  [!] Set a strong TRACE_DATABASE_URL password and TRACE_SECRET_KEY before production use."
    }
} else {
    Write-Trace "  [OK] Existing .env file preserved."
}

$TrustDir = Join-Path $Home ".trace\trust\releases"
try {
    New-Item -ItemType Directory -Force -Path $TrustDir | Out-Null
    $Bundle = Join-Path ([IO.Path]::GetTempPath()) "trace-trusted-keys.bundle"
    Invoke-LiveCommand -Target 83 -Action { param($url, $out) Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing } -ActionArgs @("https://github.com/nirjxr26/Trace/releases/latest/download/trusted-keys.bundle", $Bundle)
    foreach ($line in (Get-Content -Path $Bundle)) {
        $parts = $line.Trim() -split "\s+", 2
        if ($parts.Count -eq 2 -and $parts[0] -match "^[0-9a-f]{16}$" -and $parts[1] -match "^[0-9a-f]{64}$") {
            Set-Content -Path (Join-Path $TrustDir ($parts[0] + ".pub")) -Value $parts[1] -NoNewline
        }
    }
    Remove-Item -Force $Bundle -ErrorAction SilentlyContinue
    Write-Trace "  [OK] Release trust keys provisioned."
} catch {
    Write-Trace "  [!] Could not fetch release trust keys (offline or no release yet). Verification stays fail-closed until provisioned."
}

$DefaultStorage = Join-Path $Home ".trace\storage"
if (-not (Test-Path $DefaultStorage)) {
    New-Item -ItemType Directory -Force -Path $DefaultStorage | Out-Null
    Write-Trace ("  [OK] Created forensic storage directory at '{0}'." -f $DefaultStorage)
} else {
    Write-Trace "  [OK] Forensic storage directory exists."
}

$TraceExe = Join-Path $VenvDir "Scripts\trace.exe"

if (-not $SkipDbMigration) {
    try {
        Invoke-LiveCommand -Target 83 -Action { param($exe) & $exe doctor } -ActionArgs @($TraceExe)
        Write-Trace "  [OK] Database verified and up to date."
    } catch {
        Write-Trace "  [!] Database unreachable. Trace will self-initialize on first use once it is reachable."
        Write-Trace "      Start PostgreSQL or set TRACE_DATABASE_URL in .env, then run 'trace doctor' to verify."
    }
} else {
    Write-Trace "  Skipping database verification as requested."
}

Step-TracePhase "launcher"
if ($VerboseMode) {
    Write-Host "[6/6] Exposing 'trace' command to User PATH..." -ForegroundColor Yellow
}
$UserBin = Join-Path $Home ".local\bin"
if (-not (Test-Path $UserBin)) {
    New-Item -ItemType Directory -Force -Path $UserBin | Out-Null
}

$TraceExe = Join-Path $VenvDir "Scripts\trace.exe"
$LauncherBat = Join-Path $UserBin "trace.cmd"
$Lines = @(
    "@echo off",
    "`"$TraceExe`" %*"
)
[System.IO.File]::WriteAllLines($LauncherBat, $Lines)

$UserPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($UserPath -notlike "*$UserBin*") {
    $NewPath = "$UserBin;$UserPath"
    [Environment]::SetEnvironmentVariable("PATH", $NewPath, "User")
    $env:PATH = "$UserBin;$env:PATH"
    Write-Trace ("  [OK] Added '{0}' to User PATH." -f $UserBin)
} else {
    Write-Trace ("  [OK] '{0}' is already in PATH." -f $UserBin)
}

Show-Success -Ver ("v{0}" -f $script:DisplayVersion)
