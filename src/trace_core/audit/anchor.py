"""Single source for audit anchor files: schema, write on close, verify on demand."""

import json
from pathlib import Path
from typing import Any

from trace_core.audit.domain import SPEC_VERSION
from trace_core.core.canonical import canonical_ts, parse_trailing_seq
from trace_core.core.clock import now_utc
from trace_core.core.settings import settings


def anchor_path(case_number: str, seq: int) -> Path:
    """Filesystem location for a close-anchor. Single naming source."""
    return Path(settings.storage_root) / "anchors" / f"anchor-{case_number}-{seq}.json"


def write_anchor(case_number: str, seq: int, chain_hash: str) -> Path:
    """Persist an anchor record for the ledger head. Returns the written path."""
    payload = {
        "case": case_number,
        "last_seq": seq,
        "last_chain": chain_hash,
        "anchored_at": canonical_ts(now_utc()),
        "spec": SPEC_VERSION,
    }
    path = anchor_path(case_number, seq)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def read_anchor(anchor: str | Path) -> dict[str, Any]:
    """Load and parse an anchor file. Raises on unreadable content."""
    return json.loads(Path(anchor).read_text(encoding="utf-8"))


def latest_anchor_for(case_number: str) -> Path | None:
    """Newest anchor file for a case, if any. Single source for close output."""

    def _seq_of(path: Path) -> int:
        return parse_trailing_seq(path.stem) or -1

    try:
        matches = list(Path(settings.storage_root).glob(f"anchors/anchor-{case_number}-*.json"))
    except Exception:
        return None
    return max(matches, key=_seq_of) if matches else None


def verify_against_anchor(svc, res, anchor: str | None) -> None:  # type: ignore[no-untyped-def]
    """Compare a verify result against an anchor file. Raises AuditTamperError on tail mismatch."""
    if not anchor:
        return
    from trace_core.core.errors import AuditTamperError
    from trace_core.core.ui.renderers import console

    try:
        data = read_anchor(anchor)
        exp_seq = data.get("last_seq")
        exp_chain = data.get("last_chain")
        if res.is_valid and res.last_seq != exp_seq:
            console.print(f"[red]Anchor mismatch: DB last_seq {res.last_seq} != anchor {exp_seq}[/red]")
            raise AuditTamperError(f"Anchor tail mismatch at seq {exp_seq}")
        if res.is_valid and exp_chain:
            _, latest = svc.head()
            if latest != exp_chain:
                console.print(f"[red]Anchor chain mismatch: {latest} != {exp_chain}[/red]")
                raise AuditTamperError("Anchor chain mismatch")
    except AuditTamperError:
        raise
    except Exception as e:
        import typer

        typer.echo(f"Anchor read failed: {e}", err=True)
        raise typer.Exit(1)
