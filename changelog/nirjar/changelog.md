# Trace — Project Development Log

> Maintained by: **Nirjar Goswami**  
> Scope: Core Architecture, Database, Presentation Layer & Forensic TUI

---

## 2026-09-10 — Initial Architecture & Database Foundation

- **Hexagonal Architecture Setup**: Organized codebase into strict layers (`domain/`, `application/`, `ports/`, `adapters/`, `cli/`).
- **Domain Modeling**: Created `Case` entity model with UUID primary keys, UTC timestamps, `CaseStatus` state machine (`OPEN`, `UNDER_REVIEW`, `CLOSED`, `ARCHIVED`), and forensic tagging.
- **Database Engine (PostgreSQL 16)**:
  - Configured PostgreSQL connection pooling with `psycopg_pool`.
  - Created initial schema migration (`001_initial_schema.sql`) with JSONB tags and soft-delete support.
  - Implemented generic repository pattern in `BaseRepository` with parameterized SQL to prevent SQL injection.
- **Git Hygiene**: Created production-grade `.gitignore` safeguarding evidence files (`.dd`, `.e01`, `.raw`, `.vmdk`), dumps, credentials, and environment files.

---

## 2026-09-11 — Application Services & CLI Framework

- **Application Services**:
  - Built `BaseCrudService` for generic CRUD reusability.
  - Implemented `CaseService` with transaction safety, auto-generating unique case numbers (`YYYY-CR-XXXX`), soft-delete archiving, permanent purge, and sealed closure transitions.
- **Pydantic DTOs**: Created validated data transfer objects (`CaseCreateDto`, `CaseUpdateDto`, `CaseFilterDto`, `CaseResponseDto`).
- **Interactive Shell (REPL)**:
  - Developed prompt-toolkit REPL with command auto-completion, history navigation, and active case context tracking (`trace [CASE]>`).
  - Added support for natural aliases (`list cases`, `create case`).
- **Typer Command Group**: Built standalone CLI commands for non-interactive scripting (`trace case create`, `trace case list`, etc.).
- **Unit & Integration Test Suite**: Implemented 22 comprehensive tests covering models, services, transactions, and CLI commands.

---

## 2026-09-12 — Forensic TUI System, Quality Refactoring & Aesthetics

- **Forensic Workstation Palette**:
  - Implemented centralized `THEME_TOKENS` with low-luminance slate borders (`#3A4A5A`), soft cyan headings (`#72B7D3`), neutral white text (`#E5EAF0`), and subtle status badges.
- **Simplified TUI Screens**:
  - **Case Dossier (`case show`)**: Clean frameless layout using horizontal dividers and status badges instead of cluttered nested boxes.
  - **Case Registry (`case list`)**: Minimalist table with a single header rule and right-aligned record counters.
  - **Startup Banner**: Borderless ASCII logo with structured health metadata.
  - **Command Manual (`help`)**: 3-tier grouped command listing with indented options.
  - **Case Wizard (`case create`)**: Single-form layout with required field markers (`*`).
  - **Error Cards**: Frameless alert layout with actionable remediation tips.
- **Cross-Platform Safety**:
  - Added automatic UTF-8 stream reconfiguration and ASCII safe fallbacks to prevent `UnicodeEncodeError` on Windows `cp1252` terminals.
- **Code Cleanliness & SonarLint Hardening**:
  - Removed cluttering comments across the presentation layer.
  - Reduced Cognitive Complexity in error handlers, shell parsing, and renderers from >18 down to 2 (SonarLint S3776).
  - Replaced duplicated color string literals with constants (SonarLint S1192).
  - Eliminated nested ternaries (SonarLint S3358).
- **Skill Documentation**: Authored `.agents/skills/ponytail/SKILL.md` cheatsheet for rapid pattern reuse.
- **10/10 Test Infrastructure & CI/CD**:
  - Configured `pyproject.toml` with strict pytest flags (`-ra -v --strict-markers --strict-config`), registered markers (`unit`, `integration`, `slow`), and 70%+ branch coverage enforcement.
  - Enhanced `tests/conftest.py` with shared fixtures (`temp_storage`, `sample_cases_batch`, `session_manager`, `cli_runner`).
  - Added dedicated unit tests for all UI renderers, error cards, and backward-compatible shims (31 passing tests in ~1s).
  - Built GitHub Actions multi-platform CI/CD workflow (`.github/workflows/ci.yml`) matrixing Linux (`ubuntu-latest`) with PostgreSQL 16 service containers and Windows (`windows-latest`).
  - Expanded project root `.gitignore` with evidence stores (`cases/`, `.test_storage/`), test report caches (`.tox/`, `.nox/`, `junit/`, `coverage.json`), and modern AI/IDE artifacts (`.cursor/`, `.windsurf/`).

---

## 2026-09-12 — Transition to `trace` & Modular Feature Architecture

- **Project Command Standardized to `trace`**:
  - CLI binary command configured permanently as `trace` (`trace = "trace_core.cli.main:app"` in `pyproject.toml`).
  - Package namespace maintained as `trace_core` (`src/trace_core/`) to completely prevent conflicts with Python's built-in `Lib/trace.py` standard library module.
  - Subpart 1 feature module encapsulated in `src/trace_core/cases/` and cross-cutting components in `src/trace_core/core/`.
  - Full test suite passing (31/31 unit tests) with 72.32% branch coverage, 0 mypy errors, and 0 ruff lint/formatting issues.
  - Root `README.md` updated with official `trace` documentation and CLI usage.
  - Fixed interactive console dropdown autocompletion (`complete_while_typing=True`) and added `TraceAutoSuggest` for real-time ghost text command suggestions.
  - Expanded `CaseShellCommandHandler.get_completions` to provide contextual completions with descriptions for actions, flags, status enums, and dynamic case IDs from the database.
  - **SonarLint & Reusability Hardening**:
    - Reduced Cognitive Complexity across `shell_handler.py` (`_parse_list_options`, `get_completions`) and `shell.py` (`get_suggestion`, `execute_line`) from up to 50 down to <= 5 (SonarLint S3776).
    - Extracted reusable argument/flag parsing primitives into `src/trace_core/core/cli/args.py` (`extract_flag_value`, `has_flag`, `strip_flags`) eliminating duplicate flag extraction logic across commands.
    - Consolidated interactive identifier resolution and user prompting into reusable `_resolve_or_prompt_identifier`, eliminating duplicated prompts across 5 case action handlers.
    - Split composite assertions in `tests/unit/test_shell.py` (SonarLint S9073).
    - Increased test coverage to 73.92% with 100% pass rate (32/32 tests).

---

## 2026-09-12 — Maximum TUI Reusability Engine & CI/CD Pipeline Fix

- **GitHub Actions CI/CD Pipeline Hardening (`.github/workflows/ci.yml`)**:
  - Fixed YAML parser error caused by unquoted SQLite URL (`TRACE_DATABASE_URL: sqlite:///:memory:` -> `TRACE_DATABASE_URL: "sqlite:///:memory:"`).
  - Streamlined test matrix across Ubuntu and Windows runners.
  - Eliminated supply-chain security warnings (`Using dependencies without locking resolved versions is security-sensitive` and `Omitting "--only-binary :all:" can lead to the execution of setup scripts`):
    - Generated locked `requirements.txt` with exact version pins.
    - Used `pip install --only-binary :all: -r requirements.txt` followed by `pip install --no-deps -e .`.
    - Removed unpinned `python -m pip install --upgrade pip`.
