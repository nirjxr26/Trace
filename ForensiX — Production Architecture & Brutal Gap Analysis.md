# ForensiX — Production Architecture & Brutal Gap Analysis

This document extends the original ForensiX brief. It is written to be consumed both by humans and by an AI coding agent (Claude Code / Cursor / Copilot) as ground-truth project context — so every section states _what_, _why_, and _what breaks if you skip it_.

---

## Part 1 — Brutal Analysis of the Original Spec

The original brief is a solid _shape_ (CLI → services → domain → infra, entity list, module list) but it is not yet a spec a real forensic lab would sign off on. The gaps below are the ones that will bite you in a real deployment or a court challenge — not stylistic nitpicks.

### 1. No compliance/legal framing — this is the biggest gap

Forensic tools aren't judged on "does it work," they're judged on "would a court trust it." Nothing in the original spec references:

- **ISO/IEC 27037** — identification, collection, acquisition, preservation of digital evidence
- **ISO/IEC 27042** — analysis and interpretation of digital evidence
- **NIST SP 800-86** — guide to integrating forensic techniques into incident response
- **Daubert standard** (US) / equivalent — a forensic tool must be _validated_, _tested_, _peer-reviewed_, with a _known error rate_, or its output is inadmissible

**Practical consequence:** without validation against known-good test data (NIST CFReDS reference datasets), any output from ForensiX is legally worthless in a real case. This needs to be a first-class requirement, not an afterthought.

### 2. Single-hash chain of custody is not tamper-evident

Storing a SHA-256 of the image in a normal SQL row means whoever has DB write access can edit the hash and the audit log together. A real chain-of-custody needs to be **append-only and tamper-evident**:

- Hash-chain the audit log itself (each audit event includes the hash of the previous event) — same idea as a blockchain ledger, no need for actual blockchain infra
- Sign critical events (image creation, verification, evidence transfer) with an examiner's private key
- Treat the audit log as evidence in itself — it must survive a "prove this wasn't altered" challenge

### 3. One hash algorithm is thin

SHA-256 alone is fine cryptographically but forensic tooling conventionally computes **multiple algorithms** (MD5 _and_ SHA-1 _and_ SHA-256) because:

- Legacy tools/labs still compare against MD5/SHA-1
- Cross-validation against another tool's output (EnCase, FTK, `dc3dd`) is a standard integrity check
- Add **piecewise/block hashing** (hash every N MB chunk) so a single bad sector doesn't invalidate the whole image — you can prove exactly which region is corrupt

### 4. "Write-protected acquisition" is asserted, not verified

The spec says "prefer write-blocking" but never requires ForensiX to _detect and confirm_ an actual hardware write-blocker is in the data path, or to verify the OS mounted the source read-only. Software promises aren't enough — a dropped `O_RDONLY` flag or a udev rule failure silently converts you into evidence-modifying malware. Required: an explicit **pre-acquisition safety gate** that fails closed (refuses to proceed) unless write-protection is independently verified, not just requested.

### 5. No RBAC / multi-examiner model

Real labs have multiple examiners, evidence custodians, reviewers, and supervisors. The current entity model has no `User`/`Role`/`Permission` concept and no notion of **evidence custody transfer** (Examiner A hands off to Examiner B — that transfer itself must be an audited event). Without this, ForensiX can't model a real lab's operating procedure.

### 6. Progress/async model doesn't survive the GUI transition

CLI commands as described are implicitly synchronous/blocking (`forensix image create EVID-001` presumably blocks until done). Imaging a 4TB drive takes hours. A GUI can't block a browser tab for hours — it needs to **poll or subscribe to job status**. If the Application Service Layer is designed as synchronous function calls, you will have to rewrite it, not just wrap it, when the GUI arrives. This needs to be async from day one (see Part 3).

### 7. No data-at-rest protection for evidence storage

Forensic images often contain highly sensitive personal/corporate data. The spec never mentions encryption at rest for the image store or the case database, nor key management. A leaked unencrypted evidence store is both a security incident and a chain-of-custody failure.

### 8. No retention/disposal policy

Evidence has a legal retention period and then must be securely destroyed (with an audit record of the destruction). This is a hard requirement in most forensic SOPs and is completely absent from the original scope.

### 9. Report generation is under-specified

"Report generation" as a bullet point isn't a spec. Real forensic reports need: standardized structure, examiner attestation/signature, cryptographically signed PDF/A output (long-term archival format), and reproducibility (someone else re-running the same analysis steps against the same image should get the same findings).

