# Topic browser testing

Use the bounded operations below from the topic-testing skill. The session owns intended behavior, test selection, interpretation, fixes and retests. Read [Testing experience](../../../skills/topics/testing-experience.md) for the scoped runtime correctness goal, state-aware offers, normal-chat readiness/outcome and pause/stop copy. A one-turn capture does not limit the whole test to one message or one literal response.

## Contents

- [Resolve and inspect](#resolve-and-inspect)
- [Explicit activation](#explicit-activation)
- [Prepare the test browser](#prepare-the-test-browser)
- [Confirm browser readiness](#confirm-browser-readiness)
- [Start a new Test conversation](#start-a-new-test-conversation)
- [Capture an approved turn](#capture-an-approved-turn)
- [Optional exact-response assertion](#optional-exact-response-assertion)
- [Observe uncertainty without sending again](#observe-uncertainty-without-sending-again)
- [Observe topic values temporarily](#observe-topic-values-temporarily), including [owned cleanup](#remove-only-owned-instrumentation)
- [Fix and retest](#fix-and-retest)

Read the applicable section and its subsections before its operation. Read the complete temporary-value section, including cleanup, before saving instrumentation.

## Resolve and inspect

Use the canonical ready workspace and its selected Maker identity. Never borrow another workspace's authentication cache or change global profiles. If authentication needs a human action, tell the maker and pause for it. Do not silently select the first account.

Carry the selected topic and intended behavior from authoring or the request. When identity is unknown, use `python scripts/native_topic_test.py list` and disambiguate only as needed. A missing local YAML file does not establish remote absence.

```powershell
python scripts/native_topic_test.py inspect --component-id "<selected id>"
```

Inspection returns the authoritative component, triggers/state and a workspace-local inspection file. Ordinary dialogs can be inspected; `exactMode.supported` only describes compatibility with the optional fixed-response `run` assertion. Plan testing against intended behavior, not whatever reply happens to be saved. If current content materially differs from the authorized target or intent, resolve that difference rather than silently substituting an expectation.

Run commands from the Maker Kit folder. `--kit-root` can explicitly identify that same configured workspace when invoking from another directory.

## Explicit activation

Saving a topic does not activate or publish it. For an inactive selected topic, preview the separate activation operation:

```powershell
python scripts/native_topic_test.py activate --inspection "<inspection file>"
```

Show the effect and use the shared Activate and test choice when activation permission is missing. For already-requested testing, use Activate {Topic title} for testing? to obtain only the missing activation permission and retain test-only or test-and-fix scope. Honor no-activation requests. Only after explicit authorization for this selected topic:

```powershell
python scripts/native_topic_test.py activate --inspection "<inspection file>" --yes
```

The operation checks target/content again, changes only the selected topic's state/status, and reads back its state without publishing or changing competitors. Continue only after authoritative Active state is confirmed. Reinspect after activation to obtain the current capture boundary. Preserve known write acceptance and `activationOutcome`, `writeAccepted` and `verified` facts when later readback or local output fails; inspect actual state before any retry, never blindly activate again.

## Prepare the test browser

Reuse a valid dedicated browser and its connection facts when available.

Before calling `prepare-browser`, recover existing connection facts from the session or this workspace's `.local/topic-tests/` evidence. When the record is not already known, use filesystem discovery that includes ignored folders:

```powershell
Get-ChildItem -LiteralPath '.local\topic-tests' -Filter result.json -File -Recurse |
    Select-Object -ExpandProperty FullName | ConvertTo-Json
```

An absent evidence folder means there are no workspace-local records to inspect. Read results whose `operation` is `prepare-browser`; directories may be caller-named, not just `prepare-browser-*`. Match the recorded target's environment, tenant, ring, agent and realm to the selected context. Recover `pid`, `profile`, `cdp` and `url` from matching records, then check their live state. One stale record does not make all matching browsers unavailable. When several are usable, prefer an already signed-in browser for the selected test identity rather than simply the newest record.

Check the recorded browser PID and CDP endpoint separately. Emit JSON, not mixed formatted tables. These are read-only detection checks, not Test-pane readiness checks.

```powershell
$b = Get-Content '<recorded prepare-browser result.json>' -Raw -ErrorAction Stop |
    ConvertFrom-Json

Get-Process -Id $b.pid -ErrorAction Stop |
    Select-Object Id, Responding | ConvertTo-Json

Invoke-RestMethod "$($b.cdp.TrimEnd('/'))/json/version" -TimeoutSec 5 -ErrorAction Stop |
    ConvertTo-Json
```

Preserve and inspect any error before declaring the browser unavailable.

Otherwise, prepare a new Microsoft Edge InPrivate window for the selected agent:

```powershell
python scripts\native_topic_test.py prepare-browser `
  --url "<trusted selected-agent Studio URL>"
```

Resolve the full URL internally from the selected setup context and the exact supported host/path contract in `daga_chat_driver.validate_studio_url`. Bind it to the selected environment and agent, retaining `agentBackend=cosmos` when present. The operation validates it against the authenticated agent target before launch. Browser connection facts are operation inputs/outputs; the maker's part is sign-in and Test-pane readiness.

Preparation creates a fresh temporary profile, opens the selected URL, requests an ephemeral numeric-loopback debug port and verifies that browser metadata matches its dedicated debug descriptor. It returns `pid`, `profile`, `cdp`, `url`, the target and browser metadata, with workspace-local launch/result evidence. `prepared` means browser/connection preparation, not sign-in, Test-pane readiness or a passing test. No conversation Send, activation or publication is performed.

Feed the returned `cdp` and `url` to capture after readiness is confirmed. Preserve a live browser and all known process/endpoint facts when preparation or local evidence recording is incomplete; inspect that attempt before deciding whether another browser is needed. The temporary profile contains browser state, not test evidence: keep its contents out of logs, reports and galleries.

Keep the browser and its profile available for follow-up checks, reporting and resumption, including after a completed test or a pause/stop. Leave normal browser closure to the maker; do not close it or delete its profile as routine test cleanup. If the maker asks to close it, act only on the recorded owned PID and clean up its exact temporary profile after it has exited.

Prepare a fresh window when the existing one is unavailable or unusable, after inspecting its state and reconciling any uncertain Send. Retain the prior browser identities and evidence; completing one check is not a reason to replace the browser. A replacement can require the maker to sign in again.

### Browser refresh signals

If expected controls are not visible, try CDP `Emulation.clearDeviceMetricsOverride` on the selected test page, then recheck visibility.

Consider refreshing when:

- Replies still reflect older content after a verified save and new conversation.
- A saved, active topic is reported unavailable.
- The Test pane fails to load or Retry does not recover it.
- Send remains unresponsive or leaves a draft without a confirmed new turn.

Treat these as indicators, not proof. Missing diagnostic output alone is insufficient.

Make a best-effort refresh of the same signed-in window, preserving evidence and reconciling any uncertain Send first. Reopen Test and establish a new conversation before retesting. Use a fresh window only when the existing one remains unusable; leave normal closure to the maker.

## Confirm browser readiness

Render the shared full Test browser readiness message in normal chat, followed by its separate readiness-only control. The maker signs in with a test account if necessary, opens the Test chat pane and leaves its message box empty and idle. Omit an unnecessary sign-in paragraph and reuse valid readiness across completed turns. SDK authentication does not establish browser identity.

Not ready, keep paused and Stop without sending take effect immediately with the shared exact acknowledgements. Report completed work separately using `{topic_test_results}`. Resume with existing valid context and permissions, resolving only missing or changed prerequisites. Ask the maker only for a genuine human action, missing permission or scope decision.

Confirm the selected test resources, browser identity, correct Test pane and empty, idle composer. Do not inspect credentials, cookies, identity storage or unrelated tabs. Conversational routing can reach other tools, so stay within authorized test resources. The attach-only capture operation accepts an exact numeric-loopback endpoint and a unique page at the full trusted selected-agent URL; `localhost`, non-loopback endpoints, substring matches and duplicate matching tabs are unsupported.

Preparation is separate from capture and is not recovery from an uncertain Send. Capture does not launch, authenticate, navigate, reset or reload.

## Start a new Test conversation

When a fresh scenario or post-save retest needs a new conversation, use the existing browser connection:

```powershell
python scripts\native_topic_test.py new-conversation `
  --cdp "<confirmed numeric-loopback endpoint>" `
  --url "<confirmed full Studio URL>"
```

The operation validates the selected agent and browser target, clicks **New chat** in the supported Test frame, and detaches without closing the browser or its profile. `outcome: clicked` means the click completed, not proof of server-side conversation identity or execution of the saved version. It does not capture or send a message.

The session chooses when to call this operation and how to continue after its result or error. Reuse valid readiness and test-and-fix permission; starting a new conversation does not itself require another readiness question. Follow [post-save conversation freshness](native-topic-debugging.md#establish-post-save-conversation-freshness) for the next capture, and preserve conversation context between related turns.

## Capture an approved turn

Choose a unique output directory for each authorized turn:

```powershell
python scripts/native_topic_test.py capture `
  --inspection "<current inspection file>" `
  --prompt "<approved test message>" `
  --cdp "<confirmed numeric-loopback endpoint>" `
  --url "<confirmed full Studio URL>" `
  --output ".local/topic-tests/<unique attempt>"
```

Capture accepts an approved prompt rather than requiring a saved trigger. It records remote state and the page/turn boundary before one Send, then returns correlated reply/card, partial/timeout, screenshot and AgentBuilder readback facts. `graded: false` and `outcome: captured` mean capture completed, not correctness or backend-completion proof. The session evaluates the observed behavior and relevant effects against the intended scenario.

The result includes the existing reply classifier's `signal` (`ok`, `consent_gate`, `timeout` or `empty`) and `errorShaped` advisory. These do not grade the topic or prove a backend ran. Read every captured bubble, not just the first message.

After a saved change or when an independent conversation is required, follow [post-save conversation freshness](native-topic-debugging.md#establish-post-save-conversation-freshness). `capture` and `run` accept `--require-empty-conversation` to reject a nonempty or unverified prepared turn boundary before Send. The flag never resets the conversation and never falls back to an old one. It verifies an empty transcript, not a new server-side conversation or execution of the saved version; retain the actual preparation and observed-version evidence separately. `observe` preserves the original gate facts without applying a new empty-conversation requirement.

Use further completed turns to exercise authorized paraphrases or conversation branches. A card is observed evidence, not automatically a failure. The current driver does not submit interactive-card actions, inject backend faults or provide exact-topic invocation traces. Report a specific unperformed interaction or collaborate with the maker when needed; do not claim those capabilities or reject all ordinary dialogs because optional exact-mode is incompatible.

## Optional exact-response assertion

Use `run` instead of `capture` only when the intended assertion is a saved trigger returning the approved literal response from a `SendActivity` followed by `EndDialog`. It takes the same inspection/browser/output arguments, with `--prompt` set to a saved trigger. The exact check and selected-topic readback are evidence for that assertion only, not a universal topic-testing policy. Do not weaken a different expectation to fit this path.

## Observe uncertainty without sending again

The default observation is bounded to 90 seconds. A timeout is incomplete evidence, not proof of product failure. Do not replay the message by choosing another output path or silently increase every timeout. Wait for a still-running command to finish.

```powershell
python scripts/native_topic_test.py observe `
  --previous ".local/topic-tests/<original attempt>"
```

Observation follows the original capture or exact run without another Send, retains its graded/non-graded mode, and writes separate evidence. It preserves the original target, page, prompt and turn boundary, rejects a different document or advanced conversation, and does not erase the original error. If no boundary was recorded, no Send action was entered by the tool; establish readiness before a separately authorized new attempt.

Keep evidence directories and returned facts. Screenshot/output failures retain their causes and do not authorize replay. Known capture, remote write or readback facts survive a subsequent local recording failure. Report unavailable correlation or required readback explicitly.

## Observe topic values temporarily

Use a temporary `SendActivity` when the captured reply or rendered card is insufficient to explain topic state. The session chooses the values, placement and next investigation; this is not a mandatory step for every mismatch. Observe only non-sensitive synthetic or explicitly authorized values. Do not print credentials, tokens, employee records or entire backend responses.

Instrumentation is a saved-topic edit, not a read-only test. Use the existing authorized debugging objective and editable scope; obtain missing permission for a test-only request. Do not publish, change activation state or alter competing topics.

### Prepare an owned diagnostic

Read the mapped topic through the ordinary authoring owner, keeping its current component and YAML projection:

```powershell
python scripts\topic_authoring.py read --topic "<mapped topic path>" --output "<fresh read.json>" --yaml-output "<current projection.mcs.yml>"
```

The read result supplies `target`, `path` and `component` for update's `--expected` input. It is not a capture inspection file. Compare the working draft with saved content and preserve any pending authoring edits; do not overwrite it with a remote projection.

Choose an actual action ID after the value is assigned and before the suspected consumer. For a nested branch, choose the action in that branch; anchoring a container places the diagnostic after the entire container. Use a fresh unique diagnostic action ID.

Allow for LLM synthesis of topic output; do not assume a `SendActivity` is displayed verbatim. Use ordinary, topic-relevant wording with clearly labeled interpolated values. Avoid debugging/testing labels such as `DBG`, `DEBUG`, "diagnostic" or "test output". A prefix such as `Ready for review:` may be used, but is not required for capture or cleanup. Keep unique ownership identities in action IDs and cleanup records. Quote the activity as a YAML string, for example by applying `json.dumps` to the message:

```text
Ready for review: total={Topic.Total}
```

Use `plant_debug_node` from `scripts/debug_plant.py` to prepare the local delta. Require exactly one insertion at the intended sibling boundary, an unambiguous anchor and an unused diagnostic ID. Preserve valid text interpolation rather than turning a variable reference into literal text. Convert/preview the proposed YAML through ordinary topic authoring and inspect the resulting action and diagnostics. Conversion alone does not establish runtime reachability or value visibility.

Before any possible save, retain a small workspace-local cleanup record under the attempt's `.local/topic-tests/` evidence directory: selected target and mapped topic identity, action anchor, exact diagnostic action ID, intended owned node content and the original read/proposed-save evidence paths. Keep the record if save acceptance or readback is uncertain. This records ownership, not a second debugging workflow.

### Save and observe

Use the ordinary topic update preview/save with the fresh read as `--expected`, retaining its concurrency checks and authoritative readback. The existing scoped debugging authorization covers this in-scope temporary edit without an independent per-node approval. Inspect the saved diagnostic content and retain its canonical identity/content for precise cleanup.

Obtain a fresh `native_topic_test.py inspect` result after the save, establish [post-save conversation freshness](native-topic-debugging.md#establish-post-save-conversation-freshness), then use a bounded `capture --require-empty-conversation` with the authorized scenario and current browser readiness. Fresh AgentBuilder readback and a page reload alone do not establish updated-content execution. Read values actually present in the correlated reply alongside the normal reply and cards. A saved expression, accepted save or absent bubble does not establish the variable's runtime value. Card DOM text can omit information such as dropdown options; a deliberately chosen count or safe projected field can provide evidence that the rendering alone lacks.

If a value is unavailable, inspect the capture, message wording, conversation freshness and diagnostics before drawing conclusions. A failure before the diagnostic boundary can prevent observation. When useful, move the owned message one boundary earlier, before the suspected `Split`, `First`, parse, card or other consumer, and repeat a deliberate probe within scope. Reconcile and remove the previous owned message before moving it; keep the ownership record current before another possible save. Compare observed values and message content across boundaries without assuming that an absent message alone proves reachability or the cause. Do not move it later as a substitute for earlier-boundary localization. Do not assume exact-topic invocation or reset/reload the conversation to conceal an uncertain Send; use independent `observe` against that attempt first.

### Remove only owned instrumentation

Always attempt safe cleanup before completing the debugging work, including after an inconclusive diagnosis or a pause/stop. Honor a stop instruction that forbids further writes and explicitly report any diagnostic left in place.

Read the latest saved topic and preserve legitimate intervening fixes and newer content. Use `strip_debug_nodes` with exact IDs and `expected_nodes` from the cleanup record, not marker-wide matching:

```python
cleaned_yaml, removed_ids = strip_debug_nodes(
    fresh_projected_yaml,
    node_ids=[owned_id],
    expected_nodes={owned_id: owned_yaml_action},
)
```

`owned_yaml_action` is the complete parsed YAML action mapping, not an Object Model `$kind` object or a raw YAML string. The guard checks unique identity and unchanged owned content before returning a cleanup delta. If identity or owned content differs, inspect and reconcile it rather than deleting an ambiguous node. Never restore the whole pre-debug snapshot over legitimate changes.

Preview/save the cleanup delta through the ordinary update operation using the current read as `--expected`. Verify authoritative AgentBuilder readback, absence of the owned diagnostic IDs, preservation of intended corrections and consistency of the local working draft/baseline. Retest the affected normal behavior without instrumentation when useful. Treat byte differences from Object Model-to-YAML projection separately from semantic content preservation.

Retain the cleanup record and original errors until removal is verified. For interrupted or uncertain writes, inspect current saved content before choosing the next action; do not blindly plant, save or resend. Report cleanup failure or uncertainty separately from the original diagnosis and known fix. Link actual value/capture and cleanup evidence after the shared outcome report rather than adding a debugging-mechanics ledger.

## Fix and retest

Return observed issues to the ordinary topic/instruction owner with the selected target, intended behavior, issue evidence and existing debugging objective/editable scope. Necessary fixes, pushes and retests reuse that scoped authorization, subject to concurrency safeguards. Ask again for expanded scope, changed intended behavior or additional consequential actions. A test-only request does not authorize edits; supplied evaluation cases remain read-only unless separately selected for evaluation work.

After a verified fix, reinspect and retest affected behavior with a new capture, making a lightweight, best-effort check against matching eval intent. This is a deliberate retest after known change, not replay of an uncertain attempt. Continue useful in-scope debugging toward the latest authoring goal; a fixable mismatch is not by itself a reason to hand work back. If conflicting goals or constraints prevent progress, recommend a concrete reconciliation. If tools, access or evidence prevent further safe progress, explain the limitation and offer practical assistance, including manual testing guidance where appropriate.

Report the goal and observed runtime outcome using `{topic_test_results}`, adding a recommendation only when a change or assistance is needed. Keep actual evidence links after the complete outcome block. This is not a graded eval run or mandatory regression-coverage report. The informational report needs no routine acknowledgement; ask separately only for genuine human dependencies or a new scope decision. Exact text, successful persistence or DOM completion alone does not establish general runtime correctness.
