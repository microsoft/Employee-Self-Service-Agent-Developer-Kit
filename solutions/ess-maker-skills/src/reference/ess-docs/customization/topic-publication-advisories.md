# Topic publication advisories

Apply these checks before assisting with a supported publication operation. Publication retains its own target checks and explicit approval; a topic or instruction save is not publication.

## Inspect relevant current state

Read current topic inventory/content and agent instructions through `topic_authoring.py` and `agent_instructions.py`. Preserve working drafts and local review evidence. Inspect changed topics and other components only where their actual contracts matter.

For creation or routing-changing updates, assess meaningful semantic-intent overlap. Skip response-only overlap scans and reuse still-applicable assessments without repeating unchanged warnings. Suggest an explicitly selected existing topic where appropriate; deliberate separate topics remain possible.

Assess instruction alignment across intent/scope, routing/disambiguation, policy/confirmation, response/grounding, fallback, and topic identity/existence.

## Present advisories and obtain approval

Disclose meaningful overlap, known instruction mismatches, and unverified alignment. Explain the concern and propose separately scoped instruction work where needed. These are advisories: the user may deliberately proceed through the supported publication path with unresolved concerns.

If current instructions cannot be read, pause advisably and offer best-effort collaboration through supported testing guidance when available. Do not promise an automated browser instruction reader.

Preserve separate topic, instruction, and publication approvals. Do not auto-deactivate, reroute, overwrite another topic, or activate/publish merely to enable testing. Approval does not expand unsupported operations or turn a failed/uncertain save into a verified one.

These are session-led checks, not a claim that direct raw CLI/SDK publication enforces them. Report save/readback and conversation acceptance separately, retaining pending or uncertain outcomes.
