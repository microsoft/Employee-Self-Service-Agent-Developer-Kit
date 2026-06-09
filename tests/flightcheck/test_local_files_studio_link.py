# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the Copilot Studio deep-link helpers in
``flightcheck.checks.local_files``.

These pin the CONFIG-007 remediation behavior the user surfaced: when a
check fails, the remediation must point the user directly at the
specific agent in Copilot Studio so they know where to click.

URL shape (verified against a live tenant in conversation):
    https://copilotstudio.microsoft.com/environments/{envId}/bots/{botId}/overview
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _scripts_on_path():
    """Make `flightcheck.*` importable from the kit's scripts dir."""
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "solutions" / "ess-maker-skills" / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass


def _fake_runner(env_id="env-guid-123", agents=None, single_agent=None):
    config = {}
    if agents is not None:
        config["agents"] = agents
    if single_agent is not None:
        config["agent"] = single_agent
    return SimpleNamespace(env_id=env_id, config=config)


def test_deep_link_built_from_runner_env_id_and_matching_agent_slug():
    from flightcheck.checks.local_files import _studio_agent_url

    runner = _fake_runner(
        env_id="11111111-2222-3333-4444-555555555555",
        agents=[
            {"slug": "agent-a", "botId": "bot-a-id"},
            {"slug": "agent-b", "botId": "bot-b-id"},
        ],
    )

    url = _studio_agent_url(runner, "agent-b")

    assert url == (
        "https://copilotstudio.microsoft.com/"
        "environments/11111111-2222-3333-4444-555555555555/"
        "bots/bot-b-id/overview"
    )


def test_deep_link_falls_back_to_single_agent_shape_when_slug_not_in_agents():
    """Older configs only have a top-level "agent" key, no "agents" list."""
    from flightcheck.checks.local_files import _studio_agent_url

    runner = _fake_runner(
        env_id="env-1",
        single_agent={"slug": "legacy-agent", "botId": "legacy-bot-id"},
    )

    # agent_name doesn't match the single-agent slug, but the helper
    # falls back to the single-agent shape — that's the whole point of
    # the fallback, otherwise older configs always lose the deep link.
    url = _studio_agent_url(runner, "any-name")

    assert url == (
        "https://copilotstudio.microsoft.com/"
        "environments/env-1/bots/legacy-bot-id/overview"
    )


def test_deep_link_returns_none_when_env_id_missing():
    from flightcheck.checks.local_files import _studio_agent_url

    runner = _fake_runner(env_id=None, agents=[{"slug": "a", "botId": "b"}])

    assert _studio_agent_url(runner, "a") is None


def test_deep_link_returns_none_when_bot_id_not_findable():
    from flightcheck.checks.local_files import _studio_agent_url

    runner = _fake_runner(env_id="e", agents=[{"slug": "other", "botId": "x"}])

    assert _studio_agent_url(runner, "missing-agent") is None


def test_deep_link_returns_none_when_runner_is_none():
    from flightcheck.checks.local_files import _studio_agent_url

    assert _studio_agent_url(None, "any-agent") is None


def test_studio_link_md_uses_deep_link_when_available():
    from flightcheck.checks.local_files import _studio_link_md

    runner = _fake_runner(env_id="e1", agents=[{"slug": "a", "botId": "b1"}])

    md = _studio_link_md(runner, "a", "the agent")

    assert md == (
        "[the agent]("
        "https://copilotstudio.microsoft.com/"
        "environments/e1/bots/b1/overview)"
    )


def test_studio_link_md_falls_back_to_homepage_when_no_deep_link():
    """Failing softly to the homepage keeps the remediation actionable
    even when env_id or botId are missing (e.g. setup half-completed)."""
    from flightcheck.checks.local_files import _studio_link_md

    md = _studio_link_md(None, "", "Copilot Studio")

    assert md == "[Copilot Studio](https://copilotstudio.microsoft.com/)"