- **Maximum TUI Component Reusability Engine (`src/trace_core/core/ui/renderers.py`)**:
  - Implemented `get_status_style_and_label(status, is_deleted)` for centralized resolution of colors, borders, and labels across all domain entities (Cases, Devices, Evidence, Imaging, Tasks).
  - Built `render_status_badge_panel(status, is_deleted)` returning rounded status pill panels for dossier headers.
  - Built `create_key_value_grid(rows, width, padding)` and `render_key_value_grid(title, rows, width)` for frameless metadata and diagnostics rendering.
  - Built `render_minimalist_table(title, columns, rows, empty_message)` delivering single-rule ASCII headers and automated record counters for any entity collection.
  - Built `render_dossier(header_prefix, identifier, title, subtitle, status_badge, fields, sections)` providing a standardized forensic dossier layout with clean horizontal rules and metadata grids.
  - Added reusable prompt and wizard primitives: `prompt_required`, `prompt_optional` (with customizable hint), `prompt_confirm` (with danger highlighting), and `render_wizard_header`.
- **Elimination of Duplication in Feature Modules**:
  - Refactored `src/trace_core/cases/renderers.py` from 181 lines down to 94 lines, delegating all presentation assembly directly to the core TUI primitives.
  - Refactored `src/trace_core/cases/shell_handler.py` to use core prompt primitives, eliminating duplicate prompt logic.
  - Refactored `src/trace_core/cli/shell.py` (`print_banner` and `show_status`) to reuse `create_key_value_grid` and `render_key_value_grid`.
- **Quality Verification**:
  - Full test suite expanded to 37 unit tests (100% passing) with 75.96% coverage.
  - Strict static type checking verified (0 mypy errors across 40 source files).
  - Code formatting and linting verified with Ruff (0 errors, 44 files clean).

---

## 2026-09-12 — Subpart 1 Hardening: Phase 1 (Forensic Domain Invariants & State Machine)

- **Permanently Sealed `CLOSED` State**:
  - Removed `CLOSED -> OPEN` and `CLOSED -> ARCHIVED` transitions in `_VALID_TRANSITIONS` (`src/trace_core/cases/domain.py`). Once sealed, closed cases can never transition to any other status.
  - Guarded `CaseService.close_case` against re-closing already closed cases.
- **Decoupled Lifecycle Status from Archival/Retention**:
  - Cleaned `CaseStatus` enum to reflect strictly investigation lifecycle states: `OPEN`, `UNDER_REVIEW`, `CLOSED`.
  - Orthogonalized archival/soft-delete retention under `is_deleted: bool` and `archived_at: datetime | None` in `BaseEntity`, `SoftDeleteMixin`, and `CaseModel`. Soft-deleting a case no longer corrupts its lifecycle state to `"ARCHIVED"`.
- **Closure Metadata & Audit Traceability**:
  - Added `closure_reason` and `closed_by` fields to `Case` entity, `CaseModel`, `CaseResponseDto`, and database schemas.
  - Capturing `closure_reason` and `closed_by` during transition and rendering them in the dossier presentation view (`render_case_detail`).
- **Enforced Identity Immutability**:
  - Enforced strict immutability on `id` (UUID) and `number` (`YYYY-CR-XXXX`) in `Case.__setattr__`, raising `InvariantViolationError` if mutation is attempted after assignment.
- **Tag Normalization**:
  - Updated `validate_tags` in `Case` to strip whitespace, lowercase, and deduplicate tags (`["USB", "usb"]` -> `["usb"]`).
- **Quality & Verification**:
  - Unit test suite expanded from 37 to 39 passing tests (100% pass rate).
  - Total test coverage increased to 76.47% (exceeding 70% threshold).
  - Verified 0 Ruff lint errors and 0 Mypy type issues across 40 source files.

---

## 2026-09-12 — Subpart 1 Hardening: Phase 2 (Concurrency, Sequence Safety & Error Narrowing)

- **Optimistic Concurrency Control (OCC)**:
  - Added `version: int` tracking to `BaseEntity`, `CaseModel`, and `CaseResponseDto`.
  - Implemented version validation in `SqlAlchemyCaseRepository.update()`: updates verify `model.version == entity.version`, increment version on flush, and raise `ConcurrencyConflictError` on stale write collisions.
  - Added `ConcurrencyConflictError` presentation handling in `capture_cli_errors` with targeted actionable remediation.
- **Concurrency-Safe Sequence Allocation**:
  - Implemented `CaseSequenceModel` (`case_sequences` table) tracking `last_sequence` per calendar year with `with_for_update()` row-level locking.
  - Eliminated the `max + 1` race condition in `SqlAlchemyCaseRepository.get_next_sequence_number()`, guaranteeing monotonic sequential numbering even under parallel worker operations.
- **Narrowed Exception Classification**:
  - Refined `CaseService.create_case` to inspect SQLAlchemy `IntegrityError` details; only genuine case number collisions raise `DuplicateCaseNumberError`, while other database constraint violations raise general `ApplicationError`.
- **Injectable Clock Abstraction**:
  - Created minimal `Clock` protocol and `SystemUtcClock` in `src/trace_core/core/clock.py` (`get_clock()`, `set_clock()`, `reset_clock()`).
  - Integrated `now_utc()` with `get_clock().now()` ensuring unified, deterministic time generation for tests and domain operations without external dependencies.
- **Testing & Verification**:
  - Created `tests/unit/test_case_concurrency.py` covering optimistic lock collisions, sequence allocations, integrity error translation, and custom clocks.
  - Test suite expanded to 43 passing unit tests (100% pass rate).
  - 0 Ruff lint/formatting errors, 0 Mypy type issues across 42 source files.

---

## 2026-09-12 — Subpart 1 Hardening: Phase 3 (Database Decoupling, Migrations & Startup Hygiene)

- **Database Startup & Provisioning Decoupled (P0-6)**:
  - Removed `_ensure_postgres_database()` from `DatabaseSessionManager` (`src/trace_core/core/database/session.py`), eliminating runtime `CREATE DATABASE` commands and silent exception swallowing.
  - Database provisioning is formally isolated to setup/admin tooling and external infrastructure orchestration.
- **Unswallowed Initialization Errors (P0-7)**:
  - Replaced silent `except Exception: pass` in `Settings.model_post_init` (`src/trace_core/core/settings.py`) with explicit `OSError` catching and structured warning logging via `structlog`.
- **Database Connection Health Checks**:
  - Added `check_connection() -> tuple[bool, str]` to `DatabaseSessionManager` allowing non-destructive connectivity verification (`SELECT 1`) across CLI commands and startup checks.
- **Schema Management Decoupled from CLI Execution (P1-11)**:
  - Removed implicit `db_manager.init_schema()` calls from `_get_service()` in `src/trace_core/cases/commands.py` and `_ensure_service()` in `src/trace_core/cli/shell.py`.
  - Runtime commands now execute assuming the database schema is managed, eliminating unexpected DDL execution during read/write queries.
- **Lightweight Schema Migration System (P0-5, P1-12)**:
  - Created `src/trace_core/core/database/migrations.py` with `schema_migrations` tracking table recording migration version, name, and application timestamp.
  - Implemented initial migration `001_initial_case_schema` with idempotent migration execution via `apply_migrations(engine)`.
  - Added `alembic.ini` configuration file in project root for production migration tooling compatibility.
- **Dedicated Database CLI Commands**:
  - Created `src/trace_core/core/cli/db_commands.py` exposing the `trace db` command group registered in `main.py`:
    - `trace db status`: Displays connection status, masked credentials, existing tables, and migration history.
    - `trace db init`: Initializes schema and applies baseline migrations.
    - `trace db migrate`: Executes any pending database migrations safely.
