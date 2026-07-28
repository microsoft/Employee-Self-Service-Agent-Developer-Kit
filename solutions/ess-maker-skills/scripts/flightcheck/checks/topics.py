# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — New-topic validation (skill-6).

Programmatic checks for the ``create-new-topic`` setup skill (master-checklist
rows **S6.1** and **S6.2**). Skill-6 is a Workday-specialised refactor of the
``src/skills/topics/create`` authoring skill: it walks the operator through
creating a new custom topic (e.g. *Request Time Off*), wires its Workday
integration, and then verifies the result with the two **family** checkpoints
below — one row **per new topic** — each runnable in isolation via
``--checkpoint``:

  * ``TOPIC-TRIGGER-*`` (S6.1) — each new topic is a well-formed
    ``kind: AdaptiveDialog`` definition **and** has a trigger: a ``beginDialog``
    with a recognised trigger kind, plus (for LLM/intent-routed topics)
    ``modelDescription`` trigger phrases or ``triggerQueries``. PASS when the
    topic exists and its trigger/recognition is wired; FAILED when the
    definition or trigger is missing.
  * ``TOPIC-INTEGRATION-*`` (S6.2) — each new topic's Workday integration wiring
    resolves: any ``{{PLACEHOLDER}}`` scaffolding and unresolved ``<UPPERCASE>``
    tenant reference-ID tokens (e.g. ``<TENANT_NAME>``) have been replaced with
    real tenant values. PASS when no unresolved placeholders remain (a topic
    with no external wiring is a benign PASS — nothing to resolve); FAILED when
    placeholders are still present. **The tenant reference-ID *values* cannot be
    verified locally** — the remediation names the Workday SME as the party who
    must confirm the IDs are correct (the ``prog (+ SME for IDs)`` gate in
    ``tasks.md``); the checkpoint only proves the placeholders were resolved.

"New" is defined by an **OOTB-baseline diff**: a ``topics/*.mcs.yml`` file is a
new/custom topic when it has no byte-identical counterpart under the agent's
``.baseline/topics/`` snapshot (the post-push mirror of the installed solution).
OOTB pack topics therefore never emit rows — only topics authored or changed
since the extension-pack install do.

Design invariants (per ``scripts/flightcheck/AGENTS.md``):
  * **Never raise** — the dispatcher wraps every emitter so an unexpected
    failure degrades to a WARNING for that family instead of aborting the run.
  * **Pure local-file** — both emitters read the working copy only
    (``workspace/agents/*/topics/`` + ``.baseline/``); no HTTP, no client, no
    cassette (``clients=frozenset()``).
  * **Never return empty** — when there is no workspace or no custom topic, each
    emitter returns a single informational ``NOT_CONFIGURED`` row (id
    ``…-001``) so ``--checkpoint TOPIC-TRIGGER-*`` always resolves to a result.
  * **Every** ``CheckResult`` declares ``roles=`` (enforced by
    ``tests/flightcheck/test_check_roles.py``).