def test_config_007_missing_instructions_remediation_includes_deep_link(
    tmp_path: Path,
):
    """When CONFIG-007 fails with 'no instructions block', the
    remediation string must include the deep link so the user knows
    EXACTLY where to go in Copilot Studio."""
    from flightcheck.checks.local_files import _check_agent_identity

    agent_dir = tmp_path / "my-agent"
    agent_dir.mkdir()
    # agent.mcs.yml exists but has no instructions block at all
    (agent_dir / "agent.mcs.yml").write_text(
        "kind: AgentDefinition\nname: My Agent\n",
        encoding="utf-8",
    )

    runner = _fake_runner(
        env_id="env-007",
        agents=[{"slug": "my-agent", "botId": "bot-007"}],
    )

    results = _check_agent_identity(agent_dir, "My Agent", runner, "my-agent")

    # find the FAILED CONFIG-007 row for "Agent instructions"
    failed = [
        r for r in results
        if r.checkpoint_id == "CONFIG-007"
        and r.status == "Failed"
        and "instructions" in r.description.lower()
    ]
    assert len(failed) == 1, [r.__dict__ for r in results]

    remediation = failed[0].remediation or ""
    assert (
        "https://copilotstudio.microsoft.com/environments/env-007/"
        "bots/bot-007/overview"
    ) in remediation


def test_config_007_remediation_falls_back_when_runner_unavailable(
    tmp_path: Path,
):
    """No runner / missing config -> remediation still links somewhere
    (the homepage) rather than leaving the user without a link."""
    from flightcheck.checks.local_files import _check_agent_identity

    agent_dir = tmp_path / "my-agent"
    agent_dir.mkdir()
    (agent_dir / "agent.mcs.yml").write_text(
        "kind: AgentDefinition\nname: My Agent\n",
        encoding="utf-8",
    )

    results = _check_agent_identity(agent_dir, "My Agent", None, "")

    failed = [
        r for r in results
        if r.checkpoint_id == "CONFIG-007" and r.status == "Failed"
    ]
    assert len(failed) == 1
    assert "https://copilotstudio.microsoft.com/" in (failed[0].remediation or "")


# ---------------------------------------------------------------------------
# TOPIC-001..010 required-topic remediations must also deep-link to the
# specific agent. Pre-fix these all used the generic homepage URL because
# `_check_required_topics` never received the runner or the agent slug.
# This mirrors the CONFIG-007 pinning above for the topic checkpoints.
# ---------------------------------------------------------------------------


def test_topic_required_remediation_includes_deep_link_for_each_checkpoint(
    tmp_path: Path,
):
    """When a required topic is missing, each TOPIC-* WARNING row must
    point the user at the specific agent in Copilot Studio so they can
    open the Topics tab in one click instead of guessing."""
    from flightcheck.checks.local_files import _check_required_topics, REQUIRED_TOPICS

    agent_dir = tmp_path / "my-agent"
    (agent_dir / "topics").mkdir(parents=True)  # empty topics dir => every required topic missing

    runner = _fake_runner(
        env_id="env-topic",
        agents=[{"slug": "my-agent", "botId": "bot-topic"}],
    )

    results = _check_required_topics(agent_dir, "My Agent", runner, "my-agent")

    expected_deep_link = (
        "https://copilotstudio.microsoft.com/"
        "environments/env-topic/bots/bot-topic/overview"
    )

    # Every required topic should be WARNING (not found) and every WARNING
    # row should carry the deep link in its remediation. This pins all of
    # TOPIC-001/002/004/005/009/010 in one assertion.
    warnings = [r for r in results if r.status == "Warning"]
    assert len(warnings) == len(REQUIRED_TOPICS), [r.__dict__ for r in results]
    for row in warnings:
        assert expected_deep_link in (row.remediation or ""), row.__dict__


def test_topic_required_remediation_falls_back_when_runner_unavailable(
    tmp_path: Path,
):
    """Half-completed setup must not strip the link entirely; the
    homepage URL is the documented fallback."""
    from flightcheck.checks.local_files import _check_required_topics

    agent_dir = tmp_path / "my-agent"
    (agent_dir / "topics").mkdir(parents=True)

    results = _check_required_topics(agent_dir, "My Agent", None, "")

    warnings = [r for r in results if r.status == "Warning"]
    assert warnings, results
    for row in warnings:
        assert "https://copilotstudio.microsoft.com/" in (row.remediation or "")


# ---------------------------------------------------------------------------
# Positive case: an agent that ships the real OOTB ESS template files must
# PASS every required topic. Pre-fix this scenario reported all six as
# WARNING because the patterns (``responsepreparation``) were matched
# against raw hyphenated filenames (``response-preparation.mcs.yml``) which
# can never satisfy a substring search. Bug surfaced by the user running
# FlightCheck against an `ESS_HR_WDAY_ONLY_OAUTH` extract that clearly had
# the [System] Response Preparation topic in Copilot Studio.
# ---------------------------------------------------------------------------