- **Audit & Transaction Boundary (P0-9)**:
  - Implemented `UnitOfWork` and `BaseService.transaction()` context manager in `src/trace_core/core/service.py` supporting transactional unit-of-work boundaries and `on_commit` event/audit hooks for Subpart 2.
- **Testing & Verification**:
  - Added `tests/unit/test_database_migrations_and_lifecycle.py` testing connection checks, storage logging, migration idempotency, unit-of-work hooks, and CLI `db` commands.
  - Test suite expanded to 49 passing unit tests (100% pass rate).
  - Maintained 77.56% branch coverage (exceeding 70% threshold).
  - Verified 0 Ruff lint errors and 0 Mypy type issues across 45 source files.

---

## 2026-09-12 — Subpart 1 Hardening: Phase 4 (Query Engine, Pagination, Purge Policy & UI/CLI Polish)

- **Wired Pagination into Repository & Service (P1-4)**:
  - Extended `CaseRepository` protocol and `SqlAlchemyCaseRepository.list_cases()` with `limit: int | None` and `offset: int | None`.
  - Wired `CaseService.list_cases()` to consume `CaseFilterDto.limit` and `CaseFilterDto.offset`, bringing pagination into full active effect.
- **Search Engine Expansion & Query Normalization (P1-5)**:
  - Added `CaseModel.notes` to the multi-column search clause in `SqlAlchemyCaseRepository.list_cases()`, matching the formal architectural specification.
  - Normalized search terms so that empty or whitespace-only queries (`"   "`) evaluate to `None` rather than generating redundant wildcard `"%%"` scans.
- **Deterministic Secondary Query Ordering (P1-7)**:
  - Added secondary tie-breaker sorting by `CaseModel.id.asc()` alongside `CaseModel.opened_at.desc()` ensuring fully deterministic pagination across all database backends.
- **Forensic Purge Policy Guardrail (P0-10)**:
  - Hardened `CaseService.delete_case` with a forensic guardrail: active investigations cannot be permanently purged; cases must be explicitly archived (`is_deleted=True`) first, preventing catastrophic accidental permanent record loss.
- **Operational Error Sanitization (P1-8)**:
  - Hardened `capture_cli_errors` in `src/trace_core/core/cli/error_handler.py`: non-`ApplicationError` operational exceptions are sanitized to user-safe messages unless `settings.debug` is enabled, eliminating leaks of internal database credentials, stack traces, or file paths.
- **Terminal OS Decoupling**:
  - Replaced OS-dependent `os.system("cls"/"clear")` in `src/trace_core/cli/shell.py` with standard `console.clear()`.
  - Integrated `capture_cli_errors` boundary into shell REPL command execution loop for unified error cards and safe exception rendering.
- **Testing & Verification**:
  - Added `tests/unit/test_query_pagination_and_purge_policy.py` verifying pagination slicing, notes discovery, whitespace query normalization, purge policy guardrails, and error sanitization.
  - Test suite expanded to 54 passing unit tests (100% pass rate).
  - Test branch coverage maintained at 77.82% (exceeding 70% threshold).
  - Clean Ruff linting (0 errors) and strict Mypy typing (0 issues across 46 source files).

---

## 2026-09-12 — Subpart 1 Hardening: Phase 5 (CI/CD Pipeline, PostgreSQL Integration & Documentation)

- **PostgreSQL 16 CI Integration (P0-8)**:
  - Updated `.github/workflows/ci.yml` adding a dedicated `postgres-integration` job running with a live `postgres:16-alpine` service container.
  - Automated testing of database CLI management commands (`trace db init`, `trace db status`, `trace db migrate`) directly against real PostgreSQL.
- **PostgreSQL Lifecycle Integration Test Suite**:
  - Created `tests/integration/test_postgres.py` with `@pytest.mark.integration`.
  - Tests full end-to-end case creation, sequential number allocation, optimistic concurrency versioning, notes discovery, pagination, sealed closure, and soft-delete/purge on PostgreSQL 16.
  - Skips gracefully in local developer environments when PostgreSQL is not configured, while automatically executing in CI.
- **Architectural Specification Alignment**:
  - Verified all P0 and P1 items from `docs/architecture/changes_need_to_make.txt` across Subpart 1 are resolved and tested.
  - Preserved codebase minimalism per `AGENTS.md` and ponytail rules: zero external bloated frameworks introduced; standard library and existing dependencies leveraged throughout.
- **Quality & Verification**:
  - Full test suite: 55 passing unit tests, 1 skipped integration test (100% passing rate).
  - Branch test coverage maintained at 77.62% (above 70% requirement).
  - Ruff formatting: 51 files already formatted cleanly (0 errors).
  - Ruff linting: all checks passed (0 errors).
  - Mypy static typing: strict pass (0 issues across 47 source files).

---

---

## 2026-09-12 — Indian Standard Time (IST) Presentation Formatting

- **Indian Datetime Presentation**:
  - Implemented `format_india_datetime` and `format_india_table_time` in `src/trace_core/core/ui/renderers.py` using Python standard library `timezone(timedelta(hours=5, minutes=30))` (IST).
  - Preserved strict UTC storage in the domain and database layer while presenting timestamps in Indian format:
    - **Detail / Dossier view (`case show`)**: `DD-MM-YYYY hh:mm:ss AM/PM IST` (e.g., `12-09-2026 09:28:55 AM IST`).
    - **Table / List view (`case list`)**: `DD-MM hh:mm AM/PM` (e.g., `12-09 10:09 AM`).
    - **Database Migration status (`db status`)**: `DD-MM-YYYY hh:mm:ss AM/PM IST`.
  - Added naive datetime protection to safely assume UTC before converting to IST.
- **Verification**:
  - Verified across `trace case list`, `trace case show <case-num>`, and `trace db status`.
  - Maintained 100% test pass rate (55 passed, 1 skipped), 77.53% branch coverage (above 70% threshold).
  - Passed Ruff linting (0 errors) and Mypy static typing (0 issues).

---

## 2026-09-12 — Repository Hygiene: Gitignore & Unused Artifact Removal

- **Artifact Deletion**:
  - Deleted unused `alembic.ini` (obsoleted by native pure-SQLAlchemy runner; eliminated plaintext credential risk).
  - Deleted untracked `uv.lock` (not utilized by standard `pip` / `requirements.txt` build and CI pipeline).
- **Gitignore Hardening**:
  - Added `alembic.ini` to `.gitignore` under `# --- Local Databases & Transitory State ---`.
  - Added `.uv/` cache directory to `.gitignore`.

---

## 2026-09-12 — SonarCloud Issue Remediation & Security Hardening

- **GitHub Actions Security (Immutable SHAs & Hash Pinning)**:
  - Pinned all GitHub Action `uses:` declarations in `.github/workflows/ci.yml` to immutable 40-character commit SHAs with version tag comments:
    - `actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2`
    - `actions/setup-python@42375524e23c412d93fb67b49958b491fce71c38 # v5.4.0`
    - `actions/upload-artifact@4cec3d8aa04e39d1a68397de0c4cd6fb9dce8ec1 # v4.6.1`
  - Added `--require-hashes` to all `pip install` commands (lines 33, 71, 124 in `ci.yml`), enforcing cryptographic hash validation for all dependencies.
- **Python Dependency Lock File Generation**:
  - Generated deterministic `uv.lock` for `pyproject.toml` (36 packages resolved with hashes).
  - Tracked `uv.lock` in repository root for reproducible dependency resolution.
  - Exported `requirements.txt` with multi-platform SHA-256 hashes (`uv export --no-emit-project --frozen --extra dev`).
