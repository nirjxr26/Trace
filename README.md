<div align="center">

# Trace

### Forensic Data Imaging & Retrieval Tool

[![CI](https://github.com/nirjxr26/Trace/actions/workflows/ci.yml/badge.svg)](https://github.com/nirjxr26/Trace/actions)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type Checked: mypy](https://img.shields.io/badge/type_checked-mypy_strict-blue.svg)](https://mypy.readthedocs.io/)
[![Database: PostgreSQL 16](https://img.shields.io/badge/database-PostgreSQL_16-336791.svg)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

<p align="center">
  <b>Trace</b> is a local-first, air-gap-ready forensic case management and data acquisition engine built for digital forensics investigators and incident responders.
</p>

---

</div>

## Highlights

- **Deterministic Chain of Custody**: Strictly validated state transitions (`OPEN` -> `UNDER_REVIEW` -> `CLOSED`), immutable case identifiers, and permanent closure sealing with examiner metadata.
- **Optimistic Concurrency & Sequence Safety**: Concurrency-safe, monotonically incrementing case sequence allocation (`YYYY-CR-XXXX`) with row-level locks and version-based collision detection.
- **Dual Presentation Interfaces**: Interactive full-featured terminal REPL (`trace`) with dynamic autocompletion and contextual ghost-text suggestions, alongside a non-interactive Typer CLI for automation and scripting.
- **Forensic High-Contrast TUI**: Clean, frameless, low-luminance aesthetic designed for long investigative sessions without visual fatigue, featuring status pills and structured dossiers.
- **Strict Time Invariant**: Canonical UTC domain persistence with localized presentation formatting (including Indian Standard Time - IST).
- **Zero-Friction Cross-Platform Install**: Single-command automated bootstrapping across Windows, Linux, and macOS.

---

## Quick Installation

Trace requires **Python 3.12+**. You can install and launch Trace with a single command:

### Windows (PowerShell)
Open PowerShell and run:
```powershell
irm https://raw.githubusercontent.com/nirjxr26/Trace/main/install.ps1 | iex
```

### Linux / macOS (POSIX Shell)
Open your terminal and run:
```bash
curl -fsSL https://raw.githubusercontent.com/nirjxr26/Trace/main/install.sh | sh
```

The automated installer:
1. Validates Python 3.12+ runtime availability.
2. Clones the repository to `~/.trace/app` (or downloads archive if Git is unavailable).
3. Creates an isolated virtual environment (`.venv`).
4. Installs locked dependencies verified against cryptographic SHA-256 hashes.
5. Provisions configuration (`.env`) and local forensic storage (`~/.trace/storage`).
6. Executes database schema initialization and migrations.
7. Registers the global `trace` command in your user PATH.

---

## Developer / Manual Setup

To inspect the source or contribute to Trace:

```bash
# 1. Clone the repository
git clone https://github.com/nirjxr26/Trace.git trace
cd trace

# 2. Run the local installer
# On Linux / macOS:
chmod +x install.sh && ./install.sh

# On Windows:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install.ps1
```

Or manually using `uv` or `pip`:
```bash
python -m venv .venv
# Linux / macOS: source .venv/bin/activate
# Windows: .venv\Scripts\Activate.ps1

pip install --require-hashes --only-binary :all: -r requirements.txt
pip install --no-deps -e .
trace db init
trace db migrate
```

---

## Usage Guide

### 1. Interactive Forensic REPL

Launch the interactive shell by typing:
```bash
trace
```

The shell provides:
- Context-aware tab completion for commands, flags, and active case numbers.
- Dynamic ghost-text suggestions (`TraceAutoSuggest`).
- Natural language aliases (`list cases`, `create case`, `show case <id>`).
- Active case context indicators.

```text
  ================================================================
         TRACE -- Forensic Data Imaging and Retrieval Tool        
  ================================================================
  Connected Database: PostgreSQL 16 (Local)
  Active Cases: 12 | System Time: 12-09-2026 03:15:20 PM IST

trace> case list
trace> case show 2026-CR-0001
trace> case close 2026-CR-0001 --reason "Acquisition verified" --by "Lead Examiner"
```

### 2. Standalone CLI Commands

Trace commands can be invoked directly from any shell or automation script:

#### Case Management
```bash
# Create a new forensic case
trace case create --number "2026-CR-0001" --title "Digital Drive Acquisition" --examiner "Investigator A" --tags "usb,laptop"

# List cases with optional filtering and pagination
trace case list --status OPEN --limit 10 --offset 0

# Search cases across titles, numbers, examiners, and notes
trace case list --search "Drive"

# Display a complete case dossier
trace case show 2026-CR-0001

# Update case details or append investigative notes
trace case edit 2026-CR-0001 --notes "Imaging completed with zero bad sectors."

# Formally seal and close an investigation
trace case close 2026-CR-0001 --reason "Forensic report submitted" --by "Investigator A"

# Soft-delete an archived case
trace case delete 2026-CR-0001

# Permanently purge an archived case (requires prior archiving)
trace case delete 2026-CR-0001 --purge
```

#### Database Operations & Schema Migrations
```bash
# Verify database connection and view migration history
trace db status

# Initialize tables and apply baseline migrations
trace db init

# Apply any pending schema migrations safely
trace db migrate
```

---

## Architectural Principles

Trace is engineered according to strict **Hexagonal Architecture** (Ports & Adapters) principles:

```
src/trace_core/
├── core/                   # Cross-cutting primitives
│   ├── database/           # Engine connection pool, session manager, schema migrations
│   ├── ui/                 # Minimalist TUI renderers, theme tokens, date formatters
│   ├── cli/                # Shared CLI argument parsers, error sanitizers
│   ├── domain.py           # BaseEntity, SoftDeleteMixin, canonical UTC timestamps
│   └── service.py          # UnitOfWork, transactional boundaries, audit hooks
├── cases/                  # Forensic Case Feature Module
│   ├── domain.py           # Case entity, CaseStatus state machine, invariants
│   ├── models.py           # SQLAlchemy declarative ORM mappings
│   ├── repository.py       # Thread-safe repository, sequence allocator with savepoints
│   ├── service.py          # CaseService, transaction management, DTO conversions
│   ├── commands.py         # Standalone Typer CLI command group
│   ├── shell_handler.py    # Interactive shell command handler and autocompleter
│   └── renderers.py        # Dossier and table presentation layer
└── cli/                    # CLI entrypoint (trace) and interactive REPL engine
```

### Core Invariants
- **Air-Gap Security**: Zero external telemetry; all state and forensic evidence resides locally or in your designated private database instance.
- **Fail-Safe Audit Boundaries**: Pre-commit hooks execute *inside* the database transaction; if an audit event or invariant check fails, the transaction aborts cleanly.
- **Safe Error Boundaries**: Database connection strings, filesystem paths, and internal stack traces are sanitized from user-facing screens unless explicitly run in debug mode.

---

## Verification & Testing

Trace maintains a strict testing regime with >=70% branch coverage, zero Ruff lint warnings, and zero Mypy type issues.

```bash
# Run unit tests and PostgreSQL integration suite
pytest -v

# Run with test coverage report
pytest --cov=src/trace_core --cov-report=term-missing

# Run static type checking
mypy src tests

# Run linter and formatting checks
ruff check .
ruff format --check .
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

---

## License

This project is licensed under the [MIT License](LICENSE).