### 10. No tool validation / self-test story

Forensic tools are expected to validate themselves against known reference media (NIST CFReDS hash sets, sector-known-content test images) before being trusted in a case. This should be a `forensix selftest` / `forensix validate` command, not something bolted on later.

### 11. Time is a first-class forensic concept, and it's missing

Timestamps (file MAC times, acquisition start/end, audit events) need: consistent UTC storage, NTP-synced host clock verification at acquisition time, and explicit timezone metadata in reports. Courts have thrown out evidence over unexplained timestamp discrepancies.

### 12. Scope ambiguity: physical-only vs. also live/remote

The flow assumes physical media only. That's a reasonable phase-1 boundary, but it should be **stated explicitly as out of scope** (live/remote/cloud/network forensics, mobile device acquisition) so the architecture doesn't silently paint itself into a corner if that's wanted later.

---

## Part 2 — Refined Core Principles (additions to the original list)

Original priority order (evidence integrity → safety → correctness → auditability → fault tolerance → security → testability → maintainability → performance → UX) is good. Add these as non-negotiable, cross-cutting principles:

- **Fail closed, always.** Any uncertainty about evidence integrity, write-protection, hash mismatch, or device identity halts the operation. Never guess and continue.
- **Everything is evidence, including the tool's own behavior.** Logs, audit events, and even ForensiX's version/config at time of acquisition are part of the record.
- **Reproducibility over cleverness.** Two examiners running the same command against the same image on different machines must get identical results.
- **No implicit trust in the OS.** Verify write-protection and device identity independently rather than trusting that the caller passed the right flags.

---

## Part 3 — Architecture: Designing for CLI _and_ GUI from Day One

Use **hexagonal (ports & adapters) architecture**, which the original spec gestures at but doesn't formalize:

```
                    ┌─────────────────────────────┐
   CLI (Typer) ────▶│                              │
   REST/gRPC API ──▶│   Application Service Layer  │◀──── Web UI (future)
   (future)          │   (use-case orchestration)   │◀──── Desktop UI (future)
                    │                              │
                    └───────────┬──────────────────┘
                                │
                    ┌───────────▼──────────────────┐
                    │        Domain Layer           │
                    │  (Case, Evidence, Image, ...) │
                    │  pure business rules, no I/O   │
                    └───────────┬──────────────────┘
                                │
                    ┌───────────▼──────────────────┐
                    │     Infrastructure Layer      │
                    │  DB, filesystem, device I/O,   │
                    │  hashing, external tools        │
                    └────────────────────────────────┘
```

Key rule an AI coding agent should enforce: **the CLI is just one adapter.** It must never contain business logic, validation rules, or direct DB/filesystem access — only argument parsing, calling a service method, and formatting output.

### The concrete GUI-readiness requirement: build a thin internal API now

Don't wait for "the GUI phase" to add an API. Instead:

1. Application Service Layer methods return **plain DTOs (Pydantic models)**, never ORM objects, never CLI-formatted strings.
2. Long-running operations (imaging, recovery, analysis) are modeled as **Jobs**: `POST` a job, get a `job_id`, poll or subscribe for `JobStatus{state, progress_pct, message, error}`. The CLI just polls its own local job and renders a progress bar; a future web client polls the same job over HTTP or subscribes via SSE/WebSocket — no rewrite needed.
3. Wrap the Application Service Layer in a thin **FastAPI (or equivalent) REST layer** early, even if only the CLI calls it locally at first. This forces the CLI to _not_ special-case anything, because it's forced through the same contract a GUI would use.
4. Use a background job runner (Celery, RQ, or even a simple asyncio task queue for phase 1) so acquisition/imaging isn't blocking either the CLI process or a hypothetical web request.
5. Define the API contract with **OpenAPI/JSON Schema** from the start — this becomes free documentation and a contract test suite.

This is the single highest-leverage change relative to the original spec: it turns "CLI first, GUI later" from a rewrite risk into a genuinely additive step (new adapter, same core).

---

## Part 4 — Expanded Domain Model

Additions to the original entity list:

| Entity                               | Purpose                                                                                                                                        |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `Examiner` / `User`                  | Identity of who performed an action — required for chain of custody and RBAC                                                                   |
| `Role` / `Permission`                | Examiner, Reviewer, Lab Admin, Read-only Auditor — gates which service calls are allowed                                                       |
| `CustodyTransfer`                    | Explicit record of evidence moving between examiners/storage locations, distinct from generic audit events                                     |
| `Job`                                | Async unit of work (acquisition, analysis, recovery, report generation) with status/progress, decoupled from CLI/HTTP request lifecycle        |
| `ValidationRun`                      | Result of running ForensiX against a known reference dataset (NIST CFReDS or similar) — proves the tool behaves correctly on this build/config |
| `RetentionPolicy` / `DisposalRecord` | When evidence may/must be destroyed, and the audited record that it was                                                                        |
| `DeviceFingerprint`                  | Serial number, model, capacity, firmware version, interface type — captured _before_ acquisition begins, used for the safety/identity gate     |
| `PiecewiseHash`                      | Per-block hash records tied to a Forensic Image, enabling partial-corruption proof                                                             |
| `Attestation`                        | Examiner's signed statement accompanying a Report — the legal "I performed this analysis" record                                               |

Extend existing entities:

- `Acquisition` needs: write-blocker verification result, source device fingerprint snapshot, retry/resume checkpoint state, host clock/NTP sync status at start.
- `Forensic Image` needs: format (RAW/E01/AFF4), compression, segment files (E01 splits into .E01/.E02/...), multiple hash values, piecewise hash list.
- `Audit Event` needs: previous-event hash (hash chain), actor (`Examiner`), optional digital signature.
- `Report` needs: format (PDF/A for archival), signature/attestation reference, generation reproducibility metadata (tool version, exact command/parameters used).

---

## Part 5 — Security & Forensic Integrity (expanded)

Beyond the original list, add:

- **Independent write-protection verification**, not just intent: check the block device's read-only status at the kernel/udev level and via a physical write-blocker where available; abort acquisition if unverifiable.
- **Dual/triple hashing** (MD5 + SHA-1 + SHA-256 minimum) plus piecewise hashing.
- **Tamper-evident audit log** via hash-chaining + examiner signing of critical events.
- **Encryption at rest** for the case database and image store (e.g., LUKS/dm-crypt at the storage layer, or application-level encryption with proper key management — never a hardcoded key).
- **RBAC enforced in the Application Service Layer**, not just the CLI (since the API layer will be a second entry point).
- **Secrets management**: DB credentials, signing keys — never in config files committed to source; use environment variables or a secrets manager, and say so explicitly in the infra module.
- **Immutable/append-only storage** for the audit log (write-once table, or an actual append-only log file, checked against tampering on read).
- **Retention & secure disposal**, with the disposal itself producing an audit event.

---

## Part 6 — Failure Handling Matrix (concrete, not just a bullet list)

