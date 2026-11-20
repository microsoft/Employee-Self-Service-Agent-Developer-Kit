# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Guards: ServiceNow Connect must never surface a card to the maker."""

from __future__ import annotations

import json
import re

from pathlib import Path

import pytest

import connect_servicenow_da as snow


REPO = Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills"
CONNECT_DOCS = REPO / "src" / "skills" / "connect"
CARD_TOOL = re.compile(r"ask_user|vscode_askQuestions|AskUserQuestion")
NEGATION = re.compile(r"\b(never|not|no|don't|do not|without)\b", re.I)
GUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)
INTERNAL_LABELS = (
    "Values from the maker",
    "Send back to the maker",
)


def _servicenow_docs() -> list[Path]:
    roots = [
        CONNECT_DOCS / "servicenow-da",
        CONNECT_DOCS / "servicenow-da-hrsd",
        CONNECT_DOCS / "servicenow-da-itsm",
        CONNECT_DOCS / "shared" / "runtime-instructions",
    ]
    docs = [path for root in roots for path in root.rglob("*.md")]
    docs += [
        CONNECT_DOCS / "servicenow" / "entry.md",
        CONNECT_DOCS / "servicenow" / "realms.md",
    ]
    return docs


def test_entry_documents_carry_the_hard_no_card_rule() -> None:
    prompt = (REPO / ".github" / "prompts" / "connect.prompt.md").read_text(
        encoding="utf-8"
    )
    entry = (CONNECT_DOCS / "servicenow" / "entry.md").read_text(
        encoding="utf-8"
    )
    realms = (CONNECT_DOCS / "servicenow" / "realms.md").read_text(
        encoding="utf-8"
    )
    for name, text in (
        ("connect.prompt.md", prompt),
        ("entry.md", entry),
        ("realms.md", realms),
    ):
        top = text[:1800]
        assert "HARD RULE" in top, name
        assert "ask_user" in top and "never" in top.lower(), name
        assert "chatMessage" in top, name


def test_servicenow_docs_never_instruct_a_card_tool() -> None:
    offenders: list[str] = []
    for path in _servicenow_docs():
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not CARD_TOOL.search(line):
                continue
            window = " ".join(lines[max(0, index - 2) : index + 3])
            if not NEGATION.search(window):
                offenders.append(f"{path.name}:{index + 1}")
    assert offenders == []


def test_legacy_servicenow_step_is_marked_retired() -> None:
    step1 = (CONNECT_DOCS / "servicenow" / "step1.md").read_text(
        encoding="utf-8"
    )
    assert "Retired legacy flow" in step1[:600]
    assert "entry.md" in step1[:600]


def test_administrator_packets_have_no_internal_labels() -> None:
    for path in _servicenow_docs():
        text = path.read_text(encoding="utf-8")
        for label in INTERNAL_LABELS:
            assert label not in text, f"{path.name}: {label}"


def _walk(value: object):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _assert_no_card(output: dict) -> None:
    for node in _walk(output):
        if not isinstance(node, dict):
            continue
        assert "askUserArguments" not in node
        assert not node.get("questions")
        assert not (
            isinstance(node.get("question"), str)
            and ("options" in node or "allowFreeformInput" in node)
        )


def _pending_card() -> dict:
    return snow._native_question(
        header="ServiceNow administrator",
        question="Is your ServiceNow administrator available?",
        option_labels=["Yes, available now", "No, not yet"],
    )


@pytest.mark.parametrize(
    "key",
    ["businessGroupAvailability", "instanceQuestion", "userField", "ready"],
)
def test_pending_question_reaches_the_maker_as_the_final_chat_message(
    key: str,
) -> None:
    payload = {
        "decision": "ask",
        "renderBlock": {"text": ""},
        "transport": {key: {"question": _pending_card()}},
        "questions": [_pending_card()],
    }

    wrapped = snow._with_agent_rules(
        snow.plain_text_output(payload), "resume-handoff"
    )

    _assert_no_card(wrapped)
    assert wrapped["endTurn"] is True
    assert "Is your ServiceNow administrator available?" in (
        wrapped["chatMessage"]
    )
    assert wrapped["chatMessage"].rstrip().endswith("Reply **Yes** or **No**.")
    assert list(wrapped)[:2] == ["chatMessage", "endTurn"]
    rules = " ".join(wrapped["agentRules"])
    assert "never uses ask_user" in rules
    assert "END YOUR TURN" in rules


