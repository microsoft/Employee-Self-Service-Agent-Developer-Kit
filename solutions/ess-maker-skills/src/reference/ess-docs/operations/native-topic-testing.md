# Native topic browser testing

Test one saved native fixed-response topic in the selected Dev agent. The
supported dialog is a literal text `SendActivity` followed by `EndDialog`.
Dynamic expressions, cards, additional branches, workflows and backend-fault
diagnostics are not supported by this procedure.

## Resolve the topic and expected response

Use the canonical ready workspace and its selected Maker identity. Never
borrow another workspace's authentication cache or change global profiles.
If authentication needs a human action, tell the maker and pause for it.
Do not silently select the first account.

1. Resolve an explicitly requested component ID. If only a name or description
   is known, run `python scripts/native_topic_test.py list` and identify one
   exact native topic with the maker. Do not require a local topic file.
2. Run `python scripts/native_topic_test.py inspect --component-id "<id>"`.
   This fresh read returns the saved response, trigger phrases, active state
   and an inspection file under `.local/topic-tests/`.
3. Confirm that the selected topic and saved response are what the maker
   intends to test. Reuse an existing approval when the fresh content matches
   it. If the content changed, obtain approval again rather than silently
   changing the expected answer.
4. Select one saved trigger phrase. Do not invent failure probes or additional
   messages for this response-only path. The run command rejects content
   drift since inspection and refuses an inactive topic.

Run commands from the Maker Kit folder. `--kit-root` can explicitly identify
that same configured workspace when invoking a script from another directory.
An unsupported topic is a coverage boundary, not a successful test.

## Confirm browser readiness

The maker supplies the exact numeric-loopback CDP endpoint, such as
`http://127.0.0.1:9222`, and the full trusted Studio details URL for the selected
environment and agent, including `agentBackend=cosmos` when present.
`localhost`, non-loopback endpoints, guessed hosts, substring page matches and
duplicate matching tabs are not accepted.

Confirm that the environment, account and data are approved for testing and
that the maker has signed into that browser with the intended test identity,
opened the Test pane and left an empty, idle composer. Reuse current valid
confirmation; native SDK authentication does not establish browser identity.
Do not inspect browser credentials, cookies, identity storage or unrelated
tabs. Conversational routing can reach other tools even when the intended
topic itself is response-only, so stay within the approved test resources.

This tool attaches only. If no suitable browser is ready, ask the maker to
provide one and pause. It does not launch a browser, authenticate, navigate,
reset or reload. Only the supported embedded M365 composer and current-turn
boundaries are accepted. Other surfaces require separate support.

Activation, agent-wide routing and publication are separate operations
requiring explicit approval. Do not perform them to make `/test` pass.

## Run once and retain evidence

Choose one fresh output directory and keep that exact path for the attempt:

```powershell
python scripts/native_topic_test.py run `
  --inspection "<inspection file>" `
  --prompt "<one saved trigger phrase>" `
  --cdp "<confirmed numeric-loopback endpoint>" `
  --url "<confirmed full Studio URL>" `
  --output ".local/topic-tests/<unique attempt>"
```

The tool writes the prospective case and native snapshot before driving. It
records the browser page and turn boundary before one Send action, captures
only the correlated current reply, classifies it with the shared reply
classifier, and checks case-sensitive exact rendered-text equality. A real
error reply is not a correct answer. Consent gates, cards, empty captures and
timeouts cannot pass the response check. Rendering can change Markdown or
whitespace; do not substitute substring matching to hide such a mismatch.

The tool independently rereads native components and reports any drift.
Evidence includes the inspection, case, execution boundary, capture, native
snapshots, result and a current-turn screenshot for a completed capture.
All evidence is workspace-local and ignored by git. Never overwrite an
existing attempt, edit its expected response or discard a failed result.

## Timeouts and ambiguous submissions

The default observation is bounded to 90 seconds. A timeout is incomplete
reply evidence, not proof of a product failure. Do not run the send command
again, choose a new attempt path to replay it, or silently increase every
timeout. If a shell command is still running, wait for it to finish.

To observe the same pending attempt without sending another message:

```powershell
python scripts/native_topic_test.py observe `
  --previous ".local/topic-tests/<original attempt>"
```

The observation uses the original target, browser page, prompt and turn
boundary, writes a separate evidence directory, and preserves the original
timeout or submission error. It verifies the original chat document and
response identity, and refuses a different document or an advanced
conversation. A page refresh requires a separately approved new attempt, not
observation of the previous conversation. If the original execution boundary was never recorded, no Send
action was entered by this tool; restore readiness with the maker before an
explicitly approved new attempt.

## Report the bounded outcome

State the actual prompt, reply classification, exact-answer result, native
integrity result and evidence path. Distinguish the original bounded result
from a later completion. Report unsupported or unavailable evidence plainly.
Exit `0` means the response and integrity checks passed; `1` means a captured
check did not pass; `2` means execution or required evidence is blocked.

Exact reply text is not an exact-topic invocation trace. An existing
conversation is not an independent discovery trial. Do not claim general GA
compatibility, arbitrary-topic coverage, card support, backend execution or
automatic topic discoverability from this bounded result.
