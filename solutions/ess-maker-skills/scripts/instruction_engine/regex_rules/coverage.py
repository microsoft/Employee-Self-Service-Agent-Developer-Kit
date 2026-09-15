import re
from ..models import Finding

def _has(prompt, pattern):
    return re.search(pattern, prompt.raw, re.IGNORECASE) is not None

def _cov(id, present, message, suggestion):
    if present:
        return []
    return [Finding(id=id, severity="error" if id in ("COV001","COV002") else "warn",
                    category="coverage", section="(document)", line=0,
                    message=message, suggestion=suggestion)]

def check_grounding(p):
    present = _has(p, r"never answer.*from (memory|training)") or \
              _has(p, r"grounding guard")
    return _cov("COV001", present,
                "No grounding guard forbidding answers from memory/training.",
                "Add: never answer info-seeking from memory; use a tool, clarify, or abstain.")

def check_abstain(p):
    present = _has(p, r"couldn'?t find a definitive answer") or _has(p, r"\babstain\b")
    return _cov("COV002", present,
                "No abstain/fallback verbatim string.",
                "Add a fixed 'couldn't find a definitive answer' fallback line.")

def check_escalation(p):
    present = _has(p, r"escalat") or _has(p, r"contact.*(hr|people team)")
    return _cov("COV003", present, "No escalation path.",
                "Add an HR/People-team escalation instruction.")

def check_sensitive(p):
    present = _has(p, r"sensitive") or _has(p, r"verbatim")
    return _cov("COV004", present, "No sensitive-topic handling.",
                "Add a sensitive-topic verbatim response block.")

def check_identity(p):
    present = any("identity" in s.name.lower() or "core" in s.name.lower()
                  for s in p.sections)
    return _cov("COV005", present, "No core identity/role section.",
                "Add a #Core identity section defining role and scope.")

COVERAGE_RULES = [check_grounding, check_abstain, check_escalation,
                  check_sensitive, check_identity]
