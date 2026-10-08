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

trap {
    if (Get-Command Release-Steps -ErrorAction SilentlyContinue) {
        Release-Steps
    }
    throw $_
}

[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

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
$PhaseTotal = 4
$script:PhaseDone = 0
$script:StepIndex = 0
$script:StepPainted = $false
$script:DotIdx = 0
$script:DoneGlyph = [string]([char]0x25CF)
$script:PendGlyph = [string]([char]0x25B2)
$script:NextGlyph = [string]([char]0x25CF)
$script:FailGlyph = [string]([char]0x2715)
$script:TickGlyph = [string]([char]0x2713)
$script:DotFrames = @(
    [string]([char]0x280B), [string]([char]0x2819), [string]([char]0x2839), [string]([char]0x2838),
    [string]([char]0x283C), [string]([char]0x2834), [string]([char]0x2826), [string]([char]0x2827),
    [string]([char]0x2807), [string]([char]0x280F)
)
$script:SpinDelayTicks = 4
$script:StepTicks = 0
$script:StepLabels = @(
    "Verifying",
    "Downloading",
    "Installing",
    "Finishing setup"
)
$script:StepGutter = [string]([char]0x2502) + " "
$script:StepStates = @("pending", "pending", "pending", "pending")
$VerboseMode = [bool]$VerboseOutput
if ($env:TRACE_VERBOSE -eq "1") {
    $VerboseMode = $true
}

function Write-TraceLog {
    param([string]$Text)
    Add-Content -Path $InstallLog -Value $Text -ErrorAction SilentlyContinue
}

function Show-TraceUsage {
    Write-Output "Usage: install.ps1 [--version <tag>] [--list-versions] [--reinstall] [--uninstall [--purge-data]] [--verbose] [--help]"
    Write-Output ""
    Write-Output "  (none)              Quiet install of main (or TRACE_REF when set)"
    Write-Output "  --version <tag>     Install that release instead"
    Write-Output "  --list-versions     List releases; TTY offers pick-and-install"
    Write-Output "  --reinstall         Wipe app code first, then install"
    Write-Output "  --uninstall         Remove launcher + app + config; keeps storage and database"
    Write-Output "  --uninstall --purge-data  Also remove storage; confirms first"
    Write-Output "  --verbose           Full step-by-step output"
    Write-Output "  --help              Usage; exit 0"
}

function Write-StepBlock {
    $esc = [char]27
    $count = $script:StepLabels.Count
    $frame = ""
    for ($i = 0; $i -lt $count; $i++) {
        $glyph = $script:PendGlyph
        $colour = "33"
        $label = $script:StepLabels[$i]
        if ($script:StepStates[$i] -eq "done") {
            $glyph = $script:DoneGlyph
            $colour = "32"
        } elseif ($script:StepStates[$i] -eq "active") {
            $glyph = $script:DotFrames[$script:DotIdx % $script:DotFrames.Count]
            $colour = "32"
        } elseif ($script:StepStates[$i] -eq "fail") {
            $glyph = $script:FailGlyph
            $colour = "31"
        }
        $frame += "`r{0}[2K  {1}[{2}m{3}{4}  {1}[0m{5}" -f $esc, $esc, $colour, $script:StepGutter, $glyph, $label
        if ($i -lt $count - 1) {
            $frame += "`n"
        }
    }
    Write-Host -NoNewline $frame
}

function Show-InstallTitle {
    $ver = if ($script:DisplayVersion) { $script:DisplayVersion } else { "main" }
    $ver = $ver -replace '^v', ''
    if ($VerboseMode -or [Console]::IsOutputRedirected) {
        return
    }
    Write-Output ""
    Write-Host ("  Trace {0}" -f $ver)
    Write-Output ""
}

function Show-Steps {
    if ($VerboseMode -or [Console]::IsOutputRedirected) {
        return
    }
    $esc = [char]27
    if ($script:StepPainted) {
        Write-Host -NoNewline ("`r$esc[{0}A" -f ($script:StepLabels.Count - 1))
    } else {
        Write-Host -NoNewline "$esc[?25l"
    }
    Write-StepBlock
    $script:StepPainted = $true
}

function Release-Steps {
    if (-not $script:StepPainted) {
        return
    }
    Write-Host -NoNewline ("`n$([char]27)[?25h")
    $script:StepPainted = $false
}

function Animate-Steps {
    if ($VerboseMode -or [Console]::IsOutputRedirected) {
        return
    }
    $script:StepTicks += 1
    if ($script:StepTicks -gt $script:SpinDelayTicks) {
        $script:DotIdx += 1
    }
    Show-Steps
}

function Start-Step {
    param([int]$Index)
    $script:StepStates[$Index] = "active"
    $script:StepIndex = $Index
    $script:StepTicks = 0
    $script:DotIdx = 0
    if ($VerboseMode -or [Console]::IsOutputRedirected) {
        Write-Output ("  |  ... {0}" -f $script:StepLabels[$Index])
        return
    }
    Show-Steps
}

function Done-Step {
    param([int]$Index)
    $script:StepStates[$Index] = "done"
    if ($VerboseMode -or [Console]::IsOutputRedirected) {
        Write-Output ("  |  [OK] {0}" -f $script:StepLabels[$Index])
        return
    }
    Show-Steps
}

function Fail-Step {
    param([int]$Index)
    $script:StepStates[$Index] = "fail"
    if (-not $VerboseMode -and -not [Console]::IsOutputRedirected) {
        Show-Steps
        Release-Steps
    }
}

function Step-TracePhase {
    param([int]$Index)
    $script:PhaseDone += 1
    Start-Step $Index
}

function Write-Trace {
    param([string]$Text)
    if ($VerboseMode) {
        Write-Output $Text
    }
    Write-TraceLog $Text
}

function Write-TempLog {
    param([string]$Tmp)
    Get-Content -Path $Tmp -ErrorAction SilentlyContinue | ForEach-Object { Write-TraceLog $_ }
    if ($VerboseMode) {
        Get-Content -Path $Tmp -ErrorAction SilentlyContinue | ForEach-Object { Write-Output $_ }
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
    param([scriptblock]$Action, [object[]]$ActionArgs = @())
    if ($VerboseMode -or [Console]::IsOutputRedirected) {
        Invoke-LoggedCommand $Action -ActionArgs $ActionArgs
        return
    }
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("trace-install-" + [Guid]::NewGuid().ToString("N") + ".log")
    $here = (Get-Location).Path
    $job = Start-Job -ScriptBlock {
        param($inner, $inArgs, $tmpPath, $workDir)
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Set-Location $workDir
        $live = [scriptblock]::Create($inner.ToString())
        & $live @inArgs > $tmpPath 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "exit code $LASTEXITCODE"
        }
    } -ArgumentList @($Action, $ActionArgs, $tmp, $here)
    try {
        while (($job.State -eq 'Running') -or ($job.State -eq 'NotStarted')) {
            Animate-Steps
            Start-Sleep -Milliseconds 120
        }
        Write-TempLog $tmp
        if ($job.State -eq 'Failed') {
            throw "exit code 1"
        }
    } finally {
        Stop-Job $job -ErrorAction SilentlyContinue
        Remove-Job $job -Force -ErrorAction SilentlyContinue
        Remove-Item -Force $tmp -ErrorAction SilentlyContinue
    }
    Done-Step $script:StepIndex
}

function Stop-TraceInstall {
    param([string]$Step)
    if ((-not [Console]::IsOutputRedirected) -and (-not $VerboseMode)) {
        Fail-Step $script:StepIndex
        Write-Output ""
    }
    Write-Progress -Activity "Installing Trace" -Completed -ErrorAction SilentlyContinue
    Write-Host "Install failed at '$Step' - see $InstallLog" -ForegroundColor Red
    Get-Content -Path $InstallLog -Tail 12 -ErrorAction SilentlyContinue | ForEach-Object { Write-Output $_ }
    exit 1
}

function Show-Success {
    param([string]$Ver)
    $tick = $script:TickGlyph
    $isTty = -not [Console]::IsOutputRedirected
    if ($isTty -and -not $VerboseMode) {
        Release-Steps
        Write-Output ""
    }
    if ($isTty) {
        Write-Host ("  {0} Installation complete" -f $tick) -ForegroundColor Green
        Write-Output ""
        Write-Host "  Run trace to get started"
        Write-Output ""
    } else {
        Write-Output "Installation complete"
        Write-Output ("Trace {0} installed successfully." -f $Ver)
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
        Write-Output "Could not list releases (offline?). Try --version vX.Y.Z explicitly."
        exit 1
    }
    $tags = @($releases | ForEach-Object { $_.tag_name } | Where-Object { $_ })
    if ($tags.Count -eq 0) {
        Write-Output "No releases found. Try --version vX.Y.Z explicitly."
        exit 0
    }
    $isTty = -not [Console]::IsInputRedirected -and -not [Console]::IsOutputRedirected
    if (-not $isTty) {
        $tags | ForEach-Object { Write-Output $_ }
        exit 0
    }
    Write-Output "Available releases:"
    for ($i = 0; $i -lt $tags.Count; $i++) {
        Write-Output ("  [{0}] {1}" -f ($i + 1), $tags[$i])
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
            Write-Output "Cancelled."
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
        Write-Output "Removed launcher, app, config, trust, storage."
        Write-Output "Kept: PostgreSQL server. To drop data run: DROP DATABASE trace;"
    } else {
        Write-Output "Removed launcher, app, config."
        Write-Output "Kept: storage (~/.trace/storage), trust keys, PostgreSQL database."
    }
    exit 0
}

if ([bool]$Help) {
    Show-TraceUsage
    exit 0
}

New-Item -ItemType Directory -Force -Path $TraceHomeDir -ErrorAction SilentlyContinue | Out-Null
"" | Add-Content -Path $InstallLog -ErrorAction SilentlyContinue

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

Show-InstallTitle

Step-TracePhase 0
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
Done-Step 0

Step-TracePhase 1
Write-Trace ("Source ready at {0}" -f $RepoRoot)
Done-Step 1

$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

Step-TracePhase 2
if ($VerboseMode) {
    Write-Host "[2/6] Configuring virtual environment..." -ForegroundColor Yellow
}
if (-not (Test-Path $VenvPython)) {
    Write-Trace ("  Creating virtual environment at '{0}'..." -f $VenvDir)
    try {
        Invoke-LiveCommand -Action { param($py, $vd) & $py -m venv $vd } -ActionArgs @($FoundPython, $VenvDir)
    } catch {
        Stop-TraceInstall "venv"
    }
} else {
    Write-Trace "  [OK] Existing virtual environment detected."
    Done-Step 2
}

if ($VerboseMode) {
    Write-Host "[3/6] Installing locked dependencies..." -ForegroundColor Yellow
    Write-Host "  Using pip with cryptographic hash verification..."
}
try {
    Invoke-LiveCommand -Action { param($py) & $py -m pip install --quiet "pip==26.2.1" } -ActionArgs @($VenvPython)
    Invoke-LiveCommand -Action { param($py) & $py -m pip install --quiet --require-hashes --only-binary :all: -r requirements.txt } -ActionArgs @($VenvPython)
    Invoke-LiveCommand -Action { param($py) & $py -m pip install --quiet --no-deps -e . } -ActionArgs @($VenvPython)
} catch {
    Stop-TraceInstall "dependencies"
}
Write-Trace "  [OK] Dependencies installed successfully."
Done-Step 2

Step-TracePhase 3
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

# Bootstrap anchor, established independently of the release channel. The channel
# only supplies key bytes; a bundle line is written solely when the id derived from
# its own content is one embedded here. An attacker who controls the channel can
# therefore withhold a key but can never introduce a new trust root. Adding one
# means editing this installer, which is reviewed code.
$BootstrapKeyIds = @("53712e8bb8a774e6")
$TrustDir = Join-Path $Home ".trace\trust\releases"
try {
    New-Item -ItemType Directory -Force -Path $TrustDir | Out-Null
    $Bundle = Join-Path ([IO.Path]::GetTempPath()) "trace-trusted-keys.bundle"
    Invoke-LiveCommand -Action { param($url, $out) Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing } -ActionArgs @("https://github.com/nirjxr26/Trace/releases/latest/download/trusted-keys.bundle", $Bundle)
    $Provisioned = 0
    foreach ($line in (Get-Content -Path $Bundle)) {
        $parts = $line.Trim() -split "\s+", 2
        if ($parts.Count -ne 2 -or $parts[0] -notmatch "^[0-9a-f]{16}$" -or $parts[1] -notmatch "^[0-9a-f]{64}$") { continue }
        # Hex -> bytes without [Convert]::FromHexString, which Windows PowerShell 5.1 lacks.
        $raw = New-Object byte[] 32
        for ($i = 0; $i -lt 32; $i++) { $raw[$i] = [Convert]::ToByte($parts[1].Substring($i * 2, 2), 16) }
        $sha = [System.Security.Cryptography.SHA256]::Create()
        $derived = -join (($sha.ComputeHash($raw))[0..7] | ForEach-Object { $_.ToString("x2") })
        # The bundle's own filename is attacker-controlled; the id is derived from the
        # key bytes and must agree with it.
        if ($derived -ne $parts[0]) { continue }
        if ($BootstrapKeyIds -notcontains $derived) {
            Write-Trace ("  [!] Skipped release key {0}: not a bootstrap anchor." -f $derived)
            continue
        }
        Set-Content -Path (Join-Path $TrustDir ($derived + ".pub")) -Value $parts[1] -NoNewline
        $Provisioned++
    }
    Remove-Item -Force $Bundle -ErrorAction SilentlyContinue
    if ($Provisioned -gt 0) {
        Write-Trace ("  [OK] Release trust keys provisioned ({0} bootstrap anchor(s))." -f $Provisioned)
    } else {
        Write-Trace "  [!] Release bundle carried no known bootstrap anchor. Verification stays fail-closed."
    }
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
        Invoke-LiveCommand -Action { param($exe) & $exe doctor } -ActionArgs @($TraceExe)
        Write-Trace "  [OK] Database verified and up to date."
    } catch {
        Write-Trace "  [!] Database unreachable. Trace will self-initialize on first use once it is reachable."
        Write-Trace "      Start PostgreSQL or set TRACE_DATABASE_URL in .env, then run 'trace doctor' to verify."
    }
} else {
    Write-Trace "  Skipping database verification as requested."
}

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
Done-Step 3

Show-Success -Ver ("v{0}" -f $script:DisplayVersion)
