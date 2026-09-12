import re
from ..models import Finding

def _find_line(prompt, pattern):
    for i, line in enumerate(prompt.lines, 1):
        if re.search(pattern, line, re.IGNORECASE):
            return i
    return 0

def _cites(prompt):
    return re.search(r"\bcite\b", prompt.raw, re.IGNORECASE) is not None

def check_forced_citation(p):
    pat = r"cite (all|each|every)"
    line = _find_line(p, pat)
    if line:
        return [Finding(id="AP001", severity="error", category="antipattern",
                        section="(document)", line=line,
                        message="Forced/over-citation language ('cite all/each/every').",
                        suggestion="Cite only the most intent-specific source the user can access.")]
    return []

def check_access_scoping(p):
    if re.search(r"(cite|suggest).*article", p.raw, re.IGNORECASE | re.DOTALL) and \
       not re.search(r"access", p.raw, re.IGNORECASE):
        return [Finding(id="AP002", severity="error", category="antipattern",
                        section="(document)", line=_find_line(p, r"article"),
                        message="Cites/suggests articles without an access-scoping caveat.",
                        suggestion="Only cite/suggest articles the user has access to.")]
    return []

def check_unbounded_never(p):
    for s in p.sections:
        block = s.text
        if re.search(r"\bnever\b|\bdo not\b", block, re.IGNORECASE):
            items = re.findall(r"^\s*[-*]\s+", block, re.MULTILINE)
            if len(items) >= 10:
                return [Finding(id="AP003", severity="warn", category="antipattern",
                                section=s.name, line=s.start_line,
                                message=f"Unbounded 'Never' list ({len(items)} items) risks overrefusal.",
                                suggestion="Scope items to intent conditions or split into a policy block.")]
    return []

def check_link_integrity(p):
    if _cites(p) and not re.search(r"preserve.*url|never (shorten|rewrite|invent)",
                                   p.raw, re.IGNORECASE):
        return [Finding(id="AP005", severity="warn", category="antipattern",
                        section="(document)", line=_find_line(p, r"\bcite\b"),
                        message="Cites sources but has no link-integrity instruction.",
                        suggestion="Add: preserve every retrieved URL exactly; never invent links.")]
    return []

def check_citation_count(p):
    if _cites(p) and not re.search(r"sources.*match|match.*inline|citation.*consisten",
                                   p.raw, re.IGNORECASE):
        return [Finding(id="AP006", severity="warn", category="antipattern",
                        section="(document)", line=_find_line(p, r"\bcite\b"),
                        message="No rule requiring the Sources list to match inline citations.",
                        suggestion="Require inline citation count to equal the Sources list.")]
    return []

def check_variable_leakage(p):
    if re.search(r"(Global\.ESS_|System\.User\.)", p.raw) and \
       not re.search(r"(do not|never) expose (variable|internal)", p.raw, re.IGNORECASE):
        return [Finding(id="AP007", severity="warn", category="antipattern",
                        section="(document)", line=_find_line(p, r"Global\.ESS_|System\.User\."),
                        message="Uses raw context variables without a 'don't expose variable names' guard.",
                        suggestion="Add a guard: never expose variable names or internal reasoning.")]
    return []

def check_contradiction(p):
    if re.search(r"answer.*complete", p.raw, re.IGNORECASE) and \
       re.search(r"never (offer|append|invite)", p.raw, re.IGNORECASE):
        return [Finding(id="AP004", severity="review", category="antipattern",
                        section="(document)", line=0,
                        message="Possible contradiction: 'answer completely' vs 'never offer next steps'.",
                        suggestion="Confirm the boundary between completeness and no-offer is unambiguous.")]
    return []

def check_tone_conflict(p):
    if re.search(r"warm|empathetic", p.raw, re.IGNORECASE) and \
       re.search(r"overrides all|verbatim", p.raw, re.IGNORECASE):
        return [Finding(id="AP008", severity="review", category="antipattern",
                        section="(document)", line=0,
                        message="Warmth tone alongside absolutist verbatim overrides may whiplash.",
                        suggestion="Confirm tone guidance and hard-override blocks are reconcilable.")]
    return []

ANTIPATTERN_RULES = [check_forced_citation, check_access_scoping,
                     check_unbounded_never, check_link_integrity,
                     check_citation_count, check_variable_leakage,
                     check_contradiction, check_tone_conflict]