# Real filenames from solutions/ess-maker-skills/workspace/agents/<slug>/topics/
# after running /setup against an OOTB ESS Workday template. Picked the
# minimal set that covers each REQUIRED_TOPICS entry's expected match.
_OOTB_TOPIC_FILENAMES = [
    "user-context-setup.mcs.yml",                         # TOPIC-001
    "response-preparation.mcs.yml",                       # TOPIC-002
    "sensitive-topics.mcs.yml",                           # TOPIC-004
    "on-error.mcs.yml",                                   # TOPIC-005
    "seek-emotional-intelligence-response.mcs.yml",       # TOPIC-009
    "seek-clarification-to-avoid-ambiguous-answers.mcs.yml",  # TOPIC-010
]


def test_required_topics_recognize_real_ootb_ess_filenames(tmp_path: Path):
    """Each REQUIRED_TOPICS entry must match the actual ESS template
    filename via the normalize-then-substring rule. This pins the
    matcher against the OOTB Workday extract so the bug from the user's
    live run (TOPIC-002 false-positive WARNING on a topic that was
    visibly present in Copilot Studio) cannot regress."""
    from flightcheck.checks.local_files import _check_required_topics, REQUIRED_TOPICS

    agent_dir = tmp_path / "my-agent"
    topics = agent_dir / "topics"
    topics.mkdir(parents=True)
    for name in _OOTB_TOPIC_FILENAMES:
        # A minimal AdaptiveDialog body is enough — the matcher must NOT
        # depend on body content (which never carried the schema name).
        (topics / name).write_text("kind: AdaptiveDialog\n", encoding="utf-8")

    results = _check_required_topics(agent_dir, "My Agent", None, "")

    by_id = {r.checkpoint_id: r for r in results}
    assert len(by_id) == len(REQUIRED_TOPICS), [r.__dict__ for r in results]
    for req in REQUIRED_TOPICS:
        row = by_id[req["id"]]
        assert row.status == "Passed", (
            f"{req['id']} ({req['pattern']!r}) should match OOTB filenames "
            f"but got {row.status}: {row.result!r}"
        )


def test_required_topics_do_not_match_unrelated_topics(tmp_path: Path):
    """An agent that has only unrelated topics must still WARN on every
    required entry. Guards against over-broad patterns matching random
    topics by accident after the body-scan removal."""
    from flightcheck.checks.local_files import _check_required_topics, REQUIRED_TOPICS

    agent_dir = tmp_path / "my-agent"
    topics = agent_dir / "topics"
    topics.mkdir(parents=True)
    # None of these names contain any of the required-topic patterns.
    for name in ["greeting.mcs.yml", "fallback.mcs.yml", "echo.mcs.yml"]:
        (topics / name).write_text("kind: AdaptiveDialog\n", encoding="utf-8")

    results = _check_required_topics(agent_dir, "My Agent", None, "")

    by_id = {r.checkpoint_id: r for r in results}
    for req in REQUIRED_TOPICS:
        assert by_id[req["id"]].status == "Warning", by_id[req["id"]].__dict__


# ---------------------------------------------------------------------------
# CONFIG-014 (topic description quality) remediations historically had no
# Copilot Studio link at all, even though `_check_topic_descriptions` already
# received the runner. These tests pin the deep link on both failure modes.
# ---------------------------------------------------------------------------


def _placeholder_topic_yaml() -> str:
    # modelDescription contains a bracketed placeholder marker — must trip
    # _PLACEHOLDER_PATTERNS_INSENSITIVE and produce CONFIG-014 FAILED.
    return (
        "kind: AdaptiveDialog\n"
        "modelDisplayName: My Placeholder Topic\n"
        "modelDescription: '[Describe this topic here]'\n"
    )


def _too_short_topic_yaml() -> str:
    # 5 words << _MIN_DESCRIPTION_WORDS (20) and no placeholder markers.
    return (
        "kind: AdaptiveDialog\n"
        "modelDisplayName: My Short Topic\n"
        "modelDescription: 'one two three four five'\n"
    )


