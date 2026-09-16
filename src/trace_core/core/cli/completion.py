"""Reusable completion core: ranking, preview, fuzzy, cache, limit 8, no SQLAlchemy."""

import time
from collections.abc import Callable, Iterable
from typing import Any

_CACHE: dict[str, tuple[float, Any]] = {}
_TTL = 2.0  # seconds
_MAX_CACHE = 64


def _cached(key: str, loader: Callable[[], list[tuple[str, str]]]) -> list[tuple[str, str]]:
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]
    val = loader()
    _CACHE[key] = (now, val)
    while len(_CACHE) > _MAX_CACHE:
        _CACHE.pop(next(iter(_CACHE)))
    return val


def _service_key(service: Any, kind: str, extra: str = "") -> str:
    """Stable cache key from sanitized DB identity. Never id() or raw URLs."""
    from trace_core.core.database.session import db_identity

    try:
        ident = db_identity(getattr(service, "session_manager", None))
    except Exception:
        ident = "unknown"
    return f"{kind}:{ident}:{extra}"


def cached_complete(
    kind: str, service: Any, loader: Callable[[], list[tuple[str, str]]], limit: int = 8, extra: str = ""
) -> list[tuple[str, str]]:
    """Single source for cached completion loaders. try/except→[], slice to limit."""

    def _safe() -> list[tuple[str, str]]:
        try:
            return loader()
        except Exception:
            return []

    return _cached(_service_key(service, kind, extra), _safe)[:limit]


def _fetch_cases(case_service: Any, include_deleted: bool = False) -> list[Any]:
    """Single source for completion case reads. Raises on DB failure (callers coerce to [])."""
    from trace_core.cases.dto import CaseFilterDto

    return case_service.list_cases(CaseFilterDto(include_deleted=include_deleted, limit=50))


def _distinct_terms(values: Iterable[Any], label: str, limit: int) -> list[tuple[str, str]]:
    """Sorted unique non-empty terms with preview labels. Single source for tag/search/actor lists."""
    terms = sorted({t for t in values if t})
    return [(t, f"{label} · {t}") for t in terms][:limit]


def filter_completions(candidates: list[tuple[str, str]], query: str, limit: int = 8) -> list[tuple[str, str]]:
    """Prefix → substring → fuzzy (contains) ranking, capped to 8. Pure, no DB."""
    if not query:
        return candidates[:limit]
    q = query.lower()
    prefix = [c for c in candidates if c[0].lower().startswith(q)]
    if len(prefix) >= limit:
        return prefix[:limit]
    substr = [c for c in candidates if q in c[0].lower() and c not in prefix]
    merged = prefix + substr
    if len(merged) >= limit:
        return merged[:limit]

    # fuzzy: all chars of query appear in order in candidate
    def _fuzzy(s: str) -> bool:
        it = iter(s.lower())
        return all(ch in it for ch in q)

    fuzzy = [c for c in candidates if _fuzzy(c[0]) and c not in merged]
    return (merged + fuzzy)[:limit]


def rank_cases(cases: list[Any], active_number: str | None = None) -> list[Any]:
    """Active first, then recent (updated_at desc), then OPEN before others."""

    def _key(c: Any) -> tuple[int, float, int, int]:
        is_active = 0 if active_number and c.number == active_number else 1
        try:
            ts = c.updated_at.timestamp() if hasattr(c.updated_at, "timestamp") else 0
        except Exception:
            ts = 0
        raw_status = getattr(c, "status", "")
        is_open = 0 if getattr(raw_status, "value", raw_status) == "OPEN" else 1
        # tie-breaker: larger case number (more recent) first when ts equal
        try:
            seq = int(str(c.number).split("-")[-1])
        except Exception:
            seq = 0
        return (is_active, -ts, is_open, -seq)

    return sorted(cases, key=_key)


def preview_case(c: Any) -> tuple[str, str]:
    """Human preview: 2026-CR-0029 · CLOSED · Laptop SSD (width-aware)."""
    from trace_core.core.ui.renderers import breakpoint_width, fit_text, title_max_width

    bp, term_w = breakpoint_width()
    max_title = min(title_max_width(bp, term_w) or 36, 36)
    if bp == "XS":
        max_title = min(max_title, 14)

    status = getattr(c, "status", "")
    status_str = getattr(status, "value", str(status)) if status else ""
    raw_title = getattr(c, "title", "") or ""
    title = fit_text(raw_title, max_title)
    return (c.number, f"{c.number} · {status_str} · {title}".strip(" ·"))


def complete_from_audit(audit_service: Any, limit: int = 8) -> list[tuple[str, str]]:
    """Seq completions with preview, cached 2s, limit 8."""

    def _load() -> list[tuple[str, str]]:
        evts = audit_service.list_events()[:20]
        out = []
        for e in evts:
            preview = f"Seq {e.seq} · {e.action.value} · {e.subject_case_number}"
            out.append((str(e.seq), preview))
        return out

    return cached_complete("audit", audit_service, _load, limit)


def number_group(number: str) -> str:
    """Middle-code group (CR/NR/CLI/…) for case numbers. Single source."""
    try:
        return number.split("-")[1] if "-" in number else "OTHER"
    except Exception:
        return "OTHER"


def _group_ranked(ranked: list[Any]) -> tuple[dict[str, list[Any]], list[str]]:
    """Group ranked cases by prefix like CR/NR/CLI, keeping rank order inside groups."""
    grouped: dict[str, list[Any]] = {}
    order: list[str] = []
    for c in ranked:
        prefix = number_group(c.number)
        if prefix not in grouped:
            grouped[prefix] = []
            order.append(prefix)
        grouped[prefix].append(c)
    return grouped, order


def complete_from_cases(case_service: Any, active_number: str | None = None, limit: int = 8) -> list[tuple[str, str]]:
    """Case-number completions ranked active→recent→open, grouped by prefix CR/NR/CLI, cached 2s, limit 8."""
    cap = limit + 4  # room for group headers

    def _load() -> list[tuple[str, str]]:
        ranked = rank_cases(_fetch_cases(case_service, include_deleted=True), active_number)
        grouped, order = _group_ranked(ranked)
        out: list[tuple[str, str]] = []
        for pref in order:
            # header as non-insertable separator (text="" display="── CR ──")
            if len(order) > 1:
                out.append(("", f"── {pref} ──"))
            for c in grouped[pref]:
                out.append(preview_case(c))
                if len(out) >= cap:
                    break
            if len(out) >= cap:
                break
        return out

    return cached_complete("cases", case_service, _load, cap, extra=active_number or "")


def complete_tags(case_service: Any, limit: int = 8) -> list[tuple[str, str]]:
    """Tag completions from live case taxonomy."""

    def _load() -> list[tuple[str, str]]:
        return _distinct_terms([t for c in _fetch_cases(case_service) for t in c.tags], "Tag", limit)

    return cached_complete("tags", case_service, _load, limit)


def complete_search_terms(case_service: Any, limit: int = 8) -> list[tuple[str, str]]:
    """Title/examiner completions for search boxes."""

    def _load() -> list[tuple[str, str]]:
        cases = _fetch_cases(case_service)
        return _distinct_terms([c.title for c in cases] + [c.lead_examiner for c in cases], "Search", limit)

    return cached_complete("search", case_service, _load, limit)


def complete_actors(audit_service: Any, limit: int = 8) -> list[tuple[str, str]]:
    """Actor completions from live ledger."""

    def _load() -> list[tuple[str, str]]:
        evts = audit_service.list_events()[:50]
        return _distinct_terms([e.actor for e in evts], "Actor", limit)

    return cached_complete("actors", audit_service, _load, limit)
