# ForensiX — System Design & Backend Architecture

> Companion documents:
> - `ForensiX — Production Architecture & Brutal Gap Analysis.md` (why these decisions exist)
> - `ForensiX — Production Readiness & Engineering Playbook.md` (how we get from here to production)
>
> This document is the **technical ground truth**: package layout, ports, data flows, schemas,
> algorithms, and runtime topologies. Any AI coding agent or engineer working on ForensiX should
> treat this as the source of truth and raise an ADR before deviating.

---

## Table of Contents

1. [Guiding Principles](#1-guiding-principles)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Runtime Topologies (CLI → Server Evolution)](#3-runtime-topologies)
4. [Repository Layout](#4-repository-layout)
5. [Domain Layer](#5-domain-layer)
6. [Ports Catalog](#6-ports-catalog)
7. [Application Service Layer](#7-application-service-layer)
8. [Acquisition Engine Deep Dive](#8-acquisition-engine-deep-dive)
9. [Job Subsystem (Async Model)](#9-job-subsystem)
10. [Data Architecture & Persistence](#10-data-architecture--persistence)
11. [Tamper-Evident Audit Log Specification](#11-tamper-evident-audit-log-specification)
12. [API Surface (FastAPI)](#12-api-surface-fastapi)
13. [CLI Surface (Typer)](#13-cli-surface-typer)
14. [On-Disk Storage Layout](#14-on-disk-storage-layout)
15. [Security Architecture](#15-security-architecture)
16. [Failure Handling → Component Map](#16-failure-handling--component-map)
17. [Observability](#17-observability)
18. [Cross-Platform Notes (Windows/Linux)](#18-cross-platform-notes)
19. [Testing Architecture](#19-testing-architecture)
20. [Technology Stack & Rejected Alternatives](#20-technology-stack)
21. [Evolution Path: Web/GUI Deployment](#21-evolution-path-webgui-deployment)
22. [ADR Seeds (Open Decisions)](#22-adr-seeds)

---

## 1. Guiding Principles

Non-negotiable. Every design decision below traces back to one of these:

| # | Principle | Consequence in code |
|---|-----------|---------------------|
| P1 | **Evidence integrity above all** | Hashes computed at multiple granularities; verification is a mandatory pass, never optional |
| P2 | **Fail closed** | Safety gates throw typed exceptions; nothing proceeds "hopefully" |
| P3 | **Everything is evidence** | Tool version, config snapshot, host clock status captured into the record |
| P4 | **Reproducibility** | Same input image + same command + same version ⇒ byte-identical findings & report body |
| P5 | **No implicit trust in the OS** | Write-protection and device identity verified independently, not assumed from flags |
| P6 | **Hexagonal boundary is law** | Domain imports nothing; Application imports only Domain+Ports; Adapters implement Ports; CLI/API import only Application |
| P7 | **Crash-only design** | Every long operation assumes it may die mid-way; recovery is a designed-in state, not an afterthought |
| P8 | **Air-gap friendly** | Zero network calls at runtime unless explicitly configured; no telemetry; offline installable |

---

## 2. High-Level Architecture

Classic ports-and-adapters, with the dependency rule enforced mechanically (import-linter contract in CI):

```
┌─────────────────────────────────────────────────────────────────────┐
│                            ADAPTERS (in)                            │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────────┐  │
│  │  CLI (Typer) │  │ REST (FastAPI│  │ Selftest / Validation     │  │
│  │  pure parser │  │ thin router) │  │ harness (CI entry point)  │  │
│  └──────┬───────┘  └──────┬───────┘  └────────────┬──────────────┘  │
└─────────┼─────────────────┼───────────────────────┼─────────────────┘
          │                 │                       │
          ▼                 ▼                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    APPLICATION SERVICE LAYER                        │
│  CaseService · AcquisitionService · AnalysisService · ReportService │
│  JobService · CustodyService · RetentionService · AdminService      │
│  ─────────────────────────────────────────────────────────────────  │
│  • Orchestrates use cases      • Enforces RBAC                      │
│  • Owns transaction boundaries • Emits audit events                 │
│  • Returns DTOs only (Pydantic) — never ORM objects, never strings  │
└──────────────────────────────┬──────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           DOMAIN LAYER                              │
│  Entities: Case · EvidenceItem · ForensicImage · Acquisition · Job  │
│            Examiner · Role · CustodyTransfer · ValidationRun        │
│            RetentionPolicy · DisposalRecord · Attestation           │
│  Value objects: Hash · HashAlgorithm · DeviceFingerprint · Offset   │
│  Pure state machines + invariants. ZERO imports beyond stdlib/pyd.  │
└──────────────────────────────┬──────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          PORTS (interfaces)                         │
│  BlockDevice · WriteBlockerProbe · ImageWriter · HashPipeline       │
│  CaseRepository · AuditAppender · Clock · JobQueue · KeyStore       │
│  FilesystemChecker · ProgressSink                                   │
└─────────────────────────────────────────────────────────────────────┘
                               ▲ implemented by
┌─────────────────────────────────────────────────────────────────────┐
│                         ADAPTERS (out)                              │
│  db/(SQLAlchemy+Alembic) · devices/(win32, linux) · imaging/(raw,   │
│  ewf) · hashing/(multihash, piecewise) · audit/(sqlite-appendonly)  │
│  reports/(jinja2→pdf/a) · clock/(ntpchecked) · keystorage/(dpapi,   │
│  secret-service) · external_tools/(ewfacquire, tsk subprocess)      │
└─────────────────────────────────────────────────────────────────────┘
```

**Enforcement:** `import-linter` contracts in CI fail any commit where `domain` imports infra,
or `cli` imports `sqlalchemy` directly. The boundary is not aspirational; it is gated.

---

## 3. Runtime Topologies

ForensiX ships as one Python package with three deployment shapes. The core does not change;
only which adapters get wired changes.

### Topology A — Workstation (Phase 1 default)

```
forensix CLI ──▶ in-process Application Services ──▶ SQLite (case DB) + local disk
                     └─▶ in-process asyncio JobRunner (single worker thread pool)
```
- Single examiner machine. Everything local. No network.
- Jobs run in a dedicated worker thread inside the CLI process, but **state lives in the DB**,
  so a crashed run is recoverable by the next invocation.

### Topology B — Lab workstation with local daemon (Phase 2–3)

```
forensix CLI ──HTTP(localhost)──▶ forensix-daemon (uvicorn + FastAPI)
                                     ├─▶ JobRunner process(es), DB-backed queue
                                     └─▶ SQLite/WAL or PostgreSQL
```
- Long acquisitions survive CLI exit/close. GUI-ready: any HTTP client can drive it.
- Daemon runs as a systemd service / Windows service. CLI becomes stateless client.

### Topology C — Multi-user lab server (Phase 4+, optional)

```
N × CLI / Web UI ──▶ FastAPI server ──▶ PostgreSQL ──▶ NFS/SAN evidence store
                          └─▶ Worker fleet (Postgres SKIP LOCKED queue)
```
- Only reached when a lab needs shared case DB. Requires the RBAC + custody model (already built).
- Evidence images stay on lab-controlled storage; server never egresses data.

> Design rule: **Application Services must never assume which topology they're in.**
> They receive injected ports; wiring happens once, in composition roots
> (`cli/bootstrap.py`, `api/bootstrap.py`).

---

## 4. Repository Layout

```
forensix/
├── pyproject.toml              # uv/pip build; deps pinned via uv.lock / requirements*.txt
├── importlinter.toml           # architectural boundary contracts
├── .github/workflows/          # ci.yml, release.yml, nightly-validation.yml
├── docs/
│   ├── adr/                    # Architecture Decision Records (0001-style numbering)
│   ├── sop-templates/          # lab-facing procedure templates
│   └── api/                    # generated OpenAPI snapshots
├── src/forensix/
│   ├── domain/
│   │   ├── models/             # entities & value objects (pure)
│   │   ├── state_machines/     # Case/Image/Job transition tables
│   │   ├── rules/              # invariants, retention math, custody rules
│   │   └── events.py           # AuditEvent definitions (typed payloads)
│   ├── application/
│   │   ├── dto.py              # ALL Pydantic response/request models live here
│   │   ├── cases.py            # CaseService
│   │   ├── acquisition.py      # AcquisitionService
│   │   ├── analysis.py         # AnalysisService (TSK-backed)
│   │   ├── recovery.py         # CarvingService
│   │   ├── reports.py          # ReportService
│   │   ├── jobs.py             # JobService (enqueue/status/cancel)
│   │   ├── custody.py          # CustodyService
│   │   ├── retention.py        # RetentionService
│   │   └── security.py         # authn/authz helpers, RBAC checks
│   ├── ports/
│   │   ├── devices.py          # BlockDevice, DeviceEnumerator, WriteBlockerProbe
│   │   ├── imaging.py          # ImageWriter, ImageVerifier
│   │   ├── hashing.py          # HashPipeline
│   │   ├── repositories.py     # repository protocols
│   │   ├── audit.py            # AuditAppender, AuditReader
│   │   ├── jobs.py             # JobQueue
│   │   ├── system.py           # Clock, HostInfo, FsChecker
│   │   └── crypto.py           # KeyStore, Signer
│   ├── adapters/
│   │   ├── db/                 # SQLAlchemy models, repositories, alembic/
│   │   ├── devices/win32/      # CreateFile/IOCTL implementation
│   │   ├── devices/linux/      # POSIX ioctl/udev implementation
│   │   ├── imaging/raw.py      # chunked copier (our engine)
│   │   ├── imaging/ewf.py      # E01 via pyewf or ewfacquire subprocess
│   │   ├── hashing/            # multihash + piecewise implementations
│   │   ├── audit/sqlite_appendonly.py
│   │   ├── reports/            # jinja templates → WeasyPrint PDF/A
│   │   ├── tsk/                # pytsk3 wrapper + subprocess fallback
│   │   └── exttools/           # ewfacquire/dc3dd optional cross-validation adapters
│   ├── jobs/
│   │   ├── runner.py           # worker loop, heartbeats, claim/release
│   │   └── handlers.py         # maps job type → application call
│   ├── api/
│   │   ├── bootstrap.py        # composition root for HTTP topology
│   │   ├── routers/            # thin FastAPI routers (no logic)
│   │   └── sse.py              # job progress streams
│   ├── cli/
│   │   ├── bootstrap.py        # composition root for CLI topology
│   │   ├── main.py             # Typer app assembly
│   │   ├── commands/           # one module per noun (case, image, job, …)
│   │   ├── renderers/          # table/json/yaml output formatting ONLY
│   │   └── exit_codes.py       # stable numeric exit-code contract
│   ├── observability/          # structlog config, trace-id middleware, metrics
│   ├── settings.py             # layered TOML + env config (pydantic-settings)
│   └── selftest/               # reference-data self-test harness
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── chaos/                  # fault-injection scenarios
│   ├── validation/             # golden datasets (NIST CFReDS manifests, expected hashes)
│   └── factories/              # synthetic disk-image builders
└── tools/
    ├── gen_synthetic_disk.py   # deterministic test-image factory
    └── bench/                  # throughput benchmark scripts
```

---

## 5. Domain Layer

### 5.1 Entity catalog

Full entity list with key fields (SQLAlchemy mirrors these; domain classes are plain Pydantic/dataclasses):

| Entity | Key fields | Invariants (enforced in domain, not DB) |
|---|---|---|
| `Case` | id, number, title, status, opened_at, lead_examiner | Number immutable; cannot close while child evidence is `ACTIVE`; status transitions via machine |
| `Examiner` | id, name, cert_id, public_key, roles[] | Soft-delete only (never remove — history references it) |
| `Role` | name ∈ {EXAMINER, REVIEWER, LAB_ADMIN, AUDITOR} | Permissions are static table, not free-form |
| `EvidenceItem` | id, case_id, type, collected_at, collected_by, custody_chain | Custody chain is ordered & contiguous |
| `DeviceFingerprint` | serial, model, capacity_bytes, firmware, interface, wwn | Immutable once attached to an Acquisition |
| `Acquisition` | id, evidence_item_id, source_fingerprint, method, started_at, finished_at, wp_verification, ntp_status, checkpoint_ref | Cannot complete without wp_verification=PASS and finished hash manifest |
| `ForensicImage` | id, acquisition_id, format(RAW/E01), paths[], compression, segments, hashes{md5,sha1,sha256}, piecewise[], state | State ∈ {PENDING→ACQUIRING→ACQUIRED→VERIFYING→VERIFIED \| FAILED \| QUARANTINED}; VERIFIED required for analysis |
| `PiecewiseHash` | image_id, index, offset, length, sha256 | length == chunk_size except last |
| `CustodyTransfer` | id, evidence_item_id, from_examiner, to_examiner, transferred_at, reason, signature | from/to ≠ null; signed by releasing party |
| `Job` | id, type, payload, state, progress_pct, heartbeat_at, claimed_by, result_ref, error | Heartbeat stale > threshold ⇒ CRASHED |
| `AuditEvent` | seq, ts, actor, action, subject, payload_hash, prev_hash, signature | prev_hash chains; seq strictly increasing |
| `ValidationRun` | id, build_fingerprint, dataset_id, expected_manifest, actual_manifest, verdict, ran_at | Verdict PASS required for release sign-off |
| `RetentionPolicy` | case_type → duration, basis (legal cite) | Disposal blocked until expiry AND dual approval |
| `DisposalRecord` | evidence ids wiped, method, witnessed_by[], certificate hash | Irreversible; requires prior RetentionService clearance |
| `Attestation` | report_id, examiner_id, statement, signed_at, signature | One attestation per report revision |
| `Report` | id, case_id, params_snapshot, tool_version, format(PDF/A), schema_version, file_ref | Regeneration produces identical body bytes given same inputs |

### 5.2 Core state machines

```
Case:      OPEN → UNDER_REVIEW → CLOSED → ARCHIVED → (DISPOSED via retention)
                └────────────── REOPENED ←──────────────┘ (audited, reviewer role)

ForensicImage:
  PENDING ─acquire ok─▶ ACQUIRING ─▶ ACQUIRED ─verify pass─▶ VERIFYING ─▶ VERIFIED
                            │ fail          │ verify fail        │
                            ▼               ▼                    ▼
                         FAILED        QUARANTINED ◀── (reviewer may return to VERIFYING)
  Transitions are total functions in domain/state_machines/image.py:
      allowed(state, event) -> Result[State, TransitionError]
  Illegal transitions raise; services translate to typed API errors. No stringly states.

Job:       QUEUED → RUNNING → SUCCEEDED | FAILED | CANCELLED
                 └─(stale heartbeat)─▶ CRASHED ─examiner confirm─▶ QUEUED(resume)
```

---

## 6. Ports Catalog

Python `Protocol` classes (structural typing — adapters need not inherit anything):

```python
# ports/devices.py
class DeviceEnumerator(Protocol):
    def list_block_devices(self) -> list[DeviceInfo]: ...

class BlockDevice(Protocol):
    fingerprint: DeviceFingerprint          # captured lazily, cached
    size_bytes: int
    def read_at(self, offset: int, length: int) -> memoryview: ...
    def close(self) -> None: ...

class WriteBlockerProbe(Protocol):
    """Independent verification — NOT trust of caller flags."""
    def verify(self, device: DeviceInfo) -> WpVerification:
        """Returns PASS(reason=evidence)/FAIL(reason)/UNKNOWN. Service fails closed on UNKNOWN."""

# ports/imaging.py
class ImageWriter(Protocol):
    def open(self, dest: ImageSpec) -> None: ...
    def write_chunk(self, data: memoryview) -> int: ...     # returns bytes written
    def mark_bad_region(self, offset: int, length: int) -> None: ...
    def finalize(self) -> WrittenManifest: ...
    def abort(self) -> None: ...

class ImageVerifier(Protocol):
    def verify(self, image_paths: list[Path], expected: HashManifest) -> VerificationReport: ...

# ports/hashing.py
class HashPipeline(Protocol):
    """Computes N algorithms + piecewise over a byte stream in ONE pass."""
    def process(self, chunk: memoryview) -> None: ...
    def manifest(self) -> HashManifest: ...                  # {algo: digest} + piecewise list

# ports/audit.py
class AuditAppender(Protocol):           # MUST be append-only; adapter rejects UPDATE/DELETE
    def append(self, event: NewAuditEvent) -> ChainedAuditEvent: ...

# ports/system.py
class Clock(Protocol):                   # injectable; wraps time + NTP status probe
    def now_utc(self) -> datetime: ...
    def sync_status(self) -> ClockSyncStatus: ...

# ports/jobs.py
class JobQueue(Protocol):
    def enqueue(self, job: NewJob) -> JobId: ...
    def claim_next(self, worker_id: str) -> Job | None: ...  # atomic
    def heartbeat(self, job_id: JobId) -> None: ...
    def complete(self, job_id: JobId, result: JobResult) -> None: ...

# ports/crypto.py
class Signer(Protocol):                  # examiner/lab signing keys
    def sign(self, data: bytes) -> Signature: ...
    def verify(self, data: bytes, sig: Signature) -> bool: ...
```

**Why Protocols:** cheap to fake in tests (`FakeBlockDevice` backed by a BytesIO over a synthetic
image), trivially adaptable to Linux/Windows, and keeps the Application layer import-free of infra.

---

## 7. Application Service Layer

### 7.1 Rules

1. **DTOs only.** Every method takes/returns Pydantic models from `application/dto.py`.
2. **RBAC here, nowhere else.** First line of every mutating method: `require(actor, Permission.X, resource)`.
3. **Transaction boundary here.** A service method = one logical transaction (unit-of-work injected).
4. **Audit emission here.** Domain emits nothing; services record *who did what* via `AuditAppender`.
5. **No I/O primitives.** Services never touch `open()`, sockets, or SQL — only ports.

### 7.2 Use-case ↔ surface map (v1 scope)

| Use case | CLI command | API route (Topology B+) | Job? |
|---|---|---|---|
| Create/open case | `case create/list/show/close` | `POST/GET /cases` | no |
| Register evidence item | `evidence register` | `POST /cases/{id}/evidence` | no |
| Enumerate block devices | `devices list` | `GET /devices` | no |
| Fingerprint device | `devices inspect DEV` | `GET /devices/{id}/fingerprint` | no |
| Acquire image | `image acquire SRC CASE` | `POST /jobs {type:"acquire"}` | ✅ |
| Resume acquisition | `image resume JOB_ID` | `POST /jobs/{id}/resume` | ✅ |
| Verify image | `image verify IMG` | `POST /jobs {type:"verify"}` | ✅ |
| Analyze FS / timeline | `analyze fs IMG`, `analyze timeline IMG` | `POST /jobs {type:"analysis"}` | ✅ |
| Carve / recover deleted | `recover files IMG --filter` | `POST /jobs {type:"carve"}` | ✅ |
| Custody transfer | `custody transfer EV → EXAMINER` | `POST /evidence/{id}/transfer` | no |
| Generate report | `report generate CASE` | `POST /jobs {type:"report"}` | ✅ |
| Apply disposal | `retention dispose CASE` | `POST /cases/{id}/dispose` | gated |
| Audit trail export/verify | `audit export/verify` | `GET /audit`, `POST /audit/verify` | no |
| Self-test against references | `selftest run [--dataset]` | `POST /jobs {type:"selftest"}` | ✅ |

---

## 8. Acquisition Engine Deep Dive

This is the highest-risk component. Specified precisely because courts will ask.

### 8.1 Pipeline stages

```
[1] DISCOVER      enumerate devices (adapter), present candidates
[2] FINGERPRINT   capture DeviceFingerprint (serial/model/size/firmware/WWN);
                  persist BEFORE any read of evidentiary data
[3] SAFETY GATE   WriteBlockerProbe.verify():
                    Linux: O_RDONLY|O_EXCL open + BLKROGET ioctl + mount ro-scan
                    Windows: CreateFile(FILE_SHARE_READ) + IOCTL_DISK_IS_WRITABLE
                  Result must be PASS with recorded evidence (ioctl outputs).
                  FAIL or UNKNOWN ⇒ ABORT (fail closed). Examiner override of UNKNOWN
                  requires second-examiner role + is audited as OVERRIDE event.
[4] PREFLIGHT     dest free space ≥ est. size ×1.05; dest writable; dest not the source;
                  clock NTP-sync status captured; tool version + config snapshot hashed
[5] ACQUIRE LOOP  see §8.2 — chunked copy with inline piecewise hashing + checkpoints
[6] FINALIZE      flush+fsync all segment files; write manifest.json (hashes, params,
                  timeline, bad-sector map); E01: writer metadata records
[7] VERIFY PASS   read-back from DESTINATION computing whole-image md5/sha1/sha256 +
                  recomputing piecewise hashes; compare to [5] results
                  (validates BOTH the copy AND destination media health)
[8] REGISTER      ForensicImage.state = VERIFIED; audit event IMAGE_VERIFIED with manifest hash
```

### 8.2 The acquire loop

```python
CHUNK = settings.acquisition.chunk_size        # default 4 MiB
while offset < source.size_bytes:
    try:
        data = device.read_at(offset, CHUNK)   # retry ≤3 w/ exp backoff on transient IO err
    except UnrecoverableIOError as e:
        bad_regions.append(offset)             # per E01 convention: zero-fill + record
        data = zero_chunk
        audit.append(BadSectorEncountered(offset=offset, errno=e.errno))
    hasher.process(data)                       # updates md5+sha1+sha256+piecewise states
    written = writer.write_chunk(data)         # E01 writer compresses internally if enabled
    if offset // CHECKPOINT_EVERY_BYTES != (offset+len(data)) // CHECKPOINT_EVERY_BYTES:
        checkpoint.save(Checkpoint(job_id, next_offset=offset+CHUNK,
                                   piecewise_index=hasher.piecewise_count))
    progress.publish(written_total=offset+len(data))   # → Job.progress_pct + SSE
    offset += len(data)
```

- **Checkpoint cadence:** every `CHECKPOINT_EVERY_BYTES` (default 64 GiB) *and* on any pause signal.
  Checkpoint = tiny JSON sidecar next to job row: `{next_offset, piecewise_index, params_hash}`.
- **Resume algorithm:** reload params, re-fingerprint source, compare to stored fingerprint
  (mismatch ⇒ refuse), seek source to `next_offset`, seek destination to matching segment/offset,
  continue. Whole-image hashes are **not** resumed — they are finalized during the [7] VERIFY
  read-back pass, which is why verification is mandatory and not skippable.
- **Why two-pass:** (a) hashlib state isn't serializable, so resumable inline whole-hashing is a lie;
  (b) read-back verification independently proves destination integrity — a court-relevant fact;
  (c) cost is one extra sequential read, negligible vs. total acquisition time.

### 8.3 Bad-sector policy (matches failure matrix)

Zero-fill + record offset range + continue. Never abort for a bad sector; never hide it — the
bad-region map lands in the manifest and the report. Reviewer sees `IMAGE_HAS_BAD_REGIONS` flag.

### 8.4 Formats

| Format | Engine | Notes |
|---|---|---|
| RAW (+ `.raw.hash` manifest) | Our chunked engine | Default; simplest to verify byte-for-byte |
| E01 (EWF) | `pyewf` binding; `ewfacquire` subprocess fallback adapter | Segmented `.E01/.E02…`; compression level from config; our piecewise hashing still applies on the plaintext stream |
| AFF4 | Out of scope v1 (ADR seed) | Interface allows adding later without touching services |

Cross-validation adapter (optional, off by default): pipe through `dc3dd`/`ewfacquire` and compare
digests — logged as `CROSS_VALIDATION` audit event. Useful for Daubert-style error-rate evidence.

---

## 9. Job Subsystem

### 9.1 Design

- **DB-backed queue**, not Redis. Columns: `state, priority, claimed_by, claimed_at,
  heartbeat_at, attempts, payload(json), result_ref`. Claim = atomic `UPDATE … WHERE state='QUEUED'
  LIMIT 1 RETURNING` (SQLite: immediate transaction; Postgres: `FOR UPDATE SKIP LOCKED`).
- **Worker**: single process, thread-pool executor sized by config (device I/O is the bottleneck;
  parallel acquisitions of different devices allowed, same device never).
- **Heartbeat** every 5 s while running. Stale (>30 s) ⇒ marked CRASHED by janitor sweep on next
  daemon boot or CLI `job janitor` invocation. Crash recovery always requires explicit examiner
  confirmation before resume (failure-matrix requirement).
- **Progress**: `Job.progress_pct` updated in DB (throttled ≥1 s apart); SSE stream `/jobs/{id}/events`
  fans out in-process; CLI renders Rich progress bar by polling the same row — identical contract.
- **Cancellation**: cooperative. Cancel sets flag in DB; loops check between chunks; partial image
  goes to QUARANTINED, never silently discarded.

### 9.2 Idempotency

Mutating non-job operations carry optional `Idempotency-Key` (API header / `--idempotency-key`).
Service stores key→result hash for 24 h; replays return original outcome. Mandatory for
`custody transfer` and `retention dispose`.

---

## 10. Data Architecture & Persistence

### 10.1 Engines

| Phase | Engine | Rationale |
|---|---|---|
| 1–2 | SQLite, WAL mode, `fullfsync` on critical writes | Zero-infra, air-gapped friendly, adequate for single workstation |
| 3+ option | PostgreSQL 15+ | Multi-examiner concurrency, row-level locking, managed backups |

Repository protocols make the swap a wiring change. Both adapters ship from Phase 3.

### 10.2 Schema highlights

- All timestamps: `TIMESTAMP WITH TIME ZONE`, UTC. Never naive datetimes anywhere (lint rule).
- Money-like precision irrelevant; offsets: `BIGINT` bytes.
- **Append-only enforcement** for `audit_events`: dedicated SQLite connection/user without UPDATE
  grant; trigger raising exception on UPDATE/DELETE (defense in depth even for local DB).
- Alembic from day one. Migration policy (see Playbook §8): forward-only, reviewed, destructive
  changes require explicit backup step + sign-off.

### 10.3 ERD (core, abbreviated)

```
CASE 1─* EVIDENCE_ITEM 1─* ACQUISITION 1─1 FORENSIC_IMAGE 1─* PIECEWISE_HASH
EVIDENCE_ITEM 1─* CUSTODY_TRANSFER *─1 EXAMINER (from/to)
EXAMINER *─* ROLE
CASE 1─* REPORT 1─1 ATTESTATION
JOB (standalone; payload references subject ids; result_ref → manifest/report path)
AUDIT_EVENT (append-only, chained)
VALIDATION_RUN, RETENTION_POLICY, DISPOSAL_RECORD
```

---

## 11. Tamper-Evident Audit Log Specification

### 11.1 Event canonicalization

Every event serialized as canonical JSON: sorted keys, UTF-8, no whitespace,
timestamps ISO-8601 Zulu, integers not floats.

### 11.2 Chain

```
genesis.prev_hash = 32×0x00
event_n.payload_hash = SHA256(canonical_json(event_n minus chain fields))
event_n.prev_hash    = event_{n-1}.payload_hash ⊕-chained as:
event_n.chain_hash   = SHA256(event_{n-1}.chain_hash || event_n.payload_hash || event_n.seq)
```

### 11.3 Anchoring & signing

- Every event additionally carries optional `signature` (Ed25519) by acting examiner for
  CRITICAL class actions: `IMAGE_VERIFIED`, `CUSTODY_TRANSFERRED`, `DISPOSAL_EXECUTED`,
  `REPORT_GENERATED`, `WP_OVERRIDE`.
- `forensix audit anchor` writes `anchor.json`: `{last_seq, last_chain_hash, tool_version, ts}`
  signed with the **lab key**. Labs anchor daily/on case close. Anchor files can live outside
  ForensiX entirely (email, print, separate vault) — breaking the single point of compromise.
- `forensix audit verify [--from-anchor]` recomputes the entire chain and reports the first
  divergent seq if tampered. Runs in <seconds for 10⁶ events.

### 11.4 Export

`forensix audit export --format jsonl|csv` produces a portable, verifiable bundle
(events + anchor + chain spec version) suitable for submission alongside case evidence.

---

## 12. API Surface (FastAPI)

Thin routers: parse → authorize (delegates to service) → call service → serialize DTO.
OpenAPI generated and **snapshotted into repo**; CI contract-tests CLI behavior against it.

```
POST /auth/token                 local passphrase → scoped token (Topology B/C)
GET  /cases  POST /cases  GET /cases/{id}  POST /cases/{id}/close
GET  /cases/{id}/evidence  POST /cases/{id}/evidence
GET  /devices  GET /devices/{id}/fingerprint
POST /jobs                       {type, payload} → JobDto (202)
GET  /jobs/{id}                  JobStatusDto {state, progress_pct, message, error}
GET  /jobs/{id}/events           text/event-stream (progress ticks)
POST /jobs/{id}/cancel  POST /jobs/{id}/resume
GET  /images/{id}  GET /images/{id}/manifest
POST /evidence/{id}/custody-transfer
POST /reports  GET /reports/{id}
GET  /audit?case_id=&from_seq=  POST /audit/verify  POST /audit/anchor
POST /selftest
```

Auth: Topology B uses a local token file with OS-keystore-protected secret; Topology C adds
per-examiner accounts + role claims. TLS termination documented for C; B is localhost-only.

---

## 13. CLI Surface (Typer)

Command grammar mirrors the API 1:1 (same service calls, same DTOs):

```
forensix case create|list|show|close
forensix evidence register|show|transfer
forensix devices list|inspect
forensix image acquire SOURCE --case ID --format raw|e01 [--chunk] [--compress L]
forensix image verify IMAGE
forensix image status JOB_ID
forensix analyze fs|timeline IMAGE
forensix recover files IMAGE [--deleted] [--types jpg,pdf] [--out DIR]
forensix report generate CASE --template standard --attest
forensix custody transfer EVIDENCE --to EXAMINER
forensix retention apply|due|dispose
forensix audit show|export|verify|anchor
forensix selftest run|report
forensix config show|set|path
forensix daemon start|status|stop        (Topology B)
```

**CLI rules (enforced in review):**

1. Zero business logic. Parse args → call service → render DTO.
2. `--output json|yaml|table` on every listing command (json is the stable contract; tables are UX).
3. Stable exit codes (`cli/exit_codes.py`):

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | generic error |
| 2 | usage/argument error |
| 10 | safety gate failed (write-block unverified) |
| 11 | hash mismatch / verification failed |
| 12 | device not found / fingerprint mismatch |
| 13 | insufficient resources (disk space) |
| 14 | permission denied |
| 20 | job failed (see `job status`) |
| 30 | authorization denied |

Scripts and SOPs key off these codes — they are part of the public contract (SemVer applies).

---

## 14. On-Disk Storage Layout

Configurable root (`storage.root`), default `%PROGRAMDATA%\ForensiX` / `/var/lib/forensix`:

```
<root>/
├── cases/<CASE_NUMBER>/
│   ├── evidence/<EVID_ID>/
│   │   ├── <EVID_ID>.E01, .E01.hash …        # or .raw
│   │   ├── manifest.json                      # HashManifest + params + timeline + bad-map
│   │   └── checkpoints/<job>.ckpt.json        # removed on successful completion
│   ├── reports/<REPORT_ID>/report.pdf + .sig + params.json
│   └── exports/
├── audit/
│   ├── audit.sqlite                           # append-only events DB
│   └── anchors/anchor-<seq>-<date>.json
├── casdb/cases.sqlite                         # main DB (SQLite topology)
└── tmp/staging/                                # preflight scratch, auto-cleaned
```

Naming rule: identifiers are case numbers/evidence IDs (human-meaningful, unique), never UUIDs in
filenames — examiners physically label drives with these. Manifests always sit beside their image.

---

## 15. Security Architecture

### 15.1 Cryptography

| Purpose | Choice | Notes |
|---|---|---|
| Integrity hashes | MD5 + SHA-1 + SHA-256 (+SHA-512 opt) | Convention & cross-tool comparison; MD5/SHA-1 are *compatibility*, never sole proof |
| Audit chain | SHA-256 over canonical JSON | §11 |
| Signatures | Ed25519 | Examiner & lab keys; small, fast, modern |
| At-rest (app-level, optional) | XChaCha20-Poly1305 envelope per image file | For exports/removable media |
| At-rest (preferred) | OS layer: BitLocker/LUKS | Documented in admin guide; simpler, audited, whole-volume |

### 15.2 Key management

- Examiner private keys: OS keystore (Windows DPAPI / freedesktop Secret Service) or PKCS#11 token.
  Never in config files, never committed. `forensix keys init` generates & stores; public keys go
  into the `examiners` registry.
- Lab anchor key: held by lab admin, ideally on HSM/YubiKey (PKCS#11 adapter ready).
- Rotation: documented procedure; old keys retained for verification (never deleted).

### 15.3 Secrets

DB credentials / tokens via environment or OS credential store only. `settings.py` refuses to start
if it detects a secret-looking value sourced from a file inside the repo (heuristic + pre-commit
secret scan, see Playbook §9).

### 15.4 Threat model summary (details in Playbook §9)

| Threat | Mitigation |
|---|---|
| Rogue admin edits DB + audit together | Hash chain + externally anchored anchors + examiner signatures |
| Silent evidence modification during acquisition | Fail-closed WP gate + read-back verification pass |
| Destination media corruption | Verify pass detects; piecewise locates region |
| Stolen evidence store | BitLocker/LUKS guidance + optional envelope encryption |
| Malicious/compromised tool build | Signed releases + `selftest` against NIST CFReDS per install |
| Insider replaces binary on workstation | Release checksums published; `forensix version --verify` against signed manifest |

---

## 16. Failure Handling → Component Map

Extends Gap-Analysis Part 6 with *where* each behavior lives:

| Failure | Detected by | Handled in | Behavior |
|---|---|---|---|
| Device disconnect mid-acquire | `read_at` raises `DeviceGoneError` | Acquisition loop → JobService | Auto-pause, checkpoint saved, job → PAUSED_DEVICE_LOST; resume requires re-fingerprint match |
| Bad sector | `UnrecoverableIOError` | Acquisition loop | zero-fill + record + audit event + continue |
| Dest full | Preflight + `ENOSPC` on write | Writer + loop | Preflight blocks start; mid-run: flush, checkpoint, job PAUSED_NEEDS_DEST, prompt for continuation target |
| Hash mismatch | Verify pass | VerificationReport → Image state | state QUARANTINED; analysis/report blocked; REVIEWER notification |
| Crash mid-acquire | Janitor heartbeat sweep | JobService | CRASHED; explicit confirm → resume path (never silent) |
| Perm denied | OS error at open | CLI error renderer | Immediate clear failure, remediation hint ("run elevated"), exit 14 |
| Unsupported FS | TSK probe returns unknown | AnalysisService | Raw imaging unaffected; FS analysis refused with typed error; device registered unsupported |
| WP not detected | Probe | Safety gate | HARD STOP, exit 10; override only by REVIEWER+ role, audited |
| Clock skew >threshold | Clock.sync_status | Preflight | Warning + recorded; >configurable hard limit (default 5 min) ⇒ abort unless overridden+audited |

---

## 17. Observability

### 17.1 Structured logging (structlog)

```json
{"ts":"2026-08-25T09:14:03.112Z","level":"info","logger":"acquisition",
 "trace_id":"acq_7f3a","case":"2026-CR-0142","evidence":"EV-0031",
 "job":"job_5512","event":"checkpoint_saved","next_offset":137438953472,
 "throughput_mbps":118.4,"tool_version":"0.4.1"}
```

Rules:
- `trace_id` = acquisition/analysis/job identifier; present on **every** line for that operation.
- Human console output (Rich) is a rendering of the same structured events — never a parallel path.
- Logs are operational, NOT evidentiary. Evidentiary record = audit log (§11). Log retention short;
  audit retention = case retention. Separation is deliberate and documented.
- No PII/evidence content in log messages — offsets and IDs only.

### 17.2 Metrics (local, Prometheus-text endpoint optional; never leaves host)

`acquisition_throughput_mbps`, `acquisition_bytes_total{format}`, `bad_sector_count`,
`job_duration_seconds{type}`, `job_queue_depth`, `verification_failures_total`,
`wp_gate_blocks_total`.

These double as Daubert-supporting performance/error-rate evidence (see Playbook §10).

---

## 18. Cross-Platform Notes

| Concern | Windows | Linux |
|---|---|---|
| Raw device open | `CreateFile("\\\\.\\PhysicalDriveN")`, share READ only; admin required | `open("/dev/sdX", O_RDONLY \| O_EXCL)`; root or `disk` group |
| Writability probe | `IOCTL_DISK_IS_WRITABLE` | `ioctl(BLKROGET)` + `/sys/block/*/ro` + mounted-ro scan |
| Fingerprint | WMI `Win32_DiskDrive` (SerialNumber, Model, Size) + `IOCTL_STORAGE_QUERY_PROPERTY` | `udevadm info --export-db` / sysfs attrs (model, serial, WWN) |
| Size | `IOCTL_DISK_GET_LENGTH_INFO` | `BLKGETSIZE64` |
| Privilege doc | Explicit UAC/admin requirement in admin guide | sudo/capabilities guidance; document exact group |
| E01 engine | pyewf wheels exist for both | same |
| Keystore | DPAPI | Secret Service (gnome-keyring/kwallet) |

Platform differences live **only** under `adapters/devices/{win32,linux}`; everything above sees
the same `BlockDevice` protocol. CI runs unit+integration on both OSes; device-integration tests
run in QEMU with loop devices on Linux and VHD mounts on Windows runners where feasible.

---

## 19. Testing Architecture

| Layer | Scope | Speed | CI gate |
|---|---|---|---|
| Unit | Domain rules, state machines, canonicalization, chain math, DTO validation | ms | every push, must be 100% green |
| Integration | Repositories (real SQLite), job queue semantics, adapters against synthetic images (file-backed "devices") | seconds | every PR |
| Property-based (Hypothesis) | Carver/parsers vs random+mutated inputs; chain verifier vs shuffled/truncated logs | seconds-min | nightly |
| Chaos | Fault-injection ports: kill mid-write, ENOSPC, corrupt sector stream, stale heartbeats → assert failure-matrix behaviors | minutes | nightly |
| Tool-validation | Golden datasets: NIST CFReDS + `tools/gen_synthetic_disk.py` deterministic images; assert EXACT expected hashes/findings | minutes | nightly + release |
| Contract | OpenAPI snapshot diff; CLI↔service parity checks | seconds | every PR |
| Performance | Throughput benchmark vs baseline (regression >10% fails) | scheduled | weekly |

Synthetic disk factory is deterministic (seeded): generates partition tables, FAT/NTFS/ext4
images with known deleted files, known MAC timestamps, planted artifacts — so expected outputs are
computable and stable. This is what converts "tests pass" into "error rate measured."

---

## 20. Technology Stack

| Layer | Choice | Why | Rejected alternative |
|---|---|---|---|
| Language | Python 3.12+ | Team skillset, ecosystem (TSK/EWF bindings), speed acceptable for I/O-bound work | Rust/Go (better perf, worse iteration + binding friction for v1; revisit for carver hot path via ADR) |
| CLI | Typer + Rich | Declarative, typed; Rich progress | argparse (manual), Click (less typed) |
| Config | pydantic-settings + TOML | Layered + validated | YAML (ambiguous types), ini (weak) |
| Domain models | Pydantic v2 / dataclasses | Validation + fast | attrs (fine, less ecosystem) |
| DB | SQLAlchemy 2.x + Alembic | Standard, migration discipline | raw SQL (no migrations story) |
| API | FastAPI + uvicorn | OpenAPI-native, async | Flask (no schema), Django (too much) |
| Queue | DB-backed custom (§9) | Zero extra infra, air-gap OK | Celery/Redis (ops burden, unjustified at this scale) |
| Logging | structlog | Structured-first | stdlib logging alone (unstructured) |
| Hashing | hashlib (stdlib) | Audited, boring, correct | third-party crypto for digests |
| Signatures | `cryptography` (Ed25519) | Maintained, vetted | pynacl (fine), openssl CLI (fragile) |
| E01 | pyewf / ewfacquire | Battle-tested libewf | hand-rolled EWF (never) |
| FS analysis | pytsk3 (+ TSK binaries fallback) | Industry standard | bespoke parsers for v1 (carving custom later, ADR) |
| Reports | Jinja2 → WeasyPrint (PDF/A-3b) | Deterministic templating + archival PDF | LibreOffice headless (heavy), fpdf (not archival) |
| Packaging | uv + hatchling; PyInstaller for standalone; Docker for server mode | Reproducible envs | setup.py |
| Quality | ruff (lint+fmt), mypy --strict (target), import-linter, pip-audit, bandit | One toolchain, enforced in CI | multiple formatters |

Versioning: **SemVer**. Public contracts: CLI exit codes/output JSON shape, OpenAPI schema,
manifest.json schema (versioned field `schema_version`), audit bundle format. Breaking any of these
requires major bump + migration notes.

---

## 21. Evolution Path: Web/GUI Deployment

Because services already speak DTOs and jobs are first-class:

1. **Web UI (React/Vue) hits the existing FastAPI** — no core change. SSE for progress exists.
2. **Multi-user**: enable Topology C wiring (Postgres adapter + per-examiner auth). RBAC was
   enforced in the service layer since day one, so the API gains teeth automatically.
3. **Scale-out workers**: swap `JobQueue` adapter to Postgres `SKIP LOCKED` fleet. Handlers unchanged.
4. **Review workflow UI** (quarantined-image adjudication, custody approvals) rides existing
   state machines + audit events.

Explicitly *not* planned (non-goals, per Gap-Analysis Part 9): live/remote/cloud/mobile acquisition,
streaming analysis, federated multi-lab sharing.

---

## 22. ADR Seeds

Decisions deliberately deferred; each needs an ADR when triggered:

| # | Decision | Trigger |
|---|---|---|
| 1 | AFF4 support | First lab requests it |
| 2 | Custom carver engine vs TSK/photorec wrapping | Recovery precision benchmarks miss requirements |
| 3 | Rust extension for carve hot path | Profiling shows Python-bound throughput ceiling |
| 4 | Full PAdES embedded PDF signatures | Legal requirement in a target jurisdiction (v1 ships detached .sig + attestation) |
| 5 | PostgreSQL-only cutover (drop SQLite) | Multi-user lab deployment confirmed |
| 6 | Hardware RNG / HSM key ceremony | Lab demands formal key ceremony |
