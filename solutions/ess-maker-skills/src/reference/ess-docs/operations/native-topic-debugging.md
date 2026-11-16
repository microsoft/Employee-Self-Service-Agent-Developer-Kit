# Debug topic behavior

Use this procedure with the topic-testing owner, the applicable [bounded operations](native-topic-testing.md), the [shared foundation](../../../skills/topics/experience-contract.md) and [Testing experience](../../../skills/topics/testing-experience.md). The session selects probes, interprets evidence, chooses the fault surface and coordinates authorized corrections. Do not generate a second workflow engine or batch runner.

## Contents

- [Build the probe set](#build-the-probe-set)
- [Capture and confirm a real reply](#capture-and-confirm-a-real-reply)
- [Check behavior against intent](#check-behavior-against-intent)
- [Establish post-save conversation freshness](#establish-post-save-conversation-freshness)
- [Localize a backend-backed mismatch](#localize-a-backend-backed-mismatch)
- [Inspect authoring validation](#inspect-authoring-validation)
- [Observe internal state and narrow the boundary](#observe-internal-state-and-narrow-the-boundary)
- [Correct, retest and clean up](#correct-retest-and-clean-up)

Read the applicable section before its phase. Load localization or instrumentation guidance only when needed, including cleanup requirements before any temporary edit.

## Build the probe set

Read the latest authoring goal, current topic and relevant installed contracts. Existing evaluation cases are read-only intent, not expectations to weaken until a test passes. Use real case inputs where useful; add exploratory prompts for uncovered behavior. Missing cases do not prevent useful testing. Route separately requested case authoring through its existing owner.

Include a normal request and applicable safe negative cases. Examples include a known synthetic missing record, a malformed input that should be validated without a write, an out-of-range value, an empty required input and an already-existing consent or backend error. Derive cases from the actual topic and intended behavior rather than requiring every example for every topic. Do not revoke access, disconnect a backend, send destructive malformed requests or manufacture an outage without separate authorization and a supported operation.

Describe the proposed testing scope in normal chat so the maker can adjust it. Reuse valid testing consent. Start with informative applicable failure cases when safe, then the happy path and useful paraphrases or conversational branches. Preserve dependent multi-turn context; do not reset between steps of one scenario.

## Capture and confirm a real reply

Prepare the browser and obtain readiness through Testing experience. Use a unique bounded `capture` for each approved turn. Read all bubbles, cards, timeout facts, turn identities and AgentBuilder readback.

Use the returned `signal` as an advisory:

- `ok`: text was captured, not proof of correctness. A genuine error reply can be `ok`; inspect `errorShaped` and the actual content.
- `consent_gate`: inspect the observed connection request. Do not assume the intended backend ran or diagnose its data from this reply. Connection authorization is a human or separately supported action.
- `timeout`: the observation is incomplete. Use `observe` on the original attempt without another Send.
- `empty`: text evidence is absent; inspect card presence, correlation and runtime readiness. Do not conclude that a topic was absent or the backend returned no records.

These are text-level hints, not an exact-topic invocation trace or a guarantee of tool execution. A card-only result may need human interaction that the capture driver cannot perform. Explain the specific gap rather than inventing a submission or a passing result.

Do not blindly re-drive on a non-`ok` signal. Preserve the original attempt and use independent observation first when submission or completion is uncertain. After a known completed turn, remediation and a deliberately authorized retest can proceed.

## Check behavior against intent

Compare the observations with intended behavior, including relevant failure handling. Existing deterministic checks are available through `reply_signal.py`:

```powershell
python scripts\reply_signal.py "<captured real reply>" --expect "<required text>" --reject "<forbidden text>"
```

Apply these only to a correlated, completed reply appropriate for a text assertion. No supplied expectations is not a correctness check. Do not assert an absent error string against a consent gate, timeout or empty capture. A substring match is a narrow signal; use best-effort semantic reasoning over the actual capture when it cannot establish the intended meaning. Neither is a graded evaluation run.

Rendered card text can omit dropdown choices and other hidden state. Do not infer an empty choice table from missing DOM option text. Observe a safe count, branch marker or projected field using the owned temporary-value technique when authorized.

## Establish post-save conversation freshness

After saving a correction or diagnostic, inspect the updated saved component. A save/readback proves persistence, not execution of that version.

Before retesting an affected scenario after a save:

1. Retain the prior turn's result and correlation evidence. If a Send is uncertain, observe that attempt first; do not reset, reload, navigate or open another browser to hide its uncertainty.
2. Use [Start a new Test conversation](native-topic-testing.md#start-a-new-test-conversation) with the existing browser's `cdp` and `url`. It clicks **New chat** in the selected Test pane. Keep timing and recovery in the session; ask the maker only when a genuine human action is needed. Clearing visible bubbles, reloading a page and obtaining an empty transcript are not independently proof of a fresh runtime conversation.
3. Keep the selected agent and test identity, confirm the pane is idle and the composer empty, and reuse still-valid readiness. Do not re-prompt for known connection facts or sign-in.
4. Capture the first turn of the fresh scenario with the additional empty-boundary precondition:

   ```powershell
   python scripts\native_topic_test.py capture `
     --inspection "<post-save inspection file>" `
     --prompt "<approved probe>" `
     --cdp "<confirmed numeric-loopback endpoint>" `
     --url "<confirmed full Studio URL>" `
     --output ".local/topic-tests/<unique attempt>" `
     --require-empty-conversation
   ```

Replay any necessary lead-in steps and preserve context between the scenario's turns. Use further bounded captures without requiring an empty transcript or resetting between those turns.

The flag checks the prepared boundary before Send. A nonempty or unknown boundary blocks without resetting or falling back to the existing conversation. It does not create a conversation or prove server-side freshness. Retain the actual new-conversation evidence and compare the captured behavior with the saved change. Allow for synthesized wording; a normal answer or a shared message prefix alone does not establish the exact topic or version used.

If a new conversation cannot be established or the diagnostic remains invisible, report that limitation. Do not claim freshness or a variable value merely because the flag or component inspection succeeded. Preserve the unresolved cause.

## Localize a backend-backed mismatch

Distinguish a backend/connector failure from a later topic binding or branch failure. When the authorized scope includes read-only run inspection, resolve the exact environment and installed flow plus a relevant run identity or correlation evidence. Selected Dev setup does not establish Flow API access.

Follow [workflow run inspection](../../../skills/workflows/test/SKILL.md) and [cascade interpretation](flow-run-inspection.md). Reuse the existing read-only inspector only with its independent authentication prerequisites. Do not borrow authentication caches, substitute the AgentBuilder token audience, enable retired Dataverse setup or claim automatic Flow access.

A latest run is not necessarily the run caused by this probe, especially under concurrency. Retain that uncertainty unless identity and timing establish the connection. Inspect the first relevant failed action, status code, containing scope and subsequent skipped or catch-handler actions. A successful error handler or catch-all response does not itself establish that the original operation succeeded.

If evidence localizes a required correction to a flow, connector or template configuration, direct it to its supported external owner. Do not fix topic text to disguise an uncorrected backend failure. Reinspect and retest within the approved scope after an actual external correction. If evidence instead points to a topic calculation, binding or branch, investigate that topic.

## Inspect authoring validation

For an unexplained authoring error, inspect the ordinary topic create/update operation's retained service response and the selected component's nested diagnostics from fresh AgentBuilder readback. Use the ordinary topic read operation when current component evidence is needed; do not save unchanged content just to obtain diagnostics.

Retain the actual error code, message, object path and reference or component identity when supplied. Resolve component IDs through the selected workspace map and inspect the named expression, binding or card. Ordinary create/update verifies saved content and checks blocking diagnostics; keep the full returned evidence rather than treating HTTP acceptance, YAML conversion or the diagnostic summary alone as validation of intended behavior.

Distinguish no reported diagnostics from unavailable validation evidence. Neither an empty diagnostic list nor a successful save establishes universal authoring coverage, correct runtime values or topic reachability. If the returned evidence cannot explain the failure, retain that gap and continue useful authorized diagnosis through correlated captures, backend evidence or owned temporary values. Do not infer a specific authoring failure from a generic reply alone.

Correct the evidenced topic expression or card through ordinary authoring, confirm saved state and validation evidence, then establish a fresh conversation before retesting the affected scenario. A validation failure after save does not itself mean the write was rejected; inspect actual saved state before another write.

## Observe internal state and narrow the boundary

Use [owned temporary value observation](native-topic-testing.md#observe-topic-values-temporarily) when replies, run history or diagnostics cannot explain a branch or value. Bind each temporary `SendActivity` to the exact selected topic, action boundary, unique action ID and expected owned content before saving. Choose only non-sensitive synthetic or explicitly authorized values.

Place the message after the relevant assignment and before the suspected consumer. Follow the temporary-value reference's message-wording guidance and use valid text interpolation, for example `Ready for review: total={Topic.Total}`. The prefix is optional, not a capture or cleanup requirement. Save with ordinary target/concurrency guards, establish post-save conversation freshness and capture all bubbles.

Read values actually present in the correlated reply, not the source expression or an absent bubble. If values do not appear, inspect message wording, freshness and diagnostics, then move the owned message one action boundary earlier when useful. Place it before a suspected `Split`, `First`, parse, card or expression consumer; keep branch-local placement explicit. A preceding expression failure can prevent later instrumentation, but message absence alone does not prove that cause or exact-topic reachability.

Remove or reconcile the old owned node before moving it and update the cleanup record before another possible save. Compare observed values and message content across deliberate probes. Stop repeating the same placement without new evidence.

## Correct, retest and clean up

Return the actual mismatch and supporting evidence to the ordinary topic or instruction owner, carrying the latest goal, selected target and approved debugging/edit scope. Necessary in-scope corrections and retests reuse that authorization. Expanded scope, changed intended behavior or additional consequential actions require approval. Test-only requests do not authorize instrumentation or fixes.

After verified saved corrections, reinspect and retest the affected scenario and useful intent guardrails. Continue until the goal is satisfied or a concrete constraint, missing capability or evidence gap prevents safe progress. Preserve intended behavior and evaluation expectations rather than optimizing for a superficial pass.

Remove only owned diagnostic nodes using exact IDs and parsed-content guards against the latest saved content. Preserve legitimate fixes and other edits; do not restore an entire pre-debug snapshot. Verify removal and local draft/baseline consistency, and retest normal behavior without instrumentation when useful. On pause, stop or interruption, attempt safe owned cleanup within existing permission; honor an explicit stop that forbids writes and disclose any remaining instrumentation or cleanup uncertainty.

Retain original errors and known completed work through recovery. Never publish, change competitors or blindly replay an uncertain write or Send. Report through the shared goal/outcome copy, with actual evidence links afterward and a recommendation only when assistance or a change is needed. The report itself needs no routine acknowledgement.