def test_config_014_placeholder_remediation_includes_deep_link(tmp_path: Path):
    from flightcheck.checks.local_files import _check_topic_descriptions

    agent_dir = tmp_path / "my-agent"
    (agent_dir / "topics").mkdir(parents=True)
    (agent_dir / "topics" / "my-topic.mcs.yml").write_text(
        _placeholder_topic_yaml(), encoding="utf-8"
    )

    runner = _fake_runner(
        env_id="env-014",
        agents=[{"slug": "my-agent", "botId": "bot-014"}],
    )

    results = _check_topic_descriptions(agent_dir, "My Agent", runner, "my-agent")

    failed = [
        r for r in results
        if r.checkpoint_id == "CONFIG-014" and r.status == "Failed"
    ]
    assert len(failed) == 1, [r.__dict__ for r in results]
    assert (
        "https://copilotstudio.microsoft.com/environments/env-014/"
        "bots/bot-014/overview"
    ) in (failed[0].remediation or "")


def test_config_014_too_short_remediation_includes_deep_link(tmp_path: Path):
    from flightcheck.checks.local_files import _check_topic_descriptions

    agent_dir = tmp_path / "my-agent"
    (agent_dir / "topics").mkdir(parents=True)
    (agent_dir / "topics" / "my-topic.mcs.yml").write_text(
        _too_short_topic_yaml(), encoding="utf-8"
    )

    runner = _fake_runner(
        env_id="env-014",
        agents=[{"slug": "my-agent", "botId": "bot-014"}],
    )

    results = _check_topic_descriptions(agent_dir, "My Agent", runner, "my-agent")

    warnings = [
        r for r in results
        if r.checkpoint_id == "CONFIG-014" and r.status == "Warning"
    ]
    assert len(warnings) == 1, [r.__dict__ for r in results]
    assert (
        "https://copilotstudio.microsoft.com/environments/env-014/"
        "bots/bot-014/overview"
    ) in (warnings[0].remediation or "")


# ---------------------------------------------------------------------------
# CONFIG-013 (knowledge source readiness) remediations had no deep link
# either. The API-error branch is the easiest to exercise without standing
# up a fake Island Gateway response stream — the rest of the branches go
# through the same shared `studio_link`, so pinning the auth-failure path
# is sufficient to prove the runner+agent_name plumbing reached the call.
# ---------------------------------------------------------------------------


def test_config_013_api_failure_remediation_includes_deep_link(tmp_path: Path):
    from flightcheck.checks.local_files import _check_knowledge_sources

    agent_dir = tmp_path / "my-agent"
    (agent_dir / "knowledge").mkdir(parents=True)
    (agent_dir / "knowledge" / "src.mcs.yml").write_text("kind: KnowledgeSource\n", encoding="utf-8")

    class _ExplodingPVA:
        is_configured = True
        def get_knowledge_sources(self, _bot_id):
            raise RuntimeError("boom")

    runner = SimpleNamespace(
        env_id="env-013",
        config={
            "agent": {"botId": "bot-013"},
            "agents": [{"slug": "my-agent", "botId": "bot-013"}],
        },
        pva=_ExplodingPVA(),
    )

    results = _check_knowledge_sources(agent_dir, "My Agent", runner, "my-agent")

    warnings = [
        r for r in results
        if r.checkpoint_id == "CONFIG-013" and r.status == "Warning"
    ]
    assert len(warnings) == 1, [r.__dict__ for r in results]
    assert (
        "https://copilotstudio.microsoft.com/environments/env-013/"
        "bots/bot-013/overview"
    ) in (warnings[0].remediation or "")


# ---------------------------------------------------------------------------
# CONFIG-014 parse-error behavior:
#   - Copilot Studio's topic exporter emits unquoted `@type` / `#text` keys
#     for XML/XSD-defined connector actions (Workday SOAP, etc). These are
#     reserved YAML 1.2 indicators that PyYAML correctly refuses. The maker
#     can't fix this — the file came verbatim from Copilot Studio — and
#     editing locally would be overwritten on the next `/scan`.
#   - `_check_topic_descriptions` salvages such files (re-quotes the keys
#     in a copy, never on disk) so the real check — modelDescription
#     quality — still runs.
#   - If salvage doesn't help (a genuinely-broken file the maker actually
#     authored or some other Copilot Studio quirk we haven't seen), the
#     row drops to a low-priority Skipped row that explains the file is
#     a Copilot Studio export, NOT a "fix your YAML" lecture.
# ---------------------------------------------------------------------------


