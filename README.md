<div align="center">

<h1>Trace</h1>

</div>

Local-first forensic case management and data acquisition with secure chain of custody, safe case sequencing, and air-gap-ready storage..

> Project is still in its development phase.

---

## Overview

Trace is a local-first, air-gap-ready forensic case management and data acquisition engine built for digital forensics investigators and incident responders.

Core design rules:

- Case status transitions are strictly validated (`OPEN` → `UNDER_REVIEW` → `CLOSED`) and closure is permanent once sealed.
- Case identifiers are immutable and allocated under row-level locks to guarantee sequence safety under concurrent writers.
- Version-based collision detection backs every optimistic-concurrency write.
- All timestamps persist in canonical UTC; presentation-layer formatting (including IST) is applied only at render time.
- Zero external telemetry — all state and forensic evidence resides locally or in your designated private database instance.

---

## Features

**Case Management**

- Deterministic chain-of-custody state machine with permanent closure sealing and examiner metadata.
- Concurrency-safe, monotonically incrementing case sequence allocation (`YYYY-CR-XXXX`) with row-level locks.
- Full case lifecycle: create, list, search, edit, close, soft-delete, and purge.
- Filtered and paginated case listing, plus full-text search across titles, numbers, examiners, and notes.

**Presentation Interfaces**

- Interactive terminal REPL (`trace`) with context-aware tab completion and dynamic ghost-text suggestions.
- Natural-language command aliases (`list cases`, `create case`, `show case <id>`).
- Non-interactive Typer CLI for scripting and automation pipelines.
- Forensic-grade, high-contrast, low-luminance TUI designed for long investigative sessions.

**Data & Time Integrity**

- Canonical UTC domain persistence with localized presentation formatting.
- Structured case dossiers with active case context indicators.

**Deployment & Install**

- Single-command automated bootstrapping across Windows, Linux, and macOS.
- Locked dependencies verified against cryptographic SHA-256 hashes.
- Automated schema initialization and migrations on install.

---

## Tech Stack

| Layer | Technologies |
|---|---|
| Language / Runtime | Python 3.12+ |
| CLI Framework | Typer |
| Interactive Shell | Custom REPL with autocompletion, ghost-text suggestions |
| Database | PostgreSQL 16, SQLAlchemy (declarative ORM) |
| Architecture | Hexagonal (Ports & Adapters), UnitOfWork transactional boundaries |
| Quality Gates | Ruff (lint + format), Mypy (strict), Pytest (≥70% branch coverage) |
| CI/CD | GitHub Actions |
| Install | Cross-platform bootstrap scripts (`install.sh`, `install.ps1`) |

---

## Architecture

Trace is engineered according to strict **Hexagonal Architecture** (Ports & Adapters) principles:

```
src/trace_core/
├── core/                   
│   ├── database/           
│   ├── ui/                 
│   ├── cli/                
│   ├── domain.py           
│   └── service.py          
├── cases/                 
│   ├── domain.py           
│   ├── models.py           
│   ├── repository.py       
│   ├── service.py          
│   ├── commands.py         
│   ├── shell_handler.py    
│   └── renderers.py       
└── cli/                   
```
---

## Quick Start

### Prerequisites

Trace requires **Python 3.12+**.

### Option 1 — Automated Install (quiet by default)

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/nirjxr26/Trace/main/install.ps1 | iex
```

**Linux / macOS (POSIX Shell — also works in Git Bash on Windows):**
```bash
curl -fsSL https://raw.githubusercontent.com/nirjxr26/Trace/main/install.sh | sh
```

Default runs show one live green download block (`Downloading Trace vX.Y.Z...` plus a single 20-cell bar counting 0 to 100 percent in real time with no speed or ETA; long steps keep a pulse so it never stalls). Everything else goes to `~/.trace/install.log`. Success ends in two green lines: `Installation complete` plus `Trace vX.Y.Z installed successfully.`. Failures end in `Install failed at '<step>' - see ~/.trace/install.log`.

| Flag | Effect |
|---|---|
| *(none)* | Quiet install of `main` (or `TRACE_REF` when set) |
| `--version <tag>` | Install that release instead |
| `--list-versions` | List releases; TTY offers pick-and-install |
| `--reinstall` | Wipe app code first, then install |
| `--uninstall` | Remove launcher + app + config; keeps storage and database |
| `--uninstall --purge-data` | Also remove storage; confirms first, prints drop line for Postgres |
| `--verbose` | Full step-by-step output |
| `--help` | Usage; exit 0 |

Storage and the database are never touched without `--purge-data`. Details live in `docs/INSTALLER_UX.md`.

The installer validates the Python runtime, clones the repository to `~/.trace/app`, provisions an isolated virtual environment, installs hash-verified dependencies, sets up configuration and local forensic storage, runs schema migrations, and registers the global `trace` command.

### Option 2 — Manual / Developer Setup

```bash
git clone https://github.com/nirjxr26/Trace.git trace
cd trace

python -m venv .venv
# Linux / macOS: source .venv/bin/activate
# Windows: .venv\Scripts\Activate.ps1

pip install --require-hashes --only-binary :all: -r requirements.txt
pip install --no-deps -e .

trace db init
trace db migrate
```

---

## Configuration

Trace is configured via environment variables or a `.env` file in the project root:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `TRACE_DATABASE_URL` | SQLAlchemy connection string | `postgresql+psycopg://postgres:postgres@localhost:5432/trace` |
| `TRACE_STORAGE_PATH` | Local forensic image & artifact root | `~/.trace/storage` |
| `TRACE_DEBUG` | Enable verbose diagnostic logging and stack traces | `False` |
| `TRACE_LOG_LEVEL` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
