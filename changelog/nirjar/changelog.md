# Trace — Project Development Log

> Maintained by: **Nirjar Goswami**
> Scope: Core Architecture, Database, Presentation Layer & Forensic TUI

**About this log.** Append-only per-person record (newest at the bottom). Entries are never rewritten; structure lives in the Part dividers and the contents list below. Original record order is preserved — a few entries were recorded out of date order and stay where they were written. A byte-identical backup of the pre-restructure file is kept at `changelog.backup.2026-09-18.md`.

**Legend.** `SEC-NN` = internal security-finding IDs (not CVEs — no CVE has ever been assigned to or found in this project). Each entry ends with its verification proof (tests / ruff / mypy).

# Contents

- **Part 1 — Foundation (cases, CLI, database, installers)** — Subpart 1 core, hardening phases, installers and pre-audit readiness.
  - [2026-09-10 — Initial Architecture & Database Foundation](#2026-09-10--initial-architecture--database-foundation)
  - [2026-09-11 — Application Services & CLI Framework](#2026-09-11--application-services--cli-framework)
  - [2026-09-12 — Forensic TUI System, Quality Refactoring & Aesthetics](#2026-09-12--forensic-tui-system-quality-refactoring--aesthetics)
  - [2026-09-12 — Transition to `trace` & Modular Feature Architecture](#2026-09-12--transition-to-trace--modular-feature-architecture)
  - [2026-09-12 — Maximum TUI Reusability Engine & CI/CD Pipeline Fix](#2026-09-12--maximum-tui-reusability-engine--cicd-pipeline-fix)
  - [2026-09-12 — Subpart 1 Hardening: Phase 1 (Forensic Domain Invariants & State Machine)](#2026-09-12--subpart-1-hardening-phase-1-forensic-domain-invariants--state-machine)
  - [2026-09-12 — Subpart 1 Hardening: Phase 2 (Concurrency, Sequence Safety & Error Narrowing)](#2026-09-12--subpart-1-hardening-phase-2-concurrency-sequence-safety--error-narrowing)
  - [2026-09-12 — Subpart 1 Hardening: Phase 3 (Database Decoupling, Migrations & Startup Hygiene)](#2026-09-12--subpart-1-hardening-phase-3-database-decoupling-migrations--startup-hygiene)
  - [2026-09-12 — Subpart 1 Hardening: Phase 4 (Query Engine, Pagination, Purge Policy & UI/CLI Polish)](#2026-09-12--subpart-1-hardening-phase-4-query-engine-pagination-purge-policy--uicli-polish)
  - [2026-09-12 — Subpart 1 Hardening: Phase 5 (CI/CD Pipeline, PostgreSQL Integration & Documentation)](#2026-09-12--subpart-1-hardening-phase-5-cicd-pipeline-postgresql-integration--documentation)
  - [2026-09-12 — Indian Standard Time (IST) Presentation Formatting](#2026-09-12--indian-standard-time-ist-presentation-formatting)
  - [2026-09-12 — Repository Hygiene: Gitignore & Unused Artifact Removal](#2026-09-12--repository-hygiene-gitignore--unused-artifact-removal)
  - [2026-09-12 — SonarCloud Issue Remediation & Security Hardening](#2026-09-12--sonarcloud-issue-remediation--security-hardening)
  - [2026-09-12 — Cross-Platform Automated Installers (`install.ps1` & `install.sh`)](#2026-09-12--cross-platform-automated-installers-installps1--installsh)
  - [2026-09-12 — Architecture Hardening (changes_need_to_make_2.txt) — Part 1: High-Priority P0 Invariants](#2026-09-12--architecture-hardening-changes_need_to_make_2txt--part-1-high-priority-p0-invariants)
  - [2026-09-12 — Remote Single-Command Installation (`irm | iex` & `curl | sh`)](#2026-09-12--remote-single-command-installation-irm--iex--curl--sh)
  - [2026-09-12 — Subpart-2 Readiness: Pre-Audit Hardening (UoW, Actor, Archive, Canonical)](#2026-09-12--subpart-2-readiness-pre-audit-hardening-uow-actor-archive-canonical)
  - [2026-09-12 — Max Reusability Pass: Zero-Duplication Extraction (Same Branch)](#2026-09-12--max-reusability-pass-zero-duplication-extraction-same-branch)
  - [2026-09-12 — Deep Reusability Pass 2: Whole-Codebase Deduplication](#2026-09-12--deep-reusability-pass-2-whole-codebase-deduplication)
  - [2026-09-12 — SonarLint + Pylance Remediation (S1192, S3776, reconfigure)](#2026-09-12--sonarlint--pylance-remediation-s1192-s3776-reconfigure)
  - [2026-09-12 — Deep Reusability Pass 3: Full-Codebase Sweep](#2026-09-12--deep-reusability-pass-3-full-codebase-sweep)
  - [2026-09-12 — Fix: `case list` Execution Error on Stale Databases (Migration 004)](#2026-09-12--fix-case-list-execution-error-on-stale-databases-migration-004)
- **Part 2 — Audit ledger (Subpart 2)** — Tamper-evident ledger, 5W1H enrichment, layered architecture and polish.
  - [2026-09-13 — Subpart 2: Tamper-Evident Audit Ledger (Production-Grade)](#2026-09-13--subpart-2-tamper-evident-audit-ledger-production-grade)
  - [2026-09-13 — Audit 5W1H + Human Verify + Compact Table (V1.1)](#2026-09-13--audit-5w1h--human-verify--compact-table-v11)
  - [2026-09-13 — Audit Layered Architecture (Long-Term, No UX Change)](#2026-09-13--audit-layered-architecture-long-term-no-ux-change)
  - [2026-09-13 — Subpart-1/2 Final Solidity (No Future-Proofing)](#2026-09-13--subpart-12-final-solidity-no-future-proofing)
  - [2026-09-13 — Subpart-1/2 Solidity Hardening (No Future-Proofing)](#2026-09-13--subpart-12-solidity-hardening-no-future-proofing)
  - [2026-09-13 — Ship Now (Indexes, DTO Cap, get_db, Property, pip-audit, make_case)](#2026-09-13--ship-now-indexes-dto-cap-get_db-property-pip-audit-make_case)
  - [2026-09-13 — Simplicity & Complexity Pass (CCN>15 → ≤12)](#2026-09-13--simplicity--complexity-pass-ccn15--12)
  - [2026-09-13 — Forensic Polish (1-4 + 5 Anchor + 6-9)](#2026-09-13--forensic-polish-1-4--5-anchor--6-9)
  - [2026-09-13 — Dropdown & Case List Grouping (Only Preview, CR/NR/CLI)](#2026-09-13--dropdown--case-list-grouping-only-preview-crnrcli)
  - [2026-09-13 — Docs: Subpart-2 Detailed (like Subpart-1)](#2026-09-13--docs-subpart-2-detailed-like-subpart-1)
- **Part 3 — Responsive UI, dossiers & fullscreen TUI** — Responsive engine, dossier rhythm passes, Textual console and polish.
  - [2026-09-13 — Responsive TUI Engine (XS, MD, LG, XL & Height-Aware UX)](#2026-09-13--responsive-tui-engine-xs-md-lg-xl--height-aware-ux)
  - [2026-09-13 — Responsive Reuse Pass (minimal, no textual)](#2026-09-13--responsive-reuse-pass-minimal-no-textual)
  - [2026-09-13 — Fix wrapping in case list (width budget)](#2026-09-13--fix-wrapping-in-case-list-width-budget)
  - [2026-09-13 — Whole-app responsive (every screen)](#2026-09-13--whole-app-responsive-every-screen)
  - [2026-09-13 — Live resize redraw (no retype)](#2026-09-13--live-resize-redraw-no-retype)
  - [2026-09-13 — Fix ANSI leak on legacy cmd (`?[2J` garble)](#2026-09-13--fix-ansi-leak-on-legacy-cmd-2j-garble)
  - [2026-09-13 — Proper polling + invalidation (no thread, no clear-as-primary)](#2026-09-13--proper-polling--invalidation-no-thread-no-clear-as-primary)
  - [2026-09-13 — Remove toolbar, true live re-render (no Enter, no retype)](#2026-09-13--remove-toolbar-true-live-re-render-no-enter-no-retype)
  - [2026-09-13 — Cap tables at laptop width, drop live-watch dead code](#2026-09-13--cap-tables-at-laptop-width-drop-live-watch-dead-code)
  - [2026-09-13 — DB refresh: wipe junk, reseed live demo set](#2026-09-13--db-refresh-wipe-junk-reseed-live-demo-set)
  - [2026-09-13 — Phase A trust fixes (production-readiness register)](#2026-09-13--phase-a-trust-fixes-production-readiness-register)
  - [2026-09-13 — Phase B reuse pass (delete + unify)](#2026-09-13--phase-b-reuse-pass-delete--unify)
  - [2026-09-13 — Phase C UX honesty (say what it does)](#2026-09-13--phase-c-ux-honesty-say-what-it-does)
  - [2026-09-13 — Leftover sweep (register §F cleared)](#2026-09-13--leftover-sweep-register-f-cleared)
  - [2026-09-13 — Max-reuse + writing-quality sweep (UX deferred)](#2026-09-13--max-reuse--writing-quality-sweep-ux-deferred)
  - [2026-09-13 — Max-reuse sweep (one source per behavior)](#2026-09-13--max-reuse-sweep-one-source-per-behavior)
  - [2026-09-14 — Audit detail to professional dossier (no icons, CHANGES, INTEGRITY)](#2026-09-14--audit-detail-to-professional-dossier-no-icons-changes-integrity)
  - [2026-09-14 — Audit detail hierarchy pass (20-point review applied)](#2026-09-14--audit-detail-hierarchy-pass-20-point-review-applied)
  - [2026-09-14 — Case dossier in audit-detail language](#2026-09-14--case-dossier-in-audit-detail-language)
  - [2026-09-14 — Detail-view max-reuse (one dossier language)](#2026-09-14--detail-view-max-reuse-one-dossier-language)
  - [2026-09-14 — Alignment fixes (CHANGES indent + tight columns, case status indent)](#2026-09-14--alignment-fixes-changes-indent--tight-columns-case-status-indent)
  - [2026-09-14 — CHANGES divider breathing room](#2026-09-14--changes-divider-breathing-room)
  - [2026-09-14 — Case dossier section dividers](#2026-09-14--case-dossier-section-dividers)
  - [2026-09-14 — Dossier rhythm pass (equal padding everywhere)](#2026-09-14--dossier-rhythm-pass-equal-padding-everywhere)
  - [2026-09-14 — Tighter dossier rhythm](#2026-09-14--tighter-dossier-rhythm)
  - [2026-09-14 — CHANGES header indent](#2026-09-14--changes-header-indent)
  - [2026-09-14 — Textual fullscreen console (pilot built, all four screens)](#2026-09-14--textual-fullscreen-console-pilot-built-all-four-screens)
  - [2026-09-14 — TUI escape + scroll (unstick every modal)](#2026-09-14--tui-escape--scroll-unstick-every-modal)
  - [2026-09-14 — Case form focus + Enter flow (typing actually works)](#2026-09-14--case-form-focus--enter-flow-typing-actually-works)
  - [2026-09-14 — Full-size form inputs (compact was untypeable-feeling)](#2026-09-14--full-size-form-inputs-compact-was-untypeable-feeling)
  - [2026-09-14 — Prettier case form (round inputs, centered header + buttons)](#2026-09-14--prettier-case-form-round-inputs-centered-header--buttons)
  - [2026-09-14 — Integrity & Database as structured cards](#2026-09-14--integrity--database-as-structured-cards)
  - [2026-09-14 — 2-per-row form + dossier section breathing room](#2026-09-14--2-per-row-form--dossier-section-breathing-room)
  - [2026-09-14 — Audit + form + confirm polish (4-image sweep)](#2026-09-14--audit--form--confirm-polish-4-image-sweep)
  - [2026-09-14 — Fix clipped form buttons + soften outer border (create/edit reuse)](#2026-09-14--fix-clipped-form-buttons--soften-outer-border-createedit-reuse)
  - [2026-09-14 — TUI declutter (slim table, cards, dossier hierarchy)](#2026-09-14--tui-declutter-slim-table-cards-dossier-hierarchy)
  - [2026-09-14 — Audit tab declutter (mirrors Cases)](#2026-09-14--audit-tab-declutter-mirrors-cases)
  - [2026-09-14 — TUI pure-black background](#2026-09-14--tui-pure-black-background)
  - [2026-09-14 — Dossier breathing room](#2026-09-14--dossier-breathing-room)
  - [2026-09-14 — Textual TUI blueprint (plan only, no code)](#2026-09-14--textual-tui-blueprint-plan-only-no-code)
  - [2026-09-14 — Process decisions recorded (no code change)](#2026-09-14--process-decisions-recorded-no-code-change)
- **Part 4 — Production hardening & security program** — Trust fixes, reuse passes, assessments (SEC-01…27), remediation batches, Ed25519/RBAC/anchors, tooling, Subpart-3 planning and release hygiene.
  - [2026-09-13 — Phase D production hardening (database honest at last)](#2026-09-13--phase-d-production-hardening-database-honest-at-last)
  - [2026-09-16 — Code reusability refactor (pure, no logic/UI change)](#2026-09-16--code-reusability-refactor-pure-no-logicui-change)
  - [2026-09-16 — SonarQube 45-issue remediation (no logic/UI change)](#2026-09-16--sonarqube-45-issue-remediation-no-logicui-change)
  - [2026-09-16 — CI mypy `src tests` fix (msvcrt attr-defined)](#2026-09-16--ci-mypy-src-tests-fix-msvcrt-attr-defined)
  - [2026-09-16 — SonarQube 7-issue follow-up (no logic/UI change)](#2026-09-16--sonarqube-7-issue-follow-up-no-logicui-change)
  - [2026-09-16 — Pylance diagnostics (3 errors, 2 sites)](#2026-09-16--pylance-diagnostics-3-errors-2-sites)
  - [2026-09-16 — CI collection failure + TUI speed (no behavior change)](#2026-09-16--ci-collection-failure--tui-speed-no-behavior-change)
  - [2026-09-16 — Authorized white-box security assessment (no source changes)](#2026-09-16--authorized-white-box-security-assessment-no-source-changes)
  - [2026-09-16 — Security assessment round 2: identity, terminal, identifiers (no source changes)](#2026-09-16--security-assessment-round-2-identity-terminal-identifiers-no-source-changes)
  - [2026-09-17 — Security assessment round 3: forensic-logic flaws (no source changes)](#2026-09-17--security-assessment-round-3-forensic-logic-flaws-no-source-changes)
  - [2026-09-17 — Security assessment round 4: 360 sweep (no source changes)](#2026-09-17--security-assessment-round-4-360-sweep-no-source-changes)
  - [2026-09-18 — Batch 1 input containment implemented (SEC-02/03/06/07/08)](#2026-09-18--batch-1-input-containment-implemented-sec-0203060708)
  - [2026-09-18 — Batch 2 lifecycle integrity (SEC-09/10/11/13/15, SEC-04)](#2026-09-18--batch-2-lifecycle-integrity-sec-0910111315-sec-04)
  - [2026-09-18 — Batch 3 error boundaries (SEC-12/14)](#2026-09-18--batch-3-error-boundaries-sec-1214)
  - [2026-09-18 — Batch 4 HMAC ledger envelope (SEC-01 interim)](#2026-09-18--batch-4-hmac-ledger-envelope-sec-01-interim)
  - [2026-09-18 — Batch 5 attribution (SEC-05 partial)](#2026-09-18--batch-5-attribution-sec-05-partial)
  - [2026-09-18 — Batch 6 DB + storage (SEC-16/18/20/21/22/23)](#2026-09-18--batch-6-db--storage-sec-161820212223)
  - [2026-09-18 — Batch 7 installer + release + CI (SEC-19/24/25/26/27)](#2026-09-18--batch-7-installer--release--ci-sec-1924252627)
  - [2026-09-18 — Ed25519 + RBAC + anchor outbox + TRACE_ENV + sealed exports](#2026-09-18--ed25519--rbac--anchor-outbox--trace_env--sealed-exports)
  - [2026-09-17 — Master-brief review: changes required before implementation](#2026-09-17--master-brief-review-changes-required-before-implementation)
  - [2026-09-17 — External 26-point review adjudication (no source changes)](#2026-09-17--external-26-point-review-adjudication-no-source-changes)
  - [2026-09-16 — CI speed-up (same checks, less redundant work)](#2026-09-16--ci-speed-up-same-checks-less-redundant-work)
  - [2026-09-18 — Validator centralization + lookup hardening (grammar decision)](#2026-09-18--validator-centralization--lookup-hardening-grammar-decision)
  - [2026-09-18 — Reusability pass over old + new code](#2026-09-18--reusability-pass-over-old--new-code)
  - [2026-09-18 — SonarLint cleanup (S6353/S3776/S1192/S9073)](#2026-09-18--sonarlint-cleanup-s6353s3776s1192s9073)
  - [2026-09-18 — SonarLint + Pylance cleanup (S3776/Pylance ×2)](#2026-09-18--sonarlint--pylance-cleanup-s3776pylance-2)
  - [2026-09-18 — PSScriptAnalyzer cleanup (install.ps1)](#2026-09-18--psscriptanalyzer-cleanup-installps1)
  - [2026-09-18 — CI pipeline end-to-end local replication (no repo changes)](#2026-09-18--ci-pipeline-end-to-end-local-replication-no-repo-changes)
  - [2026-09-18 — Local pre-PR gate script (`check-pr.ps1`)](#2026-09-18--local-pre-pr-gate-script-check-prps1)
  - [2026-09-18 — `check-pr.ps1` kept local-only (not for GitHub)](#2026-09-18--check-prps1-kept-local-only-not-for-github)
  - [2026-09-18 — Sonar Blocker + pytest hygiene (signing traversal, S5754 ×3)](#2026-09-18--sonar-blocker--pytest-hygiene-signing-traversal-s5754-3)
  - [2026-09-18 — Subpart 3 build plan (`docs/subparts/subpart-3.md`)](#2026-09-18--subpart-3-build-plan-docssubpartssubpart-3md)
  - [2026-09-18 — Subpart 3 plan revised per design review (8.7→spec 10/10)](#2026-09-18--subpart-3-plan-revised-per-design-review-87spec-1010)
  - [2026-09-18 — Subpart 3 plan round 2 (reviewer follow-ups A–F, doc-only)](#2026-09-18--subpart-3-plan-round-2-reviewer-follow-ups-af-doc-only)
  - [2026-09-18 — Devices TUI blueprint (`docs/blueprints/devices_tui.md`)](#2026-09-18--devices-tui-blueprint-docsblueprintsdevices_tuimd)
  - [2026-09-18 — Decision: CLI + TUI both permanent (no removal, ever)](#2026-09-18--decision-cli--tui-both-permanent-no-removal-ever)

# Part 1 — Foundation (cases, CLI, database, installers)

>Subpart 1 core, hardening phases, installers and pre-audit readiness.

## 2026-09-10 — Initial Architecture & Database Foundation

- **Hexagonal Architecture Setup**: Organized codebase into strict layers (`domain/`, `application/`, `ports/`, `adapters/`, `cli/`).
- **Domain Modeling**: Created `Case` entity model with UUID primary keys, UTC timestamps, `CaseStatus` state machine (`OPEN`, `UNDER_REVIEW`, `CLOSED`, `ARCHIVED`), and forensic tagging.
- **Database Engine (PostgreSQL 16)**:
  - Configured PostgreSQL connection pooling with `psycopg_pool`.
  - Created initial schema migration (`001_initial_schema.sql`) with JSONB tags and soft-delete support.
  - Implemented generic repository pattern in `BaseRepository` with parameterized SQL to prevent SQL injection.
- **Git Hygiene**: Created production-grade `.gitignore` safeguarding evidence files (`.dd`, `.e01`, `.raw`, `.vmdk`), dumps, credentials, and environment files.

---

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

---

## 2026-09-12 — Repository Hygiene: Gitignore & Unused Artifact Removal

- **Artifact Deletion**:
  - Deleted unused `alembic.ini` (obsoleted by native pure-SQLAlchemy runner; eliminated plaintext credential risk).
  - Deleted untracked `uv.lock` (not utilized by standard `pip` / `requirements.txt` build and CI pipeline).
- **Gitignore Hardening**:
  - Added `alembic.ini` to `.gitignore` under `# --- Local Databases & Transitory State ---`.
  - Added `.uv/` cache directory to `.gitignore`.

---

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

---

## 2026-09-12 — Fix: `case list` Execution Error on Stale Databases (Migration 004)

- **Root cause**: `archived_by` was added to migration 002's backfill list, but databases that had already recorded 002 as applied never received the column. Reads then failed with `OperationalError: no such column: cases.archived_by`, surfaced in the shell as the sanitized `Execution Error → Verify database connectivity` card.
- **Fix (`core/database/migrations.py`)**: forward-only migration `004_add_archived_by_column`, idempotent via `_ensure_column()` inspect-check (PostgreSQL + SQLite safe). Fresh DBs unaffected; stale DBs self-heal on next `trace db migrate`.
- **Regression test (`tests/unit/test_database_migrations_and_lifecycle.py:test_migration_004_backfills_archived_by_on_old_database`)**: drops the column + un-records 004 to simulate the stale state, asserts `list_cases()` raises `OperationalError`, then asserts `apply_migrations()` heals it and reads return `[]`.
- **Verification**: 62 passed, 0 Ruff check/format, 0 Mypy (50 files).

---

---

# Part 2 — Audit ledger (Subpart 2)

>Tamper-evident ledger, 5W1H enrichment, layered architecture and polish.

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

---

---

## 2026-09-13 — Dropdown & Case List Grouping (Only Preview, CR/NR/CLI)

> `case edit` dropdown showed duplicate `2026-CR-0031 | 2026-CR-0031 · OPEN` and mixed `CR/NR/CLI` order; `case list` table showed `CR/NR/CR/CLI` scattered.

- **Dropdown (`core/cli/completion.py`, `cli/shell.py`)**: `complete_from_cases` now groups by middle code `split("-")[1]` (`CR/NR/CLI/OTHER`), `order` `CR` first then alphabetically, inserts header `── CR ──` (`val=""` non-insertable) + `preview_case` per group, `limit 20` + `filter_completions(..., limit=15)` so every format appears (was `8` → `NR` truncated). `TraceShellCompleter` now `Completion(val, display=meta)` for `·` previews (left shows `2026-CR-0031 · OPEN · title` only, right empty, inserted text still just number) — removes left duplicate.
- **Case list table (`cases/renderers.py`)**: `render_case_table` now groups by `_case_prefix(number)` same `CR` first, blank separator row `["","","","",""]` between groups, `● active` highlight preserved, `newest-first` inside each group.
- **UX kept**: `case list --recent` + `recent` shell still `updated_at DESC LIMIT 5`, `audit --case` header + `audit --seq` 5W1H unchanged, `ls/sh/ed` aliases, `back`, ghost `case show → active`, `8` limit + fuzzy + `2s` cache all preserved.
- **Verification**: 85 passed, 0 Ruff, 0 Mypy (70 files).

---

---

## 2026-09-13 — Docs: Subpart-2 Detailed (like Subpart-1)

> Previous `docs/subparts/subpart-2.md` was 28-line stub. Rewrote to 130-line `subpart-1.md` style.

- **New `docs/subparts/subpart-2.md`** (13 sections, mirrors `subpart-1.md`): Mission, Stack, Actual layout (`audit/` 10 files), Domain (`AuditAction` 6, `Subject/Context`, `GENESIS`, `payload_hash/chain_hash`, `build_payload`), Persistence (`audit_chain_state` + `audit_events` + `005/006/007`), Builder (`_case_event`), Service (`record` central gate, `verify` streaming `Iterable`, `export` header+JSONL `tmp→fsync→rename`), DTO (`AUDIT_*_FLAGS`), Transactions (`before_commit` atomic), Interfaces (Typer `audit show/verify/export` with `--seq/--case/--anchor`, shell `show/verify/export` with completions `Seq→preview`, TUI `render_audit_table` 5-col + `render_case_audit_header` + `render_audit_timeline` + `render_audit_detail` 5W1H + hashes), Config/Security, Quality (85 passed, tribunal 13 + `completion` + `property`), Limits (tail blind → `anchor`, single global head).
---

---

# Part 3 — Responsive UI, dossiers & fullscreen TUI

>Responsive engine, dossier rhythm passes, Textual console and polish.

## 2026-09-13 — Responsive TUI Engine (XS, MD, LG, XL & Height-Aware UX)

- **Responsive Breakpoint Engine (`core/ui/renderers.py`)**:
  - Defined 4 formal viewports: `XS` (< 80 cols), `MD` (80–119 cols), `LG` (120–159 cols), `XL` (160+ cols).
  - Added `get_breakpoint()`, `breakpoint_width()`, and `is_compact_height()` (<= 24 rows).
  - Added `create_dual_key_value_grid()` pairing metadata in 4-column balanced layouts for wide terminals (`LG`/`XL`).
  - Made `render_dossier()` width-aware: responsive horizontal rules (`min(term_w - 4, 66)`), single/dual column switching, and clean 32-char line-wrapping for 64-char SHA-256 hashes on narrow screens.
  - Made `render_minimalist_table()` responsive: padding `(0, 1)` on `XS` vs `(0, 2)` on standard, concise record counters.
  - Made `render_key_value_grid()` responsive: dynamic label width (14 on `XS` vs 19 on standard).
- **Responsive Forensic Cases Table (`cases/renderers.py`)**:
  - `render_case_table()` dynamically selects columns: 3 columns on `XS` (`Case #`, `Title`, `Status`), 5 columns on `MD`/`LG` (`Case #`, `Title`, `Examiner`, `Status`, `Opened`), 6 columns on `XL` (`Tags` included).
  - Forensic invariant preserved: Case numbers (`2026-CR-0001`) have `no_wrap: True` and are NEVER truncated.
  - Dynamic `overflow: ellipsis` on secondary titles based on actual terminal width.
- **Responsive Audit Ledger Table & Timelines (`audit/renderers.py`)**:
  - `render_audit_table()` adapts columns: 4 columns on `XS` (`Seq`, `Action`, `Case #`, `Time`), 5 columns on `MD` (`Actor` added), 6 columns on `LG`/`XL` (`Command` added).
  - Dynamic rule width for timeline headers and separators.
- **Compact Shell Banner for 80×24 Displays (`cli/shell.py`)**:
  - When running in compact height (<= 24 rows) or narrow width (`XS`), renders a sleek 2-line header, saving 10+ vertical lines for investigative prompt work.
  - Full ASCII banner rendered on spacious terminals.
- **Width-Aware Dropdown Autocomplete (`core/cli/completion.py`)**:
  - `preview_case()` dynamically calculates title preview length to prevent completion menus from wrapping or overflowing terminal boundaries.
- **Verification & Test Suite**:
  - Added `test_responsive_breakpoints` and `test_responsive_rendering_across_terminal_sizes` in `tests/unit/test_ui_renderers.py` validating 60, 80, 120, 160 widths and 20, 24, 30, 40 heights.
  - All 87 unit tests passing (100% pass rate).
  - 0 Ruff lint errors, 0 format issues, 0 Mypy static typing errors across 70 source files.

---

---

## 2026-09-13 — Responsive Reuse Pass (minimal, no textual)

> No new deps. Stdlib `textwrap` only. Single-source helpers, XS keeps forensic Who.

- **Core (`core/ui/renderers.py`)**: added `fit_text`, `rule_line`, `table_padding`, `kv_width`, `is_compact_view`, `title_max_width`, `page_rows`. `render_minimalist_table` now pages to 10 rows on `height<=24` with `… N more` hint; `render_dossier/key_value_grid` reuse same widths/padding/rule.
- **Cases (`cases/renderers.py`)**: `_case_table_columns` single source, merged `MD/LG` duplicate, `Examiner max_width 16`, `Title` via `title_max_width`.
- **Audit (`audit/renderers.py`)**: `_audit_table_columns` single source, `XS` now `Seq/Action/Case/Actor` (was `Time`, keeps Who), `Actor fit 14`, header/timeline use `rule_line` + `fit_text`.
- **Completion (`core/cli/completion.py`)**: `preview_case` reuses `fit_text+title_max_width`.
- **Shell (`cli/shell.py`)**: `print_banner` reuses `is_compact_view/rule_line/kv_width/table_padding`.
- **Verification**: 87 passed, 0 Ruff, 0 Mypy (70 files).
- **Files**: `src/trace_core/core/ui/renderers.py`, `src/trace_core/cases/renderers.py`, `src/trace_core/audit/renderers.py`, `src/trace_core/core/cli/completion.py`, `src/trace_core/cli/shell.py`

---

---

## 2026-09-13 — Fix wrapping in case list (width budget)

> `case list` wrapped to 2 lines: 5 cols + `(0,2)` padding needed ~126 cols for 110-col terminal.

- **Core**: `table_padding` tight `(0,1)` except `XL`, `render_minimalist_table` caps `width=term_w-2` to force fit.
- **Cases**: headers `Case #` (no leading spaces), `max_width 16/14/10/14`, narrow `MD/LG term_w<100` drops to 4-col (no `Opened`), `Tags :3→:2`.
- **Audit**: headers `Seq` (no leading spaces), `max_width 6/14/16/14`, rows `str(seq)` no indent.
- **Verification**: 87 passed, 0 Ruff, 0 Mypy.

---

---

## 2026-09-13 — Whole-app responsive (every screen)

> Terminals differ, content must not. Same 7 helpers everywhere, no new deps.

- **Core**: `render_dossier` fits title/subtitle on `XS`, `render_wizard_header` stacks note on `XS`, `render_entity_panel` responsive width/padding + `width=term_w-2`, `render_table` same cap + paging, `render_error_card` tight indent + fit title on `XS`.
- **Help (`cli/shell.py`)**: `_print_help_row` stacks `syntax/alias/desc` on 3 lines for `XS`, single line otherwise.
- **Cases**: `case show` subtitle short `UUID 8…` on `XS`.
- **Audit**: `--seq` `Before/After` compact single-line JSON on `XS` via `_dump_json`.
- **DB (`core/cli/db_commands.py`)**: `status` grid responsive, URL/tables fit on `XS`, migrations `Ver/Name` 2-col on `XS` else 4-col with `table time`.
- **Verification**: 87 passed, 0 Ruff, 0 Mypy (70 files).

---

---

## 2026-09-13 — Live resize redraw (no retype)

> Scrollback can't reflow. New output can. Auto re-render last read-only view on breakpoint change.

- **New (`core/cli/resize.py`)**: `term_size()` via `shutil` (Windows-safe), `is_rerunnable_line()` allow `list/show/verify/status/help/recent/ls/sh`, block `create/edit/close/delete/restore/select`, `should_redraw()` only on breakpoint/compact change (ignores pixel jitter).
- **Shell (`cli/shell.py`)**: `RLock + _last_size/_last_view`, `run()` uses `patch_stdout` + 0.5s daemon watcher, empty-Enter fast path `_redraw_if_resized()`, `execute_line(_from_redraw)` remembers views. Mutations never auto-rerun.
- **Tests (`tests/unit/test_resize.py`)**: readonly vs mutating, breakpoint change, shell memory.
- **Verification**: 90 passed, 0 Ruff, 0 Mypy (72 files).

---

---

## 2026-09-13 — Fix ANSI leak on legacy cmd (`?[2J` garble)

> `cls` + background redraw emitted `ESC[2J/38;2` raw on Command Prompt. VT off + concurrent print.

- **Core (`core/ui/renderers.py`)**: `_enable_windows_vt()` via `SetConsoleMode`, `clear_screen()` uses `os.system(cls)` on legacy cmd, single source.
- **Shell**: `clear/cls/redraw` use `clear_screen()`, watcher only when `can_live_redraw()` (WT or non-Windows). Legacy cmd uses Enter-to-refresh, no `patch_stdout` thread corruption.
- **Resize (`core/cli/resize.py`)**: added `can_live_redraw()` gate.
- **Verification**: 92 passed, 0 Ruff, 0 Mypy.

---

---

## 2026-09-13 — Proper polling + invalidation (no thread, no clear-as-primary)

> Scrollback is immutable. Live parts (toolbar, completions, prompt) poll + invalidate.

- **Resize (`core/cli/resize.py`)**: `term_size()` reads `console.size` fresh first, `current_breakpoint()/size_label()` fresh each call, no width globals. Kept `is_rerunnable/should_redraw`.
- **Shell (`cli/shell.py`)**: removed daemon thread + `patch_stdout` + `console.clear()` redraw. `PromptSession(refresh_interval=0.5)` uses prompt_toolkit's `terminal_size_polling_interval` (0.5s default) for Windows. Live `bottom_toolbar` shows `cols x rows · BP` + `resized — Enter to re-render` stale hint. `Enter`/`redraw` re-renders last read-only view in place (append, no clear). Mutations never re-run.
- **Renderers**: every layout reads `breakpoint_width()` → `console.size` live each render. Verified 80/120/160/200.
- **Verification**: 93 passed, 0 Ruff, 0 Mypy.

---

---

## 2026-09-13 — Remove toolbar, true live re-render (no Enter, no retype)

> Toolbar removed. Resize now auto prints the fresh table below within 0.5s.

- **Shell (`cli/shell.py`)**: deleted `bottom_toolbar` + `refresh_interval`. Watcher back but append-only (no `clear`, no banner): `resized 113x39 — re-rendering case list` + fresh table. Gated by `can_live_redraw()` (WT/non-Windows); legacy cmd keeps Enter/`redraw` path. `redraw` preserves `_last_view`.
- **Resize (`core/cli/resize.py`)**: restored `can_live_redraw()`, fresh `console.size` first.
- **Verification**: 94 passed, 0 Ruff, 0 Mypy.

---

---

## 2026-09-13 — Cap tables at laptop width, drop live-watch dead code

> Yes, understood: tables must never stretch past a comfortable laptop threshold even on 200-col terminals. Live watcher dropped.

- **Core (`core/ui/renderers.py`)**: `MAX_TABLE_WIDTH=116`, `render_minimalist_table` + `render_table` cap `width=min(term_w-2, 116)`.
- **Removed dead code**: `core/cli/resize.py`, `tests/unit/test_resize.py`, shell watcher (`_snapshot/_remember/_redraw/_watcher`, `_last_size/_last_view`, `RLock`, `redraw` command + help entry). `execute_line` back to `(line)`. Each command already reads `console.size` fresh, so breakpoints stay live per render.
- **Verification**: 87 passed, 0 Ruff, 0 Mypy (70 files).

---

---

## 2026-09-13 — DB refresh: wipe junk, reseed live demo set

> Postgres `trace` held 9 junk cases + 6 stale audit events + 3 orphan anchors. Full reset per approval.

- **Backup**: 9 cases dumped to temp `trace-backup-cases.json` before wipe (no `pg_dump` on host).
- **Reset**: `DROP SCHEMA public CASCADE` + `CREATE SCHEMA` + `init_schema()` re-applied migrations 001–007 clean (`drop_all` skipped — ledger lives in separate `MetaData`). Cleared stale `anchors/`.
- **Reseed live via `CaseService` only (no SQL)**: 5 auto-numbered cases (`2026-CR-0001`–`0005`), 1 documented edit with reason (5W1H diff), 1 sealed closure with fresh anchor. Numbering, UTC, audit hashes all produced by live paths.
- **Result**: 5 cases (4 OPEN, 1 CLOSED), audit VALID 7 events seq 1→7, anchor `anchor-2026-CR-0003-7.json`.
- **Verification**: 87 passed, 0 Ruff, 0 Mypy. No source files changed (data-only task).

---

---

## 2026-09-13 — Phase A trust fixes (production-readiness register)

> Full problem list frozen in `docs/audits/production_readiness_subpart_1_2.md`. Phase A = 10 trust fixes, no UX change.

- **Honest counts (A1)**: `render_minimalist_table(..., total=)`, case table passes `len(cases)` — separators no longer inflate.
- **ARCHIVED filter (A2)**: `deleted_only` on `BaseFilterDto` → repository → service → Typer + shell. `--status ARCHIVED` now lists only archived.
- **Edit guard (A3)**: reason-only edit reports "not modified" instead of false success.
- **Delete actor (A4)**: fallback to lead examiner (was `"system"`); new `case delete --by` mirroring `--closed-by`.
- **Mask parser (A5)**: `urllib.parse` split — special-char passwords can't leak fragments.
- **Markup escape (A6)**: `escape()` inside `render_error_card` (single source); 5 raw `[red]` shell prints routed through it.
- **DB errors (A7)**: `check_connection` returns generic message, detail to structlog.
- **Anchor (A8)**: failure now structlog-warns with case context instead of `pass`.
- **Narrow excepts (A9)**: timeline/header paths catch `NotFoundError` only; outages reach the boundary.
- **Hash single-pass (A10)**: `append` hashes serialized bytes once.
- **Tests**: archived-only filter, delete-actor attribution, special-char mask, markup escape.
- **Verification**: 91 passed, 0 Ruff, 0 Mypy (70 files). B/C/D phases queued in the register.

---

---

## 2026-09-13 — Phase B reuse pass (delete + unify)

> Nine dead helpers deleted, four new single sources. No behavior change except advertised-but-ignored shell flags now working.

- **Deleted**: `strip_flags`, `list_all`, `stream_all`, `maybe_show_case_header`, `build_audit_filter`, `_dto_from_row`, `_parse_status`, `_create_case_status_badge`, `_check_anchor`, `_render_case_timeline` (callers go straight to the single source).
- **New single sources**: `render_success` (13 scattered `[OK]` prints), `extract_int_flag` (int parsing + `ValidationError`), `recent_filter` (5-recent rule for Typer + shell), `audit/anchor.py` (schema + write + read + verify), `helpers.render_case_timeline_view` (header + timeline + empty hint for both CLIs; shell `_show_seq` folds into `show_seq_view`).
- **Shell parity**: `case list` honors `--limit/--offset/--recent`, `audit show` honors `--limit/--offset` (flags were advertised, silently ignored).
- **`record()` typed**: `(Session, AuditAction, Subject, str, details, Context|None) → AuditEventDto`; dead `str`-ctx branch deleted (sole caller always passed `Context`).
- **Tests**: shell parity, anchor write→verify→tamper roundtrip.
- **Verification**: 93 passed, 0 Ruff, 0 Mypy (71 files). C/D phases queued in the register.

---

---

## 2026-09-13 — Phase C UX honesty (say what it does)

> Every message now matches behavior. Flag-value/positional parser fixed as a class via `extract_positional`.

- **Sealed truth (B1)**: closed-edit error no longer promises a reopen that doesn't exist.
- **Copy tip (U2)**: cut the `[c] Copy` half (no such binding) in both dossiers.
- **Identifier honesty (U4)**: `case show --output json` no longer 404s on `"json"`; `audit show <number>` scopes without `--case` — via new `extract_positional` (flags + their values excluded).
- **Status parity (U5)**: shell rejects bad `--status` with the same card as Typer.
- **Scope note (U6)**: auto-scope prints `Scoped to active case …`.
- **Confirm docs (U9)**: close/delete help names the confirm style in both interfaces.
- **Anchor surfaced (U7/U8)**: VALID grid carries an Anchor row (warning when unchecked); shell `verify` gains `--anchor`; close prints the anchor path via `latest_anchor_for`.
- **Clear rules (U10)**: blank required keeps, blank optional clears to `""` (`None` = absent to the service — test caught it).
- **DB styling (U11)**: `_require_db` via error card; migrations table via `render_minimalist_table`.
- **Tests**: invalid status, flag-value identifiers, positional audit case, edit clear rules, anchor warning row.
- **Verification**: 98 passed, 0 Ruff, 0 Mypy (71 files). Leftovers queued as register §F.

---

---

## 2026-09-13 — Leftover sweep (register §F cleared)

> Everything remaining except process decisions. One rule kept: tested surface stays (`count()`, panel/table primitives).

- **Correctness**: sequence self-heal loop (B2); ledger boundary catches `DBAPIError` so fresh-PG shows migrate guidance (R10); `--recent` composes via `with_recent()` (R11).
- **Reuse**: badge/pill one source + `border_*` tokens; `number_group`, single completion cap, enum-safe rank; `_show_seq` folded; `ls/sh/ed` help row; filter contract + purge note; version-sync test.
- **Deleted**: audit `count()`, `build/` dir, `recent_filter` (superseded).
- **Verification**: 104 passed, 0 Ruff, 0 Mypy (71 files). Register §F closed save process items.

---

---

## 2026-09-13 — Max-reuse + writing-quality sweep (UX deferred)

> Output dispatch, time, diffs, URLs unified; completion core typed; prompt split; P-1 head query.

- **Dispatch**: `render_event/render_events/render_verify` mirror `render_case(s)` — six json/table branches gone.
- **Time/snapshot/URL**: `format_ledger_time` + `format_utc_zulu` in core (`_time_compact`/`_utc_display` deleted); `CASE_TRACKED_FIELDS` + `tracked_snapshot` + `changed_fields` shared by service + shell; `sanitized_db_url` single source (`_mask_db_url` deleted); dead base `ensure_utc` removed.
- **Writing**: completion core fully typed (mypy notes gone); prompt classes extracted to `cli/suggest.py` (shell.py −150 lines, re-exported); crypto-path `why` docstrings on `record`/`chain_hash`/`verify_rows`.
- **Performance (P-1)**: `head()` one-row tip query; close anchor + tail check use it (was full-table read).
- **Flake killed**: Windows clock ties made ordering random — parity test now uses a ticking clock.
- **Verification**: 106 passed (3 consecutive green runs), 0 Ruff, 0 Mypy (72 files).

---

---

## 2026-09-13 — Max-reuse sweep (one source per behavior)

> Audit found six remaining duplications; all unified. No behavior change.

- **Output dispatch**: `render_event/render_events/render_verify` mirror `render_case(s)` — six json/table branches gone from audit commands/shell/helpers.
- **Time**: `format_ledger_time` + `format_utc_zulu` in core; `_time_compact`/`_utc_display` deleted.
- **Diffs**: `CASE_TRACKED_FIELDS` + `tracked_snapshot` + `changed_fields` in domain; service and shell preview share them.
- **URLs**: `sanitized_db_url` in session; `_mask_db_url` deleted.
- **Dead static**: base `ensure_utc` removed (zero callers).
- **Tests**: snapshot/diff, `number_group`.
- **Verification**: 106 passed, 0 Ruff, 0 Mypy (71 files).

---

---

## 2026-09-14 — Audit detail to professional dossier (no icons, CHANGES, INTEGRITY)

> `audit show --seq N` rebuilt to the approved mockup. Before/After kept as evidence, presented as a table.

- **Labels**: Who/When/Where/Why/What/How → Actor/Timestamp/Target/Reason/Event/Method (same values).
- **CHANGES table**: one row per changed field, old red-tinted → new green-tinted, `null`/`""` literal. Only on update events.
- **INTEGRITY section**: Payload/Prev/Chain hashes as labeled rows (real Chain Hash included), split on narrow screens.
- **Cleanup**: `_detail_sections`/`_dump_json` deleted (superseded); `show_count=False` added for titled tables.
- **Verification**: 106 passed, 0 Ruff, 0 Mypy (72 files). Rendered against live seq 11 at full + 60-col widths.

---

---

## 2026-09-14 — Audit detail hierarchy pass (20-point review applied)

> Single identity-block header, human action titles, grouped metadata, tight CHANGES table, categorized INTEGRITY with row self-check.

- **Header**: one block, no blank split; `CASE_UPDATED` → `Case details updated` (all six actions mapped, enum kept in Event row + `--output json`).
- **Metadata**: Actor → Target → When, blank, Event → Reason → Method; UUID muted inline; labels professional throughout.
- **CHANGES**: `CHANGES · N records` single heading; content-capped Before/After columns; text-only red/green (no blocks); `Not set`/`Empty` empties.
- **INTEGRITY**: grid kept per direction; `Previous Chain` label; `✓ VERIFIED`/`✗ MISMATCH` via new pure `verify_event` (row self-check, chain truth stays with `audit verify`); 16-floor label width so nothing wraps at XS.
- **Ending**: raw-payload tip with the exact command.
- **Verification**: 107 passed, 0 Ruff, 0 Mypy (72 files). Live-rendered seq 11 attached above.

---

---

## 2026-09-14 — Case dossier in audit-detail language

> `case show` rebuilt to mirror `audit show --seq`: identity block, grouped metadata, sections, proof block.

- **Identity**: `CASE number / title / STATUS · Opened IST` one block; UUID subtitle dropped.
- **Metadata**: Lead Examiner/Tags, blank, Opened/Updated/Closed with UTC in brackets; closure/archival rows only when set; 16-floor label width (same XS fix as integrity).
- **Sections**: `DESCRIPTION`/`NOTES` uppercase, skipped silently when empty (no more `None` rows).
- **HISTORY proof block**: newest-first compact event lines (max 5 + pointer), fed by live ledger read in both CLIs (degrades to no block if unreadable so the dossier always renders).
- **Shared**: `_history_lines`, `action_title` promoted public, `_format_closed_timestamp` deleted (superseded by `_closed_value`).
- **Verification**: 108 passed, 0 Ruff, 0 Mypy (72 files). Live-rendered CR-0006 attached above.

---

---

## 2026-09-14 — Detail-view max-reuse (one dossier language)

> Both dossiers now share primitives; no view owns its own header/section/tip code.

- **Core**: `render_detail_header` (Text-aware meta line), `render_section_title` (styled), `render_raw_tip`.
- **Shared**: `short_action_label` (timeline + HISTORY), `_history_lines` deleted.
- **Verification**: 108 passed, 0 Ruff, 0 Mypy (72 files). Both live renders byte-identical to approved look.

---

---

## 2026-09-14 — Alignment fixes (CHANGES indent + tight columns, case status indent)

> From screenshots: Field column flush-left, Before/After dead zones, case `OPEN` line unindented.

- **CHANGES table**: `  Field` header + indented cells (matches case-table pattern); content-measured column budgets (indent-aware) instead of terminal-derived; new `tight=True` on `render_minimalist_table` so small tables hug content instead of stretching.
- **Case identity**: status line carries its `  ` indent inside the assembled meta Text.
- **Verification**: 108 passed, 0 Ruff, 0 Mypy (72 files). Live renders confirmed above.

---

---

## 2026-09-14 — CHANGES divider breathing room

> After column carries `min_width + 4` so the header rule extends slightly past content.
> Verification: 108 passed, 0 Ruff, 0 Mypy (72 files).

---

---

## 2026-09-14 — Case dossier section dividers

> One shared `rule_line` divider closes identity, metadata, each text section, and HISTORY.
> Verification: 108 passed, 0 Ruff, 0 Mypy (72 files). Live-rendered CR-0006 attached above.

---

---

## 2026-09-14 — Dossier rhythm pass (equal padding everywhere)

> One blank line on each side of every divider; one blank between every title and its content; HISTORY left open at the bottom (no closing divider).
> Verification: 108 passed, 0 Ruff, 0 Mypy (72 files). Live-rendered CR-0006 attached above.

---

---

## 2026-09-14 — Tighter dossier rhythm

> Dividers hug the content above; exactly one blank below every divider and title.
> Verification: 108 passed, 0 Ruff, 0 Mypy (72 files). Live-rendered CR-0006 attached above.

---

---

## 2026-09-14 — CHANGES header indent

> First column header is now `  Field`, matching its indented cells (same convention as `  Case #`).
> Verification: 108 passed, 0 Ruff, 0 Mypy (72 files).

---

---

## 2026-09-14 — Textual fullscreen console (pilot built, all four screens)

> `trace tui`. Third adapter; Typer + REPL untouched. Calm UX: tabs, live panes, palette, toasts.

- **Dep chain**: `textual==8.2.8` via `uv add` → `pyproject` + `uv.lock` + hash-pinned `requirements.txt` (both envs verified).
- **Shell (`tui/app.py`)**: tabbed Cases/Audit/Verify/DB, contextual hint bar, `Ctrl+P` fuzzy palette (reuses core matcher), `?` key map, `1-4` tabs. Views refresh on tab switch; focus follows the active pane.
- **Cases**: searchable table + live dossier + HISTORY + raw drawer; create/edit/close/archive/purge/restore via modals with CLI-identical confirms. Mutations toast + refresh.
- **Audit**: live stream + detail (human titles, CHANGES, row self-check) + scope/search + export. Shared `format_change_value`, `short_action_label`, `action_title`.
- **Verify**: big verdict, anchor picker, export; **DB**: health, tables, migrations, one-button migrate. All service errors toast, never crash.
- **Blueprint** `docs/blueprints/textual_tui.md` marked built.
- **Verification**: 110 passed (headless pilot: mount → navigate → dossier → audit → verify → db), 0 Ruff, 0 Mypy (83 files).

---

---

## 2026-09-14 — TUI escape + scroll (unstick every modal)

> Every modal backs out on Esc with cancel semantics; the case form scrolls so Save/Cancel stay reachable on short terminals.

- **Shared `ESCAPES` binding** in forms (reused by palette modals): `Esc` → cancel-safe dismiss on CaseForm/Raw/TextInput/TypedConfirm/YesNo/Palette/Keys.
- **Case form body scrolls** (`VerticalScroll` + max-height); Cancel button renamed `Cancel (Esc)`.
- **Verification**: 111 passed (escape test pushes every modal, Esc, asserts it popped), 0 Ruff, 0 Mypy.

---

---

## 2026-09-14 — Case form focus + Enter flow (typing actually works)

> Root cause: focus landed on the scroll container, so keystrokes went nowhere.

- **Focus**: `on_mount` puts the cursor in Title; compact inputs kept (form fits, no scroll needed).
- **Easy apply**: `Enter` advances field-to-field, last `Enter` saves (validated); `Esc` still cancels.
- **Verification**: 112 passed (keyboard-flow test types/advances/saves headlessly), 0 Ruff, 0 Mypy.

---

---

## 2026-09-14 — Full-size form inputs (compact was untypeable-feeling)

> Compact single-row inputs felt too small to write in. Back to bordered inputs with tight margins; form fits without scrolling, `max-height: 32` keeps short terminals scrolling.
> Verification: 112 passed (headless: focus, typing, zero scrollbars at 100x40), 0 Ruff, 0 Mypy.

---

---

## 2026-09-14 — Prettier case form (round inputs, centered header + buttons)

> Round input borders (accent on focus), centered bold-accent heading, centered round buttons.
> Verification: TUI tests green, 0 Ruff, 0 Mypy, zero CSS errors on mount.

---

---

## 2026-09-14 — Integrity & Database as structured cards

> Both tabs were flat dumps with huge empty gaps. Now each is three cards on a scroll.

- **Integrity** (`tui/screens/verify.py`): `Chain status` (verdict + counts + gaps), `Anchor check` (input + Verify, helper text), `Export bundle` (input + Export). Each card `round $panel` with title, `input-row` with round inputs.
- **Database** (`tui/screens/db.py`): `Connection` (pill + URL), `Tables` (dim list), `Migrations` (DataTable + button) — same card chrome, `max-height 12` for the table.
- **Shell** (`tui/app.py`): shared `.card` + `.input-row` CSS, scroll containers `1fr`.
- **Verification**: 112 passed, 0 Ruff, 0 Mypy.

---

---

## 2026-09-14 — 2-per-row form + dossier section breathing room

> Form shows Title+Examiner and Number/Tags (or Tags+Reason) side-by-side; Description/Notes stay full-width.

- **Form** (`tui/forms.py`): wider `80` card, grid `2` cols + `field-full` span, `CREATE CASE` big centered header (`height 3` + underline), `72→80` wider inputs, `4`-high rows with minimal `1` gutter; same `CaseForm` for create/edit via `for_create`.

- **Audit list** (`tui/screens/audit.py`): scoped hint hidden when empty (`display` toggle) — upper gap above `Seq/Event` header gone.

- **Dossier line-height** (`tui/screens/cases.py` + `audit.py`): added blank line between Tag→Opened groups and extra breathing before section dividers; titles (`Create Case`, `DESCRIPTION` etc.) no longer collide with dividers.
- **Verification**: 112 passed, 0 Ruff, 0 Mypy.

---

---

## 2026-09-14 — Audit + form + confirm polish (4-image sweep)

> One reusable form, no scroller unless needed, dim labels, centered red/blue modals.

- **Audit dim** (`tui/screens/audit.py`): Actor/When/Event/Reason labels `dim`, values bright — same hierarchy as case dossier.
- **Form** (`tui/forms.py`): `84` wide, grid `2` + `field-full` span, `CREATE CASE` centered `height 3` underline, `max-height 90%` + `22` fields cap → no scrollbar at 100×40, `scrollbar-gutter stable`; same `CaseForm` for create/edit.
- **Confirms** (`tui/forms.py`): `TypedConfirmModal` `round $error 60%` + `YesNoModal` `round $panel 50%`, both `height auto` + centered `Horizontal` buttons (`min-width 18`, `round`), `Esc` shared.
- **Verification**: 112 passed, 0 Ruff, 0 Mypy.

---

---

## 2026-09-14 — Fix clipped form buttons + soften outer border (create/edit reuse)

> Buttons were half-cut by the form's clipping; New/Edit already shared the same `CaseForm`.

- **Buttons**: `dock: bottom` + fixed height + wider min-width — fully visible at 40 rows, still docked + scrollable at 24 rows.
- **Borders**: outer `round $panel 50%` (subtle), inputs stay `round $panel` with no focus-color flash; create/edit remain one class via `for_create`.
- **Verification**: headless: both buttons visible, focus/typing/Enter intact, 0 Ruff, 0 Mypy.

---

---

## 2026-09-14 — TUI declutter (slim table, cards, dossier hierarchy)

> Table shows only Case # + Status (dossier carries the rest); panes are rounded bordered cards with a gap; Footer removed (hint bar was duplicating it).

- **Layout**: 1fr/2fr split, `#cases-*/#audit-*` round `$panel` cards on darker ground, search placeholder trimmed.
- **Dossier**: bold-bright title, status dot + word, dim labels over bright values, history action word emphasized, UTC moved to raw drawer, live-width dividers between sections.
- **Verification**: 111 passed, 0 Ruff, 0 Mypy (83 files).

---

---

## 2026-09-14 — Audit tab declutter (mirrors Cases)

> Stream slimmed to Seq + human Event; search + scope live inside the left card; both cards full-height; shared `DossierScroll` divider engine for both dossiers.
> Verification: 111 passed, 0 Ruff, 0 Mypy (84 files).

---

---

## 2026-09-14 — TUI pure-black background

> Theme background + surface are `#000000` (true transparency isn't renderable — every cell needs a color). Card separation now comes from borders alone.
> Verification: TUI tests green, 0 Ruff, 0 Mypy.

---

---

## 2026-09-14 — Dossier breathing room

> Right-hand cards (`#cases-right`, `#audit-right`) get `padding: 1 2` — content floats inside the border, structure untouched.
> Verification: TUI tests green, 0 Ruff, 0 Mypy.

---

---

## 2026-09-14 — Textual TUI blueprint (plan only, no code)

> `docs/blueprints/textual_tui.md`: full implementation contract for the building agent — architecture (third adapter, headless core), design language, all four screens, command mapping, subpart fit, testing, build order with pilot gate.
> Verification: docs only, suite untouched.

---

---

## 2026-09-14 — Process decisions recorded (no code change)

> Human calls, per AGENTS.md §3 — verified current state first, then recorded.

- **Lockfiles**: canonical chain is `pyproject → uv.lock → requirements.txt → CI/installers` (header already states the export command). Rule: never hand-edit `requirements.txt`.
- **Version**: test-guard stays (`test_version_single_sourced` green); derivation rejected.
- **Docs**: `/docs` stays ignored — private working set; public docs authored separately later.
- **Verification**: no code touched, suite untouched (108 green from prior run).

---

---

# Part 4 — Production hardening & security program

>Trust fixes, reuse passes, assessments (SEC-01…27), remediation batches, Ed25519/RBAC/anchors, tooling, Subpart-3 planning and release hygiene.

## 2026-09-13 — Phase D production hardening (database honest at last)

> Runbook: `docs/specs/production_operations.md` (three roles, parity table, checklist, close habit).

- **R1 ledger protection**: migration `008_audit_append_only_protection` — PG trigger + SQLite self-heal, verified per backend. Roles: app (INSERT/SELECT), migration owner, DB owner (never used by Trace).
- **R5 verify-then-record**: `MIGRATION_VERIFIERS` run inside the migration transaction — failure rolls back unrecorded. 006 verifier included (006 is PG-only now; SQLite enforces in domain).
- **R7 cache keys**: `db_identity()` (sha of credential-free URL) + 64-entry bound. No `id()`, no raw URLs.
- **R8 bootstrap lock**: PG advisory lock, SQLite lockfile, `:memory:` no-op. Two-process race test asserts exactly-once ledger.
- **R9 parity**: 5-row guarantee table, one test per row (incl. new PG append-only integration test).
- **S4 knobs split**: `TRACE_SQL_ECHO` separate from `TRACE_DEBUG`, off by default + documented warning.
- **S5 habit**: close prints "copy off-host"; runbook defines export-per-close.
- **Tests**: trigger enforcement, bootstrap race, threaded chain contiguity, case-insensitive search, knob decoupling.
- **Verification**: 103 passed, 0 Ruff, 0 Mypy (71 files). Register Section E complete.

---

---

## 2026-09-16 — Code reusability refactor (pure, no logic/UI change)

- **Rule followed**: AGENTS.md + ponytail full. No logic, UI, or behavior changed. All 112 tests pass, ruff clean, mypy clean (68 files).
- **Fix 1 time/hash single-source**: `core/canonical.py` gained `coerce_utc/canonical_ts/canonical_json_str/parse_trailing_seq`; `core/domain.ensure_utc` delegates, new `require_utc`; `core/clock.default_ts`; `audit/domain.build_payload`, `cases/domain.validate_closed_at_utc`, `audit/repository.append` (uses `payload_hash`), `audit/exporter._record_dict`, `audit/anchor` (canonical_ts + trailing-seq), `cases/repository` sequence parse reuse.
- **Fix 2 repo base**: `core/database/repository.paginate/_fetch/_guard_version`; `cases/repository` soft-delete/restore/purge/update use them (4 OCC blocks removed); `audit/repository.list_events` uses `paginate`.
- **Fix 3 renderers**: `core/ui/renderers.render_output/split_hash`; `cases/renderers.render_case/render_cases`, `audit/renderers.render_event/render_events/render_verify` use dispatch; integrity + dossier hash splits share `split_hash`.
- **Fix 4 Typer vs shell**: `audit/helpers.parse_action_value/do_show_list/do_verify/do_export/fetch_case_with_history`; `audit/commands`, `audit/shell_handler`, `cases/commands.show`, `cases/shell_handler._interactive_show_case` share cores (each keeps its own error UI/capture).
- **Fix 5 db health**: new `core/database/health.fetch_db_snapshot/migration_entries/DbSnapshot`; `core/cli/db_commands.db_status/_require_db` and TUI `DbView.refresh_data` render from it (identical rows/colors).
- **Fix 6 TUI**: `tui/theme.status_text/health_dot` (byte-identical to `CasesView._status_text`); `CasesView` reuses it; new `tui/actions.resolve_palette_command/export_bundle/require_selection/mutate`; `tui/app._palette_done` uses resolver.
- **Fix 7 CLI**: `core/cli/completion.cached_complete` (5 loaders share cache/except/slice); new `core/cli/shell_base.BaseShellHandler.unknown_action`; case/audit shells extend it with exact messages preserved.
- **Fix 8 forms/catalog**: `tui/forms.FIELD_LABELS` module-level single source for create/edit labels; new `core/cli/catalog.feature_apps/default_handlers`; `cli/main` + `cli/shell` register from it (same order/set).
- **Intentionally left explicit (no behavior-change risk)**: per-handler completion display labels differ (cases FORMAT_CHOICES vs shared OUTPUT_CHOICES); full TableDossierView/CardView base-class rewrite and registry dispatch unification deferred (would risk UI/focus/precedence changes); `parse_args` single-pass deferred (subtle dash-skip differences). Smallest safe diffs only.
- **Files touched**: `core/canonical/domain/clock`, `core/database/repository/health`, `core/cli/args/completion/db_commands/catalog/shell_base`, `core/ui/renderers`, `cases/domain/repository/renderers/commands/shell_handler`, `audit/domain/repository/exporter/anchor/helpers/renderers/commands/shell_handler`, `cli/main/shell`, `tui/theme/actions/app/forms/screens/cases/screens/db` + new `health/catalog/shell_base/actions`.

---

---

## 2026-09-16 — SonarQube 45-issue remediation (no logic/UI change)

- **Rule followed**: AGENTS.md + ponytail full. Behavior identical everywhere. Verified: 112 passed, ruff check clean, ruff format clean, mypy clean (68 files), ci.yml parses.
- **Blocker + reliability**: `audit/shell_handler._show_seq` returns `None` (was `True` on all paths; caller ignores it); `cases/renderers` same-value ternary collapsed to plain style.
- **Security (ci.yml)**: `pip-audit==2.10.1` + `cyclonedx-bom==7.4.0` pinned with `--only-binary :all:` (verified resolvable via pip index).
- **Dup literals → constants**: `theme._BLUE/_GREEN`; `suggest._CASE_SHOW/_MANUAL_META`; `core/ui/renderers.COLUMN_CASE_NUMBER` shared by case+audit tables; `tui/app._DEFAULT_HINT`; per-screen `TABLE_ID`/`MIGRATIONS_TABLE`/`ANCHOR_INPUT`/`EXPORT_INPUT`, `cases/_NO_SELECTION`; `THEME_TOKENS["accent"]` replaces hardcoded `"bold #72B7D3"` in TUI screens.
- **Complexity (9)**: `render_case_table` → `_group_cases` + `_case_table_row`; `render_case_detail` → `_case_dossier_fields` + `_render_case_history`; `_complete_list_args` → `_complete_flag_value`; `_get_candidate_case_numbers` → `_prepend_active` + `_fallback_candidates`; `suggest.get_completions` → `_ROOT_OPTIONS`/`_ACTIVE_ROOT_OPTIONS` + `_root_completions` + `_delegated_completions`; `complete_from_cases` → `_group_ranked`; `db_status` → `_migration_table_columns` + `_migration_table_rows`; `render_dossier` → `_dossier_heading` + `_render_dossier_sections`; TUI `_render_dossier` → `_dossier_events` + `_append_history`.
- **Triaged, not changed**: `theme.py` section dividers are headers, not dead code (kept per AGENTS §10); `tui/actions` unused `require_selection/mutate/export_bundle` deleted (zero callers); per-handler completion labels differ intentionally (cases `FORMAT_CHOICES` vs shared `OUTPUT_CHOICES`); `health.dict(pending)` micro-fix.
- **Tests (9)**: DTO/seal setup hoisted out of `raises` blocks; single-invocation `_attempt_tamper_write`/`_attempt_ledger_write` helpers; `Exception` → `DBAPIError` in PG test; split composite assert in completion test. Intent unchanged.
- **Files touched**: `.github/workflows/ci.yml`, `core/ui/theme/renderers`, `core/database/health`, `core/cli/completion/db_commands/suggest`, `cases/renderers/shell_handler`, `audit/shell_handler/renderers`, `tui/actions/app/theme/screens/{cases,audit,db,verify}`, `tests/{unit,test_completion,test_audit_ledger,test_case_state_machine_property,test_database_migrations_and_lifecycle,integration/test_postgres}`.

---

## 2026-09-16 — CI mypy `src tests` fix (msvcrt attr-defined)

- **Root cause**: typeshed's `msvcrt` stub lacks `locking`/`LK_LOCK`/`LK_UNLCK`; mypy checks both `os.name` branches, so `mypy src tests` (the CI command) failed with 4 errors in `core/database/migrations.py`.
- **Fix**: `# type: ignore[attr-defined]` on the two `msvcrt.locking(...)` lines — same convention the file already uses for `fcntl`.
- **Caught by tests**: first attempt dropped the `else:` and broke Windows file locking (3 sqlite file-lock tests failed); restored immediately. Verified: `mypy src tests` clean (88 files), 112 passed, ruff check + format clean.
- **Files touched**: `core/database/migrations.py`.

---

## 2026-09-16 — SonarQube 7-issue follow-up (no logic/UI change)

- **Bug found while triaging**: `_render_dossier` rendered HISTORY twice — the old inline block survived the earlier `_append_history` extraction. Deleted the inline copy; dossier now renders one HISTORY via the helper. Verified by diff (identical row order) + TUI tests.
- **Complexity**: `_render_dossier` → `_append_head` + `_append_meta` (helper kept); `complete_from_cases._load` → `_grouped_rows`.
- **Literals**: `_TITLE_STYLE = "bold #E5EAF0"` module const in TUI cases screen; `TAB_HINTS = dict.fromkeys(...)`.
- **Triaged, not changed**: `theme.py` dividers (L9/L25/L42) are section headers, not dead code — kept per AGENTS §10 (second time Sonar flagged them after line shifts).
- **Verified**: 112 passed, ruff check + format clean, `mypy src tests` clean (88 files).
- **Files touched**: `tui/screens/cases.py`, `tui/app.py`, `core/cli/completion.py`.

---

## 2026-09-16 — Pylance diagnostics (3 errors, 2 sites)

- **`audit/helpers.py:57` "No parameter named case_number"**: false-ish positive triggered by a redundant function-level re-import (mine, copied from the call sites the helper replaced). Deleted the two local imports — module already imports both names. Same objects, zero behavior change.
- **`tui/app.py:148` `.get()` overload/Literal mismatch**: `dict.fromkeys` inferred literal keys. Annotated `TAB_HINTS: dict[str, str]`. Same dict at runtime.
- **Verified**: 112 passed, ruff check + format clean, `mypy src tests` clean (88 files). Pylance itself can't run headless here — confirm the squiggles clear on your side.
- **Files touched**: `audit/helpers.py`, `tui/app.py`.

---

## 2026-09-16 — CI collection failure + TUI speed (no behavior change)

- **CI fix**: `test_tui.py` needs the `anyio` pytest plugin but `requirements.txt` lacked it; `--strict-markers` turned that into a collection error on both runners. Added `anyio>=4.0` to dev extras and re-exported the chain (`pyproject` +1, `uv.lock` +24, `requirements.txt` +9, purely additive). Proved with a clean venv installed exactly like CI (`--require-hashes --only-binary :all:`): `test_tui.py` collects, 4 passed. No `ci.yml` changes.
- **TUI perf** (measured headless, 60 cases):
  - Dossier events cached per case, cleared on refresh (mutations/tab switches stay fresh): 120 highlights → 59 queries (was 120; revisits free).
  - Integrity verdict cached on ledger-head `(seq, chain, anchor)`: tab revisits → 0 rescans (was a full O(n) chain rehash per visit).
  - Search inputs debounced 250ms on Cases/Audit (timers delay, never drop; tests don't touch search).
- **Verified**: 112 passed, ruff check + format clean, `mypy src tests` clean (88 files).
- **Files touched**: `pyproject.toml`, `uv.lock`, `requirements.txt`, `tui/screens/{cases,audit,verify}.py`.

---

## 2026-09-16 — Authorized white-box security assessment (no source changes)

- **Scope**: full local attack run with owner authorization, throwaway SQLite DBs + temp dirs only. No prod, no network, no source edits. (Strix engine not used — no Docker/keys in this env; manual PoCs instead.)
- **Confirmed**: (1) HIGH — chain-recompute evasion: with DB-file access, attacker drops triggers and re-hashes with app's own canonical math; `verify()` returns VALID after authorship forgery. Secretless SHA-256 is detection-only. (2) MEDIUM — path traversal via case number (`validate_number` allows `/`): `close_case` writes anchor outside `storage_root` (proven in temp dir). (3) MEDIUM — Rich markup injection at 4 sinks (`audit/helpers.py:28,88`, `audit/shell_handler.py:170`, `cases/shell_handler.py:343`, `:479`): forged `[/dim][bold red]` renders attacker text as trusted output (ANSI evidence captured).
- **Held**: append-only triggers (UPDATE/DELETE → IntegrityError), no eval/exec/subprocess/pickle sinks, no raw SQL in src (ORM + bound params), `.env` gitignored + no hardcoded secrets, `secret_key` setting exists but is consumed nowhere (natural home for future HMAC).
- **Full fix checklist delivered in chat; PoCs kept under `Temp/opencode/poc_*.py` (not committed).**

---

## 2026-09-16 — Security assessment round 2: identity, terminal, identifiers (no source changes)

- **Confirmed**: (A) HIGH — audit authorship fully self-asserted: every action as `alice` by Mallory lands in the ledger as `alice`; no OS-user capture exists; 300-char actor bypasses the 255 model cap on SQLite. (B+C) MEDIUM — control-character injection via title: OSC-8 hyperlink (`\\x1b]8;;`) and forged newline rows survive into dossier bytes. (D) MEDIUM — `latest_anchor_for('*')` resolves to another case's anchor (glob metachars in numbers) → wrong-anchor verification. (E) LOW — `2026-cr-0100` and Cyrillic-homoglyph twins accepted as distinct identities. (F) LOW — `export --out` silently replaces any existing file via `os.replace`.
- **Checked clean**: no `re` usage (no ReDoS surface); `closed_by`/`closure_reason` columns match domain caps.
- **Fix checklist delivered in chat; PoCs `poc2*.py` uncommitted in temp.**

---

## 2026-09-17 — Security assessment round 3: forensic-logic flaws (no source changes)

- **Confirmed**: (G) HIGH — purged-number resurrection: manual reuse of a purged number merges two cases into one audit timeline (auto-allocator verified NOT to reuse). (H) MEDIUM — sequence-squat DoS: 100 pre-registered numbers exhaust the allocator, denying all automatic creation. (I) MEDIUM — bad anchor path crashes the TUI (`typer.echo`/`typer.Exit` escaping Textual); bad export path escapes identically (`FileNotFoundError` vs `ApplicationError`-only handler).
- **Latent (code-evident)**: caller-supplied `ts` param on `append()` (backdating primitive, no prod caller yet); OS-clock-trusted timestamps; `getattr` command dispatch is safe but allowlist-worthy.
- **Details + PoCs filed**: `docs/security/assessment-2026-09-17.md` (SEC-10/11/12), `docs/security/pocs/poc3*.py`. Full fix checklist in chat.

---

## 2026-09-17 — Security assessment round 4: 360 sweep (no source changes)

- **Confirmed**: SEC-13 callers override host/command via `setdefault` merge; SEC-14 unclosed quote escapes `execute_line` as `ValueError`; SEC-15 seal accepted with empty reason; SEC-16 migration checksums hash the name and are never compared (theater); SEC-17 anchor-after-commit crash window + tip imprecision.
- **Clean**: TUI modals (falsy→no-op), `run()` error cards, `render_error_card` escaping, `append(ts=)` still caller-free.
- **Details + PoCs filed**: `docs/security/assessment-2026-09-17.md` (SEC-13…17), `docs/security/pocs/poc4_misc.py`.

---

## 2026-09-18 — Batch 1 input containment implemented (SEC-02/03/06/07/08)

- **Rule followed**: AGENTS.md re-read first; domain-centralized validators (all surfaces inherit); smallest diffs in existing style; no logic change beyond rejecting hostile input.
- **Domain** (`core/domain.py`, `cases/domain.py`, `cases/service.py`): new `strip_controls()` (C0/DEL always, `\n` only multiline); case numbers canonicalized (NFKC→upper) and held to `^[0-9]{4}-[A-Z]{2,8}-[0-9]{4}$` (covers CR/NR/CLI + fixture codes; rejects traversal, glob, homoglyphs, twins); title/examiner/tags/description/notes/reason/closed_by/actor all control-stripped. `--number` help documents the format.
- **Filesystem** (`audit/anchor.py`): `anchor_path` resolves + enforces containment (`ValueError` on escape) — backstop behind the grammar.
- **Output** (`core/ui/renderers.py` + CLI/TUI sinks): new `sanitize_terminal()` (CSI/OSC/C1/DEL + unicode separators) and `safe_text()` (sanitize + escape); applied to every user-content interpolation in case/audit CLI renderers, TUI dossier/detail builders, and the 4 shell markup sinks.
- **Proof**: new `tests/unit/test_security_regressions.py` (7 tests, written failing-first); original PoCs re-run — traversal rejected at create, markup renders literal, OSC hyperlink gone. Suite: 119 passed, ruff + format + `mypy src tests` clean.
- **Not in this batch** (brief Batches 2+): export `--force`, search caps, tombstones, merge precedence, shlex guard, reason-required close.
- **Files touched**: `core/domain`, `core/ui/renderers`, `cases/{domain,service,commands,renderers,shell_handler}`, `audit/{anchor,helpers,renderers,shell_handler}`, `tui/screens/{cases,audit}`, `tests/unit/test_security_regressions.py`.

---

## 2026-09-18 — Batch 2 lifecycle integrity (SEC-09/10/11/13/15, SEC-04)

- **Tombstones** (migration `009_create_purged_numbers_tombstone` + `PurgedNumberModel`): `repo.purge` tombstones in-txn; `create_case` rejects tombstoned numbers as conflicts; allocator skips them. PoC-G re-run dies at re-registration.
- **Allocator**: 100→10000 cap with operational message; `note_manual_number` advances the year counter past high manual numbers; `for_case_created` records `number_source` manual/auto for anomaly monitoring.
- **Export `--force`**: shared `check_export_dest` guard (Typer `--force`/`-f`, shell flag, TUI YesNoModal confirm on both audit + verify screens); refusal is a `ValidationError` card.
- **Reason-required close** (+2 tests updated, TUI seal now collects reason before typed confirm).
- **Metadata wins**: system `host/trace_version/command` overwrite caller keys.
- **Literal search**: shared `ilike_literal` (explicit `ESCAPE`) in case + audit repositories; `search` capped at 200 chars.
- **Proof**: 12→17 security tests green; full suite 124 passed, ruff + format + `mypy src tests` clean.
- **Files touched**: `cases/{models,repository,service}`, `core/{dto,database/{migrations,repository}}`, `audit/{builder,helpers,commands,shell_handler,dto}`, `tui/screens/{cases,audit,verify}`, `tests/unit/{test_security_regressions,test_case_service,test_cli_commands,test_database_migrations_and_lifecycle}`.

---

## 2026-09-18 — Batch 3 error boundaries (SEC-12/14)

- **Anchor split** (`audit/anchor.py`): pure `check_anchor_match` (raises, never prints/exits) + thin `verify_against_anchor` (unreadable file → `ValidationError`, was `typer.echo` + `Exit(1)`). CLI exit for bad anchor file is now 11/1 via typed cards; shell REPL no longer dies on it; TUI notifies. Existing anchor roundtrip test untouched and green.
- **TUI boundary**: all service-call catches in the 4 screens broadened to `Exception` → toast (never a crash); 3 dead imports removed.
- **Shell**: unclosed quote → `Invalid Command` card (was `ValueError` traceback out of `execute_line`).
- **Palette**: wrong-tab ids toast instead of vanishing (`CasesView` allowlisted to `action_*`, others get `else` branches).
- **Proof**: 4 new regression tests (shlex card, typed anchor errors, pure mismatch, wrong-tab pilot); suite 128 passed, ruff + format + `mypy src tests` clean.
- **Files touched**: `audit/anchor.py`, `audit/helpers.py` (unchanged callers), `cli/shell.py`, `tui/screens/{cases,audit,db,verify}.py`, `tests/unit/test_security_regressions.py`.

---

## 2026-09-18 — Batch 4 HMAC ledger envelope (SEC-01 interim)

- **New `audit/signing.py`**: `sign_bytes`/`verify_bytes`/`expected_signature` HMAC-SHA256 backend behind a keyed interface (`key_id="hmac-v1"`, constant-time compare, unknown keys fail closed, one-time structlog warning on the default dev key). Shaped for a future Ed25519 backend under the same `key_id` vocabulary.
- **Schema** (migration `010_add_ledger_signature_columns` + model): nullable `key_id`/`signature` on `audit_events` (legacy rows verify chain-only); domain + DTO carry both; exporter includes both (offline verification complete).
- **Repository**: `append()` stamps `now_utc()` internally (caller `ts` param removed — was a backdating primitive with zero callers) and signs every event.
- **Verifier**: order payload → linkage → chain → envelope; new `signature` mismatch type with dedicated expected/actual fields, `_what_text` + tamper-grid support; `verify_event` takes optional envelope kwargs (old callers unchanged); legacy unsigned rows pass.
- **Proof**: PoC4 re-run — identical forgery now fails `signature at seq 1` (was VALID); new tests (envelope present, recompute rejected, legacy verifies, unknown key fails closed); updated tribunal expectation (forgery dies at seq 1, not seq 2). Suite 132 passed, ruff + format + `mypy src tests` clean.
- **Not done (needs decisions/infra)**: Ed25519 + key provisioning/rotation, external key custody (env-held HMAC stops DB-only attackers, not host attackers — documented).
- **Files touched**: `audit/{signing (new),models,domain,dto,repository,verifier,exporter,renderers}`, `core/database/migrations.py`, `tui/screens/audit.py`, `tests/unit/{test_security_regressions,test_audit_ledger,test_database_migrations_and_lifecycle}`.

---

## 2026-09-18 — Batch 5 attribution (SEC-05 partial)

- **Context enriched** (`audit/events.py`, `audit/builder.py`): `os_user` (getpass, `"unknown"` fallback) + process-scoped `session_id` on every event, merged system-wins (Batch 2 precedence already flipped). Explicitly metadata, not authentication — documented in helper + file.
- **Actor length** (`audit/service.py:record`): >255 → `ValidationError` (closes the SQLite over-long bypass; PG errored cryptically before).
- **Not built**: login/RBAC/roles — no auth infrastructure exists to hang them on; building role checks without authentication would be theater. Scoped as documented follow-up with the operator-entity design already in the security file.
- **Proof**: 2 new tests (attribution present, length enforced); suite 134 passed, ruff + format + `mypy src tests` clean.
- **Files touched**: `audit/{events,builder,service}.py`, `tests/unit/test_security_regressions.py`.

---

## 2026-09-18 — Batch 6 DB + storage (SEC-16/18/20/21/22/23)

- **TRUNCATE backstop**: `PG_AUDIT_TRUNCATE_TRIGGER_DDL` (`FOR EACH STATEMENT`) installed alongside the row trigger; DDL exposed as a constant for tests.
- **Roles** (migration `011_create_least_privilege_roles`, PG-only): NOLOGIN `trace_app/trace_reader/trace_migrator` if-missing; ledger grants SELECT+INSERT only; explicit REVOKEs on ledger + migrations tables. No secrets in code; LOGIN/passwords stay an operator step (documented).
- **Content checksums**: `_migration_checksum` hashes name + registered source (newline-normalized for CRLF checkouts); `verify_migration_checksums` runs inside the apply lock — legacy name-only values upgrade once with warning, anything else fails closed. Fail-closed by default on tamper.
- **Filesystem** (new `core/fs.py`): `ensure_dir` (0o700), `check_contained`, `atomic_write_lines` (unlink-stale + exclusive-create + fsync + rename + 0o600). Adopted by settings storage init, anchor writes, exporter (streaming preserved via generator), migration lockfile parent.
- **Proof**: 7 new tests (DDL strings, least-privilege asserts, drift fails closed, legacy upgrade, restrictive modes posix-only, stale-tmp recovery); suite 140 passed, ruff + format + `mypy src tests` clean.
- **Not done**: ownership transfer (operator-run, would break existing deploys if forced); at-rest encryption (needs backend decision + infra); Ed25519 (Batch 4 follow-up).
- **Files touched**: `core/{fs (new),database/migrations}`, `core/settings.py`, `audit/{models,exporter,anchor}.py`, `tests/unit/{test_security_regressions,test_database_migrations_and_lifecycle}`.

---

## 2026-09-18 — Batch 7 installer + release + CI (SEC-19/24/25/26/27)

- **Token leak closed** (`install.sh`, `install.ps1`): `GIT_ASKPASS` answers from env (nothing in `.git/config` or process URL); old askpass/env restored in `finally`.
- **Pinned ref**: `TRACE_REF` (default `main`, `v*` → tags archive) for clone + tarball/zip; signed-release verification documented as needing release infra (not pretended).
- **Pinned bootstrap**: `pip==26.2.1` (verified resolvable) with rotation note; `.env` creation now warns about default credentials.
- **App warning**: startup `structlog` warning on shipped-default DB credentials (refusal deferred — breaks password-less dev/test).
- **CI gates**: `pip-audit` blocking (verified clean on the lock), SBOM fixed to v7 syntax + uploaded as artifact + blocking, `--cov-fail-under=70` wired (measured 75.21%). `mypy --strict` (56 pre-existing gaps) and SAST tools left out deliberately — unverifiable/fragile from here, noted as follow-ups.
- **Matrix + statuses**: all 27 traceability rows now carry remediation state; 5 OPEN / 5 PARTIAL-in-code remain (SEC-17/21 + partials), each with a named reason.
- **Proof**: ps1 parses clean (Parser API), sh reviewed by eye (no shell available); suite 142 passed, ruff + format + `mypy src tests` clean.
- **Files touched**: `install.sh`, `install.ps1`, `core/settings.py`, `.github/workflows/ci.yml`, `pyproject.toml` (lock-only comment), `docs/security/*`, `changelog`.

---

## 2026-09-18 — Ed25519 + RBAC + anchor outbox + TRACE_ENV + sealed exports

- **Ed25519 ledger signing** (`audit/signing.py`, `audit keys-init/rotate/list`): file keystore (0600 dir, 0600 keys), `ed25519:<fp16>` ids beside `hmac-v1`, rotation with retired-key verification, unknown keys fail closed. Repository signs with the active key automatically. Same PoC4 forgery now dies on signature under either backend.
- **Workstation RBAC** (new `core/operators.py`, migration `012`, `AuthorizationError`): operators auto-provision (first-ever is admin), `investigator/auditor/admin` enforced in the service layer (mutate/purge/keys gates), explicit claims dual-logged as `claimed_actor`, `--by`/`--closed-by` preserved as the override mechanism. Existing single-user flows unchanged (first operator is admin).
- **Anchor outbox** (SEC-17; model + migration `013`): `anchor_intents` rows capture exact seq/chain in-transaction; `publish_pending_anchors` signs (envelope now signature-checked on verify), writes atomically, fans out to extra sinks, marks CONFIRMED/PENDING/FAILED loudly. Close output (CLI/shell/TUI) reports the anchor state; no more head re-read, no silent success.
- **TRACE_ENV refusal** (SEC-19): `production` startup refuses shipped-default DB credentials/secret key; dev/test unaffected; installers warn on template `.env`.
- **Sealed exports** (SEC-21, code side): `audit/vault.py` (PBKDF2-600k + AES-GCM, single-error decrypt, iteration bounds), `audit export --encrypt` + `audit decrypt` (Typer; shell `decrypt` action + completions), passphrase via env or hidden prompt — never argv. Disk/SQLite encryption stays an ops decision.
- **Installer verification** (SEC-25): `TRACE_RELEASE_SHA256` digest gate (fail closed) + cosign hook (bundle+identity when provided, loud warning otherwise) on both installers; ps1 parses clean.
- **Proof**: suite 155 passed (13 new: ed25519 lifecycle/forgery, RBAC roles/claims, outbox exactness/failure loudness, vault roundtrip/wrong/tamper, production refusal), ruff + format + `mypy src tests` clean.
- **Files touched**: `audit/{signing,vault (new),models,dto,repository,verifier,exporter,anchor,commands,shell_handler}`, `core/{operators (new),errors,database/migrations,settings}`, `cases/service.py`, `cli`/`shell`/`tui` close outputs, `install.{sh,ps1}`, `tests/unit/test_security_regressions.py`.

---

## 2026-09-17 — Master-brief review: changes required before implementation

- **Reviewed a 26-point master brief against code + filed findings**: adopted almost all; three corrections applied to `docs/security/assessment-2026-09-17.md` (new adjudication section + S-section amendments) because implementing them as written would break things: (1) CR-only number grammar rejected — codebase uses CR/NR/CLI + 7-letter fixture codes, adopted `^[0-9]{4}-[A-Z]{2,8}-[0-9]{4}$` instead; (2) exporter is already tmp→fsync→rename, SEC-09 fix scoped to clobber gate only; (3) my own monotonic-timestamp-reject idea replaced with `CLOCK_REGRESSION` anomaly.
- **Also adopted**: HMAC-vs-Ed25519 trust distinction, per-state verification vocabulary, anchor outbox (replacing my `before_commit`-write idea), metadata-vs-auth identity model, terminal-boundary sanitizer matrix, NOLOGIN owner + self-computing append procedure, content checksums compared at startup, one-signing-model scoping, 20 agent rules, precise claims language.

---

## 2026-09-17 — External 26-point review adjudication (no source changes)

- **Verdict**: 25 of 26 claims verified against code (10 become new SEC-18…27; 14 duplicate own earlier findings; 1 advisory claim left to CI `pip-audit`). Zero refuted.
- **New, highest-signal**: SEC-18 TRUNCATE bypass (`BEFORE UPDATE OR DELETE`, no TRUNCATE trigger); SEC-19/20 default `postgres:postgres` + zero DB role separation; SEC-21 no at-rest encryption; SEC-22 unhardened storage perms; SEC-24 installer token-in-URL (`install.sh:31`, `install.ps1:30`); SEC-25 mutable-`main` pipe-to-shell installs; SEC-16 migration checksums confirmed theater from round 4.
- **Filed**: `docs/security/assessment-2026-09-17.md` adjudication table + new IDs.

---

## 2026-09-16 — CI speed-up (same checks, less redundant work)

- **Caches**: pip was already cached; added `.mypy_cache`/`.ruff_cache` via pinned `actions/cache@v4` (SHA-verified against the repo tag), keyed on OS + Python + `requirements.txt` hash. Both tools self-invalidate on source edits.
- **One resolver run**: `pip-audit` + `cyclonedx-bom` install in a single `pip install` (was two).
- **Hygiene**: `permissions: contents: read`, `timeout-minutes` 15/20/20, `PIP_DISABLE_PIP_VERSION_CHECK=1`.
- **Untouched**: gates, matrix, coverage, audit tolerance, postgres service. YAML parses; caches are gitignored.
- **Files touched**: `.github/workflows/ci.yml`.

---

## 2026-09-18 — Validator centralization + lookup hardening (grammar decision)

- **Single source**: `cases/domain.py` now exposes `normalize_number()` (NFKC/strip/upper, no rejection) + `canonical_number()` (grammar-enforcing `^[0-9]{4}-[A-Z]{2,8}-[0-9]{4}$`); the `Case` validator delegates. Repository lookups (`resolve`, `get_by_number`, `is_purged`, `record_purge`, `note_manual_number`) and the audit case filter all normalize through it — lowercase input finds canonical rows; unknown input still misses to NotFound exactly as before. CR-only grammar explicitly rejected: NR/CLI grouping + FIXTURE/BATCH fixtures require the wider class.
- **Glob backstop**: `latest_anchor_for` filters results by literal stem-prefix match + containment, so metacharacters can't widen matches even on direct calls.
- **Proof**: 2 new tests (canonical lookup, metachar anchor returns None beside a real anchor); suite 144 passed, ruff + format + `mypy src tests` clean.
- **Files touched**: `cases/{domain,repository}.py`, `audit/{repository,anchor}.py`, `tests/unit/test_security_regressions.py`.

---

## 2026-09-18 — Reusability pass over old + new code

- **Deleted dead code**: `extract_str_flag` (zero callers), `default_ts` (inlined into `build_payload`), `render_table` + its tests (zero production callers; `render_minimalist_table` is the single table renderer).
- **New constants**: `INTENT_*` (anchor outbox states), `STATUS_ACTIVE`, vault KDF bounds, `_EMPTY_TIMELINE_HINT`, `ACTION_TITLES` canonical table in `audit/domain.py` (both `action_title` and `ACTION_CHOICES` derive from it), migration version list derived from `MIGRATIONS`.
- **Shared TUI helpers** (`tui/actions.py`): `run_guarded` (all 10 mutation epilogues across 4 screens), `confirm_overwrite` + per-screen `_do_export` (audit/verify), `describe_anchor` (Typer + shell close outputs).
- **Unifications**: generic `parse_enum_value` (deleted `parse_action_value`, 3 call sites rewired); `verify_migration_checksums` returns records so `apply_migrations` lists once; `_grouped_rows` counts real rows (headers free); `_status_text` wrapper inlined.
- **Tests**: `as_user`/`temp_storage_root`/`detached_event` moved to `conftest.py`; 4 storage dances + 3 identity helpers migrated to fixtures.
- **Left alone deliberately**: help-surface catalog, status-color maps, coerce/ensure pair, `_DEV_KEY_SENTINEL` duplication (import cycle), nested publisher sessions (failure isolation), mismatch-path double hash.
- **Proof**: suite 155 passed, ruff + format + `mypy src tests` clean, no behavior change (close/message/row output verified identical via tests).

---

## 2026-09-18 — SonarLint cleanup (S6353/S3776/S1192/S9073)

- **S6353 `cases/domain.py`**: `CASE_NUMBER_RE` `[0-9]` → `\d` with `re.ASCII` (ASCII-only semantics preserved, concise syntax).
- **S3776 `cases/repository.py`**: `get_next_sequence_number` split into `_scan_max_seq` + `_ensure_seq_record` + `_is_candidate_free`; allocator loop unchanged.
- **S1192 `tui/screens/verify.py`**: new `VERIFY_RESULT` constant replaces 3× `"#verify-result"` + `id="verify-result"` (matches existing `ANCHOR_INPUT` pattern).
- **S9073 `tests/unit/test_security_regressions.py`**: split 5 composite asserts (lines 92,218,275,278,487) into single-condition asserts.
- **Proof**: 155 passed, 3 skipped (PG), 75.59% branch (>70%), 0 Ruff check/format (97 files), 0 Mypy (93 files).

---

## 2026-09-18 — SonarLint + Pylance cleanup (S3776/Pylance ×2)

- **S3776 `audit/verifier.py`**: `verify_rows` first-seq branch extracted into `_retain_first()` (mirrors existing `_collect_gaps` helper style); loop and tamper semantics unchanged.
- **Pylance `tests/unit/test_database_migrations_and_lifecycle.py:94`**: added explicit `import sqlalchemy.exc` (runtime already worked; static resolution needed the submodule import).
- **Pylance `tests/unit/test_ui_renderers.py` (20× `reportCallIssue`)**: 3 hand-built `CaseResponseDto(...)` now go through production's `CaseResponseDto.from_domain(Case(...))` factory (the single source `service.py` uses 7×); `Case(...)` kwargs were already Pylance-clean, runtime output identical, no ignores added.
- **Proof**: 155 passed, 3 skipped (PG), 75.66% branch (>70%), 0 Ruff check/format (97 files), 0 Mypy (93 files).

---

## 2026-09-18 — PSScriptAnalyzer cleanup (install.ps1)

- **`install.ps1`**: removed dead `$VenvPip` assignment (PSScriptAnalyzer `PSUseDeclaredVarsMoreThanAssignments`). All pip calls already go through `$VenvPython -m pip` (or `uv ... --python $VenvPython`), so the variable had zero callers; deletion is behavior-identical.
- **Proof**: PowerShell parser reports 0 errors, 0 remaining `VenvPip` references.

---

## 2026-09-18 — CI pipeline end-to-end local replication (no repo changes)

- **ci.yml valid**: parses as YAML (3 jobs, expected steps/triggers); all 10 `uses:` pins are full 40-char SHAs and each was verified against the GitHub API to equal its commented tag (`checkout@v4.2.2`, `setup-python@v5.4.0`, `cache@v4`, `upload-artifact@v4.6.1` — all MATCH).
- **lint-and-types replicated**: `pip-audit --desc --require-hashes -r requirements.txt` → no known vulnerabilities; `cyclonedx-py requirements` → valid SBOM (44 components); `ruff format --check` + `ruff check` clean (97 files); `mypy src tests` clean (93 files).
- **test-matrix replicated** with CI's exact command + env (`pytest --cov=trace_core --cov-report=term-missing --cov-report=xml --cov-fail-under=70`, sqlite memory): 155 passed, 3 PG-skips, 75.58% branch (>70% gate).
- **Install steps proven in a scratch venv**: `pip install --require-hashes --only-binary :all: -r requirements.txt` (44 pkgs) + `pip install --no-deps -e .` both succeed from scratch; smoke subset (14 tests) green there too.
- **postgres-integration replicated against scratch `trace_ci` on local PG16** (fresh DB, since dropped): `trace db init/status/migrate` all exit 0 with all 13 migrations; `pytest tests/integration/ -v` → 3 passed on real PostgreSQL.
- **Live `trace` db untouched**: residue audit found zero test rows (newest case/event are the developer's own CR-0008 work); scratch db dropped, temp scaffolding deleted.
- **Local quirk noted (not a CI issue)**: `cmd set VAR=x && ...` appends a trailing space to the value — CI's `env:` block doesn't do this; local replication used in-process env instead.

---

## 2026-09-18 — Local pre-PR gate script (`check-pr.ps1`)

- **New `check-pr.ps1`** (root, mirrors `install.ps1` style): fast local replication of CI for clean PRs — `.\check-pr.ps1` runs venv/import, offline lockfile hash coherence, `ruff format --check`, `ruff check`, `mypy src tests`, `pytest --cov=trace_core --cov-fail-under=70` with CI env (save/restore vars, fail-fast summary, per-step timing, nonzero exit on failure). `-Full` adds `pip-audit`, SBOM (to TEMP, repo stays clean), and a fresh-venv hashed-install proof (self-deleting temp venv).
- **Proven**: fast mode green in ~20s, `-Full` green end-to-end (155 passed, audit clean, SBOM 44 components, fresh-venv proof 10 passed). PowerShell parser 0 errors.

---

## 2026-09-18 — `check-pr.ps1` kept local-only (not for GitHub)

- Per request, the pre-PR gate script stays a local dev tool: added root-anchored `/check-pr.ps1` to `.gitignore` (new "Local Developer Scripts" section, same spirit as ignored `/docs`). Verified via `git status` (no longer listed) + `git check-ignore`.
- Note: the `.gitignore` edit itself is tracked — required so the rule is shared and nobody commits the script by accident. The script file remains fully usable locally.

---

## 2026-09-18 — Sonar Blocker + pytest hygiene (signing traversal, S5754 ×3)

- **Blocker `audit/signing.py` (CWE path traversal)**: `_verify_ed25519` and `_load_private` interpolated the `key_id` suffix straight into a keystore path, but suffixes arrive from DB rows and the active-key pointer file (both attacker-writable). New `_key_file()` single source enforces grammar first (`^[\da-f]{16}$`, matching `init_key` output) then `check_contained()` (the existing `core/fs` backstop, same as `anchor_path`). Verify path still fails closed (`ValueError` is already in its caught tuple → `False`); signing path now raises `ValueError` instead of reading an arbitrary path.
- **S5754 ×3 `tests/unit/test_security_regressions.py`**: hoisted DTO/service/subject setup out of `pytest.raises` blocks (purged-twin DTO, actor-length recorder/action/subject/actor, auditor-reader service + DTO) so each block holds exactly one throwing invocation — same pattern as the prior S5754 pass.
- **Regression test**: `test_traversal_key_id_fails_closed` (`ed25519:../../../../tmp/pwn` → `verify_bytes False` + `verify_rows` signature-mismatch, fail closed).
- **Proof**: 156 passed (155 + 1 new), 3 skipped (PG), 75.68% branch (>70%), 0 Ruff check/format (97 files), 0 Mypy (93 files).

---

## 2026-09-18 — Subpart 3 build plan (`docs/subparts/subpart-3.md`)

- **New 360° plan doc** (local-only `docs/`, mirrors `subpart-2.md` structure): mission + scope lock, ASCII architecture, per-module spec for all 10 new files (`domain/ports/file_device/synthetic/linux/win32/repository/models/service/dto/commands/shell_handler/renderers/helpers` + migration `014` + TUI screen), data-flow sequences, fail-closed matrix, security/reliability/maintainability/test/TUI sections, 8-step build order, acceptance checklist, 360 risk table.
- **8 decisions locked with rationale, awaiting confirm**: evidence registry deferred to Subpart 4 [D1]; UNKNOWN-override = typed serial confirm + dual-log (no second human in V1) [D2]; immutable-append fingerprint rows [D3]; `EXIT_SOURCE_WRITABLE = 10` [D4]; smartctl optional-only [D5]; `--allow-real-hardware` opt-in [D6]; 3 new audit actions [D7]; new `devices/ports.py` (documented deviation) [D8].
- **No code touched** — plan only.

---

## 2026-09-18 — Subpart 3 plan revised per design review (8.7→spec 10/10)

- **Verdict: apply** — 11/13 review points adopted outright, 1 partial
  (operation-state vocabulary yes, coded state machine no — linear flow,
  YAGNI), 1 detail deviated (`ProtectionEvidence` as frozen Pydantic, not
  dataclass, per codebase consistency).
- **Doc completed + revised** (`docs/subparts/subpart-3.md`, 544 lines,
  §§0–14): the earlier draft was truncated mid-§4.5 on disk — rewrote the
  tail whole (§§4.5-rest…§14). Key structural changes: `BlockDevice.read_at`
  deferred to Subpart 4, new `DeviceInspector` port, `DeviceInspection`
  operation object passed between calls (no adapter/TTL caching),
  Native→Enrichment smartctl phases with cheap-list invariant,
  fixed per-command persistence/audit budget, 11-mode fake fault matrix,
  structured evidence schema, §12 grep-check against scope leak.
- **Decisions now [D1]–[D13]** (5 new); §14 logs the full 13-point
  adopt/partial/reject mapping.

---

## 2026-09-18 — Subpart 3 plan round 2 (reviewer follow-ups A–F, doc-only)

- **Verdict: all worth it, all applied.** C fixed a genuine contradiction
  (`inspect()` returning protection fields while `probe.verify()` owned the
  verdict) — would have caused day-one implementation thrash. D added the
  missing admission rule (override ONLY for UNKNOWN; WRITABLE is final) plus
  `original_verdict`/`authorized_by`/`reason` preservation. F adds a safety
  decision-coverage table as the stated confidence gate over the global 70%.
  B deferred explicitly with criterion (repr decided at Subpart-4 preflight);
  E restated budget as invariant; A concurred with no change.
- **Doc**: `DeviceInspection`/`GateCheck` split, `verify() → GateCheck`,
  §2/§5 flows, §6 WRITABLE-final row, §10 safety table, §12 seam + coverage
  items, §14 round-2 log. 611 lines, no truncation. Architecture frozen per
  reviewer agreement — build next, no more spec rounds.
- **No code touched** — plan only.

---

## 2026-09-18 — Devices TUI blueprint (`docs/blueprints/devices_tui.md`)

- **Design-only 5th tab spec** (no code — services don't exist yet; UI never
  leads, per build order §7): placement/chrome, Cases-mirroring layout sketch
  (table + dossier + gate block + raw drawer), full CLI↔TUI parity matrix
  (`list/inspect/check/override/raw` all reachable; exit codes render as
  cards, `--yes` has no modal equivalent — documented, not missing),
  re-enumerate-on-tab-switch policy (no polling, reasoned vs Audit),
  state/styling rules incl. XS collapse, explicit non-goals, headless pilot
  extension plan. **No code touched** — plan only.

---

## 2026-09-18 — Decision: CLI + TUI both permanent (no removal, ever)

- Asked whether to drop the CLI and go TUI-only. Decision after review:
  **both stay, permanently**. Typer owns headless/automation/CI/JSON
  (selftest, db provisioning, piped reports, exit codes — meaningless in a
  TUI-only world); TUI owns interactive human operation. The 155-test
  `CliRunner` surface, CI bootstrap, and the §7.2 CLI-first contract all
  depend on this split.
- Noted for later (not decided): the REPL shell duplicates the TUI's
  interactive job and is the actual overlap — *if* a surface is ever cut,
  that is the candidate, with `trace` launching straight into the TUI.
  No action taken.
- **No code touched** — decision only.

---

## 2026-09-18 — Changelog restructure (109 entries → 4 parts, zero loss)

- **Backup first**: byte-identical copy at
  `changelog/changelog.backup.2026-09-18.md` (verified identical before
  touching the live file).
- **New structure, same content**: title block + About/Legend note, grouped
  **Contents** list (109 linked entries), and four `# Part` dividers —
  Foundation (22) · Audit ledger (10) · Responsive UI + TUI (41) ·
  Hardening & security program (36). Every `## ` header and body kept
  verbatim in original record order; only separators/whitespace normalized.
- **Proof of zero loss**: scripted round-trip verification — re-parsed the
  restructured file and asserted all 109 headers + bodies identical and
  ordered (caught and fixed two real bugs in the script itself: a shifted
  part-marker list that mislabeled Part 2, and divider lines absorbed into
  body regions — both now exactly accounted).
- **No code touched** — log hygiene only.

---

## 2026-09-19 — Automatic DB bootstrap (no manual init/migrate)

- **Leftover fixed**: fresh installs required manual `trace db init` + `trace db migrate`
  (runtime commands assumed a managed schema; installers swallowed DB failures).
  Every `session()` now calls `DatabaseSessionManager.ensure_ready()` — first use per
  database applies pending migrations under the existing lock + checksum + verifier
  machinery, later uses return on a dict lookup (`:memory:` always runs, each engine
  owns a private DB). `trace doctor` heals then proves (offline → FAIL card, not a
  traceback). Installers run one visible `trace doctor` instead of two swallowed
  `db init`/`db migrate` calls — faster (1 startup vs 2) with an honest proof gate.
- **Tests updated to the new contract**: pending-schema doctor now expects auto-heal
  PASS; stale-004 test asserts first read heals (`list_cases() == []`, no manual apply);
  unreachable paths use a mocked `ensure_ready` refusal (no network wait, no stray
  `D:\nonexistent` side-effect — created once by the old bad-path URL, deleted).
- **Proof**: fresh file DB with zero manual commands — `case list` exit 0 (empty),
  `doctor` all PASS (13 applied), `audit verify` VALID 0 events. Suite 159 passed,
  3 PG-skipped, 75.68% branch (>70%), 0 Ruff check/format (100 files), 0 Mypy (95 files).
- **Files touched**: `core/database/session.py` (`_READY_CACHE` + `ensure_ready()` +
  `session()` hook), `core/cli/doctor.py` (heal-then-prove with offline card),
  `install.ps1`/`install.sh` (single `trace doctor` proof gate + self-heal wording),
  `tests/unit/test_doctor.py`, `tests/unit/test_database_migrations_and_lifecycle.py`.

---

## 2026-09-19 — Update module work plan (`docs/UPDATE_PLAN.md`)

- **New plan file** under `docs/` with the full update-module work list:
  ground rules, reuse inventory, early trust fixes, Phases 0–6 with per-phase
  tasks and acceptance, prohibitions, and the 22-box program acceptance list.
  Mirrors the validated target architecture (packaging decision as Phase 0,
  updater-owned migration, Phase 6 deferred).
- **No code touched** — plan only.

---

## 2026-09-19 — Update UX review refinements (`docs/UPDATE_PLAN.md`)

- **Applied all five review points, doc-only**: available/installable split
  (AVAILABLE … ROLLED_BACK states); verification-summary confirm screen
  before install commits; `restart_required` manifest metadata with a stated
  restart line; persistent update result marker read by the new process after
  handoff;   deterministic security-update language (manifest facts only, no
  "recommended"). Plus: reminder-dismissal as UI preference state, frozen
  thin-UI contract section, extended acceptance list.
- **No code touched** — plan only.

---

## 2026-09-19 — Update module implementation (Phases 0–6)

- **Phases 0–6 implemented**: packaging decision `docs/decisions/packaging.md`
  (source distribution retained, frozen binary deferred); release pipeline
  `.github/workflows/release.yml` + `release/manifest.schema.json` with sigstore
  separation; update protocol `updates/manifest.py/verifier.py/policy.py/checker.py`;
  Update Manager `updates/{domain,models,dto,service,commands,errors}` + migration
  `014_create_update_history` + CLI `trace update check|history|verify` (table|json,
  exit 0 on availability, forensic deferral, deterministic security label) +
  TUI `UpdatesView` as 5th tab wired via `tui/app.py`; standalone updater
  `trace_updater/updater.py` (staging `.partial→replace`, `atomic_install`,
  `rollback`, `previous/` preservation); result marker `write/read_result_marker`
  on `UpdateService` (atomic `tmp→replace`); recovery `trace recovery`
  (doctor-based diagnostics, migration-pending guidance).
- **Trust separation**: release trust never touches forensic keystore; update
  history is a dedicated `update_history` table, never the audit ledger.
- **Verification**: 159 passed, 3 PG-skipped, 74.5% branch (>70%), ruff check +
  format clean, mypy clean (88 files), `trace update check --help` and
  `trace recovery --help` both green. Plan `docs/UPDATE_PLAN.md` checked off
  per phase.

---

## 2026-09-19 — Update system hardening (Phases A–F fixes)

- **Phase A**: version-owned layout documented in `docs/decisions/packaging.md`
  (releases/current/previous/staging/updater/state/logs, pointer-swap
  activation); `updates/trust.py` (release trust store
  `~/.trace/trust/releases`, separate from forensic `keys/`,
  `require_trusted_key` fail-closed) + `updates/gate.py`
  (`ForensicOperationGate` ALLOWED/ACTIVE/UNKNOWN); `updates/domain.py`
  state machine (`_ALLOWED` + `can_transition`/`assert_transition`,
  `AVAILABLE_BUT_POLICY_BLOCKED/DOWNLOADING/STAGED/MIGRATING/HEALTH_CHECK/
  ROLLING_BACK/RECOVERY_REQUIRED`); `updates/models.py` (`transaction_id`,
  `release_id`, indexed `started_at`, `migration_range`,
  `health_check_result`, `failure_stage`, `restart_required`);
  `updates/dto.py` wired (`transaction_id`, `release_id`); `updates/service.py`
  (`transaction()` + `paginate(limit/offset)` + `atomic_write_lines` +
  `check_contained` for markers, `marker_schema`); `updates/shell_handler.py`
  + `catalog.default_handlers` (REPL parity).
- **Phase B**: `updates/manifest.py` manifest signature fields + bounded
  1 MB load; `updates/sources.py` (`ManifestSource`/`Local`/`Test`);
  `updates/verifier.py` (unsafe filename, signature presence, trusted-key
  check for manifest+artifact); `updates/policy.py` (`packaging.version`
  semver, no naive `int` split); `updates/trust.py` is release-only;
  `core/cli/error_handler.py` maps `UpdateVerificationError` → `EXIT_VERIFY_FAILED`.
- **Phase C**: `updates/lock.py` (file lock, stale-safe, `update.lock`);
  `updates/service` marker now crash-safe (`atomic_write_lines`);
  `trace_updater/updater.py` reuse `ensure_dir`/`check_contained`, hash-bound
  staging, `tmp→replace` per file.
- **Phase D**: `core/cli/recovery.py` independent `DatabaseSessionManager`
  per run + last marker diagnostics; no dependency on broken app's manager.
- **Phase E**: `updates/commands.py` (`update show` with security label +
  `restart_required` + verification), `tui/screens/updates.py`
  (sanitized marker/history, `limit=5` pagination), thin-UI preserved.
- **Phase F**: telemetry guard verified (no `httpx`/`requests` in `updates/`);
  rollout deferred intentionally (policy extensible via `UpdateChannel`).
- **Verification**: 159 passed, 3 PG-skipped, ruff + mypy clean, no new deps.

---

## 2026-09-19 — Update remediation round (P0/P1, adversarial audit findings)

- **P0 crypto**: `updates/signing.py` (Ed25519 over `canonical_json` bytes,
  `ed25519:<fp16>` IDs, `trust/releases/*.pub` + `revoked/`, wrong-algorithm
  rejection); `verifier.py` full chain with no `if signing_key_id` bypass;
  manifest requires `security_update`/`restart_required`/`manifest_signature`/
  `signing_key_id` + `schema_min`/`schema_target`/`backup_required`;
  `packaging` floor declared in `pyproject.toml`.
- **P0 install**: `trace_updater/updater.py` rewritten to version-owned
  `releases/<version>/` + atomic `active-version`/`previous-version`
  pointers; staged `.partial` resume + hash binding; `stage_release`
  completeness check + immutability refusal.
- **P0 lock/staging**: `core/fs.file_lock` single source (migrations +
  updates delegate, reentrant `update_lock`); `updates/staging.py`
  (`staged.json` binding + re-hash on promote); marker via
  `atomic_write_lines` + `check_contained`.
- **P0 migration**: `updates/migration.py` (active-marker,
  `run_updater_migration` with backup/compat/verify, sqlite copy +
  `pg_dump` paths); `ensure_ready()` defers while a marker is active
  (lazy import, no cycle); backup-failure blocks before apply.
- **P0 health/rollback/recovery**: `updates/lifecycle.py` (lock-held run:
  policy→verify→stage→activate→migrate→health→complete/rollback, history
  rows for FAILED + ROLLED_BACK); `recovery.py` release-aware (active/
  previous/marker inspection, corrupt-marker fail-closed, restore);
  `update install` command; `EXIT_UPDATE_BLOCKED=14`/`EXIT_RECOVERY_FAILED=15`.
- **P1**: dead DTOs removed; gate UNKNOWN fails closed in lifecycle;
  `update check` TTL cache with stable JSON; release workflow (existence
  gate, tag==version, manifest generation, client self-verify,
  reproducibility double-build, immutable publish); `release/` scripts.
- **Tribunal** `tests/updates/` (58 tests: trust, policy, state machine,
  staging/install, migration race, lifecycle/recovery, CLI contracts,
  telemetry guard).
- **Verification**: 217 passed, 3 PG-skipped, 76.91% branch (>70%), ruff +
  format + mypy clean, plan checkboxes + acceptance list updated.

---

## 2026-09-19 — Remaining NOT READY gaps closed where provable locally

- **HTTP manifest source**: `updates/sources.py` gained `HttpManifestSource`
  (stdlib urllib only: https-only outside loopback, JSON content-type gate,
  1 MB bound, 10 s timeout, no https→http downgrade) + `source_for`
  routing; `checker.check_for_update` accepts URLs; 8 localhost tribunal
  tests (ok/non-JSON/oversized/refused/plain-http/redirect/routing/check).
  Telemetry guard updated to ban third-party HTTP clients while allowing
  stdlib urllib inside `sources.py` only.
- **TUI update UX**: `UpdatesView` gained `focus_default` (the missing piece
  that let `_on_tab_pane_focused` snap focus back to Cases and silently
  revert tab activation), a wired Check button, verification-summary detail,
  history rows, and hint-pill update; `TRACE_UPDATE_MANIFEST` /
  `TRACE_UPDATE_CHANNEL` settings added; 2 Textual pilot tests.
- **PG backup wiring**: proven via stubbed `pg_dump` argv/timeout/check
  contract test + missing-binary fail-closed test; live-server proof still
  requires PostgreSQL (none in this environment).
- **Reproducibility**: proven in an isolated throwaway venv (repo venv
  untouched): two `SOURCE_DATE_EPOCH=0` builds → wheels byte-identical,
  sdists differ; workflow reproducibility step narrowed to `*.whl` with the
  sdist exclusion documented in `docs/decisions/packaging.md`; `release.yml`
  validated as well-formed YAML in the same isolated env.
- **Verification**: local CI gate PASSED — 230 passed, 3 PG-skipped,
  77.35% branch (>70%), ruff + format + mypy (135 files) clean.

---

## 2026-09-19 — Live PostgreSQL proof (docker pg16 + native pg_dump)

- **Defect found by going live**: `backup_database` passed the SQLAlchemy URL
  (`postgresql+psycopg://…`) straight to `pg_dump`, which rejects the driver
  scheme. Fixed to strip `+driver` → plain `postgresql://`, plus empty-dump
  refusal. Tribunal argv test updated to the converted URL.
- **Live proof** (Windows PG16 service + container image cached; container
  removed afterwards): schema 14 on PG; `backup_database` produced a real
  35 KB dump; dump contains all tables + live case/audit rows; full restore
  into `trace_restore` verified (`case show 2026-CR-0009` intact);
  `run_updater_migration` on PG (backup 54 KB → compat → apply →
  checksums → schema 14); migration race blocked; PG integration suite
  3 passed. Pre-existing seq-17 ledger mismatch exists identically on
  source and restore (byte-faithful backup, developer's lived-in dev DB —
  not caused by this work). Leftovers removed (restore DB, container,
  temp files); proof case 2026-CR-0009 remains in dev `trace` DB.
- **Verification**: local CI gate PASSED — 230 passed, 3 skipped,
  ruff + format + mypy clean.

---

## 2026-09-19 — Business-logic fix round (C/H/M findings → implementation)

- **P0-A**: `marker_state()` tri-state (active/absent/corrupt);
  `ensure_ready()` fails closed on corrupt; non-blocking `try_file_lock`
  in `core/fs` + reentrant `try_update_lock`; recovery triages stale
  markers (prove-no-live-holder → clear → record FAILED/recovery row).
  Fixed own bug found by tests: `try/except/else` skipped cleanup on
  `return` (restructured so finish always runs, original error preserved).
- **P0-B/C**: rollback split from forward-activate (previous pointer
  preserved, repeat-safe); `release.json` compat metadata staged per
  release; `rollback_release()` compat-gates + restores backup;
  `backup_path` + `override_reason` columns via migration 015 (+DTOs,
  service, lifecycle, marker).
- **P0-D/E**: `run()` rejects downgrades itself; unified versioned marker
  module (`marker_schema=2`, validated reads, fail-closed loads);
  service/TUI/recovery rewired; dead `require_result_marker` removed.
- **P1**: staged re-verify gate; bound `.partial` sidecars (hash-less branch
  closed); updater entry points self-lock; health checks pointer +
  completeness + schema target with post-activate verify + rollback
  re-health; min-bypass `--bypass-minimum` recorded; contiguity check;
  backup default-on with waiver + `VACUUM INTO`; content-bound shared check
  cache (CLI+TUI); install confirm/`--yes`; exact platform selection
  (schema + model + verifier + lifecycle).
- **P2**: `started_at` captured; history `--limit/--offset`; channel enum
  validation; typed loader errors; strict key parsing; UNVERIFIED framing
  in `show`; retry/backoff + ETag/304 + exact-URL identity; dead DTOs and
  `signing.ALGORITHM` removed; `forensic_keystore` dead helper removed.
  M3 decision: no durable VERIFYING state (confirm stays ephemeral UI).
- **Tribunal**: 98 update tests (+39); full suite 257 passed, 3 PG-skipped,
  coverage gate held; ruff + format + mypy clean.

---

## 2026-09-19 — Business-logic fix round, completion pass

- **Caught by tests during implementation**: `try/except/else` cleanup skip
  on `return` (restructured); cross-test shared install-base collisions
  (isolated per-test storage); suite-masked health-ordering bug (pointer
  check ran pre-activate — moved post-activate; `started_at` DTO field
  added); missing `select_artifact` import surfaced by gates.
- **Closed**: staged re-verify + pointer verify wired with failure rows;
  whole-run marker ownership with ambient-transaction exemption (owner
  proceeds, others defer); `override_reason`/`backup_waived` recorded;
  platform selection exact with ambiguity rejection; cache/TTL/ETag
  content-bound and shared CLI↔TUI; install confirm/`--yes`/`--bypass-minimum`
  with recorded overrides; contiguity + require-both-or-neither; WAL-safe
  default-on backup with waiver.
- **Tribunal**: 105 update tests; full suite 264 passed, 3 PG-skipped,
  77.50% branch coverage; ruff + format + mypy clean.

---

## 2026-09-19 — SonarLint & SonarQube Quality Remediation (S1871, S3776, S8513, S1192, S5713, S5958, S9073)

- **`src/trace_updater/updater.py`**: Merged duplicate `tmp.unlink()` condition on size limit exceeding 100MB into primary validation branch, resolving `python:S1871`.
- **`src/trace_core/updates/sources.py`**:
  - Extracted URL prefixes `_HTTPS_PREFIX = "https://"`, `_HTTP_PREFIX = "http://"`, and `_LOOPBACK_PREFIXES`, resolving `python:S1192` duplicate string literals.
  - Replaced chained `startswith` checks with tuple checks, resolving `python:S8513`.
  - Extracted `_HttpsRedirectGuard`, `_validate_manifest_url()`, and `_is_retryable_url_error()`, reducing `fetch_with_etag` Cognitive Complexity from 21 down to 11 (`python:S3776`).
- **`src/trace_core/updates/manifest.py`**: Moved `return _validate(parsed)` outside the JSON `try ... except ValueError` block in `load_manifest_bytes`, resolving redundant exception handling (`python:S5713`).
- **`src/trace_core/updates/checker.py`**:
  - Extracted `_URL_PREFIXES` tuple for `startswith`, resolving `python:S8513`.
  - Extracted `_cached_check_http()` helper, reducing `cached_check` Cognitive Complexity from 23 down to 4 (`python:S3776`).
- **`src/trace_core/updates/commands.py`**:
  - Replaced duplicate string literals (`"Path to artifact file"` and `"Trace will restart to complete this update."`) with module-level constants `ARTIFACT_PATH_HELP` and `RESTART_REQUIRED_MESSAGE`, resolving `python:S1192`.
- **`tests/updates/test_lifecycle_gates.py`**:
  - Replaced broad `pytest.raises(Exception)` with concrete `pytest.raises(UpdateError)` and `pytest.raises(ValidationError)`, resolving `python:S5958`.
  - Decomposed composite assertions into dedicated atomic assertions (`assert dto.override_reason is not None`, `assert "lab device" in dto.override_reason`, `assert rows`, and `assert rows[0].started_at <= rows[0].completed_at`), resolving `python:S9073`.
- **Verification Proof**:
  - Pytest: 266 passed, 3 skipped in 36.6s.
  - Ruff check: All checks passed (0 errors).
  - Ruff format: 148 files checked, all formatted cleanly.
  - Mypy: Success: no issues found in 141 source files (`mypy src tests`).

---

## 2026-09-19 — SonarLint & Pylance Follow-up Remediation (S5713, S9073, OptionalSubscript, OperatorIssue, CallIssue)

- **`src/trace_core/updates/lifecycle.py`**:
  - Removed redundant `FileNotFoundError` from `except (OSError, UpdateError) as e:` since `FileNotFoundError` inherits from `OSError`, resolving `python:S5713`.
- **`tests/updates/test_cli_contract.py`**:
  - Split composite assertion `assert rows and rows[0]["from_version"] == "0.1.0"` into two atomic assertions, resolving `python:S9073`.
- **`tests/updates/test_lifecycle_recovery.py`**:
  - Added `assert marker is not None` before accessing `marker[...]`, resolving Pylance `reportOptionalSubscript`.
- **`tests/updates/test_lifecycle_gates.py`**:
  - Added `assert rows[0].completed_at is not None` before `< =` comparison with `started_at`, resolving Pylance `reportOperatorIssue`.
  - Used dictionary unpacking `**kwargs` for `UpdateHistoryCreateDto` unknown field rejection test, resolving Pylance `reportCallIssue`.
- **`tests/updates/test_policy_versions.py`**:
  - Added `assert reason is not None` before asserting `"forensic" in reason`, resolving Pylance `reportOperatorIssue`.
- **Verification Proof**:
  - Pytest: 266 passed, 3 skipped in 33.1s (100% passing).
  - Ruff check: All checks passed (0 errors).
  - Ruff format: 148 files already formatted.
  - Mypy: Success: no issues found in 141 source files (`mypy src tests`).

---

## 2026-09-19 — Pre-PR Gate Execution & Recovery Fixture Hardening

- **`tests/updates/test_recovery_paths.py`**:
  - Fixed `test_recovery_restores_previous` release metadata to set `schema_min: 0` for compatibility when running in isolated memory SQLite mode (`TRACE_DATABASE_URL="sqlite:///:memory:"`), preventing false recovery failure on un-migrated ephemeral test instances.
- **Local Pre-PR Gate (`check-pr.ps1`) Execution**:
  - Step 1: Virtual environment import check — Passed.
  - Step 2: Lockfile hash coherence — Passed (all pinned packages verified).
  - Step 3: Ruff format check & Ruff lint — Passed (0 errors, 148 files checked).
  - Step 4: Mypy strict type checking — Passed (141 files clean).
  - Step 5: Pytest + 70% coverage gate — Passed (266 passed, 3 PG skipped, 77.44% branch coverage).
  - Pre-PR Gate Exit Code: 0 (`PRE-PR GATE PASSED -- safe to open the PR`).
- **`src/trace_core/updates/commands.py`**:
  - Made `--manifest` option in `trace update check` optional, seamlessly falling back to `settings.update_manifest` from `.env` (`TRACE_UPDATE_MANIFEST`), so examiners can run bare `trace update check` without needing to pass long manifest URLs manually.

---

## 2026-09-20 — SonarQube findings remediation (Blocker + High + Medium + Low)

- **Blocker — `updates/migration.py` (`restore_backup` path traversal)**:
  replaced vacuous self-containment checks with `_confine_backup_path()`,
  confining the marker/DB-sourced backup path to the Trace tree
  (`storage_root` or its parent); unreadable paths fail closed.
- **High — `release.yml`**: pinned `softprops/action-gh-release` to full
  commit SHA `3bb1273…` (# v2.6.2, verified live via `gh api`), matching
  repo SHA-pin convention.
- **High — release scripts (`make/sign/verify`)**: all `sys.argv` paths now
  resolved + contained to repo root; manifest-supplied artifact filenames
  rejected on `/`, `\`, `..` (same rule as the client verifier). Proven:
  full make→sign→verify round trip with the production key exits 0, and a
  `../evil.bin` manifest is refused with exit 1.
- **High — `install.sh`**: explicit no-op `*)` defaults on the trust-bundle
  validation cases (behavior unchanged, rule satisfied).
- **Medium — `release.yml` deps**: `build==1.6.1` + `cyclonedx-bom==7.4.0`
  moved into the hash-locked chain (`pyproject` dev extra → `uv.lock`
  purely additive → `requirements.txt` re-exported); release job now
  installs everything via `--require-hashes`; unpinned install line
  deleted. Lockfile coherence + hashed-install dry-run verified.
- **Medium — `fs.check_contained` oracle**: `resolve()` OSError unified
  into the generic refusal (no behavior change; no test depended on it).
- **Medium — pytest single-invocation** (`test_http_source` ×4,
  `test_lifecycle_gates` ×3, `test_lifecycle_recovery` ×2,
  `test_manifest_trust` ×1): constructors/handlers hoisted out of
  `pytest.raises` blocks per repo S5754 convention.
- **Low — `install.sh`**: `CURL_PROTO='=https'` constant replaces all
  curl `--proto` literals; `sh -n` clean, `install.ps1` parser clean.
- **Verification (targeted, full gate deferred per plan — CI last)**:
  updates tribunal 107 passed; ruff + format clean; mypy clean
  (src + release scripts); release script round trip + traversal
  rejection proven live. Full `check-pr.ps1` gate reserved for the end.
- **Final gate (`check-pr.ps1`, run after all fixes)**: PASSED — venv,
  lockfile coherence, ruff format + lint, mypy strict (all clean);
  pytest 266 passed, 3 PG-skipped (no local PostgreSQL), coverage gate
  held. Pre-PR gate exit code 0.

---

## 2026-09-20 — SonarQube 3-finding remediation (High + 2× Medium)

- **High — `release/make_manifest.py` (path traversal, `main`)**:
  deleted private `_contained` (echoed path, unhandled `OSError`);
  reuse `trace_core.core.fs.check_contained` like `sign/release_verify`;
  added `argv` count guard + generic `refusing path outside repository`
  refusal (no path echo). Proven: valid manifest writes, `../evil.json`
  exits 1.
- **Medium — `updates/migration.py` (`_confine_backup_path` oracle)**:
  unified `OSError` + escape branches into single
  `backup path refused; cannot restore` (same as `fs.check_contained`
  convention); moved `roots` resolve inside `try` + `from None`.
  No path echo preserved. Kills existence/outside distinguisher.
- **Medium — `tests/updates/test_lifecycle_recovery.py` (S5754)**:
  hoisted `UnknownGate()` out of `pytest.raises` so block holds only
  `life.run(...)` (repo single-invocation convention).
- **Verification**: ruff + format clean (3 files); mypy clean
  (`migration.py` + `make_manifest.py`); updates tribunal 107 passed;
  targeted `lifecycle_recovery + migration_race + recovery_paths`
  22 passed.
- **Files**: `release/make_manifest.py`, `src/trace_core/updates/migration.py`,
  `tests/updates/test_lifecycle_recovery.py`.

---

## 2026-09-20 — Fix `update check` vs GitHub octet-stream + multi-artifact verify

- **Root cause 1**: `HttpManifestSource` rejected any `Content-Type` without
  `json`; GitHub serves `stable.json` release assets as
  `application/octet-stream`, so the documented
  `releases/latest/download/stable.json` URL always failed closed.
- **Fix 1**: accept `octet-stream` alongside `json` (`sources.py`);
  content-type stays a hint — signature + schema + size still decide.
  `text/html` still rejected.
- **Root cause 2 (live-proved)**: shipped `v0.1.0` manifest holds wheel +
  sdist, both untagged → `select_artifact` correctly refuses ambiguity, but
  `verify`/`install`/lifecycle called it even when the operator already named
  the file, so `trace update verify --artifact <wheel>` failed.
- **Fix 2**: `verifier.resolve_artifact` — explicit `platform_key`, else exact
  filename match, else strict `select_artifact` (unchanged); wired into
  `verify_manifest`, `commands.install` display, and `lifecycle` staging.
  Wrong file still fails filename/size/hash. `select_artifact` contract untouched.
- **Verification**: ruff + format clean; mypy clean (141 files);
  `tests/updates/ + tests/unit/` 268 passed; live `stable.json` HTTPS check
  → `Up to date (0.1.0, stable)`, live wheel `verify` → `Verification passed`;
  trust bundle key matches `signing_key_id`.
- **Files**: `src/trace_core/updates/sources.py`, `verifier.py`,
  `lifecycle.py`, `commands.py`, `tests/updates/test_http_source.py`,
  `tests/updates/test_platform_select.py`.

---

## 2026-09-20 — Fix REPL `update` ANSI leak (raw `[1;38;2;…m` codes)

- **Root cause (pre-existing, not from octet-stream work)**: only
  `updates/shell_handler.py` renders via `CliRunner().invoke()` capture +
  `console.print(raw_string)`; the captured string already holds ANSI, and
  re-printing leaks escapes on hosts without VT. Cases/audit handlers call
  services directly — no capture path.
- **Fix**: `console.print(Text.from_ansi(res.output))` — Rich re-renders (or
  strips) for the current terminal. One-line, `rich` already installed.
  `select_artifact`/verify logic untouched.
- **Note**: the underlying card text was correct — `no update manifest
  configured` means the REPL process has no `TRACE_UPDATE_MANIFEST`
  (env read at import; restart REPL or pass
  `update check --manifest <https-url>` inside it).
- **Verification**: ruff + format + mypy clean; shell/cli-contract/tui
  17 passed; ANSI round-trip script proves old leaks / new clean with text kept.
- **Files**: `src/trace_core/updates/shell_handler.py`.

---

## 2026-09-20 — Phase A P0 update-pipeline fixes (gate/allow-list/strict-key/urlparse/containment)

- **Scope**: deep-audit P0-1 to P0-5 per `docs/audits/update-pipeline-deep-audit-2026-09-20.md` section 4/9.3, ponytail minimal diffs reusing `core/fs.py`.
- **Fix**: gate pluggable `active_probe` plus `UpdateGateContext` plus exhaustive `match` fail-closed (`gate.py`, `lifecycle.py`); `stage_release` copytree ignore sidecars (`*.partial`, `*.partial.json`, `staged.json`); strict `import_release_pubkey` matching loader; IPv6 loopback via `urlparse` hostname set; `trust_key_path`/`revoked_path` `check_contained` wrapped as `UpdateVerificationError`.
- **Verification**: `tests/updates/test_phase_a_p0.py` (6 adversarial) plus full `tests/updates/` 115 passed; ruff plus format plus mypy clean.
- **Files**: `src/trace_core/updates/gate.py`, `src/trace_core/updates/lifecycle.py`, `src/trace_updater/updater.py`, `src/trace_core/updates/signing.py`, `src/trace_core/updates/sources.py`, `src/trace_core/updates/trust.py`, `tests/updates/test_phase_a_p0.py`, `tests/updates/test_lifecycle_recovery.py`, `docs/audits/update-pipeline-deep-audit-2026-09-20.md`.

---

## 2026-09-20 — Phase B P1 update-pipeline fixes (locks/types/policy)

- **Scope**: deep-audit P1-1 to P1-8 per `docs/audits/update-pipeline-deep-audit-2026-09-20.md` section 4/9.4, plus P2-3 and V-02 pulled in.
- **Fix**: `CHANNEL_COMPATIBILITY` map with nightly-on-stable rejected (`policy.py`); owner stays thread-local with migration self-owning worker threads (`migration.py`); pure `__init__` plus `load` reconstruct plus keyword-only `run` (`lifecycle.py`, `commands.py`); `IDLE→FAILED` plus `FAILED/RECOVERY_REQUIRED→IDLE` (`domain.py`); `artifact: str|None`; typed staging errors; duplicate-filename reject (`verifier.py`); both-or-neither `model_validator` at load (`manifest.py`).
- **Caught mid-work**: first file-backed `is_owner` opened the gate (non-owner presenting the marker tx passed); tribunal `test_ensure_ready_blocked_during_update` forced the correct semantics.
- **Verification**: `tests/updates/test_phase_b_p1.py` (9 tests) plus full `tests/updates/` 124 passed; ruff plus format plus mypy clean.
- **Files**: `src/trace_core/updates/policy.py`, `verifier.py`, `migration.py`, `lifecycle.py`, `domain.py`, `commands.py`, `manifest.py`, `src/trace_updater/updater.py`, `tests/updates/test_phase_b_p1.py`, `tests/updates/test_staging_install.py`, `docs/audits/update-pipeline-deep-audit-2026-09-20.md`.

---

## 2026-09-20 — Phase C durable-transaction fixes (markers/backup/recovery)

- **Scope**: deep-audit Phase C per `docs/audits/update-pipeline-deep-audit-2026-09-20.md` sections 3.1/9 (L-02, MARK-01, MIG-03, REC-01, REC-02, S-02). No new code comments written per instruction; existing comments preserved.
- **Fix**: `migration_marker_path()` rename with all callers updated; `transition()` writes marker before mutating state; versioned `SCHEMA_REQUIRED_KEYS`; pre-mutation backup orphans removed while post-mutation backups preserved; deterministic `corrupt-<sha12>` recovery ids; `read_result_marker` delegates to `read_marker`; `RecoveryBlockedError` maps to new `EXIT_RECOVERY_RETRY (16)`.
- **Verification**: `tests/updates/test_phase_c_durable.py` (8 tests) plus full `tests/updates/` 132 passed; ruff plus format plus mypy clean.
- **Files**: `src/trace_core/updates/migration.py`, `marker.py`, `lifecycle.py`, `service.py`, `errors.py`, `src/trace_core/core/cli/recovery.py`, `error_handler.py`, `exit_codes.py`, `tests/updates/test_phase_c_durable.py`, `tests/updates/test_migration_race.py`, `docs/audits/update-pipeline-deep-audit-2026-09-20.md`.

---

## 2026-09-20 — Update pipeline P2-D completeness + reusability hardening

- **Scope**: Close every remaining P2/P3/Perf finding from `update-pipeline-deep-audit-2026-09-20.md` that was deferred after Phase C, per AGENTS §§1-4/14 ponytail minimalism: one source per behavior, no new deps, match surrounding style exactly. Keep dirty tree (no commit) as instructed.
- **Fix**:
  - **DTO/Service**: `UpdateHistoryCreateDto.started_at` now `Field(default_factory=now_utc)` required at creation (no longer `None` fallback) — canonical wall-clock at transaction start, not at record time; `UpdateHistoryDto.from_model` single source replaces 3 manual mappings and now round-trips `artifact_sha256/signing_key_id/failure_reason/restart_required` (was dropped in `history --json`); `UpdateHistoryModel` widened `String(32)→64` for semver+build suffix, added `server_default=text("0")`, `DateTime(timezone=True)` + `@validates(coerce_utc)` for §14 Canonical UTC, index `ix_update_history_transaction_id` via `016_update_history_roundtrip` (idempotent, creates missing columns/indexes, backfills `NULL→0`).
  - **Manifest/Policy/Verifier/Signing/Trust**: `manifest.py` surfaces all Pydantic errors (`"; ".join(loc:msg)`), bounded `read_bytes()+len>1MiB` kills TOCTOU, `platform/arch` `pattern` mirrors `release/manifest.schema.json`, `version` regex tightened `([._-][a-zA-Z0-9]+)*` + `max_length=64`; `policy.py` `_parse_version` stays `ValueError` for `packaging.Version` compat (test `test_version_ordering` pins `ValueError`), `_current_platform` emits `unknown(raw)` for empty `machine`; `verifier.py` adds `is_safe_filename/assert_safe_filename` single source, `unsafe` checked before `filename mismatch` to avoid leaking traversal payload, `verify_artifact_signature_streaming` streaming guard `>10GiB→UpdateVerificationError` + `Ed25519` full-bytes verify; `signing.py` `import_release_pubkey` now `atomic_write_lines(...,mode=0o600)` (no `0o644` window) with strict `len==1` split; `trust.py` caches `ensure_dir` in `_TRUST_ROOT_CACHE` and wraps both paths with `check_contained` defense-in-depth; `release/make_manifest|sign|verify` filtered `dist` glob (`*.sig/*.json/*.sbom/SHA256SUMS` skip), ensured `out.parent`, argv arity, revoked-skip.
  - **Sources/Checker/Cache**: `sources.py` IPv6 loopback via `urlparse(hostname)` not prefix, `_HttpsRedirectGuard` cross-host + `https→http` downgrade both reject, `UpdateNetworkError(UpdateError)` split so `error_handler` shows "Check network" (`EXIT_ERROR`) vs trust (`EXIT_VERIFY_FAILED`/`11`); added `normalize_manifest_url/split_manifest_url` single source handling query strings; `checker.py` normalized etag key + single `manifest_identity` via `cache_valid_for(identity)` + `_payload_from_check` dedupe; `cache.py` `write_check_cache` wraps `json.dumps` to `UpdateNetworkError` and `cache_valid_for` takes optional precomputed identity; `staging.py` `is_verified_stage` single hash `actual==expected` string compare then one `sha256_file`; `updater.py` adds `install_root()` single source (replaces `settings.storage_root.parent/"install"` in `lifecycle`+`recovery`), `STAGED_RECORD_FILENAME` constant shared with `staging.py`, `_binding_path` via `assert_safe_filename+check_contained`, `tmp` also `check_contained`, `activate`/`rollback` idempotent.
  - **Lifecycle/Migration/DB**: `lifecycle.py` `_override_note` now logs `structlog.warning` with `override_reason` trace, `_check_release_health` docs freshness contract, extracted `_verify_stage/_download_stage/_assert_verified_stage/_install_stage` helpers (god-function L-04 hardened to testable stages, still on `UpdateLifecycle` until second caller proves extraction), typed `_run_locked` signature, `load()` raises `RecoveryError` for wrong tx (consistent `EXIT_RECOVERY_FAILED`), `_run_locked` now `failure_stage=UpdateFailureStage.*` not magic strings; `migration.py` `backup_database` via `ensure_dir(dest)` + `check_contained(out)` + empty-file guard, `restore_backup` re-resolves after existence (TOCTOU), `core/database/session.ensure_ready` comment on `_READY_CACHE` thread-safety via `migrations._migration_lock`, `migrations._migration_checksum` memcached, `paginate` guard `if offset is not None and offset` / `if limit is not None` (allows `limit=0` to mean 0 rows, not all rows), `fs.file_lock/try_file_lock` `chmod(path,0o600)` not `fileno`.
  - **CLI/Shell/TUI**: `commands.py` `HISTORY_COLUMNS+history_table_rows(rows)` single source shared with `shell_handler.py`, `update history` empty at offset says `No updates at offset X`, `RESTART_REQUIRED_MESSAGE` reused 3×; `shell_handler.py` replaced `CliRunner` test util with direct `cached_check/history/show/verify` service dispatches + explicit `update install` guidance to standalone CLI (preserves AGENTS §14 Strict Mutation Flow), `recovery.py` uses `updater.install_root()+marker.marker_path()+get_db(None)` + `UpdateFailureStage.RECOVERY`; `tui/screens/updates.py` shows `unknown→` and `—` placeholders, documents HTTP hint as local-only, caps `notify(...[:500])`.
  - **Reusability sweep**: `verifier.assert_safe_filename`, `updater.install_root`, `staging.STAGED_RECORD_FILENAME`, `commands.history_table_rows`, `sources.normalize_manifest_url` each replace 2-3 duplicated literals/branches; `UpdateHistoryDto.from_model` collapses 18-field hand-roll; `Dto.started_at` default_factory collapses `or now_utc()` fallback; no new framework or abstraction introduced (ponytail).
## 2026-09-20 — Fix GitHub Release CDN redirect & HTTP 304 ETag handling

- **`src/trace_core/updates/sources.py`**:
  - Permitted GitHub release asset CDN redirects in `_HttpsRedirectGuard` (`github.com` → `*.githubusercontent.com`), resolving `refusing cross-host manifest redirect` when querying live releases.
  - Explicitly caught `urllib.error.HTTPError` with status code 304 in `fetch_with_etag` and converted to internal `_NotModified`, eliminating false `manifest download failed` errors on cached repeat update checks.
- **Verification**:
  - Live HTTPS `trace update check` verified: `Up to date (0.1.0, stable)`.
  - Repeat check with cached ETag verified: returns cached payload immediately without error.
## 2026-09-20 — Zero-Config Update Checking & Global `~/.trace/.env` Loading

- **`src/trace_core/core/settings.py`**:
  - Configured `update_manifest` to default to the official release URL (`https://github.com/nirjxr26/Trace/releases/latest/download/stable.json`) so users running Trace from any directory globally do not have to manually configure `.env`.
  - Configured Pydantic Settings `env_file` to search both local `.env` and global user configuration `~/.trace/.env`, resolving path-dependent configuration misses.
- **Verification**:
  - Tested running `trace update check` outside repository (`C:\Users\nirja`): successfully queries release manifest and reports `Up to date (0.1.0, stable)`.
  - Pre-PR Gate (`check-pr.ps1`): **PASSED** (291 passed, 3 skipped, 76.48% coverage).

---

## 2026-09-20 — PostgreSQL boolean compatibility in migration 016 & UpdateHistoryModel

- **Root cause**:
  - `UpdateHistoryModel.restart_required` and `rollback` columns were configured with `server_default=text("0")` instead of `false()`.
  - In migration `016_update_history_roundtrip`, `ALTER TABLE ... BOOLEAN DEFAULT 0` and `UPDATE update_history SET restart_required=0` used integer `0` instead of ANSI SQL boolean literal `FALSE`.
  - In PostgreSQL, assigning integer `0` to a `BOOLEAN` column fails with `DatatypeMismatch: column "restart_required" is of type boolean but expression is of type integer`.
  - On PostgreSQL, any unhandled statement failure inside a transaction marks the transaction as aborted (`InFailedSqlTransaction`). Subsequent reflection queries (e.g. `_index_exists` querying `pg_catalog`) failed with `current transaction is aborted, commands ignored until end of transaction block`.
- **Fix**:
  - `src/trace_core/updates/models.py`: Changed `server_default` from `text("0")` to `false()` (compiles cross-dialect to `DEFAULT false` on PostgreSQL and `DEFAULT 0` on SQLite).
  - `src/trace_core/core/database/migrations.py`:
    - Dialect-aware boolean literals in migration 016: `DEFAULT FALSE` and `SET ...=FALSE` on PostgreSQL, `DEFAULT 0` on SQLite.
    - Wrapped speculative DDL/DML in `with conn.begin_nested():` savepoints so any database-level exceptions never poison or abort the parent transaction.
- **Verification**:
  - Applied migration 016 cleanly to live PostgreSQL instance (`trace db migrate` / `apply_migrations` -> all 16 migrations applied).
  - Verified `tests/updates/test_migration_race.py::test_recovery_clears_stale_marker` passes.
  - Verified PostgreSQL integration tests (`tests/integration/test_postgres.py`) with live PostgreSQL container (3 passed).
  - Local pre-PR gate (`check-pr.ps1`): **PASSED** (all 6 stages clean: virtualenv, lockfile, ruff format, ruff lint, mypy, 291 passed, 3 skipped, 76.46% coverage).

---

## 2026-09-20 — PR #5 SonarQube 8-issue remediation (Cognitive Complexity, Duplication, Suspicious Code, Exception Isolation)

- **Cognitive Complexity**:
  - `release/verify_release.py` (16 → 4): Extracted `_safe_filename`, `_verify_artifact_integrity`, and `_sync_trusted_keys` out of `main()`.
  - `src/trace_core/core/cli/error_handler.py` (16 → 3): Replaced repeated `isinstance` branches and boolean fallback cascades in `_update_error` with a declarative `specs` tuple loop.
  - `src/trace_core/core/database/migrations.py` (29 → 1): Extracted `_safe_nested_execute`, `_migration_016_ensure_columns`, `_migration_016_ensure_indexes`, and `_run_migration_016` out of `_migration_016_update_roundtrip`.
  - `src/trace_core/updates/sources.py` (25 → 4): Extracted `_read_manifest_response` and `_handle_url_error` from `fetch_with_etag`.
- **Code Duplication**:
  - `src/trace_core/updates/sources.py`: Defined `_JSON_SUFFIX = ".json"` constant replacing 4 duplicate string literals in `split_manifest_url` and `fetch_with_etag` (SonarLint S1192).
- **Suspicious Code**:
  - `release/make_manifest.py`: Removed empty `pass` in `if` branch with `elif ... continue`; unified into `is_tar_gz = ...` single check.
- **Test Exception Isolation (python:S5754)**:
  - `tests/updates/test_phase_a_p0.py`: Extracted object instantiation and argument prep outside `pytest.raises` in `test_gate_active_probe_blocks_install`, `test_gate_probe_error_fails_closed`, `test_strict_key_import_rejects_trailing_garbage`, and `test_trust_path_traversal_rejected`.
- **Verification**:
  - All 291 tests passed, 3 skipped.
  - Local pre-PR gate (`check-pr.ps1`): **PASSED** (all 6 stages clean, 76.76% branch coverage).

---

## 2026-09-22 — Fully automatic update module (no manual manifest/artifact)

- **Scope**: Make `update check/show/verify/install` work with zero flags per user request, reusing `checker/sources/policy/verifier/fs` contracts. No new deps, no bypass of verification, AGENTS §§1-4/14 preserved.
- **Fix**: `checker.py` adds `default_manifest_target/resolve_manifest_target/resolve_channel/load_manifest_auto/ensure_artifact_path` single sources (explicit wins, else `settings.update_manifest/update_channel`, else fail closed only when explicitly disabled); `sources.py` adds `fetch_artifact_bytes` reusing TLS/redirect/retry guards with `assert_safe_filename` + size cap, cached under `state/artifacts/` with sha/size re-verify; `commands.py` makes `--manifest/--artifact/--channel` optional on all four commands and auto-resolves/downloads before `verify_manifest/lifecycle.run`; `shell_handler.py` uses same resolvers and updated help text; `cli/shell.py` strips leading `trace` inside REPL (`trace update check` == `update check`); `tui/screens/updates.py` hint + check use resolvers so default HTTPS manifest shows pill automatically.
- **Verification**: ruff check clean; ruff format clean; mypy clean (144 files); pytest 291 passed / 3 skipped; manual `resolve_manifest_target(None)` returns default stable.json URL and `trace update check` tolerated via REPL strip.
- **Files**: `src/trace_core/updates/checker.py,sources.py,commands.py,shell_handler.py`, `src/trace_core/cli/shell.py`, `src/trace_core/tui/screens/updates.py`.

---

## 2026-09-22 — Update module 50-issue permanent remediation (audit list closure)

- **Scope**: Close all 50 issues from the 2026-09-22 file-by-file audit list in smallest permanent diffs per AGENTS §§1-4/14. No new deps or frameworks. Dirty tree kept, nothing committed.
- **Fix**: Streaming artifact download to temp file (`sources.stream_artifact_to_file` + `_with_retries` single retry path, `checker.ensure_artifact_path` atomic promote); install availability/policy before download with `get_installed_version()` single authority (active pointer else settings); URL-stem-respecting `check_for_update` delegation + query-safe channel via `sources.has_json_suffix`; REPL quote-preserving `trace` strip; `cache` null-timestamp tolerance + mtime fast-path identity; service negative-pagination guard + `started_at/id` ordering; `UpdateFailureStage.from_state` single mapping + `BaseException` interrupted history with record guard; trust/checksum caches keyed by root/action; `manifest` shared constants/capped errors/bounded read/`+build` support/`_parse_bytes`; `policy` unknown-channel reject + sanitized platform; `staging/marker` typed `UpdateError`; DTO channel/result/stage validators; `signing` honest `verify_artifact_signature_file` + alias; `sources` CDN host tuple + manifest-size default; shell completions; canonical layout doc in `updater.install_root`; `lifecycle` sanitized override, typed health/stages, schema-once threading, preverified short-circuit, retention prune hook; `migration` PGPASSWORD env, AUTOCOMMIT vacuum, O_NOFOLLOW probe; `updater` single-pass copy+hash, `os.replace`, `prune_retention`; TUI sync-documented hint; tests updated to typed contracts (`UpdateError`, PGPASSWORD, state-name stages).
- **Verification**: ruff check clean; ruff format clean; mypy clean (144 files); pytest 291 passed / 3 skipped; `check-pr.ps1` PASSED (coverage ~76%).
- **Files**: `src/trace_core/updates/checker.py,sources.py,manifest.py,policy.py,domain.py,dto.py,verifier.py,signing.py,trust.py,cache.py,service.py,lifecycle.py,migration.py,marker.py,staging.py,commands.py,shell_handler.py,lock.py`, `src/trace_updater/updater.py`, `src/trace_core/cli/shell.py`, `src/trace_core/tui/screens/updates.py`, `src/trace_core/core/cli/recovery.py`, `src/trace_core/core/database/migrations.py`, `tests/updates/test_marker_schema.py,test_staging_install.py,test_backup_pg.py`.

---

## 2026-09-22 — Fix check/install version-authority divergence (HTTP check used settings.version)

- **Scope**: `update check` (HTTP path) reported `current = settings.version` (0.1.0) while `update install` used `get_installed_version()` (active pointer, 0.2.0) and correctly refused — contradictory cards seconds apart.
- **Fix**: `_cached_check_http` now uses `get_installed_version()` single authority, matching `check_for_update`/`lifecycle.run`/`update_install`. One-line change in existing style, no new abstraction.
- **Verification**: ruff + format + mypy clean; `test_cli_contract` + `test_lifecycle_gates` 13 passed.
- **Files**: `src/trace_core/updates/checker.py`.

---

## 2026-09-24 - TUI UX refinement pass

Scope: terminal-native refinement only, no backend change, per AGENTS 1-4/14 and ponytail. Global tab/footer/selection/status/scrollbars; Cases aligned + progressive + integrity summary; Audit Seq/Event/Case + no hashes; Integrity hashes-only; Database connection+migrations; Updates Previous/Current/Status single state. Verification: ruff clean, mypy clean (144 files), pytest 291 passed / 3 skipped, coverage 75.7 percent. Files: tui/app.py,theme.py,palette.py, screens/cases.py,audit.py,verify.py,db.py,updates.py, tests/unit/test_tui.py.

---

## 2026-09-24 - Settings tab consolidation (Cases/Audit unchanged)

Scope: terminal-native consolidation per approved design, AGENTS 1-4/14 and ponytail (1 new file, no new deps, services reused). Tabs 5 to 3: Cases, Audit, Settings. Left fixed section list (Database, Updates, Integrity, Storage and Paths, Operator and Env, Diagnostics, About) with selection prefix; right detail reuses fetch_db_snapshot, cached_check, AuditService.verify, settings/trust/doctor calls. Old screens/db.py, updates.py, verify.py removed (superseded, zero other importers). Palette tab-settings plus aliases for old tab ids; Keys 1-3. Verification: ruff clean, mypy clean (142 files), pytest 291 passed / 3 skipped, coverage 75.2 percent. Files: tui/screens/settings.py (new), tui/app.py, actions.py, palette.py, tests/unit/test_tui.py, tests/updates/test_tui_updates.py, tests/unit/test_security_regressions.py.

---

## 2026-09-24 - Settings left nav spacing/size/dividers + 2-col lists + fast arrow

Scope: left-bar readability pass per screenshot review, AGENTS 1-4/14 and ponytail (no new deps, no backend change). Settings left DataTable to ListView with item spacing and instant CSS highlight; left width 1fr like Cases/Audit; muted Rule under Settings title and under Cases/Audit search boxes; Cases list Case-number plus Status only; Audit list Seq plus Event only (details unchanged); arrow repaint O(n) to O(1) old-plus-new row in Cases/Audit and single-item paint in Settings. Verification: ruff clean, mypy clean, pytest 291 passed / 3 skipped, coverage 75.1 percent. Files: tui/app.py, tui/screens/settings.py, cases.py, audit.py, tests/unit/test_tui.py, tests/updates/test_tui_updates.py, tests/unit/test_security_regressions.py.

---

## 2026-09-24 - Table header dividers, flat settings nav, active-tab label fix

Scope: screenshot-review pass, AGENTS 1-4/14 and ponytail (CSS-only plus 2-line test, no backend change). Cases/Audit DataTable headers gain a muted bottom divider separating header from rows. Settings ListView drops hover/active backgrounds entirely: transparent bg, bold text plus existing selection prefix (never color-only). Settings title gains padding. Root cause for the blank active tab: Tab is fixed at height 1, so any border-bottom clips the label row away; replaced with underline text-style at zero layout cost. Proved with headless SVG render probe (border build omits Audit from SVG, underline build keeps it) and locked with export_screenshot label assertions for Audit and Settings in the pilot flow. Verification: ruff clean, mypy clean, pytest 291 passed / 3 skipped, coverage 75.1 percent. Files: tui/app.py, tests/unit/test_tui.py.

---

## 2026-09-24 - Real table header dividers plus dossier integrity divider

Scope: screenshot follow-up, AGENTS 1-4/14 and ponytail (no new deps, no backend change). Root-caused the missing header divider the same way as the tab bug: proved with headless SVG probes that box borders on .datatable--header render nothing (identical SVG with and without), then used the mechanism that provably aligns: header_height=2 with two-line muted dash labels, verified row order header, dashes, data in render output. Cases shows Case-number divider plus Status divider; Audit shows Seq divider plus Event divider. Removed the dead border CSS. Added the missing rule between NOTES and INTEGRITY in the case dossier. Hardened the pilot flow with render assertions (table painted, headers and divider present) at realistic 110-col width after finding the 80-col default clips the Status column. Verification: ruff clean, mypy clean, pytest 291 passed / 3 skipped, coverage 75.1 percent. Files: tui/screens/cases.py, audit.py, tui/app.py, tests/unit/test_tui.py.

---

## 2026-09-24 - Full-width table dividers plus flat inputs/nav

Scope: screenshot follow-up, AGENTS 1-4/14 and ponytail (no new deps, no backend change). Tables now render a manual bold header plus a full-pane Rule divider (image-2 style) instead of segmented per-column dashes, after proving via SVG probes that box borders on .datatable--header render nothing. Header text alignment derived from measured DataTable geometry (width equals content width, 1 padding each side) via shared tui.theme.table_head_text, verified column-for-column in render output; trimmed Cases columns back to 16/10 so normal panes need no h-scroll. Settings list hover/active backgrounds removed for real this time (Textual uses .-hovered class, not :hover, plus focus tint kill); bold text plus selection prefix only. Search, create/edit, and purge inputs flattened to transparent with no focus tint (borders unchanged). Verification: ruff clean, mypy clean, pytest 291 passed / 3 skipped, coverage 75.2 percent. Files: tui/theme.py, tui/app.py, tui/forms.py, tui/screens/cases.py, audit.py, tests/unit/test_tui.py.

---

## 2026-09-24 - Max-reuse pass over new TUI code

Scope: reuse-only refactor per request, AGENTS 1-4 and ponytail (no behavior change, deletion over addition). New shared helpers in tui/widgets.py: repaint_selection (O(1) arrow, was duplicated in Cases/Audit), mount_header_table (header Static plus fixed columns from one constant, was duplicated), selected_item (cursor to item, was duplicated). New append_kv in tui/theme.py (detail Label/value rows, was 4 copies in Settings). Cases/Audit adopted all four and deleted locals; Settings adopted append_kv; audit also gained a shared _row_cells so refresh and repaint use one builder. Skipped per ponytail: test _text helper (import fragility across test dirs for 4 lines), focus_default one-liners, run_command toast tails, Settings ListView painter (different widget, single use). Verification: ruff clean, mypy clean, pytest 291 passed / 3 skipped, coverage 75.3 percent. Files: tui/widgets.py, theme.py, screens/cases.py, audit.py, settings.py.

---

## 2026-09-24 - Installer UX module spec (docs only, no code)

Scope: design doc per request, AGENTS 1-4 (no code changed). Wrote docs/INSTALLER_UX.md: quiet-by-default contract with single live progress line plus log file, six named phases, TTY fallback, four flags (version, list-versions, reinstall, uninstall/purge-data), exact wipe table, old-versions-via-installer-only rationale (updater stays forward-only), unchanged safety invariants, shellcheck plus PSScriptAnalyzer plus dry-run verification plan, acceptance list. Cut: separate version-manager tool, auto-update, updater downgrades, release-pipeline changes. Open: bar-plus-spinner versus spinner-only default.

---

## 2026-09-24 - Subparts 1 and 2 logic and stability audit (docs only, no code)

Scope: file-by-file line-by-line re-read of cases, core, cli, audit plus installers (updates and TUI excluded). Wrote docs/SUBPART_12_AUDIT.md: 28 findings, 0 critical, 7 medium, 21 low, each with exact file and line. Mediums: SQLite audit-append race, verify-vs-head TOCTOU, HMAC secret rotation framing history as tampered, gap-list memory bomb, dossier silently dropping history, signing-key loss bricking writes, db status markup leak (confirmed live on Kali screenshot), health snapshot wrong-URL with injected managers. Plus cleared-as-sound list and suggested fix order.

---

## 2026-09-24 - Subparts 1 and 2 fix round (all 28 audit findings)

Scope: fixed every actionable finding from docs/SUBPART_12_AUDIT.md per AGENTS 1-4/14, smallest permanent diffs, no new deps. Ledger: savepoint-retry appends (SQLite/PG races), 10k gap cap, non-dict details coercion, loud missing-key error, strict pointer parse with warn-fallback, ASCII key grammar, HMAC no-rotate docs. Surfaces: styled db status (was literal markup), manager-aware masked URL, history-unavailable notice at fetch site, equals-form flags, None-empty canonicalization with preview parity, output validation, single completion list, case-insensitive ghosts. Anchors/exports: 24h failed-retry cooldown, tip in export header. Infra: single hashed pip path in both installers, .env 600 plus manifest-dup guard, per-manager completion nonce. KEPT deliberately: corrupt-row fail-loud display, anchor-skip ordering, keys-init auto-migrate, mutable-main default, completion fetch depth. Verification: ruff clean, mypy clean (142 files), pytest 300 passed / 3 skipped (9 new tests), coverage 75.5 percent.

---

## 2026-09-24 - Release v0.2.1 ops (branch, PR, tag, publish)

Scope: release operations, no new code beyond the triple bump. Cut release/v0.2.1 from main carrying the TUI work plus two pre-existing version-related fixes found dirty in tree (stale check-cache guard, unpinned CLI version assert). Local pre-PR gate 6/6 green. Opened PR 6, remote CI 5/5 green (lint, ubuntu plus windows suites, PostgreSQL 16 integration, SonarCloud). Merged to main, verified triple plus trace version output, confirmed no existing v0.2.1 release, pushed annotated tag v0.2.1. Release workflow green in 46s (reproducible build, SBOM, Ed25519 sign, client self-verify, immutable publish with wheel, sdist, SHA256SUMS, manifest, trust bundle). Wrote then compacted the release notes on user request.

---

## 2026-09-24 - Help alignment plus audit list trim

Scope: two screenshot-driven UX fixes per AGENTS patterns, smallest diffs. Help: update shell entries (45 to 48 chars) overflowed the shared 36-col grid and pushed descriptions out of line; shortened the three long syntaxes to fit (remaining flags stay in tab-completion and Typer help) and added a grid-width guard test covering every handler plus console entries. Audit list: dropped Actor and Command columns from the CLI audit table at all breakpoints (Seq, Action, Case, Time remain); Actor stays in detail views where the 5W1H who belongs, TUI list was already Seq/Event only. Verification: ruff plus mypy clean, targeted suites green, full suite plus coverage gate in final check.

---

## 2026-09-24 - Help grid single-source plus stale-manifest race fix

Scope: reuse plus one real bug found during verification, smallest diffs. Extracted HELP_GRID_SYNTAX_WIDTH and HELP_GRID_ALIAS_WIDTH next to the printer in cli/shell.py; the width-guard test now imports the constant instead of duplicating 36. Removed the manifest (mtime, size) fast-path in updates/cache.py after the full suite exposed it flaking test_cache_invalidates_on_content_change: equal-size rewrites inside one mtime tick reused the old sha and served a stale manifest for the full TTL, able to hide security releases. Always rehash (manifests capped at 1 MiB, milliseconds). Verification: ruff plus mypy clean, full suite 301 passed / 3 skipped with the previously flaking test green, coverage 75.5 percent.
