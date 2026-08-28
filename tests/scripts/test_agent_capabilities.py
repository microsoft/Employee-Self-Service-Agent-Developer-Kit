# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for ``list_agent_capabilities`` — the inventory probe the
``/harden`` skill uses before writing any rule about what an agent cannot do.

The rule this protects: never prohibit something the agent actually supports.
That check is only as good as the capability picture behind it, and the picture
has to come from somewhere cheaper than reading three dozen topic files, or it
gets skipped.

The load-bearing case is ``test_description_survives_non_yaml_topic``. Copilot
Studio topic files are *not* valid YAML — they contain unquoted ``@type:`` keys
— and the files that fail a strict parse are exactly the Workday and ServiceNow
integration topics whose descriptions matter most. A parser-based
implementation silently returns "no description" for them, which reads as "the
agent can't do this" and invites a prohibition on a supported action.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import list_agent_capabilities as inventory

_SKILL_ROOT = Path(inventory.__file__).resolve().parent.parent
_SCRIPT = _SKILL_ROOT / "scripts" / "list_agent_capabilities.py"
_AGENTS_DIR = _SKILL_ROOT / "workspace" / "agents"

_SENTINEL = "###AGENT_CAPABILITIES_JSON###"

# A topic shaped like a real generated integration topic: an unquoted "@type"
# nested in the body, which makes the file unparseable as strict YAML.
_NON_YAML_TOPIC = """\
kind: AdaptiveDialog
modelDescription: You will respond to requests about the base compensation of the user.
beginDialog:
  kind: OnRecognizedIntent
  actions:
    - kind: InvokeFlowAction
      input:
        binding:
          value:
            @type: String
"""

_REPLY_ONLY_TOPIC = """\
kind: AdaptiveDialog
modelDescription: |
  You will respond only to questions about parking.
  Do not answer anything else.
triggerQueries:
  - where do I park
  - parking policy
beginDialog:
  kind: OnRecognizedIntent
  actions:
    - kind: SendActivity
      activity: Here is the parking policy.
"""


@pytest.fixture
def temp_agent():
    """A throwaway agent with one acting topic, one reply-only topic, and one
    undecodable file. Lives under the gitignored workspace/agents/ tree."""
    name = f"_pytest_{uuid.uuid4().hex}"
    agent_dir = _AGENTS_DIR / name
    topics = agent_dir / "topics"
    topics.mkdir(parents=True)
    (agent_dir / "workflows").mkdir()

    (topics / "workday-get-basecompensation.mcs.yml").write_text(
        _NON_YAML_TOPIC, encoding="utf-8"
    )
    (topics / "parking.mcs.yml").write_text(_REPLY_ONLY_TOPIC, encoding="utf-8")
    (topics / "broken.mcs.yml").write_bytes(b"\xff\xfe\x00\x80\x81\xff")
    (agent_dir / "workflows" / "workday-abc123").mkdir()

    try:
        yield name
    finally:
        shutil.rmtree(agent_dir, ignore_errors=True)


def _run(*args) -> tuple[int, dict, str]:
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    combined = proc.stdout + proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith(_SENTINEL)]
    assert len(lines) == 1, f"expected one sentinel line, got {len(lines)}: {combined}"
    return proc.returncode, json.loads(lines[0][len(_SENTINEL):]), combined


def _topic(result: dict, filename: str) -> dict:
    match = [t for t in result["topics"] if t["file"] == filename]
    assert match, f"{filename} missing from inventory: {result['topics']}"
    return match[0]


def test_description_survives_non_yaml_topic(temp_agent):
    """The regression that motivates this probe: an unquoted `@type` must not
    cost us the topic's description."""
    _, result, combined = _run("--agent", temp_agent)
    topic = _topic(result, "workday-get-basecompensation.mcs.yml")

    assert topic["has_description"] is True
    assert "base compensation" in combined
    assert "error" not in topic


def test_acting_topics_are_distinguished_from_reply_only(temp_agent):
    """"Can answer about X" and "can do X" need different instruction rules, so
    the inventory has to tell them apart."""
    _, result, _ = _run("--agent", temp_agent)

    assert _topic(result, "workday-get-basecompensation.mcs.yml")["actions"] == ["flow"]
    assert _topic(result, "parking.mcs.yml")["actions"] == []


def test_block_scalar_description_and_triggers(temp_agent):
    _, _, combined = _run("--agent", temp_agent)

    assert (
        "You will respond only to questions about parking. Do not answer anything else."
        in combined
    )
    assert "triggers: where do I park; parking policy" in combined


def test_json_stays_compact(temp_agent):
    """Descriptions belong in the table, not duplicated into the JSON. On a
    real agent that duplication pushed the output past the caller's limit and
    the capability evidence was lost."""
    _, result, _ = _run("--agent", temp_agent)

    assert "description" not in result["topics"][0]
    assert set(result["topics"][0]) == {"file", "actions", "has_description"}


def test_unreadable_topic_is_disclosed(temp_agent):
    """A topic that could not be read is a hole in the capability picture. The
    caller is about to write prohibitions from that picture, so silence here
    would be worse than the missing data."""
    code, result, combined = _run("--agent", temp_agent)

    assert code == 0, combined
    assert "broken.mcs.yml" in result["unreadable"]
    assert result["coverage_complete"] is False
    assert "NOT analyzed" in combined
    assert "coverage is incomplete" in combined


def test_workflows_are_listed(temp_agent):
    _, result, _ = _run("--agent", temp_agent)
    assert result["workflows"] == ["workday-abc123"]


def test_long_descriptions_are_truncated(temp_agent):
    topics = _AGENTS_DIR / temp_agent / "topics"
    (topics / "verbose.mcs.yml").write_text(
        "kind: AdaptiveDialog\nmodelDescription: " + ("word " * 400) + "\n",
        encoding="utf-8",
    )
    _, _, combined = _run("--agent", temp_agent)

    description_line = [
        ln for ln in combined.splitlines() if ln.strip().startswith("word word")
    ]
    assert description_line, combined
    assert description_line[0].strip().endswith("...")
    assert len(description_line[0].strip()) <= inventory._MAX_DESCRIPTION + 8


def test_agent_accepts_slug_or_config_folder_path(temp_agent):
    _, by_slug, _ = _run("--agent", temp_agent)
    _, by_path, _ = _run("--agent", f"workspace/agents/{temp_agent}")
    assert by_slug["topic_count"] == by_path["topic_count"]


def test_missing_agent_is_reported(temp_agent):
    code, result, _ = _run("--agent", "_pytest_does_not_exist")
    assert code != 0
    assert "error" in result
