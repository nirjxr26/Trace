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
    [switch]$AllowUnverified,
    [switch]$VerboseOutput,
    [switch]$SkipDbMigration,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

trap {
    throw $_
}

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
if ([Enum]::GetNames([Net.SecurityProtocolType]) -contains "Tls13") {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls13
}
$TraceProxy = $env:HTTPS_PROXY
if (-not $TraceProxy) { $TraceProxy = $env:HTTP_PROXY }
if ($TraceProxy) {
    [Net.WebRequest]::DefaultWebProxy = New-Object Net.WebProxy($TraceProxy)
}

$UnknownFlags = @()
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
    } elseif ($rawArg -eq '--allow-unverified') {
        $AllowUnverified = $true
    } elseif ($rawArg -eq '--verbose') {
        $VerboseOutput = $true
    } elseif ($rawArg -eq '--help' -or $rawArg -eq '-h') {
        $Help = $true
    } else {
        # A typo'd flag used to be ignored, so `--purge-date` installed the default ref and
        # `--uninstall --purge-data` silently dropped the data removal. install.sh exits 2.
        $UnknownFlags += $rawArg
    }
}

if ($UnknownFlags.Count -gt 0 -and -not $Help -and -not $ListVersions) {
    foreach ($bad in $UnknownFlags) {
        Write-Host "Unknown flag '$bad'. Run with --help to see the options." -ForegroundColor Red
    }
    exit 2
}

$TraceHomeDir = Join-Path $Home ".trace"
$InstallLog = Join-Path $TraceHomeDir "install.log"
$script:DisplayVersion = ""
$script:DoctorFailed = $false
$script:LastChildExit = 0
$script:StageRoot = ""
$script:Staged = $false
$script:TempArtifacts = @()
$VerboseMode = [bool]$VerboseOutput
if ($env:TRACE_VERBOSE -eq "1") {
    $VerboseMode = $true
}

function Write-TraceLog {
    param([string]$Text)
    Add-Content -Path $InstallLog -Value $Text -ErrorAction SilentlyContinue
}

function Protect-TraceFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    try {
        $acl = Get-Acl -Path $Path
        $acl.SetAccessRuleProtection($true, $false)
        foreach ($rule in @($acl.Access)) { $acl.RemoveAccessRule($rule) | Out-Null }
        $owner = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $grant = New-Object Security.AccessControl.FileSystemAccessRule($owner, "FullControl", "Allow")
        $acl.AddAccessRule($grant)
        Set-Acl -Path $Path -AclObject $acl
    } catch {
        Write-Host "  [!] Could not restrict permissions on a local file." -ForegroundColor Yellow
    }
}

function Add-TraceTempArtifact {
    param([string]$Path)
    if ($Path) { $script:TempArtifacts += $Path }
}

function Remove-TraceTempArtifacts {
    foreach ($artifact in $script:TempArtifacts) {
        if ($artifact -and (Test-Path $artifact)) {
            Remove-Item -Recurse -Force $artifact -ErrorAction SilentlyContinue
        }
    }
    $script:TempArtifacts = @()
}

function Show-TraceUsage {
    Write-Output "Usage: install.ps1 [--version <tag>] [--list-versions] [--reinstall] [--uninstall [--purge-data]] [--allow-unverified] [--verbose] [--help]"
    Write-Output ""
    Write-Output "  (none)              Quiet install of main (or TRACE_REF when set)"
    Write-Output "  --version <tag>     Install that release instead"
    Write-Output "  --list-versions     List releases; TTY offers pick-and-install"
    Write-Output "  --reinstall         Wipe app code first, then install"
    Write-Output "  --uninstall         Remove launcher + app + config; keeps storage and database"
    Write-Output "  --uninstall --purge-data  Also remove storage; needs a TTY prompt or typed PURGE"
    Write-Output "  --allow-unverified  Opt in to mutable main without TRACE_RELEASE_SHA256 or TRACE_COSIGN_BUNDLE_URL"
    Write-Output "  --verbose           Full step-by-step output"
    Write-Output "  --help              Usage; exit 0"
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
        $script:LastChildExit = $code
        if ($code -ne 0) {
            throw "exit code $code"
        }
    } finally {
        Remove-Item -Force $tmp -ErrorAction SilentlyContinue
    }
}

