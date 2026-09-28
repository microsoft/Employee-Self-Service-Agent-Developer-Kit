"""A minimal GitHub Copilot API client, mirroring the ADK's eval judge.

The ESS Maker Kit already reaches a model in exactly one place — its evaluation
judge (``solutions/ess-maker-skills/scripts/evaluate_evals.py``) — by POSTing to
the Copilot Models API and authenticating with ``gh auth token``. That path needs
no API keys, endpoints, or extra setup: the maker already has ``gh`` and a Copilot
entitlement to run the kit. This module reuses the same contract so instruction
migration ships no secrets and keeps one auth story across the whole kit.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request

MODELS_API_URL = "https://api.githubcopilot.com/chat/completions"


class LlmUnavailable(RuntimeError):
    """The Copilot API could not be reached or authenticated.

    Raised instead of exiting so callers can degrade gracefully — a migration that
    cannot reach the model still produces a package; it just leaves the instruction
    edit for a human rather than crashing the whole run.
    """


def gh_token() -> str:
    """The current GitHub token from ``gh auth token``.

    Raises :class:`LlmUnavailable` (never exits) when ``gh`` is missing or the maker
    is not signed in, so the migration can fall back rather than abort.
    """
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError as error:
        raise LlmUnavailable(
            "'gh' CLI not found. Install it from https://cli.github.com/ "
            "and run 'gh auth login'."
        ) from error
    except subprocess.TimeoutExpired as error:
        raise LlmUnavailable("'gh auth token' timed out.") from error

    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        detail = (result.stderr or "").strip()
        raise LlmUnavailable(
            f"'gh auth token' failed; run 'gh auth login'. {detail}".strip()
        )
    return token


def complete(
    system: str,
    user: str,
    *,
    max_tokens: int = 4000,
    temperature: float = 0.2,
) -> str:
    """Return the model's reply to a system+user prompt via the Copilot API.

    No model is named, deliberately: the Copilot API uses the account's plan
    default, which avoids failures on Business/Enterprise accounts that restrict
    specific models (the same choice the ADK's eval judge makes).
    """
    token = gh_token()
    payload = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    request = urllib.request.Request(
        MODELS_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Copilot-Integration-Id": "copilot-chat",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise LlmUnavailable(f"Copilot API returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise LlmUnavailable(f"Copilot API could not be reached: {error.reason}") from error

    try:
        choice = body["choices"][0]
        if choice.get("finish_reason") == "length":
            raise LlmUnavailable(
                "Copilot API response was truncated (finish_reason=length)."
            )
        return str(choice["message"]["content"])
    except (KeyError, IndexError, TypeError) as error:
        raise LlmUnavailable(f"Copilot API returned an unexpected shape: {body!r}") from error