| Failure                            | Detection                                 | Required Behavior                                                                                                                                                             |
| ---------------------------------- | ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Device disconnects mid-acquisition | I/O error / device node disappears        | Pause, checkpoint offset, log event, allow resume once device reappears with fingerprint re-verification                                                                      |
| Bad/corrupted sector               | Read error at offset                      | Log offset+error, write zero-fill or padding marker (per E01 convention), continue — never abort the whole image for one bad sector                                           |
| Destination full                   | Write error / preflight free-space check  | Preflight check before starting (compare estimated image size vs. free space); mid-acquisition, pause and prompt for new destination, don't corrupt partial image             |
| Hash mismatch after verification   | Post-acquisition hash != expected         | Flag evidence as **unverified**, block downstream analysis/report generation until reviewed by a second examiner                                                              |
| Process crash mid-acquisition      | Missing heartbeat / unclean shutdown flag | On restart, detect incomplete job, do not silently resume without explicit examiner confirmation                                                                              |
| Permission errors                  | OS-level access denied                    | Fail immediately with clear remediation message; never attempt privilege escalation silently                                                                                  |
| Unsupported filesystem/device      | Detection step returns unknown type       | Register device with `unsupported` status, allow raw sector imaging still (imaging doesn't require filesystem understanding), block filesystem-level analysis until supported |
| Write-blocker not detected         | Safety gate check                         | **Hard stop** — do not proceed with acquisition at all                                                                                                                        |

---

## Part 7 — Testing & Validation Strategy

This needs to be its own module-level concern, not just "pytest":

- **Unit tests** for domain logic (pure, no I/O) — the bulk of test coverage should live here since it's fast and deterministic.
- **Integration tests** using loopback devices / disk image files as fake "physical devices" (`losetup` on Linux) so CI doesn't need real hardware.
- **Tool validation tests**: run ForensiX against NIST CFReDS reference images and known-content test images; assert exact expected hash/recovery output. This is what makes ForensiX's output _legally defensible_, not just "it passed my tests."
- **Property-based tests** (Hypothesis) for parsers/carvers — file carving and filesystem parsing are exactly the kind of code that breaks on malformed/adversarial input.
- **Chaos/failure-injection tests** for the acquisition engine: simulate disconnects, I/O errors, and crashes mid-write and assert the failure matrix above is honored.
- **Contract tests** against the OpenAPI schema once the API layer exists, so CLI and future GUI can't silently drift from the documented contract.

---

## Part 8 — Deployment, Ops & Observability (missing from original)

- **Containerization**: Docker image for the backend/API layer; CLI can run natively or in-container. Document required host privileges (raw device access needs elevated permissions — be explicit about what and why).
- **Structured logging** (already listed) should be **correlated** — every log line for a given acquisition/case carries a trace/job ID so a support engineer (or an AI coding agent) can follow one operation end-to-end across the CLI, service, and infra layers.
- **Metrics**: acquisition throughput (MB/s), error rates, job queue depth — useful both operationally and as evidence of tool performance.
- **CI/CD**: GitHub Actions running lint (Ruff), type-check (mypy), unit+integration tests, and the tool-validation suite on every PR; block merge on failure.
- **Migrations**: Alembic migrations must be reviewed as carefully as schema changes to production forensic data — never allow a destructive migration to run without an explicit backup step.
- **Backup/DR for the case database itself** — losing the case DB (not the evidence images) still destroys chain-of-custody continuity.

---

## Part 9 — Explicit Non-Goals (Phase 1)

State these clearly so scope doesn't creep and so an AI agent building this doesn't "helpfully" wander:

- Live/remote/network forensics (acquiring from a running remote system)
- Mobile device acquisition (iOS/Android — different toolchain entirely, e.g. Cellebrite-class tooling)
- Cloud/SaaS forensics (M365, Google Workspace, AWS artifacts)
- Real-time/streaming analysis during acquisition (analysis happens on the completed, verified image only)
- Multi-lab/federated case sharing across organizations

---

## Part 10 — Revised Module List (Team of 4, mapped to the above)

1. **Hardware/Acquisition** (Person 1) — device discovery, fingerprinting, independent write-protection verification, sector acquisition with resume/checkpoint, RAW/E01 imaging, multi-algorithm + piecewise hashing, job/progress model.
2. **Analysis & Recovery** (Person 2) — partition/filesystem parsing (via Sleuth Kit bindings), file carving, deleted-file recovery, timeline construction, artifact-to-evidence linkage.
3. **Backend/Domain/Chain-of-Custody** (Person 3) — domain entities, SQLAlchemy models, RBAC, tamper-evident/hash-chained audit log, custody transfer records, retention/disposal.
4. **CLI/API/Infrastructure/QA** (Person 4) — Typer CLI as a pure adapter, thin FastAPI layer + job queue for GUI-readiness, structured logging/observability, CI/CD, unit/integration/tool-validation test suites.

---

## Summary: What Changed vs. the Original Brief

| Area               | Original                                  | Now                                                                                     |
| ------------------ | ----------------------------------------- | --------------------------------------------------------------------------------------- |
| Legal grounding    | Implied                                   | Explicit ISO 27037/27042, NIST SP 800-86, Daubert-driven validation requirement         |
| Hashing            | Single SHA-256                            | Multi-algorithm + piecewise, tool-validated against NIST CFReDS                         |
| Chain of custody   | DB records                                | Tamper-evident hash-chained + signed audit log, explicit custody transfer entity        |
| Write protection   | Asserted                                  | Independently verified, fail-closed safety gate                                         |
| Access control     | None                                      | RBAC with Examiner/Reviewer/Admin roles                                                 |
| GUI-readiness      | "Future UI can reuse core" (aspirational) | Concrete: DTOs, async Job model, thin API + queue built in phase 1                      |
| Encryption at rest | None                                      | Required for evidence store and case DB                                                 |
| Retention/disposal | None                                      | Explicit policy + audited disposal                                                      |
| Testing            | pytest, generic                           | Unit + integration + property + chaos + tool-validation, contract tests once API exists |
| Scope              | Implicit physical-only                    | Explicit non-goals list                                                                 |
