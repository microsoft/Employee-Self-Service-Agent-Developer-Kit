import dataclasses

from instruction_engine.models import Finding


def test_regex_finding_defaults_source_to_regex():
    f = Finding(id="AP001", severity="error", category="antipattern",
                section="Formatting", line=3, message="m", suggestion="s")
    assert f.source == "regex"


def test_regex_and_semantic_findings_share_shape():
    regex_finding = Finding(id="AP001", severity="error", category="antipattern",
                             section="Formatting", line=3, message="m", suggestion="s")
    semantic_finding = Finding(id="INSTR-020", severity="warn", category="over-restriction",
                                section="Formatting", line=0, message="m", suggestion="s",
                                source="semantic")

    assert {f.name for f in dataclasses.fields(regex_finding)} == \
        {f.name for f in dataclasses.fields(semantic_finding)}
    assert set(dataclasses.asdict(regex_finding).keys()) == \
        set(dataclasses.asdict(semantic_finding).keys())
    assert regex_finding.source == "regex"
    assert semantic_finding.source == "semantic"
