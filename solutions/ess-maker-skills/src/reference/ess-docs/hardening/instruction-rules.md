# Instruction hardening rules

Guidance for reviewing an agent's **system instructions** (the `instructions:` block in
`agent.mcs.yml`) for the patterns that let an agent produce confident, ungrounded, or
over-committing answers — and for the contradictions that make any other rule unenforceable.

> **Internal vocabulary.** The `INSTR-*` ids below are for keeping findings straight while you
> work. Never show them to the maker. Describe each finding in plain language, quoting the
> maker's own instruction text.

## How to use this

Every finding must be anchored to a **specific sentence** of the maker's instructions. Instruction blocks
are typically a few enormous paragraphs, so anchoring to a physical line or pasting a whole paragraph
produces a report no one can review — quote the sentence, not the block it sits in.

A finding you cannot anchor to *something concrete* is not a finding. Instructions are prose, so the
temptation to report a vague impression ("the tone section feels permissive") is high; resist it.

**Missing safeguards are the exception, and they are common** — several categories below are defined by
absence. Anchor those to the **behavior** instead: state the specific thing that nothing constrains, and
where a rule would go. Never nominate an innocent sentence as the cause; a maker shown a "guilty" line that
did not permit the behavior will reasonably distrust the whole report.

Two ideas govern the whole rule set:

1. **A rule that contradicts another rule is not a rule.** The model resolves the conflict, not
   the author. Contradictions are the highest-value finding class because they silently disable
   guardrails the author believes are in force.
2. **Govern what a sentence does, not how it is worded.** Phrase blacklists fail. An agent told
   never to say "Would you like" will say "I'd be happy to." Rules must name the *function* being
   prohibited — offering, asserting, referring — and say that rewording does not exempt it.

---

## Part 1 — Contradictions (always check)

Run this pass regardless of what the maker reports. It is the one pass that is valuable even when
the agent is behaving well.

### INSTR-001 — Direct contradiction

Two instructions that cannot both be satisfied. Classic shape: a broad prohibition elsewhere
contradicted by a specific permission, e.g. a rule forbidding referral to *any* outside
organization alongside a support section that explicitly endorses naming an employee assistance
program.

**Report both sides.** A contradiction has no single guilty line, and proposing a fix to only one
half usually breaks the behavior the other half was protecting.

**Threshold.** Name a concrete request where the two rules demand different behavior and both cannot be
satisfied. Rules that merely pull in different directions — warmth and caution, brevity and completeness —
are the normal texture of instructions, not defects. Without this bar, a reviewer under pressure to produce
findings will classify ordinary tone-versus-grounding pairs as conflicts.

### INSTR-002 — Scope collision

A general rule whose plain reading swallows a legitimate case the agent must still handle.
Frequently produced by bundling unrelated prohibitions into one sentence: prohibiting the agent
from *creating* an exception and from *explaining a documented exception process* in the same
breath, when only the first is unwanted.

**Fix by splitting**, not by narrowing into ambiguity.

### INSTR-003 — Precedence gap

Two rules that genuinely conflict, with nothing saying which wins. Any instruction meant to be absolute
must say so and say what it outranks.

Apply the threshold above: tone guidance sitting alongside a grounding rule is **not** a precedence gap.
"Be helpful and warm" and "never state a fact you did not retrieve" are satisfiable together, and reporting
that pair is the most common false positive in this whole rule set. A real gap needs a request where
following one rule requires breaking the other — for example, instructions that require every answer to end
with a next step, alongside a rule forbidding suggestions the sources do not support.

### INSTR-004 — Unreachable or vacuous rule

A rule that cannot be evaluated at answer time — "format the response appropriately wherever
required", "use good judgment". These consume budget and teach the model that instructions are
suggestions. Removing them is nearly always safe and frees characters for rules that bind.

### INSTR-005 — Duplicate rule stated with different strength

