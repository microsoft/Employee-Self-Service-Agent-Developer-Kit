# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only inspection of a cloud flow's run history (Flow Management API).

The decisive "why" surface for flow-backed / connector-path bugs: did the
connector actually get called, which action failed, did the failure branch fire,
and why is the reply a generic error. Neither the bot reply nor the flow source
alone reveals this — the per-action run view does.

This module is read-only. It performs plain HTTPS GETs against the Flow
Management API to list a flow's runs and read one run's per-action cascade. It
never creates, patches, invokes, or deletes anything, which keeps its trust
surface tiny: a developer reads their own flow's run history in their own
environment.

Token: callers pass a Flow Management API bearer token
(resource ``https://service.flow.microsoft.com/``). Acquisition is intentionally
left to the caller — the maker kit's Dataverse MSAL flow targets a different
audience, so a Flow-scoped token is a separate concern (see the module's
companion skill-doc / follow-up).

Two layers:
  * The GET helpers (``get_latest_run`` / ``get_run_by_id`` / ``get_run_actions``)
    are thin REST reads.
  * ``summarize_actions`` is a pure interpreter over an already-fetched action
    list, producing the ``{name, status, statusCode}`` cascade a caller (agentic
    or human) reasons about. It is the offline-testable consumer contract.
"""
from __future__ import annotations

import logging
import re
import time

import requests

from http_errors import raise_api_error

logger = logging.getLogger(__name__)


def load_config():
    """Load the active agent's ``.local/config.json`` (lazy ``auth`` import).

    Wrapped at module scope — rather than a top-level ``from auth import`` — so
    tests can substitute it and so importing this read-only module never drags in
    ``auth`` (and its MSAL dependency) or risks an import cycle.
    """
    from auth import load_config as _load_config
    return _load_config()

_FLOW_API_HOST = "https://api.flow.microsoft.com"
API_TIMEOUT_SECONDS = 30
_GUID_NODASH_RE = re.compile(r"^[0-9a-fA-F]{32}$")
# Flow run ids are GUIDs or opaque alphanumeric tokens; anything outside this set
# (path/query separators, whitespace) could reshape the request path.
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_https_url(url: str) -> None:
    """Reject non-https URLs — sending a bearer token over cleartext is unacceptable."""
    if not url.lower().startswith("https://"):
        raise ValueError(
            f"url must use https:// (got: {url!r}). Refusing to send a bearer "
            "token over an unencrypted channel."
        )


_RETRY_STATUSES = (429, 500, 502, 503, 504)
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.0


def _get_json(url: str, *, headers: dict) -> requests.Response:
    """GET with a bounded retry on transient throttling / 5xx.

    The run-history reads are the decisive diagnostic surface, so a 429 or a
    transient 5xx should back off and retry rather than fail the whole dump. A
    4xx other than 429 is a real error and returned immediately for the caller's
    ``raise_api_error`` to handle.
    """
    _validate_https_url(url)
    resp = None
    for attempt in range(_RETRY_ATTEMPTS):
        resp = requests.get(url, headers=headers, timeout=API_TIMEOUT_SECONDS)
        if resp.status_code not in _RETRY_STATUSES or attempt == _RETRY_ATTEMPTS - 1:
            return resp
        time.sleep(_RETRY_BASE_DELAY * (2 ** attempt))
    return resp


def _validate_guid_nodashes(value: str, *, name: str = "value") -> str:
    """Raise ValueError unless ``value`` (with dashes stripped) is 32 hex chars.

    Guards the environment and flow ids that are interpolated into the request
    URL, so a malformed or injected value can't reshape the path.
    """
    no_dashes = value.replace("-", "") if isinstance(value, str) else ""
    if not _GUID_NODASH_RE.match(no_dashes):
        raise ValueError(
            f"{name} must be a GUID (32 hex chars after stripping dashes); got: {value!r}"
        )
    return no_dashes


def _validate_run_id(value: str) -> str:
    """Raise ValueError unless ``value`` is a safe run-id token.

    Guards the run id interpolated into the request path so a value carrying a
    path/query separator can't reshape the URL.
    """
    if not (isinstance(value, str) and _RUN_ID_RE.match(value)):
        raise ValueError(
            f"run_id must be an alphanumeric token (got: {value!r})"
        )
    return value


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def get_latest_run(environment: str, flow_id: str, token: str) -> dict | None:
    """Return the most recent run for a flow, or None if it has never run."""
    _validate_guid_nodashes(environment, name="environment")
    _validate_guid_nodashes(flow_id, name="flow_id")
    url = (
        f"{_FLOW_API_HOST}/providers/Microsoft.ProcessSimple/environments/"
        f"{environment}/flows/{flow_id}/runs?api-version=2016-11-01&$top=1"
    )
    resp = _get_json(url, headers=_auth_headers(token))
    raise_api_error(resp, resource_name="cloud flows", operation="read")
    runs = resp.json().get("value", [])
    return runs[0] if runs else None


def get_run_by_id(environment: str, flow_id: str, run_id: str, token: str) -> dict | None:
    """Return a specific run by id. Returns None if the run is gone (404)."""
    _validate_guid_nodashes(environment, name="environment")
    _validate_guid_nodashes(flow_id, name="flow_id")
    _validate_run_id(run_id)
    url = (
        f"{_FLOW_API_HOST}/providers/Microsoft.ProcessSimple/environments/"
        f"{environment}/flows/{flow_id}/runs/{run_id}?api-version=2016-11-01"
    )
    resp = _get_json(url, headers=_auth_headers(token))
    if resp.status_code == 404:
        return None
    raise_api_error(resp, resource_name="cloud flows", operation="read")
    return resp.json()


def get_run_actions(environment: str, flow_id: str, run_id: str, token: str) -> list[dict]:
    """Return a run's actions as ``[{name, status, outputs}]``.

    ``status`` is the per-action run status (Succeeded / Skipped / Failed /
    TimedOut / Cancelled). ``outputs`` is fetched via the action's anonymous SAS
    ``outputsLink`` when present (that is where a connector action's
    ``statusCode`` lives); a SAS fetch failure is logged and leaves ``outputs``
    as None rather than aborting the whole dump.

    Inputs are intentionally not fetched — the consumer contract
    (``summarize_actions``) needs only status + statusCode, and skipping the
    extra SAS reads keeps the surface minimal.
    """
    _validate_guid_nodashes(environment, name="environment")
    _validate_guid_nodashes(flow_id, name="flow_id")
    _validate_run_id(run_id)
    url = (
        f"{_FLOW_API_HOST}/providers/Microsoft.ProcessSimple/environments/"
        f"{environment}/flows/{flow_id}/runs/{run_id}/actions?api-version=2016-11-01"
    )
    resp = _get_json(url, headers=_auth_headers(token))
    raise_api_error(resp, resource_name="cloud flows", operation="read")

    actions: list[dict] = []
    for action in resp.json().get("value", []):
        entry = {
            "name": action["name"],
            "status": action["properties"]["status"],
            "outputs": None,
        }
        outputs_uri = action["properties"].get("outputsLink", {}).get("uri")
        if outputs_uri:
            try:
                out_resp = requests.get(outputs_uri, timeout=API_TIMEOUT_SECONDS)
                if out_resp.status_code == 200:
                    entry["outputs"] = out_resp.json()
                else:
                    logger.warning(
                        "SAS outputs fetch for action %s returned HTTP %s",
                        action["name"], out_resp.status_code,
                    )
            except Exception as exc:
                # Never stringify the exception — a requests error can embed the
                # signed outputsLink (SAS token) in its message. Log type only.
                logger.warning(
                    "SAS outputs fetch for action %s failed: %s",
                    action["name"], type(exc).__name__,
                )
        actions.append(entry)
    return actions


def _norm_host(url: object) -> str:
    """Reduce a URL to a comparable host: no scheme, no trailing slash, lowercase."""
    if not isinstance(url, str):
        return ""
    host = url.strip().lower()
    host = host.split("://", 1)[-1]  # drop scheme
    return host.rstrip("/")


def match_environment_id(environments: list[dict], dataverse_url: str) -> str | None:
    """Return the Power Platform environment id whose linked Dataverse org matches.

    ``config.json`` records only the Dataverse org URL (``dataverseEndpoint``),
    but the Flow Management API is addressed by the environment GUID. Each listed
    environment carries its linked Dataverse instance URL under
    ``properties.linkedEnvironmentMetadata`` (``instanceApiUrl`` / ``instanceUrl``);
    this matches on host (scheme- and trailing-slash-insensitive) and returns the
    environment ``name`` (the GUID), or None when nothing matches.
    """
    target = _norm_host(dataverse_url)
    if not target:
        return None
    for env in environments or []:
        linked = ((env or {}).get("properties", {}) or {}).get(
            "linkedEnvironmentMetadata", {}) or {}
        for key in ("instanceApiUrl", "instanceUrl"):
            if _norm_host(linked.get(key)) == target:
                return env.get("name")
    return None


def list_environments(token: str) -> list[dict]:
    """List the caller's Power Platform environments (Flow Management API)."""
    url = (
        f"{_FLOW_API_HOST}/providers/Microsoft.ProcessSimple/environments"
        "?api-version=2016-11-01"
    )
    resp = _get_json(url, headers=_auth_headers(token))
    raise_api_error(resp, resource_name="environments", operation="read")
    return resp.json().get("value", [])


def resolve_environment_id(dataverse_url: str, token: str) -> str | None:
    """Resolve the environment GUID for a Dataverse org URL via the Flow API."""
    return match_environment_id(list_environments(token), dataverse_url)


def _extract_status_code(outputs: object) -> int | None:
    """Pull the connector/HTTP ``statusCode`` out of an action's outputs, if any.

    Returns None when outputs are absent (e.g. a Skipped action) or carry no
    status code (e.g. a Compose / SetVariable), so the caller can distinguish
    "no code" from a real code without a KeyError.
    """
    if isinstance(outputs, dict):
        code = outputs.get("statusCode")
        if isinstance(code, int):
            return code
    return None


def summarize_actions(actions: list[dict]) -> list[dict]:
    """Reduce ``get_run_actions`` output to the ``{name, status, statusCode}``
    cascade a caller reasons about.

    Pure and side-effect-free: given a recorded action list it returns the same
    summary every time, which makes the interpretation contract offline-testable.
    Interpreting the cascade (e.g. a Failed scope despite a Succeeded failure
    handler) is the caller's job, taught by the companion skill-doc; this
    function only shapes the data that interpretation runs on.
    """
    return [
        {
            "name": a.get("name"),
            "status": a.get("status"),
            "statusCode": _extract_status_code(a.get("outputs")),
        }
        for a in actions
    ]


def _render_cascade(summary: list[dict]) -> str:
    """Format a summarized cascade as an aligned name/status/statusCode table."""
    if not summary:
        return "(run has no actions)"
    width = max(len(str(row["name"])) for row in summary)
    lines = []
    for row in summary:
        code = row["statusCode"] if row["statusCode"] is not None else "—"
        lines.append(f"{str(row['name']):<{width}}  {row['status']:<10}  {code}")
    return "\n".join(lines)


def _resolve_token(explicit_env_token: str) -> str | None:
    """Resolve a Flow Management API bearer token.

    Prefers the ``FLOW_API_TOKEN`` env var (explicit / CI / bring-your-own).
    Falls back to acquiring one via the kit's MSAL flow (``auth.get_flow_token``)
    using the active agent's environment from ``.local/config.json`` for tenant
    discovery. Returns None if neither path yields a token.
    """
    if explicit_env_token:
        return explicit_env_token
    try:
        from auth import get_flow_token
        env_url = load_config()["dataverseEndpoint"]
    except Exception as exc:  # noqa: BLE001 — surface a clean message, no token
        print(f"Could not load environment config for token acquisition: {exc}")
        return None
    return get_flow_token(env_url)


def main(argv=None) -> int:
    """CLI: dump a flow run's action cascade for interpretation.

    Acquires a Flow Management API bearer token: uses ``FLOW_API_TOKEN`` if set,
    otherwise signs in via the kit's MSAL flow (Flow-scoped, using the active
    agent's environment from ``.local/config.json`` for tenant discovery).
    Interpret the output with the companion doc
    reference/ess-docs/operations/flow-run-inspection.md.
    """
    import argparse
    import os

    parser = argparse.ArgumentParser(
        description="Dump a cloud flow run's per-action cascade (read-only).")
    parser.add_argument("--environment", default=None,
                        help="environment id (GUID); resolved from the active "
                             "agent's Dataverse org URL when omitted")
    parser.add_argument("--flow", required=True, help="flow id (GUID)")
    parser.add_argument("--run", default=None,
                        help="run id (default: the latest run)")
    args = parser.parse_args(argv)

    token = _resolve_token(os.environ.get("FLOW_API_TOKEN", "").strip())
    if not token:
        print("No Flow Management API token: set FLOW_API_TOKEN, or ensure "
              ".local/config.json is present so a token can be acquired.")
        return 2

    environment = args.environment
    if not environment:
        try:
            dataverse_url = load_config()["dataverseEndpoint"]
        except Exception as exc:  # noqa: BLE001 — surface a clean message
            print(f"Could not read dataverseEndpoint to resolve the environment: "
                  f"{exc}. Pass --environment explicitly.")
            return 2
        environment = resolve_environment_id(dataverse_url, token)
        if not environment:
            print(f"Could not resolve an environment GUID for {dataverse_url!r}. "
                  "Pass --environment explicitly.")
            return 2
        print(f"Resolved environment {environment} for {dataverse_url}")

    if args.run:
        run = get_run_by_id(environment, args.flow, args.run, token)
    else:
        run = get_latest_run(environment, args.flow, token)
    if not run:
        print("No run found for that flow.")
        return 1

    run_id = run.get("name") or args.run
    actions = get_run_actions(environment, args.flow, run_id, token)
    print(f"Run {run_id}:")
    print(_render_cascade(summarize_actions(actions)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
