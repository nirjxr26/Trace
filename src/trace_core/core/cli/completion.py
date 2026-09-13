"""Reusable completion core: ranking, preview, fuzzy, cache, limit 8, no SQLAlchemy."""

import time
from typing import Any

_CACHE: dict[str, tuple[float, Any]] = {}
_TTL = 2.0  # seconds


def _cached(key: str, loader):  # type: ignore[no-untyped-def]
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]
    val = loader()
    _CACHE[key] = (now, val)
    return val


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


def rank_cases(cases: list[Any], active_number: str | None = None) -> list[Any]:  # type: ignore[no-untyped-def]
    """Active first, then recent (updated_at desc), then OPEN before others."""

    def _key(c):  # type: ignore[no-untyped-def]
        is_active = 0 if active_number and c.number == active_number else 1
        try:
            ts = c.updated_at.timestamp() if hasattr(c.updated_at, "timestamp") else 0
        except Exception:
            ts = 0
        is_open = 0 if str(getattr(c, "status", "")) == "OPEN" else 1
        # tie-breaker: larger case number (more recent) first when ts equal
        try:
            seq = int(str(c.number).split("-")[-1])
        except Exception:
            seq = 0
        return (is_active, -ts, is_open, -seq)

    return sorted(cases, key=_key)


def preview_case(c: Any) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    """Human preview: 2026-CR-0029 · CLOSED · Laptop SSD"""
    status = getattr(c, "status", "")
    status_str = getattr(status, "value", str(status)) if status else ""
    title = (getattr(c, "title", "") or "")[:20]
    return (c.number, f"{c.number} · {status_str} · {title}".strip(" ·"))


def complete_from_audit(audit_service: Any, limit: int = 8) -> list[tuple[str, str]]:  # type: ignore[no-untyped-def]
    """Seq completions with preview, cached 2s, limit 8."""

    def _load():  # type: ignore[no-untyped-def]
        try:
            evts = audit_service.list_events()[:20]
            out = []
            for e in evts:
                preview = f"Seq {e.seq} · {e.action.value} · {e.subject_case_number}"
                out.append((str(e.seq), preview))
            return out
        except Exception:
            return []

    return _cached(f"audit:{id(audit_service)}", _load)[:limit]


def complete_from_cases(case_service: Any, active_number: str | None = None, limit: int = 8) -> list[tuple[str, str]]:  # type: ignore[no-untyped-def]
    """Case-number completions ranked active→recent→open, grouped by prefix CR/NR/CLI, cached 2s, limit 8."""

    def _load():  # type: ignore[no-untyped-def]
        try:
            from trace_core.cases.dto import CaseFilterDto

            cases = case_service.list_cases(CaseFilterDto(include_deleted=True, limit=50))
            ranked = rank_cases(cases, active_number)
            # group by prefix like CR/NR/CLI for together + space
            grouped: dict[str, list[Any]] = {}
            order: list[str] = []
            for c in ranked:
                try:
                    prefix = c.number.split("-")[1] if "-" in c.number else "OTHER"
                except Exception:
                    prefix = "OTHER"
                if prefix not in grouped:
                    grouped[prefix] = []
                    order.append(prefix)
                grouped[prefix].append(c)
            out: list[tuple[str, str]] = []
            for pref in order:
                # header as non-insertable separator (text="" display="── CR ──")
                if len(order) > 1:
                    out.append(("", f"── {pref} ──"))
                for c in grouped[pref]:
                    out.append(preview_case(c))
                    if len(out) >= 20:
                        break
            return out
        except Exception:
            return []

    key = f"cases:{id(case_service)}:{active_number}"
    # filter after grouping, but keep header logic inside _load already; just cap
    return _cached(key, _load)[: limit + 4]  # +4 for headers


def complete_tags(case_service: Any, limit: int = 8) -> list[tuple[str, str]]:  # type: ignore[no-untyped-def]
    def _load():  # type: ignore[no-untyped-def]
        try:
            from trace_core.cases.dto import CaseFilterDto

            cases = case_service.list_cases(CaseFilterDto(limit=50))
            tags = sorted({t for c in cases for t in c.tags})
            return [(t, f"Tag · {t}") for t in tags]
        except Exception:
            return []

    return _cached(f"tags:{id(case_service)}", _load)[:limit]


def complete_search_terms(case_service: Any, limit: int = 8) -> list[tuple[str, str]]:  # type: ignore[no-untyped-def]
    def _load():  # type: ignore[no-untyped-def]
        try:
            from trace_core.cases.dto import CaseFilterDto

            cases = case_service.list_cases(CaseFilterDto(limit=50))
            terms = set()
            for c in cases:
                terms.add(c.title)
                terms.add(c.lead_examiner)
            # also audit actors
            return [(t, f"Search · {t}") for t in sorted(terms) if t][:limit]
        except Exception:
            return []

    return _cached(f"search:{id(case_service)}", _load)[:limit]


def complete_actors(audit_service: Any, limit: int = 8) -> list[tuple[str, str]]:  # type: ignore[no-untyped-def]
    def _load():  # type: ignore[no-untyped-def]
        try:
            evts = audit_service.list_events()[:50]
            actors = sorted({e.actor for e in evts})
            return [(a, f"Actor · {a}") for a in actors]
        except Exception:
            return []

    return _cached(f"actors:{id(audit_service)}", _load)[:limit]