"""

from __future__ import annotations

import re
from collections import namedtuple
from pathlib import Path

from ..runner import CheckResult, Priority, Role, Status

DOC_BASE = (
    "https://learn.microsoft.com/en-us/copilot/microsoft-365/"
    "employee-self-service"
)
_DOC_TOPICS = f"{DOC_BASE}/workday#topics"

_CATEGORY = "Workday Topics"

# S6.1/S6.2 are gated "Environment Maker (+ Workday SME)" in tasks.md; the
# FlightCheck role for the Environment Maker persona is ESS_MAKER (matches
# skill-2's ESS-SOLN-001 and skill-5's maker-owned rows). The Workday SME
# obligation for tenant-ID *values* is carried in the remediation text and the
# playbook's attest overlay — there is no separate SME Role enum value.
_MAKER_ROLES = [Role.ESS_MAKER.value]

_AGENTS_ROOT = "workspace/agents"
_TOPICS_SUBDIR = "topics"
_BASELINE_SUBDIR = ".baseline"
_TOPIC_GLOB = "*.mcs.yml"
_TOPIC_SUFFIX = ".mcs.yml"

_TRIGGER_DESC = "New-topic trigger phrases + definition"
_INTEGRATION_DESC = "New-topic integration wiring (tenant reference IDs)"

# A topic is a well-formed Copilot Studio dialog when it declares this kind.
_ADAPTIVE_DIALOG_RE = re.compile(r"^\s*kind:\s*AdaptiveDialog\b", re.MULTILINE)

# Recognised trigger kinds. An OnRecognizedIntent topic is LLM/intent-routed and
# additionally needs trigger phrases; the OnRedirect/system + lifecycle kinds do
# not (they are invoked by another topic or by a runtime event).
_INTENT_TRIGGER = "OnRecognizedIntent"
_OTHER_TRIGGER_KINDS = (
    "OnRedirect",
    "OnConversationStart",
    "OnEvent",
    "OnError",
    "OnActivity",
    "OnSelectItem",
    "OnUnknownIntent",
)

# Trigger-phrase carriers for an intent-routed topic.
_MODEL_DESCRIPTION_RE = re.compile(r"^\s*modelDescription:\s*\S", re.MULTILINE)
_TRIGGER_QUERIES_RE = re.compile(r"\btriggerQueries\b")

# Integration-wiring markers — a topic that calls out to a system topic / flow /
# HTTP endpoint. Absence of all of these means the topic is purely
# conversational and has no tenant reference IDs to resolve.
_WIRING_MARKERS = (
    "BeginDialog",
    "InvokeFlowAction",
    "ScenarioName",
    "HttpRequest",
)

# Unresolved-placeholder markers. ``{{...}}`` is the scaffolding token the
# create skill leaves for values the operator must fill; ``<UPPER_CASE>`` is the
# convention for tenant reference-ID slots (e.g. ``<TENANT_NAME>``). Lowercase
# angle tokens like ``<date>`` / ``<reason>`` are slot *examples* inside trigger
# phrases and are intentionally NOT matched.
_PLACEHOLDER_RES = (
    re.compile(r"\{\{[^}\r\n]+\}\}"),
    re.compile(r"<[A-Z][A-Z0-9_]{2,}>"),
)

_NewTopic = namedtuple("_NewTopic", "slug name path text")


def _strip_topic_suffix(filename: str) -> str:
    if filename.endswith(_TOPIC_SUFFIX):
        return filename[: -len(_TOPIC_SUFFIX)]
    return filename


def _normalize(text: str) -> str:
    """Whitespace/EOL-insensitive form for baseline comparison."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


def _iter_agent_dirs() -> list[Path] | None:
    """Return sorted agent dirs, or ``None`` when the workspace is absent."""
    root = Path(_AGENTS_ROOT)
    if not root.is_dir():
        return None
    return sorted(
        d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")
    )


def _enumerate_new_topics(runner) -> list[_NewTopic] | None:
    """New/custom topics = ``topics/*.mcs.yml`` differing from the OOTB baseline.

    Returns ``None`` when there is no agent workspace at all (distinct from an
    empty list, which means the workspace exists but holds no custom topics).
    """
    agent_dirs = _iter_agent_dirs()
    if agent_dirs is None:
        return None

    items: list[_NewTopic] = []
    for d in agent_dirs:
        topics_dir = d / _TOPICS_SUBDIR
        if not topics_dir.is_dir():
            continue
        baseline_topics = d / _BASELINE_SUBDIR / _TOPICS_SUBDIR
        for tf in sorted(topics_dir.glob(_TOPIC_GLOB)):
            try:
                text = tf.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            baseline_file = baseline_topics / tf.name
            if baseline_file.is_file():
                try:
                    baseline_text = baseline_file.read_text(
                        encoding="utf-8", errors="replace"
                    )
                except OSError:
                    baseline_text = None
                if baseline_text is not None and _normalize(baseline_text) == _normalize(text):
                    # Unchanged OOTB topic — not a skill-6 custom topic.
                    continue
            items.append(
                _NewTopic(
                    slug=d.name, name=_strip_topic_suffix(tf.name), path=tf, text=text
                )
            )
    return items


