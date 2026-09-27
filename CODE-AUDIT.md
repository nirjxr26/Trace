
# Trace — Full Codebase Audit

**Date:** 2026-09-27
**Scope:** every tracked file, line by line — `src/trace_core/**`, `src/trace_updater/**`, `release/*`, `install.sh`, `install.ps1`, `.github/workflows/*`, `pyproject.toml`, `tests/**`
**Codebase:** ~13 400 lines of production Python/shell/PowerShell + ~7 000 lines of tests, 152 Python files, 16 migrations, 4 renderer modules, 3 shell handlers, 2 installers
**Method:** 7 parallel deep-read audits (one file-group each) + direct line-level verification of every critical/high claim by the author. Read-only. **Nothing in the repository was modified.**

**Primary objective, in the user's words: _maximum code reusability_**, plus the smallest-possible logic/correctness defects, in service of production-grade maturity.

---

## How to read this document

| Section | Contents |
|---|---|
| §1 | Executive summary + severity counts |
| §2 | The 24 **critical** findings |
| §3 | The 78 **high** findings |
| §4 | The **medium** findings, grouped by module |
| §5 | The **low** findings, grouped by module |
| §6 | **THE REUSABILITY MATRIX** — the single consolidated list of every duplication found, ranked, with the proposed single source of truth for each |
| §7 | Dead / single-implementation / no-op code inventory |
| §8 | Test-suite audit: coverage matrix, tautologies, bugs encoded as expected behaviour, flakiness |
| §9 | Build / release / installer / CI audit |
| §10 | Architectural invariant scorecard against `AGENTS.md` §14 |
| §11 | Recommended remediation order |

Every finding carries `path:line`, the real quoted code, why it is wrong, and what it should be. Where a claim could not be settled from the source alone it is marked `[VERIFY]`.

---

## 1. Executive summary

### 1.1 Severity counts

| Severity | Count | What they cluster on |
|---|---:|---|
| **Critical** | 24 | False integrity claims, supply-chain trust collapse, data-loss on restore, timezone-wrong court timestamps, masked user errors |
| **High** | 79 | Trust gates that fail open, crash-safety holes, unbounded queries, invariant violations, silent error swallowing |
| **Medium** | ~180 | Duplication, dead abstractions, wrong error types, magic constants, type leakage, repeated boilerplate |
| **Low** | ~150 | Magic numbers, redundant imports, dead comments, naming drift |

**Revision note (2026-09-27, post-review).** The first pass did not read `docs/`. After cross-referencing all 44 files there — including a 127 KB prior deep audit of the same update pipeline — **15 of 28 tested update-pipeline findings proved genuinely new and 13 were already documented**. Three entries in §7.1 were withdrawn as false positives, one new high (H-79, a migration-number collision with the Subpart-3 plan) was added, and §3.3 now records the full prior-art map. **The count went up and the false-positive count went down**, which is the correct direction: seven of the new findings *contradict* an explicit prior verdict ("Correct. Noted.", "Noted as OK", "✅ FIXED"), which makes them stronger, not weaker.

### 1.2 The eight things that actually matter

1. **The CLI prints `"Signature: Verified"` before any signature is verified** (`updates/renderers.py:74` vs `updates/commands.py:133/147`). The manifest signature is *never* checked on the production install path, because the `preverified_sha256` fast path at `updates/lifecycle.py:221-231` verifies only the artifact. Both production call sites always pass `preverified_sha256`.

2. **The forensic-operation interlock is inert.** `ForensicOperationGate.can_install_update` returns `ALLOWED` whenever no probe is wired (`updates/gate.py:30-32`); `lifecycle.py:129` always constructs it with no probe; a probe is constructed **only in `tests/updates/test_phase_a_p0.py`**. A self-update will run in the middle of an active forensic acquisition, which is the exact thing `AGENTS.md` §14 exists to prevent.

3. **`audit/renderers.py` asserts `"Chain ✓ VALID"` on three code paths with zero verification** (`:78`, `:81`, `:117`). Every `audit show`, every `audit show --case`, and every case-dossier HISTORY block claims ledger integrity it has not checked. The TUI *does* verify (`tui/screens/audit.py:137`); the CLI does not.

4. **`format_utc_zulu` emits a wrong UTC timestamp on SQLite** (`core/ui/renderers.py:294-299`) — it has no naive guard, while its sibling `_to_ist` (`:262-266`) does. Because `DateTime(timezone=True)` is a no-op on SQLite, a value stored as `10:00:00Z` renders as `04:30:00Z` — a 5 h 30 m error in the field explicitly labelled UTC, printed next to the correct IST rendering, in both the case dossier and the audit dossier.

5. **Every domain invariant violation is masked as an internal fault.** `InvariantViolationError` extends `DomainError(ValueError)`, not `ApplicationError` (`core/domain.py:46,61`), and `core/cli/error_handler.py:100-143` has no branch for it or for `pydantic.ValidationError`. So a bad case number, an empty title, an over-long tag — the most common user errors in the product — render as *"An unexpected operational error occurred. Run with TRACE_DEBUG=1"*.

6. **`restore_backup` overwrites the live forensic database with `shutil.copy2` in place** (`updates/migration.py:160`) — no temp file, no fsync, no `os.replace`, and **no WAL checkpoint**, while WAL is force-enabled at `core/database/session.py:31`. A crash mid-copy corrupts the primary evidence database.

7. **Rollback compatibility is checked in the wrong direction.** `rollback_release` compares the live schema against the previous release's `schema_min` (`updates/migration.py:198-201`). The case that motivates rollback is `current > previous.schema_target`. `schema_target` *is* written into `release.json` (`updates/lifecycle.py:306`) and is **never read by any code**. The test suite encodes the wrong direction.

8. **The trust anchor is fetched unsigned from the channel it is meant to constrain.** `install.sh:622` pulls `trusted-keys.bundle` from `releases/latest/download` — unsigned, not in `SHA256SUMS`, not in any manifest — and writes its contents as the Ed25519 trust root. The burned-in key at `release/trusted-keys/53712e8bb8a774e6.pub` (whose id was verified correct) is never seeded.

### 1.3 The reuse verdict

The codebase has **no duplication problem in its architecture** — the layering is genuinely clean, the naming is disciplined, the comments explain *why*, and the docstring "Single source" convention is used widely and mostly honoured. The duplication is almost entirely **leaf-level**: the same 5–20 line utility re-implemented in 3–5 sibling modules, because the shared module already exists and the author reached past it.

Concretely: **~60 distinct duplicated blocks**, totalling **~1 100 lines** of code that could be deleted outright, touching **~190 call sites**. The single highest-value cluster is the four-layer renderer/theme split (§6.1) and the four-way duplication of every CLI/REPL/TUI surface (§6.2). Both are cases where the shared module exists, is documented as the single source, and is then bypassed.

The duplication is also **load-bearing for bugs**: `audit/verifier.py` has two verification implementations that disagree about which checks are performed, and the UI uses the weaker one (§6.4).

---

## 2. Critical findings (24)

Each was verified by the author against the source.

---

### C-01 · The manifest signature is never verified on the install path, and "Verified" is printed before any verification

`src/trace_core/updates/lifecycle.py:221-232`
```python
        if preverified_sha256 is not None:
            artifact = resolve_artifact(manifest, Path(artifact_path))
            if artifact.sha256 == preverified_sha256:
                try:
                    if sha256_file(artifact_path) == artifact.sha256:
                        from trace_core.updates.signing import verify_artifact_signature_file

                        verify_artifact_signature_file(artifact_path, artifact.signature, artifact.signing_key_id)
                        return
                except OSError:
                    pass
        verify_manifest(manifest, Path(artifact_path))
```

`verify_manifest` (`updates/verifier.py:59-61`) is `verify_manifest_signature(m) + verify_artifact(...)`. The fast path returns after the *artifact* half only, so **`verify_manifest_signature(manifest)` is skipped**. Both production call sites always pass `preverified_sha256`:
- `updates/commands.py:154` — `UpdateLifecycle(str(uuid.uuid4())).run(m, artifact_path, channel=channel, allow_minimum_bypass=bypass_minimum, preverified_sha256=entry.sha256)`
- `tui/screens/settings.py:503` — same, plus `progress=`

So the release manifest's own Ed25519 signature is **never checked in production**. Anyone able to substitute a manifest (but not forge a signature) is constrained by nothing inside the manifest — including `schema_min`, `schema_target`, `backup_required`, and `minimum_supported_version`, all of which gate migrations and policy.

Compounding, `updates/renderers.py:68-74`:
```python
def render_install_summary(manifest: ReleaseManifest, current: str, bypass_note: str) -> None:
    console.print("")
    console.print("Update available")
    ...
    console.print("Signature: Verified")
```
`render_install_summary` takes no verification result and cannot know one. Call order in `updates/commands.py`: `render_install_summary(...)` at **:133**, `verify_manifest(m, artifact_path)` at **:147**. The operator is told the signature verified 14 lines before it is checked, and `load_update` (`commands.py:30-45`) does not verify at all — so on that path the string is never anything but fiction.

**Fix:** delete the fast path entirely and call `verify_manifest(manifest, Path(artifact_path))` unconditionally (it is one extra SHA-256 of a file already in page cache, plus the Ed25519 check — the "fast path" saves nothing measurable). Delete the `"Signature: Verified"` line, or pass a real result in.

---

### C-02 · The forensic-operation interlock is inert — a self-update runs mid-acquisition

`src/trace_core/updates/gate.py:30-32`
```python
    def can_install_update(self, context: UpdateGateContext | None = None) -> GateDecision:
        if self._probe is None:
            return GateDecision.ALLOWED
```

Verified by grep — `ForensicOperationGate(` is constructed at:
```
src/trace_core/updates/lifecycle.py:129:        gate = gate or ForensicOperationGate()
tests/updates/test_phase_a_p0.py:21:    gate = ForensicOperationGate(active_probe=_probe)
tests/updates/test_phase_a_p0.py:40:    gate = ForensicOperationGate(_boom)
```
**Only tests supply a probe.** Production always constructs the default, so `decision` is always `ALLOWED` (`lifecycle.py:345`) and `forensic_active` is always `False` (`lifecycle.py:344/350`). Consequently `policy.py:40-41`'s `if forensic_active: return False, "forensic operation active"` is **unreachable**, and the whole 41-line `gate.py` + `UpdateGateContext` + `ActiveProbe` type alias is an abstraction with zero production wiring. The class docstring (`gate.py:22`) documents the hole rather than closing it.

**Second, independent defect in the same function** — `gate.py:37-41`:
```python
        if result is True:
            return GateDecision.ACTIVE_OPERATION
        if result is None:
            return GateDecision.UNKNOWN
        return GateDecision.ALLOWED
```
A probe returning the **int** `1` (e.g. `return len(open_handles)`) satisfies neither branch and falls to `ALLOWED`. Only a literal `None` or a raised exception yields the safe verdict. And `except Exception: return GateDecision.UNKNOWN` at `:35-36` has **no logging at all** on the single most security-relevant hook in the update path, so the operator gets `lifecycle.py:348`'s `UpdateError("unknown forensic-operation state; failing closed")` with no cause.

---

### C-03 · `"Chain ✓ VALID"` printed with zero verification — on three paths, in the crown-jewel module

`src/trace_core/audit/renderers.py:78, :81, :117`
```python
console.print(f"[dim]Chain: ✓ VALID — {len(events)} events[/dim]\n")
console.print(f"[dim]Chain: ✓ VALID — SHA-256 — {len(events)} events — {ts}[/dim]\n")
console.print(Text("  Chain ✓ VALID", style=TOK["success"]))
```

`render_audit_table` (`:38`) has only a list of DTOs. `render_case_audit_header` (`:100`) has only `case_number/title/status/events`. **Not one line of verification runs.** Every `audit show`, every `audit show --case X`, and every case-dossier HISTORY block asserts ledger integrity it has not checked.

The contrast is the finding: the **TUI** does verify (`tui/screens/audit.py:137 intact = verify_event(...)`, `tui/screens/cases.py:160-168` up to 6 events), and the **CLI** does not. A forensic product that verifies in one UI and asserts in the other.

Related, in the same file:
- `audit/renderers.py:345` — the compliance report says `"Checked": "payload_hash (SHA256 canonical) + chain_hash (prev-hash-seq) recomputed from payload_json"`. The verifier *also* checks `prev_chain` linkage (`verifier.py:105-106`) **and the signature** (`verifier.py:110-113`). The screen shown to an auditor **under-reports two of four** checks.
- `audit/renderers.py:336` — `("Chain", "trace-audit-v1 — SHA-256 — trace-canonical-json-v1")` hard-codes the three values of `SPEC_VERSION`/`HASH_ALGO`/`CANONICAL_VERSION` (`audit/domain.py:16-18`) as literals. Bump the spec and the compliance screen lies about which spec the ledger conforms to.
- `audit/verifier.py` has **two** verification implementations with different semantics — `verify_event` (`:64-87`, payload+chain+signature) and `_row_mismatch` (`:101-114`, payload+**prev_chain**+chain+signature). The UI verdict **omits the `prev_chain` linkage check** — the exact field an attacker rewrites when splicing. See §6.4.

---

### C-04 · `format_utc_zulu` emits a court-facing UTC timestamp that is wrong by 5 h 30 m

`src/trace_core/core/ui/renderers.py:294-299`
```python
def format_utc_zulu(ts: Any) -> str:
    """UTC Zulu string for court-facing timestamps."""
    try:
        return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return str(ts)
```

Compare its sibling 32 lines above, `:262-266`:
```python
def _to_ist(dt: datetime) -> datetime:
    """Normalize any datetime to IST, assuming UTC when naive."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(IST)
```

`format_utc_zulu` has **no naive guard**. Root cause: `DateTime(timezone=True)` is a no-op on SQLite — SQLAlchemy's SQLite `DATETIME` result processor returns a **naive** `datetime`, and `.timestamp()` on such a value is off by the local offset. Python's `naive.astimezone(UTC)` interprets the naive value as **local** time.

**Empirically reproduced in this environment (author's probe against the repo's own SQLAlchemy 2.0.52):**

```
roundtrip tzinfo: None
format_utc_zulu   -> 2026-09-27T04:30:00Z     # 5h30m WRONG
correct (guarded) -> 2026-09-27T10:00:00Z
```

This value is displayed at:
- `cases/renderers.py:146, :197, :236` — all three as `f"{format_india_datetime(x)} ({format_utc_zulu(x)})"`, i.e. **next to the correct IST rendering**
- `audit/renderers.py:226, :311`

A forensic timestamp wrong by a timezone offset, in the field explicitly labelled UTC, in the case dossier and the audit dossier, is the most serious correctness defect in the codebase.

**Fix (one line):** `return _to_ist(ts).astimezone(UTC).strftime(...)` — i.e. route through the existing naive guard. See §6.5 for the related `is_naive(dt)` extraction that would have prevented this divergence.

---

### C-05 · Every domain invariant violation is masked as an internal fault

`src/trace_core/core/domain.py:46, 61`
```python
class DomainError(ValueError):
    """Base exception for all domain-level rule violations."""
    pass
...
class InvariantViolationError(DomainError):
```

`src/trace_core/core/cli/error_handler.py:9-16, 100-143` — the typed ladder imports and handles exactly six application types plus the update family:
```python
from trace_core.core.errors import (
    ApplicationError, AuditTamperError, ConcurrencyConflictError,
    ConflictError, NotFoundError, StateTransitionError,
)
...
    if isinstance(e, ApplicationError):
        return operation_title or "Application Error", str(e), default_remediation, EXIT_ERROR
    return _resolve_unexpected_error(e, operation_title, default_remediation)
```

**No branch for `DomainError`, `InvariantViolationError`, `EntityNotFoundError`, or `pydantic.ValidationError`.** Verified: `error_handler.py` imports nothing from `core.domain`, and grep finds no `except` clause anywhere in the repo catching `DomainError` or its subclasses.

Therefore `_resolve_unexpected_error` (`:25-29`) replaces every message with
`"An unexpected operational error occurred. Run with TRACE_DEBUG=1 or inspect system logs for technical details."`

`cases/domain.py` raises `InvariantViolationError` 12+ times with carefully written, user-facing messages:
```
"Case number must match YYYY-CODE-XXXX (e.g. 2026-CR-0001)."
"Case {name} is strictly immutable once assigned."
"tag exceeds maximum length of 50 characters."
"too many tags (max 50)."
```
All of them are hidden. Same for every `CaseCreateDto(...)` construction failure inside a `with capture_cli_errors(...)` block, and for `audit/commands.py`'s own validation path. **User-input failures are indistinguishable from bugs.** This is the single highest-impact consistency defect in the product and the fix is 3 lines.

Related in the same file:
- `cases/service.py:144` — `raise ApplicationError(f"Database constraint violation: {e}") from e`. `ApplicationError` is returned **unmasked** at `error_handler.py:142`, so schema names, column names, constraint names and DBAPI values are printed regardless of `TRACE_DEBUG`. The `debug` gate only guards the *unexpected* branch. This is the exact inverse of C-05 in the same 90 lines.
- `audit/commands.py:63` — `limit: int = typer.Option(50, "--limit", help="Max rows (1..500)")` with **no** `min=1, max=500` (contrast `updates/commands.py:83` which does it correctly). `audit show --limit 999999` reaches pydantic → C-05 → masked.

---

### C-06 · `restore_backup` overwrites the live forensic database in place, ignoring WAL

`src/trace_core/updates/migration.py:156-163`
```python
    if url.startswith("sqlite") and ":memory:" not in url:
        live = Path(url.split("sqlite:///", 1)[1].split("?", 1)[0])
        if manager._engine is not None:
            manager._engine.dispose()
        shutil.copy2(src, live)
        manager._engine = None
        manager._session_factory = None
        return
```

Three compounding problems:

1. **No atomicity.** `shutil.copy2` is truncate-and-rewrite in place. No temp file, no fsync, no `os.replace`. A crash or a full disk mid-copy leaves a **corrupt primary evidence database** — the single worst failure mode this tool has. Every other write in the codebase goes through `atomic_write_lines` (`core/fs.py:47-62`); this is the only in-place overwrite of a critical file.

2. **WAL sidecars are ignored.** `core/database/session.py:31` force-enables `PRAGMA journal_mode=WAL`, and `manager._engine.dispose()` neither checkpoints nor removes `-wal`/`-shm`. Replacing only the main file leaves stale WAL frames that SQLite replays over the restored file — resurrecting post-backup rows or corrupting the database.

3. **The layer is bypassed.** `migration.py:146, 158, 161-162` reaches into `manager._url`, `manager._engine` and **assigns** `manager._engine = None` / `manager._session_factory = None`. `DatabaseSessionManager` has no API for this, and there is no lock, so any concurrent thread holding a `Session` bound to the disposed engine fails mid-query.

The PostgreSQL branch (`:164-185`) has the same missing-rollback shape: `psql -f -` restores into a database the session manager may hold pooled connections to, with no `pg_terminate_backend`, no advisory lock, and no `update_lock`. It will block on table locks or deadlock.

**Untested.** `rg "restore_backup" tests` → **0 hits**. The entire disaster-recovery restore path — the highest-consequence code in the update pipeline — has no test.

---

### C-07 · Rollback compatibility is checked in the wrong direction; `schema_target` is never read

`src/trace_core/updates/migration.py:195-204`
```python
    meta = updater_mod.read_release_meta(base, previous)
    if meta is None:
        raise RecoveryError(f"previous release {previous} carries no compatibility metadata")
    schema_min = meta.get("schema_min")
    if schema_min is not None and current_schema_version(manager) < schema_min:
        if backup_path is None:
            raise RecoveryError(f"previous release {previous} requires schema >= {schema_min}; no backup recorded")
        restore_backup(backup_path, manager)
```

`release.json` **does** carry `schema_target` — written at `updates/lifecycle.py:306`:
```python
            release_meta={
                "version": manifest.version,
                "release_id": manifest.release_id,
                "schema_min": manifest.schema_min,
                "schema_target": manifest.schema_target,
            },
```
Verified by grep: **`schema_target` is read by nothing on the rollback path.** The forward path checks *both* bounds (`migration.py:101-104`: rejects `current < schema_min` **and** `current > schema_target`). The rollback path checks only `schema_min`.

The case that motivates a rollback is the opposite: the update **advanced** the schema past what the previous release supports, i.e. `current > previous.schema_target`. As written, rolling back to an older, schema-incompatible release proceeds with a **forward-migrated database and no restore** — precisely the failure the restore exists to prevent.

**The test suite encodes the bug.** `tests/updates/test_migration_race.py:88-103` exercises only the `schema_min` branch, and `tests/updates/test_migration_race.py:72-85` is a second `pytest.raises(RecoveryError)` with **no `match=`** — and `rollback_release` raises `RecoveryError` from four distinct sites (`migration.py:194, 197, 201, 213`). The two tests are **mutually indistinguishable**: swap the `release_meta` kwarg between them and both still pass.

---

### C-08 · The trust anchor is fetched unsigned from the channel it is meant to constrain

`install.sh:619-641`
```sh
TRUST_DIR="${HOME}/.trace/trust/releases"
if mkdir -p "$TRUST_DIR" 2>/dev/null; then
    BUNDLE_FILE="$(mktemp)"
    if trace_run_live 83 curl --proto "$CURL_PROTO" --proto-redir "$CURL_PROTO" -fsSL -o "$BUNDLE_FILE" "https://github.com/nirjxr26/Trace/releases/latest/download/trusted-keys.bundle"; then
        while IFS=' ' read -r _fp _hex _rest; do
            ...
            printf '%s' "$_hex" > "$TRUST_DIR/${_fp}.pub"
        done < "$BUNDLE_FILE"
```

`releases/latest/download/trusted-keys.bundle` is served from the **same GitHub Releases channel** that serves `stable.json` and the wheel. The bundle is **not signed**, **not** covered by `SHA256SUMS`, and **not** referenced by any manifest. Full chain:

> unsigned bundle (GitHub) → arbitrary Ed25519 pubkeys → self-signed manifest → wheel

Whoever controls the release channel chooses the trust root. The repo *does* burn in exactly one key — `release/trusted-keys/53712e8bb8a774e6.pub`, whose id was verified correct (`sha256(bytes.fromhex(...))[:16] == "53712e8bb8a774e6"`) — but **the installer never seeds it**. That burned-in anchor is reachable only from `release/verify_release.py:38` (CI-side).

Also in this block:
- 18 lines of hand-rolled shape checking that **never** assert `_fp == key_id_for_pubkey(bytes.fromhex(_hex))`. The application already has that helper (`updates/signing.py:9-12`) and a length-validating import path (`signing.py:93-102`).
- `printf '%s' "$_hex" > "$TRUST_DIR/${_fp}.pub"` writes with the process umask (typically 0644) and is not atomic — four lines away from `updates/signing.py:107`'s deliberate `atomic_write_lines(path, [raw_pub.hex()], mode=0o600)`.

**The trust anchor is updateable by the thing it is supposed to constrain.**

---

### C-09 · The pip subprocess inherits the full ambient environment

`src/trace_core/updates/pip_backend.py:40, 47`
```python
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
...
    proc = _run_quiet([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], _PIP_TIMEOUT_SECONDS)
```

No `env=` is passed, so pip reads `PIP_INDEX_URL`, `PIP_EXTRA_INDEX_URL`, `PIP_FIND_LINKS`, `PIP_TRUSTED_HOST`, `PIP_CERT`, and `PIP_CONFIG_FILE` from the process environment. Two concrete attacks:

- `PIP_INDEX_URL=http://attacker/` sends the wheel request to a plaintext mirror and `--trusted-host` silences the warning. Because the command has **no `--require-hashes` and no `--no-index`**, pip does not re-verify the wheel's hash — so the carefully computed `artifact.sha256` (`manifest.py:13`) protects **nothing** on this path.
- `PIP_CERT` / `SSL_CERT_FILE` swap the CA bundle.

This is precisely the "env var that disables a security control" class `AGENTS.md` §5 forbids. The sibling in `updates/migration.py:171, 242` *does* build an explicit `env` — the convention exists in the codebase and was not applied here. Fix: pass a scrubbed `env`, or `--isolated`.

Compounding, `pip_backend.py:51`:
```python
        tail = (proc.stderr or proc.stdout or "").strip()[-2000:]
```
pip's stderr routinely contains the resolved index URL. If `PIP_INDEX_URL` embeds credentials, they land in the exception string, which `error_handler.py:91` prints to the console **and** `lifecycle.py:172, 200` persists into `update_history.failure_reason` (`models.py:28`) — i.e. **into the database, permanently**.

---

### C-10 · The rollback path pip-installs a retained wheel with no signature verification

`src/trace_core/updates/pip_backend.py:85-99`
```python
def restore_release(base: str | Path, version: str) -> bool:
    ...
    candidates = sorted((Path(base) / "releases" / version).glob("*.whl"))
    if not candidates:
        return False
    if len(candidates) > 1:
        raise UpdateError(f"ambiguous previous wheels for {version}; refusing to guess")
    python = venv_python()
    if python is None:
        return False
    pip_install_wheel(python, candidates[0])
    return True
```

The wheel is read straight from `~/.trace/install/releases/<prev>/` and handed to pip. Never hashed, never compared to a retained manifest, never signature-checked. Compare the forward path, which verifies three times (`commands.py:147`, `lifecycle.py:371`, `lifecycle.py:275`). **A rollback is exactly when an operator is least able to notice.** `updater.py:194` shows the wheel arrived via `shutil.copytree`, so the on-disk copy is mutable after the fact.

Also `pip_backend.py:91` — `version` is joined into a path with **no `check_contained`**, in the one module whose stated job is path safety. `updater.py` calls it on *every* path it builds (lines 100, 102, 186, 189, 250, 266). `version` comes from the `previous-version` pointer file. Constrained today by the manifest regex (`manifest.py:25`, no `/`), so latent rather than live.

And the return value is **discarded** at `migration.py:210-211`:
```python
    try:
        pip_backend.restore_release(base, previous)
```
`restore_release` returns `bool` ("True if attempted") — a `False` (no wheel staged, frozen layout, no venv) is indistinguishable from a successful reinstall, so the code proceeds to flip the pointer having installed nothing. Only tests read the return value.

---

### C-11 · `atomic_write_lines` uses a fixed temp filename — concurrent writers publish a truncated file

`src/trace_core/core/fs.py:50-61`
```python
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.unlink(missing_ok=True)  # unlink removes a planted symlink itself; never follows it
    with open(tmp, "x", encoding=encoding, newline=newline) as handle:  # noqa: PTH123
        for line in lines:
            handle.write(line)
        handle.flush()
        ...
    os.chmod(tmp, mode)
    os.replace(tmp, target)
```

