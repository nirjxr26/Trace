<div align="center">

<h1>Trace</h1>

Local-first forensic case management and device inspection with a tamper-evident chain of custody.

**v0.3.5 · Python 3.12+ · Windows / Linux / macOS · MIT**

</div>

> Trace is under active development. Storage layout, CLI surface, and database schema may still change between releases.

---
## Overview

Trace is a local-first, air-gap-ready forensic case management and device inspection engine built for digital forensics investigators and incident responders.

Core design rules:

- Case status transitions are strictly validated (`OPEN` → `UNDER_REVIEW` → `CLOSED`), and closure is permanent once sealed.
- Case identifiers are immutable and allocated under row-level locks to guarantee sequence safety under concurrent writers.
- Version-based collision detection backs every optimistic-concurrency write.
- Cross-entity links (cases ↔ devices) hold no database foreign keys: services validate targets at write time, purge never cascades, and retired records leave tombstones that read paths render as purged markers.
- Every mutation flows through a single path — UI / CLI → application service → domain invariants → repository → database — and mandatory audit entries are written inside the same transaction as the change they describe.
- All timestamps persist in canonical UTC; presentation-layer formatting (including IST) is applied only at render time.
- All state and forensic evidence resides locally or in your designated private database instance, with zero external telemetry.

---

## Features

### Case Management

- Deterministic chain-of-custody state machine with permanent closure sealing and examiner metadata.
- Concurrency-safe, monotonically incrementing case sequence allocation (`YYYY-CR-XXXX`, e.g. `2026-CR-0001`) with row-level locks.
- Full lifecycle: create, list, show, edit, review / resume, close, archive, restore, and purge.
- Purge guardrails: active cases can never be purged and must be archived first; purging requires typing the case number to confirm.
- Filtered and paginated listing, plus full-text search across titles, numbers, examiners, and notes.

### Device Inspection and Identity

- Adapter-based discovery: platform adapters for Linux block devices and Windows disks, plus a `file` adapter for image and evidence files. Real-hardware access is always an explicit opt-in.
- Identity capture (serial, size, model) recorded in the signed audit ledger, with per-identity history and JSONL export.
- Serial-less drives are identified by a hash of their observed characteristics, so a swapped disk in the same bay can never inherit the previous identity. Synthetic targets receive unique 128-bit serials.
- Write-protection gate: `trace device check` exits `10` when the source is writable and `9` when protection cannot be determined. Overrides require a typed acknowledgement.
- Case linking and unlinking; purged cases render as `(purged)` tombstones in every dossier.

### Audit Ledger and Chain of Custody

- Append-only, hash-chained ledger: every case, device, and update mutation is recorded with actor, action, and payload.
- Ledger rows are signed (Ed25519 keystore by default; HMAC via `TRACE_SECRET_KEY` when set). A signed chain-head tip with move-forward-only database protection makes tail rewinds and deletions detectable.
- Key lifecycle commands: `trace audit keys-init`, `keys-rotate` (retired keys keep verifying historical events), and `keys-list` (public keys only; private material is never displayed).
- `trace audit verify` produces structured verdicts for broken links, tampered rows, key problems, gaps, and column-level edits. External anchor files verify the ledger tail.
- `trace audit export` refuses a failing ledger and writes a signed JSONL bundle, optionally sealed with a passphrase and restorable with `trace audit decrypt`.

### Updates and Release Trust

- Signed release manifests are verified against the local trust store (`~/.trace/trust/releases/`) before anything is downloaded or installed.
- `trace update check` / `trace update install`: staged installs with health checks and automatic rollback on failure.
- `trace recovery` safely resolves state left behind by an interrupted update, under the update lock.
- `stable` and `beta` channels. Releases are tag-driven, reproducible (two builds compared byte-for-byte), published with SHA-256 sums and an SBOM, and immutable once published.

### Interfaces

- Interactive forensic console (`trace` with no arguments) with context-aware completion and ghost-text suggestions.
- Non-interactive Typer CLI for scripting and pipelines (`--help` on every command).
- Fullscreen Textual TUI (`trace tui`) with Cases, Devices, Audit, and Settings screens.
- Operations commands: `trace doctor` (preflight diagnostics), `trace db status | init | migrate`, and `trace uninstall [--purge-data]`.

---

## Tech Stack

| Layer | Technologies |
|---|---|
| Language / Runtime | Python 3.12+ |
| CLI | Typer, Rich; interactive console built on prompt-toolkit |
| TUI | Textual |
| Database | SQLAlchemy 2.x with SQLite or PostgreSQL 16 |
| Cryptography | Ed25519 / HMAC signing, SHA-256 hash chains (`cryptography`) |
| Architecture | Hexagonal (Ports and Adapters), UnitOfWork transactional boundaries |
| Quality Gates | Ruff (lint and format), Mypy (static type checking), Pytest (branch coverage ≥ 70%) |
| Supply Chain | Hash-pinned dependency chain, pip-audit, CycloneDX SBOM in CI |
| CI/CD | GitHub Actions: Ubuntu and Windows test matrix, PostgreSQL 16 integration, real update E2E, signed reproducible releases |
| Install | Cross-platform bootstrap scripts (`install.sh`, `install.ps1`) |


---

## Installation

### Prerequisites

Trace requires **Python 3.12+** and runs on Windows, Linux, and macOS.

