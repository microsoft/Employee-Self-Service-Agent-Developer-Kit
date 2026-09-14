"""Semantic (LLM-driven) pass over an agent's instructions.

Runs the INSTR-0xx rule pack (``instruction-rules.md``) against instruction
text via an LLM call and returns findings in the same shape the regex pass
uses (``instruction_engine.models.Finding``, with ``source="semantic"``).

The LLM invocation mechanism mirrors ``evaluate_evals.py``'s Copilot judge:
GitHub Copilot's chat completions API, authenticated via ``gh auth token``.
No extra API keys or setup — reuses credentials already required to work in
this repo.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from ..models import Finding

_RULES_PATH = Path(__file__).resolve().parent / "instruction-rules.md"
_MODELS_API_URL = "https://api.githubcopilot.com/chat/completions"

_SYSTEM_PROMPT = (
    "You are an expert reviewer of AI agent system instructions, applying "
    "the INSTR-0xx rule pack you are given. Be precise and conservative: "
    "only report a finding you can anchor to a specific quoted sentence (or, "
    "for absence-based rules, a specific unconstrained behavior). Always "
    "respond with valid JSON matching the schema in the prompt — no prose, "
    "no markdown fences."
)

_RESPONSE_SCHEMA_HINT = """
Respond with a JSON array of findings. Each finding is an object:

{
  "id": "INSTR-0xx",
  "severity": "error" | "warn" | "review",
  "category": "contradiction" | "ungrounded-response" | "over-commitment" | "over-restriction",
  "section": "<section name the anchor sentence lives in, or '(document)'>",
  "anchor": "<the exact sentence quoted from the instructions this finding is tied to>",
  "message": "<plain-language description of the problem>",
  "suggestion": "<line-level fix, or null if none>"
}

If there are no findings, respond with an empty JSON array: []
"""


class SemanticRunnerError(RuntimeError):
    """Raised when the LLM call or its response cannot be used."""


def get_gh_token() -> str:
    """Get the current GitHub token via ``gh auth token``."""
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError as e:
        raise SemanticRunnerError(
            "'gh' CLI not found. Install it from https://cli.github.com/"
        ) from e
    if result.returncode != 0:
        err = (result.stderr or "").strip()
        raise SemanticRunnerError(f"'gh auth token' failed (exit {result.returncode}). {err}")
    token = result.stdout.strip()
    if not token:
        raise SemanticRunnerError("gh auth token returned empty. Run 'gh auth login' first.")
    return token


def default_llm_client(prompt: str) -> str:
    """Call the Copilot chat completions API and return the raw response text."""
    token = get_gh_token()
    payload = {
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 4000,
        "temperature": 0.0,
    }
    req = urllib.request.Request(
        _MODELS_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Copilot-Integration-Id": "copilot-chat",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            choice = body["choices"][0]
            if choice.get("finish_reason") == "length":
                raise SemanticRunnerError(
                    "Model response was truncated (finish_reason=length); "
                    "instructions may be too large for one call."
                )
            return choice["message"]["content"]
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise SemanticRunnerError(f"Copilot API returned {e.code}: {err_body}") from e
    except urllib.error.URLError as e:
        raise SemanticRunnerError(f"Could not reach Copilot API: {e.reason}") from e


def _strip_code_fences(text: str) -> str:
    clean = text.strip()
    if clean.startswith("```"):
        clean = "\n".join(clean.split("\n")[1:])
    if clean.endswith("```"):
        clean = "\n".join(clean.split("\n")[:-1])
    return clean.strip()


def build_prompt(instructions_text: str, rule_pack_text: str, scope_hint: Optional[str] = None) -> str:
    scope_block = f"\nFocus only on findings relevant to: {scope_hint}\n" if scope_hint else ""
    return (
        f"## Rule pack\n\n{rule_pack_text}\n\n"
        f"## Agent instructions to review\n\n{instructions_text}\n"
        f"{scope_block}\n"
        f"{_RESPONSE_SCHEMA_HINT}"
    )


def _finding_from_json(obj: dict) -> Finding:
    return Finding(
        id=obj["id"],
        severity=obj["severity"],
        category=obj.get("category", "semantic"),
        section=obj.get("section", "(document)"),
        line=0,
        message=obj["message"],
        suggestion=obj.get("suggestion") or "",
        source="semantic",
    )


def run_semantic_pass(
    instructions_text: str,
    rule_pack_text: Optional[str] = None,
    scope_hint: Optional[str] = None,
    llm_client: Optional[Callable[[str], str]] = None,
) -> list[Finding]:
    """Run the semantic (INSTR-0xx) pass over ``instructions_text``.

    ``llm_client`` defaults to ``default_llm_client`` (a real Copilot API
    call); pass a stub for tests.
    """
    rule_pack_text = rule_pack_text if rule_pack_text is not None else _RULES_PATH.read_text(encoding="utf-8")
    llm_client = llm_client or default_llm_client

    prompt = build_prompt(instructions_text, rule_pack_text, scope_hint)
    raw_response = llm_client(prompt)
    clean = _strip_code_fences(raw_response)

    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError as e:
        raise SemanticRunnerError(f"Could not parse semantic pass response as JSON: {e}\nRaw: {raw_response}") from e

    if not isinstance(parsed, list):
        raise SemanticRunnerError(f"Expected a JSON array of findings, got: {type(parsed).__name__}")

    return [_finding_from_json(item) for item in parsed]