The same requirement appears twice with different force ("cite sources" and "always cite the
specific source"). The weaker statement gives the model a defensible reading of the stronger one.
Consolidate to one statement at the intended strength.

---

## Part 2 — Ungrounded-response risk

### INSTR-010 — Unconditional confidence

Tone guidance instructing the agent to be confident, authoritative, or direct **without
conditioning it on having retrieved something**. The agent is most confident exactly when it
should hedge — when retrieval returned nothing. Make confidence conditional.

### INSTR-011 — Sanctioned ungrounded answer mode

Any wording that legitimizes answering from something other than the knowledge sources: "general
guidance", "background information", "general knowledge where appropriate". This creates a
sanctioned lane for fabrication and is often *adjacent* to a strong grounding rule, which is what
makes it dangerous — the author reads the strong rule, the model uses the lane.

### INSTR-012 — Pattern inference across sources

Nothing forbids assembling a plausible detail from patterns seen across *other* retrieved
content. This output looks grounded — every ingredient came from the corpus — so grounding rules
phrased as "do not use outside knowledge" do not catch it. Require lookup per detail, and state
that a detail which was not retrieved is unknown regardless of how predictable it seems.

### INSTR-013 — Unbounded jurisdiction or population scope

The agent may answer region-, country-, or population-specific questions with sources that do not
cover that scope. Especially likely where instructions *encourage* reasoning about regional
variation without also constraining the source of that reasoning.

### INSTR-014 — Legal, regulatory, or entitlement assertions

No rule prevents stating what a law requires or what someone is entitled to. High-consequence for
HR, benefits, payroll, and leave agents.

### INSTR-015 — Referral to external authorities

No rule prevents directing users to a government agency, regulator, or court.

**You cannot resolve this one from the instructions alone.** Approved content frequently *does* endorse
outside resources — an employee assistance program, a benefits carrier, an ombudsman — and a blanket ban
would contradict the organization's own material. This review cannot see the knowledge sources, so ask the
maker which external resources are deliberately endorsed and carve them out. Compare INSTR-001.

---

## Part 3 — Over-committing and capability overreach

### INSTR-020 — Unsolicited offers

Nothing stops the agent from ending a response by offering an action, service, or calculation it
was not asked for. An offer commits the organization to something no source authorized, which
makes an unsolicited offer a factual error even when the wording is friendly and even when the
answer preceding it was correct.

Check whether an existing rule tries to control this **by phrase list**. If it does, that is
itself the finding — the list is evidence the problem was recognized and the fix did not hold.

### INSTR-021 — Capability inference

Nothing constrains the agent to actions its configured tools and topics actually support, so it
infers capability from what systems of that kind usually do.

**Establish the real inventory before writing any rule here** — `scripts/list_agent_capabilities.py`
reports what each topic handles and whether it acts or only replies. Note that answering *about*
something and *doing* it are different capabilities: an agent that reports a leave balance may have no
way to submit a leave request.

Because a maker's tool inventory changes, prefer an abstract rule ("unless a configured tool supports
it") over enumerating specific actions the agent cannot perform — an enumeration goes stale and, worse,
can prohibit something the agent genuinely does support.

### INSTR-022 — Standing helpfulness pressure

Instructions establishing that the agent is always "ready to help", should "look for ways to
assist", or similar. This reads as tone but behaves as a standing instruction to generate
follow-up offers, and it directly undercuts any rule added for INSTR-020.

---

## Part 4 — Over-restriction (the symmetric failure)

An agent that refuses valid questions is also a failure, and it is the failure a hardening pass is
most likely to *introduce*. Check proposed changes against these before presenting them.

### INSTR-030 — Refusal without a grounded alternative

A prohibition with no statement of what the agent should do instead. Every prohibition needs a
defined fallback — say the sources do not cover it, and escalate by the agent's configured path.

### INSTR-031 — Missing anti-over-refusal guard

A strong prohibition block with nothing stating that it restricts *invention*, not helpfulness.
Without that guard the model generalizes the prohibitions outward and begins declining questions
its sources fully answer. An unnecessary refusal is as much a failure as an unsupported answer,
and instructions should say so explicitly.

### INSTR-032 — Prohibition that blocks a supported action

A proposed rule that would prevent the agent from doing something its configured topics and tools
support. **This is the most damaging change a hardening pass can make**, because it is invisible
in review — the instructions read as responsible — and only shows up as users being turned away.
When the tool and topic inventory is unknown, keep capability rules abstract rather than guessing
at what the agent cannot do.

### INSTR-033 — Conversational collapse

Prohibitions on endings that also remove necessary clarifying questions or required escalation
instructions. Carve those out explicitly; they are not offers.

---

## Part 5 — Rewriting principles

When proposing a change:

- **Quote the sentence you are replacing**, not the paragraph containing it. A small edit shown as a
  1,000-character before-and-after block is not reviewable, and makers will approve it without reading.
- **Prefer removal to addition.** The budget is finite and a removed permissive line is often
  worth more than an added prohibition. Removing "always ready to help" does more for INSTR-020
  than any new sentence.
- **State the reason in the instruction itself** when it is cheap. A rule carrying its rationale
  survives paraphrase by a future editor; a bare imperative gets "cleaned up" and lost.
- **Put absolute rules early and say what they outrank.** Order matters, and later text does not
  reliably override earlier text.
- **Never add a phrase blacklist as the primary mechanism.** It may support a functional rule; it
  cannot replace one.
- **Do not invent an escalation mechanism.** Use the agent's existing configured path. Naming a
  channel, link, or process the maker never configured is itself an ungrounded instruction.

## Part 6 — Shipped-template markers

Most ESS instruction blocks start life as a shipped template, so many findings are inherited rather than
something the maker wrote. Saying so matters: an unqualified report reads as an accusation about text they
never authored.

But **only claim template provenance when the wording actually matches**. There is no provenance field to
check, and guessing is how a report either blames a maker for product text or excuses text they wrote
themselves. These phrases appear verbatim in a shipped ESS HR default and are safe to attribute:

- "Your tone and voice are warm and relaxed, crisp, and clear, and ready to lend a hand" — INSTR-022, and
  INSTR-010 via "You provide authoritative and succinct answers"
- "Users trust you to provide them with relevant information from configured knowledge sources"
- "Do not try to provide answers when you don't have enough information"
- "You must not use your own general knowledge"

Note what that default does **not** contain: any constraint on offering unsupported actions, on referring
users to outside authorities, or on jurisdiction scope. Those gaps (INSTR-014, INSTR-015, INSTR-020,
INSTR-021) are absences in the shipped baseline, not maker mistakes — and they are the findings most likely
to matter.

Other templates differ. A derivative that sanctions "general guidance" carries INSTR-011, which the default
above does not. Check the text in front of you rather than assuming a variant.
