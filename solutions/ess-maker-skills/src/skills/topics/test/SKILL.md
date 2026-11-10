# Debug and fix a topic

Debug and fix the selected topic toward the latest authoring request within the authorized scope, checking observed runtime behavior after changes.

Read [experience-contract.md](../experience-contract.md) for the scoped runtime correctness goal, testing offers, complete readiness message/control, `{topic_test_results}` outcome copy and pause/stop/resume instructions. Read [native-topic-testing.md](../../../reference/ess-docs/operations/native-topic-testing.md) before invoking the bounded inspection, browser preparation, activation, capture or observation operations. The session owns test selection, interpretation, fixes, recovery and completion; a one-turn capture is not a one-message testing policy.

Read [native-topic-debugging.md](../../../reference/ess-docs/operations/native-topic-debugging.md) for the complete debugging procedure: choose applicable failure-first probes, confirm actual reply evidence, check intent, localize through backend run evidence, authoring diagnostics or temporary values, correct the authorized source and retest. Use its post-save conversation-freshness procedure before interpreting changed behavior. Keep the loop in the session, not a generated batch driver.

## Readiness and selection

Require canonical setup schema version `4`, with the entry matching `.local/config.json`'s `activeAgent` workspace slug marked `connect_ready: true`. If setup or the selected Dev identity is unavailable, report the prerequisite and pause. Do not borrow another workspace's authentication or change global profiles.

Carry forward the selected topic from the current authoring or testing request. Do not ask the maker to select it again. Resolve any unknown component identity through the native list operation, then inspect the selected component freshly. A missing local YAML file does not establish remote absence. Confirm genuinely ambiguous identity or changed saved content with the maker.

Establish intended behavior from the latest authoring request and context, with matching eval intent as a read-only guardrail. Use the fresh native topic as current implementation evidence. General inspection supports ordinary saved dialogs; optional exact-response compatibility is not admission to all testing. Do not change intended behavior, narrow the topic or weaken expectations merely to obtain a passing check.

Carry the explicit test/fix objective and editable scope. An explicit test-only request remains test-only. When testing is already requested and only activation permission is missing, use the shared Activate {Topic title} for testing? question. For an inactive topic, use the reference's separate activation preview and authorized activation operation. Confirm authoritative Active state before sending; honor no-activation requests and report any unresolved prerequisite using `{topic_test_results}`. Creation itself stays inactive and updates preserve state. Never publish or change unrelated routing.

For a selected test-anyway continuation, or later authorized testing after Push topic anyway, carry the declined routing correction as an explicit exclusion. Push topic anyway authorizes only the topic save, not testing; obtain the later testing choice before entering this owner. Leave the declined instructions unchanged even if the conflict blocks topic execution; report the observed limitation rather than silently resolving it through the debugging loop. Do not repeat an already-authorized testing offer. Preserve the stated testing objective and existing editable scope; a test-anyway selection is not blanket debugging consent.

## Check matching eval intent

Find and read matching existing evaluation cases as read-only intent. Make a lightweight, best-effort check that observed behavior and proposed fixes preserve that intent, using simple checks or semantic judgment over captures as useful. Preserve their inputs, expected behavior, thresholds and case references. Exercise useful prompts, paraphrases and conversational branches according to intended behavior and available interactions; do not require a full eval run or case-by-case coverage report. Do not flatten multi-turn/backend cases, replace expectations with an easier substring check, or silently edit cases.

This procedure is not a graded evaluation-set execution. Route separately requested case creation or editing through the existing evaluation skill, with its own scope and approvals.

Build a useful probe set from intended behavior, actual inputs/backend contracts and matching eval intent, including safe applicable negative cases as well as a happy path. Explain the scope so the maker can adjust it, without inserting another routine approval gate. Exercise informative failure cases first when safe and within the approved resources. Do not invent a mandatory case matrix or force real outages, permission changes or malformed writes.

## Prepare the browser separately

Prepare or reuse the test browser and open the selected agent. Resolve the trusted selected-agent Studio URL and numeric-loopback connection internally from the selected context and preparation result. Use the reference's bounded browser preparation operation when a new browser is needed. Browser preparation ends before human sign-in, Test-pane preparation or any conversation Send. SDK sign-in does not establish browser identity.

Keep the browser and its profile available for follow-ups, including after a completed check or pause/stop. Leave normal closure to the maker, not routine test cleanup. Prepare a fresh window when the existing one is unavailable or unusable; reconcile an uncertain Send before replacement and retain the prior browser identities and evidence. Follow the reference for requested closure and exact-profile cleanup.

Present the full shared readiness message in normal chat, followed by its separate readiness-only control. The maker signs in with a test account if necessary and opens the Test chat pane with an empty, idle composer. Omit the sign-in paragraph when already signed in with a test account; reuse valid readiness. Keep the existing test-only or test-and-fix scope.

Apply Not ready, keep paused or Stop without sending immediately using the shared exact acknowledgement, reporting any completed work separately using `{topic_test_results}`. Resume within the existing objective and permissions, resolving only changed or missing prerequisites. Pause until the maker confirms the correct Test pane is open with an empty, idle composer. Do not inspect credentials, unrelated tabs or shared authentication stores. Browser preparation is not recovery from an uncertain Send: do not automatically launch, navigate, reset, reload or resend.