def _flow_output(kind: str) -> tuple[dict, str]:
    """One representative controller output per class, with its command."""
    pending = snow.plain_text_output(
        {"questions": [_pending_card()], "renderBlock": {"text": "Hello."}}
    )
    outputs = {
        "question": (pending, "resume-handoff"),
        "pending-input": (
            {
                "renderBlock": {"kind": "waiting", "text": "Waiting."},
                "pendingInput": {"kind": "instance-confirmation"},
            },
            "resume-handoff",
        ),
        "final": (
            {"renderBlock": {"kind": "final", "text": "All done."}},
            "resume-handoff",
        ),
        "error": (
            {"status": "error", "renderBlock": {"kind": "error", "text": "x"}},
            "resume-handoff",
        ),
        "maker-action": (
            {
                "status": "shared-identity-reuse-required",
                "renderBlock": {"kind": "plan", "text": "Plan."},
            },
            "resume-handoff",
        ),
        "admin-handoff": (
            {
                "decision": "instructions-required",
                "ordinaryReply": {"text": "Please send this to your admin."},
            },
            "identity-direct-handoff",
        ),
        "realm": (
            {"renderBlock": {"kind": "realm-step", "text": "Next step."}},
            "check-realm",
        ),
        "lead-in-checkpoints": (
            {
                "provider": "servicenow-da-itsm",
                "agentSlug": "agent",
                "renderBlock": {"kind": "plan", "text": "We're checking."},
                "checkpoints": {
                    "decision": "run-exact-commands",
                    "commands": [{"command": "python scripts/flightcheck/cli.py"}],
                },
            },
            "resume-handoff",
        ),
        "lead-in-action": (
            {
                "provider": "servicenow-da-itsm",
                "agentSlug": "agent",
                "renderBlock": {"kind": "progress", "text": "Next up."},
                "action": {"decision": "read-action-doc", "actionDoc": "a.md"},
            },
            "resume-handoff",
        ),
        "lead-in-after-record": (
            {
                "provider": "servicenow-da-itsm",
                "agentSlug": "agent",
                "ordinaryReply": {"text": "Saved."},
            },
            "record-preflight",
        ),
    }
    return outputs[kind]


WAIT_CLASSES = (
    "question",
    "pending-input",
    "final",
    "error",
    "maker-action",
    "admin-handoff",
    "realm",
)
CONTINUE_CLASSES = (
    "lead-in-checkpoints",
    "lead-in-action",
    "lead-in-after-record",
)


@pytest.mark.parametrize("kind", WAIT_CLASSES)
def test_outputs_with_a_question_or_wait_end_the_turn(kind: str) -> None:
    payload, command = _flow_output(kind)
    wrapped = snow._with_agent_rules(payload, command)
    assert wrapped["chatMessage"]
    assert wrapped["endTurn"] is True
    assert "nextCommand" not in wrapped


@pytest.mark.parametrize("kind", CONTINUE_CLASSES)
def test_status_outputs_continue_with_an_explicit_next_command(
    kind: str,
) -> None:
    payload, command = _flow_output(kind)
    wrapped = snow._with_agent_rules(payload, command)
    assert wrapped["chatMessage"]
    assert wrapped["endTurn"] is False
    assert isinstance(wrapped["nextCommand"], str) and wrapped["nextCommand"]
    assert "resume-handoff" in wrapped["nextCommand"] or (
        "flightcheck" in wrapped["nextCommand"]
        or "a.md" in wrapped["nextCommand"]
    )


def test_resume_handoff_with_nothing_runnable_never_loops() -> None:
    wrapped = snow._with_agent_rules(
        {"renderBlock": {"kind": "progress", "text": "Hi."}}, "resume-handoff"
    )
    assert wrapped["endTurn"] is True
    assert "nextCommand" not in wrapped


