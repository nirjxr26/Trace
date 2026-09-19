# ==============================================================================
# Trace -- Automated Windows Installer
# Sets up Python virtual environment, dependencies, settings, and exposes 'trace'
# ==============================================================================

[CmdletBinding()]
param (
    [switch]$SkipDbMigration
)

$ErrorActionPreference = "Stop"

# Determine repository root (support local execution and remote 'irm ... | iex' execution)
$RepoRoot = $PSScriptRoot
if (-not $RepoRoot -or -not (Test-Path (Join-Path $RepoRoot "pyproject.toml"))) {
    if (Test-Path "pyproject.toml") {
        $RepoRoot = (Get-Location).Path
    } else {
        # Remote execution mode: download repository into $HOME\.trace\app
        $TraceHome = Join-Path $Home ".trace"
        $RepoRoot = Join-Path $TraceHome "app"
        Write-Host "Remote installation detected. Setting up Trace in '$RepoRoot'..." -ForegroundColor Cyan
        
        if (-not (Test-Path (Join-Path $RepoRoot "pyproject.toml"))) {
            if (-not (Test-Path $TraceHome)) {
                New-Item -ItemType Directory -Force -Path $TraceHome | Out-Null
            }
            $Token = $env:GH_TOKEN
            if (-not $Token) { $Token = $env:GITHUB_TOKEN }
            # Pinned ref: set $env:TRACE_REF to a signed release tag in production (default tracks main).
            $TraceRef = if ($env:TRACE_REF) { $env:TRACE_REF } else { "main" }
            $RefKind = if ($TraceRef -like "v*") { "tags" } else { "heads" }
            $ArchiveUrl = "https://github.com/nirjxr26/Trace/archive/refs/$RefKind/$TraceRef.zip"
            $WebHeaders = if ($Token) { @{ Authorization = "Bearer $Token" } } else { @{} }

            $GitCmd = Get-Command "git" -ErrorAction SilentlyContinue
            if ($GitCmd) {
                Write-Host "Cloning repository via git (ref: $TraceRef)..."
                if ($Token) {
                    # Never put secrets in the remote URL: GIT_ASKPASS answers from the
                    # environment, so nothing persists in .git/config or process listings.
                    $AskPass = Join-Path ([IO.Path]::GetTempPath()) ("trace-askpass-" + [Guid]::NewGuid().ToString("N") + ".cmd")
                    Set-Content -Path $AskPass -Value "@echo off`r`n@echo %TRACE_GIT_TOKEN%"
                    $OldAskPass = $env:GIT_ASKPASS
                    try {
                        $env:TRACE_GIT_TOKEN = $Token
                        $env:GIT_ASKPASS = $AskPass
                        $env:GIT_TERMINAL_PROMPT = "0"
                        & git clone --depth 1 --branch $TraceRef https://github.com/nirjxr26/Trace.git $RepoRoot
                    } finally {
                        Remove-Item -Force $AskPass -ErrorAction SilentlyContinue
                        Remove-Item Env:\TRACE_GIT_TOKEN -ErrorAction SilentlyContinue
                        if ($null -eq $OldAskPass) { Remove-Item Env:\GIT_ASKPASS -ErrorAction SilentlyContinue }
                        else { $env:GIT_ASKPASS = $OldAskPass }
                        Remove-Item Env:\GIT_TERMINAL_PROMPT -ErrorAction SilentlyContinue
                    }
                } else {
                    & git clone --depth 1 --branch $TraceRef https://github.com/nirjxr26/Trace.git $RepoRoot
                }
            } else {
                Write-Host "Downloading repository archive..."
                $ZipPath = Join-Path $TraceHome "trace-main.zip"
                $TempExtract = Join-Path $TraceHome "trace-temp"
                Invoke-WebRequest -Uri $ArchiveUrl -Headers $WebHeaders -OutFile $ZipPath
                if ($env:TRACE_RELEASE_SHA256) {
                    # Pinned release: verify digest before extraction, fail closed on mismatch.
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
                    Write-Host "  [!] No TRACE_RELEASE_SHA256 pinned: installing unverified $TraceRef." -ForegroundColor Yellow
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
Set-Location $RepoRoot

Write-Host ""
Write-Host "  ================================================================" -ForegroundColor Cyan
Write-Host "         TRACE -- Forensic Data Imaging and Retrieval Tool        " -ForegroundColor Cyan
Write-Host "                           Windows Installer                      " -ForegroundColor Cyan
Write-Host "  ================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Locate compatible Python (3.12+)
Write-Host "[1/6] Searching for Python 3.12+..." -ForegroundColor Yellow
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
                    Write-Host "  [OK] Found Python $versionOutput using '$cmd'" -ForegroundColor Green
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
    exit 1
}

# 2. Virtual Environment (.venv)
$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

Write-Host "[2/6] Configuring virtual environment..." -ForegroundColor Yellow
if (-not (Test-Path $VenvPython)) {
    Write-Host "  Creating virtual environment at '$VenvDir'..."
    & $FoundPython -m venv $VenvDir
} else {
    Write-Host "  [OK] Existing virtual environment detected." -ForegroundColor Green
}

# 3. Install Dependencies
Write-Host "[3/6] Installing locked dependencies..." -ForegroundColor Yellow
$UvCmd = Get-Command "uv" -ErrorAction SilentlyContinue

if ($UvCmd) {
    Write-Host "  Using uv for fast deterministic dependency installation..."
    & uv pip sync requirements.txt --python $VenvPython
    & uv pip install --no-deps -e . --python $VenvPython
} else {
    Write-Host "  Using pip with cryptographic hash verification..."
    # Pinned bootstrap toolchain (rotate with the lockfile, verify with: pip index versions pip)
    & $VenvPython -m pip install --quiet "pip==26.2.1"
    & $VenvPython -m pip install --quiet --require-hashes --only-binary :all: -r requirements.txt
    & $VenvPython -m pip install --quiet --no-deps -e .
}
Write-Host "  [OK] Dependencies installed successfully." -ForegroundColor Green

# 4. Environment & Storage Configuration
Write-Host "[4/6] Verifying environment and storage directories..." -ForegroundColor Yellow
$EnvFile = Join-Path $RepoRoot ".env"
$EnvExample = Join-Path $RepoRoot ".env.example"

if (-not (Test-Path $EnvFile)) {
    if (Test-Path $EnvExample) {
        Copy-Item $EnvExample $EnvFile
        Write-Host "  [OK] Created .env from template (.env.example)." -ForegroundColor Green
        Write-Host "  [!] Set a strong TRACE_DATABASE_URL password and TRACE_SECRET_KEY before production use." -ForegroundColor Yellow
    }
} else {
    Write-Host "  [OK] Existing .env file preserved." -ForegroundColor Green
}

$DefaultStorage = Join-Path $Home ".trace\storage"
if (-not (Test-Path $DefaultStorage)) {
    New-Item -ItemType Directory -Force -Path $DefaultStorage | Out-Null
    Write-Host "  [OK] Created forensic storage directory at '$DefaultStorage'." -ForegroundColor Green
} else {
    Write-Host "  [OK] Forensic storage directory exists." -ForegroundColor Green
}

# 5. Database Proof Gate (automatic init + migrate + verify in one run)
Write-Host "[5/6] Verifying database (auto-initializes schema on first use)..." -ForegroundColor Yellow
$TraceExe = Join-Path $VenvDir "Scripts\trace.exe"

if (-not $SkipDbMigration) {
    & $TraceExe doctor
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] Database verified and up to date." -ForegroundColor Green
    } else {
        Write-Host "  [!] Database unreachable. Trace will self-initialize on first use once it is reachable." -ForegroundColor Yellow
        Write-Host "      Start PostgreSQL or set TRACE_DATABASE_URL in .env, then run 'trace doctor' to verify." -ForegroundColor Yellow
    }
} else {
    Write-Host "  Skipping database verification as requested."
}

# 6. Expose 'trace' command globally
Write-Host "[6/6] Exposing 'trace' command to User PATH..." -ForegroundColor Yellow
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
    Write-Host "  [OK] Added '$UserBin' to User PATH." -ForegroundColor Green
} else {
    Write-Host "  [OK] '$UserBin' is already in PATH." -ForegroundColor Green
}

Write-Host ""
Write-Host "  ================================================================" -ForegroundColor Green
Write-Host "              TRACE INSTALLATION COMPLETED SUCCESSFULLY!          " -ForegroundColor Green
Write-Host "  ================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  You can now run Trace from any terminal by typing:"
Write-Host "      trace" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Quick test:"
Write-Host "      trace case list" -ForegroundColor Cyan
Write-Host ""