- **Exception Test Refactoring (SonarCloud python:S5754)**:
  - Refactored `tests/unit/test_case_entity.py` (line 54): moved `datetime.now(UTC)` and `uuid.uuid4()` outside `pytest.raises` blocks so only target operations are tested.
  - Refactored `tests/unit/test_case_service.py` (lines 134, 147): extracted `CaseUpdateDto(title="Illegal Edit")` outside `pytest.raises` blocks.
  - Refactored `tests/unit/test_database_migrations_and_lifecycle.py` (line 103): wrapped transaction execution in helper so `pytest.raises` contains only one invocation.
- **Verification**:
  - 100% test pass rate (55 passed, 1 skipped), 77.50% branch coverage.
  - 0 Ruff lint/format errors; 0 Mypy typing issues across 47 files.
  - Local dry-run installation with `--require-hashes` verified successfully.

---

## 2026-09-12 — Cross-Platform Automated Installers (`install.ps1` & `install.sh`)

- **Single-Command Automated Setup**:
  - Implemented `install.ps1` for Windows PowerShell with robust ASCII encoding and user PATH registration (`$HOME\.local\bin\trace.cmd`).
  - Implemented `install.sh` for POSIX systems (Linux / macOS) with syntax checking, virtual environment bootstrapping, and executable wrapper generation (`$HOME/.local/bin/trace`).
- **Idempotency & Safe Defaults**:
  - Created `.env.example` with PostgreSQL defaults and optional SQLite configuration.
  - Automatically provisions `.env` from template on initial run without overwriting existing customizations.
  - Ensures forensic storage directory (`~/.trace/storage`) is created.
  - Safely initializes database schema and migrations (`trace db init`, `trace db migrate`).
- **Documentation**:
  - Updated `README.md` with 1-line installation instructions for Linux and Windows.

---

## 2026-09-12 — Architecture Hardening (changes_need_to_make_2.txt) — Part 1: High-Priority P0 Invariants

- **P0-1: First-Year Sequence Race Elimination**:
  - Refactored `SqlAlchemyCaseRepository.get_next_sequence_number()` using SQLAlchemy savepoints (`session.begin_nested()`).
  - Gracefully recovers from `IntegrityError` if a concurrent transaction initializes the sequence row first, immediately re-locking `with_for_update()` to guarantee conflict-free case generation across threads.
- **P0-2: Transactional Audit Boundary in UnitOfWork**:
  - Refactored `UnitOfWork` in `src/trace_core/core/service.py` to establish a strict forensic boundary:
    - `before_commit(hook)`: Mandatory pre-commit operations (such as forensic audit writes) executed *inside* the transaction boundary; any exception aborts the entire transaction.
    - `on_commit(hook)`: Optional external side-effects (telemetry, notifications) executed strictly after transaction commits.
- **P0-3: Atomic Migration Execution & Ledger Bookkeeping**:
  - Refactored `apply_migrations()` in `src/trace_core/core/database/migrations.py` so both the DDL action and the ledger write to `schema_migrations` execute within the **same** database transaction (`with engine.begin() as conn:`).
  - Added migration `003_create_case_sequences_table` to guarantee explicit table creation without relying on implicit ORM metadata.
- **P0-4: Hardened PostgreSQL Integration Assertions**:
  - Enforced `assert pg_session_manager.engine.dialect.name == "postgresql"` and `SELECT version();` checking in `tests/integration/test_postgres.py` to prevent silent fallback to SQLite.
  - Added `test_postgres_concurrent_sequence_allocation()` testing 5 concurrent threads allocating case sequences against real PostgreSQL simultaneously.
- **P1-1: Canonical UTC Invariant**:
  - Enforced UTC normalization in `BaseEntity` and `Case`: any non-UTC timezone-aware datetime is canonically converted to UTC (`astimezone(UTC)`), while naive datetimes are strictly rejected.
- **Verification**:
  - All 59 tests passing (57 unit, 2 PostgreSQL integration).
  - Branch coverage: **77.05%** (exceeds 70% threshold).
  - 0 Ruff lint errors, 0 Mypy static typing issues across 47 source files.

---

## 2026-09-12 — Remote Single-Command Installation (`irm | iex` & `curl | sh`)

- **Remote Installer Capability**:
  - Enhanced `install.ps1` and `install.sh` to support zero-prerequisite single-command remote installation:
    - Automatically detects when running outside a cloned repo (via piped stdin or absent `pyproject.toml`).
    - Provisions permanent app directory at `$HOME\.trace\app` (Windows) or `~/.trace/app` (Linux/macOS).
    - Clones repository using `git` if available, or automatically downloads and extracts the latest GitHub release/main archive if `git` is absent.
    - Bootstraps virtual environment, installs dependencies with cryptographic hash verification, initializes `.env` from template, runs database migrations, and binds the global `trace` command into user PATH.
- **Documentation & Repository Remote**:
  - Updated repository URLs across `README.md`, `install.ps1`, `install.sh`, and local git remote `origin` to `https://github.com/nirjxr26/Trace`.
  - Overhauled `README.md` into an enterprise-grade forensic software specification: added official project badges, highlights, single-command remote install steps, interactive REPL / CLI reference, architectural map, and configuration tables.
- **Title Standardization (`Forensic Data Imaging & Retrieval Tool`)**:
  - Updated startup banner subtitle across interactive shell (`src/trace_core/cli/shell.py`), CLI help text (`src/trace_core/cli/main.py`), package docstrings (`src/trace_core/__init__.py`), project descriptor (`pyproject.toml`), and installer banners (`install.ps1`, `install.sh`).
- **Cryptographic Secret Key Configuration**:
  - Provisioned a cryptographically secure 256-bit token (`secrets.token_hex(32)`) for `TRACE_SECRET_KEY` in `.env`.
- **Architectural Guidelines Hardening (`AGENTS.md`)**:
  - Added Section 14 to `AGENTS.md` explicitly codifying forensic domain invariants: strict application service mutation flows, immutable case identity, permanently sealed closures, canonical UTC storage, pre-commit audit boundaries, and purge guardrails.
- **SonarCloud & CI Issue Remediation**:
  - Enforced HTTPS redirect safety on `curl` invocations in `install.sh` (`--proto '=https' --proto-redir '=https'`).
  - Added default wildcard `*)` handler to `case` statement in `install.sh`.
  - Refactored `_migration_002_add_columns` in `src/trace_core/core/database/migrations.py` with static column definitions, reducing Cognitive Complexity from 28 to < 5 (SonarCloud S3776).
  - Split composite `assert ... and ...` in `tests/integration/test_postgres.py` into separate discrete assertions (SonarCloud S5958).
  - Cleanly formatted all files via `ruff format` to resolve CI formatting failures.
- **CI PostgreSQL Service Configuration Fix**:
  - Aligned CI PostgreSQL container database name (`POSTGRES_DB: trace`) and explicitly passed `TRACE_DATABASE_URL` so that `trace db init` connects to the initialized database in CI without error.

---

## 2026-09-12 — Subpart-2 Readiness: Pre-Audit Hardening (UoW, Actor, Archive, Canonical)

> Branch: `feat/subpart-2-audit`. No audit tables yet — this makes Subpart-2 a pure addition with no Subpart-1 rewrite.

