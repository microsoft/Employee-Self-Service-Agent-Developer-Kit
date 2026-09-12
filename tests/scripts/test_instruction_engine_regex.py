from instruction_engine.parser import parse
from instruction_engine.regex_rules import run_rules
from instruction_engine.models import Section, Prompt, Finding
from instruction_engine.normalize import normalize


def test_forced_citation_flagged():
    p = parse("#Formatting rules\nWhen multiple articles contribute, cite all.")
    findings = [f for f in run_rules(p) if f.id == "AP001"]
    assert findings and findings[0].severity == "error"


def test_missing_link_integrity_flagged_when_citing():
    p = parse("#Formatting rules\ncite each contributing article")
    ids = [f.id for f in run_rules(p)]
    assert "AP005" in ids


def test_link_integrity_present_suppresses_ap005():
    p = parse("#Formatting rules\ncite each article. Preserve every retrieved URL exactly.")
    ids = [f.id for f in run_rules(p)]
    assert "AP005" not in ids


def test_unbounded_never_list_flagged():
    never = "Never:\n" + "\n".join(f"- do not {i}" for i in range(12))
    p = parse("#Handoff\n" + never)
    ids = [f.id for f in run_rules(p)]
    assert "AP003" in ids


def test_access_scoping_flagged_across_lines():
    p = parse("#Formatting\nCite the specific source used.\nOpen the most relevant article.")
    ids = [f.id for f in run_rules(p)]
    assert "AP002" in ids


def test_missing_grounding_guard_flagged():
    p = parse("#Core identity\nyou are an agent")
    ids = [f.id for f in run_rules(p)]
    assert "COV001" in ids


def test_grounding_guard_present_not_flagged():
    p = parse("#Grounding\nNEVER answer info-seeking from memory or training data.")
    ids = [f.id for f in run_rules(p)]
    assert "COV001" not in ids


def test_finding_defaults():
    f = Finding(id="AP001", severity="error", category="antipattern",
                section="Formatting", line=3, message="m", suggestion="s")
    assert f.severity == "error"


def test_prompt_holds_sections():
    s = Section(name="Core identity", level=1, start_line=1, end_line=2, text="x")
    p = Prompt(sections=[s], raw="x", lines=["x"])
    assert p.sections[0].name == "Core identity"


def test_strips_zero_width_and_nbsp():
    raw = "a​b c﻿"
    out, lines = normalize(raw)
    assert out == "ab c"
    assert lines == ["ab c"]


def test_preserves_line_count_and_trims_trailing_ws():
    raw = "line1   \nline2\t\n"
    out, lines = normalize(raw)
    assert lines == ["line1", "line2", ""]


def test_splits_on_hash_headers():
    raw = "#Core identity\nyou are\n#Formatting rules\ncite"
    p = parse(raw)
    names = [s.name for s in p.sections]
    assert "Core identity" in names and "Formatting rules" in names


def test_captures_mandatory_caps_marker():
    raw = "#A\nx\nMANDATORY VERBATIM RESPONSES FOR SENSITIVE TOPICS\ny"
    p = parse(raw)
    assert any("MANDATORY" in s.name for s in p.sections)


def test_preamble_becomes_implicit_section():
    raw = "intro text\n#A\nx"
    p = parse(raw)
    assert p.sections[0].name == "(preamble)"
