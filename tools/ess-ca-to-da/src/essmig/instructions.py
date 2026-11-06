"""Reconcile agent instructions across the CA→DA gap with a language model.

Instructions are the one customization a structural three-way merge cannot carry.
The DA ships the *same* instructions the CA shipped, but rewritten for the DA
runtime, so the ``instructions`` string differs on every side:

* ``base``   — the instructions ESS shipped in the CA.
* ``ours``   — the customer's edited CA instructions (``base`` plus their changes).
* ``theirs`` — the instructions ESS ships in the DA today, reworded for the DA.

Because ``base`` ≠ ``theirs`` (ESS rewrote it) and ``base`` ≠ ``ours`` (the customer
edited it), a literal merge of the scalar can only ever report a conflict — which is
exactly why an edited-instructions migration used to carry nothing. What actually
needs to migrate is the customer's *intent*: the delta from the shipped CA text,
re-expressed in the DA's own voice. That is a language task, so this module hands
all three versions to a model and asks it to apply the customer's delta onto the DA
instructions while preserving the DA's wording, structure, and runtime references.
"""

from __future__ import annotations

from collections.abc import Callable

from essmig import llm

InstructionMerger = Callable[[str, str, str], str]
"""``(base, ours, theirs) -> merged`` — pluggable so the merge and tests can inject."""

_SYSTEM = (
    "You migrate a Microsoft Employee Self-Service agent's system instructions from "
    "an older Custom Engine Agent (CA) to the current Declarative Agent (DA). You are "
    "given three versions:\n"
    "  BASE — the instructions Microsoft shipped in the CA.\n"
    "  CUSTOMER — the customer's edited CA instructions (BASE plus their changes).\n"
    "  TARGET — the instructions Microsoft ships in the DA today, reworded for the DA "
    "runtime.\n\n"
    "Identify what CUSTOMER changed relative to BASE, and apply ONLY those changes "
    "onto TARGET. Preserve TARGET's wording, structure, headings, and any DA-specific "
    "variables or references (for example ${...} or Global.* / System.* tokens). Do "
    "not reintroduce CA-specific phrasing the DA deliberately dropped, do not invent "
    "new policy, and if a customer change is already reflected in TARGET, leave it. "
    "Output ONLY the final merged DA instructions as plain text — no preamble, no "
    "commentary, no code fences."
)


def reconcile_instructions(
    base: str,
    ours: str,
    theirs: str,
    *,
    complete: Callable[[str, str], str] = llm.complete,
) -> str:
    """Return the DA instructions with the customer's CA edits applied.

    Raises :class:`essmig.llm.LlmUnavailable` when the model cannot be reached; the
    caller decides whether to fall back to reporting a conflict.
    """
    user = (
        "BASE (CA as shipped by Microsoft):\n"
        f"{base}\n\n"
        "CUSTOMER (the customer's edited CA instructions):\n"
        f"{ours}\n\n"
        "TARGET (DA as shipped by Microsoft today):\n"
        f"{theirs}\n\n"
        "Return the merged DA instructions, applying the customer's changes onto TARGET."
    )
    return complete(_SYSTEM, user).strip()


def keep_target_instructions(base: str, ours: str, theirs: str) -> str:
    """An offline :data:`InstructionMerger` that keeps the DA's wording unchanged.

    Used by the assessment/dry-run path, which must stay fast and network-free: it
    predicts that an instruction edit *can* be migrated without actually calling the
    model.
    """
    return theirs


class InstructionReconciliationSkipped(RuntimeError):
    """Signals that instruction reconciliation was deliberately not performed.

    Distinct from :class:`essmig.llm.LlmUnavailable` (the model *could not* be
    reached): here the maker opted out with ``--keep-instructions``. Either way the
    caller keeps the DA's wording and leaves the edit as a conflict, but the reason —
    and therefore the message shown to the maker — differs.
    """


def skip_instruction_reconciliation(base: str, ours: str, theirs: str) -> str:
    """An offline :data:`InstructionMerger` for ``--keep-instructions``.

    Unlike :func:`keep_target_instructions` (a dry-run *prediction* that the edit can
    migrate), this is used in a real migration where the maker chose not to call the
    model. It must not masquerade as a successful merge: it raises
    :class:`InstructionReconciliationSkipped` so the edit is reported as a conflict
    for hand re-application, per DEV_DESIGN §5.3.
    """
    raise InstructionReconciliationSkipped(
        "instruction edits were kept as a conflict because --keep-instructions was "
        "set; re-apply them by hand, or re-run without --keep-instructions to let the "
        "model reconcile them onto the DA's wording."
    )