def test_every_output_with_a_chat_message_sets_exactly_one_flow() -> None:
    for kind in WAIT_CLASSES + CONTINUE_CLASSES:
        payload, command = _flow_output(kind)
        wrapped = snow._with_agent_rules(payload, command)
        assert isinstance(wrapped["endTurn"], bool)
        assert wrapped["endTurn"] == ("nextCommand" not in wrapped)


def test_agent_rules_end_the_turn_only_for_a_pending_question_or_wait() -> None:
    rules = " ".join(snow.AGENT_RULES)
    assert "endTurn is true" in rules and "END YOUR TURN" in rules
    assert "endTurn is false" in rules
    assert "do NOT stop" in rules
    for name in ("connect.prompt.md", "entry.md", "realms.md"):
        path = (
            REPO / ".github" / "prompts" / name
            if name.endswith("prompt.md")
            else CONNECT_DOCS / "servicenow" / name
        )
        top = path.read_text(encoding="utf-8")[:2200]
        assert "nextCommand" in top, name


def test_question_helpers_are_not_wrapped_with_chat_message() -> None:
    result = {"schemaVersion": "servicenow.plain-question.v1"}
    assert snow._with_agent_rules(result, "adapt-question") is result
    assert snow._with_agent_rules(result, "match-reply") is result


@pytest.mark.parametrize("profile", ["hrsd", "itsm"])
def test_instance_question_is_maker_friendly(
    profile: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snow, "ACTIVE_AGENT_NAME", "ESS IT")
    context = {
        "agent": {"id": "x", "workspace_slug": "agent"},
        "environment": {"id": "env"},
    }
    with snow.product_profile_context(profile):
        question, choices, _ = snow._preflight_instance_question(
            context=context,
            candidates=["dev123"],
            discovery_error=None,
        )
        text = snow.adapt_question_to_plain_text(question)["plainText"]

    assert "ESS IT" in text
    assert "Employee Self-Service" not in text
    assert "http" not in text.lower()
    assert "service-now.com" not in text
    assert not GUID.search(text)
    assert "Reply **Yes** or **No**" in text
    assert choices["Yes"] == "https://dev123.service-now.com"


@pytest.mark.parametrize("profile", ["hrsd", "itsm"])
def test_every_maker_text_uses_the_recorded_agent_name(
    profile: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snow, "ACTIVE_AGENT_NAME", "ESS Recorded")
    context = {
        "agent": {
            "id": "00000000-0000-4000-8000-000000002222",
            "display_name": "ESS Recorded",
            "workspace_slug": "agent",
        },
        "environment": {
            "id": "00000000-0000-4000-8000-000000001111",
            "display_name": "Contoso Dev",
            "ring": "test",
        },
    }
    with snow.product_profile_context(profile):
        texts = [
            snow._dev_opening_text(context, None),
            snow._current_task_guidance(
                context, {}, phase_id="credential", role="maker"
            ),
        ]
        question, _, manual = snow._preflight_instance_question(
            context=context, candidates=[], discovery_error=None
        )
        texts.append(question["question"])
        texts.append(manual["question"])

    for text in texts:
        assert "ESS Recorded" in text or "Which ServiceNow" in text
        assert "Employee Self-Service" not in text
    assert any("ESS Recorded" in text for text in texts)


def test_card_output_would_have_failed_this_guard() -> None:
    leaked = {"askUserArguments": {"questions": [_pending_card()]}}
    with pytest.raises(AssertionError):
        _assert_no_card(leaked)
    with pytest.raises(AssertionError):
        _assert_no_card({"questions": [_pending_card()]})
    assert json.dumps(snow.plain_text_output(leaked)).count(
        "askUserArguments"
    ) == 0


CARD_PAYLOAD_MARKERS = (
    "visible-handoff-question",
    "allowFreeformInput",
    '"options"',
    '"header"',
)
SHORT_LABELS = {"yes", "no"}


