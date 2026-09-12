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
