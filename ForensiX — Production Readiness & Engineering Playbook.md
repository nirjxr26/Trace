# ForensiX — Production Readiness & Engineering Playbook

> Companion documents:
> - `ForensiX — Production Architecture & Brutal Gap Analysis.md` — what was wrong with the original brief
> - `ForensiX — System Design & Backend Architecture.md` — how it is built
> - **This document** — how we get from "a spec + empty repo" to a tool a forensic lab will sign off on,
>   and how we keep it maintainable for years.

This playbook is the operating system of the project: quality bars, phased roadmap, engineering
processes, compliance program, and operational discipline. It is written to be enforced — every
section ends in something checkable (a CI gate, a checklist, or a metric).

---

## Table of Contents

1. [Definition of Production-Grade](#1-definition-of-production-grade)
2. [Current State Assessment](#2-current-state-assessment)
3. [Roadmap: Phases 0–4 with Exit Criteria](#3-roadmap)
4. [Reliability Engineering Standards](#4-reliability-engineering)
5. [Code Quality & Maintainability System](#5-code-quality)
6. [Dependency & Supply-Chain Policy](#6-dependencies--supply-chain)
7. [Testing Program](#7-testing-program)
8. [CI/CD, Branching & Release Engineering](#8-cicd-branching--releases)
9. [Security Program](#9-security-program)
10. [Compliance & Legal Defensibility Program](#10-compliance--legal-defensibility)
11. [Data Governance: Encryption, Backup, Retention](#11-data-governance)
12. [Distribution, Installation & Operations](#12-distribution--operations)
13. [Documentation Set](#13-documentation-set)
14. [Feature Lifecycle Management](#14-feature-lifecycle-management)
15. [Incident & Defect Management](#15-incident--defect-management)
16. [Metrics That Matter](#16-metrics-that-matter)
17. [Risk Register](#17-risk-register)
18. [First 30 Days — Concrete Actions](#18-first-30-days)
19. [Appendix A–C: Checklists](#19-appendices-checklists)

---

## 1. Definition of Production-Grade

For a general SaaS, "production" means uptime dashboards. For forensic software, production means:

**ForensiX is production-grade when all of the following are true:**

1. **Admissibility bar met.** Output has survived validation against NIST CFReDS reference data with
   a documented, published error rate per release; methodology maps to ISO/IEC 27037/27042 and
   NIST SP 800-86 workflows.
2. **Fail-closed verified by test.** Every entry in the failure-handling matrix has an automated
   chaos test proving the behavior — not a code comment claiming it.
3. **Tamper-evidence proven.** An adversarial internal test (red team within the team) that edits
   DB rows and audit events is *detected* by `audit verify` every time.
4. **Reproducibility demonstrated.** Two clean machines, same image, same version ⇒ byte-identical
   report bodies and analysis findings; asserted in the validation suite.
5. **Operable by non-authors.** A lab tech who has never seen the codebase can install offline,
   run an acquisition end-to-end from the SOP, verify the audit chain, and produce a signed report
   using only shipped documentation.
6. **Maintainable long-term.** Strict typing green, architectural boundaries machine-enforced,
   ADRs current, no orphaned modules, dependency tree audited and SBOM-published.
7. **Supportable.** Versioned releases with signed artifacts, changelog, migration path, rollback
   procedure, and a known-issues register.

Anything less is a prototype wearing a production costume. The roadmap below is sequenced so each
phase produces something *usable* while ratcheting toward this definition.

---

## 2. Current State Assessment

| Area | Status today |
|---|---|
| Requirements | Strong gap-analysis exists (legal framing, failure matrix, domain additions) ✅ |
| Architecture decision | Hexagonal + DTO/job model decided ✅ (see Architecture doc) |
| Code | None yet — greenfield ⚠️ |
| Tooling/CI | Not established ⚠️ |
| Test corpora | None; synthetic-disk factory not built ⚠️ |
| Validation program | Not started (NIST CFReDS harness absent) ⚠️ |
| Docs/SOPs | Gap analysis only; user/admin/dev guides pending ⚠️ |

Conclusion: we are at Phase −1. The gap analysis already made the expensive mistakes cheap;
the fastest safe path is to stand up foundations (Phase 0) before any feature code, because
retrofitting CI/typing/boundaries onto working code is where projects rot.

---

## 3. Roadmap

Overview (each phase ends in something demoable and internally releasable):

| Phase | Name | Duration (team of 4) | Headline outcome |
|---|---|---|---|
| 0 | Foundations | 2 weeks | Repo, CI gates, boundaries, ADRs, synthetic-image factory |
| 1 | Core Loop MVP | 4–5 weeks | Case → acquire RAW → multi-hash → verify → audit trail, CLI-only |
| 2 | Trust Layer | 4 weeks | WP safety gate, piecewise hashing, tamper-evident audit, E01, selftest vs references |
| 3 | Lab Readiness | 5–6 weeks | RBAC, custody transfer, jobs+daemon+API, retention/disposal, PDF/A signed reports, encryption guidance |
| 4 | Hardening & Certification | 4 weeks | Chaos suite complete, validation report v1, perf benchmarks, packaging, DR drills, docs set |

### Phase 0 — Foundations (do NOT skip)

Deliverables:
- Monorepo skeleton per Architecture doc §4; `uv` env; Python 3.12 pinned.
- CI pipeline (GitHub Actions): ruff, mypy --strict (initially scoped, target full), pytest unit,
  import-linter contracts, pip-audit, secret scan. **All blocking from commit #1.**
- `docs/adr/0001-record-architecture-decisions.md` … seed ADRs for stack choices.
- `tools/gen_synthetic_disk.py` v0: deterministic FAT32 image with known content + expected hashes.
- Settings layer (TOML + env), structured logging config, exit-code contract module.
- Definition-of-Done template added to PR template.

Exit criteria: CI green on empty-but-real codebase; boundary violations impossible to merge;
synthetic disk generates byte-stable output across runs/machines.

### Phase 1 — Core Loop MVP

Scope: Case CRUD, evidence registration, device enumeration/fingerprinting (both OSes),
RAW acquisition with MD5+SHA-1+SHA-256, mandatory read-back verification, manifest.json,
append-only audit log (chain implemented now, signing in P2), basic `image status` progress.
SQLite persistence, Alembic baseline. In-process job runner (thread) with checkpoint/resume for
acquisition only.

Exit criteria: End-to-end demo — create case, image a loopback/VHD device, kill the process
mid-run, resume, verify, inspect audit chain. Unit+integration tests ≥ defined coverage policy
(§7). Failure-matrix rows for disconnect/ENOSPC/crash covered by chaos-lite tests.

### Phase 2 — Trust Layer

Scope: Independent write-blocker probe (fail closed), piecewise hashing, audit chain **signing +
anchoring + verify**, custody-transfer entity (pre-RBAC single-user form), E01 via pyewf adapter
with segmenting/compression, `selftest` command against bundled reference images + NIST CFReDS
manifests, cross-validation adapter (dc3dd/ewfacquire, optional).

Exit criteria: Red-team exercise #1 (tamper detection); selftest detects a deliberately corrupted
reference dataset; acquisition refuses to start when writability probe returns UNKNOWN without
audited override; E01 output opens correctly in third-party tools (Autopsy/The Sleuth Kit) —
interoperability proof.

### Phase 3 — Lab Readiness

Scope: Examiner identity + RBAC enforcement in service layer; custody transfers signed; retention
policies + disposal workflow (dual approval); FastAPI daemon topology B (DB-backed queue, SSE);
report generation (Jinja2→PDF/A-3b) with attestation + detached Ed25519 signature; at-rest
encryption guidance + optional envelope encryption for exports; backup/restore procedures.

Exit criteria: Two-examiner workflow demo (acquire → review → approve → report); API contract
snapshot tested; report regenerates byte-identical body from stored params; restore-from-backup
drill executed successfully once.

### Phase 4 — Hardening & Certification

Scope: Full chaos matrix automated; performance benchmark suite + regression gate; packaging
(Windows installer w/ driver notes, Linux deb/rpm/AppImage, Docker for daemon mode); air-gapped
install bundle; full documentation set (§13); **Validation Report v1.0** published (per-release);
DR drill #2 incl. case-DB loss scenario; support process live.

Exit criteria: §1 definition satisfied point-by-point; external pilot with one friendly lab or
internal forensics team using SOPs only; sign-off checklist (Appendix C) fully checked.

---

## 4. Reliability Engineering

Forensic operations are low-volume but ultra-high-consequence: one botched acquisition can destroy
evidence permanently. Reliability posture therefore favors **stopping over continuing**, and
**durability over speed**.

### 4.1 Durability rules

- Destination writes flushed (`flush` + `os.fsync`) at every checkpoint boundary and at finalize.
- We do **not** trust OS cache flush claims — the mandatory read-back verification pass is the
  actual durability proof. Document this rationale; never make verification optional.
- SQLite: WAL mode + `synchronous=FULL` for the case DB and audit DB. Postgres topology: default
  durable settings, no async-commit.
- Manifests are written atomically (temp file + fsync + rename).

### 4.2 Crash-only design

Every long-running operation assumes death at any instruction:
- All state transitions persist **before** side effects where possible; checkpoint format carries
  enough info to reconstruct intent (params hash, next offset, counters).
- No operation relies on in-memory-only state surviving.
- Startup always runs recovery sweep: find CRASHED/stale jobs, surface them to examiner, act only
  on explicit confirmation.

### 4.3 Idempotency & retries

- Device reads: bounded exponential backoff (3 attempts) for transient errors, then bad-region
  policy. Never infinite retry loops against failing hardware.
- Custody transfer/disposal/report generation accept idempotency keys; duplicates return the first
  result rather than creating second records.
- External-tool adapters (ewfacquire, tsk) have explicit timeouts + output capture into job log.

### 4.4 Resource guards (fail early, loudly)

Preflight checks before any destructive-or-long operation: free space ×1.05 estimate, destination
≠ source (byte-identity check of device fingerprints AND mount points), writable destination,
clock sanity, privilege level adequate. Each guard emits a typed error with remediation text.

### 4.5 Internal SLO-style targets

| Operation | Target | Measured by |
|---|---|---|
| RAW acquisition throughput (SSD→SSD) | ≥ 400 MB/s desktop class; ≥ disk-speed bound otherwise | bench suite |
| Verify pass throughput | ≥ 500 MB/s | bench suite |
| Audit verify (10⁶ events) | < 30 s | unit-perf test |
| Resume accuracy after crash | 100% (no lost/duplicated sectors ever — hard invariant, property-tested) | chaos + property tests |
| Report regeneration determinism | byte-identical body | validation suite |

Performance regressions >10% block release (bench gate). Speed matters here too: hours-long
imaging windows are risk windows.

---

## 5. Code Quality

### 5.1 Non-negotiables (CI-enforced)

| Gate | Tool | Policy |
|---|---|---|
| Formatting/lint | ruff | zero warnings; line length 100 |
| Types | mypy | `--strict` on `domain/`, `application/`, `ports/`; adapters may start `--strict-optional` and tighten per-module (tracked) |
| Boundaries | import-linter | contracts from Architecture §2; violation = failed build |
| Tests | pytest | changed-code coverage policy (below); no skipped tests merged to main |
| Deps | pip-audit | no known HIGH/CRITICAL vulns |
| Secrets | gitleaks pre-commit + CI | zero tolerance |
| Complexity | ruff (mccabe) + manual review | cyclomatic ≤10 per function; exceptions need ADR note |

Coverage policy: **changed-lines coverage ≥90% on domain/application; integration coverage required
for every port adapter.** We do not chase a global % number — we chase *untested diffs being
invisible*.

### 5.2 Writing rules (style of thought, not just style)

- Pure functions by default; I/O pushed to edges. If a function opens a file, question its design.
- Errors are typed exceptions with actionable messages; no bare `Exception`, no silent `except`.
- No comments explaining *what* (code says it); comments explain *why* — especially why a forensic
  constraint forces an unusual choice, linking the ADR or standard clause.
- Timestamps: UTC everywhere; conversion to local only at render edge.
- No magic numbers in forensic logic — chunk sizes, thresholds, retry counts come from validated
  settings with documented defaults.
- Public behavior (CLI text output aside) is contract: exit codes, JSON shapes, manifest schema get
  version fields and SemVer discipline.

### 5.3 Review standards

PR review checklist (Appendix A) includes forensic-specific items reviewers must actually verify:
fail-closed paths tested? audit event emitted for new mutating action? new state transitions added
to machine table? reproducibility affected?

Two approvals for changes under `domain/`, `adapters/imaging/`, `adapters/audit/`,
`adapters/devices/`. One approval elsewhere. Author never sole reviewer.

### 5.4 ADR practice

Any decision that is expensive to reverse gets `docs/adr/NNNN-title.md`: context, options,
decision, consequences. Triggers: new dependency, schema change affecting manifests/APIs, changing
hash/signature schemes, altering failure-matrix behavior, adding/removing a public command.
ADRs are immutable once accepted; superseded, never edited.

### 5.5 Ownership & hygiene

Module owners mapped to the 4-person split (Architecture §Part-10 analog). Monthly hygiene pass:
dead code removal (vulture report), TODO audit (every TODO needs issue link), deprecation sweep,
dependency drift review. Orphaned modules are deleted, not archived in-tree.

---

## 6. Dependencies & Supply Chain

Principle: **every dependency is attack surface and audit burden.** Forensic tools get cited in
court; "we didn't know what was inside it" is disqualifying.

Policy:
- Default answer is stdlib. Add a dependency only when it removes more risk than it adds.
- All deps pinned via lockfile (`uv.lock`); transitive pins included. Dependabot/Renovate PRs
  reviewed like feature PRs.
- Vet before adopting: license (permissive only), maintenance activity, wheel availability for
  Windows+Linux, whether it's plausibly court-defensible ("we used libewf, the standard library
  behind ewfacquire" is defensible; "some GitHub repo" is not).
- SBOM generated (CycloneDX) per release, published alongside artifacts.
- `pip-audit` blocks releases on known HIGH/CRITICAL; exception register documents accepted risks
  with expiry dates.
- Vendoring stance: none for crypto/hashing (use vetted libs); TSK/EWF binaries pinned by version
  and hash-checked at install.
- Release artifacts: sha256 checksums file + Ed25519 signatures by release key; installation docs
  teach verification.

---

## 7. Testing Program

Layered exactly as Architecture §19; this section defines the *program* around them.

### 7.1 Corpus strategy

The heart of forensic credibility is test data with **known truth**:
- `tools/gen_synthetic_disk.py` builds deterministic images (seeded RNG): partition tables,
  filesystems (FAT32/NTFS/ext4 targets), planted files, planted deleted files with known clusters,
  known MACb timestamps, embedded markers. Expected outputs computed analytically and stored as
  golden manifests.
- NIST CFReDS datasets downloaded once into `tests/validation/corpus/` (git-LFS or fetch script
  with recorded hashes — never committed raw).
- Every feature that parses/carves/recovers must ship with corpus cases covering success +
  adversarial inputs (truncated headers, cross-cluster chains, hostile filenames).

### 7.2 Gates

| When | What runs | Blocking? |
|---|---|---|
| Pre-commit | ruff, mypy (touched files), unit tests fast subset, gitleaks | yes (local) |
| Every push/PR | full unit + integration + contract + boundary contracts | yes |
| Nightly | property-based, chaos suite, tool-validation (CFReDS + synthetic), benchmarks | yes (breaks must be fixed same day) |
| Weekly | full benchmark regression vs stored baselines | report + gate on >10% |
| Release candidate | everything above + validation report generation + install smoke tests on clean Win/Linux VMs + upgrade-path test from previous release | yes |

### 7.3 Property-based focus areas (Hypothesis)

- Hash-chain verifier accepts valid chains, rejects every single-field mutation, insertion,
  deletion, reordering — exhaustively generated.
- Carver/parsers fed mutated corpus images; must never crash uncaught (fail = typed error),
  never produce findings contradicting golden truth.
- Checkpoint/resume: random kill points during simulated acquisition; final image byte-identical
  to uninterrupted run (modulo recorded bad regions). This is THE core integrity property.

### 7.4 Chaos scenarios (automated)

Map 1:1 to the failure matrix (Gap Analysis Part 6 / Architecture §16). Each scenario asserts both
the immediate behavior and the resulting audit/state records. New failure mode without a chaos test
= incomplete feature.

---

## 8. CI/CD, Branching & Releases

### 8.1 Branching

Trunk-based: short-lived feature branches → PR → squash-merge to `main`. `main` is always
releasable. Release branches `release/x.y` cut for stabilization; hotfixes cherry-picked.
Tags `vX.Y.Z` are the only source of release artifacts.

### 8.2 Pipeline stages (release.yml)

```
test (win+linux matrix) → build (sdist/wheel/binaries/docker) → sbom → sign (Ed25519 + checksums)
→ publish (PyPI private index / GitHub Releases) → smoke-install on clean VMs → tag announcement
```

Binaries via PyInstaller for labs that can't manage Python; Docker image for daemon topology.
All artifacts versioned together; a release is atomic (code + SBOM + validation report + checksums).

### 8.3 Versioning & migration discipline

- SemVer; breaking changes to CLI exit codes/output JSON/OpenAPI/manifest schema ⇒ major bump.
- Alembic migrations: forward-only, reviewed as production changes; destructive migrations require
  explicit backup step in the migration docstring and a release-note warning. Upgrade path tested
  from every supported prior minor in RC stage.
- Deprecation: announce one minor ahead, warn at runtime (`DeprecationWarning` surfaced in CLI),
  remove at next major. Never silent removals.

### 8.4 Changelog

Keep-a-Changelog format, maintained per PR (changelog entry required by PR template). Release notes
include: validation verdict summary, known issues, upgrade steps, checksums.

---

## 9. Security Program

| Activity | Cadence | Owner |
|---|---|---|
| Threat model review (STRIDE-lite over new surfaces) | per phase gate + per major feature | Backend owner |
| Dependency audit (pip-audit) | every build | CI |
| Secret scanning | pre-commit + CI | CI |
| Static security lint (bandit) | every build | CI |
| Internal red-team (tamper DB/audit/binary) | Phase 2 exit, then per major release | QA + Backend |
| Release signing & key ceremony | per release | Release manager |
| Vulnerability intake (SECURITY.md, coordinated disclosure, security.txt) | standing | Lead |

Rules baked into product:
- Least privilege: CLI requests elevation only when touching raw devices; daemon runs as dedicated
  low-privilege user with explicit ACLs on storage root.
- No telemetry. Diagnostics leave the machine ONLY as examiner-initiated export bundles.
- Logs exclude evidence content (offsets/IDs only) — reduces blast radius if logs leak.
- Crypto agility note: algorithms named in config with safe defaults; swapping SHA-256→SHA3 later
  is an ADR + migration, not a rewrite.

---

## 10. Compliance & Legal Defensibility

This is the program that turns ForensiX from "works" into "court-credible."

### 10.1 Standards mapping (maintained as living table in docs/compliance.md)

| Standard / clause area | ForensiX feature | Proof artifact |
|---|---|---|
| ISO/IEC 27037 — identification of media | device enumeration + fingerprinting | fingerprint record in manifest |
| ISO/IEC 27037 — acquisition integrity | fail-closed WP gate, dual hashing, read-back verify | WpVerification + VerificationReport |
| ISO/IEC 27042 — analysis interpretation | TSK-based analysis with recorded parameters | params snapshot per analysis job |
| NIST SP 800-86 — process integration | case→acquire→analyze→report workflow | SOP templates map step-for-step |
| Daubert — testability/error rate | validation suite vs CFReDS; measured false-negative rate per release | Validation Report vX.Y |
| Daubert — peer review/method publication | open architecture docs + published test methodology | repo docs |
| Daubert — known error rate | tracked metrics (§16) + chaos-proven failure behaviors | metrics dashboard export |
| Daubert — general acceptance | use of libewf/TSK industry standards; interop demos (opens in Autopsy) | interop test results |

### 10.2 Per-release Validation Report (template)

Generated automatically at RC: `{version, build_fingerprint, date}` → for each dataset
(synthetic + CFReDS variants): expected vs actual hashes/findings table, PASS/FAIL, measured error
counts, environment matrix, signer. Published beside artifacts. Labs attach it to their own
tool-validation SOPs.

### 10.3 Per-case defensibility bundle

Every case can emit `forensix case export-bundle CASE`: manifest(s), audit export + anchor,
report + attestation + signatures, tool version/config snapshot, validation report reference for
the exact build used. Goal: a reviewing expert can independently verify everything without
ForensiX installed (bundle contains verifier instructions + standalone chain-check script).

---

## 11. Data Governance

- Encryption at rest: primary guidance is OS-level (BitLocker/LUKS) with documented lab setup;
  optional app-level XChaCha20 envelope for exports/removable media. Keys via DPAPI/Secret Service
  or PKCS#11 tokens; key ceremony documented; rotation procedure documented; old keys retained for
  verification.
- Backups: case DB backup procedure (SQLite `VACUUM INTO` scheduled / pg_dump) with **restore
  drills quarterly** — an untested backup is Schrödinger's backup. Evidence images backed up per
  lab SOP (ForensiX verifies restored copies via existing verify pass).
- Retention/disposal: policies modeled in-product; disposal requires expiry + dual approval +
  witnessed audit record + disposal certificate (hash-logged). Deletion method documented
  (overwrite passes per lab standard).
- Access reviews: examiner list + role audit exported periodically for lab admin review.

---

## 12. Distribution & Operations

| Channel | Audience | Contents |
|---|---|---|
| Standalone binaries (Win installer / Linux AppImage+deb+rpm) | examiners' workstations | CLI + selftest; admin-required device access documented |
| Python package (private PyPI) | labs with Python practice | full CLI |
| Docker image | daemon/server topology | uvicorn + worker; storage mounted volume |
| Air-gap bundle | classified/offline labs | all above + wheels mirror + checksums + offline docs |

Ops requirements:
- `forensix doctor`: environment self-diagnosis (privileges, device visibility, keystore, clock,
  DB writability, dependency binaries present+hash-verified). First-run requirement in SOPs.
- `forensix version --verify`: binary/tool hash vs signed release manifest (detects workstation
  tampering).
- Upgrade runbook: backup → migrate → selftest → spot-verify old case (proves backward compat).
  Rollback runbook symmetric.
- Support tiers: bug (workaround + fix release), data-safety issue (**stop-ship**: immediate
  advisory + patch), questions (docs first). Known-issues register shipped with release notes.

---

## 13. Documentation Set

| Doc | Audience | Owner | Gate |
|---|---|---|---|
| Admin Guide (install, privileges, keys, backups, upgrades) | lab IT | Infra owner | Phase 4 |
| User Manual / SOP templates (acquire, analyze, report, custody) | examiners | Product lead | Phase 3 draft, 4 final |
| Compliance & Validation overview | lab QA/legal | QA owner | Phase 4 |
| Developer Guide (setup, boundaries, ADR index, test corpora) | contributors | All | Phase 0 skeleton |
| OpenAPI reference (generated) | integrators/GUI | auto | always |
| man-page/--help parity check | scriptability | QA | CI test asserting help completeness |
| Changelog + release notes | everyone | release manager | per release |

Docs are tested artifacts: SOP walkthrough scripts exist as CI smoke tests where possible
("documented command sequence runs green").

---

## 14. Feature Lifecycle Management

A feature is not "done when it merges." Lifecycle:

```
PROPOSAL (issue, problem statement, forensic justification)
  → triage: fits non-goals? (reject) → needs ADR?
SPIKE (if risky: time-boxed, findings posted)
SPEC (behavior + failure modes + validation plan + docs impact)
BUILD (tests-first for domain/application; chaos scenario drafted alongside)
VALIDATE (new corpus cases added; nightly-validation updated)
DOCS (manual + SOP touch points; help text; exit codes)
RELEASE (changelog; if visible behavior: SemVer assessment)
MONITOR (first real-use feedback → defect/insight backlog)
```

Governance rules:
- **Non-goals list is load-bearing.** Anything in Gap-Analysis Part 9 requires a leadership-level
  scope change, not an enthusiastic PR.
- Experimental features ship behind `forensix config experimental true` + `EXPERIMENTAL` marker in
  help; excluded from validation claims until graduated (validation report lists graduated features
  only).
- Deprecation per §8.3. Removal of any public command is a major release event with migration doc.
- Feature freeze windows during validation cycles (RC period): only stop-ship fixes.

---

## 15. Incident & Defect Management

Severity ladder (data-safety first):

| Sev | Definition | Response |
|---|---|---|
| S1 Data-safety | Any path that could corrupt evidence, break verification guarantees, or silently weaken fail-closed behavior | Stop-ship advisory, hotfix branch, out-of-band patch release, postmortem |
| S2 Correctness | Wrong findings/outputs without data destruction | Fix next patch; assess whether past outputs affected → notify users if yes |
| S3 Usability | Workflow friction, crashes with typed errors, no data risk | Next minor |
| S4 Polish | Cosmetic/docs | Backlog |

Postmortem template (blameless): timeline, root cause, why tests missed it, **which test/checklist
now prevents recurrence** (every postmortem must end in a concrete guardrail, or it doesn't close).

Known-issues register: shipped with each release; anything affecting evidentiary output MUST appear
there with workaround.

---

## 16. Metrics That Matter

Engineering health (reviewed monthly):
- Validation suite pass rate per release (target 100%; any FAIL = no release)
- Changed-line coverage on domain/application (≥90%)
- Boundary-contract violations merged (target: 0 ever)
- Mean time CI green after red (<half day)
- Dependency vuln debt (target: 0 HIGH/CRITICAL older than 14 days)
- Postmortem guardrail closure rate (100%)

Product/forensic KPIs (published per release):
- Acquisition throughput percentiles on reference hardware
- Bad-sector handling correctness rate on seeded-corruption corpus (target 100%)
- False-negative rate on CFReDS recovery tasks (tracked trend — the Daubert number)
- Audit-tamper detection rate in red-team rounds (must be 100%)
- Time-to-complete SOP walkthrough by non-author (usability proxy)

---

## 17. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Scope creep into mobile/cloud forensics | Med | High | Non-goals governance; ADR gate |
| pytsk3/pyewf binding fragility on some platforms | Med | High | Subprocess-fallback adapters; platform matrix in CI; pin versions |
| Team writes business logic in CLI out of habit | High | High | Boundary linter + review rule + bootstrap pattern shown early |
| Validation corpora stale vs new formats | Med | Med | Quarterly corpus refresh task; version datasets |
| Single-person knowledge silos (small team) | High | Med | Ownership rotation; ADR culture; pairing on critical modules |
| Performance chase corrupts safety (skipping fsync etc.) | Low | Critical | Safety-vs-speed decisions require ADR; chaos tests assert durability behaviors |
| Legal requirement shifts (jurisdiction-specific signing) | Med | Med | Attestation/signature abstraction ready; ADR seed #4 |
| SQLite limits hit in multi-user lab unexpectedly | Low | High | Topology C plan pre-built; Postgres adapter maintained from P3 |

---

## 18. First 30 Days

Week 1: Phase 0 kickoff — repo skeleton, CI gates live, ADR seeds written, synthetic-disk factory
v0, settings/logging/exit-codes modules.
Week 2: Domain models + state machines + audit chain math (pure code, 100% strict typing), unit
suite green; device-enumeration ports prototyped behind fakes.
Week 3: RAW acquisition engine against file-backed fake devices; checkpoint/resume implemented +
property test for kill/resume equivalence; real-device adapters (win/linux) integrated.
Week 4: End-to-end Phase 1 demo (case→acquire→kill→resume→verify→audit); failure-matrix rows for
disconnect/ENOSPC/crash chaos-tested; Phase 1 exit review against criteria; Phase 2 planning.

Standing rule: nothing merges that isn't typed, linted, boundary-clean, and tested — from day one.
Retrofitting rigor costs 3–5×; installing it first costs 1×.

---

## 19. Appendices: Checklists

### Appendix A — PR Review Checklist

- [ ] Boundary rule respected (no infra imports in domain/application; no logic in cli/api routers)
- [ ] Typed exceptions; fail-closed preserved on all new uncertainty paths
- [ ] Mutating action emits audit event (right actor, right subject)
- [ ] State transitions added to the machine table, not ad-hoc ifs
- [ ] UTC timestamps; naive datetime banned
- [ ] Tests-first for domain/application logic; adapter has integration test
- [ ] New failure mode has chaos-test or explicit ticket
- [ ] Reproducibility assessed (would two machines agree?)
- [ ] Docs/help/changelog touched; SemVer impact stated
- [ ] No secrets, no PII in logs, no evidence content in messages

### Appendix B — Release Checklist

- [ ] Full pipeline green incl. nightly suites rerun on RC commit
- [ ] Validation Report generated, reviewed, signed; attached to release
- [ ] SBOM + checksums + signatures published
- [ ] Clean-VM install smoke tests (Win/Linux) pass; `doctor` green
- [ ] Upgrade path from last supported release tested; migrations reviewed (no unbacked destructive)
- [ ] Known-issues register updated; stop-ship advisories clear
- [ ] Changelog complete; deprecations announced per policy
- [ ] Tag signed; release artifacts immutable

### Appendix C — Production Sign-off (Phase 4 Exit)

- [ ] §1 definition items 1–7 individually evidenced (links to artifacts)
- [ ] Red-team tamper round #2 completed: 100% detection
- [ ] DR drills passed (case-DB loss scenario + image-store restore)
- [ ] Pilot lab completed ≥1 real case end-to-end using SOPs only
- [ ] Support process staffed; severity ladder acknowledged by team
- [ ] Metrics dashboard live; baselines recorded
