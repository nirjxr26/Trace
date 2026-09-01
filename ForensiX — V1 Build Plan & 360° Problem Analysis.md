# ForensiX — V1 Build Plan & 360° Problem Analysis

> Companion docs (read order):
> 1. `ForensiX — Production Architecture & Brutal Gap Analysis.md` — why the domain demands these things
> 2. `ForensiX — System Design & Backend Architecture.md` — full target architecture (V2/V3 horizon)
> 3. **This doc** — the *actual first build*: tight scope, concrete tooling, week-by-week plan,
>    and an honest map of every problem V1 will hit.
>
> Philosophy of V1: **small surface, deep integrity.** Better to image a drive perfectly with a
> provable trail than to half-do ten features. Everything here is chosen so V1 is genuinely
> demo-impressive AND legally-honest — nothing in V1 claims more than it tests.

---

## Table of Contents

1. [V1 Mission Statement](#1-v1-mission-statement)
2. [What V1 Does — Feature List](#2-what-v1-does--feature-list)
3. [What V1 Deliberately Does NOT Do](#3-what-v1-deliberately-does-not-do)
4. [Why This Scope Is Impressive](#4-why-this-scope-is-impressive)
5. [Tools & Environment Setup](#5-tools--environment-setup)
6. [Project Bootstrap — Step by Step](#6-project-bootstrap--step-by-step)
7. [V1 Architecture (Simplified Hexagon)](#7-v1-architecture-simplified-hexagon)
8. [Module Plan & Build Order (Weeks 1–6)](#8-module-plan--build-order-weeks-16)
9. [The Five Demo Scenarios V1 Must Nail](#9-the-five-demo-scenarios-v1-must-nail)
10. [360° Problem Analysis](#10-360-problem-analysis)
11. [V1 Acceptance Criteria](#11-v1-acceptance-criteria)
12. [Bridge to V1.5 / V2](#12-bridge-to-v15--v2)

---

## 1. V1 Mission Statement

> **ForensiX V1 acquires physical drives into verifiable forensic images with a tamper-evident
> audit trail — surviving crashes, bad sectors, and operator mistakes — from a single CLI,
> on Windows and Linux, with zero infrastructure.**

One sentence decomposition:

| Fragment | What it commits us to |
|---|---|
| "acquires physical drives" | Real device access on Win+Linux, fingerprints, safety checks |
| "verifiable forensic images" | Multi-hash + piecewise hashing + mandatory read-back verification |
| "tamper-evident audit trail" | Hash-chained append-only event log with export + verify commands |
| "surviving crashes/bad sectors/mistakes" | Checkpoint-resume, zero-fill-and-record bad-region policy, preflight guards |
| "single CLI, zero infrastructure" | One Python install, SQLite, no daemons/servers/accounts |

---

## 2. What V1 Does — Feature List

### F1. Case & evidence registry
```
forensix case create|list|show|close
forensix evidence register|list|show
```
- Cases have numbers (`2026-CR-0001`), status lifecycle (`OPEN→CLOSED`), notes.
- Evidence items attach to cases with labels (`EV-0031`), collection metadata.
- Single-examiner model: a configured examiner name/ID stamps every action (no login system yet).

### F2. Device discovery & fingerprinting
```
forensix devices list
forensix devices inspect <DEVICE>
```
- Enumerates block devices with size/model/interface.
- Captures full fingerprint: serial, model, capacity, firmware, interface, WWN (where OS exposes it).
- Fingerprint is stored **before** any evidentiary read and embedded in the image manifest.

### F3. Software write-protection check (fail-closed)
```
# runs automatically before acquisition; also standalone:
forensix devices check-writable <DEVICE>
```
- Linux: `O_RDONLY|O_EXCL` open + `BLKROGET` ioctl + `/sys/block/*/ro` check.
- Windows: `CreateFile(...FILE_SHARE_READ)` + `IOCTL_DISK_IS_WRITABLE`.
- Result ∈ {READ_ONLY ✅ proceed} / {WRITABLE ❌ abort, exit 10} / {UNKNOWN ⚠ abort unless
  `--acknowledge-unverified-source` given, which records an explicit audited override}.
- Honest labeling in docs: this verifies *software-visible* state; a hardware write-blocker is
  still recommended for real casework (V1 documents this limitation rather than hiding it).

### F4. RAW forensic acquisition (the core)
```
forensix image acquire <DEVICE> --case CASE --label EV-0031 [--chunk-size 4M] [--dest DIR]
```
Pipeline per acquisition: **fingerprint → safety gate → preflight → copy loop → finalize →
verify pass → register**.

Copy loop specifics:
- Chunked streaming (default 4 MiB) — constant memory regardless of drive size.
- Inline hashing: **MD5 + SHA-1 + SHA-256** whole-image, plus **SHA-256 piecewise per 4 MiB block**.
- Progress bar (Rich): percent, throughput MB/s, ETA, elapsed.
- Checkpoints every 64 GiB + on Ctrl-C (graceful pause, never silent kill of state).
- Bad sector encountered → zero-fill chunk, record offset range, continue, audit event.
  Never abort the whole image for one bad region.
- Preflight guards: free space ≥ est×1.05, destination ≠ source, destination writable, clock sanity.

### F5. Crash-safe resume
```
forensix image resume <JOB_ID>
forensix job list|status <JOB_ID>
```
- Process killed / power loss / Ctrl-C mid-copy ⇒ next invocation resumes at exact checkpoint offset.
- Resume **re-fingerprints the source first**; mismatch = refuse (wrong/replaced device protection).
- Property-tested invariant: resumed image ≡ uninterrupted image (byte-identical, modulo recorded
  bad regions).

### F6. Mandatory verification pass
```
forensix image verify <IMAGE_ID>
```
- Reads back the finished image from disk, recomputes all hashes, compares to acquisition-time values.
- Pass → image status `VERIFIED`; fail → `QUARANTINED`, downstream actions blocked.
- Piecewise comparison means a corrupted region is pinpointed to its exact 4 MiB block index+offset.

### F7. Tamper-evident audit log
```
forensix audit show [--case CASE]
forensix audit verify
forensix audit export --format jsonl --out bundle.jsonl
```
- Every action (case created, acquisition started/checkpointed/completed, bad sector, verification,
  override) becomes an event in an **append-only** SQLite table.
- Chain: `chain_hash_n = SHA256(chain_hash_{n-1} ‖ payload_hash_n ‖ seq_n)`; genesis anchored to zeros.
- `audit verify` recomputes the entire chain and names the exact seq where any tampering occurred.
- Adapter physically blocks UPDATE/DELETE (trigger raises).

### F8. Image manifest (versioned)
Every image gets a sidecar `manifest.json` (schema_version field):
```json
{
  "schema_version": 1,
  "image_id": "...", "case": "2026-CR-0001", "evidence_label": "EV-0031",
  "format": "RAW",
  "source_fingerprint": {"serial": "...", "model": "...", "capacity_bytes": ..., ...},
  "acquisition": {"started_at": "...Z", "finished_at": "...Z",
                  "tool_version": "0.1.0", "config_snapshot_hash": "...",
                  "wp_check": "READ_ONLY", "clock_sync": "NTP_OK"},
  "hashes": {"md5": "...", "sha1": "...", "sha256": "..."},
  "piecewise": {"algorithm": "sha256", "chunk_size": 4194304, "count": 119209,
                "first": "...", "stored_in": "piecewise.sqlite"},
  "bad_regions": [{"start": 889192448, "length": 4194304}],
  "verification": {"verified_at": "...Z", "verdict": "PASS"}
}
```

### F9. Self-test
```
forensix selftest run
```
- Generates deterministic synthetic disks locally (seeded factory), runs the full pipeline against
  them, asserts expected hashes/findings. Green self-test = "this install behaves correctly."
- This is the seed of the future NIST CFReDS validation suite (V2).

### F10. Case summary report (text/markdown)
```
forensix report generate <CASE>
```
- Markdown report: case metadata, evidence list, per-image hash tables, timeline of audited events,
  tool/version/config info, examiner statement placeholder.
- Plain, reproducible, diffable — deliberately NOT a signed PDF in V1 (that's V2; we don't ship
  signatures we haven't built a key ceremony for).

### Cross-cutting (part of V1, not extras)
- `--output json|table` on all listing commands; stable documented **exit codes**.
- Structured logs (JSON lines) separate from the evidentiary audit log.
- Layered TOML config (`forensix config show/set/path`).
- Alembic-managed SQLite schema from migration #1.
- CI from day one: ruff + mypy(strict-on-core) + pytest + boundary-contract checker.

---

## 3. What V1 Deliberately Does NOT Do

Saying no is the scope discipline that keeps V1 shippable:

| Excluded | Why excluded from V1 | Returns in |
|---|---|---|
| E01/EWF image format | Adds binding/tooling risk (libewf) before core loop proven; RAW+manifest is fully verifiable today | V1.5 (adapter slot reserved) |
| Filesystem analysis / carving (TSK) | Heavy native dep (pytsk3 wheel pain on Windows); orthogonal to acquisition integrity | V1.5 stretch |
| Multi-user / RBAC / custody-transfer signatures | Needs identity & key infrastructure; premature before single-operator loop is bulletproof | V2 |
| Local daemon + REST API | Real value only with GUI/multi-client; DTO-first design keeps door open at near-zero retrofit cost | V2 |
| PDF/A + digital signatures on reports | Without a key ceremony it's security theater; markdown report is honest | V2 |
| Retention/disposal workflows, encryption-at-rest | Lab-process features; depend on deployment context | V2/V3 |
| Live/cloud/mobile acquisition | Explicit non-goal of the product phase-1 (see Gap Analysis Part 9) | never in this line |
| Hardware write-blocker *guarantee* | Physically impossible to guarantee from software; V1 verifies software state + documents the limit | documented forever |

---

## 4. Why This Scope Is Impressive

Against typical student/hobby "disk imager" projects, V1 already demonstrates:

1. **Crash-proof acquisition** — kill the process mid-image, resume exactly, prove byte-equality.
   Most imagers (including several commercial ones) fail this demo.
2. **Pinpoint corruption forensics** — flip one bit anywhere in a 500 GB image; `verify` names the
   guilty 4 MiB block. That's piecewise hashing most tools don't expose cleanly.
3. **Tamper-evident history** — edit one row in the audit DB; `audit verify` convicts it instantly.
   A live "try to fool it and fail" demo lands hard with any audience.
4. **Honest failure handling** — pull the USB cable mid-run; watch it pause, checkpoint, and offer
   verified resume instead of crashing or silently truncating.
5. **Engineering maturity signals** — strict typing, architectural boundary enforcement in CI,
   deterministic synthetic test corpora, property-based resume tests. Rare even in professional tools.

Impressiveness here comes from **depth of guarantees**, not breadth of features.

---

## 5. Tools & Environment Setup

### 5.1 Core toolchain

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.12.x | runtime |
| uv | latest | env + lockfile + builds (`pip` alternative, fast, reproducible) |
| Git | latest | version control (initialize when scaffolding the code repo) |
| VS Code / PyCharm | — | editor (ruff + mypy extensions) |
| Windows Terminal / bash | — | shells |

### 5.2 Python dependencies (deliberately minimal)

```
typer>=0.12          # CLI framework (typed)
rich                 # progress bars, tables (comes with typer[all])
pydantic>=2.7        # DTOs, settings validation
pydantic-settings    # layered TOML+env config
sqlalchemy>=2.0      # persistence (2.0 style)
alembic              # migrations
structlog            # structured logging
```

Dev/test:
```
pytest, pytest-cov, hypothesis      # test stack incl. property-based
ruff                                # lint + format
mypy                                # typing (strict on src/forensix/domain+application+ports)
import-linter                       # architectural boundary contracts
freezegun                           # deterministic time in tests
```

Notably **absent on purpose**: celery/redis (no queue infra), fastapi (no API yet),
pytsk3/pyewf (deferred), cryptography (no signing yet). Fewer deps = fewer supply-chain and
platform headaches while the core proves itself.

### 5.3 Test hardware/environment matrix

| Environment | Use |
|---|---|
| **File-backed fake devices** (primary dev) | A `BlockDevice` adapter reading a plain file lets 95% of development happen with zero privileges and zero risk. All CI runs here. |
| **Linux loop devices** (`losetup`) | Integration realism: kernel block device semantics, BLKROGET ro-flag behavior. WSL2 does NOT support losetup reliably → use a Linux VM or spare machine/partition. |
| **Windows VHD mount** (dev machine) | Mount a VHD read-only via Disk Management to exercise `\\.\PhysicalDriveN` paths safely. |
| **One sacrificial USB drive** | Final acceptance: real USB acquire/verify cycle. Label it clearly TEST-NOT-EVIDENCE. |

⚠️ Rule: **never develop against a drive containing anything you care about.** Device selection
bugs are the #1 way hobby forensic projects destroy someone's data (see §10.5).

---

## 6. Project Bootstrap — Step by Step

```powershell
# 1. scaffold
uv init forensix --package && cd forensix
uv python pin 3.12

# 2. dependencies
uv add typer rich pydantic pydantic-settings sqlalchemy alembic structlog
uv add --dev pytest pytest-cov hypothesis ruff mypy import-linter freezegun

# 3. layout (see Architecture doc §4; V1 subset below)
mkdir src/forensix/domain,src/forensix/application,src/forensix/ports,
      src/forensix/adapters/db,src/forensix/adapters/devices/win32,
      src/forensix/adapters/devices/linux,src/forensix/adapters/imaging,
      src/forensix/adapters/hashing,src/forensix/adapters/audit,
      src/forensix/cli,src/forensix/cli/commands,tests/unit,tests/integration,
      tests/chaos,tools

# 4. quality gates wired BEFORE first feature commit
#    - pyproject: [tool.ruff], [tool.mypy] strict for domain/application/ports
#    - importlinter.toml: domain→nothing, application→domain+ports only,
#      cli→application only
#    - .github/workflows/ci.yml: ruff, mypy, pytest on windows+ubuntu matrix
git init && git add -A && git commit -m "chore: scaffold with quality gates"
```

First milestone commit sequence (each independently green):
1. Settings + logging + exit-code contract modules + their tests
2. Domain entities/state machines + audit chain math (pure functions, exhaustive unit tests)
3. Fake-device port + synthetic disk factory (`tools/gen_synthetic_disk.py`)
4. Acquisition engine against fakes + resume property test
5. Audit appender/reader adapters + chain verifier
6. CLI wiring end-to-end

---

## 7. V1 Architecture (Simplified Hexagon)

Identical principles to the full architecture doc, fewer modules:

```
CLI (Typer/Rich)  ──▶  Application Services ──▶  Domain (pure rules/state machines)
                            │                        ▲
                     uses ports                      │ implemented by
                            ▼                        │
                    Ports (Protocols) ◀──── Adapters: sqlite-db · win32/linux devices
                                             raw-imaging · multihash · chained-audit
                                             fake-device (tests)
```

Runtime shape: **one process**. `image acquire` runs the pipeline inline (no background worker
needed in V1 — the CLI process owns the long task, checkpoints make it restartable). The Job table
still exists so V2's daemon can adopt the exact same rows later.

Key simplifications vs. full doc (all reversible, none structural):
- No FastAPI layer (DTOs still used everywhere, so adding it is a router exercise).
- No Signer port (audit chain is un-signed but still tamper-*evident*; signing slots in later
  without changing chain math — signature becomes another field hashed into payload).
- Single storage engine: SQLite WAL.

---

## 8. Module Plan & Build Order (Weeks 1–6)

| Week | Deliverable | Done when |
|---|---|---|
| 1 | Scaffold, gates, settings/logging/exit-codes, ADR seeds | CI green on windows+ubuntu; boundary linter active |
| 2 | Domain: entities, state machines, canonicalization, chain math | 100% typed; chain math property-tested against mutation fuzzing |
| 3 | Ports + fake device + synthetic disk factory + DB adapters (cases/evidence/jobs) | Factory output byte-stable; repo tests on real SQLite |
| 4 | Acquisition engine: copy loop, multihash, piecewise, checkpoints, bad-region policy | Kill-at-random-offset property test passes; throughput ≥100 MB/s on SSD-to-file |
| 5 | Verify pass, quarantine flow, resume UX, audit show/verify/export, manifests | Demo scenarios 1–4 scripted and passing |
| 6 | Report generation, selftest command, polish (help texts, errors, JSON shapes), docs-lite | Demo scenario 5 + acceptance checklist §11 green |

Team-of-one or pair pacing assumed; scale linearly otherwise. Weeks 4–5 are the technical heart —
protect them from scope creep ruthlessly.

---

## 9. The Five Demo Scenarios V1 Must Nail

Scriptable, repeatable, and each one is a "wow" moment with substance behind it:

1. **Clean acquisition** — image a 32 GB test drive/file-device: live progress, final manifest
   printed, three digests shown, `verify` → PASS in one smooth run.
2. **Assassination test** — start acquisition, `kill -9` the process at 40%, relaunch with
   `resume`, watch it pick up at the exact sector, finish, verify PASS. Then diff against a
   reference copy: identical.
3. **Corruption localization** — flip one byte at offset 3.2 GB in the stored image;
   `verify` reports FAIL naming block #762 (offset range) — then restore, PASS again.
4. **Audit conviction** — `sqlite3 audit.db "UPDATE audit_events SET actor='someone' WHERE seq=42"`;
   `forensix audit verify` prints: `TAMPER DETECTED at seq=42`. Export bundle re-verifies clean.
5. **Self-check** — fresh machine: `forensix selftest run` → generates synthetic disks, runs the
   whole pipeline headless, all assertions green. "This tool just proved itself" moment.

If a stakeholder only ever sees these five demos, they've seen everything V1 promises.

---

## 10. 360° Problem Analysis

Every category of trouble V1 will actually hit, with mitigations designed in from day one.

### 10.1 Platform & OS problems

| Problem | Reality | Mitigation |
|---|---|---|
| Raw access needs elevation | Windows `\\.\PhysicalDriveN` requires admin; Linux `/dev/sdX` needs root/`disk` group | Dev via file-backed fakes; elevate only for real runs; `doctor`-style preflight message states exactly what's missing |
| **PhysicalDrive numbering is unstable** | `PhysicalDrive2` today may be `PhysicalDrive1` tomorrow (USB order, boot changes) | Never persist device *names* as truth — persist **fingerprints**; UI always shows serial+model beside the name; acquire re-confirms fingerprint before writing anything |
| Windows volume auto-mount writes to source | AutoPlay/mounting updates access times, $LogFile etc. | Safety gate checks writable state; docs instruct hardware blocker or OS-level RO where possible; UNKNOWN → explicit audited override required |
| Antivirus/EDR blocks raw reads or our binary | Common on corporate Windows | Documented exclusion guidance; fail loudly with remediation text, never retry-storm |
| WSL2 ≠ real Linux block stack | No losetup, different /sys | Treat WSL as unit-test host only; integration on real Linux VM/bare metal |
| Path/encoding hell | Unicode device names, long paths, UTF-16 Win APIs | All internal strings UTF-8; Windows adapters isolate wide-char conversions; test unicode filenames in fixtures |

### 10.2 Hardware & media problems

| Problem | Reality | Mitigation |
|---|---|---|
| Bad/degraded sectors | The reason imaging exists | Zero-fill + record + continue policy; bad-region map in manifest; verify pass flags them honestly |
| Mid-read device disconnect | USB cables, power saving | Typed `DeviceGoneError` → graceful pause + checkpoint; resume re-fingerprints |
| USB bridges lie | Some adapters fake serials, cache identify data, truncate >2TB | Fingerprint includes capacity+WWN cross-check; capacity anomalies recorded as warnings; docs list known-bad bridge behaviors |
| Destination dies mid-write | Cheap target drives | fsync at checkpoints; verify pass catches; ENOSPC/dying-disk handled as PAUSED_NEEDS_DEST |
| Hidden areas (HPA/DCO) | Host-protected areas invisible to OS | **Explicitly out of V1 scope**, documented limitation; roadmap note (ATA commands need elevated passthrough) |
| Source larger than destination estimate math | Rounding, sector-size mismatch (512e vs 4K) | Size arithmetic in bytes everywhere (BIGINT); preflight ×1.05 margin; unit tests for 512/4096 sector mixes |

### 10.3 Performance problems

| Problem | Reality | Mitigation |
|---|---|---|
| Python too slow? | Naive loops aren't; but hashing is C (hashlib releases GIL) and I/O dominates | Buffered chunk I/O, single-pass multihash, measure weekly; target ≥100 MB/s conservative floor, stretch 400+ on SSD→NVMe |
| Memory blowups on huge drives | Streaming done wrong | Fixed 4 MiB chunks; constant-memory invariant asserted in tests (RSS sampling in perf test) |
| Progress rendering slows the loop | Rich redraw cost per chunk | Throttle UI updates to ≥250 ms intervals; progress lives outside hot loop |
| fsync cost | Full-fsync per chunk would halve throughput | fsync at checkpoints (64 GiB default) + finalize; correctness guaranteed by verify pass, not per-chunk flushes (documented rationale) |
| Piecewise store bloat | 500 GB ÷ 4 MiB = 119k rows | Bulk-insert batches; piecewise in dedicated sqlite beside manifest; indexed by block index |

### 10.4 Correctness & integrity problems (the ones that matter most)

| Problem | Trap | Mitigation |
|---|---|---|
| Resume ≠ original image | Off-by-one at chunk boundaries; re-read drift on flaky media | Property test: random kill offsets × 100 runs → byte-compare; checkpoint stores next_offset + params hash + piecewise count |
| Whole-image hash can't resume | hashlib state isn't serializable | Two-pass design: inline piecewise during copy; whole-image hashes computed on read-back verify (also validates destination) |
| Partial final chunk math | Last block shorter than chunk size | Piecewise length recorded per block; last-block unit tests at multiple sizes |
| Sparse/zero regions inflate files | Wasted space, slower verify | Optional zero-chunk detection (skip-write, mark sparse) behind config flag — default OFF until proven (correctness first) |
| Manifest lies if edited | Manifest is just JSON | Manifest hash itself recorded in audit events; `verify` recomputes from image, not from manifest trust |
| Clock skew poisoning timestamps | Wrong times in evidence record | Capture NTP sync status at start; warn/abort threshold configurable; UTC-only storage enforced by lint rule |
| Ctrl-C corrupts state | Signal handlers writing mid-row | Handler sets flag; loop finishes current chunk, saves checkpoint, exits cleanly; SIGKILL covered by crash recovery anyway |

### 10.5 Data-safety problems (where V1 could hurt someone)

These deserve their own section because a forensic tool that destroys data is worse than useless:

| Problem | Mitigation |
|---|---|
| **Imaging INTO the source device** (direction confusion) | Triple guard: preflight compares fingerprints source≠destination; destination must be a regular file path, never a device node; acquire refuses device-node destinations entirely |
| Selecting the wrong PhysicalDrive | Confirm prompt echoes serial/model/capacity and requires typed confirmation for devices >0 bytes that look non-empty; `--yes` exists but is audited |
| Test tooling touching real drives | Fake-device port is default; real-device paths require `--i-understand-this-touches-real-hardware` style explicit opt-in flag in dev builds |
| Overwriting existing image file | Refuse unless `--force` + prior file gets `.bak-<timestamp>` rename, audited |
| Silent truncation on crash | Crash leaves QUARANTINED/incomplete marker; resume/verify flows refuse ambiguous states without explicit examiner choice |

### 10.6 Forensic-credibility problems

| Problem | Risk | Mitigation |
|---|---|---|
| Overclaiming compliance | Legal exposure | V1 docs say exactly what's verified (software WP state, hashes, chain) and what isn't (hardware blocker, HPA, E01 interop); honesty is a feature |
| Non-reproducible outputs | Daubert problem | Config snapshot hash + tool version in every manifest; same input+version ⇒ identical digests; determinism tested |
| Undocumented error-rate | Can't defend tool in court | Selftest + synthetic corpus from day one; V2 formalizes CFReDS; V1 at least measures and publishes selftest results |
| Timestamp ambiguity | Courts hate unexplained times | UTC everywhere + captured clock-sync status + explicit timezone notes in reports |

### 10.7 Engineering & team problems

| Problem | Reality | Mitigation |
|---|---|---|
| Boundary erosion ("just this once" imports) | How every hexagonal project dies | import-linter blocking merge; new-dev onboarding doc explains the *why* (courts, not aesthetics) |
| mypy strict friction slowing velocity | Early weeks feel slow | Strict scope grows gradually (core first); typed DTOs pay off immediately at CLI edges |
| Test corpus effort explodes | Hand-making disk images is misery | Deterministic seeded factory IS the corpus strategy; golden hashes computed once, reused everywhere |
| Windows CI slowness/cost | GH Actions Windows minutes | Windows job runs unit+fake-integration only; heavier suites nightly |
| Scope creep (the eternal one) | "Just add E01, how hard…" | §3 exclusion table is the contract; additions require swapping something out or a written deferral |
| Solo-developer knowledge silos | Bus factor 1 | ADR habit + this doc set + demo scripts double as documentation |

### 10.8 UX & interface problems

| Problem | Mitigation |
|---|---|
| Hours-long command feels dead | Rich progress + throughput + ETA; `--quiet` for scripting; job rows let any later invocation query status |
| Errors that say "Error" | Every failure = typed exception mapped to specific exit code + remediation hint ("run elevated", "device went away — resume with …") |
| Output drift breaking scripts | JSON shapes frozen at v0.1; schema_version fields; contract tests assert shapes |
| Dangerous defaults | Destructive ops always confirm; safe defaults everywhere (RAW format, conservative chunk, verify mandatory) |

---

## 11. V1 Acceptance Criteria

V1 is done when ALL of these are true:

**Functional**
- [ ] All five demo scenarios (§9) execute green from scripts on Windows AND Linux
- [ ] Real USB drive end-to-end: acquire → verify → manifest correct → report generated
- [ ] Resume property test: 100 consecutive random-kill runs, all byte-identical outcomes
- [ ] Corruption localization demo returns exact block indices
- [ ] Audit tamper detection: 100% on injected-mutation fuzzing

**Quality**
- [ ] CI green on both OS matrices; boundary contracts active
- [ ] mypy --strict green on domain/application/ports
- [ ] Changed-line coverage ≥90% core, adapters integration-tested
- [ ] pip-audit: no known HIGH/CRITICAL
- [ ] Throughput baseline recorded; regression gate armed (>10% fails)

**Honesty**
- [ ] Docs state every limitation (software-only WP check, no HPA, RAW-only, single-user)
- [ ] Selftest ships and passes on clean machines
- [ ] Exit codes + JSON schemas documented and contract-tested

**Safety**
- [ ] Source-vs-destination triple guard demonstrated in tests
- [ ] Device-node-as-destination refused (tested)
- [ ] All destructive ops confirmed/audited

---

## 12. Bridge to V1.5 / V2

V1's structure is deliberately the load-bearing frame for what follows:

| V2 capability | Already prepared by V1 |
|---|---|
| E01 support | `ImageWriter` port — new adapter, zero service changes |
| FS analysis/carving | New analysis service + TSK adapter behind existing ports pattern |
| REST daemon + GUI-ready API | Services return DTOs; Job table exists; SSE is additive |
| Examiner identities + signed custody | Audit events already carry actor IDs; signature field slots into chain payloads |
| CFReDS validation suite | Selftest harness + synthetic factory evolve directly into it |

Rule for the transition: nothing in V2 may require editing V1's domain rules or rewriting a
service — if it does, that's a V1 defect to fix before proceeding.

---

## Final note

V1's success metric isn't the feature count. It's this sentence being true at the end:

> *"We killed it mid-image, corrupted a byte, edited the database behind its back, and pulled the
> cable out — and it caught, proved, or survived every single thing we did to it."*