def _no_workspace_result(checkpoint_id: str, description: str) -> CheckResult:
    return CheckResult(roles=_MAKER_ROLES,
        checkpoint_id=checkpoint_id, category=_CATEGORY,
        priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
        description=description,
        result=f"No agent workspace found at {_AGENTS_ROOT}/.",
        remediation=(
            "Extract the agent locally (fetch_and_setup) so new topics can be "
            f"inspected under {_AGENTS_ROOT}/*/topics/."
        ),
        doc_link=_DOC_TOPICS,
    )


def _no_new_topics_result(checkpoint_id: str, description: str) -> CheckResult:
    return CheckResult(roles=_MAKER_ROLES,
        checkpoint_id=checkpoint_id, category=_CATEGORY,
        priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
        description=description,
        result=(
            f"No custom topics found under {_AGENTS_ROOT}/*/topics/ — nothing "
            "authored beyond the OOTB baseline yet, so there is nothing to "
            "verify."
        ),
        remediation=(
            "Create a new Workday topic with the create-new-topic skill; this "
            "checkpoint then emits one row per custom topic."
        ),
        doc_link=_DOC_TOPICS,
    )


def _evaluate_trigger(text: str, name: str) -> tuple[bool, str, str]:
    """Return ``(ok, result, remediation)`` for TOPIC-TRIGGER-* on one topic."""
    if not _ADAPTIVE_DIALOG_RE.search(text):
        return (
            False,
            (
                f"'{name}' is not a well-formed topic definition — missing the "
                "top-level 'kind: AdaptiveDialog'."
            ),
            (
                "Author the topic as a Copilot Studio AdaptiveDialog (start "
                "'kind: AdaptiveDialog') using the create-new-topic skill, "
                "mirroring an existing agent topic."
            ),
        )

    has_intent = _INTENT_TRIGGER in text
    has_other_trigger = any(k in text for k in _OTHER_TRIGGER_KINDS)
    has_begin_dialog = "beginDialog" in text

    if not (has_intent or has_other_trigger or has_begin_dialog):
        return (
            False,
            (
                f"'{name}' has no trigger — no 'beginDialog' with an "
                "'OnRecognizedIntent' (or other trigger kind) was found."
            ),
            (
                "Add a 'beginDialog' with a trigger (e.g. 'OnRecognizedIntent' "
                "for a user-facing topic, or 'OnRedirect' for a system topic) "
                "so Copilot Studio can route to the topic."
            ),
        )

    if has_intent:
        has_phrases = bool(_MODEL_DESCRIPTION_RE.search(text)) or bool(
            _TRIGGER_QUERIES_RE.search(text)
        )
        if not has_phrases:
            return (
                False,
                (
                    f"'{name}' is intent-routed (OnRecognizedIntent) but has no "
                    "trigger phrases — no 'modelDescription' content or "
                    "'triggerQueries' was found."
                ),
                (
                    "Add a 'modelDescription' with trigger phrases (what the "
                    "topic does, plus valid and invalid trigger examples), or a "
                    "'triggerQueries' list, so the LLM can recognise the topic."
                ),
            )
        return (
            True,
            (
                f"'{name}' is a valid AdaptiveDialog with an intent trigger and "
                "trigger phrases (modelDescription / triggerQueries)."
            ),
            "",
        )

    return (
        True,
        (
            f"'{name}' is a valid AdaptiveDialog with a "
            "trigger (beginDialog)."
        ),
        "",
    )


def _find_placeholders(text: str) -> list[str]:
    """Distinct unresolved placeholder tokens, in first-seen order."""
    found: list[str] = []
    for rx in _PLACEHOLDER_RES:
        for m in rx.finditer(text):
            token = m.group(0)
            if token not in found:
                found.append(token)
    return found