Interleaving two processes A and B on the same target:
1. A: `unlink(tmp)`; A: `open(tmp,"x")` → creates inode **I₁**, holds fd.
2. B: `unlink(tmp)` → **unlinks I₁ from the directory** (A's fd stays valid on POSIX, but the directory entry is gone).
3. B: `open(tmp,"x")` → creates inode **I₂**.
4. A: writes to I₁ (now orphaned). A: `os.replace(tmp, target)` → `tmp` names **I₂**, so **A publishes B's partially-written file as `target`**.
5. B: `os.replace(tmp, target)` → `tmp` no longer exists → `FileNotFoundError`.

`target` can be a truncated JSON, and the docstring's "never partial" claim is false under concurrency. `atomic_write_lines` has 10 call sites including forensic export and ledger paths. Fix: `tempfile.mkstemp(dir=target.parent, prefix=target.name)` — one line, keeps the symlink and atomicity properties.

The symlink defence in the comment is correct and worth keeping; it is the *uniqueness* of the temp name that is missing.

---

### C-12 · The `preverified_sha256` fast path skips three of four verification checks

Covered in C-01 for the manifest signature. The additional omissions, `lifecycle.py:221-231` vs `updates/verifier.py:20-35`:
```python
def verify_artifact(path: Path, artifact: ManifestArtifact) -> None:
    assert_safe_filename(artifact.filename)
    if path.name != artifact.filename:
        raise UpdateVerificationError(f"filename mismatch: ...")
    verify_artifact_content(path, artifact)
```
The fast path skips `assert_safe_filename`, the `path.name != artifact.filename` check, and the `size != artifact.size` check. It is an 11-line hand-rolled partial re-implementation of an existing one-call helper. Also `except OSError: pass` at `:230-231` is pointless — the fallthrough to `verify_manifest` re-reads and re-hashes the same file and raises the same `OSError`, so the only effect is a duplicated full-file hash of a file that may be 10 GiB.

---

### C-13 · `UpdateFailureStage.from_state` is called *after* the state has already been set to `FAILED`

`src/trace_core/updates/lifecycle.py:162-171` (and verbatim again at `:187-199`)
```python
                if can_transition(self.state, UpdateState.FAILED):
                    self.transition(UpdateState.FAILED)
                try:
                    self.service.record_history(
                        UpdateHistoryCreateDto(
                            ...
                            failure_stage=UpdateFailureStage.from_state(self.state),
```

`self.state` is now `UpdateState.FAILED`. `from_state` (`updates/domain.py:83-92`) has no branch for `FAILED`, so it hits the fallback `return str(state).lower()` → `"failed"`. **Verified empirically.** So every generically-recorded failure in `update_history.failure_stage` is the literal string `"failed"`, and the UI's `_FAILED_STAGE` map (`updates/renderers.py:36-41`) has no `"failed"` key, so the stage row is silently omitted.

Consequences:
- All nine branches of `from_state` and its fallback are **unreachable in production**; the only two correct call sites are the literal `UpdateFailureStage.STAGING` at `lifecycle.py:279-292` and `UpdateFailureStage.POLICY` at `:361`.
- `UpdateFailureStage.MIGRATION` (`domain.py:81`) is **never produced by any writer** — a `run_updater_migration` failure is filed as `"failed"`, not `"migration"`. A migration-checksum failure is indistinguishable from a health-probe failure in the ledger.
- Three different ways of computing the same field in one file (`from_state(...)` at `:171`/`:199`, literal at `:279` and `:361`).

Fix: `stage = UpdateFailureStage.from_state(self.state)` on the line **above** `self.transition(...)`.

---

### C-14 · A half-migrated database is silently completed on the next startup

`src/trace_core/updates/migration.py:311-332`
```python
    backup_path = ... if needs_backup else None
    mutated = True
    try:
        apply_migrations(self.service.session_manager, current, manifest.schema_target)
        ...
    except Exception:
        ...
        finish_update_migration(transaction_id)      # ← removes the active-update marker
        raise
```

Two defects:

1. **`mutated = True` is set *before* `apply_migrations` is called**, so the handler's guard `if backup_path is not None and not mutated` (`:326`) never fires for a migration failure. The backup file survives but its path is recorded **nowhere** — not in `update_history`, not in the marker. `prune_retention` (`updater.py:219-226`) then deletes it as one of `keep_backups=3` files with no transaction association.

2. **`apply_migrations` commits one migration per transaction** (`migrations.py:441-457`), so a failure at migration *k* leaves 1..k applied and k+1 absent. `finish_update_migration(transaction_id)` **removes the active-update marker**, so `DatabaseSessionManager.ensure_ready()` (`session.py:94-117`) proceeds normally on the next startup and completes the half-migration with no operator involvement. Direct violation of the crash-safety contract: *a half-applied update must always be detectable and resumable*.

---

### C-15 · A crash after `stage_release` makes an update permanently un-completable

`src/trace_core/updates/lifecycle.py:297-308` → `trace_updater/updater.py` `stage_release`, which raises
`FileExistsError(f"release {version} already staged; releases are immutable")` if the release dir already exists.

Combined with the fact that `UpdateLifecycle.load()` (`lifecycle.py:96-109`) is **dead and broken** (see H-04), a crash between `stage_release` (`:389`) and `activate` (`:455`) leaves the update permanently un-completable: every retry hits the same `FileExistsError`, and there is no `resume()`.

---

### C-16 · Every non-terminal marker write omits the recovery-critical fields

`src/trace_core/updates/lifecycle.py:25-35`
```python
        write_marker({"transaction_id": self.transaction_id, "state": str(to)})
```

The result marker written by every `transition()` carries **only** `{transaction_id, state}` — no `backup_path`, no `release_id`, no migration range. `core/cli/recovery.py:95` reads `marker.get("backup_path")`, which is therefore **always `None`** for every marker the lifecycle itself writes. Recovery after a failed update rolls back with **no DB restore**, and `rollback_release` then raises `RecoveryError("... no backup recorded")` whenever the previous release needs a schema bump. The full record is only written on the COMPLETED path (`:476-490`) — which is why the only `write_marker` with a complete payload is the success one.

---

### C-17 · `marker.write_marker` lets the caller override the enforced schema version

`src/trace_core/updates/marker.py:28`
```python
    record = {"marker_schema": MARKER_SCHEMA, **data}
```

The caller's dict is **second**, so a caller-supplied `marker_schema` overrides the enforced value. `write_marker({..., "marker_schema": 99})` succeeds, and `read_marker` then rejects it as "unsupported marker schema 99".

The sibling module does it correctly — `staging.py:32`: `record = {**record, "staged_schema": 1}`. **Two modules performing the identical operation with opposite merge order**, and the wrong one is the forensic result marker.

---

### C-18 · A corrupt forensic result marker is indistinguishable from an absent one

`src/trace_core/updates/service.py:63-73`
```python
        try:
            return read_marker(target)
        except RecoveryError:
            return None
```

`marker.py:32-49` raises `RecoveryError` for three *materially different* conditions: missing file (`:37`), corrupt/unreadable (`:38-41`), and wrong schema / missing fields (`:45, :48`). The service collapses all three to `None`. A truncated `update-result.json` — a plausible outcome of the C-11 race — is reported as a clean install, and the operator gets no recovery prompt. `lifecycle.load` (`:102`) calls `read_marker()` directly and *does* surface the error, so the two entry points disagree.

---

### C-19 · The entire disaster-recovery restore path has no test

`rg "restore_backup" tests` → **0 hits.** Untested: the SQLite `shutil.copy2` + engine/session-factory reset (`migration.py:156-163`), the PostgreSQL `psql` subprocess with `PGPASSWORD` (`:164-185`), the `O_NOFOLLOW` symlink-swap re-resolve (`:149-155`), and `_confine_backup_path`'s widened two-root containment (`:111-116`).

`tests/updates/test_migration_race.py:165-173 test_sqlite_backup_roundtrip` tests the *backup* direction only.

Compounding, `migration.py:149-155` — the comment claims *"Re-resolve after existence check to close symlink-swap TOCTOU"* but the code opens the path with `O_NOFOLLOW`, **closes the fd immediately**, then hands the *path* to `shutil.copy2`, which re-resolves it. The check validates a path that is never used. And `getattr(os, "O_NOFOLLOW", 0)` is `0` on Windows — **the guard is a literal no-op on the platform it was written on**.

Also `migration.py:157` — `url.split("sqlite:///", 1)[1]` raises a bare **`IndexError`** for `sqlite+pysqlite://` or `sqlite://`, escaping a recovery path as a non-`UpdateError`. The identical two-step split is duplicated at `migrations.py:418-419`; neither handles a `+driver` scheme.

---

### C-20 · `prune_retention` deletes backups, and is itself untested

`src/trace_updater/updater.py:219-226` (`keep_backups=3`, called unconditionally from `lifecycle.py:457`). `rg "prune_retention" tests` → **0 hits**, yet it calls `stale.unlink()`. It prunes by mtime, so a slow update or a clock skew can delete the *current* backup.

The naming defect that makes this unrecoverable is `migration.py:225, 236`:
```python
    dest = backups_dir / "trace-backup.db"      # ← fixed literal
```
Every update overwrites the previous backup in a shared `backups/` directory, so `keep_backups=3` can never retain more than **one** SQLite backup, and a rollback to release *n-2* cannot find its backup. `transaction_id` is in scope at `migration.py:264` and is not used in the filename. The history row written at `lifecycle.py:466` stores a path that is **guaranteed to be overwritten by the next update**.

---

### C-21 · The TUI runs Ed25519 signature verification on the event loop, on every arrow keypress

`src/trace_core/tui/screens/cases.py:256-260` → `_render_dossier` (`:141`) → `_dossier_events` (`:227`, a DB read) → `_append_integrity` (`:149`) → up to 6 × `verify_event(..., signature=e.signature, key_id=e.key_id)` (`:160-168`).

`verify_event` recomputes a SHA-256 over canonical payload JSON **and** verifies an Ed25519 signature. Holding `↓` re-runs 6 signature verifications per row, synchronously, on the UI thread. The `_event_cache` (`:50`) helps only the *ledger* half — the *crypto* half is never cached. Same defect at `tui/screens/audit.py:137-145`, which is additionally **unguarded** (no `try/except`, unlike its twin at `cases.py:170-173`).

---

### C-22 · `_require_db` and `fetch_db_snapshot` perform 4 connections and 3 redundant round-trips

`src/trace_core/core/database/health.py:39-41`
```python
        names = get_table_names(manager.engine)
        applied = get_applied_migrations(manager.engine)
        pending = get_pending_migrations(manager.engine)
```
`get_pending_migrations` internally calls `get_applied_migrations(engine)` again (`migrations.py:392`), and each of those calls `ensure_migration_table` — which issues a `checkfirst` create probe **and** a `BEGIN`/`_ensure_column` block (`migrations.py:353-354`). So a getter performs **DDL**. This runs on every `trace db status`, `trace doctor`, TUI settings refresh, and `_require_db()`.

`verify_migration_checksums` (`migrations.py:314-339`) also **writes** to the database. So `trace db status` — a diagnostic — creates and `ALTER`s tables. That matters for the least-privilege `trace_app` role that migration 011 exists to create.

---

### C-23 · First-ever-admin election is not atomic

`src/trace_core/core/operators.py:83-84`
```python
        first_ever = session.scalar(select(OperatorModel.id).limit(1)) is None
```

Unlocked `SELECT`; the subsequent `INSERT` is protected only by `UniqueConstraint("name", "host")` (`:51`). Two different OS identities starting simultaneously — or on two workstations against a fresh DB — both observe an empty table, both insert, both get `ROLE_ADMIN`, and the `IntegrityError` handler (`:90-95`) does not fire because the tuples differ. Given `AGENTS.md` §5 ("bind permissions to OS identity … raises the bar from anonymous self-assertion to workstation accountability"), two concurrent admins is the exact failure this module exists to prevent. Needs a DB-level guarantee.

---

### C-24 · A plaintext unencrypted copy of the entire ledger is written to disk before encryption

`src/trace_core/audit/helpers.py:49-55`
```python
    tmp = Path(out).with_suffix(Path(out).suffix + ".plain-tmp")
    try:
        do_export(svc, str(tmp))
        sealed = encrypt_bytes(tmp.read_bytes(), passphrase)
```

The **complete unencrypted ledger** is written to disk next to the destination first. The `finally: tmp.unlink(missing_ok=True)` only cleans up on a clean unwind — a `kill -9`, a power loss, or a container stop between `:51` and `:55` leaves a full plaintext JSONL evidence bundle on disk indefinitely, at a path the user never named. The whole file is also read into memory and re-buffered by `encrypt_bytes`, so peak RAM is ~2× the ledger.

Compounding, `core/fs.py:47-62` has **no `try/finally` around the write**, and `audit/exporter.py:65-70` passes a **generator** so the `SELECT` executes lazily *during* the write. Any DB error mid-stream propagates out of `atomic_write_lines` leaving `out_path + ".tmp"` — a partial, unencrypted, real-evidence file — permanently on disk. The docstring's "never partial" claim is contradicted.

---

## 3. High findings (79)

### 3.1 Update pipeline — trust, security, crash-safety

| # | Finding | Location |
|---|---|---|
| H-01 | `manifest.filename` has **no pattern**, and `"."` passes `assert_safe_filename` — so a signed-but-malformed manifest steers the client to fetch an arbitrary same-host path. `sha256` right above it gets a strict anchored regex; `filename` gets nothing. | `updates/manifest.py:11-14`, `updates/verifier.py:9-11` |
| H-02 | `manifest_signature` / `signing_key_id` are unconstrained strings; `bytes.fromhex` runs on them. | `updates/manifest.py:32-33` |
| H-03 | `updates/trust.py:19-26` has **no key-id grammar validation** — only `check_contained`. The sibling `audit/signing.py:165-176` validates grammar first and says why. A crafted `ed25519:../../x` must never become a path. | `updates/trust.py:19-26` |
| H-04 | `UpdateLifecycle.load()` is **dead and broken** — it restores state from the marker, but `_run_locked` unconditionally does `transition(CHECKING)` at `:338` and `_ALLOWED` has no `-> CHECKING` edge from any state except `IDLE`. If wired it would raise `illegal update transition DOWNLOADING -> CHECKING` for every non-IDLE state. Crash resumability is **advertised but not implemented**. | `updates/lifecycle.py:96-109, 338`, `updates/domain.py:25-46` |
| H-05 | The install path **ignores the channel encoded in the manifest URL**. `checker.py:47-49` does `source_for(target)` (which discards the URL's channel) then `.fetch(channel)` rebuilds `{base}/{channel}.json`. So `trace update install --manifest https://host/beta.json` on a stable install fetches `https://host/stable.json`. The sibling path at `checker.py:136-138` gets it right. | `updates/checker.py:47-49` vs `:136-138`, `updates/sources.py:224-228` |
| H-06 | `checker.py:79-81` re-hashes the artifact in full, then calls `verify_artifact` which re-stats the size, re-hashes, and re-checks the signature. Three lines of fully redundant pre-verification over a file that can be 10 GiB. | `updates/checker.py:79-81` |
| H-07 | `verify_artifact_signature_file` **slurps up to 10 GiB into RAM** (`MAX_ARTIFACT_BYTES = 10_737_418_240`) with the docstring *"Streams… never holds full bytes in RAM"* two files over. Signature is `path: object` + `str(path)` + `_Path` — a signature never designed. OOM-kill on the happy path. | `updates/signing.py:76-85` vs `updates/sources.py:150` |
| H-08 | `revoke_release_key` writes the revocation marker non-atomically and with no permission control — **4 lines below** a sibling that uses `atomic_write_lines(..., mode=0o600)`. Trust material is 0600 on import and umask-default on revoke. | `updates/signing.py:111-115` vs `:106-107` |
| H-09 | `revoke_release_key("ed25519:")` → `root/"revoked"/""` collapses to `root/"revoked"`, `mkdir(exist_ok=True)` succeeds, then `write_text` writes a **file where a directory is** → every subsequent `revoked_path(key_id).exists()` returns `False`, **silently un-revoking every key**. | `updates/trust.py:34` + `updates/signing.py:111-115` |
| H-10 | A partial temp file is left on disk on every size-cap network failure, and the next run reuses that exact path. Unbounded disk growth across retries, no GC. | `updates/sources.py:142-177`, `:215-216` |
| H-11 | A security refusal (non-HTTPS manifest URL) is raised as `UpdateNetworkError`, which `error_handler.py:68-73` renders as *"Check network connectivity and manifest URL, then retry"* — telling the operator to look in the wrong place and inviting them to reach for `http://` again. | `updates/sources.py:66-74` |
| H-12 | CDN redirect allowlist is a bare `endswith(".githubusercontent.com")` — accepts **any** host under that suffix, not just the release-asset CDN. | `updates/sources.py:157`, `:53-55` |
| H-13 | A rollback never updates `previous-version`, and `recovery.py:92` handles `FAILED/ROLLING_BACK/RECOVERY_REQUIRED` but **not `ROLLED_BACK`** — so after a successful in-run rollback `trace recovery` reports "No recovery needed", and if re-run would roll back a second time to the same version. | `updates/lifecycle.py:437`, `core/cli/recovery.py:92` |
| H-14 | `_assert_verified_stage` records a FAILED history row then raises `UpdateVerificationError` (not `UpdatePolicyBlockedError`), so `run()`'s generic handler writes a **second** FAILED row for the same `transaction_id`. | `updates/lifecycle.py:276-292` vs `:165` |
| H-15 | If `activate()` succeeds but `_verify_activation` raises, the pointer **is** flipped and the DB **is** migrated, yet `run()` transitions `HEALTH_CHECK -> FAILED` and performs **no rollback**. Half-applied state, `failure_stage="failed"`, and no code path reconciles it. | `updates/lifecycle.py:455-456` |
| H-16 | The state `HEALTH_CHECK` is durable from `lifecycle.py:401` onward, but `recovery.py:92` does not handle it — so a crash at 405-455 makes `trace recovery` print "No recovery needed — up to date" over a genuinely half-applied update. | `updates/lifecycle.py:401-455`, `core/cli/recovery.py:92` |
| H-17 | `finish_update_migration` is called on the **success** of the migration, i.e. the "update in progress" marker is deleted **before** health check, activation, retention prune, history write and result-marker write. For that whole window only `update_lock` protects the update. | `updates/migration.py:333` |
| H-18 | `lifecycle.py:81` requires `after != manifest.schema_target` (exact equality) for health, while `migration.py:315` only requires `after >= schema_target`. If the local migration registry is ahead of the manifest — a normal state after the tool is patched — the update is judged unhealthy and **spuriously rolled back**. | `updates/lifecycle.py:81` vs `updates/migration.py:315` |
| H-19 | `except Exception: schema_before = None` / `except Exception: schema_after = schema_before` swallow a genuine DB error and substitute a value known to be wrong, which then fails the H-18 check and **triggers a rollback of a perfectly healthy update**. | `updates/lifecycle.py:375-379, 405-409` |
| H-20 | `"actual_sha256": artifact.sha256` writes the manifest's **expected** hash into a field named *actual*, before any measurement. `staging.py:53` then compares `actual_sha256 != expected_sha256` — a value against itself. | `updates/lifecycle.py:270`, `updates/staging.py:53` |
| H-21 | `fs.py:16-25 check_contained` is **vacuous when the root itself is a symlink**: both sides are `resolve()`d, so `base` *is* the symlink target. It can never fire for a symlinked root — and `trust_root()` is the highest-value target in the product. | `core/fs.py:16-25` |
| H-22 | `UpdateHistoryCreateDto.result` defaults to `"SUCCESS"`. Any caller that constructs a partial DTO and forgets `result` persists a **successful update that never happened**, on the one table that is the update audit trail. `from_version`/`to_version` are required for exactly this reason. | `updates/dto.py:15` |
| H-23 | `if manifest.minimum_supported_version:` and `manifest.py:28` declares it `str \| None = None` with **no `min_length=1`**, so `"minimum_supported_version": ""` is schema-valid and, being falsy, **skips the whole minimum-version control**. A signed-but-malformed manifest is a config-equivalent bypass. | `updates/policy.py:44`, `updates/manifest.py:28` |
| H-24 | `UpdateHistoryCreateDto.channel`'s validator raises `UpdateVerificationError` for a **caller input** error, which `error_handler.py:57-61` renders as *"Update Verification Failed — Update rejected, verification failed. Installation not performed."* An operator who mistypes a channel is told their release failed signature verification. The `errors.py:21` docstring ("Distinct from trust failures for UX routing") exists to prevent exactly this. | `updates/policy.py:38-39` |
| H-25 | `lifecycle.run()` is annotated `-> UpdateHistoryCreateDto` but **every** return path returns the unrelated `UpdateHistoryDto` from `service.record_history`. Two `extra="forbid"` `BaseDto` subclasses, so the annotation is false and both call sites are typed wrongly. | `updates/lifecycle.py:122, 436, 454` |
| H-26 | `UpdateHistoryModel.transaction_id: String(36)` with no DTO-side length validation. On SQLite a longer value truncates silently, producing two history rows sharing a 36-char prefix. | `updates/models.py:20`, `updates/service.py:18` |
| H-27 | The *unpinned* path streams a remote archive straight into `tar` with no temp file and no verification; the result is then `pip install --no-deps -e .` — i.e. **remote code imported and executed**. The pinned path correctly does mktemp → sha256 → cosign → extract. | `install.sh:486-492, 598` |
| H-28 | The **one unhashed, unpinned download in the whole install**: `pip install --quiet "pip==26.2.1"`, no `--require-hashes`, no `--only-binary`, and it runs *first*, upgrading the component that installs everything else. | `install.sh:596`, `install.ps1:581` |
| H-29 | `${TRACE_REINSTALL:+--reinstall} ${VERBOSE:+--verbose}` expands whenever the variable is **set and non-null**, not truthy. `TRACE_REINSTALL=0` and `VERBOSE=0` are both non-empty, so picking a release from the interactive list **always** passes `--reinstall`, which runs `rm -rf "${HOME}/.trace/app"` and `rm -rf "$REPO_ROOT/.venv"` with no confirmation. `install.ps1:309-316` gets this right. | `install.sh:300, 12, 15, 502-520` |
| H-30 | No rollback in either installer. The app dir and venv are destroyed *before* the new copy is proven installable; `trace_fail` only prints and exits 1. A failed `pip install` leaves the user with **no `trace` at all**. | `install.sh:502-520, 596-598`; `install.ps1:470-493` |
| H-31 | The `TRACE_RELEASE_SHA256` / `TRACE_COSIGN_*` verification block lives only in the archive branch, so it is **unreachable whenever `git` exists** — i.e. every developer box and most CI images. Setting the pin is silently a no-op. | `install.sh:441-454 vs 455-493`; `install.ps1:437-454` |
| H-32 | cosign verification is **skipped silently** when the tool is absent: `[ -n "${TRACE_COSIGN_BUNDLE_URL:-}" ] && command -v cosign >/dev/null 2>&1`. No message. Fails open on a missing verifier. | `install.sh:476`; `install.ps1:444` |
| H-33 | `install.ps1:194-201` — the trust-bundle download **always "fails" on an interactive console** and is masked as "offline". `Start-Job` spawns a fresh process where `$LASTEXITCODE` is `$null` until a *native* command runs; `Invoke-WebRequest` is a cmdlet, so `$null -ne 0` → `throw`. **On every interactive Windows install the trust store is never provisioned.** The sibling function at `:171-175` handles `$null` correctly, proving the asymmetry. | `install.ps1:194-201` vs `:171-175, 622` |
| H-34 | The documented install path is `irm …/main/install.ps1 \| iex` and `curl …/main/install.sh \| sh`. Mutable `main` ref, no checksum, no signature, and the script then clones + `pip install`s. | `README.md:105, 110` |
| H-35 | The hand-rolled argv parser in `make_manifest.py` treats any unrecognised token as a **positional**, so `make_manifest.py v1.2.3 stable r1 --min-version` writes the manifest to a file literally named `--min-version` in the repo root. `argparse` is stdlib and handles this in 3 lines; this is 31. | `release/make_manifest.py:12-42` |

### 3.2 Audit module, cases, core, TUI, tests

| # | Finding | Location |
|---|---|---|
| H-36 | `AuditEvent` (21 lines, `frozen=True`, `alias="chain_hash"` + a `chain_hash` property that exists solely to undo the alias) is **constructed in exactly one place** — `_model_to_domain` — **which nothing calls**. Every read path returns `AuditEventDto`. A dead entity in the crown-jewel module, whose 13 fields are a third copy of the schema. | `audit/domain.py:55-75`; `audit/repository.py:37-38` |
| H-37 | `VerifyResultDto` has **no `last_chain` field**, so `anchor.py:96` must read the chain from `audit_chain_state` — the **unprotected, unsigned, unchained** head row. The anchor's `last_seq` check is real; the `last_chain` check is decorative. | `audit/dto.py:58-71`, `audit/anchor.py:96` |
| H-38 | `write_anchor` is **never called**, writes an anchor with **no `key_id` and no `signature`**, and `check_anchor_match` **skips** signature verification for the unsigned variant: `if res.is_valid and data.get("signature") and data.get("key_id")`. **An anchor file with the signature fields stripped verifies successfully** — a live fail-open check, not just dead code. | `audit/anchor.py:21-32, 77-83` |
| H-39 | `AuditChainStateModel` — the chain's own tip — has **no integrity protection of any kind**: no signature, no hash, no append-only trigger, no immutability. It is the sole serialisation point and the sole source for `head()`, which is what users are shown as "the ledger tip". | `audit/models.py:13-20`, `audit/repository.py:114-144` |
| H-40 | `AnchorIntentModel` has no unique constraint on `(case_number, seq)`, and `record_anchor_intent` adds unconditionally — a retried close produces duplicate rows and `publish_pending_anchors` writes the same anchor file once per row. | `audit/models.py:28-43`, `audit/anchor.py:100-109` |
| H-41 | `sign_bytes` is called at `anchor.py:162`, **outside** the `try` at `:165`. It raises when a key is selected but unreadable, which escapes `_publish_one`, so the handler at `:235` skips `session.commit()` — meaning `attempt_count += 1` and `last_attempt_at` are **rolled back**, and the `_FAILED_RETRY_COOLDOWN_HOURS` backoff is gated on a *persisted* `last_attempt_at`. A missing keystore therefore re-attempts the full write on every close, forever, and the cooldown never engages. | `audit/anchor.py:162, 165, 235` |
| H-42 | `export_bundle` streams every row **without** invoking `verify_rows`, and the header is **unsigned**, while anchors *are* signed. An operator can export a ledger that `audit verify` would reject and receive a file that looks like evidence; the bundle's `last_seq`/`last_chain` carry no signature, so a bundle header can be edited to match a truncated body. The mitigating comment describes a comparison **no reader in this codebase performs**, and `bundle.verify()` does not exist. | `audit/exporter.py:61-70, 22-37` |
| H-43 | `_is_ledger_missing` string-matches four table-name substrings, while `core/operators.py:67-68` implements a 2-line subset of the same check. Two implementations of "is the schema missing", one more thorough, neither shared. | `audit/service.py:21-34`, `core/operators.py:67-68` |
| H-44 | The PostgreSQL branch of `_missing_table` **can never fire**. The installed driver is **psycopg 3.3.5** (verified; `psycopg2` absent), whose exception objects expose `.sqlstate`, **not** `.pgcode`. Confirmed: `hasattr(psycopg.errors.UndefinedTable('x'), 'pgcode')` is `False`. So the friendly *"Operator store not initialized"* message is **unreachable on PostgreSQL**, and a missing table raises a raw `ProgrammingError` → C-05 masked card. | `core/operators.py:67-68` |
| H-45 | A failing `post_commit` hook propagates **after** the transaction is durably committed, so the CLI reports failure for work that succeeded. For a forensic app this is the dangerous direction: the user retries and **double-applies a mutation**. The invariant is currently safe *only by accident* — the sole production hook wraps its own body in `try/except`. | `core/service.py:57-61` |
| H-46 | `HASH_ALGO = "SHA-256"` is written into every ledger payload, but `payload_hash` and `chain_hash` both hardcode `hashlib.sha256`. Change `HASH_ALGO` to `"SHA-512"` and every newly written row would **claim** SHA-512 while being SHA-256. | `audit/domain.py:18, 43, 52, 97` |
| H-47 | The anchor's *own* Ed25519 signature verification is never negatively tested. One test passes a dict with **no** `signature`/`key_id` so the branch is skipped; another tampers `last_seq`, tripping an earlier branch. The anchor-forgery defence has positive coverage only. | `audit/anchor.py:77-83` |
| H-48 | `audit/verifier.py` has two verification implementations with **different semantics** — `verify_event` omits the `prev_chain` linkage check that `_row_mismatch` performs. The TUI verdict therefore omits the exact field an attacker rewrites when splicing. See §6.4. | `audit/verifier.py:64-87, 101-114` |
| H-49 | Hash fields are constrained by length only — no hex charset, no case normalisation. A stored uppercase hash fails the `!=` comparisons (reported as tampering) while `verify_bytes` uses case-sensitive `hmac.compare_digest`. Two comparison disciplines for one column family. | `audit/domain.py:65-67`, `audit/verifier.py:107-108`, `audit/signing.py:54` |
| H-50 | `" -" in argv_cmd` is a substring test over the whole command line, so a user-supplied `--reason "evidence held - in situ"` flips the branch and writes the **full argv including all flag values** into the immutable `details.command`. The stored value is a function of user text, not of the invocation. | `audit/builder.py:21-29` |
| H-51 | `init_key` writes `priv_path`, then `pub_path`, then the pointer, with no fsync and no atomicity. A crash after `:126` leaves an orphaned private key and **no pointer** — so `active_key_id()` returns `HMAC_KEY_ID` and the app **keeps signing the forensic ledger under HMAC** while a half-created Ed25519 key sits in the keystore, shown as `retired`. | `audit/signing.py:119-130, 80-81` |
| H-52 | `open(path, "a+b")` **follows symlinks** — a planted symlink at a `.migratelock` or update-lock path creates the lock at the symlink target, outside the intended directory. This directly contradicts `atomic_write_lines`'s explicit "Never follows symlinks" contract. The module has two opposite symlink policies and only one is documented. | `core/fs.py:47, 103, 125` |
| H-53 | `require_mutator(...)` **returns the `OperatorModel`** and every call site throws it away. The ledger's `actor` is computed from a DTO field the user typed. In the edit and restore paths **no actor is passed at all**, so `CASE_UPDATED`/`CASE_RESTORED` are permanently attributed to the case's stored `lead_examiner`, not the OS operator. `OperatorModel.public_key` exists and is never populated or used. | `cases/service.py:97, 173, 233`, `core/operators.py:118-120` |
| H-54 | `CaseRepository.purge()` hard-deletes with **no archive-first precondition**; the guard lives only at the service layer. `CaseRepository.delete(entity_id, purge=True)` routes straight to it. `AGENTS.md` §14 names this an architectural invariant, but any future repository caller bypasses it. | `cases/repository.py:220-240`, `cases/service.py:303-306` |
| H-55 | `transition_case(...)` internally applies `strip_controls(reason)`, but `for_case_closed(..., reason)` is handed the **raw, unstripped, control-character-bearing** value. The case row is sanitised and its own audit record is not. The only thing preventing terminal-escape injection into the ledger is `sanitize_terminal` at render time. | `cases/service.py:245, 258` |
| H-56 | `if len(manifest.artifacts) == 1: return next(iter(...))` means a single-artifact manifest installs on **any** platform, skipping platform/arch match entirely. Correct today; when frozen per-OS bundles land, a Windows manifest with one Windows artifact installs on Linux. The invariant is documented in `release/make_manifest.py:52-56`, ~800 lines and one package away. | `updates/policy.py:80-81` |
| H-57 | The migration integrity check hashes the **Python source text** of the migration function. Any edit — including a comment or a reformat — hard-fails every deployed install with no bypass flag and no escape hatch. `getsource` also raises for a frozen/zipapp build (caught at `:296`, `source = ""`), producing a *different* digest and the same brick. A checksum should cover schema state, not source formatting. | `migrations.py:283-304, 338` |
| H-58 | Migration 011 has **no exception handling and no verifier**, unlike neighbours 006/007/008. It executes `CREATE ROLE trace_app NOLOGIN` (needs `CREATEROLE`). On a managed PostgreSQL this raises, `apply_migrations` propagates, and because every migration is in its own `engine.begin()` migrations 1-10 stay applied while **12-16 never run and never will** → `ensure_ready()` fails on every startup and `trace db migrate` is permanently impossible. **This makes Trace uninstallable on any non-superuser PostgreSQL.** | `migrations.py:511-524, 441-457` |
| H-59 | `_sqlite_lock_path` — `sqlite+pysqlite:///trace.db` falls to the `else` branch and sets `path` to the **entire URL string**, then `abspath(path) + ".migratelock"`. On Windows the `:` is illegal in a filename → `OSError` before any migration runs. On POSIX it creates a junk lockfile in CWD and **the concurrency serialisation silently stops existing.** | `migrations.py:412-422` |
| H-60 | Sequence allocation sits **outside** the `try` that handles DB errors, so `IntegrityError` from the savepoint insert and SQLite's `OperationalError("database is locked")` both escape unmasked. Sequence allocation is a normal, expected contention path. | `cases/repository.py:100, 267, 300` |
| H-61 | `for _ in range(10000)` allows `last_sequence` to reach 10000, producing a 5-digit number which `CASE_NUMBER_RE` rejects. **The 10 000th case of any year always fails** with the wrong error, and the counter is already advanced. | `cases/repository.py:298, 301` |
| H-62 | `status=CaseStatus(model.status)` raises a bare `ValueError` on any status string not in the enum. A row written by a newer version makes **every** `case list`/`case show` fail with the masked card. `parse_enum_value` exists to return `None` instead and is used for every *filter* path but not here. | `cases/repository.py:57`, `core/domain.py:36` |
| H-63 | **No guard against running against a non-empty or foreign database.** A typo'd `TRACE_DATABASE_URL` results in 6 tables created and 11 ALTERs applied, with no prompt — while every *case* mutation requires typing the case number to confirm. Schema writes unguarded, record writes guarded. | `migrations.py:434-459` |
| H-64 | No contiguity or ordering validation. Deleting a migration silently forks history: an existing DB keeps the row, a fresh DB never applies it, and the two schemas diverge with no error on either. `verify_migration_checksums` will not catch it. | `migrations.py:441-457` |
| H-65 | `_render_detail` paints "Checking…" then immediately makes the blocking `cached_check` call with no `await`, no worker, and no `call_after_refresh` between them, so the text is never composited. The cold-cache path does **network I/O on the event loop**, freezing the whole app. `self._checking` is a lie. | `tui/screens/settings.py:452-453, 196` |
| H-66 | Opening (and every re-render of) the Diagnostics section **writes and deletes a file in the evidence storage root** on the event loop, on mount, on every section change, on `action_check`, and on `refresh_data`. | `tui/screens/settings.py:374-375`; `core/cli/doctor.py:30-44` |
| H-67 | The TUI opens a raw DB session and calls a repository-level function, bypassing the application service, where Typer and REPL go through the documented `describe_anchor` single source. The TUI re-implements a **partial** version: it drops the off-host reminder and prints `Anchor: UNKNOWN.` where the CLI prints `Anchor state: PENDING (attempts=2) — copy off-host once confirmed.` | `tui/screens/cases.py:369-376`; `audit/anchor.py:112-121` |
| H-68 | The palette router special-cases only the `tab-` prefix, so **3 of 15 commands can never work**: `case-close` (builds `action_close`; the method is `action_seal`), `audit-export` and `audit-anchor` (compared against bare `"export"`/`"anchor"`). `settings.py:552-559` deliberately accepts both forms — only the Settings view got prefix-tolerant dispatch. | `tui/app.py:152-166`, `tui/palette.py:24, 29-30` |
| H-69 | `tui/theme.py` claims *"Single source: core/ui/theme"* then hardcodes 9 of the 10 colours it needs, re-typing the exact hex of nine `THEME_TOKENS` entries. A change to `core/ui/theme.py` silently fails to reach the TUI. | `tui/theme.py:10-19` |
| H-70 | Two visible colour divergences from that copy: `panel="#1E2328"` vs `THEME_TOKENS["border"] = "#1D1F21"` (the CSS border and the `─` rule *inside the same pane* are two different greys), and `DOT_OK = "#5FD18A"` vs `THEME_TOKENS["success"] = "#63D391"` (the *same* "Database Online" fact rendered in two greens). | `tui/theme.py:19, 53`; `core/ui/theme.py:6, 15, 48` |
| H-71 | A FAILED update stage is rendered with the **success** label — twice. `updates/renderers.py:164-169` returns `STAGE_DONE_LABEL[stage]` as the `FAILED` fallback, and `tui/theme.py:79-87` does the same, fed by `settings.py:255-261` which also uses `STAGE_DONE_LABEL` for `FAILED`. The operator sees **`✕ Health check passed`** in red, on the failure path of every install. There is no `STAGE_FAILED_LABEL` in `stages.py:23-35`. | `updates/renderers.py:164-169`, `tui/theme.py:79-87`, `tui/screens/settings.py:255-261` |
| H-72 | Unverified manifest fields (`notes`, `version`, `block_reason`) are written with `console.print` on a plain `str`, which **interprets Rich markup**, with no `sanitize_terminal` and no escaping. `notes` is fully attacker-controlled for anyone who can serve the manifest URL — and the module's own comment says "TLS is transport-only and Ed25519 is trust". The remedy is used everywhere else, including on case data. The TUI *does* call it; the CLI is the outlier. | `updates/renderers.py:45-47, 53, 58, 64, 71-73, 96, 147, 158, 160` |
| H-73 | The private key is written with `NoEncryption()` and protected only by `os.chmod(0o600)` and a `0o700` parent. **On Windows `os.chmod` only toggles the read-only bit; it does not restrict ACLs**, so a default-profile NTFS key file is readable by other local users, while the module docstring states "private keys live in the filesystem keystore (0600 dir)". CI runs `windows-latest` and the permission tests are `if sys.platform != "win32"`-guarded, so this is unverified on the dev platform. | `audit/signing.py:119-125`; `core/fs.py:8-13` |
| H-74 | **Reading a role writes to the database.** `require_role` → `current_operator` → `get_or_provision` → `session.add(row) + flush()`. The Settings tab calls `current_operator(session).role` purely to *display* it, and that INSERTs. Worse, a **denied** first-ever action rolls the provisioning row back, so the operator identity of a rejected attempt is not retained. | `core/operators.py:99-110`; `tui/screens/settings.py:341` |
| H-75 | The no-telemetry / no-network **security guard uses relative paths**. Run pytest from anywhere but the repo root and it passes **vacuously**. | `tests/updates/test_no_telemetry.py:8` |
| H-76 | The integration test falls back to `os.environ.get("TRACE_DATABASE_URL")`. A developer with a production URL in their shell who runs `pytest` will have `test_postgres_integration_lifecycle` **create, close, archive and permanently purge** cases there, and the append-only test will attempt `DELETE FROM audit_events`. | `tests/integration/test_postgres.py:22` |
| H-77 | The only test exercising the **real** `trace update install` path (real venv, real `pip install`, real wheel repacking, real rollback restoring the previous wheel) is **gitignored** and skips silently when its env var is unset. The unit test monkeypatches `pip_install_wheel` with a no-op, so the real pip path has **zero** CI coverage. | `.gitignore:11`; `tests/updates/test_update_e2e_local.py` |
| H-78 | `temp_storage_root` sets `storage_root = tmp_path`, but production derives `install_root()` and `trust_root()` from `storage_root.parent` — which under pytest is **shared by every test in the session**. CI uses the *relative* `TRACE_STORAGE_ROOT: "./.test_storage"`, so `install_root()` becomes `./install` and `trust_root()` becomes `./trust/releases` — **inside the checked-out tree**. Confirmed on disk: `D:\Projects\trace\trust\releases\` exists, and `.test_storage/anchors/anchor-2026-CLI-0001-3.json` is the fingerprint of `test_cli_commands.py:70`. CI writes anchors, signing keys, the update lock and the check cache into the repository on every run. | `tests/conftest.py:94-100`; `core/database/session.py:31`; `trace_updater/updater.py:31`; `updates/trust.py:14` |
| **H-79** | **`docs/subparts/subpart-3.md` plans migration `014_create_device_fingerprints` — version 014 is already `014_create_update_history`.** Because `register_migration` has no uniqueness check (§4.2) and `apply_migrations` sorts by version, two version-14 entries means the second's verifier silently replaces the first's and **only one ever runs**; the other is recorded in `schema_migrations` and never executes. Subpart-3 §4.9 says "Pattern-copy migration `013`" and §3 repeats `migrations/014` at line 119, so the collision is stated twice. The plan must be renumbered to **017**, and `register_migration` must gain the duplicate-version guard *first* — otherwise building Subpart-3 bricks `trace db migrate` for every deployed install. | `docs/subparts/subpart-3.md:119, 174, 416`; `migrations.py:545` vs `:553`; `migrations.py:36-48` |

### 3.3 Prior-art cross-reference — what was already known, and what invalidates a prior claim

The first pass of this audit did **not** read `docs/`, which holds 44 files including a 127 KB prior deep audit of the same update pipeline (`docs/audits/update-pipeline-deep-audit-2026-09-20.md`) and a 22 KB remediation plan. This section records the corrected picture. **Seven of the new findings contradict an explicit prior verdict** — which strengthens them, and three prior findings rest on a premise this audit falsifies.

| # | Prior state | Verdict |
|---|---|---|
| C-01 | `update-module-permanent-remediation…md:161` (D-01) specified the flag and claims it *"still always re-checks Ed25519 signature … **preserves trust**"*. Landed per `changelog:2300`. | **The doc's own safety claim is what failed.** Reinforced by `…deep-audit…:334` CMD-02. |
| C-02 | `…deep-audit…:169` **G-01 CRITICAL** "Forensic gate is a no-op"; closed `…:456` **"✅ FIXED — pluggable `active_probe` + `UpdateGateContext`"**. | **Reopened.** The ✅ closed it with a seam and no plug. No doc records that no production caller supplies a probe, nor adds TEST-01's requested test of the real gate (`…:522`). |
| C-02 (verdict logic) | `…deep-audit…:170` G-02 requested exhaustive matching; **FIXED**. | **New defect in the replacement** — an exhaustive `match` on a *truthiness* probe still lets a probe returning `1` fall to ALLOWED. |
| C-06 | `…deep-audit…:323` MIG-04 quotes the `copy2`; `UPDATE_LOGIC_FIXES.md:189` (H7) fixes only the **backup** direction WAL-aware. | **Restore direction's in-place overwrite is genuinely new.** |
| C-08 | `docs/INSTALLER_UX.md:103-108` §9 lists *"trust-key provisioning from `trusted-keys.bundle`"* as a **"Safety invariant … never their enforcement"**. | **Directly contradicts a stated invariant.** |
| C-11 | `…deep-audit…:301` MARK-02, `:420` FS-01, `:541` **Do-Not-Regress** — all three reason *symlink-only* and mark it "Noted as OK". | **The two-writer collision angle is absent from all three.** Contradicts a do-not-regress entry. |
| C-13 | `update-module…:48-51` (A-08) specified `from_state`, *"at record time"*. Status **OPEN**. | **Ordering hazard implied by the spec, never stated.** |
| C-15 | `…deep-audit…:358` UPD-04: `FileExistsError` is *"correct immutability"*, plus `:612` "releases immutable after verification" and `:616` **"Do not rewrite without evidence"**. | **The crash-path consequence is nowhere.** Expect pushback; bring the proof. |
| C-16 | `UPDATE_LOGIC_FIXES.md:67-77` **Problem/Fix B2** — *"backup path is computed, then discarded"*, closed at `UPDATE_PLAN.md:257-260` and `…deep-audit…:643` §29. The `None` consequence was walked at `…:371` REC-04 and dismissed **"Correct. Noted."** | **Cleanest "known, fix incomplete" case.** |
| C-17 | `…deep-audit…:300` MARK-01 quotes the exact expression: **"Correct."** | **Overturns a "Correct."** |
| C-18 | — | **New.** |
| C-20 | `…deep-audit…:471` P1-6 names only `RECOVERY_REQUIRED`; `:705` defers "recovery rules per state" wholesale. | **New.** No doc enumerates the handled set. |
| C-22 (H-18) | `…deep-audit…:185` L-07 covers *staleness*, not the *operator*. `:325` MIG-06 / `:481` P2-3 covered both-or-neither only (FIXED). | **The exact-equality-vs-`>=` disagreement is new.** |
| C-19 (H-19) | `…deep-audit…:184` L-06 (swallow, **OPEN**) + `update-module…:105` B-02 (**OPEN**). | **Known. The spurious-rollback consequence is new.** |
| C-02 (H-23) | `…deep-audit…:158` P-03 says the field is *"already validated by `manifest.py`"* — precisely the premise the falsy-check breaks. | **New, and contradicts P-03's stated assumption.** |
| H-05 | `update-module…:23-26` A-03 and `:28-31` A-04 — **OPEN**, plus `UPDATE_LOGIC_FIXES.md:247` M12. | **Known and open.** |
| H-33 | `changelog:2435-2437` claims *"nonzero-exit detection … all green"* for the exact code. | **Invalidates a recorded verification claim.** Strongest form of the finding. |
| H-18 (§9.3) | `…deep-audit…:226` MF-03 and `update-module…:73` A-13 documented the schema divergence — **OPEN**. Worse, `…:257` T-01 and `:247` SG-03 both assert the schema **is** enforced. | **Divergence known; deadness new — and T-01/SG-03 rest on a false premise.** |
| H-04 | `…deep-audit…:110` D-01 **FIXED**; `:111` D-02 **Phase F NOT FIXED**; the no-resume half is a conscious **DEFER** at `:705` (*"YAGNI until a real resume path is implemented"*). | **Partially known, half-open, half-deferred by design.** Reclassify; the "dead" framing is mine. |
| `AVAILABLE_BUT_*` | `update-module…:66-69` A-12: *"Dead … invite misuse. **Permanent fix: Delete** the two members … If policy deferral is needed later, **re-add with a caller**"*. **OPEN.** | **Known and adjudicated — report as OPEN-already-decided, not as new.** The "re-add with a caller" wording is the opposite of a reserved seam. |
| `Subject.type` | `subpart-3.md:21-26` **[D1]** reserves `evidence` verbatim: *"Audit side stays ready (`Subject.type` already accepts `evidence`)"*. | **Half my §4.4 finding is wrong.** `evidence` is a reserved seam with a named owner. `report`/`device`/`system` have **no** stated consumer in any doc — that half stands. |
| H-37 / R-58 | — | `AuditAction` gains 3 members per subpart-3 [D7]; `ACTION_TITLES` must gain them too or `_timeline_summary` returns `""` (§4.4). The plan **inherits** the defect. |

**Repo policy on unwired seams — the rule I got wrong.** `…deep-audit…:612` principle #15: **"never delete a safety check because its implementation is incomplete."** That defends the inert `ForensicOperationGate` (C-02) from deletion — **wire it, don't cut it**. But `:709` says the opposite for everything else (*"Seven new stage classes … if each has one implementation and one caller. Violates ponytail 'no interface with one implementation.' … **prove the second caller first**"*). So the repo's policy is **collapse-unless-safety**, and §6.6 must carry that carve-out. It now does.

**Two `[x]`-closed requirements this audit breaks:** `UPDATE_PLAN.md:247` (*"Verification summary shown and confirmed before any install commits"*) by the hardcoded `"Signature: Verified"`; `UPDATE_PLAN.md:218` (*"No optional integrity verification in production"*) by the unverified rollback wheel.

**Two subpart-3 collisions:** migration `014` → **H-79** above. `EXIT_SOURCE_WRITABLE = 10` is **clean** — 10 is genuinely unallocated (current codes: 0, 1, 2, 11, 12, 13, 14, 15, 16).

**Two of my reuse findings are validated by subpart-3 §3's reuse table**, which pre-commits `core/ui/renderers.py render_dossier` to `devices/renderers.py` (confirming R-03) and cites the `render_case(s)` dispatch to *"kill the six json/table branch duplications before they are born"* (confirming R-30).

**Tally: 15 of 28 tested update-pipeline findings are genuinely new; 13 were already documented.** No prior doc contains a ranked duplication matrix — §6 is new in full, including every line count. `read_json_record` and `is_naive` return **zero hits** across all of `docs/`.

---

## 4. Medium findings


Grouped by module. Each is a real defect or a real maintainability hazard; none is generic advice.

### 4.1 `core/` — time, errors, domain, repository, CLI

| Location | Finding |
|---|---|
| `core/canonical.py:13`, `core/domain.py:31`, `core/ui/renderers.py:264` | The naive-datetime predicate `dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None` is written out **three times** (the third, shorter, is the C-04 bug). No `is_naive(dt)`. |
| `core/canonical.py:21` | `assert coerced is not None` is unreachable (`canonical_ts` is typed non-optional), and asserts vanish under `python -O`. |
| `core/canonical.py:41` vs `:50` | Dict keys are sorted **twice** — once in the comprehension, once by `json.dumps(sort_keys=True)`. One is dead work. |
| `core/canonical.py:44` | `set` (and any non-`dict`/`list`/`tuple`) falls through unconverted, so `json.dumps` raises an opaque `TypeError` on an audit payload instead of a clear contract error. |
| `core/canonical.py:25` vs `core/cli/completion.py:115` | `parse_trailing_seq` is the sanctioned case-number tail parser; `completion.rank_cases` re-implements it inline with `except Exception: seq = 0` — silently yielding rank 0 where the helper returns `None`. |
| `core/dto.py:26-29` | `BaseResponseDto.opened_at`/`updated_at` are bare `datetime` with **no tz validator**, while `domain.BaseEntity` enforces `require_utc`. The DTO boundary — exactly where external input enters — enforces nothing. |
| `core/dto.py:38` vs `core/cli/completion.py:57` | The page-size default 50 is written twice: as the DTO default and as a bare literal in `_fetch_cases`. |
| `core/dto.py:15-20` | `BaseCreateDto` and `BaseUpdateDto` are empty marker classes constraining nothing; only `cases/dto.py` subclasses them. |
| `core/domain.py:22-24` | `ensure_utc` is a pure alias for `canonical.coerce_utc`, re-exported to 7 call sites. Two "single sources" for UTC coercion, one of which is not the one the docstring names. |
| `core/domain.py:52-58` | `EntityNotFoundError` has **zero raisers** anywhere in the repo (verified by grep) while `errors.NotFoundError` has the real subclass `CaseNotFoundError`. Dead, and the direct cause of a duplicated concept with incompatible signatures. |
| `core/domain.py:36-43` | `parse_enum_value` leaks `Any` on all three positions. A `TypeVar` bound to `Enum` would catch a wrong-enum bug at type-check time. Its two `except`/`return None` paths are indistinguishable. |
| `core/errors.py:34-47` | `ConcurrencyConflictError.__init__` builds its message through the `ConflictError` constructor, producing **`"Case with version='expected 3, found 4' already exists."`** A concurrency conflict is not an existence conflict, and `error_handler.py:111` renders `str(e)` unmasked. |
| `core/errors.py:10, 13` | `EXIT_CONFLICT = 13` and `EXIT_USAGE = 2` are **defined and never referenced anywhere** (verified). The constants promise a mapping the handler does not implement: `ConflictError` → `EXIT_ERROR`, every `ValidationError` → `EXIT_ERROR`. An exit-code contract that lies is worse than none. |
| `core/errors.py:53-59` | `StateTransitionError.reason` is consumed into the message string but never stored as `self.reason`, unlike every sibling. And with `default_remediation=None` (`:122-123`) it renders a card with **no `→` remediation line** — a differently-shaped card from every other error in the app. |
| `core/errors.py:69-70` | `AuditTamperError.__init__` is a pure passthrough to `Exception.__init__`. Dead override. |
| `core/fs.py:60-61` | The rename is never made durable — the file is fsynced but the **parent directory is not**, so after a crash the rename can be lost while the content is intact. `os.chmod(tmp, mode)` is *after* the write, so the file briefly exists with umask permissions before being tightened to 0600. |
| `core/fs.py:11-12` | `mkdir(parents=True, exist_ok=True)` creates with the umask (commonly 0755, world-readable) and only *then* `os.chmod(target, 0o700)`. For a forensic storage root there is a window in which case directories are world-readable. `mkdir(mode=0o700)` closes it. |
| `core/fs.py:9` vs `core/settings.py:65-75` | `ensure_dir`'s docstring claims *"Fails loudly instead of inheriting umask"* — but `model_post_init` wraps the call in `except OSError` and only logs a warning. The loudness is provided by one caller and abandoned by the caller that matters at import time. |
| `core/fs.py:66-80` vs `:97-136` | On Windows `msvcrt.locking(LK_LOCK, 1)` retries then **raises** after ~10 s; on POSIX `flock(LOCK_EX)` blocks indefinitely. Same API, divergent semantics — a Windows CLI can fail a migration lock that Linux would have waited out. |
| `core/fs.py:131-133` | `try_file_lock` releases in `finally` **even when `_acquire` returned `False` and the lock was never taken**. The primitive lies; the `if not held:` guard at every call site is the only thing preventing a caller from proceeding unlocked. |
| `core/fs.py:47-62` | `atomic_write_lines` has **no `try/finally` around the write** — an exception mid-write leaves `target.tmp` permanently on disk. Root cause of the plaintext-evidence-leak in C-24. |
| `core/database/base.py:17-31` | `TimestampMixin` is used by **exactly one** model; the other three hand-roll their own timestamp columns with genuinely different names. An abstraction with one implementation. |
| `core/database/base.py:43-45` | `SoftDeleteMixin` provides `is_deleted` + `archived_at` but **not** `archived_by`, which `cases/models.py:26` adds by hand and migration 002 adds by DDL. An incomplete mixin is exactly how the three-place `archived_*` duplication arose. |
| `core/database/session.py:44, 108-117` | `_READY_CACHE` is a module-level `dict[str, bool]` keyed by URL that makes `ensure_ready()` a permanent no-op for the life of the process. The TUI is long-lived, so running `trace db migrate` in another terminal is never noticed. A `False` is never cached, so a transient failure re-runs the whole advisory-lock + file-lock sequence on **every** session open. |
| `core/database/session.py:199` | `db_manager = DatabaseSessionManager()` at module scope captures `settings.database_url` at **import time**. Any test or tool mutating it after import gets a stale URL from the global while explicit managers get the new one — two behaviours from one config. |
| `core/database/session.py:133-167` | `sanitized_db_identity` and `sanitized_db_url` are two near-identical URL-scrubbing functions (~8 duplicated lines). `sanitized_db_identity` has **one** caller and should be private. |
| `core/database/session.py:165` | `urlunsplit(...)` returns the **query string verbatim**. The password is masked in `netloc`, but many drivers accept credentials in the query (`?password=`, `?PWD=`, `?authToken=`). The function is documented as "Full database URL with the password masked" and is used for user-facing display and logging. |
| `core/database/session.py:94-101` | `ensure_ready` reaches into `trace_core.updates.migration` and `trace_core.updates.errors`. **`core/database/session.py` — the lowest layer — depends on the `updates` feature package**, for a concern unrelated to database readiness. A layering inversion: `core` → `updates`. |
| `core/database/session.py:187-195` | `get_db(ctx)` duck-types `ctx.service.session_manager` and wraps the whole probe in `try/except Exception: pass`, so a `ctx` with a broken `service` **silently falls back to the global `db_manager`** — i.e. a typo'd context queries the *production* database instead of the caller's. One of two call sites exercises the parameter. |
| `core/database/repository.py:68-71` | `_fetch` is documented as *"Single source for PK fetch. Shared by get/update/soft-delete flows"* and is used **only** by `get_by_id`. `update`, `delete`, and `exists` each inline the identical `select(self.model_cls).where(getattr(self.model_cls, "id") == entity_id)` — three verbatim copies of a query the docstring claims is single-sourced. |
| `core/database/repository.py:94` | `raise ValueError(f"{...} does not exist.")` — a bare `ValueError` for a not-found, while `errors.NotFoundError` exists for exactly this. Two error types for one failure class, and this one is *outside* the `ApplicationError` tree, so it hits the C-05 masking path. |
| `core/database/repository.py:129-131` | `if hasattr(self.model_cls, "is_deleted")` is duck-typing on a generic base whose mixins are the intended contract. Silently skipping the soft-delete filter for a model that forgot the mixin produces a **silently wrong result set** — archived rows leaking into counts — which is worse than an error. |
| `core/database/health.py:39-41` | The docstring says *"Never raises on connection failure"* but only `check_connection()` is inside the `try`. The three inspection calls are outside it, and their exceptions are not `ApplicationError`, so they hit the C-05 mask. |
| `core/database/health.py:32` | `except Exception as exc: healthy, message = False, str(exc)` puts the **raw DB exception** into `message`, rendered to the user with no `TRACE_DEBUG` gate. |
| `core/database/health.py:14, 15, 18` | `applied: list[dict]`, `pending: list[tuple]`, and `fetch_db_snapshot(mgr=None)` — the shared contract between CLI, TUI and `migration_entries` is entirely unspecified. |
| `core/service.py:46-51` | Read paths bypass `BaseService.transaction()` and open raw sessions; the audit service adds a *second* wrapper. **Three** session-scope idioms — and `UnitOfWork` is reachable only from mutating paths, so the "audit inside the transaction" invariant has no enforcement point on reads. |
| `core/service.py:54-55` | Hooks are coupled by **registration order** and by **shared mutable closure state** (`cases/service.py:251 pinned`), neither of which is in the `UnitOfWork` contract. That undocumented coupling is what allows `pinned` to be silently skipped. |
| `core/service.py:28, 35` | `before_commit()` / `on_commit()` are *registration* methods while `*_hooks` are the *execution* lists, and `before_commit` is also the phase name in the class docstring. `register_before_commit` / `after_commit` would be self-evident. |
| `core/settings.py:65-75, 89` | `model_post_init` performs a **filesystem write at import time**, because `settings = Settings()` executes at module import. Every process that imports settings — including `trace --help` and all 40+ test modules — creates `~/.trace/storage`. And the `except OSError` converts failure to a warning, so a bad `TRACE_STORAGE_ROOT` produces a successful-looking process that fails later at the real write site. |
| `core/settings.py:37` vs `:85` | The shipped dev secret is a **string literal repeated twice in the same file**. If someone rotates the default but not the guard, the guard silently stops protecting production. (4 copies repo-wide.) |
| `core/settings.py:53` | `update_channel: str = Field(default="stable")` with no `Literal` or validator, so an arbitrary operator-supplied string reaches `f"{base_url}/{channel}.json"` unvalidated whenever the manifest URL has no `.json` suffix. `UpdateChannel.contains` — documented as *"Single choke point for channel validation"* — is bypassed by the one setting that feeds it. |
| `core/settings.py:17` vs `pyproject.toml:7` | `version: str = "0.2.6"` is a hand-maintained duplicate of the packaging version. Nothing enforces it. |
| `core/settings.py:43, 60` | `Path.home() / ".trace"` is built twice, and `updates/` + `trace_updater/` hardcode the same home layout — **4 copies** of the app's home directory convention. |
| `core/operators.py:99-110` | Covered in H-74. Also `role`/`status` are bare `String(16)`/`String(255)` with **no enum type and no `CheckConstraint`**, so a typo'd role is storable and silently reads as "not admin". |
| `core/operators.py:73` | `from sqlalchemy import select` is imported *inside* `get_or_provision` while `:16` imports three names from the same module at module level. No cycle reason. |
| `core/cli/error_handler.py:57-94` vs `:100-133` | **Two** dispatch mechanisms for the same job: an `isinstance` ladder for application errors and a `specs` tuple loop for update errors. One ordered `specs` tuple covering all types would be ~25 lines shorter and would make C-05 a one-line fix. |
| `core/cli/exit_codes.py` | `EXIT_USAGE` and `EXIT_CONFLICT` unused (above). `EXIT_ERROR` is hardcoded as a literal `1` in `audit/commands.py:27, 73, 102` while `cases/commands.py:16` imports it. |
| `core/cli/completion.py:153-158` | `return number.split("-")[1] if "-" in number else "OTHER"` plus `except Exception: return "OTHER"` — the `except` is **dead** (`str.split` cannot raise), which is why the "OTHER" fallback is only reachable for the zero-dash case, and why `test_completion.py:44` locks in the meaningless `"no-dashes-here" → "dashes"`. |
| `core/cli/doctor.py:30-44` | `_storage_check` writes and deletes a probe file in the evidence storage root, and is called on every Diagnostics render (§ H-66). |
| `core/cli/args.py:12-15` vs `:39-42` | `--flag` / `--flag=value` matching is implemented twice in the two primitives every shell handler parses through. |

### 4.2 `migrations.py` (618 lines, 16 migrations)

| Location | Finding |
|---|---|
| `migrations.py:82-90, 112-116, 154-158, 183-194, 201-207, 502-508, 514-524, 559-565, 614-618` | The `if isinstance(bind, Connection): … else: with bind.begin():` fork is repeated **9 times** (~45 lines) and is **entirely dead** — `apply_migrations:444` always passes a `Connection`. Pure deletion, the largest mechanical win in the file. |
| `migrations.py:36-48` | `register_migration` overwrites `MIGRATION_VERIFIERS[version]` with **no uniqueness check**. Two migrations sharing a version number is silent, total, and unrecoverable: the second's verifier replaces the first's and only one ever runs. A `RuntimeError` on duplicate version/name is three lines. |
| `migrations.py:68-77` | `_ensure_column` and `_apply_missing_columns` are the same operation, and the second is the *worse* variant: it takes a pre-computed column set and never re-inspects, so a partially-applied set from an earlier failure is mis-detected. |
| `migrations.py:480-492` + `settings.py:29` | `ROLE_DDL` grants/revokes for `trace_app`/`trace_reader`, but the **default** `database_url` connects as a superuser table owner, which bypasses all GRANT/REVOKE. Migration 011 is a **complete no-op** under the shipped configuration — and it hard-fails (H-58) on exactly the non-superuser setups where the grants would matter. |
| `migrations.py:568-573, 600-611` | `_safe_nested_execute` swallows every exception and migration 016 calls it for 4 columns, 2 backfill UPDATEs and 2 index CREATEs with **no verifier**. Migration 016 can be a complete no-op and still be recorded as applied, permanently. |
| `migrations.py:171-194` | Migration 007 has **no verifier** and `_try_idx` swallows all exceptions, so a failed index creation is recorded as success. Its `CREATE INDEX IF NOT EXISTS` is also not portable (MySQL has no such syntax). |
| `migrations.py:314-339` | A function named `verify_migration_checksums` **writes to the database**. |
| `migrations.py:59-65` | `_CASE_COLUMN_DEFINITIONS` is the 4th place `archived_at`/`archived_by`/`version` are declared (also `base.py:43-45`, `domain.py:73-75`, `cases/models.py:26-27`, and the migration-006 CHECK). Realistically irreducible across layers, but nothing *enforces* the agreement. |

### 4.3 `cases/`

| Location | Finding |
|---|---|
| `cases/domain.py:64-65, 114-118` | **UNDER_REVIEW is an unreachable state** yet is filterable and advertised: `_VALID_TRANSITIONS` permits `OPEN→UNDER_REVIEW`, but the only caller passes `CaseStatus.CLOSED`, so the whole `elif target == CaseStatus.OPEN` branch is dead. `case list --status UNDER_REVIEW` always returns empty. |
| `cases/domain.py:110-112` | `object.__setattr__` bypasses **all** pydantic field validation, not just the validator being dodged. `closed_by="   "` stores `""` instead of `None` because the truthiness test runs before the strip; `min_length=1` is skipped. A CLOSED case with an empty `closure_reason` is representable. |
| `cases/domain.py:50` | `class TransitionError(Exception)` does not inherit `TraceError`/`DomainError`, unlike its sibling `InvariantViolationError`. Any future caller outside the `try` at the service layer leaks a raw `Exception` past `capture_cli_errors`, which has no branch for it. |
| `cases/domain.py:244-246` | `changed_fields(before, after)` is the declared *"Single source for diff detection"* and **the service never calls it** — the service re-implements the same diff with 18 hand-written lines. The service is the authority that decides what enters the immutable ledger, and it is using a private copy of the rule. |
| `cases/domain.py:235` | `tracked_snapshot(case: Any) -> dict[str, Any]` with `getattr` duck-typing. A `Protocol` with the five `CASE_TRACKED_FIELDS` attributes would give the same duck-typing *with* type checking. |
| `cases/domain.py:241` | `list(getattr(case, k)) if k == "tags" else getattr(case, k)` hardcodes `"tags"` inside a comprehension driven by `CASE_TRACKED_FIELDS` — a second source of truth for the field set, expressed as a magic-literal conditional. |
| `cases/domain.py:75, 80` | `STATUS_FILTER_KEYWORDS` exists, then `is_archived_filter` re-tests `raw.upper() == "ARCHIVED"` instead of deriving from the tuple. `"ARCHIVED"` appears at 2 more sites. |
| `cases/dto.py:19, 21-29` vs `cases/domain.py:195-209` | The "≤50 tags, ≤50 chars each" rule and **its two exact error strings** are implemented **three times**. Because pydantic runs `Field` constraints before `mode="after"` validators, the `if len(v) > 50` at `:27-28` is unreachable dead code. |
| `cases/dto.py:39` | `CaseUpdateDto.tags` has **no** `max_length` and no per-tag cap, while `CaseCreateDto.tags` is capped. An update can push 500 tags of 5000 chars past the DTO. |
| `cases/dto.py:94-98` + `cases/domain.py:201` | **Phantom audit entries.** `parse_tags` returns tags stripped but not lowercased; `Case.validate_tags` lowercases. The service compares the raw DTO value against the normalised entity value, so `--tags USB` on a case holding `usb` records `"tags"` in `changed`, the domain normalises it back, and the ledger records `before == after` — **an edit that did not happen**. Same defect for `title` via `.strip()`. |
| `cases/dto.py:59-80` | `from_domain` is an 18-line hand-copy of `Case`'s fields. `BaseDto` already sets `from_attributes=True`, so `CaseResponseDto.model_validate(case)` derives it. As written, adding a field to `Case` **silently drops it from the API payload**. |
| `cases/dto.py:91` | `limit: 5` — the same 5 is hardcoded at 4 more sites. Two of those five must agree for the UI to be right. |
| `cases/models.py:22` | `default="OPEN"` re-declares `CaseStatus.OPEN.value` as a bare literal in the persistence layer, so the enum is not the single source for the DB default. |
| `cases/repository.py:256-265` | `_scan_max_seq` loads **all** case numbers for the year and loops in Python. A cold-start year with 50 000 cases materialises 50 000 strings; the same maximum is one `SELECT max(CAST(substr(number,-4) AS INT))`. |
| `cases/repository.py:298-301` | `get_next_sequence_number` issues up to **10 000 `flush()` round-trips** inside the loop before giving up. |
| `cases/repository.py:267-284` vs `audit/repository.py:63-69` | `_ensure_seq_record` handles the cold-start insert race **properly** (catches `IntegrityError`, re-queries `with_for_update()`). The structurally identical audit-head path does **not**. The case repository has the stronger pattern; the ledger should use it. |
| `cases/repository.py:58, 65` | `opened_at=ensure_utc(model.opened_at) or now_utc()` — the `or now_utc()` is unreachable on a `nullable=False` column, *and* if a row ever violated the constraint the read would silently substitute "now" instead of failing. Wrong behaviour for a forensic timestamp. |
| `cases/repository.py:118-121` | `record_purge` unconditionally `add`s a `PurgedNumberModel`. A second purge of the same number raises `IntegrityError`, failing an otherwise-successful purge. |
| `cases/repository.py:18-42, 114-131, 286-288` | `CaseRepository` declares 15 methods but omits three that `CaseService` calls. So the service types its repo as the **concrete** class (7 sites) and the `Protocol` — whose docstring says *"Port defining persistence contracts"* — is a single-implementation abstraction nothing depends on. |
| `cases/repository.py:234` | `delete(entity_id, purge=False, expected_version=None)` diverges from both the Protocol and the base. A caller typed against either, invoking `delete(id)`, gets `ValueError("expected_version is required for forensic delete")` at runtime. The `# type: ignore[override]` is silencing a real design divergence. |
| `cases/repository.py:242-254` | The `update()` override duplicates 7 of the base's 9 lines. The base could expose `_fetch` reuse and the subclass would be 3 lines. |
| `cases/repository.py:293` | `prefix = f"{current_year}-CR-"` — every auto-allocated case is CR regardless of the NR/CLI taxonomy that two other modules assume exists. Undocumented. |
| `cases/repository.py:166` | `search.strip() if search and search.strip() else None` calls `.strip()` twice and is the third hand-rolled "normalise or None". |
| `cases/repository.py:168-176` | `ilike_literal` over 5 columns = 5 leading-wildcard `LIKE`s on TEXT, one of which (`notes`, up to 50 000 chars) is never indexed and unindexable for a prefix-free pattern. Every `case list -q` is a full scan. |
| `cases/service.py:140-143` | `err_msg = str(e).lower()` then `if "number" in err_msg or "uq_cases_number" in err_msg` — substring-matching driver text to decide a domain conflict. `"number" in err_msg` also matches a NOT NULL violation or any FK error mentioning the column. |
| `cases/service.py:50-54, 179, 241, 299, 305, 337` | `InvalidCaseStateError` hardcodes `current_state="UNKNOWN", target_state="UNKNOWN"`, so the rendered message is *"Cannot transition from UNKNOWN to UNKNOWN. Reason: …"*. It is then used for **four failures that are not transitions at all**: already-archived, not-archived, soft-deleted, and the purge precondition. |
| `cases/service.py:251, 264-269` | `pinned: dict = {}` … `if pinned: record_anchor_intent(...)`. If the `_audit` hook ever fails to populate `pinned`, the case closes permanently with **no anchor outbox row and no error**. The only reason it works is `UnitOfWork.transaction()`'s in-order iteration, and that dependency is undocumented at the registration site. `if pinned:` should be a hard failure. |
| `cases/service.py:84` | `return AuditService().record(session, …)` — constructs a service bound to the **global** `db_manager` (not `self.session_manager`) and uses only the passed `session`. A trap that is invisible at the call site. |
| `cases/service.py:188-205` vs `cases/shell_handler.py:430-443` | The "None and `''` both mean empty" normalisation rule is written **twice**, with the *same* comment claiming to describe the single shared rule. Combined with the tags/title defect, the shell's preview and the service's actual write **disagree in at least one case**. |
| `cases/service.py:243` + `cases/commands.py:184` vs `cases/shell_handler.py:486` | The CLI calls `close_case(..., actor=closed_by)`; the shell passes **no actor**, so an empty `closed_by` falls back to `case.lead_examiner`. **The same command writes a different `actor` and a different provenance block depending on which UI you used.** |
| `cases/service.py:207-208` | `if not changed: return` returns from *inside* `with self.transaction()`, so `session.commit()` still runs. A no-op edit still commits. |
| `cases/service.py:339-340` | `repo.restore(case.id, …)` then `repo.resolve(identifier)` — `resolve` re-normalises, re-attempts a UUID parse and issues a second SELECT. `repo.get_by_id(case.id)` is the direct call. |
| `cases/service.py:219-223` + `cases/commands.py:219-223` | The `else: render_error_card("Delete Failed", …)` branch is unreachable and its message would be misleading if it were. |
| `cases/commands.py:70-87` | The command declares no `--limit`/`--offset`, so `CaseFilterDto.limit=50` silently truncates — and `core/ui/renderers.py:403` then prints *"… N more (short screen — use --limit to page)"* pointing at a flag this command does not have. `cases/renderers.py:132` also reports the *page* length as the record count. |
| `cases/commands.py:94-102` vs `cases/shell_handler.py:108-115` | The same status-filter rule, the same `is_archived_filter` composition, and the same error string — CLI prints a card and `raise typer.Exit(EXIT_ERROR)`, shell **raises `ValidationError`**. Identical failure, two types, two code paths. |
| `cases/commands.py:49-64` vs `cases/shell_handler.py:356` | The same field is a CLI flag in one surface and a prompted value in the other, with different trimming. |
| `cases/commands.py:42, 137` vs `cases/shell_handler.py:353-359` | The CLI offers `--notes`; the shell wizard **never sets `notes`** in the create DTO, so interactive create silently drops a field the CLI supports. |
| `cases/renderers.py:24-65` vs `:84-109` | The breakpoint ladder is written **twice** (42 lines + 26 lines), and the second docstring admits *"Breakpoint branches mirror _case_table_columns"*. The header decides by **exclusion** while the row builder decides by **equality**, so a new breakpoint silently produces 6 columns of rows against a 5-column header. |
| `cases/renderers.py:10, 21` vs `:26, 105, 114, 138, 165, 166, 194` | **Eight** redundant import statements in one 246-line file. |
| `cases/renderers.py:88-91` | The bolding decision is made by comparing the **rendered prefix** (`if prefix == "● "`) rather than the condition. Reorder the two columns and the styling silently inverts. |
| `cases/renderers.py:88-91, 186` + `tui/theme.py:37-43` + `core/ui/renderers.py:302-312` | **Three** status → (label, colour, glyph) implementations, all using the fallback hex `#E5EAF0` which **does not exist in `THEME_TOKENS`** (nearest is `value = #E3E7EA`). Two near-identical whites coexist in the product. |
| `cases/renderers.py:120-123` | The group separator is built as `["" for _ in columns]`, coupling the separator width to the column count. `core/cli/completion.py:174 _grouped_rows` solves the same problem properly. |
| `cases/renderers.py:26` | An import executed on every table render, for a symbol used three times. |
| `cases/renderers.py:160, 182, 239, 244` | `events: list[Any] \| None` — nothing type-checks the `e.ts`/`e.action`/`e.actor` accesses. |
| `cases/shell_handler.py:205-206, 260-261, 276-277, 347-348` | **Four** bare `except Exception: pass` with no `structlog` — unlike the rest of the codebase, which logs every swallowed error. |
| `cases/shell_handler.py:256` | `list_cases(CaseFilterDto(include_deleted=True))` with **no `limit`**, then `cases[:15]`, on every completion keystroke whenever `complete_from_cases` throws. The primary path correctly uses `limit=50`. |
| `cases/shell_handler.py:259` | `candidates.append((c.number, c.title[:30]))` re-implements `preview_case`, which is already width-aware and status-aware — plus a hand-rolled **O(n²) dedupe** inside the loop. |
| `cases/shell_handler.py:274-275` | A comment saying "just return" immediately followed by a `return` that does something. Either the comment or the call is wrong. |
| `cases/shell_handler.py:129-131` | `resource = "Case"` followed by a bare string literal — a no-op expression, not a `__doc__`. The class has no docstring. |
| `cases/shell_handler.py:344` | Tags are collected from `list_cases()` with no filter (bounded at 50 cases), so the "Existing tags" offer is derived from an arbitrary subset — and it is prompted **before** the number is chosen, in the wrong dependency order. |

### 4.4 `audit/`

| Location | Finding |
|---|---|
| `audit/domain.py:86-88` | The UTC guard is `core/domain.py:27-33 require_utc` re-implemented with a different message. Four call sites already do the correct `canonical_ts(require_utc(ts_val))`. |
| `audit/domain.py:46-52` | `f"{prev_chain}{p_hash}{seq}"` relies on both hashes always being exactly 64 chars for the concatenation to be unambiguous. Nothing asserts it; `chain_hash` is public and callable with arbitrary strings. |
| `audit/dto.py:19-23` | `payload_hash`, `prev_chain`, `chain_hash` carry **no** length constraint, while the (dead) domain entity enforces 64. `actor` likewise — the 255 guard exists solely as a service-side `if`. **The invariants live in the dead class and not in the live one.** |
| `audit/dto.py:33-55` | Six REPL tab-completion tables living in the **DTO layer**, imported only by `shell_handler.py`. `cases/shell_handler.py:31-65` keeps the identical kind of data in the handler. Same concept, two different homes. |
| `audit/dto.py:33` | `_OUTPUT_DESC = "Output table|json"` vs `core/cli/output.py:6 OUTPUT_HELP = "table|json"` — same string, two spellings. And `AUDIT_SHOW_FLAGS`'s `("--limit", "Max rows")` contradicts the CLI's `help="Max rows (1..500)"`. |
| `audit/dto.py:55` | `ACTION_CHOICES = list(ACTION_TITLES.items())` makes presentation titles the **completion candidates**, so renaming a title for display silently changes tab-completion ordering and previews. |
| `audit/events.py:29-36` | `except Exception: return {}` for unparseable `payload_json`. A tampered or truncated payload renders as a *normal-looking event with no details* rather than "unreadable" — and combined with the hardcoded `Chain ✓ VALID` (C-03), the UI actively hides corruption. |
| `audit/events.py:9-26` | `Subject.type: str  # case \| evidence \| report \| device \| system` and `Context`'s five fields, for a codebase with exactly one call site that always passes `type="case"` and all five. `AuditAction` right next door is a proper `StrEnum`. |
| `audit/builder.py:131-139` | `out["host"]` … `out["os_user"]` unconditionally **clobber** any same-named key the caller put in `details`. A future caller that legitimately wants a `command` in `details` loses it with no signal. |
| `audit/builder.py:62, 90, 102, 114, 120, 126` | All six `command: str \| None = None` parameters are **dead** — every call site omits them. Six parameters that exist only to be ignored. |
| `audit/builder.py:21-29` | `return command or ""` on lines 25 and 29 is dead — `command` is truthy in both branches. |
| `audit/helpers.py:130` | `from trace_core.cases.service import CaseService` **inside** a function — the audit package imports the cases package. The reverse also exists in 9+ places. **The two features are mutually dependent**, which is why every one of those is a function-local import. The genuine unifier is `normalize_number` — which belongs in `core/canonical.py` beside `canonical_ts` and `parse_trailing_seq`, both of which `audit` already imports. |
| `audit/helpers.py:44, 58, 80, 91, 113, 125` | **Six** `# type: ignore[no-untyped-def]`. The functions are not untyped, they are *partially* typed, and the blanket ignore is what lets six parameters leak `Any` into the audit layer. None of these cycles actually require it. |
| `audit/helpers.py:91-93` | `do_export(svc, out): return svc.export(out)` — a one-line pass-through that adds nothing, called at 2 sites. Its siblings `do_verify` / `do_show_list` *do* add logic. |
| `audit/helpers.py:21-26` | `check_export_dest` returns a `Path` that is **discarded at all four call sites**. A fifth dead value. |
| `audit/helpers.py:29, 38` | `prompt_passphrase(confirm=False)` — the CLI's encrypted export confirms, the shell does not, and neither `decrypt` call confirms. A mistyped passphrase in the REPL produces a **permanently unopenable bundle** with no recovery path. |
| `audit/service.py:104, 113, 120, 125, 133` | Five read methods each open `_ledger_session` **and** import the repository *inside* the `with`. The local imports buy nothing — the `repository → dto → domain` chain is cycle-free as written. |
| `audit/service.py:99, 116, 131` | Three public API methods with **no return annotation**, all suppressed. And `AuditFilterDto \| None` is immediately collapsed by `filt = f or AuditFilterDto()` in the repository, so the `\| None` lies about its own contract. |
| `audit/anchor.py:217-233` | An unbounded `SELECT` materialises **every** non-confirmed intent including all FAILED ones, then opens **a new session and transaction per intent**. Every `case close` re-reads the entire outbox. `extra_sinks` fan-out has no per-sink failure isolation — one bad sink marks the whole intent FAILED even though the local anchor landed. |
| `audit/anchor.py:119-120` | `if state != "CONFIRMED"` where `state` is the *display* string from `latest_intent_status`, while the stored value is lowercase `INTENT_CONFIRMED`. The behaviour of `describe_anchor` depends on an undocumented formatting decision in a different function. |
| `audit/anchor.py:73, 75, 77` | Three consecutive `if res.is_valid and …`. Once the chain is broken the anchor is **never consulted**, so `audit verify --anchor FILE` against a tampered ledger reports only the chain mismatch and never tells the operator whether the anchor also disagrees. |
| `audit/anchor.py:173` | `intent.failure_code = f"{type(exc).__name__}: {exc}"[:255]` — exception text frequently contains absolute filesystem paths and OS error strings; persisted and surfaced to the CLI. Truncation is not sanitisation. |
| `audit/anchor.py:16, 44` | The anchors dir is computed twice, with a third implicit path via `anchor_path`. |
| `audit/anchor.py:35-37` | `json.loads(read_text())` on an operator-supplied `--anchor` path with **no size bound**. |
| `audit/anchor.py:23-29` vs `:155-161` | The same 5-key anchor payload is built twice, with the same field order — and a drift means the dead writer and the live publisher disagree about the schema. |
| `audit/signing.py:57-63` | `_keystore_dir()` calls `ensure_dir(...)` which `mkdir`s **and `os.chmod`s**. It is reached from `active_key_id()`, so a read-only `audit show` **creates and chmods a directory**. |
| `audit/signing.py:134-136` | `rotate_keys(label)` is a one-line pass-through to `init_key(label)`. "Rotation" is the same operation re-labelled. |
| `audit/vault.py:39-45, 54-57` | `envelope["alg"] = _ALG` is written but **never read on decrypt**. A bundle with a rewritten `alg` opens without complaint. |
| `audit/vault.py:55-63` | `iterations` is read from the (attacker-supplied) file up to `MAX_KDF_ITERATIONS = 5_000_000` — an 8× multiple of the writer's value for no stated reason. |
| `audit/vault.py:64` | `salt`, `nonce`, `ciphertext` and `iterations` are **unauthenticated** (`AESGCM(aad=None)`). |
| `audit/exporter.py:42-44` | `except Exception: ts_str = str(m.ts)` — a fallback that would emit a **naive, non-Zulu, locale-dependent** timestamp into a forensic bundle. The `except` is nearly dead, but when it fires it papers over a ledger-integrity failure. |
| `audit/exporter.py:45-58` | `_record_dict` is the **fifth** copy of the event schema — 12 keys hand-written, with `subject_case_id` stringified where the DTO keeps a `UUID`. |
| `audit/exporter.py:14-19` | `_ledger_tip` is a byte-for-byte reimplementation of `audit/repository.py:139-144 head()`. |
| `audit/exporter.py:52` | A JSON **string** nested in a JSON object, so every consumer must `json.loads` twice. Preserving the canonical bytes is right, but it is undocumented, and `_header` is described as canonical while using **default separators** — i.e. not `canonical_json`. |
| `audit/renderers.py:345`, `:336` | Covered in C-03. |
| `audit/renderers.py:123-144` | `_timeline_summary` dispatches on **string literals** while `AuditAction` exists and is used everywhere else. Adding an action falls through to `return ""` — the timeline renders an empty summary with no error. The five terminal labels are a second hand-written set parallel to `ACTION_TITLES`. |
| `audit/renderers.py:46` | `_, style, _ = get_status_style_and_label(e.action, False)` — the map contains no `CASE_*` action, so `style` always falls back to the default and **every audit row renders in the same colour**. The `border_color` third element is discarded. |
| `audit/renderers.py:8-19` vs `:39, 73, 103, 149, 208-222, 277, 331` | **Twelve** redundant import statements, including one placed **mid-function** at `:277`. |
| `audit/renderers.py:296-303` | `_how_text(details)` is defined and **never referenced** (verified). 8 lines of dead code, and the `command`/`trace_version` provenance written into **every** payload is never displayed. |
| `audit/renderers.py:320-327` | The final `return "chain_hash mismatch"` is the else-branch for *any* unknown `mismatch_type`, including a future one. |
| `audit/renderers.py:168`, `cases/renderers.py:168`, `:333` | Pluralisation hand-written in three files. |
| `audit/commands.py:139-140, 154-155` | `require_admin` → `get_or_provision` **adds and flushes** an `OperatorModel` row into a session that is closed **without committing**, so the row is **rolled back**. The "first operator becomes admin" bootstrap only ever persists via a case mutation's commit. |
| `audit/commands.py:26-27` vs `audit/shell_handler.py:214` | The same unknown-action failure gets a different card title, a different message (the CLI lists valid actions, the shell does not), and different control flow — and the CLI's `raise typer.Exit(1)` is outside `capture_cli_errors`, bypassing `exit_codes.py` entirely. |
| `audit/commands.py:10` vs `:165` + 5 methods | One file, two import conventions. |
| `audit/commands.py:88-89` vs `audit/shell_handler.py:222-228` | **Tamper policy asymmetry.** The CLI raises `AuditTamperError` → `EXIT_VERIFY_FAILED`. The shell calls `do_verify(...)` and **discards the result** — the helper even documents this as intentional, but the shell then owns *no* policy. `audit verify` in the REPL prints the tamper grid and returns as if the command succeeded. **The primary UI cannot distinguish a clean ledger from a broken one by exit status.** |
| `audit/commands.py:15-16` + `cases/commands.py:24-25` | Byte-identical 2-line `_get_service(session_manager=None)`. `BaseService.__init__` already does the fallback, so both reduce to a constructor call. |
| `audit/shell_handler.py:85-147` + `cases/shell_handler.py:190-217` | **Four** + **two** completion methods, each re-implementing "if the last token is a flag → return its values; else filter the table", plus the same `try/except Exception: return []`. **~30 lines duplicated across two handlers**, and `BaseShellHandler` is the natural home but currently only owns `unknown_action`. |
| `audit/shell_handler.py:178-184` | The positional is **re-serialised back into a flag** so `_show_list` can re-parse it. The scope-to-active-case guard is a `startswith("-")` heuristic that misfires on `--search --case` style invocations, and the scope notice it prints has no test. |
| `audit/shell_handler.py:111, 121` vs `:199, 254, 270, 281` vs `:149-152` | **Three** different idioms for accessing the same service. |
| `audit/shell_handler.py:135` vs `:95` | One completion path returns raw `OUTPUT_CHOICES`, the other caps at 8. |
| `audit/shell_handler.py:190-194` + `helpers.py:117` + `service.py:100-103` | `seq` is validated **twice**. |
| `audit/shell_handler.py:248` | `_ = svc` inside `_decrypt` — `decrypt` needs no database, yet `execute` builds an `AuditService` (and therefore a session manager) for **every** action including `decrypt`. |

### 4.5 `updates/`

| Location | Finding |
|---|---|
| `updates/lifecycle.py:155-208` | The `except Exception` and `except BaseException` bodies are ~24 lines of **near-verbatim copy-paste** — same `can_transition` check, same 12-field DTO, differing only in `failure_reason` and `override_reason`. |
| `updates/lifecycle.py:145-153` | `_run_locked` is called with 10 positional arguments, three of which have defaults **duplicating** `run()`'s and are **never used**. Two default sites for the same three values. |
| `updates/lifecycle.py:38, 158, 183` | `import structlog` **three times in one file** under two spellings. The repo has the one-module-`logger` pattern. |
| `updates/lifecycle.py:90, 160, 185, 26, 474` | Function-local re-imports of names already bound at module scope. ~40 function-local imports in a 491-line file, at least 6 pure redundancy. |
| `updates/lifecycle.py:173, 351, 377, 407` | `_override_note` is called on both the success and the failure path, each time executing a fresh `current_schema_version`. One update performs **up to 4 identical** schema queries. |
| `updates/lifecycle.py:336-337` | `with update_lock():` inside `_run_locked` is a **pure no-op** — `run()` already holds it and the comment says so. It exists only because `lock.py`'s thread-local depth counter makes re-entry safe. It fires **6 times** per update. |
| `updates/lifecycle.py:60, 70-71` | `snap: object` plus `getattr` duck-typing, while the concrete `DbSnapshot` dataclass is imported in the same file at `:331`. |
| `updates/lifecycle.py:62-63` | `schema_after` and `staged` are both **always** supplied by the sole call site, and the docstring's stated precondition is enforced by nothing. |
| `updates/lifecycle.py:73, 76, 82, 87, 417` | Health verdicts are bare `"failed"` / `"passed"` strings, and the rollback path **re-derives the same two magic strings independently**. |
| `updates/lifecycle.py:417` vs `:72` | The post-rollback health check tests only `.healthy`, not `.pending`. **A rollback that lands on a DB with pending migrations is reported `"passed"`.** |
| `updates/lifecycle.py:380` | `staging_dir = base / "staging" / self.transaction_id` with an unvalidated caller-supplied `transaction_id`, and `staging_dir` itself is never checked against `base`. |
| `updates/lifecycle.py:22` + `tui/screens/settings.py:501` | `self.service = service or UpdateService()` defaults to the **global** `db_manager`. The TUI constructs `UpdateLifecycle(uuid4())` with no service, so it writes history to the global DB regardless of the manager the TUI was given. |
| `updates/lifecycle.py:381-403` | `Stage.DOWNLOAD` is **never** reported by the lifecycle. The real download happens *before* `run()`, and the TUI passes no `on_bytes`. The progress bar **never renders** in the TUI. |
| `updates/lifecycle.py:155-208` + `updates/stages.py:52-54` | `StageStatus.FAILED` is **never** passed to `progress.on_stage` on any error path, yet the glyph map, style map, `_FAILED_STAGE` and the `ProgressCallback` protocol all handle it. A live display freezes on "Verifying ◌" until `finish()`. |
| `updates/lifecycle.py:369-370` | Two durable marker writes with no observable state between them. `AVAILABLE` is never externally observable. |
| `updates/lifecycle.py:436` | The `RECOVERY_REQUIRED` branch records `result=FAILED` and leaves `rollback=False`, so `finish()` takes the "Update failed" branch and **never prints "The update was rolled back"** — even though a rollback was attempted. The state is not represented in the DTO at all. |
| `updates/lifecycle.py:416` | `rollback_release(...)` is trusted without a `_verify_activation`-equivalent. Nothing confirms the pointer actually flipped. |
| `updates/lifecycle.py:318-491` | `_run_locked` is **174 lines**, 8 levels of nesting in the rollback branch, performing 11 distinct concerns. |
| `updates/lifecycle.py:250-258` | `_assert_verified_stage` takes `staging_dir` **and** `staged`, but `staged` is always `staging_dir / src.name`, so `staging_dir` is derivable. It also takes `channel`, `current`, `started_at` purely to build a history DTO — a 43-line method doing two unrelated things. |
| `updates/lifecycle.py:131` + `commands.py:39, 55` | `is_update_available` is checked at **three** call sites for one precondition. |
| `updates/lifecycle.py:348` | `raise UpdateError("unknown forensic-operation state; failing closed")` loses the reason entirely, because `gate.py` swallowed the probe's exception with no log. |
| `updates/migration.py:29-47` | `update_migration_owner` defines a nested `@contextmanager` closure on **every call**. The reentrancy contract is functionally identical to `lock.update_lock`'s thread-local depth counter — two hand-rolled reentrant thread-local mechanisms, same purpose, different bookkeeping, different type-ignore styles. |
| `updates/migration.py:71-74` vs `:274-275` | `begin_update_migration` performs **no ownership check** before overwriting, while `run_updater_migration` *does*. Two entry points, two policies, and the check-then-write is not atomic. |
| `updates/migration.py:98-99` vs `manifest.py:51-55` | The "both or neither" rule is implemented **twice**, with **different error types**. |
| `updates/migration.py:303` + `:310` | `current_schema_version(manager)` is called, then `verify_compatibility(manager, …)` re-executes the identical query. Two identical round-trips per migration. |
| `updates/migration.py:229-231` | `literal = str(check_contained(out, dest)).replace("'", "''")` then `VACUUM INTO '{literal}'` — hand-rolled quote-doubling inside an f-string. `VACUUM INTO` takes no bind parameters, so the correct construction is SQLAlchemy identifier quoting. Mitigated by a `check_contained` that is provably always true here. |
| `updates/migration.py:110-117` | `_confine_backup_path` accepts anything under `Path(storage_root).parent`, which includes the **evidence storage root itself** and the whole install tree. It **widens** with the same `check_`-less name that `check_contained` uses to narrow. |
| `updates/migration.py:110-114` | `Path(...).resolve()` can raise `RuntimeError` (symlink loop) as well as `OSError`; only `OSError` is caught, so a looped symlink escapes as `RuntimeError` from a recovery path that promises `RecoveryError` in every other branch. |
| `updates/migration.py:186` vs `:259` | `RecoveryError` vs `UpdateError` for the identical condition. `RecoveryError` subclasses `UpdateError`, so the two are indistinguishable to callers. |
| `updates/migration.py:305-310` | `needs_backup` triggers a **full database backup** *before* `verify_compatibility` rejects an incompatible target. A forensic tool writes a full copy of the evidence database to disk for an update it is about to refuse. |
| `updates/migration.py:179, 250` | Bare `timeout=600` / `timeout=300` where `pip_backend.py:16-17` establishes the named-constant convention. The asymmetry is unexplained. |
| `updates/migration.py:143, 165, 169, 240` | `import os`, `import os as _os` ×2, and `import subprocess` (already module-level) — inside a single function — plus a re-import of a module-level name. |
| `updates/migration.py:79`, `:274` | `if state == "active" and active and …` — when `marker_state()` returns `"active"` it guarantees `active` is a dict, so `and active` can never be false. Two copies of the same redundant conjunct. |
| `updates/migration.py:318, 321` | `result["applied"]` and `result["backup_waived"]` are **never read** by any production code or any test (verified). A waiver that skipped the mandatory backup is computed and thrown away. |
| `updates/marker.py:13` vs `:25` | `REQUIRED_KEYS` is referenced by **no production code** (only a tautological test), while `write_marker` **hardcodes its own copy** — omitting `marker_schema` even though `SCHEMA_REQUIRED_KEYS` includes it. Three sources of truth, and the writer's copy disagrees with the reader's. |
| `updates/marker.py:20-29` | `write_marker` validates only that two keys are *present*, never that `state` is a legal `UpdateState` and never that `transaction_id` is non-empty. A forensic marker can be written with `state="GARBAGE"`. |
| `updates/lock.py:17-35` | The 10-line thread-local depth counter exists only to make **re-entrant no-ops** safe, and every re-entrant acquisition in the codebase is one that should not happen. |
| `updates/lock.py:20` | *"TUI async tasks must use anyio.to_thread"* — the TUI uses `asyncio.to_thread`. `anyio` is a dev-only dependency and is not imported anywhere in `src/`. The docstring directs callers to an API the codebase does not use. |
| `updates/lock.py:45` → `fs.py:125` | `try_file_lock` does `open(path, "a+b")`, so the "is anyone home?" probe **creates `update.lock`** even when it never intends to take a lock. |
| `updates/stages.py:38-49` vs `updates/renderers.py:36-41` | Two mappings of the same concept in two shapes, and they already **disagree**: a migration failure renders as a **health** failure. And `"recovery_required"`, which `from_state` actually produces, is **not a `_FAILED_STAGE` key**, so the stage row is silently omitted; while `"recovery"`, which *is* a key, is never produced. |
| `updates/stages.py:21, 23-28, 30-35` | Three hand-maintained containers that must stay in sync over the same `Stage` key set, indexed with `[]` by consumers, so a missing key is a runtime `KeyError` during rendering. |
| `updates/stages.py:52-54` vs `renderers.py:81` | `ProgressCallback` is a `Protocol` (structural), but `UpdateProgressDisplay` **explicitly subclasses** it while `SilentProgress` does not. Explicit Protocol inheritance disables structural checking and adds an edge the design does not need. |
| `updates/stages.py:83` | `f"{eta // 60:.0f}m {eta % 60:.0f}s"` — `eta % 60` is a **float** rounded by `:.0f`, so `eta = 119.7` renders `"1m 60s"`. |
| `updates/stages.py:75, 79` + `:69` | `read / elapsed` is recomputed from scratch instead of reusing `speed * (1 << 20)`, and the magic `1 << 20` appears three times. `format_mb` divides by `1 << 20` (MiB) but emits the SI label `" MB"`. |
| `updates/staging.py:24-33` | `write_staged_record` is `marker.write_marker` with different names: validate → `json.dumps` → `atomic_write_lines`. Two modules, one operation, two implementations — and `staging.py` got the merge order right while `marker.py` got it wrong. |
| `updates/staging.py:32, 44` | The record is stamped `"staged_schema": 1` on write but **never validated on read**, and will accept a record with no `staged_schema` or `staged_schema: 999`. |
| `updates/staging.py:36-46` | `read_staged_record` returns `None` on corruption while `marker.read_marker` **raises** — the read side is the odd one out, which forces C-18's swallow. |
| `updates/staging.py:56` | `sha256_file(artifact_path)` recomputes the full artifact hash, which the stage copy **already verified byte-for-byte** moments earlier. A multi-GB wheel is hashed **three times** per update. |
| `updates/staging.py:31`, `marker.py:24`, `migration.py:73`, `cache.py:39` | Four `check_contained` calls that are **provably always true** because the target is derived from the root itself. They read as security controls and provide none. (Contrast `updater.py:100/102/186/189/250/266`, where the root is a sibling directory and the guard is real.) |
| `updates/checker.py:22` | `resolve_manifest_target(explicit, channel="stable")` — `channel` is **never read in the body**, yet is threaded through 5 call sites that believe resolution is channel-aware. A "Single source" whose signature lies is worse than no docstring. |
| `updates/checker.py:196-205` + `cache.py:47-65` | Cache identity is computed from one read of the file and the payload from a second, so the recorded identity and the recorded payload **can describe different bytes**. |
| `updates/checker.py:139-147` | The 304 branch refreshes `checked_at` on an entry whose `channel` was never re-checked. The guard the file path gets for free is missing on the HTTP path. |
| `updates/checker.py:110-119` | `read_active` is `p.read_text().strip() or None` — arbitrary bytes from a 0600 file. Any non-empty garbage is returned as "the installed version" and then hits `Version(...)`. And a failed import raises `ModuleNotFoundError`, which is **not** `OSError`, so it escapes a function whose contract is "always return a version". |
| `updates/checker.py:41-49` + `commands.py:30-45` + `commands.py:48-58` | One "load the update" concern split across three overlapping functions, with a 6-element positional tuple. `update_install` does not call `prepare_install`; it re-inlines the same 4 lines. `resolve_channel(None)` is called three times per install. |
| `updates/checker.py:122-172` vs `:175-188` | The payload dict is constructed **twice**, from two sources, that have drifted. `_payload_from_check` has a `"Single source for cached payload shape"` docstring — but the HTTP path doesn't use it. |
| `updates/checker.py:9`, `sources.py:8-9`, `cache.py:55` | The URL-scheme literal tuple in **three homes, two spellings**. |
| `updates/checker.py:9` + `sources.py:9` | `# NOSONAR` on the *constant's definition* rather than on the one line that permits plain HTTP. A reviewer scanning for `NOSONAR` cannot tell which one is the decision. |
| `updates/checker.py:217-220` | `except Exception: return None` around a function that already absorbs its own errors. Catches nothing, logs nothing, and this is the update-hint source for the shell. |
| `updates/checker.py:86` | `max(artifact.size + 1, 1_048_576)` — `1_048_576` is `MAX_MANIFEST_BYTES` re-typed as a literal in a different module, and the floor is a real decision documented with a "what" comment. This is the **only** size ceiling on the network read. |
| `updates/cache.py:30` | A `checked_at` in the future yields a negative age, which is `<= max_age`, so the entry stays fresh for as long as the clock is behind. The cache also uses `time.time()` (wall clock) while the rest of the codebase routes through `core/clock.py`, so **the test clock cannot age the cache**. |
| `updates/cache.py:61-63` | `stat()` and `sha256_file()` read the file at different instants, so `mtime_ns`/`size` can describe different bytes than `sha256`. The docstring argues `(mtime, size)` is unreliable — yet both unreliable keys are carried in the "Single source for content identity". |
| `updates/sources.py:104-105` | `if response.status == 304: raise _NotModified()` is **dead** — `OpenerDirector` routes any non-2xx to `error()` and raises `HTTPError`. The code *knows* this: `_handle_url_error` exists solely to translate the `HTTPError(304)`. |
| `updates/sources.py:116-126` | Retry backoff is `time.sleep(attempt)` — 1 s then 2 s, fixed, no jitter, not applied to the manifest timeout budget, with no cap on the aggregate. |
| `updates/sources.py:129-139` | `_with_retries(op)` has no parameter type and no return type, so the "single source" is invisible to the type checker at both call sites. The shared `Request`/`opener` reuse is undocumented, and the `"wb"` truncation is what makes the retry correct. |
| `updates/sources.py:180-187` | `fetch_artifact_bytes` has **zero call sites**. A "Single source" with no callers. |
| `updates/sources.py:28-33` | `TestManifestSource` is a **test double shipped in the production module** with zero call sites. Because it is named `Test*` and lives in an importable module, pytest attempts to collect it and emits `PytestCollectionWarning`. |
| `updates/sources.py:242-257` | `split_manifest_url` re-derives the `.json`-suffix predicate three more times instead of calling the existing `has_json_suffix` (documented as "Single source for manifest-path check"), and one of its branches is provably dead. |
| `updates/sources.py:224-228` | `source_for` re-does the dispatch its only caller already did, then **discards the channel** that `split_manifest_url` computed for it. |
| `updates/sources.py:190-196` | `max_bytes: int \| None = None` immediately collapses to a non-null default. One line does the same; the sentinel exists only to support one test call. |
| `updates/manifest.py:25` vs `policy.py:10-16` | The version regex admits `01.2.3` (leading zeros), which PEP 440 rejects. `_parse_version` then raises a **bare `ValueError`**, which is not an `ApplicationError`, so it routes to the C-05 masked card. A release tagged `v01.x.y` produces a mystery failure on every client. |
| `updates/manifest.py:51-55` | The validator checks co-presence but **not ordering** — a manifest with `schema_min: 12, schema_target: 3` validates, producing a migration that downgrades and a rollback that can never succeed. |
| `updates/manifest.py:76-77, 90-91` | The size check is performed **three times** on one read path, and at `:91` the raise is *inside* `try: … except OSError` — correct only because `UpdateVerificationError` is not an `OSError`, a structural accident rather than a decision. |
| `updates/manifest.py:66-69` | `e.errors()` is called **three times**, re-serialising the whole error list. |
| `updates/manifest.py:98-99` | `load_manifest_dict` skips both size and parse validation. Correct by design, but of the module's three public entry points only one has a size story. |
| `updates/verifier.py:20-28` vs `:31-35` | `verify_artifact` is `verify_artifact_content` plus a filename check, but `verify_artifact_content` is **public** and does not check the filename — and `checker.py:87` calls it directly. The comment at `:48-50` is only true of `verify_artifact`. |
| `updates/verifier.py:27` | `f"sha256 mismatch: {digest} != {artifact.sha256}"` echoes 128 hex characters into a user-facing error returned verbatim. |
| `updates/verifier.py:59` | `platform_key` is `None` at every production call site and non-`None` only at `release/verify_release.py:67`. Widening the client verification API for a build tool inverts the dependency. |
| `updates/signing.py:20-27` vs `:93-102` | The "parse a strict hex key" logic is written twice, and the copies **diverge on length validation**: `_strict_hex_key` has no 32-byte check, so a corrupt trust key's `ValueError` is caught and re-raised as `"invalid manifest signature"` — a trust failure masquerading as a signature failure. |
| `updates/signing.py:50-57` vs `:66-73` vs `audit/signing.py:186-195` | The Ed25519 verify block is duplicated **three times**, differing only in the message. |
| `updates/signing.py:9-12` vs `audit/signing.py:116` vs `:148` | The key-identity derivation exists **three times** in two packages, and the third re-derives the id from the *filename* rather than the key. |
| `updates/signing.py:88-90` | `verify_artifact_signature_streaming` — a deprecation shim with **zero** call sites and no deprecation date. |
| `updates/signing.py:24, 34` | `"ed25519:"` is a bare string literal where `KEY_PREFIX` is defined 18 lines up in the same file and re-defined in `audit/signing.py`. `trust.py` hardcodes it twice rather than import it — a sign the constant is in the wrong module. |
| `updates/policy.py:29-35` | Five positional parameters, **two of them booleans with defaults**, called positionally with all five. Two adjacent `bool` parameters in a positional call is the classic boolean trap; swapping them inverts the bypass. `forensic_active` is a *derived* value, and letting the caller pass it is what let the dead gate (C-02) go unnoticed. |
| `updates/policy.py:42` | `CHANNEL_COMPATIBILITY.get(channel, {channel})` — the default can never be reached, and if it were it would be the wrong fallback (silently allow). |
| `updates/policy.py:4` vs `:11` | `Version` is imported twice, the second shadowing the first, inside the function whose return annotation uses the module-level one. |
| `updates/policy.py:60-72` | `raw_machine` is `strip_controls`-ed before going into an error string; `sys.platform` is **not**, in the very next expression, feeding the same error. |
| `updates/trust.py:6-16` | A module-global cache that saves one `mkdir` syscall, with no reset path — which makes it untestable in-process. The codebase's convention for this pattern is `core/clock.py` (`_current_clock` + `set_clock`/`reset_clock`). |
| `updates/service.py:47` | The shell path validates `limit >= 0` but has **no ceiling**, while Typer caps at 500. `update history --limit 10000000` from the REPL materialises a million DTOs. `offset` is validated but is `0` at every call site. |
| `updates/service.py:13-41` | A **19-field** hand-written constructor duplicating the model's column set. Nothing enforces that the two stay in sync; a renamed DTO field fails only at runtime. |
| `updates/service.py:58-61` | `write_result_marker` is a pure delegation to a filesystem module with a different signature. It exists only so two test files can reach it — **tests are driving the API shape**. And a *service* delegating to a filesystem module is the layering inverted, not enforced. |
| `updates/models.py:15-16` | An index on `transaction_id`, which **no query in `src/` filters on**. Write cost with no read path. |
| `updates/models.py:39-41` | `_coerce_utc` calls `coerce_utc` (which *assumes* UTC for naive input) rather than `require_utc` (which *rejects* it) — and `require_utc` is documented as *"Single source for validators"*. |
| `updates/models.py:9` + `service.py:6` + `dto.py:6` | Three modules import `now_utc` through **two different module paths** for the same symbol. |
| `updates/models.py:36` vs `dto.py:13` | Two default sources for `started_at`; `service.py:37` always supplies it, so the column default is unreachable. |
| `updates/domain.py:10-11, 29-30, 35-36` | Two enum members and their transition edges have **no producer** outside a test shaped around the dead code. `lifecycle.py:369` goes `AVAILABLE -> READY_TO_INSTALL` directly, so **the state machine cannot represent a deferred update** — the single most common non-success outcome. |
| `updates/domain.py:62-65` | `contains` is documented as the *"Single choke point for channel validation"* and is bypassed by `core/settings.py:53`. |
| `updates/dto.py:17-24` vs `manifest.py:42-49` | The channel validator is copied verbatim — **identical method name `_channel_known`, identical body** — differing only in the message. The method name is defined twice in one package. |
| `updates/dto.py:42-49` | The allowed failure stages are re-enumerated instead of derived from the enum that declares them. |
| `updates/dto.py:11-15` vs `:54-65` | The DTO's fields are split by **30 lines of interleaved validators**, so the identity fields are separated from the metadata fields in every serialised output and every validation error message. |
| `updates/dto.py:90-112` | `from_model(m: object)` with **20 `getattr` calls** defeats the type checker: a renamed column raises `AttributeError` at runtime, not at type-check time, and the two `default=False` defaults are dead because the columns are `nullable=False`. There is no import cycle. |
| `updates/commands.py:25-27` + `updates/renderers.py:24-28` | `"✓"` is hardcoded, bypassing the platform-fallback helper that exists for exactly this. On a cp437/cp850 Windows console (a supported target) these raise `UnicodeEncodeError`. |
| `updates/commands.py:80-99` vs `shell_handler.py:51-70` | The same table is rendered twice with the empty-message string duplicated verbatim, and the documented "JSON-vs-table dispatch single source" is used by **neither** surface. The CLI also prints a trailing hint the shell omits. |
| `updates/commands.py:16-22` | `dict[str, object]` is invariant in the value type, so the annotation is technically incompatible with the `dict[str, Any]` parameter it is passed to. |
| `updates/commands.py:48-58` + `settings.py:500` | A 6-tuple return forces two `_`-discard variables at the only call site. Six positional elements where four matter is a signature that will be mis-ordered silently. |
| `updates/shell_handler.py:25-26, 39-49` | The whole shell surface is a re-implementation that drops the CLI's options: `_ = args` explicitly discards the parameter that should be used, so `update check --output json` from the REPL is **silently a no-op flag**. |
| `updates/shell_handler.py:8-13, 72-74` | A Typer app stored in `self._app` and re-exposed through a pass-through property — two members of pure indirection over a module constant. |
| `updates/errors.py:4-39` | Seven empty subclasses with **no documented assignment of failure classes**, so the wrong-class assignments in H-24 and H-14 were free to happen. |
| `updates/renderers.py:111-124` vs `:188-195` | The draw throttle is applied **twice** — in `on_bytes` and in `_draw`. And because `_last_draw` is only advanced inside `_draw`, the `on_bytes` test is evaluated against a stale value on every byte. |
| `updates/renderers.py:153` | `if any(status != PENDING for …)` is reached only on the failure path, where at least one stage is already set. The guard never suppresses. |
| `updates/renderers.py:82` | `product: str = "Trace"` — the sole caller passes the manifest's lowercase `"trace"`. The reachable value is lowercase; the unreachable default is title-case. |
| `updates/renderers.py:90` | `self.tty = console.is_terminal` — an attribute named `tty` holding a bool. |
| `updates/renderers.py:126, 135, 147, 160` | A redundant `current` parameter alongside `dto.from_version`, used inconsistently: one branch reads the DTO, two read the parameter. |
| `updates/renderers.py:7` vs `checker.py:24, 43, 59` + `lifecycle.py:123` | `renderers.py` imports its DTO at module scope while the rest of the package imports peers inside function bodies. One convention or the other. |
| `updates/pip_backend.py:74` | `def pip_health(manifest, staged)` is a module-level function written with a method signature — `manifest` lands in the `self` slot. A test enshrines the confusion, so a type checker cannot see these calls. |
| `updates/pip_backend.py:47` + `:91-99` | `--no-deps` means a release that adds a dependency installs "successfully" and then fails at import. The docstring asserts deps "ride fresh installs" — a policy unverifiable by the client and enforced nowhere. The health check would not catch it. |
| `updates/pip_backend.py:24` | `getattr(sys, "base_prefix", sys.prefix)` — if `base_prefix` were ever absent the default makes the comparison `True`, classifying a system interpreter as *not* a venv. Unreachable in 3.3+ and semantically backwards. |

### 4.6 TUI

| Location | Finding |
|---|---|
| `tui/app.py:121-126` | `on_mount` calls `current_view()` while the app itself admits the content mounts **lazily** — so the initial focus is a coin flip, and `current_view()`'s bare `except Exception` swallows the resulting `NoMatches`, so the focus silently never happens. |
| `tui/app.py:193-199` | `except Exception: return None` collapses three distinct failure classes into one silent `None`. This is why H-68 stayed hidden. |
| `tui/app.py:90` vs `screens/cases.py:40` | `r` is bound to both `refresh` (App) and `recent` (Cases). Textual resolves the focused widget first, so with the `DataTable` focused — which is exactly what `focus_default()` does — `r` fires `action_recent`, never `action_refresh`. |
| `tui/app.py:143-147` | `action_refresh` does not cancel the pending search debounce, so pressing `r` mid-debounce produces two back-to-back DB queries and a repaint over the manual one. |
| `tui/app.py:11-17, 84-94, 112-118` + `palette.py:19-21` + `actions.py:6-13` | The tab set is defined **six times** across those locations, including a hardcoded stale-id set to reconcile the fifth against the fourth. |
| `tui/app.py:33, 57, 81` vs `tui/theme.py:23, 25` | Two theme variables are **never referenced by any CSS rule** (verified). `$warning`/`$success` are also unused. |
| `tui/app.py:28` | A hex literal equal to `THEME_TOKENS["value"]` and already available as `$text` — used two lines away in the same block. |
| `tui/app.py:93` + `forms.py:20, 40` | The `q` quit binding is on the `App` and **no modal re-declares it**, so on a modal screen `q` quits the whole app. |
| `tui/app.py:119, 122` | The hint bar is written twice with the identical value. |
| `tui/actions.py:35-49` | `confirm_overwrite` is a **single-implementation abstraction** implementing a *second, different* overwrite policy than the CLI. Two policies for one file-safety decision, and `Path` is imported *inside* the function for a single call. |
| `tui/actions.py:21-32` | `run_guarded` is the correct pattern but is applied only to case mutations and audit export. Four other places hand-roll their own `try/except Exception` → `notify` handling. |
| `tui/actions.py:12` | A dead alias mapping an id that exists nowhere, with no test. |
| `tui/actions.py:21, 35` | `view: Any` on both shared helpers. The real contract is narrow and is spelled out only in prose. |
| `tui/forms.py:99-112` | The normal save path is reached by **raising and catching `IndexError`**. The docstring describes intended behaviour the code only achieves incidentally, and `except ValueError` is also masking a real bug. |
| `tui/forms.py:116-122` | Only `title` and `examiner` are validated; `number` is passed through unvalidated — and neither the CLI wizard nor Typer format-checks it either, so the `YYYY-CODE-XXXX` contract is documented in three help strings and **enforced in zero places**. |
| `tui/forms.py:117-118` | `values.setdefault(...)` calls are load-bearing but read as no-ops, because `values` was just built from exactly the field keys. Two constant tuples + two `setdefault`s encode "which mode am I in" implicitly. |
| `tui/forms.py:17, 37, 129, 153, 196, 245` | Every modal subclasses both `_BaseModal` **and** a parameterised `ModalScreen[...]`, re-entering a base already in the MRO — six classes, one repeated mistake. |
| `tui/forms.py:14, 20, 40` | `ESCAPES` is a module-level `list` assigned **by reference** as `BINDINGS` on two classes, so an append to one mutates three. Line 40's reassignment is a no-op that exists only to shadow the base with the same object. |
| `tui/forms.py:245-275` | `YesNoModal` has no `on_mount` focus call, unlike the other three modals. Focus lands on `#yes` by default, so **Enter immediately confirms** an archive/restore/purge. |
| `tui/forms.py:88` | A comment coupled to a hardcoded `idx < 4` and a hardcoded `grid-size: 2`. Add a 7th field and the comment silently becomes false. |
| `tui/forms.py:27, 167`, `cases/shell_handler.py:337-338`, `cases/commands.py:36` | The required-field marker takes **four** different forms across the three surfaces. |
| `tui/forms.py:144-145` | Re-imports what lines 10 and 12 already bind at module scope, and drops `widgets.DossierScroll` for an inline `VerticalScroll`. |
| `tui/palette.py:61` | The fuzzy engine matches on the command **id** only, so the `label` and `hint` a user actually reads are **not searchable**. Typing `seal` matches nothing; typing `bundle` matches nothing. |
| `tui/palette.py:57, 61` | `limit=10` over 15 commands means the last 5 are invisible on empty input — including `updates-install`. |
| `tui/palette.py:127-128` | The same row appears **twice**, so the Keys overlay prints `u / install update` on consecutive lines. The visible symptom of the next finding. |
| `tui/palette.py:96-132` | `GROUPS` is a manual copy of the four `BINDINGS` lists and has already diverged three ways: the duplicate; a tab name that does not exist; and an Enter description that contradicts the implementation. It should be derived by walking the real `BINDINGS` class attributes. |
| `tui/palette.py:134-135` | `KEYS` is kept for tests that import it. **No test imports it** (verified). The comment is factually wrong and the attribute is dead. |
| `tui/palette.py:46-48` | `_app_ref` is stored and **never read** (verified), and the caller bothers to pass `self`. |
| `tui/theme.py:37-43` vs `core/ui/renderers.py:307-311` | `status_text` does not strip underscores or normalise case, so a lowercase or underscore-bearing status renders `under_review` in the default colour while the terminal renders `REVIEW` in amber. Two implementations, two answers. |
| `tui/theme.py:38` | *"Byte-identical to \`CasesView._status_text\`"* — **`CasesView._status_text` does not exist** (verified). The comment points at a deleted method, and it is precisely the re-implementation that should have been removed. |
| `tui/theme.py:46-48` | `health_dot` has **zero** call sites. Its docstring claims *"Single source for health pills"* — but both pills are inlined elsewhere. |
| `tui/theme.py:96` + `widgets.py:42` + `cases.py:104-106` + `audit.py:96-98` | The table header is computed **twice per view**, and the count suffix is duplicated. The `on_mount` write is always superseded. |
| `tui/theme.py:37, 46, 58, 67, 79, 90` | 5 of 7 functions carry a suppression, but one has **no annotations and no ignore** — three conventions in one file. |
| `tui/theme.py:84-86` | The `"◌ "` fall-through is the PENDING rendering, but the only caller `continue`s past PENDING before ever calling it. Dead branch. |
| `tui/widgets.py:66-69, 72-75` | The "single source" cursor repaint swallows every per-cell failure with a bare `except Exception: pass`, so an off-by-one is invisible forever. The `row_count` guard already prevents the real failure mode. |
| `tui/widgets.py:94-95` + `audit.py:86-87` `[VERIFY]` | The cursor is read **after** `table.clear()`, and Textual's `clear()` resets the cursor to row 0 — so `cursor` is always 0. Pressing `r`, switching tabs, or completing any mutation jumps the user from row 40 back to row 1. The clamp, the `_last_cursor` bookkeeping and the O(1)-repaint premise serve a behaviour that cannot occur. |
| `tui/widgets.py:24-27` | `except Exception: width = 60` swallows every layout failure and substitutes a magic number. |
| `tui/widgets.py:23-28` | `rule_width` is one of **four** copies of the divider-width formula and the caps **disagree**: 66, 66, **60**, 66 — two different caps ~20 lines apart. |
| `tui/widgets.py:120-121`, `audit.py:112-113` | Redundant guards — `repaint_selection` already range-checks both indices. |
| `tui/screens/cases.py:230` vs `:90` | The same failure class is caught two different ways in the same file. A `SQLAlchemyError` from `_dossier_events` propagates out of the row handler and **crashes the view**; an identical error from `_query` becomes a toast. |
| `tui/screens/cases.py:225-232` | A failed ledger read is **never cached** — the key is only written on success, so the guard stays false forever. With the DB down, each keypress issues a fresh failing query. |
| `tui/screens/cases.py:248-254` | The direct cause of H-68. Three problems: the mapped method doesn't exist; the `__name__.startswith("action_")` guard is **tautological**; and `.replace` is a substring replace, not a prefix strip. |
| `tui/screens/cases.py:262-265` | `TAB_HINTS` promises `"Enter Open"`. The method is even named `_opened`. Enter moves focus and opens nothing; afterwards `↑/↓` scroll the dossier instead of the table, and nothing scrolls it back to the top. |
| `tui/screens/cases.py:153, 181, 197, 222, 234` | Five methods have fully unannotated parameters despite the DTO being imported, each with a suppression. `cases.py:109` is fully annotated *and* carrying the *untyped-def* ignore. |
| `tui/screens/cases.py:20` | `tui/theme.py` has no `THEME_TOKENS` of its own; it works only because that module imports the name. Two import paths for one token table, and the TUI one breaks the moment `theme.py` stops needing it at module scope. |
| `tui/screens/cases.py:26, 67, 137, 139` | Three different strings for two states. |
| `tui/screens/cases.py:110` | A function-local re-import of a name already bound at module scope. 12 of 13 local imports in this file are legitimate lazy loads; this one is a leftover. |
| `tui/screens/cases.py:27`, `palette.py:148`, `theme.py:40`, `cases.py:144` | `_TITLE_STYLE` hardcoded at **four** sites — and the colour is not in `THEME_TOKENS`. |
| `tui/screens/cases.py:373`, `commands.py:184`, `shell_handler.py:486` | The TUI passes no actor to `close_case`, so the `CASE_CLOSED` audit event is attributed differently depending on which surface sealed the case. |
| `tui/screens/audit.py:137-145` | `verify_event` runs on every cursor move with **no** `try/except`, unlike its twin. A malformed `payload_json` raises straight out of an event handler, killing the view. |
| `tui/screens/audit.py:128-135` vs `:222-229` | The entire empty-state branch is copy-pasted, byte-identical including the long string literal. |
| `tui/screens/audit.py:123-180` vs `audit/renderers.py:207-293` | The TUI event detail is a hand-built `Text` **twin** of the terminal dossier. **~45 duplicated lines**, and the terminal version additionally shows the three hash rows and the UTC zulu, which the TUI silently omits — so **the TUI's forensic evidence view is less complete than the CLI's**. |
| `tui/screens/audit.py:187` | *"Open the Integrity tab"* — there is no Integrity tab; it is a **section** of Settings, as two other modules both know. |
| `tui/screens/audit.py:79` | `scope_widget.display = bool(scope)` inside `refresh_data` forces a relayout on every debounced refresh. |
| `tui/screens/audit.py:74`, `cases.py:23`, `settings.py:17` | Three modules each export a constant *named* `TABLE_ID` with three different values. |
| `tui/screens/audit.py:96-98` vs `cases.py:20` | The same helper imported locally in one file and at module scope in its sibling. |
| `tui/screens/settings.py:114-120` | `refresh_data` writes `view.index` and then immediately re-reads the selection from `highlighted_child`, a reactive that resolves asynchronously. The code is self-contradictory either way: it sets one variable and reads another to learn the same fact. |
| `tui/screens/settings.py:354-379` vs `core/cli/doctor.py:57-85` | The same four checks in the same order with the same pass/fail semantics, rendered differently — and it reaches into another module's **private** symbols. 26 duplicated lines plus an underscore-namespace violation. `run_doctor` raises `typer.Exit`, which is exactly why the checks were never extracted into a shared `collect_diagnostics()`. |
| `tui/screens/settings.py:492-503` | The install path discards two of six return values and passes **no** `on_bytes` — so the TUI's `on_bytes` is dead, and it is a no-op anyway. The download progress bar is simply **absent from the TUI**. |
| `tui/screens/settings.py:576-581` | A view reaches into the App's hint bar and imports the App module's constants, in a file whose docstring claims *"no view-to-view imports"* — and the `try/except: pass` guarantees the hint silently stops tracking. |
| `tui/screens/settings.py:20-28` vs `:140-148` | `SECTIONS` and the section→renderer map are two parallel literals kept in sync by hand, and the dict is rebuilt on **every** render. |
| `tui/screens/settings.py:206, 463, 509` | The same error string is truncated to 300, 500, 500, 300 — four policies, no named constant. A fifth leaves it untruncated. |
| `tui/screens/settings.py:175-180, 185-187, 376-379` | Three inline health-dot renderings, bypassing both the declared single source and the dead `health_dot`. And two hex literals are hardcoded where module constants are defined — one of which exists in no token table. |
| `tui/screens/settings.py:152, 273, 171-172` | `f"Version unavailable ({exc})"` for a database snapshot *and* an integrity check. Three surfaces for one failure class, one of them mislabelled. |
| `tui/screens/settings.py` (whole file) | **24 bare `except Exception: pass` blocks** plus 6 `except Exception as exc` handlers, and 42 function-local imports. The `_TuiProgress.on_stage` failure path silently desynchronises the install progress UI from reality, mid-update, with no log. |
| `tui/screens/settings.py:396-425` vs 4 other sites | The `resolve_channel → resolve_manifest_target → cached_check` triple is written **five times**, and the payload→human-sentence mapping **twice** — verbatim identical to `updates/renderers.py`. ~14 duplicated lines, 2 sources, 3 surfaces. |
| `tui/screens/settings.py:428-430` | A 20-line function whose entire body is wrapped in two nested `try/except: return` blocks, so a `cached_check` failure is indistinguishable from "no update available". Plus a dead import. |
| `tui/screens/settings.py` (587 lines, ~30 methods) | Owns 13 unrelated concerns. `action_migrate` re-implements `db_commands.py:127-138` and is the only view action that reaches for `mgr.engine`. |
| `tui/screens/settings.py:268, 331, 358` | Three section renderers take `width: int` and immediately discard it with `_ = width`. |

### 4.7 Top-level CLI

| Location | Finding |
|---|---|
| `cli/main.py:12-17` vs `:53-63` | `invoke_without_command=True` is set **twice**, and the version flag is typed `bool` with a `None` default. |
| `cli/main.py:47-50` vs `:66-67` | The version path is the only thing in the file that doesn't end in an implicit 0, and it does so via a different mechanism than every other command. **Three exit mechanisms, one file.** |
| `cli/shell.py` | REPL history, multi-line input, `Ctrl-C`/`Ctrl-D`, exception swallowing, dispatch fall-through and output flushing follow the same shape as the three handlers' own `try/except Exception` blocks, without a shared base. `BaseShellHandler` owns only `unknown_action`. |
| `cli/suggest.py` + `core/cli/completion.py` + `cases/shell_handler.py:259` | **Three** completion engines — one for Typer, one for the REPL, one inline — each with its own ranking, filtering and duplicate suppression, and the inline one is the **O(n²)** version of a job `filter_completions` already does. |

---

## 5. Low findings

Genuine nits, not padding. Grouped for compactness.

### 5.1 `core/`

- `core/database/base.py:20-31` vs `operators.py:49` — `default=lambda: now_utc()` (4 lambdas) vs `default=now_utc`. Same intent, two spellings, same package.
- `core/database/repository.py:9`, `core/cli/recovery.py:27`, `updates/lifecycle.py:123`, `updates/models.py:9` — `now_utc` imported from `core.domain` (a re-export) rather than `core.clock` (the definition) in **4 production modules**. `domain.py` has no `__all__`, so the accidental re-export type-checks.
- `core/database/repository.py:16, 25, 68, 73` — four `# type: ignore[no-untyped-def]` on the module's *most reused* helpers (`paginate` is used by 4 production files, `ilike_literal` by 12 call sites).
- `core/database/repository.py:70, 91, 110, 121` — `getattr(self.model_cls, "id")` four times, plus two more `hasattr` duck-typing guards. The class is generic but every query uses string-keyed reflection, so a model without an `id` fails at runtime with SQLAlchemy's `AttributeError` rather than a typed error.
- `core/database/session.py:119-130` — the session context manager is correct (rollback on exception, always close) and is the right pattern; noted only that `BaseService.transaction` and `_ledger_session` each re-wrap it rather than composing.
- `core/settings.py:76, 83` — `Settings.model_fields["database_url"].default` read twice as a reflective lookup rather than a constant. Works in pydantic 2.13.4 but would break if the field were renamed.
- `core/settings.py:10` vs 4 other sites — a module-level `logger = structlog.get_logger()` exists here, and four other `core/` modules create their own inline, one of them *inside a function* in an error path.
- `core/operators.py:108` — `operator.role not in roles` is a raw string comparison with no normalisation, while `parse_enum_value`'s `.upper()` convention is used everywhere else. Fail-closed, but undocumented and asymmetric.
- `core/domain.py:16-19` — `strip_controls` is a good primitive applied at 15 call sites across 4 feature modules. There is no single ingress point where text is guaranteed sanitized, so correctness depends on every future caller remembering. `[VERIFY]` whether any title/notes path can reach the DB unsanitized.
- `core/clock.py:28-37` — `set_clock`/`reset_clock` have zero production callers (a legitimate test seam), but the seam does **not** reach pydantic-created entities via `BaseEntity.default_factory`.

### 5.2 `cases/` and `audit/`

- `cases/domain.py:101-102` — `if case.status == target: return case` is unreachable; the service already raises before calling.
- `cases/models.py:18` — `id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)` has no explicit type, inferring from the annotation; every other column is explicit. Same for `audit/models.py:18`.
- `cases/repository.py:197-200, 216` — two `now_utc()` calls per mutation, so `archived_at` and `updated_at` can differ by microseconds on the same row. The `onupdate=now_utc` mixin already covers part of it.
- `cases/repository.py:298` — bare `range(10000)`; the same 10 000 appears as the named `_MAX_GAPS` in `audit/verifier.py:20`.
- `cases/repository.py:286-288` — `_is_candidate_free` is a correctly-named, correctly-documented single guard used exactly once. A single-use abstraction.
- `cases/renderers.py:123` — `# type: ignore[list-item]` on `rows.append(["" for _ in columns])`; `render_minimalist_table(rows: list[list[Any]])` accepts `list[str]` without complaint.
- `cases/renderers.py:214` and `audit/renderers.py:288` — `width=max(kv_width(bp), 16)` byte-identical, while `audit/renderers.py:236` in the same function uses bare `kv_width(bp)`. A magic floor with no named constant.
- `cases/renderers.py:147` → `:232` — `_closed_value` is a forward reference 85 lines below its use, which is why the "single source for the dossier" docstring is easy to miss.
- `cases/shell_handler.py:6` + `:105` — two `from trace_core.cases.domain import …` statements, the second local, covering the same module.
- `cases/shell_handler.py:377` — `# type: ignore[union-attr]` on a line already narrowed by an `and` guard.
- `cases/shell_handler.py:372, 377`, `audit/shell_handler.py:171, 182` — `ctx: ShellContext | None = None` on a method only ever called with a ctx. The `Optional` exists to support a call signature no caller uses.
- `audit/domain.py:65-67` — hash fields constrained by length only; see H-49.
- `audit/verifier.py:117-119` — `_retain_first` is a single-use one-liner whose docstring claims "Single source for ledger range tracking"; nothing else tracks ledger ranges.
- `audit/builder.py:8` + `:33` — one function-local import of a name from the same module already imported at the top; plus `import sys` inside a helper.
- `audit/builder.py:114, 126` — `sid: UUID | None` on two builders while the other four take `UUID`. Both call sites pass a real `case.id`. `Subject.id` is likewise never `None` in practice.
- `audit/models.py:28-43` — see H-40.
- `audit/renderers.py:331` etc. — see §4.4.

### 5.3 `updates/`

- `updates/lifecycle.py:457` — `prune_retention(base, keep_backups=3)` restates the module default `RETENTION_BACKUPS = 3` as a literal. Two sources of truth for a retention policy.
- `updates/lifecycle.py:372-374` — a private-looking alias for a public function, in a function that already imported the module.
- `updates/lifecycle.py:288` — `started_at: started_at,  # type: ignore[arg-type]` is spurious (the type is correct and the value comes from `now_utc()`), and a bare `type: ignore` on a `BaseDto` field will mask a future real error. The only such ignore in the file.
- `updates/lifecycle.py:227, 416, 427, 429, 444, 446, 464, 466, 484, 486` — `migration["schema"]` and `migration["backup"]` are bare dict-key reads against an untyped `-> dict`, on a forensic record. Should be a dataclass or `TypedDict`.
- `updates/migration.py:92, 94` — `max(applied, default=0)` computed twice in the same function.
- `updates/migration.py:150` — `_confine_backup_path(src)` re-resolves a path it already returned, so it cannot fail. The comment above it claims this is the TOCTOU fix.
- `updates/migration.py:150-155` — the `O_NOFOLLOW` open/close sequence is a no-op on Windows (`getattr(os, "O_NOFOLLOW", 0)` is `0`).
- `updates/migration.py:165, 169, 240` — `import subprocess` and two different `os` aliases inside one function.
- `updates/migration.py:324` + `lifecycle.py:210` + `fs.py:98, 120` — four inline `contextlib` imports for a stdlib module.
- `updates/migration.py:108` — re-imports a module-level name inside a function.
- `updates/migration.py:226, 229` — `check_contained(out, dest)` called twice on the same path in the same block.
- `updates/stages.py:104` — covered in §4.5.
- `updates/cache.py:3` + `:57` — `Path` imported at module scope and then re-imported under a pointless alias inside the function; the local `sha256_file` import is also unnecessary since the module already imports three names from it at module scope.
- `updates/checker.py:22` — see §4.5.
- `updates/dto.py:70` (`# type: ignore[no-untyped-def]`) and 5 sibling module-level private helpers imported inside functions for cycle avoidance that is never documented.
- `updates/errors.py:4-39` — see §4.5.
- `updates/service.py:20-39` — 19 keyword arguments in one constructor call; see §4.5.

### 5.4 TUI

- `tui/palette.py:65` — a no-op f-string.
- `tui/palette.py:78` — `target.removeprefix("cmd-")` guarded by `if target else None`, but `target` is a widget `id` that is always truthy when present. The ternary is dead on one branch.
- `tui/forms.py:21` — `# type: ignore[attr-defined]` on `self.dismiss(None)`, a consequence of the redundant second base.
- `tui/forms.py:20` — the `ESCAPES` type annotation admits `Binding`, which is never used.
- `tui/widgets.py:58-59` — the docstring's justification ("a stale cursor must never crash the view") is sound; the implementation over-applies it.

### 5.5 CLI / release / install / CI

- `cli/main.py:66-67` — see §4.7.
- `release/make_manifest.py:7`, `verify_release.py:5`, `sign_release.py:6` — `sys.path.insert(0, "src")` is **CWD-relative**, not script-relative, and is paired with CWD-relative `Path("dist").glob("*.whl")` and `check_contained(Path(out), Path.cwd())`. The scripts silently assume they are run from the repo root; running them from anywhere else raises `ImportError` or writes outside `dist/`.
- `release/make_manifest.py:50` — `version = tag.removeprefix("v")`; the release workflow triggers on the glob `v*.*.*`, which is not a semver check. `v1.2` and `vx.y.z` pass the glob and fail two steps later with a confusing "invalid manifest" message instead of "tag is not a release version".
- `release/make_manifest.py:81` — `release_id` is the tag, i.e. `version` again. A redundant field carrying zero information, constrained to `max_length=64` for no reason.
- `release/make_manifest.py:52-56` — the 5-line comment is a genuine, well-written *why*, but its last sentence is a speculative roadmap item, and "hash-covered" is misleading — sdist/SBOM/`SHA256SUMS` are covered only by the **unsigned** `SHA256SUMS`.
- `release/sign_release.py:8` vs `:27` — one `cryptography` import at module scope and one inside `main()`, while every other `cryptography` import in the codebase is function-local for cold-start. `import json, os, sys` are top-level while `updates/*` deliberately defers `import hashlib`.
- `release/sign_release.py:46-49` — re-dumping adds fields the pre-signing file didn't have (`published_at: null`, `schema_min: null`, …). Not a bug (sign and verify both go through the model), but the byte output of `make_manifest.py` ≠ the byte output that's signed, and the test asserts against the pre-signing shape. Worth a comment so the next reader doesn't "fix" it.
- `release/verify_release.py:50` — a side-effecting call inside a tuple assignment, inconsistent with the file's own style two lines away.
- `install.sh:88-103` — `trace_bar_for` builds a 20-char bar with two shell `while` loops and string concatenation, twice per redraw, on every 50 ms tick.
- `install.sh:143-146, 210-217` — the progress bar is **time-driven, not work-driven**; `trace_to` just sleeps to the target. Defensible UX, but nothing says so, and a future maintainer will read it as real progress.
- `install.sh:18, 585, 596-598, 622, 659, 671` + `install.ps1:40, 567, 581-583, 613, 638` — the phase percentages `50/66/83` are hardcoded at **six sites per installer** while `TRACE_PHASE_TOTAL=6` is the only real source. Add a phase and the bar silently desynchronises.
- `install.sh:276, 622` — no `--connect-timeout` / `--max-time` / `--retry` on any curl. A hung TLS connection hangs the installer forever, and the `kill -0` poll loop spins indefinitely. `install.ps1` has the same gap.
- `install.sh:281` — GitHub JSON parsed with `grep`/`cut`; works against GitHub's pretty-printed output by luck of formatting and breaks on any tag containing `"`. `install.ps1:279` uses `Invoke-RestMethod` (correct). The system `python3` is already located, so `json.load` was available.
- `install.sh:673-682` vs `install.ps1:652-663` — the two launchers differ in quoting, and only one is path-quoted. The sh side emits a POSIX launcher containing a `cygpath -w` Windows path when run under Git Bash; the ps side emits `"$TraceExe" %*` with no `call`, so a launcher argument containing `&` breaks.
- `install.ps1:405-427` vs `install.sh:442-454` — the askpass helper is correctly removed in a `finally` on the ps side (the sh side leaks it on failure), but the token is placed in `$env:TRACE_GIT_TOKEN` for the duration, exposing it to every child process; the `.cmd` passes it through a batch expansion, so a token containing `%` or `&` would be mangled. Neither script validates token shape.
- `install.ps1:666` — `$UserPath -notlike "*$UserBin*"` interpolates a path into a `-like` **pattern**; `[`, `]`, `*`, `?` in the path would misfire. `$UserPath` is `$null` on a profile that has never set a user PATH, producing a trailing `;`.
- `install.ps1:167-223` — `Invoke-LiveCommand` serialises a scriptblock through `.ToString()` and re-`Create`s it inside a job. This silently breaks for any closure over non-serialisable state, defeats PowerShell's scope chain, and means `VerboseMode` inside the job is a *different* variable.
- `install.sh:1` / whole file — **zero uses of `local`**. Every function leaks globals, including a shared `TRACE_TMP`/`TRACE_STATUS` pair that `trace_run` and `trace_run_live` both clobber and `trace_collect_tmp` reads. It works today only because the call graph never nests them.
- `install.sh:29` — the trap neither cleans temp files nor aborts on INT/TERM. A POSIX trap handler for `INT`/`TERM` that does not `exit` **resumes execution** after the interrupted command, so Ctrl-C does not abort the install and `set -e` will not fire.
- `install.sh:429, 674, 651` — install dirs inherit the umask; forensic storage ends up world-readable (typically 0755) in three places. The codebase has a single-source, explicitly-documented guard for exactly this (`ensure_dir` with `mode=0o700`) and the installer bypasses it.
- `install.sh:547-553` + `install.ps1:532-534` — the Python version gate is a two-part comparison (`major >= 3 AND minor >= 12`), so a hypothetical `4.0` is rejected and `4.12` accepted. `packaging` is a hard dependency and is available to do this properly.
- `install.sh:543, 572-580` + `install.ps1:554` — the verbose step `[2/6]` is never printed, unlike all five siblings. Cosmetic, but the documented "step-by-step output" is missing a step.
- `install.sh:526` / `install.ps1:500` / `release/verify_release.py:56` / `settings.py:17` — four independent implementations of "read the project version" (two `sed`/`Select-String` regexes, one `tomllib` parse, one pydantic literal). A `trace version --short` CLI call is the single source.
- `install.sh:347-352` — `--version` with no value silently installs `main`: `${2:-}` yields `""` with no error, and there is no usage message. `--help|-h` is handled properly; this flag is not.
- `install.sh:255-271` — the tag validator treats the tag as a **BRE** (`grep -q "$TRACE_TAG"`, so `.` is a wildcard and `v1.2.3` is "validated" by `refs/tags/v1.2.30`), matches by substring rather than exact `refs/tags/$TAG`, and — if neither `git` nor `curl` is present — the function's last statement is a false `if` condition, which per POSIX **exits 0**. The unvalidated `TRACE_REF` then flows into `git clone --branch`. `install.ps1:262-263` has the substring flaw but not the fail-open.
- `install.sh:295` — `sed -n "${TRACE_PICK}p"` splices raw `read` input into a sed program. Input such as `1;w /tmp/pwned#` becomes the script `1;w /tmp/pwned#p`, which makes GNU sed **write the pattern space to an arbitrary file** as the installing user. `install.ps1:302-306` correctly uses `TryParse` + bounds.
- `install.sh:19` — `set -eu` present, `pipefail` absent (defensible on dash), but the pipelines were not restructured to compensate: `git ls-remote | grep -q`, `sha256sum | cut`, and two `curl | tar`. For the last two, a failed `curl` that emits nothing can leave `tar` exiting 0 and the script continuing with an **empty** app dir, failing later with a confusing "dependencies" error. The pinned branch already uses the correct temp-file pattern.
- `install.ps1:20-36` — unknown flags are **silently dropped**; there is no `else` branch. `install.sh:385-388` correctly errors and exits 2. A typo (`--reinsatll`) is a no-op on Windows and a hard abort on POSIX.
- `install.ps1:14, 20-36` — `-SkipDbMigration` is declared but the manual `$args` loop has **no** `--skip-db-migration` branch and the usage text doesn't list it, so it is silently ignored through the documented `irm | iex` invocation. `install.sh:657` honours the env var. Three mechanisms for one feature, one of them dead.
- `install.ps1:495` — `Set-Location $RepoRoot` is never restored. Run as `.\install.ps1` from a prompt (not `&`, not piped) the script shares the caller's runspace and **permanently changes the user's working directory**.
- `install.ps1:20-36, 270, 279, 433, 446, 613` — no TLS *policy* is set. No cert-validation bypass anywhere (good), but equally no up-grade: under Windows PowerShell 5.1 these calls use the .NET Framework default.
- `install.ps1:598` — the copied `.env` (containing `TRACE_SECRET_KEY`) gets no ACL restriction, while `install.sh:607-608` does `chmod 600`. Divergence on the most sensitive file either installer writes.
- `install.ps1:437-454` / `install.sh:459-485` — the "pin the release" path is only reachable when `git` is absent, and cosign is skipped silently when absent.
- No `shellcheck` in CI for 686 lines of POSIX shell with a `curl|tar` pipeline, user input into `sed`, and `${VAR:+}` expansion. No `PSScriptAnalyzer` in CI for 675 lines of PowerShell (the changelog records *manual* passes). No lint gate for either.
- `.github/workflows/` — the audit found **no** `pull_request_target`, **no** `workflow_run`, **no** unpinned third-party `uses: …@main`, **no** cert bypass, and **no** secrets exposed to fork PRs. The workflow hygiene is genuinely good; the gaps are coverage and the checkout-vs-tag verification (see §9).
- `.env.example`, `requirements.txt`, `.gitignore` — no defects found. The gitignore's evidence-artifact extensions list and the `*.db` rule are correct and thorough; the `.gitignore` entries for `/.test_storage/` and `/trust/` are scar tissue from H-78 and should disappear once the test fixture is fixed.

---

## 6. THE REUSABILITY MATRIX

This is the section the brief centres on. Every row is a duplication verified by reading both copies.

**Totals: 60 duplicated blocks · ~1 100 lines eliminable · ~190 call sites touched · 6 modules that exist only to re-wrap something else.**

### 6.1 The four-layer renderer/theme split — the single largest cluster

| | Lines | Modules |
|---|---:|---|
| `core/ui/renderers.py` | 549 | the shared library |
| `audit/renderers.py` | 343 | feature copy |
| `cases/renderers.py` | 210 | feature copy |
| `updates/renderers.py` | 179 | feature copy |
| `core/ui/theme.py` | 52 | the shared token table |
| `tui/theme.py` | 85 | **re-types 9 of 10 tokens as bare hex** |
| `tui/palette.py` | 128 | a third theme module |
| `audit/dto.py:33-55` | 23 | REPL completion tables in the DTO layer |
| `cases/shell_handler.py:31-65` | 35 | the same, in the handler |
| **Total** | **1 604** | |

**Concretely duplicated:**

| # | Duplication | Sites | Lines | Single source of truth |
|---|---|---|---:|---|
| R-01 | **Status → (label, colour, glyph) resolution.** Three implementations, all using the same fallback hex `#E5EAF0` which is **not in `THEME_TOKENS`**. `core/ui/renderers.py:302-312` also mangles `UNDER_REVIEW` → `REVIEW`; `tui/theme.py:37-43` does not strip underscores at all, so `under_review` renders in the default colour. | `core/ui/renderers.py:302`, `tui/theme.py:37`, `cases/renderers.py:143, 186` | 25 | `core/ui/renderers.py:get_status_style_and_label` — return the glyph too, and have `tui/theme.py:status_text` become a one-line wrapper |
| R-02 | **Health pill / status dot rendering.** `dot_line` is declared the single source; `health_dot` is declared the single source for pills; both are bypassed by three inline renderings. | `tui/theme.py:46, 58`, `settings.py:175-180, 185-187, 376-379` | 22 | `tui/theme.py:dot_line`; delete the dead `health_dot` or wire it |
| R-03 | **Case dossier assembly** — header, divider, key-value grid, divider. `render_dossier` + `create_dual_key_value_grid` exist in the shared library (96 lines) and are referenced **only from tests**, while both features hand-roll the rhythm. The TUI builds a **third** version. | `core/ui/renderers.py:425, 498`, `cases/renderers.py:199-216`, `audit/renderers.py:229-237`, `tui/screens/cases.py:189-212`, `tui/screens/audit.py:152-163` | ~60 | `core/ui/renderers.py:render_dossier` — make the features call it, and the dual-column branch finally gets used |
| R-04 | **Audit event detail rendering.** The TUI's `Text` version is a hand-built twin of the terminal dossier, and is **less complete** (omits the 3 hash rows and UTC zulu). | `tui/screens/audit.py:123-180` vs `audit/renderers.py:207-293` | 45 | `audit/renderers.py` — factor the dossier into data (a list of `(label, value)` rows) and let each surface format it |
| R-05 | **Case table breakpoint ladder.** Written twice with the second docstring admitting it mirrors the first; the header decides by exclusion and the rows by equality, so a new breakpoint silently mis-renders. | `cases/renderers.py:24-65` vs `:84-109` | 42 | one data-driven column spec `[(bp_predicate, [(name, opts), …])]`; the row builder iterates it |
| R-06 | **Migration table breakpoint branching.** Same shape, a second implementation, independently branching on `bp != "XS"`. | `db_commands.py:32-43` vs `:46-64` | 12 | `cases/renderers.py:_case_table_columns` pattern; or one function returning `(columns, rows)` |
| R-07 | **Divider width formula.** Four copies, **two different caps** (66 and 60), 20 lines apart. | `core/ui/renderers.py:167`, `widgets.py:23-28`, `settings.py:137`, `settings.py:218` | 16 | `core/ui/renderers.py:rule_line` + a `rule_width(term_w)` helper |
| R-08 | **`kv_width` magic floor.** `max(kv_width(bp), 16)` byte-identical at 2 sites, bare `kv_width(bp)` at a third in the same function. | `cases/renderers.py:214`, `audit/renderers.py:236, 288` | 3 | one `kv_width(bp, min_width=16)` |
| R-09 | **Terminal-safety / glyph helpers bypassed.** `get_success_icon()` exists for exactly this (cp437/cp850 fallback); hardcoded `"✓"` in 3 places. | `core/ui/renderers.py:56-63` vs `updates/commands.py:25-27`, `updates/renderers.py:24-28` | 3 | `get_success_icon` |
| R-10 | **Pluralisation.** The same 2-line idiom 3 times. | `audit/renderers.py:263`, `cases/renderers.py:168`, `:333` | 6 | one `_plural(n, word)` |
| R-11 | **Table header + count line.** Computed twice per view, count suffix duplicated, the `on_mount` write always superseded. | `widgets.py:42`, `cases.py:104-106`, `audit.py:96-98`, `theme.py:101-109` | 12 | one `header_with_count(columns, n)` owned by `tui/theme.py` |
| R-12 | **REPL completion tables in two different layers.** | `audit/dto.py:33-55`, `cases/shell_handler.py:31-65` | 23 | `cases/shell_handler.py`'s home; `audit/dto.py` should not know about tab-completion |
| R-13 | **Redundant imports inside renderer files.** 8 in `cases/renderers.py`, 12 in `audit/renderers.py`, 4 in `updates/renderers.py`, 1 mid-function in `audit/renderers.py:277`. | 4 files | 24 | module-level imports |
| R-14 | **`THEME_TOKENS` reached through 2 import paths.** | `tui/theme.py:6` re-export vs `core/ui/theme.py`; 4 TUI sites use the indirect path | 6 | import from `core.ui.theme` only |
| R-15 | **Raw Rich style names bypassing `THEME_TOKENS`.** `[dim]` alone is ~30 sites across 6 files, plus bare hex and `style="green"`/`"yellow"`/`"red"` in 8 more. | 6+ files | 30 | `core/ui/theme.py` |

### 6.2 The four-way CLI / REPL / TUI surface duplication

Every command exists in a Typer module, a shell handler, and often a TUI action. The shared *logic* is extracted for some commands and re-implemented for others — and the two extracted subsets differ.

| # | Duplication | Sites | Lines | Single source of truth | Also fixes |
|---|---|---|---:|---|---|
| R-16 | **Typed-number confirmation**, with 3 different cancellation strings. | `cases/commands.py:176`, `cases/commands.py:210`, `cases/shell_handler.py:467` | 14 | `confirm_typed_number(identifier, action) -> bool` in `core/ui/renderers.py`, beside `prompt_confirm` | — |
| R-17 | **Shell flag-completion scaffolding** — "last token is a flag? return its values : filter the table", plus the same `try/except Exception: return []`. | `cases/shell_handler.py:190-217` (28) vs `audit/shell_handler.py:85-147` (63) | ~30 | `BaseShellHandler._complete_flag_value` — the class exists and owns only `unknown_action` | — |
| R-18 | **Audit filter construction + action parsing**, duplicated verbatim. The part that *can* disagree, and does (error card + `Exit(1)` vs silent return; with/without the "Valid actions:" remediation). | `audit/commands.py:19-28, 42-50` vs `audit/shell_handler.py:203-216` | 23 | `parse_audit_filter(...)` in `audit/helpers.py`, next to the already-shared `do_show_list` | — |
| R-19 | **Case status-filter validation + the exact error string**, with the two surfaces raising **different error types** for the identical failure. | `cases/commands.py:94-102` vs `cases/shell_handler.py:108-115` | 17 | `parse_case_status_filter(raw)` in `cases/domain.py`, next to `parse_status_value`/`is_archived_filter` | C-05 |
| R-20 | **`resolve_channel → resolve_manifest_target → cached_check` triple** + the payload→human-sentence mapping, written 5× and 2×. The sentences are verbatim identical to `updates/renderers.py`. | `settings.py:396-425, 432-438, 455`, `updates/commands.py:69-71`, `updates/shell_handler.py:46-48` | ~25 | `updates/checker.py` should return a typed result; `updates/renderers.py` renders it. TUI calls the same renderer. | — |
| R-21 | **Update history table** rendered twice with the empty-message string duplicated verbatim, and the documented JSON-vs-table dispatcher used by **neither** surface. | `updates/commands.py:80-99` vs `updates/shell_handler.py:51-70` | 12 | `core/ui/renderers.py:render_output` | — |
| R-22 | **Tag-count/char-cap rule and its two exact error strings, three sources** — and the pydantic `Field` cap makes the DTO validator unreachable. | `cases/dto.py:19, 21-29`, `cases/domain.py:195-209` | 20 | `cases/domain.py:validate_tags` alone | H-42 |
| R-23 | **The four doctor/diagnostics checks**, duplicated and rendered differently, reaching into another module's **private** symbols. | `settings.py:354-379` vs `core/cli/doctor.py:57-85` | 26 | `core/cli/doctor.py:collect_diagnostics() -> list[tuple[str, bool, str]]`; `run_doctor` becomes a Typer wrapper | H-66 |
| R-24 | **Service factory** — byte-identical 2-line functions, and `BaseService.__init__` already does the fallback. | `audit/commands.py:15`, `cases/commands.py:24` | 4 | `X(session_manager or db_manager)` inline | — |
| R-25 | **DB-manager resolution** — 3 idioms for the same access. | `audit/shell_handler.py:111, 121, 149`, `cases/shell_handler.py:281, 199` | 8 | `core/database/session.py:get_db` | H-74 |
| R-26 | **Case-service construction** per access, with `.session_manager` reached straight through. | `cases.py:54-56, 374`, `settings.py:540` | 6 | a `get_db(ctx)` for the TUI too | H-67 |
| R-27 | **Empty-state copy in the TUI**, 3 copies. | `cases.py:135-140`, `audit.py:128-135`, `audit.py:222-229` | 12 | one `empty_state(widget, has_rows, message)` | — |
| R-28 | **`App` hint-bar ownership** — a view reaching into the App to set it. | `app.py:122, 179`, `settings.py:576-581` | 8 | `self.app.set_hint("settings")` | — |
| R-29 | **Error-card → exit-code path**, with 3 exit mechanisms in one file. | `main.py:47-50, 66-67`, `audit/commands.py:27, 73, 102` | 6 | `core/cli/error_handler.py` + `exit_codes.py` | — |
| R-30 | **Update orchestration** duplicated across CLI, REPL and TUI, with a 6-tuple return discarded at one site. | `commands.py:125-158`, `shell_handler.py:39-70`, `settings.py:492-503` | 25 | a `UpdateInstaller` service returning a small result object | H-25 |

### 6.3 `core/` — the leaf-level utility duplications

| # | Duplication | Sites | Lines | Single source of truth | Also fixes |
|---|---|---|---:|---|---|
| R-31 | **Naive-datetime predicate** — 3 implementations, the third (shorter) is the C-04 bug. | `canonical.py:13`, `domain.py:31`, `renderers.py:264` | 6 | `canonical.py:def is_naive(dt)` | **C-04** |
| R-32 | **`file_lock` / `try_file_lock`** — the same 20-line nested-`@contextmanager` differing in one boolean and `raise` vs `yield`. `try_file_lock` has one production caller. | `fs.py:97-116` vs `:119-136` | 20 | one `file_lock(path, *, blocking=True, raise_on_fail=True)` | §4.1 symlink/`chmod` dup |
| R-33 | **URL scrubbing** — two functions, ~8 duplicated lines, and `sanitized_db_identity` has one caller. | `session.py:137-143` vs `:152-164` | 8 | one `_split_safe(url)` in `session.py`; demote `sanitized_db_identity` to private | H-44 |
| R-34 | **Case-number tail parsing** — the sanctioned helper vs an inline `int(split("-")[-1])` with a bare `except: seq = 0`. | `canonical.py:25-31` vs `completion.py:115-117` | 3 | `canonical.parse_trailing_seq` | — |
| R-35 | **Group-by-case-number logic** — the same 11-line loop, differing by one appended `order.sort(...)`, in a rendering module and a completion module. | `completion.py:161-171` vs `cases/renderers.py:68-81` | 11 | `cases/domain.py:group_by_prefix(cases)` — and it removes a lazy-import cycle between the two modules | — |
| R-36 | **Case-sequence collision scan** — `_is_candidate_free` is a single-use abstraction. | `cases/repository.py:286-288` | 3 | inline it | — |
| R-37 | **Archived/version column definitions in 4 places** (`BaseEntity`, `SoftDeleteMixin`, `CaseModel`, `_CASE_COLUMN_DEFINITIONS`, plus the migration-006 CHECK). Genuinely irreducible across layers — but nothing *enforces* the agreement. | 5 | 8 | make `_CASE_COLUMN_DEFINITIONS` the only place a DDL type is written, and add a test asserting each name appears in `CaseModel` | — |
| R-38 | **Three session-scope idioms** — `UnitOfWork`, `manager.session()`, `_ledger_session`. | `core/service.py:46`, `session.py:119`, `audit/service.py:49-59` | 20 | `UnitOfWork` composed over the other two, and reachable on read paths | §14 invariant |
| R-39 | **`now_utc` imported through the wrong module in 4 production sites**; `ensure_utc` is a dead alias re-exported to 7 sites. | `repository.py:9`, `recovery.py:27`, `lifecycle.py:123`, `models.py:9`, + 7 alias sites | 11 | `core/clock.py` for `now_utc`, `core/canonical.py` for `coerce_utc`; add `__all__` to `domain.py` | — |
| R-40 | **`--flag` / `--flag=value` matching** in the two primitives every shell handler parses through. | `args.py:12-15` vs `:39-42` | 2 | `args.py:_matches(arg, flag)` | — |
| R-41 | **`sha256_file` re-implemented in a file that already imports the module that owns it.** | `release/make_manifest.py:61-64` vs `core/fs.py:28-36` | 4 | import it (the other two release scripts already do) | — |
| R-42 | **Prompt-label formatting** — 3 implementations: one correctly aligned with tokens, one with the same tokens but no indent/alignment, one with raw `[cyan]` and no tokens. | `renderers.py:566-586`, `cases/shell_handler.py:331, 400-412`, `cases/commands.py:50, 52` | ~12 | `core/ui/renderers.py:prompt_required/optional` — already correct with 6 production call sites | — |
| R-43 | **Error → exit-code mapping** — 2 dispatch mechanisms + 2 dead constants. | `error_handler.py:101-130` vs `:55-94`, `exit_codes.py:7, 10` | ~25 | one ordered `specs` tuple covering all mapped types, with `ValidationError → EXIT_USAGE` and `InvariantViolationError` added | **C-05** |
| R-44 | **Dev-secret sentinel** — the same literal 4 times across 2 files, with a comment acknowledging the duplication. | `settings.py:37, 85`, `audit/signing.py:16, 212` | 4 | one leaf constant (the `core/clock.py` pattern) | — |
| R-45 | **`nil`/`""` normalisation** — the same "both mean empty" rule written twice with the same comment claiming to describe the single shared rule, and **the two disagree** on tags and title. | `cases/service.py:188-205` vs `cases/shell_handler.py:430-443` | 20 | one `normalise_optional(value)` in `cases/domain.py` | H-42 |
| R-46 | **Diff detection** — `changed_fields` is the declared single source; the service never calls it. | `cases/domain.py:244` vs `cases/service.py:188-205` | 18 | `changed_fields` | — |

### 6.4 `audit/` — the crown-jewel module

| # | Duplication | Sites | Lines | Single source of truth | Also fixes |
|---|---|---|---:|---|---|
| R-47 | **Row verification, two implementations with different semantics.** `verify_event` = payload+chain+signature. `_row_mismatch` = payload+**prev_chain**+chain+signature. **The UI verdict omits the `prev_chain` linkage check** — the exact field an attacker rewrites when splicing. | `audit/verifier.py:64-87` vs `:101-114` | 7 | `_row_mismatch`; make `verify_event` a thin wrapper (it already accepts the right 5 fields) | **H-48, C-03** |
| R-48 | **Key-id derivation** — 3 implementations in 2 packages, and the third re-derives the id from the *filename* rather than the key. | `updates/signing.py:9-12`, `audit/signing.py:116`, `audit/signing.py:148` | 3 | `updates/signing.py:key_id_for_pubkey`, re-exported | — |
| R-49 | **Ed25519 verify block** — 3 copies, differing only in the message. | `updates/signing.py:50`, `:66`, `audit/signing.py:186` | 8 | one `_ed25519_verify(raw_pub, sig_hex, data, what)` | — |
| R-50 | **Strict-hex-key parsing** — 2 copies, diverging on length validation; the copy without the check turns a corrupt key into "invalid manifest signature". | `updates/signing.py:20-27` vs `:93-102` | 8 | one, with the 32-byte check | — |
| R-51 | **UTC guard** — `require_utc` re-implemented with a different message. | `audit/domain.py:86-88` vs `core/domain.py:27-33` | 3 | `canonical_ts(require_utc(ts))` — 4 sites already do this | — |
| R-52 | **Anchor payload dict** — built twice with the same field order, one writer dead and unsigned. | `audit/anchor.py:23-29` vs `:155-161` | 7 | one `_anchor_payload(case, seq, chain)`; delete the dead unsigned writer | **H-38** |
| R-53 | **"Is the schema missing?"** — 2 implementations, one more thorough, neither shared. | `audit/service.py:21-34` vs `core/operators.py:67-68` | 8 | one helper; and fix `.pgcode` → `.sqlstate` | **H-44** |
| R-54 | **Event schema** — **5 copies** of the field list. | `audit/models.py:51-62`, `audit/dto.py:12-24`, `audit/domain.py:55-69` (dead), `audit/exporter.py:45-58`, `audit/helpers.py:_detail_fields` | ~40 | the model is the source; the DTO derives via `from_attributes`; `_record_dict` becomes `model_dump()` | H-36 |
| R-55 | **Ledger-tip read** — byte-for-byte reimplementation. | `audit/exporter.py:14-19` vs `audit/repository.py:139-144` | 5 | `SqlAlchemyAuditRepository(session).head()` | — |
| R-56 | **Anchor storage root** computed twice + a third implicit path. | `anchor.py:16`, `:44`, `:112` | 3 | one `_anchors_dir()` | — |
| R-57 | **`_attempt_tamper_write`-style helper, 3 copies, 2 with the identical docstring** (see §8.5). | `test_database_migrations_and_lifecycle.py:163`, `test_postgres.py:97`, `test_audit_ledger.py:204` | 4 | one conftest helper | — |
| R-58 | **Action → human label** — hand-rolled a second and third time. | `audit/domain.py:31-38 ACTION_TITLES` vs `audit/renderers.py:123-144` (5 literals), `audit/dto.py:55` | 12 | `action_title()` on the enum | C-03 |
| R-59 | **Audit chain head insert** — the case-sequence path has proper `IntegrityError` recovery; the ledger path doesn't. | `cases/repository.py:267-284` vs `audit/repository.py:63-69` | 8 | copy the case pattern | — |
| R-60 | **`check_contained` used as ceremony in 4 places** (provably always true) and as a real guard in 6 others. The 4 vacuous calls make the 6 real ones harder to see. | `staging.py:31`, `marker.py:24`, `migration.py:73`, `cache.py:39` vs `updater.py:100/102/186/189/250/266`, `anchor.py:18/55` | 4 | delete the 4; the 6 real ones stay | — |

### 6.5 `updates/` and the updater

| # | Duplication | Sites | Lines | Single source of truth | Also fixes |
|---|---|---|---:|---|---|
| R-61 | **`read_json_record(path) -> dict | None`** — the `exists → read_text → json.loads → except → isinstance` block, **5 near-verbatim copies** (plus a 6th read half). | `staging.py:36-46`, `updater.py:68-78`, `updater.py:229-239`, `migration.py:58-68`, `service.py:63-73` | 9 × 5 | `core/fs.py`, next to `atomic_write_lines` (which already owns the write half) | C-18 |
| R-62 | **`write_json_record(path, payload, required, *, stamp)`** — validate → `check_contained` → `{**payload, **stamp}` → `atomic_write_lines`. **3 copies, and the merge-order bug lives in exactly one of them.** | `marker.py:20-29`, `staging.py:24-33`, `migration.py:71-74` | 7 × 3 | `core/fs.py` | **C-17** |
| R-63 | **`Path(settings.storage_root) / …` construction** — 4 private helpers + 1 inline, while `updater.install_root()` carries the **canonical layout map** in its docstring and **none of the four reference it**. | `lock.py:11`, `migration.py:18`, `marker.py:16`, `checker.py:75` | 16 | `updater.py:install_root` + `storage_state_path(name)` | — |
| R-64 | **Postgres credential + subprocess plumbing** — 2 byte-identical blocks (backup + restore), each with its own `env["PGPASSWORD"]` + `DEVNULL` + timeout + wrap. | `migration.py:167-184` vs `:238-255` | 12 × 2 | one `_pg_env(url) -> (clean_url, env)` — and put it next to the correct `urlsplit`-based `sanitized_db_url` | H-49 |
| R-65 | **`sqlite_path_from_url(url)`** — the same brittle 2-step split in 2 places, neither handling `sqlite+pysqlite://`, one raising `IndexError` from a recovery path. | `migration.py:157`, `migrations.py:418-419` | 2 × 2 | `core/database/session.py`, beside `sanitized_db_url` | **C-19** |
| R-66 | **The failure-history DTO construction** — ~24 lines differing only in `failure_reason` and `override_reason`, in two `except` blocks. | `lifecycle.py:165-178` vs `:193-205` | 24 | one `_record_failure(current, manifest, channel, reason, started_at, allow_minimum_bypass)` | **C-13** |
| R-67 | **The "verify artifact" sequence** — 2 implementations; the hand-rolled one skips filename + size + the manifest signature. | `verifier.py:20-28` vs `lifecycle.py:221-231` | 11 | `verifier.verify_artifact(path, artifact)` + `verify_manifest_signature` | **C-01, C-12** |
| R-68 | **Re-entrant thread-local scoping** — 2 hand-rolled mechanisms, same purpose, different bookkeeping, different type-ignore styles. | `lock.py:22-35` vs `migration.py:29-47` | 19 | one `reentrant_local(name)` — or, lazier, delete the 6 redundant `with update_lock():` wrappers and collapse `lock.py` to a 3-line pass-through | §6.7 |
| R-69 | **Stage → label/status projection** — 3 hand-maintained containers + a 4th mapping + a dead 5th, and they **already disagree** on `MIGRATING`, `HEALTH_CHECK` and `RECOVERY_REQUIRED`. | `stages.py:21, 23-28, 30-35`, `stages.py:38-49` (dead), `renderers.py:36-41`, `tui/theme.py:79-87` | 40 | one `Stage -> (active_label, done_label, failed_label)` mapping, plus one state→stage function **actually wired in** | **H-71** |
| R-70 | **6 redundant `with update_lock():` wrappers** on a single call path, made no-ops by a 10-line depth counter that exists only to make them safe. | `lifecycle.py:336`, `updater.py:87, 171, 247, 260` | 6 | delete all 6; `lock.py` collapses to 3 lines; the depth counter goes with them | — |
| R-71 | **Channel validator** — verbatim copy, **identical method name** `_channel_known` defined twice in one package. | `dto.py:17-24` vs `manifest.py:42-49` | 8 | `domain.py:_validate_channel` (or a `TypeAdapter`) | — |
| R-72 | **`now_utc` import path**, and **2 default sources** for `started_at`. | `models.py:9`/`service.py:6`/`dto.py:6`; `models.py:36`/`dto.py:13` | 6 | one import path, one default owner | — |
| R-73 | **19-field hand-written model constructor.** | `service.py:13-41` | 19 | `UpdateHistoryModel(**dto.model_dump(...), ...)` | — |
| R-74 | **URL-scheme literal tuple.** | `checker.py:9`, `sources.py:8-9`, `cache.py:55` | 3 | one `is_url(target)` predicate | — |
| R-75 | **`key_id_for_pubkey` prefix literal `"ed25519:"`** hardcoded twice in `trust.py` where `KEY_PREFIX` exists 18 lines away in the same package. | `trust.py:24, 34` vs `signing.py:6` | 2 | import `KEY_PREFIX` (or move it to `core/`) | — |
| R-76 | **Manifest URL channel resolution** — 2 implementations, and the install-path one is **wrong**. | `checker.py:47-49` vs `:136-138` | 3 | one `resolve_manifest_target` that returns `(base, channel)` | **H-05** |
| R-77 | **`current_schema_version` called 6× per update** where 1 would do, because `verify_compatibility` re-queries instead of accepting the known value. | `lifecycle.py:50, 80, 377, 407`, `migration.py:303, 310` | 6 | compute once in `_run_locked` and thread it | — |
| R-78 | **Migration column-DDL boilerplate** — 4 hand-rolled `(name, ddl)` tuple loops plus `_ensure_column` as a 5th spelling, plus `_apply_missing_columns` as a *worse* 6th. | `migrations.py:59-77`, `:498-508`, `:555-565`, `:578-588` | ~30 | one `_ensure_columns(conn, table, defs)` | — |
| R-79 | **The `isinstance(bind, Connection)` migration fork, 9 times, entirely dead.** | `migrations.py` × 9 | 25 | **delete the `else` branches** — pure deletion, not refactoring | — |
| R-80 | **Inline stdlib imports** — `contextlib` ×4, `os` ×3 aliases in one function, `subprocess` re-imported, `hashlib` ×5 function-local, `structlog` ×3 in one file, `pickle`… | 8 files | ~20 | module-level | — |
| R-81 | **"Read the project version"** — 4 independent implementations. | `install.sh:526`, `install.ps1:500`, `verify_release.py:56`, `settings.py:17` | 4 | `trace version --short` | — |
| R-82 | **The trust-bundle parser** — implemented twice (sh and ps), differently (`IFS=' '` vs `\s+`), neither calling `import_release_pubkey`, both writing non-atomically with no 0600. | `install.sh:622-641`, `install.ps1:612-619` | ~30 | `import_release_pubkey` | **C-08** |
| R-83 | **`_safe_filename`** — byte-identical in 2 files. | `release/sign_release.py:16-20` vs `release/verify_release.py:10-16` | 5 | one wrapper over the existing `assert_safe_filename` | — |
| R-84 | **Artifact integrity verification** — a 12-line hand-rolled size+sha256 loop in the release verifier, duplicating `verify_artifact_content` and then being **immediately superseded by it 4 lines later** (so every wheel is stat'd and hashed twice). | `release/verify_release.py:19-30` vs `updates/verifier.py:20-28` | 12 | delete it; let `verify_manifest` do it | — |
| R-85 | **The repo slug `nirjxr26/Trace`** — 20 occurrences, no constant. | `install.sh` ×8, `install.ps1` ×8, `settings.py`, `README` ×2 | 20 | one leaf constant / one build-substituted value | — |
| R-86 | **`manifest.schema.json`** — 55 lines nothing reads, disagreeing with the only enforced contract on **12 of 16** constrained fields. `jsonschema==4.26.0` is already installed transitively. | 1 file vs `updates/manifest.py` | 55 | generate it from the pydantic model, or delete it | §9.4 |
| R-87 | **The two installers' shared pipeline** — detect platform → download → verify → install → PATH → smoke test. ~400 lines eliminable if the driver logic were shared, and the divergence is where the bugs are (H-29, H-31, H-33, H-42). | `install.sh` (686) + `install.ps1` (675) | ~400 | one cross-platform installer driver + two thin platform shells | §3.1 |

### 6.6 The reuse verdict, ranked

> **Carve-out, per repo policy.** `update-pipeline-deep-audit-2026-09-20.md:612` principle #15 — *"never delete a safety check because its implementation is incomplete"* — overrides everything below for **safety checks specifically**. That means the inert `ForensicOperationGate` (C-02) is **wired, not deleted**. The same doc at `:709` states the opposite for everything else (*"prove the second caller first"*), which is what authorises Tier 1 and Tier 2. Delete nothing on this list that is a gate, a guard, or an audit-integrity check.

**Tier 1 — pure deletion, no new API, immediate bug removal:**

| # | Action | Lines removed | Bugs fixed |
|---|---|---:|---|
| 1 | Delete the 9 dead `isinstance(bind, Connection)` `else` branches in `migrations.py` | 25 | — |
| 2 | Delete the 6 redundant `with update_lock():` wrappers + the depth counter they require | 30 | — |
| 3 | Delete the 4 vacuous `check_contained` calls | 4 | — |
| 4 | Delete `write_anchor` (the dead, unsigned, fail-open writer) | 12 | **H-38** |
| 5 | Delete `fetch_artifact_bytes` (zero callers) + `_verify_artifact_integrity` (superseded 4 lines later) | 20 | — |
| 6 | ~~Delete `stage_from_state`'s dead branches or wire it in~~ **WITHDRAWN** — it is shipped per `docs/UPDATE_UX.md:156` and has a caller. Keep it; fix only the R-69 mapping disagreement. | 0 | H-71 (partial) |
| 7 | Delete `_how_text`, `KeysModal.KEYS`, `EntityNotFoundError`, `health_dot` (all zero-caller) | 25 | — |
| 8 | Delete `release/verify_release.py:_verify_artifact_integrity` (superseded 4 lines later) | 12 | — |
| 9 | Delete `audit/helpers.py:do_export` (pure pass-through) | 3 | — |

**Tier 2 — one new small helper each, removes the largest duplication:**

| # | New single source | Lines removed | Bugs fixed |
|---|---|---:|---|
| 10 | `core/fs.py:read_json_record` | 45 | C-18 |
| 11 | `core/fs.py:write_json_record` | 21 | **C-17** |
| 12 | `core/canonical.py:is_naive` | 6 | **C-04** |
| 13 | `core/database/session.py:sqlite_file_path` | 4 | C-19 |
| 14 | `updates/lifecycle.py:_record_failure` | 24 | **C-13** |
| 15 | `core/cli/doctor.py:collect_diagnostics` | 26 | H-66 |
| 16 | `core/ui/renderers.py:confirm_typed_number` | 14 | — |
| 17 | `BaseShellHandler._complete_flag_value` | 30 | — |
| 18 | `cases/domain.py:parse_case_status_filter` | 17 | C-05 |
| 19 | `core/cli/error_handler.py`: one ordered `specs` tuple | 25 | **C-05** |
| 20 | `audit/verifier.py`: `verify_event` → thin wrapper over `_row_mismatch` | 7 | **H-48** |
| 21 | `core/ui/renderers.py:render_dossier` — make both features call it | 60 | — |
| 22 | `updates/stages.py`: one `Stage -> 3 labels` mapping | 40 | **H-71** |
| 23 | `migrations.py:_ensure_columns` | 30 | — |
| 24 | `core/domain.py`: drop the `ensure_utc` alias, add `__all__`, repoint 4 imports | 11 | — |

**Tier 3 — structural, worth doing deliberately:**

| # | Action | Lines removed | Bugs fixed |
|---|---|---:|---|
| 25 | `audit/verifier.py` + `audit/exporter.py` + `audit/dto.py` all derive from the model | ~55 | H-36, H-42 |
| 26 | Factor the case/audit dossier into data + per-surface formatting (kills the TUI twins) | ~105 | C-03 |
| 27 | `update_manifest` → `canonical.validate_release_id` + `validate_version` in `core/canonical.py` | 5 | H-46, H-57 |
| 28 | One `UpdateInstaller` service returning a small result object; CLI/REPL/TUI all call it | ~50 | H-25 |
| 29 | Generate `manifest.schema.json` from the pydantic model (or delete it) | 55 | §9.4 |
| 30 | Shared installer driver + two thin platform shells | ~400 | H-29/31/33/42 |

---

## 7. Dead / single-implementation / no-op code inventory

Everything here is safe to delete today, verified by grep across `src/`, `tests/`, and `release/`.

### 7.1 Zero production callers

| Symbol | Location | Note |
|---|---|---|
| `UpdateLifecycle.load()` | `updates/lifecycle.py:96-109` | **Also broken** — see H-04 |
| ~~`stage_from_state()`~~ **WITHDRAWN** | `updates/stages.py:38-49` | **Not dead.** `docs/UPDATE_UX.md:156` ships it: *"Single source for the mapping, mirroring the existing `UpdateFailureStage.from_state()` precedent"*, status "implemented on feat/update-ux". My grep missed the caller. The §4.5 finding that it *disagrees* with `_FAILED_STAGE` stands. |
| `fetch_artifact_bytes()` | `updates/sources.py:180-187` | "Single source" with zero callers |
| ~~`verify_artifact_signature_streaming()`~~ **WITHDRAWN** | `updates/signing.py:88-90` | **Not dead — a deliberate one-release alias.** `update-module-permanent-remediation-2026-09-22.md:157` (C-14): *"old name kept as deprecated alias for one release to avoid breaking external imports, then removed"*. Correct as-is; the doc already scheduled its removal. |
| `TestManifestSource` | `updates/sources.py:28-33` | A test double in production; also triggers a pytest collection warning |
| `write_anchor()` | `audit/anchor.py:21-32` | **Writes an unsigned anchor and is the fail-open path** — H-38 |
| `AuditEvent` (the entity) | `audit/domain.py:55-75` | Only constructed by the uncalled `_model_to_domain` |
| `SqlAlchemyAuditRepository._model_to_domain()` | `audit/repository.py:37-38` | Zero callers |
| `EntityNotFoundError` | `core/domain.py:52-58` | Zero raisers repo-wide |
| `TimestampMixin` | `core/database/base.py:17-31` | One user (`cases/models.py:13`) — borderline |
| `health_dot()` | `tui/theme.py:46-48` | Docstring claims it is the single source for the two pills it names; both are inlined |
| `KeysModal.KEYS` | `tui/palette.py:134-135` | Comment says tests import it; none do |
| `_how_text()` | `audit/renderers.py:296-303` | Defined, never referenced |
| `do_export()` | `audit/helpers.py:91-93` | Pure pass-through; siblings add logic |
| `EXIT_USAGE`, `EXIT_CONFLICT` | `core/cli/exit_codes.py:7, 10` | Never referenced |
| ~~`sanitized_db_identity()`~~ **WITHDRAWN** | `core/database/session.py:133-146` | **Not dead.** Documented live at `docs/audits/update-pipeline-deep-audit-2026-09-20.md:381` (DBS-03). I also listed it twice (§4.1 and here). The *duplication* finding (R-33) stands; the "zero callers" claim does not. |
| `is_archived_filter` re-derivation | `cases/domain.py:80` | `STATUS_FILTER_KEYWORDS` already carries the value |
| `check_contained` as ceremony | `staging.py:31`, `marker.py:24`, `migration.py:73`, `cache.py:39` | Provably always true |
| `_is_candidate_free` | `cases/repository.py:286-288` | Single-use abstraction |
| `_retain_first` | `audit/verifier.py:117-119` | Single-use; "Single source" for nothing |
| `migrations.py` Engine branches | 9 sites | `apply_migrations` always passes a `Connection` |
| `db_manager` import alias | `updates/service.py:44` | — |
| `_check_release_health`'s `"passed"`/`"failed"` literals | `updates/lifecycle.py:73, 76, 82, 87, 417` | Duplicated, and inconsistent (`.pending` not checked at 417) |
| `pipeline cache` (upstream) | `tests/conftest.py:139-144` | `cli_runner` fixture — **zero users**; 3 test files re-implement it |
| `make_case` | `tests/conftest.py:89-91` | Docstring: "Single source for case creation. Reusable." Used **once**; ~25 tests inline the same call |
| `temp_storage` | `tests/conftest.py:22-28` | Used once, and its `monkeypatch.setenv` **cannot work** (settings is already constructed) |
| `sample_case_dto` | `tests/conftest.py:46` | Used once, by a fixture used twice |

### 7.2 Dead parameters, always-constant parameters, never-read parameters

- `updates/lifecycle.py:327-329` — 3 defaults duplicated from `run()`'s and never used.
- `updates/lifecycle.py:62-63` — 2 params always supplied by the sole caller; 4 lines of dead defensive code.
- `updates/lock.py:13-18, 30` — `UpdateGateContext.target_version`/`transaction_id` always set; `can_install_update(context=None)`; `try_update_lock` never increments `depth`.
- `updates/checker.py:22` — `channel` never read in the body, threaded through 5 call sites.
- `updates/verifier.py:59` — `platform_key` non-`None` only from a release script.
- `updates/stages.py:52-54`, `updates/lifecycle.py:327` — `progress` defaults duplicated.
- `updates/pip_backend.py:74` — `self` holds `manifest`.
- `updates/dto.py:90-112` — 2 `default=False` defaults on `nullable=False` columns.
- `updates/builder.py:62, 90, 102, 114, 120, 126` — 6 `command` params, all dead.
- `audit/dto.py:58-71` — `VerifyResultDto.last_chain` never populated.
- `audit/shell_handler.py:248` — `_ = svc`.
- `audit/commands.py:139-140, 154-155` — the session opened only to have its own write rolled back.
- `cases/repository.py:103-117` — `purge` accepted then `_ = purge`.
- `cases/commands.py:76`, `cases/dto.py:39` — `--status UNDER_REVIEW` is filterable for a state nothing produces.
- `tui/palette.py:46-48` — `_app_ref` stored, never read.
- `tui/screens/settings.py:268, 331, 358` — `width` accepted, `_ = width`.
- `tui/forms.py:20, 40` — `BINDINGS = ESCAPES` assigned twice to two classes; the second is a no-op shadowing the base with the same object.
- `core/settings.py:22-28` + `tests/conftest.py:15-19` — the env var the session fixture sets has **no effect** on the already-constructed singleton.

### 7.3 Unreachable / dead code paths

- `updates/gate.py:30-32` — the entire probe path (C-02).
- `updates/lifecycle.py:131` (3× redundant `is_update_available` check).
- `updates/lifecycle.py:369-370` — `AVAILABLE` is never externally observable.
- `updates/sources.py:104-105` — the 304 branch urllib can never reach.
- `updates/completion.py:157-158` — `except Exception` around `str.split`, which cannot raise.
- `core/canonical.py:21` — an assert that cannot fire, which also vanishes under `python -O`.
- `core/domain.py:75` — `STATUS_FILTER_KEYWORDS`'s `ARCHIVED` is re-tested by a literal instead.
- `core/errors.py:53-59` — `StateTransitionError.reason` never stored.
- `cases/domain.py:101-102` — the idempotence branch the service makes unreachable.
- `cases/dto.py:27-28` — a length check pydantic already performed.
- `cases/dto.py:117-118` — `setdefault` on keys that provably exist.
- `cases/renderers.py:58` vs `:97` — the two breakpoint deciders that cannot both be right.
- `audit/dto.py:49` — `RECOVERY_REQUIRED` validates as a state but is not a `_FAILED_STAGE` key.
- `updates/renderers.py:153` — a guard that never suppresses.
- `updates/stages.py:84-86` — a PENDING branch the only caller skips.
- `migrations.py:92-90` etc. — 9 dead Engine branches.
- `tests/unit/test_case_state_machine_property.py:23-31` — an `else:` that can never run, leaving **6 of 9** matrix combinations untested while looking exhaustive.
- `tests/updates/test_policy_versions.py:46-51` — a test that overrides the method under test with a constant, exercising zero lines of it.
- `tests/unit/test_ui_renderers.py:299-349` — a 51-line "test" with **zero** `assert` statements.
- `tests/unit/test_subpart2_readiness.py:15-17` — duplicates a stronger test elsewhere.
- `tests/updates/test_phase_c_durable.py:39` — `x == x`.
- `tests/unit/test_completion.py:96-98` — asserts a string (`"a3f1"`) that appears **nowhere in `src/`** and never will.

---

## 8. Test-suite audit

### 8.1 Coverage matrix

| Production module | Test status | Evidence |
|---|---|---|
`core/cli/exit_codes.py` | **NONE** | `rg "EXIT_\|exit_codes" tests` → 0 hits. The constants are duplicated as magic numbers in 6 test files instead. |
`core/cli/registry.py` | indirect | `resolve_alias`, `all_handlers`, `ShellContext` untested; the alias-collision case (last-write-wins) untested |
`core/database/repository.py` | **indirect only** | 0 module-path references. `ilike_literal`'s backslash escaping untested (`%` and `_` are). `paginate` executed but never asserted. |
`core/ui/theme.py` | **NONE** | 0 references. No test asserts a token exists, that the `border_*`/`status_*` families are complete, or that no token is a raw hex outside the palette. |
`core/fs.py:check_contained` | **NONE** | The backstop behind **every** path-traversal defence. Untested: `path == root`, the sibling-prefix case (`root=/a/b`, `path=/a/bc` — the exact `startswith` bug it exists to prevent), a symlink escape, and the `OSError → ValueError` branch. |
`core/canonical.py` | partial | Covered via `test_subpart2_readiness.py` / `test_audit_ledger.py`; `parse_trailing_seq` untested |
`core/operators.py` | partial | `get_or_provision`'s concurrent-first-use race is **never exercised with concurrency**; the psycopg `.pgcode` path is unreachable (H-44) and untested |
`core/cli/{doctor,recovery,db_commands,error_handler}.py` | indirect | `recovery._triage_update_marker` is imported **by name** in a test (a missing public API) |
`core/service.py` | **good** | `test_unit_of_work_transaction_and_hooks` + `test_audit_failure_rolls_back_case` are the two strongest tests in the suite |
`audit/exporter.py` | **NONE** | Reached only via the service. `_record_dict`'s bare `except: ts_str = str(m.ts)` — a **non-canonical** timestamp into a forensic bundle — is unexercised. |
`audit/helpers.py` | partial | `do_export_encrypted`'s plaintext-leak window (C-24) untested |
`audit/vault.py` | partial | Wrong passphrase and a malformed `{"alg": "x"}` envelope are tested; a well-formed envelope with **downgraded `iterations: 1`** is not — the textbook KDF-downgrade attack on a passphrase-encrypted bundle, and the guard is unverified |
`audit/anchor.py` | partial | `check_anchor_match`'s signature branch is **never negatively tested**; the test passes a dict with no `signature`/`key_id` so the branch is skipped, and the other test tampers `last_seq`, tripping an earlier branch. Positive coverage only. |
`audit/builder.py` | **NONE** | 139 lines owning `_resolve_command` / `merge_details_context` — the 5W1H provenance rules that `test_audit_5w1h.py` claims to test but only observes through the service |
`audit/shell_handler.py` | **NONE** | Reached only via `test_audit_cli.py` |
`updates/models.py`, `updates/shell_handler.py` | **NONE** | `models.py:39-41 _coerce_utc` untested |
`updates/staging.py` | partial | `read_staged_record`'s 4 `return None` paths untested |
`updates/signing.py` | partial | The `MAX_ARTIFACT_BYTES` size cap — a 10 GiB guard — has **no** test |
`updates/sources.py:_HttpsRedirectGuard` | **missing** | Both **refusal** branches (https→http, cross-host) are untested. The only redirect test covers the **allow** path. The security controls are the un-tested ones. |
`updates/sources.py:_with_retries` | **NONE** | No test injects 503/429/408; the 304 ETag path is untested. (Skipped probably *because* `time.sleep(attempt)` would slow the test — it should be injected.) |
`updates/migration.py:restore_backup` | **NONE** | See C-19 — the entire disaster-recovery restore path |
`trace_updater/updater.py:prune_retention` | **NONE** | It **deletes files** |
`updates/cache.py` | partial | Content identity is tested; TTL expiry and the `float()` guard are not |
`updates/checker.py:_cached_check_http` | **NONE** | The entire HTTP + ETag revalidation cache path |
`tui/widgets.py`, `tui/theme.py`, `tui/actions.py` | **NONE** | `PALETTE_ALIASES` is exactly the kind of table that rots; the test that touches it *indirectly* cannot distinguish a correct alias map from one where every key maps to `"tab-settings"` |
`tui/screens/cases.py` (369 lines) | pilot only | |
`tui/screens/audit.py` (209 lines) | pilot only | |
`tui/screens/settings.py` (587 lines) | one import | For a type hint |
`cli/suggest.py` | indirect | |
`release/sign_release.py`, `release/verify_release.py` | **NONE** | The two scripts that actually **sign** and **verify** a release manifest — the trust root of the whole update chain |
`tests/updates/test_update_e2e_local.py` | **GITIGNORED** | See H-77 |

### 8.2 Tautological / unfalsifiable tests

| Location | Finding |
|---|---|
`tests/updates/test_phase_c_durable.py:39` | `assert SCHEMA_REQUIRED_KEYS[MARKER_SCHEMA] == REQUIRED_KEYS` — production defines it that way. `x == x`. Can never fail. |
`tests/updates/test_policy_versions.py:46-51` | Overrides `can_install_update` with a constant, then asserts the constant. Exercises **zero** lines of the method under test. Also breaks LSP: the override drops `context`, so a real call would `TypeError`. **Delete.** |
`tests/unit/test_completion.py:96-98` | Asserts `"a3f1"` never appears. `rg "a3f1" src` → **0 hits**. A historical bug's fingerprint asserted as a permanent invariant. |
`tests/updates/test_phase_c_durable.py:16` | Logically implied by the two assertions above it. |
`tests/unit/test_ui_renderers.py:29-30, 177-180` | 5 assertions of the form "the constant is one of the two values I read off the implementation". Note `get_error_icon()` and `get_warning_icon()` **share** the `"[!]"` fallback, so swapping those two would not be detected. |
`tests/unit/test_audit_cli.py:28` | A 3-way disjunction where two of three substrings appear in the same panel. Effectively `assert stdout != ""`. |
10 sites across 6 files | `assert X is not None` immediately followed by `X.<attr>` — the second line raises `AttributeError` if the first is false, so the first is dead. |
`tests/unit/test_case_state_machine_property.py:23-31` | See §7.3. The outer `if` already requires `start == CLOSED`, so the inner `if` is a tautology and the `else` is unreachable. **6 of 9** combinations do nothing, and the test looks exhaustive. A `.hypothesis/` directory exists at the repo root but `hypothesis` is neither imported nor declared. |

### 8.3 Tests that assert on a mock, or swallow failures

| Location | Finding |
|---|---|
`tests/unit/test_database_migrations_and_lifecycle.py:38-44` | `assert s is not None` is vacuous; `mock_warning.assert_called_once()` asserts a **mock's call count**, and it only passes because `model_post_init` emits a *second* warning suppressed by a session fixture's env var. Edit that fixture and the test breaks for reasons unrelated to the code under test. |
`tests/updates/test_backup_pg.py:24-31` | Asserts the production call passes the values the production call passes. The valuable assertions (no password in argv; `PGPASSWORD` in env) are on the same lines — keep those, drop the rest. |
`tests/updates/test_pip_backend.py:119-126` | The mock returns the manifest's own version, so the assertion is `x == x`. Cannot detect a change in how `pip_health` obtains the version. |
`tests/unit/test_security_regressions.py:650-655` | `except Exception: pass` swallows every failure mode including `AuditTamperError`, `AttributeError`, `KeyError`. The entire 12-line block **duplicates** `test_unreadable_anchor_typed_error` at `:591-599`, which does the same check correctly. Delete `:644-655`. |
`tests/unit/test_database_migrations_and_lifecycle.py:238-244` | `except Exception: continue` ×20 — any **non-retryable** bug is retried 20× then reported as `"case {i} never committed"`, sending the reader hunting for a concurrency problem that does not exist. Catch `OperationalError` specifically. |
`tests/updates/test_migration_race.py:121` | `pytest.raises(Exception, match=...)` — `Exception` is the base of `AssertionError`, `TypeError`, etc. Production raises `UpdateError`. |
`tests/unit/test_audit_ledger.py:33-49` | `_disable_audit_triggers` / `_enable_audit_triggers` wrap every DDL in `try: … except Exception: pass`. If `CREATE TRIGGER` silently fails, the ledger is left **unprotected** for the rest of that test and the next tamper assertion trivially succeeds. It also **re-declares the production trigger DDL verbatim** — if production changes the trigger, the test restores the *old* one and keeps passing. |

### 8.4 Tests that encode a bug as expected behaviour

| Location | Finding |
|---|---|
`tests/updates/test_migration_race.py:72-103` | **Two** `pytest.raises(RecoveryError)` with **no `match=`**, while `rollback_release` raises it from **four** sites. The two tests are **mutually indistinguishable** — swap the `release_meta` kwarg and both still pass. The `schema_min` branch the second test is named for is never pinned. This test suite is the reason C-07 survived. |
`tests/updates/test_migration_race.py:125-135` | `test_waiver_skips_backup_but_records` asserts **neither** of the two things its name promises. Tracing production: `schema_target=9999` → `raise MigrationCompatibilityError` at `:316` → the function **never reaches** the `result["backup_waived"]` assignment. `rg "backup_waived" tests` → **0 hits**. The waiver-recording feature is entirely unverified. |
`tests/unit/test_audit_ledger.py:126-136` | `test_tail_deletion_is_not_internally_detected` asserts that **successfully deleting the tail of the audit ledger reports VALID**. The comment is honest, but the assertion makes a security weakness a passing test. The compensating controls are *partially* tested — **no test ever takes a truncated bundle and proves the header detects it.** |
`tests/unit/test_audit_ledger.py:139-182` | Builds an unsigned row and asserts `is_valid is True` + a gap warning. The row cannot arise post-migration-010 (every new row is signed), and the test normalises it as "warning, not tamper". |
`tests/unit/test_completion.py:44` | `assert number_group("no-dashes-here") == "dashes"` locks in the accident that a 2-dash input returns the second token as a *group*. The untested case is the one that matters: `"2026-0001"` returns `"0001"`. |
`tests/updates/test_migration_race.py:88-103` | By setting `schema_min: 9999` and calling it "incompatible schema", the test reinforces the false impression that rollback is schema-bounded on both sides. `rg "schema_target" tests` shows it appears only in forward-migration contexts — **never on the rollback path.** |

### 8.5 Flakiness, order dependence, and host dependence

| Location | Finding |
|---|---|
`tests/conftest.py:94-100` | **The single biggest test-suite defect.** `temp_storage_root` sets `storage_root = tmp_path`, but `install_root()` and `trust_root()` derive from `storage_root.parent` — under pytest, `<basetemp>/pytest-<N>/`, **shared by every test in the session**. 4 tests that use the bare fixture are therefore **order-dependent on a shared `active-version` file**. Other tests silently work around it by setting `storage_root = tmp_path / "storage"` — an undocumented inconsistency that is the direct cause of the 11 duplicated setup blocks in §8.6. |
`.github/workflows/ci.yml:100, 155` | `TRACE_STORAGE_ROOT: "./.test_storage"` is **relative**, so `install_root()` becomes `./install` and `trust_root()` becomes `./trust/releases` — **inside the checkout**. Confirmed on disk: `D:\Projects\trace\trust\releases\` exists and `.test_storage/anchors/anchor-2026-CLI-0001-3.json` is present. CI writes anchors, signing keys, the update lock and the check cache into the repository on every run. `.gitignore:59-60` is the scar tissue. |
`tests/unit/test_cli_commands.py`, `test_case_service.py`, `test_audit_cli.py` | Write to the **real** `settings.storage_root` — never request `temp_storage_root`, so `close_case → record_anchor_intent → publish_pending_anchors` writes real anchor files outside any tmp dir. Confirmed on disk: `anchor-2026-CLOSE-0001-2.json`, `anchor-2026-SEALED-0001-2.json`. |
`tests/updates/test_no_telemetry.py:8` | Relative paths → the **security guard passes vacuously** from any other CWD. (H-75.) |
`tests/conftest.py:15-19` | Session-scoped, so it runs **after** module import — but `settings = Settings()` executes at import. The env assignment has **no effect on the singleton**; it only affects the two tests that construct a fresh `Settings()`, which are exactly the two that read the developer's real `~/.trace/.env`. |
`tests/unit/test_database_migrations_and_lifecycle.py:255-264` | `assert settings.sql_echo is False` asserts the **global singleton's** current value, populated from the developer's environment *and* `~/.trace/.env`. Same class: `test_query_pagination_and_purge_policy.py:98-115` mutates `settings.debug` globally via `try/finally` instead of `monkeypatch.setattr`. |
`tests/unit/test_security_regressions.py:310-313, 549-550, 563-564` | Three file-permission assertions guarded by an `if sys.platform != "win32":` **inside the test body**, not `skipif`. CI runs `windows-latest`, so on half the matrix the `0600` key mode, the `0700` dir mode and the `0600` atomic-write mode are **silently not checked** — and coverage tooling reports the lines as covered. (H-73.) |
`tests/updates/test_platform_select.py:66-69` | `monkeypatch.setattr(sys, "platform", "win32")` mutates the `sys` module globally, and relies on `policy.py:61` doing `import platform as _platform` **inside** the function for `setattr(_platform, "machine", ...)` to take effect. Hoist that import to module scope (the obvious refactor) and this test silently starts asserting against the real `platform.machine()`. |
`tests/updates/test_staging_install.py:97-121` | The `time.sleep(0.05)` is unnecessary (the lock already serialises) and is the only `sleep` in the suite. The assertion is also incomplete: it checks `order[1]` is an exit but never that `order[0]`/`order[1]` share a thread index. A regression letting both threads into the critical section would still satisfy it in some interleavings. |
`tests/updates/test_phase_c_durable.py:98-120` | Real threads with `ready.wait(timeout=10)`, `done.wait(timeout=30)`, `join(timeout=10)`. If the body takes >30 s the holder releases the lock mid-assertion, the CLI succeeds, and `assert res.exit_code == 16` fails intermittently. No `pytest-timeout` in `pyproject.toml`, so a genuine deadlock hangs until the 20-minute `timeout-minutes`. |
6 sites | Unbounded `thread.join()` / `pool.map()` with no timeout. Add `pytest-timeout` to the `dev` extra and `@pytest.mark.timeout(...)`. |
`test_tui_updates.py:24-29`, `test_security_regressions.py:633-639` | Retry loops used as synchronisation, with different counts and a **weaker acceptance condition** in the second (`or "No audit events found" in text_now`) — so it can pass for the wrong reason. |
`tests/unit/test_case_entity.py:43` | `naive_dt = datetime.now()` — benign (the assertion is timezone-independent) but `datetime(2026, 1, 1)` would be deterministic and free. |

### 8.6 Reuse inside the test suite

| # | Duplication | Files | Proposed fixture |
|---|---|---:|---|
T-01 | `monkeypatch.setattr(settings, "storage_root", …)` + `import_release_pubkey(release_keys["pub_hex"])` | 11 occurrences / 4 files | **Fix `temp_storage_root` to nest (`tmp_path/"storage"`) and make `release_keys` depend on it — all 11 blocks collapse** |
T-02 | The two-release seed/stage/activate block, differing only in an optional `release_meta=` kwarg | 4 / 3 | `seeded_releases(tmp_path, schema_min=…) -> (base, versions)` — and this alone makes T-04's parametrisation obvious |
T-03 | The `serve` HTTP fixture, **byte-identical**, with the file-local one shadowing the conftest one | 2 | delete the local copy; a third variant belongs on the same primitive |
T-04 | `BaseHTTPRequestHandler` subclasses, all re-implementing `log_message` suppression and `Content-Length` | 4 | one `json_routes(routes)` handler in `tests/updates/conftest.py` |
T-05 | The manifest-building dict literal (12 keys + 6-key optional loop + probe/re-sign dance) | 3 (99 call sites use one of them) | `signed_release` already exists; the 405-line e2e file **forks it wholesale** because it needs a different key. Parameterise `signed_release` with an explicit key instead of forking. |
T-06 | The `anyio_backend` fixture — identical, including the pointless single-element `params` | 3 | `tests/conftest.py`. The three files also *disagree* on how they mark async tests (3 conventions). |
T-07 | The `_text(widget)` Rich-render helper — identical | 2 | `tests/conftest.py` |
T-08 | The clock double — 3 hand-rolled classes, and `core/clock.py:set_clock` exists. Worse: if a test raises *between* `set_clock` and the `try`, the global clock stays frozen for the rest of the session. | 3 classes + 3 try/finally | a `ticking_clock` fixture with automatic reset |
T-09 | The `serve`/keys/signing setup and the `_sign` helper — 3 sites bypass the conftest helper and inline the same one line | 3 | use `_sign` |
T-10 | `_attempt_tamper_write` / `_attempt_ledger_write` — 3 copies, **2 with the identical docstring**, whose text is itself an admission that this deserves a shared home | 3 | one conftest helper |
T-11 | The `db_manager` monkeypatch triple — 3 copies, and a 4th fixture that is **never used** | 3 + 1 dead | wire up `cli_runner` |
T-12 | The file-backed `DatabaseSessionManager(...) + init_schema()` construction | 6 | a `file_db` fixture parameterised by filename |
T-13 | `--flag` / `exit_codes` / page-size / section-count / `5`-limit / `4`-column / `9999` magic numbers — including **6 hardcoded `exit_codes.py` constants** in 6 test files | 14+ | import the constants |
T-14 | **Only 1 `parametrize` in the entire 45-file suite**, against 9 near-identical badge assertions, 7 near-identical `action_title` assertions, 6 near-identical `StageStatus` render tests, 6 + 6 near-identical manifest/artifact-trust negative tests, 3 platform-guarded permission blocks, 2 structurally identical rollback tests, and a 3×3 state matrix spread across 3 files | ~40 functions | a `parametrize` sweep would cut ~120 lines **and make the matrix coverage visible instead of implied** |
T-15 | **14 imports of `_`-prefixed private symbols across 9 test files** — `error_handler._resolve_error_details`, `policy._parse_version`, `recovery._triage_update_marker`, `sources._validate_manifest_url`, `verifier._MAX_GAPS`, `display._frame()`, `app._palette_done`, `audit_models._append_locked`, … | 9 | each is a **missing public API**, not a testing convenience. Promote them. |

### 8.7 Organisation

- **`test_phase_a_p0` / `test_phase_b_p1` / `test_phase_c_durable` are an abandoned scaffold, not a taxonomy.** The names encode a *delivery schedule* and a *priority tier*, not a behavioural axis. There is no "phase" in the product. They cut across every other file (one 87-line file contains gate logic, staging, key import, URL validation and trust paths), and contain **verbatim duplicates** of topic-named files: `test_unknown_schema_still_fails_closed` is byte-identical to `test_marker_schema.py:20-24`; `test_stable_rejects_nightly` duplicates `test_policy_versions.py:23-27`; `test_recovery_edges_legal` overlaps `test_state_machine.py:25-31`. They also contain the dirtiest code in the suite: two dead `_ = hashlib` statements, three dead assignments, a tautology, and a name that lies about what it asserts. **Recommendation:** redistribute by module and delete the filenames — "P0" and "durable" carry zero information for a maintainer who has never seen the planning doc.
- **`test_subpart2_readiness.py` and the docstring of `test_audit_ledger.py` leak process history** — "Subpart-2" is a section number in a compliance specification with no index in the repo. Of its 4 tests, 2 duplicate stronger tests elsewhere. Rename and keep the 2 unique ones.
- Same leak: `test_security_regressions.py:1-5` references `docs/security/assessment-2026-09-17.md` — a file in the **gitignored** `/docs` directory, so the reference is permanently dangling — and inline comments cite "parity row 1/2/3", a cross-document numbering scheme with no index.
- **12 of 45 test files declare no `pytestmark`**, despite `--strict-markers` and a declared `slow` marker that is used **zero** times while the suite contains real slow tests. `pytest.mark.anyio` is used in 3 files but is **not** in the `markers` list — it works only because the plugin registers it, a fragile dependency for a `--strict-markers` project.
- The `postgres-integration` job **does** run (live `postgres:16-alpine`, `TRACE_TEST_POSTGRES_URL` set), which is good. But it runs with no `--cov-fail-under`, so the PG-only paths contribute nothing to the 70% gate; and the matrix job's bare `pytest --cov` also collects `tests/integration/`, where all 3 tests **skip**. The suite reports "3 skipped" in the coverage-measured run and "3 passed" in the PG run — two different pictures of the same tests.

---

## 9. Build / release / installer / CI audit

### 9.1 What is genuinely good

Worth stating, because it narrows where to look:

- `install.sh` applies `CURL_PROTO='=https'` with `--proto-redir` consistently — genuinely good, blocks `http://` and `file://` redirects. **No `curl -k`, no `--no-check-certificate`, no cert-validation bypass anywhere.**
- `install.ps1` sets `$ErrorActionPreference = "Stop"` and has **no** `ServerCertificateValidationCallback = {$true}` and **no** `SecurityProtocol` downgrade.
- No `pull_request_target`, no `workflow_run`, no unpinned third-party `uses: …@main`, no secrets exposed to fork PRs.
- `release/make_manifest.py:52-56` is a model *why* comment: the fail-closed-at-build-time decision for one-wheel-per-manifest, and why.
- `install.sh:659` correctly runs `trace doctor` post-install.
- The gitignore's evidence-artifact extension list is thorough and correct.

### 9.2 CI (`ci.yml`, 179 lines)

- **Both coverage runs collect `tests/integration/`**, where 3 tests skip, so the reported coverage is a mix of two different suites. Fix with `-m 'not integration'` on the matrix job.
- `test_update_e2e_local.py` is gitignored (H-77), so the real install path has no CI coverage. That is the most consequential gap in the file for a self-updating forensic tool.
- The GitHub-Release artifacts are **not verified against the signature on the runner after upload** — a compromised upload token would not be caught.
- No `concurrency:` group, so overlapping pushes queue rather than cancel.
- No lint or typecheck step: the duplicated and dead constants catalogued in §6 would have been caught by one `ruff` run plus one `vulture` pass. `release.yml` *does* run PSScriptAnalyzer — the PowerShell installer is linted, and the 686-line shell installer is not.
- `pip install --require-hashes` is used for the action deps (good) but the release pipeline's own `pip install` of the package does not use it, and the `pip==26.2.1` bump (H-28) has no hash at all.

### 9.3 `manifest.schema.json` vs the pydantic model — 12 of 16 constrained fields diverge

`rg "manifest.schema.json"` finds references in `changelog/` only. **No CI step, no `verify_release` step, no test, no `jsonschema` call** — while `jsonschema==4.26.0` is already installed transitively. A dead schema that contradicts the live one is worse than no schema.

| Field | `manifest.schema.json` | `updates/manifest.py` | Divergence |
|---|---|---|---|
| `schema` | `{"const": 1}` | `Field(alias="schema", ge=1)` | Schema permits **only** 1; the model permits any n ≥ 1 |
| `product` | `{"const": "trace"}` | `min_length=1, max_length=64` | Schema pins the name; the model accepts any 1–64 chars |
| `version` | stricter/different pattern | different pattern | A version valid under one is invalid under the other |
| `channel` | enum | `field_validator` via `UpdateChannel.contains` | Different enforcement paths |
| `filename` | (absent) | no constraint | H-01 |
| `manifest_signature` | `^[0-9a-f]+$` | unconstrained `str` | H-02 |
| `signing_key_id` | `^ed25519:[0-9a-f]{16}$` | unconstrained `str` | H-02, H-03 |
| `artifacts[*].sha256` | pattern | pattern | agree |
| `schema_min`/`schema_target` | (absent) | present, co-presence-validated | The schema doesn't model them at all |
| `additionalProperties` | (absent) | `extra="forbid"` | Unknown fields pass the schema, rejected by the model |

`release/make_manifest.py:69-70` writes `"signature": ""` and `"signing_key_id": ""`, which the schema **rejects** (both patterns require hex) and the model **accepts**. So the pipeline's own output is invalid against the repo's own schema, and nothing notices because nothing loads the schema.

Also missing from the release pipeline entirely:
- `schema_min` / `schema_target` — no flag, no env var. The release pipeline **can never ship them**, which means `verify_compatibility()` is a permanent no-op in production and no release can ever declare a migration floor. `--min-version` is the *app* version floor, a different concept, and easy to confuse with.
- `published_at` — declared by both the schema and the model, never written, never validated. With no freshness check anywhere in `updates/`, a **replayed old manifest is indistinguishable from a fresh one**.
- `security_update` / `restart_required` — hardcoded to `False` / `True`. A genuine security release is **indistinguishable** from a routine one in the manifest, even though `checker.py:158-160` surfaces `security_update` to the operator.

And `release/make_manifest.py:36-37` reads `TRACE_MANIFEST_MIN_VERSION` / `TRACE_MANIFEST_NOTES` while `release.yml:64-65` passes `MANIFEST_MIN_VERSION` / `MANIFEST_NOTES`. CI passes them as **CLI flags**, so the env branch never fires in the pipeline — and the test for the env path tests the **unused** spelling.

### 9.4 The version-triple convention is enforced for 2 of 3

`release/verify_release.py:56-60` checks pyproject ↔ tag. `tests/unit/test_database_migrations_and_lifecycle.py:267-275` checks settings ↔ pyproject. **`src/trace_core/__init__.py`'s `__version__` is checked by nothing and referenced by nothing** — yet the changelog identifies it as part of the mandatory "precedent triple". The release pipeline is the *only* place the third could be caught.

### 9.5 Release-key handling

`release/sign_release.py:33` reads the Ed25519 private key from the process environment. `release.yml:78` sets it as step-scoped env, so the raw 32-byte seed sits in the runner process environment for the duration — visible to anything that can read `/proc/<pid>/environ` and to `ps e`. Best practice for a release key is a file, or better OIDC/HSM. (The `bytes.fromhex` calls are not wrapped, so a malformed secret produces a raw traceback — though the error message does **not** echo the value, so no key leak.)

`release/verify_release.py:33-41` writes into the developer's **real runtime trust store** as a side effect of a verification script — surprising. It uses `shutil.copy2` (non-atomic, preserves the source's 0644 mode) where `updates/signing.py:107` uses `atomic_write_lines(..., mode=0o600)`; and it hand-builds the revoked path that `updates/trust.py:revoked_path()` exists to own. The revocation *semantics* are correct and the comment explains *why* — genuinely good — but it never asserts `key_id_for_pubkey(pub_bytes) == pub.stem`. `rg 53712e8bb8a774e6` returns **zero hits** outside the filename itself, so the filename↔content invariant is unpinned by any test, workflow, or assertion.

---

## 10. Architectural invariant scorecard (AGENTS.md §14)

| Invariant | Status | Evidence |
|---|---|---|
**Strict Mutation Flow** (UI/CLI → Service → Domain → Repo → DB; never bypass the service to mutate ORM from CLI/UI) | **NO TEST AT ALL** — and **two production violations** | No test asserts it anywhere. Violated by `tui/screens/cases.py:369-376` (raw session + repository call), `tui/screens/settings.py:540` (`mgr.engine`), and `updates/service.py:58-61` (service delegating to a filesystem module). |
**Immutable Identity** (`Case.id`/`Case.number` never mutated) | **Covered** | `test_case_entity.py:92-106` asserts both messages. |
**Permanently Sealed Closure** (closed never returns to OPEN/UNDER_REVIEW) | **Covered triply** | `test_case_state_machine.py:42-51`, `test_case_state_machine_property.py:11-31` (which is itself 1/3 dead), `test_case_service.py:95-97, 125-136`. |
**Canonical UTC Time** (DB, domain, ledger, API payloads strictly tz-aware UTC) | **Domain only. The persistence and presentation halves — where it actually breaks — are unverified, and one of them is broken.** | Domain covered. **Not covered:** no test asserts a value **read back from the database** is tz-aware — `test_lifecycle_gates.py:120` compares two datetimes SQLite returned **without** `tzinfo`, so it passes on naive values and proves nothing. `updates/models.py:39-41 _coerce_utc` untested. `cases/repository.py:58 ensure_utc` (the shim that papers over SQLite's tz loss) untested. **Broken:** C-04, a 5h30m error in the field labelled UTC. |
**Transactional Audit Boundary** (mandatory records inside the transaction) | **Well covered** — the best-tested invariant | `test_unit_of_work_transaction_and_hooks` (hook ordering, abort-on-`before_commit`-failure, post-commit suppression) and `test_audit_failure_rolls_back_case` (monkeypatched `append` raises → `create_case` raises, `list_cases() == []`, `events_verified == 0`, then recovery). |
**Purge Guardrails** (active cases can never be permanently purged) | **Covered at the service; NOT at the repository** | `test_query_pagination_and_purge_policy.py:79-95`, `test_case_service.py:100-122`, role gate at `test_security_regressions.py:341-351`. But H-54: the repository's `purge()` has no precondition, so the invariant is one layer away from being unenforced. |
**Update crash-safety** (a half-applied update must always be detectable and resumable) | **NOT an invariant in the code.** Three independent violations | H-04 (no resume path, and `load()` is broken), H-16 (`HEALTH_CHECK` unhandled by recovery), C-14 (marker removed on partial migration), C-15 (un-completable after crash), C-16 (marker omits `backup_path`). |
**Supply-chain trust** (signature verification cannot be bypassed) | **NOT met** | C-01 (manifest signature never checked), C-08 (trust anchor fetched unsigned from the channel it constrains), C-09 (pip env can redirect the install), C-10 (rollback installs an unverified wheel), H-23 (a signed manifest with `minimum_supported_version: ""` skips the control). |

---

## 11. Recommended remediation order

Sequenced so that each step's tests can be written before the next step changes the code around it. Per the repo's own workflow: **Understand → Plan → Implement → Verify → Review.**

### Stage 0 — one hour, no behaviour change, no risk

Fixes 9 criticals' root causes and 25 mediums by **deletion only**.

1. `lifecycle.py:162, 187` — capture `failure_stage` **before** the transition. **(C-13)**
2. `renderers.py:74` — delete the hardcoded `"Signature: Verified"`; `lifecycle.py:221-232` — delete the `preverified_sha256` fast path, call `verify_manifest` unconditionally. **(C-01, C-12)**
3. `error_handler.py:9-16, 100-133` — import `DomainError` and `pydantic.ValidationError`; add branches. 3 lines. **(C-05)** Delete `EXIT_USAGE`/`EXIT_CONFLICT` or wire them.
4. `fs.py:50-51` — `tempfile.mkstemp(dir=target.parent, …)`. One line. **(C-11)**
5. `renderers.py:294-299` — route `format_utc_zulu` through the existing `_to_ist` naive guard. One line. **(C-04)**
6. `gate.py:31` — invert to fail-closed on a missing probe, or wire a real probe from `core/operators.py`; add the missing `structlog.warning` on the swallow; `if result:` instead of `if result is True:`. **(C-02)**
7. `audit/renderers.py:78, 81, 117` — remove the three unconditional `"Chain ✓ VALID"` strings and print the real verdict (the TUI already computes it). **(C-03)**
8. `pip_backend.py:40` — pass a scrubbed `env` (or `--isolated`); redact URL-with-credentials from the stderr tail before it reaches `update_history`. **(C-09)**
9. `migration.py:311` — set `mutated = True` **after** `apply_migrations` returns; do **not** call `finish_update_migration` on the failure path. **(C-14)**
10. `marker.py:28` — `{**data, "marker_schema": MARKER_SCHEMA}`. One line. **(C-17)**
11. `migrations.py` — delete the 9 dead `else: with bind.begin()` branches. **25 lines.** (§6.6 Tier 1)
12. Delete the 6 redundant `with update_lock():` wrappers; collapse `lock.py` to a 3-line pass-through; delete the depth counter. **(R-70)**
13. Delete the 4 vacuous `check_contained` calls; the dead `write_anchor`; `fetch_artifact_bytes`; `_verify_artifact_integrity`; `do_export`; `_how_text`; `KeysModal.KEYS`; `health_dot`; `EntityNotFoundError`. **(H-38, §7.1)** — do **not** delete `stage_from_state` or `verify_artifact_signature_streaming`; both are shipped per §7.1's withdrawal notes.

### Stage 1 — data loss and forensic integrity (needs a test written first)

14. `migration.py:156-163` — replace `shutil.copy2` with copy-to-temp + `fsync` + `os.replace` + `PRAGMA wal_checkpoint(TRUNCATE)` + sidecar removal. Add `DatabaseSessionManager.replace_database(path)` so the `_engine = None` surgery moves into the DB layer. **(C-06)**
15. `migration.py:225, 236` — put `transaction_id` in the backup filename; move `keep_backups=3` to one constant. **(C-20)**
16. `migration.py:198-204` — check `current > meta["schema_target"]` (and keep `schema_min` as a lower bound). **Fix `test_migration_race.py:72-103` to `parametrize` over the four `RecoveryError` causes with `match=` on each** — otherwise the test keeps passing on the wrong branch. **(C-07)**
17. `helpers.py:49-55` — encrypt into a temp file and `os.replace`; never write plaintext. Add a `try/finally` to `atomic_write_lines`. **(C-24)**
18. `audit/exporter.py:61-70` — refuse (or loudly warn) when `verify().is_valid` is `False`; sign the bundle header the way anchors are signed. **(H-42)**
19. `audit/anchor.py:77-83` — a missing `signature`/`key_id` must be an **error**, not a skip. **(H-38)**
20. `audit/anchor.py:162` — move `sign_bytes` inside the `try`, so the cooldown backoff is persisted. **(H-41)**
21. `audit/verifier.py:64-87` — make `verify_event` a thin wrapper over `_row_mismatch`, restoring the `prev_chain` check in the UI verdict. **(H-48)**
22. Write the missing tests first: `restore_backup` (SQLite + PG), the **negative** anchor-signature case, the KDF-downgrade case, and both redirect-**refusal** cases. **(C-19, §8.8)**

### Stage 2 — supply chain (needs a release-process decision)

23. `install.sh:622` / `install.ps1:613` — stop provisioning trust keys from the release channel. Either seed the burned-in key, or ship the bundle **inside the signed manifest**. Prefer: publish `trusted-keys.bundle` only alongside a manifest that carries its own signature, and have the installer accept a bundle only when a signature over it verifies against a key already in the store. **(C-08)**
24. `install.sh:441-454` — move the `TRACE_RELEASE_SHA256`/cosign block so it applies to the `git clone` path too, and **fail closed** (loudly) when cosign is requested but absent. **(H-31, H-32)**
25. `install.sh:596` — hash-lock the `pip` bump or delete it. **(H-28)**
26. `install.sh:486-492` — route the unpinned path through the same mktemp → verify → extract discipline as the pinned path. **(H-27)**
27. `install.ps1:194-201` — handle `$null -eq $LASTEXITCODE` the way `:171-175` already does. **(H-33)**
28. `install.sh:300` — `if [ "$TRACE_REINSTALL" = 1 ]` instead of `${VAR:+}`. **(H-29)**
29. `README.md:105, 110` — pin the install commands to a tag, and say the installer verifies a signature. **(H-34)**
30. `release/verify_release.py:56-60` — check all **three** version copies. **(§9.4)**

### Stage 3 — reuse, batch 1 (the Tier-2 list; each is a small helper + a mechanical call-site sweep)

Order by lines-removed ÷ risk:

31. `core/canonical.py:is_naive` → the 3 sites. **(R-31)**
32. `core/fs.py:read_json_record` / `write_json_record` → the 5 + 3 sites. **(R-61, R-62, C-18)**
33. `core/database/session.py:sqlite_file_path` → 2 sites; fix `pgcode` → `sqlstate` in the same file. **(R-65, H-44)**
34. `core/cli/error_handler.py` — one ordered `specs` tuple for all mapped types. **(R-43)**
35. `core/ui/renderers.py:render_dossier` → the 2 feature renderers; `create_dual_key_value_grid` finally gets used. **(R-03)**
36. Factor the audit/case dossier into **data + per-surface formatting**; delete the TUI twin (and gain the 3 hash rows + UTC zulu in the TUI for free). **(R-04)**
37. `core/cli/doctor.py:collect_diagnostics` → the TUI stops importing `_`-prefixed symbols. **(R-23)**
38. `BaseShellHandler._complete_flag_value` → the 2 handlers. **(R-17)**
39. `cases/domain.py:parse_case_status_filter`, `parse_audit_filter`, `confirm_typed_number`, `normalise_optional`, `changed_fields` (service stops ignoring it), `validate_tags` (3 sources → 1). **(R-19, R-22, R-16, R-45, R-46)**
40. `migrations.py:_ensure_columns` → 4 migrations. **(R-78)**
41. `updates/stages.py` — one `Stage → 3 labels` mapping + a wired-in state→stage function + a `STAGE_FAILED_LABEL`. **(R-69, H-71)**
42. `updates/lifecycle.py:_record_failure`. **(R-66)**
43. `core/canonical.py:validate_release_id` + `validate_version` → `lifecycle.py:302-307`, `make_manifest.py:57-65`. **(R-27)**
44. One `UpdateInstaller` service returning a small result object; CLI/REPL/TUI all call it. **(R-30, H-25)**
45. Module-level imports everywhere; delete the ~60 redundant function-local ones. **(R-80, R-13)**
46. `core/domain.py` — drop `ensure_utc`, add `__all__`, repoint the 4 mis-pathed `now_utc` imports. **(R-39)**

### Stage 4 — crash-safety and state-machine correctness

47. Implement `resume()` or delete `UpdateLifecycle.load()` — and make `_ALLOWED` permit `-> CHECKING` from any non-terminal state. **(H-04)**
48. Write `backup_path`/`release_id`/`migration_range` into **every** marker write, not just the success one. **(C-16)**
49. Add `HEALTH_CHECK` and `ROLLED_BACK` to `recovery.py`'s trigger set; advance `previous-version` on rollback. **(H-13, H-16)**
50. `_verify_activation` equivalent for the post-rollback path. **(§4.5)**
51. `stage_release` should detect an existing *matching* release and skip, so a crash is resumable. **(C-15)**
52. Delete the 2 dead `AVAILABLE_BUT_*` states, or wire the deferral path that `is_installable`'s `(False, reason)` return already represents. **(§4.5)**
53. Delete the 6 redundant `with update_lock():` wrappers (done in Stage 0) and the thread-local depth counter with them. **(R-68, R-70)**

### Stage 5 — the migrations module

54. Delete the 9 dead Engine branches (done in Stage 0).
55. Make migration 011 best-effort with a verifier, or move it out of the auto-run path. **(H-58)**
56. Replace the source-text checksum with a schema-state checksum, or add a documented, tested escape hatch. **(H-57)**
57. `_sqlite_lock_path` → `if not url.startswith("sqlite"): return None`; reuse `sqlite_file_path`. **(H-59)**
58. Add a duplicate-version/name check to `register_migration`. **(§4.2)**
59. Add verifiers to migrations 007 and 016, or drop the "idempotent" claim from their docstrings. **(§4.2)**
60. Add a foreign-database guard + a contiguity check. **(H-63, H-64)**
61. Make `fetch_db_snapshot` / `get_pending_migrations` stop doing DDL on a read path, and take the already-fetched applied list. **(C-22)**
62. Make `DateTime(timezone=True)` actually round-trip: either a `TypeDecorator` on a `UTCDateTime` type, or an explicit UTC re-assumption in the row mappers. This is the structural fix for C-04. **(§4.1)**
63. A test asserting each name in `_CASE_COLUMN_DEFINITIONS` appears in `CaseModel.__table__`. **(R-37)**

### Stage 6 — the TUI

64. Fix the 3 dead palette commands — an explicit `{command_id: bound_method}` dict, or the prefix-tolerant dispatch `settings.py` already uses. **(H-68)**
65. Move the `verify_event` calls off the event loop (worker + a crypto cache keyed on `(seq, chain_hash)`), and guard the `audit.py` call site. **(C-21)**
66. `_check_text` → a worker; the "Checking…" paint becomes real. **(H-65)**
67. `_storage_check` → stop writing a probe file on every render; probe once per process. **(H-66)**
68. Route all three status renderings through `get_status_style_and_label`; add the glyph to its return. **(R-01)**
69. Make `tui/theme.py` reference `THEME_TOKENS` for all 10 colours, and reconcile `panel`/`DOT_OK` with it. **(H-69, H-70)**
70. Split `settings.py` (587 lines, 13 concerns) — extracting `check_state()` kills 4 findings at once.
71. Wire the harness: `set_interval` for debounces, one `refresh_data` for all three views, `Table` widgets for the action rows, `on_mount`-time focus, and pass `ctx.service` to the lifecycle.

### Stage 7 — cases + audit correctness

72. `cases/dto.py` + `cases/domain.py` — the tag rule in **one** place, and `from_domain` via `model_validate`. **(R-22)**
73. `cases/domain.py:110-112` — replace `object.__setattr__` with a model-level validate-assign.
74. Wire or delete `UNDER_REVIEW` (currently filterable, advertised, and unreachable).
75. `cases/repository.py:298` — `range(9999)`, or widen the grammar.
76. `cases/repository.py:256-265` — `SELECT max(CAST(substr(...)))` instead of loading the year; stop the 10 000-`flush()` loop.
77. `cases/service.py` — the actor comes from the gated `OperatorModel`, not a DTO field. **(H-53)**
78. `cases/service.py:258` — the ledger gets the sanitised reason. **(H-55)**
79. `cases/service.py:251` — `if not pinned: raise` (an outbox is mandatory when the hook is registered). **(§4.3)**
80. `cases/repository.py:220-240` — move the archive-first precondition into the repository. **(H-54)**
81. `cases/repository.py:57` — `parse_enum_value` so a forward-incompatible status degrades instead of exploding. **(H-62)**
82. `core/operators.py` — a partial unique index for one admin row; `sqlstate`; and stop auto-provisioning on a *read*. **(C-23, H-44, H-74)**
83. `core/service.py:57-61` — `post_commit` failures are swallowed and logged by contract, matching the docstring.
84. `audit/domain.py` — `HASH_ALGO` must actually drive the hash; hex-only, case-normalised hash fields. **(H-46, H-49)**
85. `audit/models.py` — the chain-state head needs integrity protection. **(H-39)**
86. `AnchorIntentModel` — a unique constraint on `(case_number, seq)`. **(H-40)**
87. `audit/builder.py:21-29` — stop substring-matching argv; `command` should be the *actual* command, not a heuristic. **(H-50)**
88. `audit/signing.py:119-130` — fsync the key files, write the pointer last, and consider an ACL call on Windows. **(H-51, H-73)**
89. `audit/vault.py` — read and verify `alg`; AAD the header; justify or lower `MAX_KDF_ITERATIONS`. **(§4.4)**
90. `audit/shell_handler.py:222-228` — the REPL must own the tamper policy it asked for. **(§4.4)**
91. The anchor's outbox: bound the SELECT, add per-sink failure isolation, and derive the anchors dir once. **(§4.4)**

### Stage 8 — test suite

92. **Fix `temp_storage_root` to nest**, and set `TRACE_STORAGE_ROOT` to an absolute tmp path in CI. This one change kills 11 duplicated setup blocks, removes the shared-`install_root` order dependence, and stops CI writing into the checkout. **(H-78, T-01)**
93. Delete `test_phase_a_p0/p1/c` after redistributing by module; rename `test_subpart2_readiness.py` → `test_canonical_json.py` and keep 2 tests. **(§8.7)**
94. Delete the 3 tautologies and the 1 mock-asserting test; fix the 2 indistinguishable rollback tests with `parametrize` + `match=`. **(§8.2, §8.4)**
95. Fix `test_postgres.py:22` to **not** fall back to `TRACE_DATABASE_URL`. **(H-76)**
96. Fix `test_no_telemetry.py:8` to use `Path(__file__).resolve().parents`. **(H-75)**
97. Turn the 3 `if sys.platform != "win32"` blocks into `skipif`, and add a Windows ACL test. **(H-73)**
98. Add `pytest-timeout`; bound all 6 unbounded `join()`/`map()` calls; inject the retry sleep so `_with_retries` becomes testable. **(§8.5)**
99. One `parametrize` sweep over the ~40 near-identical functions. **(T-14)**
100. Promote the 14 `_`-prefixed symbols the tests import. **(T-15)**
101. Add the missing coverage from §8.1, worst-first: `restore_backup`, `check_contained`, the redirect refusals, the KDF bound, the negative anchor-signature case, `prune_retention`, `sign_release`/`verify_release`, `core/ui/theme.py`, `exit_codes.py`.
102. Add `shellcheck` to CI (686 lines of POSIX shell, unlinted), keep PSScriptAnalyzer for the ps installer, and add `ruff` + a dead-code pass — one run of each would have caught most of §6.
103. Make the `postgres-integration` job count toward coverage, or exclude `tests/integration/` from the matrix run with `-m 'not integration'`.

### Two things this report deliberately does **not** recommend

- **Deleting `/docs` from `.gitignore`.** The 6,000-line design history is a genuine asset for a forensic tool, and `AGENTS.md` §12 already mandates a per-person changelog — which lives in a tracked folder. Un-ignoring `/docs` and pointing `test_security_regressions.py:2` at a real file is a small, high-value change, but it is a repo-policy decision, not an audit finding.
- **Rewriting the update pipeline.** Despite H-04 through H-16, the state machine's *shape* is right — the failures are an un-wired gate, one missing verification call, an ordering slip, and a schema-comparison inverted in one place. Stage 0 and Stage 4 fix all of them without touching the design. Per the repo's own `ponytail` rule: the smallest change that correctly solves exactly what is wrong.
