from .coverage import COVERAGE_RULES
from .antipattern import ANTIPATTERN_RULES

def all_rules():
    return list(COVERAGE_RULES) + list(ANTIPATTERN_RULES)

def run_rules(prompt, only=None):
    findings = []
    for rule in all_rules():
        for f in rule(prompt):
            if only is None or f.id in only:
                findings.append(f)
    return findings