def _evaluate_integration(text: str, name: str) -> tuple[bool, str, str]:
    """Return ``(ok, result, remediation)`` for TOPIC-INTEGRATION-* on one topic."""
    has_wiring = any(marker in text for marker in _WIRING_MARKERS)
    placeholders = _find_placeholders(text)

    if not has_wiring:
        return (
            True,
            (
                f"'{name}' has no external integration wiring (no BeginDialog / "
                "InvokeFlowAction / ScenarioName / HttpRequest) — there are no "
                "tenant reference IDs to resolve."
            ),
            "",
        )

    if placeholders:
        shown = ", ".join(placeholders[:8])
        if len(placeholders) > 8:
            shown += ", …"
        return (
            False,
            (
                f"'{name}' still has unresolved integration placeholders: "
                f"{shown}. Tenant reference IDs have not been wired."
            ),
            (
                "Replace the placeholder tokens above with the real tenant "
                "values (e.g. the Workday tenant name and the Time Off Type ID "
                "from the Workday 'Time Off Types' report), then push. See the "
                "Workday extensibility guide."
            ),
        )

    return (
        True,
        (
            f"'{name}' integration wiring resolves — no unresolved "
            "'{{PLACEHOLDER}}' or '<UPPERCASE>' tenant reference-ID tokens "
            "remain. Confirm the wired tenant reference-ID values are correct "
            "with a Workday SME (the kit verifies the placeholders were "
            "resolved but cannot validate each ID against the Workday instance)."
        ),
        "",
    )


def _check_topic_triggers(runner) -> list[CheckResult]:
    items = _enumerate_new_topics(runner)
    if items is None:
        return [_no_workspace_result("TOPIC-TRIGGER-001", _TRIGGER_DESC)]
    if not items:
        return [_no_new_topics_result("TOPIC-TRIGGER-001", _TRIGGER_DESC)]

    results: list[CheckResult] = []
    for i, topic in enumerate(items):
        cid = f"TOPIC-TRIGGER-{i + 1:03d}"
        ok, result, remediation = _evaluate_trigger(topic.text, topic.name)
        results.append(CheckResult(roles=_MAKER_ROLES,
            checkpoint_id=cid, category=_CATEGORY,
            priority=Priority.HIGH.value,
            status=Status.PASSED.value if ok else Status.FAILED.value,
            description=f"{_TRIGGER_DESC}: {topic.slug}/{topic.name}",
            result=result,
            remediation=remediation,
            doc_link=_DOC_TOPICS,
        ))
    return results


def _check_topic_integration(runner) -> list[CheckResult]:
    items = _enumerate_new_topics(runner)
    if items is None:
        return [_no_workspace_result("TOPIC-INTEGRATION-001", _INTEGRATION_DESC)]
    if not items:
        return [_no_new_topics_result("TOPIC-INTEGRATION-001", _INTEGRATION_DESC)]

    results: list[CheckResult] = []
    for i, topic in enumerate(items):
        cid = f"TOPIC-INTEGRATION-{i + 1:03d}"
        ok, result, remediation = _evaluate_integration(topic.text, topic.name)
        results.append(CheckResult(roles=_MAKER_ROLES,
            checkpoint_id=cid, category=_CATEGORY,
            priority=Priority.HIGH.value,
            status=Status.PASSED.value if ok else Status.FAILED.value,
            description=f"{_INTEGRATION_DESC}: {topic.slug}/{topic.name}",
            result=result,
            remediation=remediation,
            doc_link=_DOC_TOPICS,
        ))
    return results


def run_topic_checks(runner) -> list[CheckResult]:
    """Emit the two skill-6 new-topic checkpoint families.

    Each family emitter is invoked behind a guard so a single failure degrades
    to a WARNING for that family instead of aborting the remaining checks.
    """
    emitters = (
        (_check_topic_triggers, "TOPIC-TRIGGER", _TRIGGER_DESC),
        (_check_topic_integration, "TOPIC-INTEGRATION", _INTEGRATION_DESC),
    )

    results: list[CheckResult] = []
    for fn, family, description in emitters:
        try:
            results.extend(fn(runner))
        except Exception as e:  # noqa: BLE001 — one emitter must not abort the rest
            results.append(CheckResult(roles=_MAKER_ROLES,
                checkpoint_id=f"{family}-001", category=_CATEGORY,
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description=description,
                result=f"Unable to run {family}-*: {type(e).__name__}: {e}",
                remediation=(
                    "Re-run FlightCheck; if this persists, report the checkpoint "
                    f"family ({family}-*) and the error above."
                ),
            ))
    return results