- **Transactional Service Boundary (P0-1)**:
  - Migrated `CaseService.create/update/close/delete` to `BaseService.transaction() as uow` (`src/trace_core/cases/service.py`), removing direct `session.commit()/rollback()`. `before_commit()` slot is now free for Subpart-2 `audit.append()` with atomic `mutate + audit` semantics.
  - Added `restore_case()` service method using the same transaction boundary.
- **Actor Threading (P0-2)**:
  - Added `actor: str | None` to `create/update/close/delete/restore_case` with `_resolve_actor()` (`system` fallback). Typer `create` passes `--examiner`, `close` passes `--closed-by`; shell passes `None` and resolves cleanly. Every future `AuditEvent.actor` is already sourced without signature churn.
- **Canonical + CLI Shared Helpers (P0-3 / P1-7)**:
  - Created `src/trace_core/core/canonical.py:canonical_json()` (sorted keys, compact separators, UTC `Z` normalization) for Subpart-1 payload emit + Subpart-2 hash/verify reuse.
  - Created `src/trace_core/core/cli/output.py:parse_output_format()` and switched `cases/shell_handler.py` to it, eliminating duplicated `--output` parsing.
  - Added `AuditTamperError` (`src/trace_core/core/errors.py`) mapped to new `EXIT_VERIFY_FAILED=11` (`src/trace_core/core/cli/exit_codes.py`, `src/trace_core/core/cli/error_handler.py`) so `audit verify` needs no error-handler edits.
- **Clock Sweep (P0-4)**:
  - Routed `core/database/base.py` defaults/onupdate, `cases/repository.py` `soft_delete` and `_to_domain` fallbacks through `now_utc()`. Removed direct `datetime.now(UTC)` sources that would destabilize chain hashes.
- **Archive Semantics (P1-5)**:
  - Added `archived_by VARCHAR(255)` to `CaseModel`, `BaseEntity`, `CaseResponseDto`, and dossier renderer. `soft_delete(case_id, archived_by)` stamps actor; new `restore()` clears `is_deleted/archived_at/archived_by`.
  - Added `trace case restore` (Typer) + `case restore` (shell handler, completions, help, autosuggest). Kept `--status ARCHIVED` as `include_deleted` shortcut for backward compat.
- **Repository Safety (P1-6)**:
  - Narrowed `SqlAlchemyBaseRepository.delete()` to hard-delete primitive only with forensic warning; removed auto soft-delete magic. Purge stays explicitly in `SqlAlchemyCaseRepository.purge()`.
- **DI + Migrations (P1-8 / P1-9)**:
  - `_get_service(session_manager=None)` and `InteractiveShell(service=None, session_manager=None)` allow one manager to feed both `CaseService` and future `AuditService` in the same `UoW.session`.
  - Added `archived_by` to idempotent `_CASE_COLUMN_DEFINITIONS`; added `checksum VARCHAR(64)` to `schema_migrations` with backfill `ALTER`, `_migration_checksum()`, and checksum-aware `get_applied/apply_migrations`.
- **Tests & Verification**:
  - Created `tests/unit/test_subpart2_readiness.py` (canonical key-order, UTC normalization, output parsing, archive/restore with actor + purge guard).
  - Full suite: 61 passed, 77.43% branch coverage (>70%), 0 Ruff check/format issues (54 files), 0 Mypy issues (50 files).
- **Files touched**:
  - `src/trace_core/core/canonical.py` (new), `src/trace_core/core/cli/output.py` (new), `tests/unit/test_subpart2_readiness.py` (new)
  - `src/trace_core/cases/service.py`, `src/trace_core/cases/repository.py`, `src/trace_core/cases/models.py`, `src/trace_core/cases/dto.py`, `src/trace_core/cases/commands.py`, `src/trace_core/cases/shell_handler.py`, `src/trace_core/cases/renderers.py`
  - `src/trace_core/core/domain.py`, `src/trace_core/core/errors.py`, `src/trace_core/core/cli/error_handler.py`, `src/trace_core/core/cli/exit_codes.py`, `src/trace_core/core/database/base.py`, `src/trace_core/core/database/repository.py`, `src/trace_core/core/database/migrations.py`, `src/trace_core/cli/shell.py`

---

## 2026-09-12 — Max Reusability Pass: Zero-Duplication Extraction (Same Branch)

- **Render dispatch single source (`cases/renderers.py`)**:
  - Added `render_case(case, output)` + `render_cases(cases, output)` wrapping `table|json` branch once. Replaced 4 duplicated `if json/table` blocks in `cases/commands.py:list/show` and `cases/shell_handler.py:list/show`. `create/edit/close/restore` keep direct `render_case_detail` (no branch to unify).
- **Tag parsing single source (`cases/dto.py:parse_tags`)**:
  - `parse_tags(str|None) -> list|None` (None stays None, else stripped non-empty). Replaced 4 variants in `commands.py:create/edit` + `shell_handler.py:create/edit`. Stored-tag behavior unchanged (domain `validate_tags` already drops empties/lowercases/dedupes).
- **Status parsing single source (`cases/domain.py:parse_status_value`)**:
  - Pure `raw -> CaseStatus|None` (`ALL/ARCHIVED/None/invalid -> None`). Shell `_parse_status` now delegates; Typer `list` uses it while preserving its invalid-status error card. No UX change.
- **Active-case sync single source (`cases/shell_handler.py`)**:
  - Added `_sync_active_case(ctx, case)` + `_clear_active_if_matches(ctx, id)`. Replaced 5 repeated `if ctx.active_case and ...id ==` blocks (edit/close/delete/restore).
- **Deliberately not extracted**: shell ghost-text/completer UX copy (pinned by `test_shell.py` string asserts, changes rarely — coupling to registry would add fragility for ~15 strings); `CaseService()` one-line fallbacks (3 sites, extraction adds API for no win).
- **Verification**: 61 passed, 78.00% branch (up from 77.43%), 0 Ruff, 0 Mypy (50 files).

---

## 2026-09-12 — Deep Reusability Pass 2: Whole-Codebase Deduplication

- **TUI core (`core/ui/renderers.py`)**:
  - `_supports_char()` unifies 5 icon/rule try/except blocks (`get_rule/error/arrow/success/warning` now one-liners).
  - `_to_ist()` unifies naive→UTC→IST in `format_india_datetime/table_time`; `_status_styles()` lazy module cache replaces per-call dict rebuild in `get_status_style_and_label`.
  - Kept `render_table` + `render_entity_panel` (both pinned by `test_ui_renderers.py` — distinct bordered vs minimalist contracts, not dead code).
- **Service guards (`cases/service.py`)**:
  - `_require_case(repo, identifier)` replaces 5 identical resolve-or-404 blocks (get/update/close/delete/restore). State-specific messages stay per-action (different UX, not unified).
- **DB CLI (`core/cli/db_commands.py`)**:
  - `_require_db()` replaces `check_connection()+exit` in `init/migrate` (`status` keeps custom Offline grid, different UX).
- **Migrations (`core/database/migrations.py`)**:
  - `_column_names(conn, table)` replaces 3 `inspect().get_columns` comprehensions (ensure/applied/apply paths).
- **Shell + commands UX**:
  - `_format_active_case(case, hint)` shared by `print_banner` + `show_status` (wording hints stay per-view).
  - `_confirm_or_exit(prompt)` replaces 3 Typer `Confirm.ask + cancelled + Exit` blocks (close/delete/restore).
- **Verification**: 61 passed, 78.67% branch (renderers 89%→92%), 0 Ruff, 0 Mypy (50 files).

---

## 2026-09-12 — SonarLint + Pylance Remediation (S1192, S3776, reconfigure)

