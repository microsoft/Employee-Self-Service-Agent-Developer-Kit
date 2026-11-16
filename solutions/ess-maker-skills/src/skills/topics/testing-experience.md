# Topic testing experience

<!-- markdownlint-disable MD001 -->

Apply the [shared foundation](experience-contract.md). Use this reference when offering testing, entering the testing owner, reporting saved observations or handling readiness, pause and stop. Read the [post-Push conflict decision](authoring-experience.md#combined-routing-conflict-and-testing-follow-up) only when that condition applies.

## Contents

- [Testing status updates](#testing-status-updates)
- [Topic testing continuation](#topic-testing-continuation)
- [Scoped runtime correctness goal](#scoped-runtime-correctness-goal)
- [Topic debugging outcome: `{topic_test_results}`](#topic-debugging-outcome-topic_test_results)
- [Testing offers](#testing-offers)
- [Browser readiness and testing goal](#browser-readiness-and-testing-goal)
- [Pause, stop and resume](#pause-stop-and-resume)
- [Unresolved prerequisites](#unresolved-prerequisites)

## Testing status updates

Apply [Status update markers](experience-contract.md#status-update-markers) only after testing is requested or selected. Resolve `{Topic title}` and `{Agent name}` from the selected target. Not now adds no testing work.

| Reporting point       | Completion condition                                                                                                                                                              | Completion message                                                                |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `topic-activation`    | A new explicitly approved activation is confirmed and authoritative readback shows Active state.                                                                                  | ✅ Activated **{Topic title}** for testing.                                       |
| `testing-readiness`   | The saved target, intended behavior, useful probes, available capability and applicable permissions are established.                                                              | ✅ Established the testing scope for **{Topic title}**.                           |
| `browser-preparation` | A usable owned test browser is prepared or reused and opened to the selected agent.                                                                                               | ✅ Prepared the test browser for **{Agent name}**.                                |
| `browser-readiness`   | Valid human readiness and the correct selected-agent Test pane with an empty, idle composer are confirmed.                                                                        | ✅ Confirmed browser readiness for **{Topic title}**.                             |
| `test-assessment`     | The selected checks have been interpreted against intended behavior, relevant effects are verified, and the observations support that behavior without a material unresolved gap. | ✅ Observed the requested behavior for **{Topic title}** in the completed checks. |

Browser preparation is not human readiness, activation is not a test result, and a completed capture is not correctness. Use [Topic debugging outcome](#topic-debugging-outcome-topic_test_results) for failed prerequisites, observed mismatches, incomplete checks, evidence failures or uncertainty. Report the actual limitation rather than the completion message. A successful assessment covers only the completed checks, not universal runtime correctness.

For an already-Active no-write result, report the verified state and that no activation was needed rather than claiming a new activation.

Report each interpreted pass before its next fix or final report. Report a revised assessment after a post-fix retest; do not emit after every capture merely because it returned. Delegated fixes and saves use their owners' updates without a second caller update. Preserve earlier confirmed work and existing scoped consent.

For a selected pause or stop, use [Pause, stop and resume](#pause-stop-and-resume) exactly, in place of a generic `browser-readiness` update for that result. Stop sending immediately; do not finish more work to reach a marker. Keep known results and uncertainty for the separate outcome report.

## Topic testing continuation

Check `scripts/native_topic_test.py` directly before offering runnable conversation testing. If unavailable, report conversation acceptance as pending and the actual capability gap; do not imply that a save/readback tested the conversation.

### Scoped runtime correctness goal

Debug and fix the topic under test so its observed runtime behavior meets the latest authoring request, within the authorized scope. Make a lightweight, best-effort check that the behavior and proposed fixes preserve matching eval intent; keep those evals read-only. Continue useful in-scope investigation and corrections, checking the affected runtime behavior after changes. When conflicting goals or constraints prevent progress, recommend a concrete reconciliation. When tools, access or available evidence prevent further safe progress, explain the limitation and offer practical assistance, including manual testing guidance where appropriate. Honor explicit test-only, pause and stop requests.

Use relevant existing cases and useful probes as advisory intent checks, not a graded eval run or a mandatory case-by-case coverage exercise. A fixable in-scope mismatch calls for further investigation and correction, not merely a recommendation to the maker. Do not weaken the authoring goal or edit evals to manufacture agreement.

Preserve supplied or accepted response wording and links during debugging unless the maker authorizes a wording change. Do not replace wording merely to obtain a passing test. Text-message output, literal saved content and verbatim runtime delivery are distinct claims; a save alone does not establish the last. Apply Supported authoring scope to proposed topic fixes without restricting read-only inspection of existing topics.

### Topic debugging outcome: `{topic_test_results}`

Use `{topic_test_results}` to summarize the requested goal and current observed runtime outcome in normal chat. Describe behavior and its limits rather than attempts or iterations. This is an informational report, not another approval gate. Ask separately only for genuine human input or a new scope decision; necessary in-scope fixes and retests already have authorization. Finish without an automatic follow-up form.

Resolve `{Topic title}`, `{Agent name}` and `{Environment name}` from the selected target. `{Latest authoring goal}` is the requested behavior, not whatever reply happens to be saved. `{Observed runtime outcome}` states the behavior actually observed without claiming exhaustive validation.

When the requested behavior is observed, render:

> ##### TOPIC DEBUGGING OUTCOME
>
> ##### TOPIC
>
> {Topic title}
>
> ##### TARGET
>
> {Agent name}, {Environment name}
>
> ##### GOAL
>
> {Latest authoring goal}
>
> ##### OUTCOME
>
> {Observed runtime outcome}

When a change or assistance is needed, render:

> ##### TOPIC DEBUGGING OUTCOME
>
> ##### TOPIC
>
> {Topic title}
>
> ##### TARGET
>
> {Agent name}, {Environment name}
>
> ##### GOAL
>
> {Latest authoring goal}
>
> ##### OUTCOME
>
> {Current outcome and obstacle}
>
> ##### RECOMMENDATION
>
> {Concrete tweak or next action}

`{Current outcome and obstacle}` preserves completed work, unfinished or unobserved behavior and material uncertainty. `{Concrete tweak or next action}` addresses the actual obstacle: reconcile conflicting authoring constraints or eval intent, offer manual testing guidance for a tooling limitation, or identify a missing prerequisite or observation. These are applicable examples, not mandatory report categories. Do not hand back work that can still be performed safely within the existing authorization.

Render the selected block using its quoted wording, emphasis and paragraph breaks. After the complete outcome block, render:

> ##### EVIDENCE
>
> {Available evidence links}

`{Available evidence links}` contains descriptive Markdown links to the selected run's existing result/report files and other relevant artifacts. Resolve paths from the operations' returned evidence locations and retained run context, including `evidenceDirectory` for topic tests. Omit unavailable artifacts, and omit the entire Evidence line only when no relevant evidence is available. A missing screenshot does not make a saved result file unavailable.

Preserve material evidence limitations without adding a mandatory test ledger, regression matrix or grading claim. For pause/stop, keep the fixed acknowledgement separate and report any completed work using the appropriate outcome block.

### Testing offers

Carry the selected topic forward. Creation stays inactive; updating preserves current state. Activate only after explicit Activate and test selection, confirm the result before testing, and do not publish. If state is unverified, resolve it or report the blocker; do not guess which state-dependent action applies.

After authoring, honor the initial routing-conflict decision. Use the [combined routing-conflict/testing decision](authoring-experience.md#combined-routing-conflict-and-testing-follow-up) only for a newly discovered or materially changed conflict after Push. A selected test-anyway continuation enters testing directly with the declined instruction correction excluded; do not repeat the ordinary testing offer or silently fix that conflict. After Push topic anyway, use the ordinary question matching the saved topic's active state, carrying the declined correction as an explicit exclusion and retaining a concise conflict reminder. The topic-only Push did not authorize testing. Without a conflict, or after a verified instruction correction, use the same ordinary question. Do not offer runnable testing of topic changes left local or repeat an offer when testing has already been requested. Honor explicit requests to test without making changes.

For an inactive topic after any confirmed authoring or Push outcome, explain the choices in normal chat immediately before the separate control:

> ##### YOUR CHOICES
>
> | Choice            | What happens                                                                                            |
> | ----------------- | ------------------------------------------------------------------------------------------------------- |
> | Activate and test | Activate the topic in Dev, test its behavior, and fix issues within the selected scope. Do not publish. |
> | Not now           | Leave the topic saved and inactive. Defer conversation testing.                                         |

Keep these explanations outside the picker. Call `ask_user` with this JSON. Keep the top message empty, use the contextual panel title and fixed inner question below, and allow custom text. The JSON defines the control; do not print it in chat. Submit, keyboard hints and close/collapse controls belong to the host.

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "action": {
        "type": "string",
        "title": "Topic testing",
        "description": "How would you like to continue?",
        "enum": ["Activate and test", "Not now"]
      }
    }
  }
}
```

For an active topic, use this same JSON with `enum` set to `["Test topic now", "Not now"]`, and replace the explanation rows with:

> ##### YOUR CHOICES
>
> | Choice         | What happens                                                                                              |
> | -------------- | --------------------------------------------------------------------------------------------------------- |
> | Test topic now | Test the saved topic and fix issues within the selected scope. Preserve its active state; do not publish. |
> | Not now        | Leave the saved topic unchanged. Defer conversation testing.                                              |

When testing has already been requested but activation permission is missing, use the following activation-only explanations and control. Preserve the existing test-only or test-and-fix scope; activation permission adds no edit permission.

> ##### YOUR CHOICES
>
> | Choice            | What happens                                                                                                                 |
> | ----------------- | ---------------------------------------------------------------------------------------------------------------------------- |
> | Activate and test | Activate this topic for the already-requested testing. Continue only after verified Active state, within the existing scope. |
> | Not now           | Leave the topic inactive and defer testing.                                                                                  |

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "action": {
        "type": "string",
        "title": "Topic activation",
        "description": "How would you like to continue?",
        "enum": ["Activate and test", "Not now"]
      }
    }
  }
}
```

Honor an explicit no-activation instruction and report the unresolved prerequisite using `{topic_test_results}`. A test-and-fix choice authorizes necessary fixes, pushes and retests within the selected scope, not unrelated changes or publication.

Test topic now continues into the [testing owner](test/SKILL.md) with the selected topic and the authorized objective/editable scope. Activate and test performs the separately authorized activation continuation, then tests only after confirmed activation. An already-requested test does not waive missing activation permission. Honor explicit no-activation requests.

Not now uses the following outcome, then stops:

> ##### TESTING DEFERRED
>
> {Contextual trailer}

### Browser readiness and testing goal

Prepare or reuse the test browser, open the selected agent and resolve the browser connection internally. The maker opens the Test chat pane. Render the following readiness message in normal chat when confirmation is needed. Resolve `{Topic title}`, `{Agent name}` and `{Environment name}` from the selected context rather than asking for known values again. Omit the sign-in paragraph when the browser is already signed in with a test account. Reuse valid readiness confirmation instead of repeating this exchange. Use the test-and-fix goal below for an authorized test-and-fix request; preserve explicit test-only scope.

> ##### TEST BROWSER READINESS
>
> ##### TOPIC
>
> {Topic title}
>
> ##### TARGET
>
> {Agent name}, {Environment name}
>
> In the prepared test browser, sign in with a test account.
>
> Open the Test chat pane and leave its message box empty and idle.
>
> After you confirm readiness, I will test {Topic title} against its intended behavior, investigate and fix issues observed during execution, and retest the affected behavior.
>
> I will summarize the outcome and recommend any next action needed.

Render the readiness message using the quoted wording, emphasis and paragraph breaks. Start any additional scope context after a blank line following the readiness message.

Follow with this separate readiness-only control. Missing activation permission remains a separate requirement; this choice does not expand the testing/editing scope.

> ##### YOUR CHOICES
>
> | Choice                 | What happens                                                                                    |
> | ---------------------- | ----------------------------------------------------------------------------------------------- |
> | Ready to test          | Confirm this browser is ready. Continue only within the existing permissions and testing scope. |
> | Not ready, keep paused | Pause without sending a test message. Keep completed work.                                      |
> | Stop without sending   | End further testing without sending. Keep completed work and the browser available.             |

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "action": {
        "type": "string",
        "title": "Test browser readiness",
        "description": "How would you like to continue?",
        "enum": [
          "Ready to test",
          "Not ready, keep paused",
          "Stop without sending"
        ]
      }
    }
  }
}
```

For an explicit test-only request, describe that authorized scope without promising edits. An optional exact-response check remains one supported assertion, not a universal one-message or fixed-response-only testing policy.

### Pause, stop and resume

Apply the selected pause or stop immediately; no additional input is needed for either choice to take effect. Use the corresponding acknowledgement exactly. Preserve completed work and report it separately using `{topic_test_results}`.

For **Not ready, keep paused**:

> ##### TESTING PAUSED
>
> Let me know when the test browser is ready.

For **Stop without sending**:

> ##### TESTING STOPPED

A pause waits for the maker's readiness or resume signal. A stop ends further testing until a later explicit request. On resumption, continue within the existing objective and scope, reusing valid context and permissions and resolving only missing or changed prerequisites. Completed activation, fixes or pushes remain completed; pausing or stopping does not roll them back.

### Unresolved prerequisites

Resolve session-owned preparation and connection work internally before handing an unresolved prerequisite back to the maker. Prepare or reuse the test browser and open the selected agent. Ask the maker only for a genuine human action, missing permission or scope decision.

Use the activation-only question when testing is already requested and only activation permission is missing. Honor explicit no-activation and test-only instructions. Use the browser-readiness message and separate readiness control when confirmation is needed, reusing valid readiness.

Preserve completed work and uncertain outcomes; do not blindly repeat an uncertain write. Report unresolved prerequisites using `{topic_test_results}`, identifying unfinished testing explicitly. Ask any genuinely required decision separately; use normal chat for free-text clarification. Omit genuinely empty sections and unavailable evidence links.