def test_servicenow_docs_contain_no_card_payloads() -> None:
    offenders = [
        f"{path.name}: {marker}"
        for path in _servicenow_docs()
        for marker in CARD_PAYLOAD_MARKERS
        if marker in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_invented_card_text_does_not_exist_in_the_repo() -> None:
    invented = (
        "administrator-confirmed internal column name on sys_user",
        "The full administrator-confirmed employee portal URL",
        "It returned the tickets I expected",
        "Yes, the Maker is available now",
        "No, I need to bring the Maker in",
        "Use another agent (paste link)",
    )
    roots = [REPO / "scripts", REPO / "src" / "skills" / "connect"]
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".md", ".json"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for phrase in invented:
                assert phrase not in text, f"{path.name}: {phrase}"


def test_binary_option_labels_are_only_yes_or_no() -> None:
    source = (REPO / "scripts" / "connect_servicenow_da.py").read_text(
        encoding="utf-8"
    )
    for match in re.finditer(r"option_labels=\[([^\]]*)\]", source):
        labels = re.findall(r'"([^"]+)"', match.group(1))
        for label in labels:
            assert label.lower() in SHORT_LABELS, label
    assert not re.search(r'"(?:Yes|No),\s', source)


def _load_hook(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_hook_lives_in_the_opened_workspace_folder() -> None:
    # The host loads repo hooks only from the opened folder's .github/hooks.
    # Makers open solutions/ess-maker-skills, so a hook that exists only at
    # the git root is listed but never runs (live run: no deny, no trace).
    workspace_hook = REPO / ".github" / "hooks" / "servicenow-connect-no-cards.json"
    assert workspace_hook.is_file()
    root_hook = REPO.parents[1] / ".github" / "hooks" / workspace_hook.name
    if root_hook.is_file():
        assert _load_hook(root_hook) == _load_hook(workspace_hook)


def test_hook_covers_every_card_tool_and_runs_the_guard() -> None:
    hook = _load_hook(
        REPO / ".github" / "hooks" / "servicenow-connect-no-cards.json"
    )
    entry = hook["hooks"]["preToolUse"][0]
    for tool in ("ask_user", "vscode_askQuestions", "AskUserQuestion"):
        assert re.search(entry["matcher"], tool)
    assert "servicenow_connect_card_guard.py" in entry["powershell"]
    assert "servicenow_connect_card_guard.py" in entry["bash"]
    # The hook must find the guard from the workspace folder and from the git
    # root, so it cannot depend on a relative working directory.
    assert "cwd" not in entry
    assert entry["powershell"].startswith("$p='scripts/servicenow_connect_card_guard.py'")
    for command in (entry["powershell"], entry["bash"]):
        assert "git rev-parse --show-toplevel" in command
        assert "solutions/ess-maker-skills/scripts/" in command


def test_entra_packet_message_ends_with_a_plain_reply_line() -> None:
    # Live run: the message ended in a code fence, so the agent added its own
    # "Entra administrator reply" card. The last thing the maker reads must be
    # a plain statement telling them to reply in chat.
    entra = snow.ENTRA_REPLY_CLOSING_TEXT
    assert entra.startswith("Paste their reply here in chat")
    assert "?" not in entra
    assert snow.has_wait_cue(entra)
    result = {
        "ordinaryReply": {
            "kind": "ordinary-agent-response",
            "text": (
                "Send this message.\n\n**Ready-to-send message**\n```text\n"
                f"body\n```\n\n{entra}"
            ),
        },
        "decision": "instructions-required",
    }
    out = _finish(result, "identity-direct-handoff")
    assert out["endTurn"] is True
    assert out["chatMessage"].rstrip().endswith(entra)


def test_every_chat_output_ends_with_the_card_ban_key() -> None:
    out = _finish(
        {"ordinaryReply": {"kind": "ordinary-agent-response", "text": "Hi."}},
        "identity-direct-handoff",
    )
    assert list(out)[-1] == "cardBan"
    assert "ask_user" in out["cardBan"]
    assert out["cardBan"] == snow.CARD_BAN_REMINDER


def test_entra_docs_do_not_describe_the_reply_as_a_prompt() -> None:
    skills = REPO / "src" / "skills" / "connect"
    for profile in ("servicenow-da-hrsd", "servicenow-da-itsm"):
        text = (
            skills / profile / "actions" / "guide-entra-registration.md"
        ).read_text(encoding="utf-8")
        assert "answers one prompt" not in text
        assert "replies in ordinary chat" in text


def test_card_guard_records_a_trace_line_per_call(tmp_path: Path) -> None:
    import servicenow_connect_card_guard as guard

    log_dir = Path(guard.__file__).resolve().parents[1] / ".local" / "connect"
    if not log_dir.is_dir():
        pytest.skip("no local connect folder to hold the trace")
    log = log_dir / "card-guard.log"
    before = log.read_text(encoding="utf-8") if log.is_file() else None
    try:
        guard._trace({"toolName": "ask_user"}, {"permissionDecision": "deny"})
        assert "tool=ask_user decision=deny" in log.read_text(encoding="utf-8")
    finally:
        if before is None:
            log.unlink(missing_ok=True)
        else:
            log.write_text(before, encoding="utf-8")


PORTAL_SPEC_QUESTION = (
    "What is the full HTTPS base URL of your ServiceNow employee portal? It "
    "may differ from the instance URL, so we won't assume `/sp` or `/esc`."
)


def _finish(result: dict, command: str) -> dict:
    return snow._with_agent_rules(snow.plain_text_output(result), command)


def test_portal_url_question_comes_from_the_controller_not_the_agent() -> None:
    for command, raw in (
        (
            "portal-reuse-handoff",
            {"schemaVersion": "x", "decision": "none", "candidates": []},
        ),
        (
            "portal-reuse-handoff",
            {
                "schemaVersion": "x",
                "decision": "already-recorded",
                "record": {"decision": "declined"},
            },
        ),
    ):
        wrapped = _finish(snow.portal_reuse_output(raw), command)
        _assert_no_card(wrapped)
        assert wrapped["endTurn"] is True
        assert "nextCommand" not in wrapped
        assert wrapped["chatMessage"].startswith(PORTAL_SPEC_QUESTION)
        assert "Reply here in chat with the URL." in wrapped["chatMessage"]
        assert wrapped["decision"] == raw["decision"]
        assert "portal-url-confirmation" in wrapped["nextStep"]


def test_portal_reuse_with_an_accepted_value_asks_nothing() -> None:
    accepted = {
        "schemaVersion": "x",
        "decision": "already-recorded",
        "record": {"decision": "accepted"},
    }
    assert snow.portal_reuse_output(accepted) == accepted


def test_unresolved_portal_inspection_points_at_the_reuse_check() -> None:
    result = snow.portal_inspect_output(
        {"status": "input-required", "input": {"field": "portalUrl"}}
    )
    assert "portal-reuse-handoff" in result["nextStep"]
    assert "question" not in result
    done = {"status": "configured", "input": None}
    assert snow.portal_inspect_output(done) == done


def test_portal_confirmation_is_a_plain_yes_no_then_saved_message() -> None:
    confirmation = {
        "schemaVersion": "servicenow.portal-url-confirmation.v1",
        "portalUrl": "https://dev123.service-now.com/esc",
        "header": "Confirm employee portal URL",
        "question": "Is **https://dev123.service-now.com/esc** the employee portal URL?",
        "options": [{"label": "Yes"}, {"label": "No"}],
        "allowFreeformInput": False,
        "savedMessage": "We'll save that portal URL.",
    }
    wrapped = _finish(snow.portal_confirmation_output(confirmation), "portal-url-confirmation")
    _assert_no_card(wrapped)
    assert wrapped["endTurn"] is True
    assert wrapped["chatMessage"] == (
        "Is **https://dev123.service-now.com/esc** the employee portal URL?"
        "\n\nReply **Yes** or **No**."
    )
    assert wrapped["portalUrl"] == "https://dev123.service-now.com/esc"
    assert wrapped["savedMessage"] == "We'll save that portal URL."


@pytest.mark.parametrize("profile", ["hrsd", "itsm"])
def test_portal_docs_use_the_spec_wording_and_the_saved_message(profile: str) -> None:
    doc = (
        CONNECT_DOCS
        / f"servicenow-da-{profile}"
        / "actions"
        / "configure-portal-url.md"
    ).read_text(encoding="utf-8")
    flat = " ".join(doc.split())
    assert PORTAL_SPEC_QUESTION in flat
    family = "HR" if profile == "hrsd" else "IT"
    assert (
        f"We'll save that portal URL and turn on the built-in ServiceNow {family} "
        "topics, including system topics. Unrelated topics will stay unchanged."
    ) in flat
    assert "Do not announce topic changes" not in flat
    assert "Never ask it yourself" in flat


def test_card_guard_denies_only_while_a_lifecycle_is_active(
    tmp_path: Path,
) -> None:
    import servicenow_connect_card_guard as guard

    marker = tmp_path / guard.MARKER_RELATIVE
    marker.parent.mkdir(parents=True)
    payload = {"toolName": "ask_user", "cwd": str(tmp_path)}

    marker.write_text(json.dumps({"updatedAt": 1000.0}), encoding="utf-8")
    denied = guard.decide(payload, now=1100.0)
    assert denied["permissionDecision"] == "deny"
    assert "plain text" in denied["permissionDecisionReason"]
    assert guard.decide({**payload, "toolName": "vscode_askQuestions"}, 1100.0)

    stale = 1000.0 + guard.MARKER_MAX_AGE_SECONDS + 1
    assert guard.decide(payload, now=stale) == {}
    assert guard.decide({**payload, "toolName": "run_in_terminal"}, 1100.0) == {}
    marker.write_text("not json", encoding="utf-8")
    assert guard.decide(payload, now=1100.0) == {}


def test_lifecycle_marker_is_written_per_command_and_removed_on_final(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".local" / "connect").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    marker = tmp_path / ".local" / "connect" / "servicenow-active.json"

    snow._record_lifecycle_marker({"renderBlock": {"kind": "plan"}}, "resume-handoff")
    assert marker.is_file()
    snow._record_lifecycle_marker({}, "match-reply")
    assert marker.is_file()
    snow._record_lifecycle_marker(
        {"renderBlock": {"kind": "final", "text": "Done."}}, "resume-handoff"
    )
    assert not marker.exists()


@pytest.mark.parametrize(
    "text",
    [
        "Return here and tell us which connection you used.",
        "Come back and tell us what happened.",
        "Reply **Yes** or **No**.",
        "Paste the value here.",
        "Let us know once you have it.",
        "Is the administrator available?",
    ],
)
def test_wait_cue_always_ends_the_turn(text: str) -> None:
    assert snow.has_wait_cue(text)
    wrapped = snow._with_agent_rules(
        {
            "provider": "servicenow-da-itsm",
            "agentSlug": "agent",
            "ordinaryReply": {"text": text},
            "action": {"decision": "read-action-doc", "actionDoc": "a.md"},
        },
        "resume-handoff",
    )
    assert wrapped["endTurn"] is True
    assert "nextCommand" not in wrapped
    assert "a.md" in wrapped["afterReply"]


@pytest.mark.parametrize("profile", ["hrsd", "itsm"])
def test_auto_continue_lead_ins_have_no_wait_cue(
    profile: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snow, "ACTIVE_AGENT_NAME", "ESS Agent")
    context = {
        "agent": {"id": "x", "workspace_slug": "agent"},
        "environment": {"id": "env", "display_name": "Contoso Dev"},
    }
    with snow.product_profile_context(profile):
        opening = snow._dev_opening_text(context, None)
    assert not snow.has_wait_cue(opening)
    wrapped = snow._with_agent_rules(
        {
            "provider": f"servicenow-da-{profile}",
            "agentSlug": "agent",
            "renderBlock": {"kind": "plan", "text": opening},
            "checkpoints": {
                "decision": "run-exact-commands",
                "commands": [{"command": "python scripts/flightcheck/cli.py"}],
            },
        },
        "resume-handoff",
    )
    assert wrapped["endTurn"] is False
    assert wrapped["nextCommand"]


PLAIN_BLOCK = re.compile(
    r"<!-- plain-chat-question:v1[^>]*-->\s*\*\*Message:\*\*(.*?)\*\*End message\.\*\*",
    re.S,
)


@pytest.mark.parametrize("provider", ["servicenow-da-hrsd", "servicenow-da-itsm"])
def test_every_plain_question_block_in_docs_has_a_wait_cue(provider: str) -> None:
    blocks = 0
    for path in (CONNECT_DOCS / provider).rglob("*.md"):
        for match in PLAIN_BLOCK.finditer(path.read_text(encoding="utf-8")):
            blocks += 1
            assert snow.has_wait_cue(match.group(1)), f"{path.name}: {match.group(1)[:60]}"
    assert blocks >= 5