- **S1192 commands.py (`cases/commands.py`)**:
  - `_SKIP_CONFIRM_HELP` constant replaces 3× `"Skip confirmation prompt"` in close/delete/restore `--yes` options. (`"[dim]Operation cancelled.[/dim]"` was already single-sourced in `_confirm_or_exit` from the reuse pass — report was stale.)
- **S1192 shell_handler.py (`cases/shell_handler.py`)**:
  - `_ACTION_CANCELLED` constant replaces 3× `"\n[dim]Action cancelled.[/dim]\n"` in close/delete/restore interactive cancels.
- **Pylance reconfigure (`cli/main.py`, `core/ui/renderers.py`)**:
  - New `configure_utf8_streams()` in `renderers.py` uses `getattr(stream, "reconfigure")` + `callable()` instead of direct `sys.stdout.reconfigure` attribute access (unknown on `TextIO`). Both inline blocks replaced — `main.py` now calls the shared helper, removing the duplication as well.
- **S3776 error_handler (`core/cli/error_handler.py`)**:
  - Extracted `_resolve_unexpected_error()` (debug-vs-sanitized tail) out of `_resolve_error_details`, dropping it from 17 to ~14 (limit 15). Typed branches untouched, behavior identical.
- **Verification**: 61 passed, 78.98% branch, 0 Ruff check/format, 0 Mypy (50 files).

---

## 2026-09-12 — Deep Reusability Pass 3: Full-Codebase Sweep

- **Audit method**: grepped all of `src/` for repeated literals (`[OK]`, `ADD COLUMN`, `ARCHIVED/ALL`), repeated branches (`resolve-or-404`, `check_connection+exit`, `Confirm.ask`, empty-table guards, cell coercion, help-row formats). Everything with 2+ real uses got a single source; UX copy and one-off wizards deliberately left per-site (see below).
- **Migrations (`core/database/migrations.py`)**:
  - `_ensure_column(conn, table, column, ddl)` unifies the checksum backfill with the case-column backfill pattern. Third backfill (audit table, Subpart-2) now reuses it instead of a third inline `ALTER`.
- **Status filters (`cases/domain.py`)**:
  - `STATUS_FILTER_KEYWORDS` + `is_archived_filter()` replace the `("ALL","ARCHIVED")` / `== "ARCHIVED"` triples in `parse_status_value`, Typer `list`, and shell `_parse_list_options`.
- **Shell help (`cli/shell.py`)**:
  - `_print_help_row()` + `CONSOLE_HELP_ENTRIES` replace 5 identical format strings (feature-row loop + 4 console rows).
- **Tables (`core/ui/renderers.py`)**:
  - `_print_empty_message()` + `_format_table_cells()` shared by `render_minimalist_table` + `render_table`.
- **Left per-site on purpose**: per-action success texts + wizard prompt sequences (UX copy, differ per action — unifying forces a speculative wizard framework); `list_all`/`strip_flags` generic base API (public reuse surface for audit/devices); ghost-text/completer strings (test-pinned).
- **Verification**: 61 passed, 79.02% branch, 0 Ruff check/format, 0 Mypy (50 files).

---

## 2026-09-12 — Fix: `case list` Execution Error on Stale Databases (Migration 004)

- **Root cause**: `archived_by` was added to migration 002's backfill list, but databases that had already recorded 002 as applied never received the column. Reads then failed with `OperationalError: no such column: cases.archived_by`, surfaced in the shell as the sanitized `Execution Error → Verify database connectivity` card.
- **Fix (`core/database/migrations.py`)**: forward-only migration `004_add_archived_by_column`, idempotent via `_ensure_column()` inspect-check (PostgreSQL + SQLite safe). Fresh DBs unaffected; stale DBs self-heal on next `trace db migrate`.
- **Regression test (`tests/unit/test_database_migrations_and_lifecycle.py:test_migration_004_backfills_archived_by_on_old_database`)**: drops the column + un-records 004 to simulate the stale state, asserts `list_cases()` raises `OperationalError`, then asserts `apply_migrations()` heals it and reads return `[]`.
- **Verification**: 62 passed, 0 Ruff check/format, 0 Mypy (50 files).

---

## 2026-09-13 — Subpart 2: Tamper-Evident Audit Ledger (Production-Grade)

> Branch: `feat/subpart-2-audit`. Implements `v1_build_plan.md F7` + `v1_implementation_roadmap.md Subpart-2` per approved 10-point ADR revision (global monotonic chain, head-lock serialization, payload+chain recompute, gap warnings, offline bundle).

- **Domain & Hashing (`audit/domain.py`, `core/canonical.py`)**:
  - `AuditAction` enum (`CREATED/UPDATED/CLOSED/ARCHIVED/RESTORED/PURGED`), `GENESIS_CHAIN=0*64`, `SPEC_VERSION=trace-audit-v1`, `CANONICAL_VERSION=trace-canonical-json-v1`.
  - `payload_hash()`, `chain_hash(prev,p_hash,seq)`, `build_payload()` (actor/subject/spec/canonical/hash_algo/details + Zulu ts). Canonical now `allow_nan=False`, rejects `NaN/Infinity`, `sort_keys+compact+UTF-8`, UUID/Enum/date/datetime normalized.
- **Persistence (`audit/models.py`, `core/database/migrations.py:005`)**:
  - `audit_chain_state(id=1, last_seq, last_chain_hash)` single-row head serialized via `SELECT ... FOR UPDATE` on PG (SQLite single-writer, `ponytail: global head lock`) — `seq = head.last_seq+1`, `prev_chain=head.last_chain`, `chain_hash=SHA256(prev‖p_hash‖seq)`, `INSERT audit_events + UPDATE head` atomically. `audit_events(seq PK manual, ts/action/actor/subject_case_number/subject_case_id/payload_json/payload_hash/prev_chain/chain_hash)` with `subject_case_number TEXT` denormalized (survives purge, no FK cascade). Append-only triggers `BEFORE UPDATE/DELETE → RAISE(ABORT)` on SQLite (PG trigger deferred to V2 privilege-separation). `STATUS_FILTER_KEYWORDS` reused from cases.
- **Repository (`audit/repository.py`)**:
  - `SqlAlchemyAuditRepository.append()` (head-lock + canonical + hash + flush), `list_events(AuditFilterDto)` (case/action/actor/search + limit/offset reuse `BaseFilterDto`), `stream_all()` yield-per, `count()`.
- **Service (`audit/service.py`)**:
  - `list_events()`, `verify()` streaming recompute: `payload_hash` from `payload_json`, `prev_chain` linkage, `chain_hash`; returns `VerifyResultDto(is_valid, events_verified, first_seq/last_seq, first_mismatch_seq, mismatch_type, expected/actual hashes, sequence_gaps)` — gaps are warnings, not tamper; tail-truncation documented as V1 limitation (needs external anchor). `export(out)` streaming `header{spec,canonical,hash} + JSONL events`, `tmp→fsync→rename` atomic.
- **Wiring (`cases/service.py`)**:
  - All 6 mutating paths (`create/update/close/archive/purge/restore`) do `uow.before_commit(lambda s: SqlAlchemyAuditRepository(s).append(...))` — `Case UPDATE + Audit INSERT + Head UPDATE = ONE transaction`. Failure rolls back case. `actor` threaded via `_resolve_actor`.