function Invoke-TraceDownload {
    param([string]$Uri, [string]$OutFile, [hashtable]$Headers = @{})
    $next = $Uri
    for ($hop = 0; $hop -lt 6; $hop++) {
        if (-not $next.StartsWith("https://", [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing a non-HTTPS download URL."
        }
        $request = [Net.HttpWebRequest]::Create($next)
        $request.Timeout = 60000
        $request.ReadWriteTimeout = 60000
        $request.AllowAutoRedirect = $false
        foreach ($key in $Headers.Keys) { $request.Headers[$key] = $Headers[$key] }
        $response = $request.GetResponse()
        $status = [int]$response.StatusCode
        if ($status -ge 300 -and $status -lt 400) {
            $location = $response.Headers["Location"]
            $response.Close()
            if (-not $location) { throw "Redirect without a Location header." }
            $next = $location
            continue
        }
        try {
            if ($status -ne 200) { throw "Unexpected HTTP status $status." }
            $source = $response.GetResponseStream()
            $dest = [IO.File]::Create($OutFile)
            try { $source.CopyTo($dest) } finally { $dest.Dispose(); $source.Dispose() }
            return
        } finally {
            $response.Close()
        }
    }
    throw "Too many redirects while downloading."
}

function Remove-TracePath {
    param([string]$Path, [switch]$Recurse)
    if (-not $Path -or -not (Test-Path $Path)) { return }
    try {
        if ($Recurse) { Remove-Item -Recurse -Force $Path -ErrorAction Stop }
        else { Remove-Item -Force $Path -ErrorAction Stop }
    } catch {
        Write-Host "  [!] Could not remove a local file or directory." -ForegroundColor Red
        Stop-TraceInstall "uninstall"
    }
}

function Stop-TraceInstall {
    param([string]$Step)
    Remove-TraceTempArtifacts
    if ($script:StageRoot -and (Test-Path $script:StageRoot)) {
        Remove-Item -Recurse -Force $script:StageRoot -ErrorAction SilentlyContinue
    }
    if ((-not [Console]::IsOutputRedirected) -and (-not $VerboseMode)) {
        Write-Output ""
    }
    Write-Progress -Activity "Installing Trace" -Completed -ErrorAction SilentlyContinue
    Write-Host "Install failed at '$Step' - see $InstallLog" -ForegroundColor Red
    Get-Content -Path $InstallLog -Tail 12 -ErrorAction SilentlyContinue | ForEach-Object { Write-Output $_ }
    $code = $script:LastChildExit
    if (-not $code) {
        $code = 1
    }
    exit $code
}

function Show-Success {
    param([string]$Ver)
    $tick = [string]([char]0x2713)
    $isTty = -not [Console]::IsOutputRedirected
    if ($isTty) {
        Write-Output ""
        Write-Host ("{0} Installation complete" -f $tick) -ForegroundColor White
        Write-Output ""
        Write-Host "Run ``trace`` to get started."
        Write-Output ""
    } else {
        Write-Output "Installation complete"
        Write-Output ("Trace {0} installed successfully." -f $Ver)
    }
    # Trace is installed and `trace` is on PATH; a failing doctor is reported separately and
    # must not be reported as a completed install.
    if ($script:DoctorFailed) {
        $code = $script:LastChildExit
        if (-not $code) {
            $code = 1
        }
        exit $code
    }
}

function Test-TraceRef {
    param([string]$Ref)
    if ([string]::IsNullOrWhiteSpace($Ref) -or $Ref.StartsWith("-") -or $Ref.Contains("..")) {
        Write-Host "Invalid ref '$Ref'." -ForegroundColor Red
        exit 2
    }
}

function Test-ReleaseTag {
    param([string]$Tag)
    Test-TraceRef -Ref $Tag
    $gitCmd = Get-Command "git" -ErrorAction SilentlyContinue
    if ($gitCmd) {
        $out = & git ls-remote --tags https://github.com/nirjxr26/Trace.git "refs/tags/$Tag" 2>&1
        $pattern = "\s" + [regex]::Escape("refs/tags/$Tag") + "$"
        if (@($out | Where-Object { $_ -match $pattern }).Count -gt 0) {
            return
        }
        Write-Host "Unknown tag '$Tag'. Run with --list-versions to see releases." -ForegroundColor Red
        exit 1
    }
    $encoded = [uri]::EscapeDataString($Tag)
    try {
        Invoke-WebRequest -Uri "https://api.github.com/repos/nirjxr26/Trace/releases/tags/$encoded" -UseBasicParsing -TimeoutSec 60 -ErrorAction Stop | Out-Null
    } catch {
        Write-Host "Unknown tag '$Tag'. Run with --list-versions to see releases." -ForegroundColor Red
        exit 1
    }
}

function Show-ReleaseList {
    try {
        $releases = Invoke-RestMethod -Uri "https://api.github.com/repos/nirjxr26/Trace/releases?per_page=20" -TimeoutSec 60 -ErrorAction Stop
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
        if ([Console]::IsInputRedirected) {
            $confirm = Read-Host "Remove storage and config? Database server is kept. Type PURGE to confirm"
            if ($confirm -ne "PURGE") {
                Write-Output "Cancelled."
                exit 0
            }
        } else {
            $confirm = Read-Host "Remove storage and config? Database server is kept. Confirm y/N"
            if ($confirm -ne "y" -and $confirm -ne "Y") {
                Write-Output "Cancelled."
                exit 0
            }
        }
    }
    Remove-TracePath -Path $shim
    if (Test-Path $appDir) {
        Remove-TracePath -Path $appDir -Recurse
    }
    if ($envFile -and (Test-Path $envFile)) {
        Remove-TracePath -Path $envFile
    }
    $appEnv = Join-Path $Home ".trace\app\.env"
    if (Test-Path $appEnv) {
        Remove-TracePath -Path $appEnv
    }
    if ([bool]$PurgeData) {
        Remove-TracePath -Path (Join-Path $Home ".trace\trust") -Recurse
        Remove-TracePath -Path (Join-Path $Home ".trace\storage") -Recurse
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
Protect-TraceFile $InstallLog

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
        if ((-not (Test-Path (Join-Path $RepoRoot "pyproject.toml"))) -or [bool]$Reinstall -or ($Version -ne "")) {
            if (-not $env:TRACE_RELEASE_SHA256 -and -not $env:TRACE_COSIGN_BUNDLE_URL -and -not [bool]$AllowUnverified -and $env:TRACE_ALLOW_UNVERIFIED -ne "1") {
                Write-Host "  [!] Refusing unverified source. Pin TRACE_RELEASE_SHA256 or TRACE_COSIGN_BUNDLE_URL, or pass --allow-unverified (or set TRACE_ALLOW_UNVERIFIED=1)." -ForegroundColor Red
                Stop-TraceInstall "source"
            }
            if ($env:TRACE_COSIGN_BUNDLE_URL -and -not $env:TRACE_COSIGN_BUNDLE_URL.StartsWith("https://", [StringComparison]::OrdinalIgnoreCase)) {
                Write-Host "  [!] TRACE_COSIGN_BUNDLE_URL must use https://." -ForegroundColor Red
                Stop-TraceInstall "source"
            }
            if (-not (Test-Path $TraceHome)) {
                New-Item -ItemType Directory -Force -Path $TraceHome | Out-Null
            }
            $FinalRoot = $RepoRoot
            $script:StageRoot = "$RepoRoot.staging"
            $script:Staged = $true
            Remove-Item -Recurse -Force $script:StageRoot -ErrorAction SilentlyContinue
            $RepoRoot = $script:StageRoot
            $Token = $env:GH_TOKEN
            if (-not $Token) { $Token = $env:GITHUB_TOKEN }
            $TraceRef = if ($env:TRACE_REF) { $env:TRACE_REF } else { "main" }
            Test-TraceRef -Ref $TraceRef
            $RefKind = if ($TraceRef -like "v*") { "tags" } else { "heads" }
            $ArchiveUrl = "https://github.com/nirjxr26/Trace/archive/refs/$RefKind/$([uri]::EscapeDataString($TraceRef)).zip"
            $WebHeaders = if ($Token) { @{ Authorization = "Bearer $Token" } } else { @{} }

            $GitCmd = Get-Command "git" -ErrorAction SilentlyContinue
            if ($GitCmd -and -not $env:TRACE_RELEASE_SHA256 -and -not $env:TRACE_COSIGN_BUNDLE_URL) {
                Write-Trace ("Cloning repository via git (ref: {0})..." -f $TraceRef)
                try {
                    if ($Token) {
                        $AskPass = Join-Path ([IO.Path]::GetTempPath()) ("trace-askpass-" + [Guid]::NewGuid().ToString("N") + ".cmd")
                        Add-TraceTempArtifact $AskPass
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
                if ($env:TRACE_RELEASE_SHA256 -or $env:TRACE_COSIGN_BUNDLE_URL) {
                    Write-Trace "  Release pins set: verifying the downloaded archive before extraction."
                }
                if ($env:TRACE_COSIGN_BUNDLE_URL -and -not (Get-Command "cosign" -ErrorAction SilentlyContinue)) {
                    Write-Host "  [!] cosign missing: cannot verify the pinned signature. Aborting." -ForegroundColor Red
                    Stop-TraceInstall "source"
                }
                $ZipPath = Join-Path ([IO.Path]::GetTempPath()) ("trace-archive-" + [Guid]::NewGuid().ToString("N") + ".zip")
                $TempExtract = Join-Path ([IO.Path]::GetTempPath()) ("trace-extract-" + [Guid]::NewGuid().ToString("N"))
                Add-TraceTempArtifact $ZipPath
                Add-TraceTempArtifact $TempExtract
                try {
                    Invoke-TraceDownload -Uri $ArchiveUrl -OutFile $ZipPath -Headers $WebHeaders
                } catch {
                    Stop-TraceInstall "source"
                }
                if ($env:TRACE_RELEASE_SHA256) {
                    $ActualSha = (Get-FileHash -Path $ZipPath -Algorithm SHA256).Hash.ToLower()
                    if ($ActualSha -ne $env:TRACE_RELEASE_SHA256.ToLower()) {
                        Write-Host "  [!] Release digest mismatch: refusing to install." -ForegroundColor Red
                        Stop-TraceInstall "source"
                    }
                }
                if ($env:TRACE_COSIGN_BUNDLE_URL) {
                    $BundlePath = Join-Path ([IO.Path]::GetTempPath()) ("trace-bundle-" + [Guid]::NewGuid().ToString("N") + ".sigstore.json")
                    Add-TraceTempArtifact $BundlePath
                    try {
                        Invoke-TraceDownload -Uri $env:TRACE_COSIGN_BUNDLE_URL -OutFile $BundlePath -Headers $WebHeaders
                    } catch {
                        Stop-TraceInstall "source"
                    }
                    $OidcIssuer = if ($env:TRACE_COSIGN_OIDC_ISSUER) { $env:TRACE_COSIGN_OIDC_ISSUER } else { "https://token.actions.githubusercontent.com" }
                    if (-not $env:TRACE_COSIGN_IDENTITY) {
                        Write-Host "  [!] Set TRACE_COSIGN_IDENTITY to verify." -ForegroundColor Red
                        Stop-TraceInstall "source"
                    }
                    try {
                        Invoke-LoggedCommand -Action { param($bundle, $id, $issuer, $blob) & cosign verify-blob --bundle $bundle --certificate-identity $id --certificate-oidc-issuer $issuer $blob } -ActionArgs @($BundlePath, $env:TRACE_COSIGN_IDENTITY, $OidcIssuer, $ZipPath)
                    } catch {
                        Stop-TraceInstall "source"
                    }
                }
                if (-not $env:TRACE_RELEASE_SHA256 -and -not $env:TRACE_COSIGN_BUNDLE_URL) {
                    Write-Trace ("  [!] Installing unverified {0} by explicit opt-in." -f $TraceRef)
                }
                if (Test-Path $TempExtract) { Remove-Item -Recurse -Force $TempExtract -ErrorAction SilentlyContinue }
                New-Item -ItemType Directory -Force -Path $TempExtract | Out-Null
                try {
                    Expand-Archive -Path $ZipPath -DestinationPath $TempExtract -Force
                } catch {
                    Stop-TraceInstall "source"
                }
                $ExtractedFolders = @(Get-ChildItem -Directory -Path $TempExtract)
                if ($ExtractedFolders.Count -ne 1) {
                    Write-Host "  [!] Archive layout unexpected: expected one extracted directory." -ForegroundColor Red
                    Stop-TraceInstall "source"
                }
                $ExtractedFolder = $ExtractedFolders[0].FullName
                try {
                    Move-Item -Path $ExtractedFolder -Destination $RepoRoot -ErrorAction Stop
                } catch {
                    Stop-TraceInstall "source"
                }
                Remove-TraceTempArtifacts
            }
        }
    }
}

if ([bool]$Uninstall) {
    Uninstall-TraceApp -RepoRoot $RepoRoot
}

if ([bool]$Reinstall -and -not $script:Staged) {
    $defaultApp = Join-Path $Home ".trace\app"
    try {
        if ($RepoRoot -eq $defaultApp) {
            if (Test-Path $RepoRoot) {
                Remove-Item -Recurse -Force $RepoRoot -ErrorAction Stop
            }
        } else {
            $venvPath = Join-Path $RepoRoot ".venv"
            if (Test-Path $venvPath) {
                Remove-Item -Recurse -Force $venvPath -ErrorAction Stop
            }
            if (Test-Path $defaultApp) {
                Remove-Item -Recurse -Force $defaultApp -ErrorAction Stop
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

$InstallVersion = if ($script:DisplayVersion) { $script:DisplayVersion -replace '^v', '' } else { "main" }
Write-Output ""
Write-Output ("Installing Trace v{0}" -f $InstallVersion)

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
                if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 12)) {
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

Write-Trace ("Source ready at {0}" -f $RepoRoot)

$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if ($VerboseMode) {
    Write-Host "[2/6] Configuring virtual environment..." -ForegroundColor Yellow
}
if (-not (Test-Path $VenvPython)) {
    Write-Trace ("  Creating virtual environment at '{0}'..." -f $VenvDir)
    try {
        Invoke-LoggedCommand -Action { param($py, $vd) & $py -m venv $vd } -ActionArgs @($FoundPython, $VenvDir)
    } catch {
        Stop-TraceInstall "venv"
    }
} else {
    Write-Trace "  [OK] Existing virtual environment detected."
}

try {
    Invoke-LoggedCommand -Action { param($py) & $py -m pip --version } -ActionArgs @($VenvPython)
} catch {
    Write-Trace "  [i] The virtual environment has no pip; bootstrapping it with ensurepip."
    try {
        Invoke-LoggedCommand -Action { param($py) & $py -m ensurepip --upgrade } -ActionArgs @($VenvPython)
    } catch {
        Stop-TraceInstall "pip"
    }
}

if ($VerboseMode) {
    Write-Host "[3/6] Installing locked dependencies..." -ForegroundColor Yellow
    Write-Host "  Using pip with cryptographic hash verification..."
}
try {
    Invoke-LoggedCommand -Action { param($py) & $py -m pip install --quiet --require-hashes --only-binary :all: -r requirements-pip.txt } -ActionArgs @($VenvPython)
} catch {
    Write-Trace "  [i] Could not upgrade pip; continuing with the one bundled in the environment."
}
try {
    Invoke-LoggedCommand -Action { param($py) & $py -m pip install --quiet --require-hashes --only-binary :all: -r requirements.txt } -ActionArgs @($VenvPython)
} catch {
    Stop-TraceInstall "dependencies"
}
$EditableAttempt = 0
$EditableInstalled = $false
while (-not $EditableInstalled -and $EditableAttempt -lt 3) {
    $EditableAttempt += 1
    try {
        Invoke-LoggedCommand -Action { param($py) & $py -m pip install --quiet --no-deps -e . } -ActionArgs @($VenvPython)
        $EditableInstalled = $true
    } catch {
        if ($EditableAttempt -lt 3) {
            Write-Trace ("  [!] Editable install attempt {0} of 3 failed; retrying." -f $EditableAttempt)
            Start-Sleep -Seconds 2
        }
    }
}
if (-not $EditableInstalled) {
    Stop-TraceInstall "dependencies"
}
Write-Trace "  [OK] Dependencies installed successfully."

if ($script:Staged) {
    $StagedExe = Join-Path $VenvDir "Scripts\trace.exe"
    try {
        Invoke-LoggedCommand -Action { param($exe) & $exe --version } -ActionArgs @($StagedExe)
    } catch {
        Stop-TraceInstall "dependencies"
    }
    $OldEnv = Join-Path $FinalRoot ".env"
    if ((Test-Path $OldEnv) -and (-not (Test-Path (Join-Path $RepoRoot ".env")))) {
        Copy-Item $OldEnv (Join-Path $RepoRoot ".env")
    }
    $OldRoot = "$FinalRoot.old"
    Remove-TracePath -Path $OldRoot -Recurse
    try {
        if (Test-Path $FinalRoot) {
            Move-Item -Path $FinalRoot -Destination $OldRoot -ErrorAction Stop
        }
        Move-Item -Path $RepoRoot -Destination $FinalRoot -ErrorAction Stop
    } catch {
        if ((Test-Path $OldRoot) -and (-not (Test-Path $FinalRoot))) {
            try { Move-Item -Path $OldRoot -Destination $FinalRoot -ErrorAction Stop }
            catch { Stop-TraceInstall "source" }
        }
        Stop-TraceInstall "source"
    }
    Remove-TracePath -Path $OldRoot -Recurse
    $RepoRoot = $FinalRoot
    $VenvDir = Join-Path $RepoRoot ".venv"
    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    Set-Location $RepoRoot
    $script:StageRoot = ""
    $script:Staged = $false
    Write-Trace "  [OK] Staged install verified and swapped into place."
}

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
Protect-TraceFile $EnvFile

# Bootstrap anchor, established independently of the release channel. The channel
# only supplies key bytes; a bundle line is written solely when the id derived from
# its own content is one embedded here. An attacker who controls the channel can
# therefore withhold a key but can never introduce a new trust root. Adding one
# means editing this installer, which is reviewed code.
$BootstrapKeyIds = @("53712e8bb8a774e6")
$TrustDir = Join-Path $Home ".trace\trust\releases"
$Bundle = Join-Path ([IO.Path]::GetTempPath()) ("trace-keys-" + [Guid]::NewGuid().ToString("N") + ".bundle")
Add-TraceTempArtifact $Bundle
try {
    New-Item -ItemType Directory -Force -Path $TrustDir | Out-Null
    Invoke-TraceDownload -Uri "https://github.com/nirjxr26/Trace/releases/latest/download/trusted-keys.bundle" -OutFile $Bundle
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
    if ($Provisioned -gt 0) {
        Write-Trace ("  [OK] Release trust keys provisioned ({0} bootstrap anchor(s))." -f $Provisioned)
    } else {
        Write-Trace "  [!] Release bundle carried no known bootstrap anchor. Verification stays fail-closed."
    }
} catch {
    Write-Trace "  [!] Could not fetch release trust keys (offline or no release yet). Verification stays fail-closed until provisioned."
} finally {
    Remove-Item -Force $Bundle -ErrorAction SilentlyContinue
}

$DefaultStorage = Join-Path $Home ".trace\storage"
if (-not (Test-Path $DefaultStorage)) {
    New-Item -ItemType Directory -Force -Path $DefaultStorage | Out-Null
    Write-Trace ("  [OK] Created forensic storage directory at '{0}'." -f $DefaultStorage)
} else {
    Write-Trace "  [OK] Forensic storage directory exists."
}

$TraceExe = Join-Path $VenvDir "Scripts\trace.exe"

if ($VerboseMode) {
    Write-Host "[5/6] Verifying the forensic ledger..." -ForegroundColor Yellow
}
if (-not $SkipDbMigration) {
    try {
        Invoke-LoggedCommand -Action { param($exe) & $exe doctor } -ActionArgs @($TraceExe)
        Write-Trace "  [OK] Database verified and up to date."
    } catch {
        # The failure is reported and carried into the exit status. It used to be swallowed
        # into a log line, so an install onto a host that cannot verify its own records
        # finished successfully.
        $script:DoctorFailed = $true
        Write-Trace "  [!] 'trace doctor' did not pass, so this host is not verified."
        Write-Trace "      Run 'trace doctor' to see which check failed, fix it, then re-run the installer."
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
    if ($env:PATH -notlike "*$UserBin*") {
        $env:PATH = "$UserBin;$env:PATH"
    }
    Write-Trace ("  [OK] '{0}' is already in PATH." -f $UserBin)
}

Show-Success -Ver ("v{0}" -f $script:DisplayVersion)