def _workday_style_topic_yaml(model_description: str = "Routes Workday government identification lookups including social security numbers, national insurance numbers, passport numbers, and other government-issued identifiers when the employee asks about their on-file IDs.") -> str:
    """Mimics the Copilot Studio export shape that breaks PyYAML.

    Uses the same `@type` / `#text` XML-attribute-style keys we see in the
    kit's own samples/WorkdayCustomEngineAgent/Employee/* topic files.
    The default description is intentionally over the 20-word minimum so
    salvaged-and-parsed cases land in Passed instead of too-short Warning.
    """
    return (
        "kind: AdaptiveDialog\n"
        "modelDisplayName: Workday Get Government IDs\n"
        # Quote the description so callers can pass placeholders containing
        # ``:`` (e.g. ``TODO: ...``) without re-breaking the YAML parse.
        f'modelDescription: "{model_description}"\n'
        "beginDialog:\n"
        "  actions:\n"
        "    - kind: SendActivity\n"
        "      schema:\n"
        "        properties:\n"
        "          @type: String\n"
        '          "#text": String\n'
    )


def _truly_broken_topic_yaml() -> str:
    """A YAML file that's bad in a way the salvage rewrite can't help with.

    A tab character used for indentation triggers a ScannerError that has
    nothing to do with the `@`/`#` quoting issue, so the salvage pass
    leaves it alone and the file ends up on the unparseable list.
    """
    return (
        "kind: AdaptiveDialog\n"
        "modelDisplayName: Broken Topic\n"
        "beginDialog:\n"
        "\tactions:\n"  # tab indent — triggers ScannerError, salvage no-op
        "    - kind: SendActivity\n"
    )


def test_salvage_xml_attribute_yaml_quotes_at_and_hash_keys():
    """Unit test for the salvage helper itself — must quote both `@key:`
    and `#key:` patterns at the start of mapping lines, and only those."""
    from flightcheck.checks.local_files import _salvage_xml_attribute_yaml

    raw = (
        "outer:\n"
        "  @type: String\n"
        "  #text: Value\n"
        "  @complex_name.v1: Foo\n"
        "  normalKey: hello @at and #hash in value\n"  # in-value, must NOT touch
        "  # an actual YAML comment, must NOT touch\n"
    )
    out = _salvage_xml_attribute_yaml(raw)
    assert '"@type":' in out
    assert '"#text":' in out
    assert '"@complex_name.v1":' in out
    # Values that happen to contain @ or # are left alone.
    assert "hello @at and #hash in value" in out
    # Real comment lines (`#` followed by a space, not key syntax) untouched.
    assert "# an actual YAML comment" in out


def test_config_014_workday_style_topic_is_salvaged_and_check_runs(tmp_path: Path):
    """A Workday-style topic with unquoted `@type` / `#text` keys must
    NOT show up as a YAML parse error — the salvage step lets us inspect
    the modelDescription and run the real check."""
    from flightcheck.checks.local_files import _check_topic_descriptions

    agent_dir = tmp_path / "my-agent"
    (agent_dir / "topics").mkdir(parents=True)
    (agent_dir / "topics" / "workday-get-governmentids.mcs.yml").write_text(
        _workday_style_topic_yaml(), encoding="utf-8"
    )

    results = _check_topic_descriptions(agent_dir, "My Agent")

    # No Skipped-unparseable row should be emitted — the salvage worked.
    skipped = [
        r for r in results
        if r.checkpoint_id == "CONFIG-014" and r.status == "Skipped"
        and "unparseable" in (r.description or "").lower()
    ]
    assert not skipped, [r.description for r in skipped]
    # The description-quality check should have run and PASSED (the
    # description in the helper is long and contains no placeholders).
    passed = [r for r in results if r.checkpoint_id == "CONFIG-014" and r.status == "Passed"]
    assert passed, [(r.status, r.description) for r in results]


def test_config_014_salvaged_topic_still_flags_placeholder_description(tmp_path: Path):
    """Salvage must preserve the description-quality signal: a Workday-
    style topic whose modelDescription is a placeholder must still be
    flagged as such, NOT lost to a parse-error skip."""
    from flightcheck.checks.local_files import _check_topic_descriptions

    agent_dir = tmp_path / "my-agent"
    (agent_dir / "topics").mkdir(parents=True)
    (agent_dir / "topics" / "workday-broken-desc.mcs.yml").write_text(
        _workday_style_topic_yaml(model_description="TODO: fill this in"),
        encoding="utf-8",
    )

    results = _check_topic_descriptions(agent_dir, "My Agent")
    failed = [
        r for r in results
        if r.checkpoint_id == "CONFIG-014" and r.status == "Failed"
        and "placeholder" in (r.description or "").lower()
    ]
    assert failed, [(r.status, r.description, r.result) for r in results]