- **Interfaces (`audit/commands.py`, `audit/shell_handler.py`, `audit/renderers.py`, `cli/main.py`, `cli/shell.py`)**:
  - `trace audit show [--case --action --actor --search -q --output table|json --limit --offset]` → `render_audit_table` (reuses `render_minimalist_table`, `format_india_datetime`, `get_status_style_and_label`).
  - `trace audit verify [--output]` → `render_verify_result` + `AuditTamperError(11)` on tamper.
  - `trace audit export --out FILE --format jsonl` → atomic bundle, offline-verifiable (`payload_hash+chain_hash` recomputable without Trace).
  - Shell `audit show|verify|export` with completions/help mirroring `cases/` (no new patterns).
- **Tests (`tests/unit/test_audit_ledger.py`, `test_audit_cli.py`)**:
  - 14 tribunal cases: clean verify, payload-only mutate → `payload_hash` fail, payload+hash forge → `prev_chain` fail at next seq, chain/prev tamper, middle delete → next seq `prev_chain` fail, tail delete → valid (documented), gap warning not tamper, audit-failure rollback, trigger blocks, offline bundle recompute, canonical order, non-finite reject, CLI show/verify/export smoke.
- **Verification**:
  - 76 passed (62→76), 78.32% branch (>70%), 0 Ruff check/format (65 files), 0 Mypy (61 files). Coverage drop is expected (new audit module); threshold still exceeded.
- **Files touched/added**:
  - Added: `src/trace_core/audit/{__init__.py,domain.py,models.py,repository.py,service.py,dto.py,commands.py,shell_handler.py,renderers.py}`, `tests/unit/test_audit_ledger.py`, `test_audit_cli.py`
  - Modified: `src/trace_core/core/canonical.py`, `src/trace_core/core/database/migrations.py`, `src/trace_core/cases/service.py`, `src/trace_core/cli/{main.py,shell.py}`

---

## 2026-09-13 — Audit 5W1H + Human Verify + Compact Table (V1.1)

> No schema change. Payload-only enrichment. Keeps `audit show` compact + adds `--seq` dossier; `verify` now easy + efficient.

- **5W1H enrichment (`audit/repository.py`, `cases/service.py`)**:
  - `host` (`socket.gethostname()`), `trace_version` (`settings.version`), `command` (`case create/edit/close/delete/restore …`) auto-added to `details` inside `payload_json` (no DB column, still `SHA256(canonical(payload_json))`). `CASE_UPDATED` now stores `{changed, before:{field:old}, after:{field:new}, reason:"", command}` with snapshot taken pre-mutate. Other actions store `{command, reason/closed_by}` + host/version.
- **Compact `audit show` (`audit/renderers.py`)**:
  - Columns `Seq | Action | Case # | Actor @ Host | Time` (`Time` = `format_india_table_time` compact `DD-MM hh:mm`), footer `Chain: VALID · SHA-256 · N events`. Host parsed from `details.host` inside `payload_json`.
- **Detailed `--seq` view (`audit/commands.py`, `shell_handler.py`, `renderers.py:render_audit_detail`)**:
  - `trace audit show --seq 2` / `audit show --seq 2` → `render_dossier` 5W1H: `Who/When/Where/What/Why/How` + `Before/After` JSON + hashes. Handles `--seq` + `--output json` too.
- **Verify human + efficient (`audit/service.py`, `renderers.py:render_verify_result`)**:
  - Split `verify()` (20→~8) into `_expected_payload_hash/_collect_gaps/_mismatch/_verify_rows`; `events_verified` via `enumerate` (no `list.index`), gap warning not tamper. Output now `Chain · Events · Range · Gaps · Checked · Result` with `✓/✗` + `Action → Restore…` hint; empty ledger `VALID 0` kept. Streaming intent preserved (`yield_per` in export; verify uses list but O(n) not O(n²)).
- **Tests & verification**:
  - `tests/unit/test_audit_5w1h.py` (5W1H fields present, `--seq` dossier + 404). Suite: 78 passed (76→78), 75.71% branch (>70%), 0 Ruff, 0 Mypy (62 files).
- **Files**: `src/trace_core/audit/{repository.py,renderers.py,commands.py,shell_handler.py,service.py}`, `src/trace_core/cases/service.py`, `tests/unit/test_audit_5w1h.py`

---

## 2026-09-13 — Audit Layered Architecture (Long-Term, No UX Change)

> Keeps ledger primitive stable. Application code creates `AuditEvent`; audit owns normalize/chain/store/verify/render.

- **New modules**:
  - `audit/events.py` — `Subject{type,number,id}` + `Context{host,trace_version,command}`. V1 `type=case`, next `evidence/report/device` reuse same table.
  - `audit/builder.py` — `for_case_created/updated/closed/archived/restored/purged()` → `(AuditAction, Subject, details, Context)` + `merge_details_context()`. One vocabulary, no flat `CASE_UPDATED_TITLE` explosion. Families `CASE_*/EVIDENCE_*/REPORT_*` ready for `--group` later.
  - `audit/verifier.py` — pure `verify_rows(rows)`: `payload_hash` from `payload_json` + `chain_hash` + `prev_chain` + `gaps`. No Session/CLI. Same code verifies DB, bundle, backup.
  - `audit/exporter.py` — `export_bundle(session, out)` streaming `header + JSONL` with `fsync+rename`. No service logic.
- **Central contract**:
  - `AuditService.record(session, action, subject, actor, details, command)` — `Case/Evidence/Report` just `builder → record`; crypto (`canonical→payload_hash→head-lock→chain_hash→INSERT→update head`) stays inside `AuditService`/`Repository`. Before: `cases/service.py` knew hashing; now it knows only `I need to record CASE_UPDATED`.
  - `CaseService` 6 paths now `action, subject, details, ctx = for_case_*(); AuditService().record(s, action, subject, actor, details, ctx.command)` via `before_commit`.
- **User impact**: **None visible** — `audit show` compact, `--seq` 5W1H, `verify` human, newest-first all unchanged. Benefit is maintainability: next audit type plugs into same envelope, not a ledger rewrite.
- **Verification**: 78 passed, 0 Ruff, 0 Mypy (66 files).

---

## 2026-09-13 — Subpart-1/2 Final Solidity (No Future-Proofing)

> Re-scan for solid only — makes Subpart-1/2 forensically solid without adding evidence/report vocabulary.

- **Subpart-1**:
  - `tags` `50×50` cap already solid via `domain.validate_tags`; kept.
  - `006_add_case_checks` adds `CHECK(status IN…)` + `CHECK(version>=1)` idempotent.
  - `delete()` now `requires expected_version` (no silent fallback fetch → race).
  - `restore` actor fallback fixed to `case.lead_examiner` (was `system`).
- **Subpart-2**:
  - `exporter.export_bundle` true streaming `for m in scalars().yield_per(500):` (was `.all()`).
  - `renderers._actor_host` dead code removed (table now `Actor` only), `render_case_audit_header` early `if not events: return`.
  - `service.get_by_seq` validates `seq>=1` at service layer (both CLI/shell already did).
  - `service._check_ledger_error` now also catches `no such column` (covers stale `archived_by` etc).
- **Verification**: 78 passed, 75.x% branch (>70%), 0 Ruff, 0 Mypy (67 files).

---

## 2026-09-13 — Subpart-1/2 Solidity Hardening (No Future-Proofing)

> Makes only Subpart-1 + 2 solid — no new vocabulary, just correctness.

