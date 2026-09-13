"""Tests for reusable completion core: rank, preview, fuzzy, cache, limit 8."""

import pytest
from prompt_toolkit.document import Document

from trace_core.cases.dto import CaseCreateDto
from trace_core.cases.service import CaseService
from trace_core.cli.shell import InteractiveShell
from trace_core.core.cli.completion import filter_completions, preview_case, rank_cases

pytestmark = pytest.mark.unit


def test_filter_completions_prefix_substring_fuzzy_limit() -> None:
    cands = [("case", ""), ("audit", ""), ("close", ""), ("clear", "")]
    assert filter_completions(cands, "ca", limit=8)[0][0] == "case"
    assert filter_completions(cands, "au", limit=8)[0][0] == "audit"
    # fuzzy: "cs" matches "case" (c...s)
    assert any(c[0] == "case" for c in filter_completions(cands, "cs", limit=8))
    # limit
    many = [(f"case{i}", "") for i in range(20)]
    assert len(filter_completions(many, "", limit=8)) == 8


def test_preview_case() -> None:
    from types import SimpleNamespace

    c = SimpleNamespace(number="2026-CR-0029", status="CLOSED", title="Laptop SSD")
    num, preview = preview_case(c)
    assert num == "2026-CR-0029"
    assert "CLOSED" in preview
    assert "Laptop SSD" in preview


def test_rank_active_first(service: CaseService) -> None:
    c1 = service.create_case(CaseCreateDto(title="Old", lead_examiner="Ex"))
    c2 = service.create_case(CaseCreateDto(title="New", lead_examiner="Ex"))
    # c2 is more recent (updated_at later)
    ranked = rank_cases([c1, c2], active_number=c1.number)
    assert ranked[0].number == c1.number  # active first
    ranked2 = rank_cases([c1, c2], active_number=None)
    # recent first when no active: c2 newer
    assert ranked2[0].number == c2.number


def test_ghost_contextAware(service: CaseService) -> None:
    shell = InteractiveShell(service=service)
    c = service.create_case(CaseCreateDto(title="Ghost", lead_examiner="Ex"))
    shell.active_case = c  # type: ignore[assignment]
    from prompt_toolkit.document import Document

    from trace_core.cli.shell import TraceAutoSuggest

    suggester = TraceAutoSuggest(shell)
    # empty ghost should suggest case show when active
    sugg = suggester.get_suggestion(None, Document(""))  # type: ignore[arg-type]
    assert sugg is not None
    # case show ghost for active
    sugg2 = suggester.get_suggestion(None, Document("case show "))  # type: ignore[arg-type]
    # should suggest active number
    assert sugg2 is not None and c.number in sugg2.text


def test_hide_irrelevant_globals_when_active(service: CaseService) -> None:
    shell = InteractiveShell(service=service)
    c = service.create_case(CaseCreateDto(title="Hide", lead_examiner="Ex"))
    shell.active_case = c  # type: ignore[assignment]
    doc = Document("")
    completions = [c.text for c in shell.completer.get_completions(doc, None)]
    # when active and empty, prioritize case/audit, not clear/help at top
    assert completions[0] in ("case", "audit")


def test_value_completions_no_hashes(service: CaseService) -> None:
    service.create_case(CaseCreateDto(title="SearchMe", lead_examiner="Alice", tags=["usb"]))
    from trace_core.core.cli.completion import complete_search_terms, complete_tags

    search_vals = complete_search_terms(service)
    assert any("SearchMe" in v[0] for v in search_vals)
    tag_vals = complete_tags(service)
    assert any(v[0] == "usb" for v in tag_vals)
    # ensure no hash in dropdown
    for _, meta in search_vals + tag_vals:
        assert "a3f1" not in meta.lower()
