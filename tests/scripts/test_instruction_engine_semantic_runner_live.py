import pytest

from instruction_engine.semantic_rules.runner import run_semantic_pass

_SAMPLE_INSTRUCTIONS = """
#Core identity
You are an HR assistant. Your tone is always warm and ready to lend a hand.

#Formatting rules
Always offer to help with anything else at the end of every response.
Never suggest actions the user did not ask about.
"""


@pytest.mark.live
def test_real_llm_call_returns_well_formed_findings():
    findings = run_semantic_pass(_SAMPLE_INSTRUCTIONS)
    assert isinstance(findings, list)
    for f in findings:
        assert f.source == "semantic"
        assert f.id.startswith("INSTR-")
        assert f.message