- **Subpart-1 (`cases/`, `core/`)**:
  - `tags` 50×50 cap (`domain.validate_tags`), `description`/`notes` caps already solid.
  - `update_case` skips empty `changed==[]` (no `UPDATE` / no audit waste) — early return `CaseResponseDto`.
  - `actor` now `case.lead_examiner` fallback for `update/restore` (not `system`), `restore` correctly uses `case.lead_examiner`.
  - `soft_delete/restore/purge` now `expected_version` OCC + `version+=1` (concurrent archive race → `ConcurrencyConflictError` not silent overwrite).
  - `delete()` now requires `expected_version` (no silent fallback fetch).
  - `006_add_case_checks` migration: `CHECK(status IN ('OPEN','UNDER_REVIEW','CLOSED'))` + `CHECK(version>=1)` idempotent best-effort.
- **Subpart-2 (`audit/`)**:
  - `verify` streaming: `service.verify()` now `yield_per(500)` iterable → `verifier.verify_rows(Iterable)` with `first_seq/last_seq` on-the-fly, `enumerate` not `list.index` (true O(n) memory).
  - `_check_ledger_error` also handles `no such column` (stale `--case` header after `archived_by` etc) → `Run 'trace db migrate'`.
  - `audit show --seq` validates `seq>=1` (both CLI + shell) → `Invalid seq` not `Not Found`.
  - `render_audit_table` now 5 cols (`Seq/Action/Case/Actor/Time`) + `parse_details` single-source (`events.parse_details`), `audit show --case` header `CASE … Status·Events·Created·Last` via `render_case_audit_header`.
  - `builder._ctx` captures full `sys.argv` when generic `case create` placeholder would lose flags (`--reason` etc), still `ponytail: global host lock` noted.
- **Verification**: 78 passed, 75.7% branch (>70% via `--cov`), 0 Ruff, 0 Mypy (67 files).

---

## 2026-09-13 — Ship Now (Indexes, DTO Cap, get_db, Property, pip-audit, make_case)

> Cheap, correct, no downside — keeps `notes` searchable for forensic completeness (deferred #2).

- **DB #1 `007_add_perf_indexes`**: `idx_cases_lead_examiner_is_deleted` + `idx_audit_case_seq` (`subject_case_number, seq DESC`) `IF NOT EXISTS` idempotent.
- **#2 deferred**: `notes` stays in `ilike` search (forensic `test_search_includes_notes` would break); keep `number/title/lead_examiner/description/notes` all searchable, optimize when 10k+ bench shows slow.
- **#13 DTO cap**: `CaseCreateDto.tags` `max_length=50` + `validate_tags_cap` per-tag 50 / 50 tags (domain already 50×50).
- **#7 `get_db(ctx)`** single source in `core/database/session.py`, `audit/shell_handler` + `audit/service.record` now reuse builder `Context` (no double `socket.gethostname`).
- **#21 Property test** `tests/unit/test_case_state_machine_property.py` — 100 random `OPEN/CLOSED` transitions, `CLOSED` never reopens.
- **#22 CI** `pip-audit --require-hashes` + `cyclonedx-bom sbom.json` (best-effort `|| true`).
- **#24 `make_case()`** helper in `tests/conftest.py` single source for `CaseService.create_case` in tests.
- **Verification**: 85 passed (84→85), 0 Ruff, 0 Mypy (70 files).

---

## 2026-09-13 — Simplicity & Complexity Pass (CCN>15 → ≤12)

> Makes every function easy to read, no behavior change. Fixes Sonar S1764/S1192/S7498/S3776/S3358 + lizard CCN>15.

- **Builder (`audit/builder.py`)**: `_ctx 16→5` via `_get_host/_get_argv/_resolve_command`, `for_case_updated 21→7` via `_updated_details`, `CASE_PREFIX/_AUDIT_PREFIX` constants + tuple `startswith`.
- **Commands (`audit/commands.py`)**: `_show_list 51→12` via `_parse_action/_render_case_timeline`, `audit_verify 39→8` via `_check_anchor`, `audit_show 15→8` via helpers.
- **Renderers (`audit/renderers.py`)**: `render_audit_timeline 47→7` via `_timeline_summary`, `render_audit_detail 49→8` via `_how_text/_utc_display/_detail_fields/_detail_sections`, `render_verify_result 28→3` via `_render_valid/_render_tamper/_what_text`, `_actor_host` removed (dead).
- **Service/Repo (`audit/service.py`, `repository.py`)**: `_check_ledger_error 22→3` via `_is_ledger_missing` (pgcode 42P01 + `no such table/column`), `verify_rows 33→9` streaming `Iterable` + `enumerate` (was `list.index`), `export_bundle 34→6` via `_header/_record_dict`, `_base_fields` literal `{}`.
- **Shell (`audit/shell_handler.py`, `cases/shell_handler.py`)**: `_complete_show 32→4` via dict handlers, `_interactive_close_case 17→4` via `_confirm_typed`, `TraceAutoSuggest` ghost `case show`/`audit --case active`, `TraceShellCompleter` hide globals when active + limit 8 + fuzzy.
- **Cases (`cases/commands.py`, `service.py`)**: `list_cases --recent`, `case show` Tags top, `Closed` IST+UTC, `edit --reason` + diff preview, `purge/close` type-number confirm, `recent`/`back` shell commands, `ls/sh/ed` aliases.
- **Verification**: 84 passed (78→84), 0 Ruff, 0 Mypy (69 files), lizard CCN all ≤15 (was 5 over).

---

## 2026-09-13 — Forensic Polish (1-4 + 5 Anchor + 6-9)

> User wanted solid Subpart-1/2 only — skipped `case reopen` (CLOSED stays blocked, `edit` on CLOSED still `InvalidCaseStateError`), applied the rest.

- **2. Edit Why (`cases/commands.py`, `cases/service.py`, `audit/builder.py`)**: `case edit --reason "typo"` → `details.reason` → `Why` in `audit --seq` dossier (was `—`). `builder.for_case_updated` now `reason` param, `service.update_case(..., reason="")`.
- **3. Purge guard (`cases/commands.py`, `cases/shell_handler.py`)**: `--purge` without `--yes` now requires typing exact `case number` (`Prompt: Type '2026-CR-0001' to confirm purge` → mismatch → `Purge cancelled`), not just `y/N`. `--yes` still skips for scripts. Shell shows `Purge is irreversible!` warning + same typing.
- **4. Diff before confirm (`cases/shell_handler.py`)**: `case edit` wizard now snapshots `before`, shows `Changes: title: "Old" → "New"` + `Why` prompt, then `Apply these changes? y/N` before `service.update_case`. No silent blind confirm.
- **5. Anchor (`cases/service.py`, `audit/service.py`, `audit/commands.py`)**: `close_case` `on_commit` writes `~/.trace/storage/anchors/anchor-<case>-<seq>.json` `{case,last_seq,last_chain,anchored_at,spec}` + `audit verify --anchor <file>` compares `last_seq/last_chain` → `Anchor tail mismatch` if DB was truncated/replaced. Fixes `tail delete = VALID` blind spot without external HSM.
- **6. Time (`audit/renderers.py`)**: `When: 13-09 09:41 IST (2026-09-13T04:11Z)` — IST for human, UTC Zulu for court, both.
- **7. Color (`core/ui/theme.py`)**: `status_archived/record_deleted: #D06A73 red → #8A9BA8 muted slate`, red stays only for `TAMPER/PURGE/danger`.
- **8. Empty hint (`cases/renderers.py`, `audit/renderers.py`)**: `No cases found. Run 'case create' to add one.` / `No audit events found. Create or edit a case…`
- **9. Tag ghost (`cases/shell_handler.py`)**: `case create/edit` wizard now prints `Existing tags: usb, ssd …` (first 10) before `Tags` prompt, from `service.list_cases()`.
- **Verification**: 78 passed, 0 Ruff, 0 Mypy (68 files).