def test_config_014_salvage_does_not_mutate_file_on_disk(tmp_path: Path):
    """Salvage must operate on an in-memory copy only. The on-disk file
    must come back byte-identical so a subsequent `/push` doesn't try to
    re-upload a flightcheck-edited version to Copilot Studio."""
    from flightcheck.checks.local_files import _check_topic_descriptions

    agent_dir = tmp_path / "my-agent"
    (agent_dir / "topics").mkdir(parents=True)
    topic_path = agent_dir / "topics" / "workday.mcs.yml"
    original = _workday_style_topic_yaml()
    topic_path.write_text(original, encoding="utf-8")

    _check_topic_descriptions(agent_dir, "My Agent")

    assert topic_path.read_text(encoding="utf-8") == original


def test_config_014_truly_unparseable_file_becomes_low_priority_skipped(tmp_path: Path):
    """When salvage can't help (file is broken in a way unrelated to the
    `@`/`#` quirk), the row must be Skipped/Low, not Warning/Medium.
    Anything stronger would re-introduce the original false-positive
    noise for the dominant Copilot-Studio-export case."""
    from flightcheck.checks.local_files import _check_topic_descriptions

    agent_dir = tmp_path / "my-agent"
    (agent_dir / "topics").mkdir(parents=True)
    (agent_dir / "topics" / "really-broken.mcs.yml").write_text(
        _truly_broken_topic_yaml(), encoding="utf-8"
    )

    results = _check_topic_descriptions(agent_dir, "My Agent")
    unparseable = [
        r for r in results
        if r.checkpoint_id == "CONFIG-014"
        and "unparseable" in (r.description or "").lower()
    ]
    assert len(unparseable) == 1, [(r.status, r.description) for r in results]
    row = unparseable[0]
    assert row.status == "Skipped", row.status
    assert row.priority == "Low", row.priority
    # The file name must appear so the operator can locate it.
    assert "really-broken.mcs.yml" in row.result, row.result


def test_config_014_unparseable_row_does_not_lecture_about_yaml_syntax(tmp_path: Path):
    """The previous remediation told the maker to open the file and fix
    YAML syntax. For Copilot-Studio-exported content the maker has no way
    to do that. The new remediation must point at Copilot Studio's Code
    editor and the `/scan` workflow instead, and must NOT recommend
    hand-editing the local YAML."""
    from flightcheck.checks.local_files import _check_topic_descriptions

    agent_dir = tmp_path / "my-agent"
    (agent_dir / "topics").mkdir(parents=True)
    (agent_dir / "topics" / "x.mcs.yml").write_text(
        _truly_broken_topic_yaml(), encoding="utf-8"
    )

    results = _check_topic_descriptions(agent_dir, "My Agent")
    row = next(
        r for r in results
        if r.checkpoint_id == "CONFIG-014"
        and "unparseable" in (r.description or "").lower()
    )
    rem = (row.remediation or "").lower()
    assert "copilot studio" in rem
    assert "code editor" in rem
    assert "/scan" in rem
    # Old remediation text MUST be gone — it gave wrong advice for the
    # dominant case (Copilot Studio export).
    assert "fix the yaml syntax" not in rem
    assert "yaml.safe_load" not in rem
    assert "red hat" not in rem


def test_config_014_unparseable_row_caps_long_listings_at_ten(tmp_path: Path):
    """Many genuinely-broken files (rare, but possible in a kit-bug
    scenario) must not flood the report. Cap at 10 file names with a
    `+N more` overflow indicator."""
    from flightcheck.checks.local_files import _check_topic_descriptions

    agent_dir = tmp_path / "my-agent"
    (agent_dir / "topics").mkdir(parents=True)
    for i in range(13):
        (agent_dir / "topics" / f"broken-{i:02d}.mcs.yml").write_text(
            _truly_broken_topic_yaml(), encoding="utf-8"
        )

    results = _check_topic_descriptions(agent_dir, "My Agent")
    row = next(
        r for r in results
        if r.checkpoint_id == "CONFIG-014"
        and "unparseable" in (r.description or "").lower()
    )
    # Honest total in the count.
    assert "13 topic file(s)" in row.result, row.result
    # Overflow indicator present.
    assert "+3 more" in row.result, row.result
    # Only 10 file names listed in detail.
    listed = row.result.count("broken-")
    assert listed == 10, f"Expected 10 names, found {listed}: {row.result}"
