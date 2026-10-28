# Test Topic Skill

Test one saved, active native topic in the selected Dev agent through an approved browser. Read [native-topic-testing.md](../../../reference/ess-docs/operations/native-topic-testing.md) before running any operation and follow its inspection, browser confirmation, single-send and later-observation procedure.

## Readiness and selection

Require canonical setup schema version `4`, with the entry matching `.local/config.json`'s `activeAgent` workspace slug marked `connect_ready: true`. If setup or the selected Dev identity is unavailable, report the prerequisite and pause. Do not borrow another workspace's authentication or change global profiles.

Carry forward the selected topic from the current authoring or testing request. Do not ask the maker to select it again. Resolve any unknown component identity through the native list operation, then inspect the selected component freshly. A missing local YAML file does not establish remote absence. Confirm genuinely ambiguous identity or changed saved content with the maker.

The supported dialog has a saved trigger phrase, one literal text `SendActivity` and `EndDialog`. Unsaved drafts, inactive topics, dynamic responses, branches, cards, backend calls and debug-oracle instrumentation are outside this test boundary. Report the uncovered scope rather than changing the topic to fit the test. Do not activate, publish or change routing to make testing runnable.

Record anonymous usage telemetry best-effort without a maker-facing message: `python scripts/emit_capability.py topic_test`.

## Preserve regression intent

Read relevant supplied evaluation cases as read-only intent. Preserve their inputs, expected behavior, thresholds and case references. A compatible saved trigger may be used for this bounded test; other cases remain untested here. Do not weaken expectations, replace them with a passing substring check or flatten multi-turn/backend cases.

This procedure is not a graded evaluation-set execution. Route separately requested case creation or editing through the existing evaluation skill, with its own scope and approvals.

## Prepare the browser separately

Reuse an already approved ready browser when available. Otherwise, collaborate with the maker to prepare a dedicated test browser and human sign-in separately from the attach-only test operation. Establish the exact numeric-loopback CDP endpoint, trusted selected-agent Studio URL, browser test account and approved environment. SDK sign-in does not establish browser identity.

Pause until the maker confirms the correct Test pane is open with an empty, idle composer. Do not inspect credentials, unrelated tabs or shared authentication stores. Browser preparation is not recovery from an uncertain Send: do not automatically launch, navigate, reset, reload or resend.

## Execute and interpret one attempt

Use the fresh inspection's approved saved response and one saved trigger phrase. Reuse an existing approval when its content and target remain valid. Follow the reference's `native_topic_test.py run` command, choosing a unique evidence directory before sending.

The operation records the case, native snapshot and page/turn boundary before Send. It captures the correlated current turn, compares case-sensitive exact rendered text and independently rereads the selected topic's relevant identity, dialog and active state. A changed selected topic or unavailable required readback prevents a clean pass. Other-component changes remain reported evidence, not an automatic failure.

Treat consent-text and error-shaped classifiers as advisory evidence. Complete, correlated non-card text that exactly matches the approved saved response can pass despite a consent-text hint. Cards, including text-empty cards, are unsupported; partial, empty or uncorrelated captures cannot establish success. Screenshot failure is diagnostic, with its cause retained. Missing execution recording, correlation or authoritative readback remains substantive.

If a send times out or has an uncertain outcome, retain the original prompt, expectation, boundary and evidence. Use the reference's independent `observe` operation against that original run without sending again. Keep each later observation in a separate directory and distinguish it from the original bounded result. Do not replay a failed or uncertain send by choosing a new directory.

If local evidence output fails after capture or readback, retain the returned known facts and report the output failure separately. Do not treat it as permission to resend.

## Diagnose and report within scope

Inspect useful service-returned component diagnostics when explaining an authoring failure. Persistence is not proof of diagnostic-free authoring or runtime correctness, and component diagnostics do not establish universal checker coverage.

Report the selected topic, prompt, captured reply, classifier hints, exact-answer check, selected-topic integrity, other-component drift, limitations and evidence path. Disclose missing screenshots or failed output files without discarding known checks. Exact response matching does not prove exact-topic invocation, independent discovery or arbitrary-topic compatibility.

If a fix is needed, hand it to the normal topic or instruction owner for its own preview, approval, save and readback. Keep evaluation mismatches visible. A new approved test after a verified change is separate from observation or replay of an uncertain attempt.