### Option 1: Automated Install

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/nirjxr26/Trace/v0.3.4/install.ps1 | iex
```

**Linux / macOS (POSIX shell; also works in Git Bash on Windows):**

```bash
curl -fsSL https://raw.githubusercontent.com/nirjxr26/Trace/v0.3.4/install.sh | sh
```

Both commands are pinned to the `v0.3.4` release tag instead of the moving `main` branch.

The installer runs quietly by default and displays a live four-step progress list (Verifying, Downloading, Installing, Finishing setup). Detailed output is written to `~/.trace/install.log`. On success it prints `Installation complete` and `Trace vX.Y.Z installed successfully.`; on failure it prints `Install failed at '<step>' - see ~/.trace/install.log`.

The same four-step flow is shared with `trace update install`. When output is redirected (CI logs, `irm | iex`), animation and colour are disabled and each step prints a single plain line on completion. Use `--verbose` for numbered step-by-step detail.

| Flag | Effect |
|---|---|
| *(none)* | Quiet install of `main` (or `TRACE_REF` when set) |
| `--version <tag>` | Install the specified release |
| `--list-versions` | List releases; an interactive terminal offers pick-and-install |
| `--reinstall` | Wipe application code first, then install |
| `--uninstall` | Remove launcher, app, and config; keeps storage and database |
| `--uninstall --purge-data` | Also remove storage; asks for confirmation first and prints the drop command for PostgreSQL |
| `--verbose` | Full step-by-step output |
| `--help` | Show usage and exit with code 0 |

Storage and the database are never touched without `--purge-data`.

The installer validates the Python runtime, clones the repository to `~/.trace/app`, provisions an isolated virtual environment, installs hash-verified dependencies, sets up configuration and local forensic storage, runs schema migrations, and registers the global `trace` command.

### Option 2: Manual / Developer Setup

```bash
git clone https://github.com/nirjxr26/Trace.git trace
cd trace

python -m venv .venv
# Linux / macOS: source .venv/bin/activate
# Windows: .venv\Scripts\Activate.ps1

pip install --require-hashes --only-binary :all: -r requirements.txt
pip install --no-deps -e .

trace doctor
trace db init
trace db migrate
```

### First Run

```bash
trace            # interactive forensic console
trace tui        # fullscreen console
trace doctor     # preflight diagnostics: runtime, database, migrations, storage
```

---

## Configuration

Trace reads configuration from environment variables, a `.env` file in the repository root, or `~/.trace/.env` (template: `.env.example`). Unknown `TRACE_*` settings are reported and ignored.

| Variable | Description | Default |
|---|---|---|
| `TRACE_DATABASE_URL` | SQLAlchemy connection URL (PostgreSQL or SQLite, e.g. `sqlite:///trace.db`) | `postgresql+psycopg://postgres:postgres@localhost:5432/trace` |
| `TRACE_STORAGE_ROOT` | Root directory for cases, evidence, and forensic images | `~/.trace/storage` |
| `TRACE_SECRET_KEY` | Optional HMAC signing key. When unset (or left at the shipped placeholder), Trace generates an Ed25519 key in the local keystore on first use. Never rotate this while HMAC-signed ledger rows exist; rotation reads as tampering. | unset |
| `TRACE_ENV` | Deployment environment; `production` refuses the shipped default credentials and secret key | `development` |
| `TRACE_DEBUG` | Verbose diagnostic logging and stack traces | `false` |
| `TRACE_SQL_ECHO` | SQL statement echo. SQL logs carry case content; keep disabled in production. | `false` |
| `TRACE_UPDATE_CHANNEL` | Update channel | `stable` |
| `TRACE_UPDATE_MANIFEST` | Release manifest URL or local path; empty disables update checks | Official GitHub Releases manifest |
| `TRACE_DEVICE_ADAPTER` | Device adapter selection (`auto` / `file` / `linux` / `win32`); never bypasses the explicit hardware opt-in | `auto` |

---

## CLI Reference

| Command | Description |
|---|---|
| `trace` | Interactive forensic console (REPL) |
| `trace case create/list/show/edit/review/close/delete/restore` | Case lifecycle |
| `trace device list/inspect/check/history/export/link/unlink` | Device discovery, identity, write-protection |
| `trace audit show/verify/export/decrypt/keys-init/keys-rotate/keys-list` | Ledger inspection and verification |
| `trace db status/init/migrate` | Database health and schema management |
| `trace update check/install` | Update checks and installation |
| `trace tui` | Fullscreen console |
| `trace doctor` | Preflight diagnostics |
| `trace recovery` | Recover an interrupted update |
| `trace uninstall [--purge-data]` | Removal |

Every command supports `--help`.

---

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Application error |
| `2` | Usage / invalid input |
| `9` | Device preflight UNKNOWN: write protection could not be determined |
| `10` | Source is writable: write protection not confirmed |
| `11` | Update artifact trust failure |
| `12` | Record not found |
| `13` | Conflict |
| `14` | Update blocked |
| `15` | Recovery failed |
| `16` | Recovery retry required |
| `17` | Ledger tamper or distrust |

Exit code `9` is reserved for the device gate: configuration, database, and unexpected failures never masquerade as UNKNOWN.

---

## Development

```bash
python -m pytest tests -q            # full suite (SQLite in-memory by default)
python -m pytest tests/integration   # PostgreSQL integration (needs TRACE_TEST_POSTGRES_URL)
ruff format --check .                # formatting gate
ruff check .                         # lint gate
mypy src tests                       # static type check
```

- Dependencies flow `pyproject.toml` → `uv.lock` → hash-pinned `requirements.txt`. `tests/unit/test_lockfile_parity.py` fails the suite when they drift; regenerate with `uv lock` and re-export.
- Change history lives in `changelog/`.

---

## License

Trace is released under the MIT license (declared in `pyproject.toml`).