## Execute and interpret tests

Count one testing pass for the selected probes against the intended saved behavior. Immediately before the first authorized `capture` or `run` attempt of each pass, invoke:

```powershell
python scripts/emit_capability.py topic_test
```

This best-effort usage event measures an attempted pass, not successful replies. Inspection, browser preparation, activation and readiness-only pauses add no count. Additional prompts, `observe` calls and resuming the same paused pass add no count. Each post-fix retest starts a new pass and emits once before its first attempt: three initial probes followed by a fix and three retest probes count as two passes. Keep pass continuity in session context; do not add persistent telemetry state or replay an emission whose delivery is unknown.

Use the reference's general `capture` operation for approved test messages, choosing a unique evidence directory for each turn. The operation records native state and the page/turn boundary before Send and returns correlated reply/card, completion and readback facts. `graded: false` and `outcome: captured` mean observed capture, not correctness or backend success. Interpret actual observations against intended behavior and retain evidence.

Use the returned `signal` and `errorShaped` as advisory capture facts. An `ok` signal can describe a real error reply; consent, empty or partial captures cannot establish that the intended backend or topic logic ran. Check all captured bubbles against intent, using existing literal checks or semantic reasoning as appropriate. Do not treat a classifier or a vacuous absence check as a correctness verdict.

After a known completed turn, continue the authorized scenarios or conversation with further bounded captures as needed. Cards are evidence, not automatic test failure; when a required interaction cannot be performed by the available surface, report that specific remaining gap or collaborate with the maker. Do not claim an unsupported interactive-card submission, backend fault injection or exact-topic invocation trace.

Use the optional `run` exact-response check only when its saved-trigger/literal-response contract matches the intended assertion. It does not replace broader testing or authorize weakening a different expectation. Classifier hints are advisory; partial, uncorrelated or unavailable evidence cannot establish a passing behavior. Independently verify relevant effects when the tested behavior depends on them.

If a send times out or has an uncertain outcome, retain the original prompt, intended expectation, boundary and evidence. Use the independent `observe` operation against that original capture/run without sending again. Keep later observations separate and distinguish them from the original result. Do not replay a failed or uncertain send by choosing a new directory. A planned retest after a verified fix is distinct from blindly replaying an uncertain attempt.

If local evidence output fails after capture or readback, retain the returned known facts and report the output failure separately. Do not treat it as permission to resend.

## Diagnose and report within scope

Inspect useful service-returned component diagnostics when explaining an authoring failure. Persistence is not proof of diagnostic-free authoring or runtime correctness, and component diagnostics do not establish universal checker coverage.

When a reply or card does not reveal the state needed to explain a branch, calculation or binding, use [temporary value observation](../../../reference/ess-docs/operations/native-topic-testing.md#observe-topic-values-temporarily). Choose the relevant non-sensitive values and action boundary, observe them through the ordinary capture path, then remove only the owned diagnostic message. An absent diagnostic is not proof of a blank value or an unreached topic. Preserve legitimate corrections, concurrency checks and cleanup uncertainty. Test-only scope does not authorize instrumentation.

Localize a backend-backed mismatch through a correlated run only when its separate target, access and read-only inspection scope are established. Reuse the workflow inspection owner; flow, connection and template-configuration changes remain outside ADK. For an unexplained authoring error, follow native authoring validation in the debugging reference using retained service responses and fresh component diagnostics. Preserve unavailable validation evidence as a gap, not a clean result.

When an observed issue needs a fix, delegate to the normal topic or instruction owner with the selected target, intended behavior, issue evidence, debugging objective and approved editable scope. Necessary in-scope fixes, pushes and retests reuse that authorization; do not insert independent per-fix approval gates. Preserve concurrency safeguards. New scope, changed intended behavior or additional consequential actions require approval. Test-only requests report issues without editing.

Resume after the owner returns its actual save/readback outcome. Reinspect changed saved content, confirm its state and retest affected behavior; make the best-effort matching-eval intent check. Continue useful authorized investigation and corrections rather than handing back an ordinary fixable mismatch. Stop blindly repeating a failing approach: inspect new evidence and resolve the actual cause within scope.

When conflicting authoring goals, edit constraints or eval intent prevent progress, explain the conflict and recommend a concrete reconciliation. When tools, access or available evidence prevent further safe progress, explain the limitation and offer practical assistance, including manual testing guidance where appropriate. Preserve completed work and uncertainty; do not imply that unavailable testing passed.

Report in normal chat using the shared `{topic_test_results}` goal/outcome copy, with a recommendation only when a change or assistance is needed. Describe observed behavior and its limits, not the mechanics of the debugging loop. Populate its Evidence line from the selected operations' returned `evidenceDirectory` and existing result/report files, adding other relevant artifacts when available. Missing screenshots do not prevent linking saved results; omit the line only when no relevant evidence exists. Ask separately only for genuine human dependencies or a new scope decision; the report itself requires no routine acknowledgement. Disclose material evidence failures or drift without discarding known facts. Do not report a universal pass from response equality, a save/readback or a completed DOM capture.
