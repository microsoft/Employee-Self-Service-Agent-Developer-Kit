# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Capture the read-only ALM export contract without retaining agent content.

Required: ESS_AGENTBUILDER_ENVIRONMENT_ID, ESS_AGENTBUILDER_AGENT_ID,
ESS_AGENTBUILDER_ACCOUNT. Optional: ESS_AGENTBUILDER_TOKEN_CACHE,
ESS_AGENTBUILDER_EXPORT_OUTPUT. Uses the production service ring.

The recorded archive preserves member count and compression methods only.
Member names, data, timestamps, attributes, extras and comments are replaced.
This confirms the binary transport/ZIP contract, not package semantics.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
import zipfile

import yaml

from _common import CASSETTE_DIR, KIT_ROOT, REDACT_TABLE
from _redact import redact_cassette
from agentbuilder import (
    AgentBuilderClient, AgentBuilderHTTPError, authenticate_flightcheck,
    derive_environment_host,
)
from flightcheck.checks.publishing import _invalid_archive_reason


def _project_archive(package: Path) -> bytes:
    reason = _invalid_archive_reason(package)
    if reason is not None:
        raise ValueError(f"Cannot project an invalid exported archive: {reason}")
    projected = io.BytesIO()
    with zipfile.ZipFile(package) as source:
        with zipfile.ZipFile(projected, "w") as destination:
            for index, member in enumerate(source.infolist(), 1):
                info = zipfile.ZipInfo(f"redacted-{index:04d}.bin", (2026, 1, 1, 0, 0, 0))
                info.compress_type = member.compress_type
                destination.writestr(info, b"REDACTED")
    return projected.getvalue()


def main() -> None:
    environment_id = os.environ["ESS_AGENTBUILDER_ENVIRONMENT_ID"]
    agent_id = os.environ["ESS_AGENTBUILDER_AGENT_ID"]
    account = os.environ["ESS_AGENTBUILDER_ACCOUNT"]
    cache = Path(os.environ.get(
        "ESS_AGENTBUILDER_TOKEN_CACHE",
        str(KIT_ROOT / ".local" / ".agentbuilder_token_cache.bin"),
    ))
    output = Path(os.environ.get(
        "ESS_AGENTBUILDER_EXPORT_OUTPUT",
        str(CASSETTE_DIR / "agentbuilder_export.yaml"),
    ))
    token, tenant_id, authenticated = authenticate_flightcheck(
        "prod", cache_path=cache, account_hint=account,
        include_connectivity=False, emit_account_identity=False,
        return_account_identity=True,
    )
    if not authenticated or authenticated.casefold() != account.casefold():
        raise ValueError("The recorder did not authenticate the selected account.")
    host = derive_environment_host(environment_id, "prod")
    REDACT_TABLE[urlsplit(host).hostname.split(".")[0]] = "0" * 32
    client = AgentBuilderClient(host, token, ring="prod", tenant_id=tenant_id)
    interactions = []

    def record(response, **_kwargs):
        interactions.append({
            "request": {
                "method": response.request.method,
                "uri": response.request.url,
                "body": None, "headers": {},
            },
            "response": {
                "status": {"code": response.status_code, "message": response.reason},
                "headers": {"Content-Type": [response.headers["Content-Type"]]},
                "body": {"string": (
                    "REDACTED_BINARY_PROJECTION" if 200 <= response.status_code < 300 else response.text
                )},
            },
        })

    client.session.hooks["response"].append(record)
    with TemporaryDirectory(prefix="flightcheck-export-capture-") as temporary:
        package = Path(temporary) / "agent.zip"
        try:
            client.export_package(agent_id, package)
        except AgentBuilderHTTPError:
            if not interactions:
                raise
            archive = None
        else:
            archive = _project_archive(package)
        source = Path(temporary) / "projected.yaml"
        redacted = Path(temporary) / "redacted.yaml"
        source.write_text(yaml.safe_dump({"version": 1, "interactions": interactions}), encoding="utf-8")
        redact_cassette(source, redacted)
        cassette = yaml.safe_load(redacted.read_text(encoding="utf-8"))
        # The shared text redactor cannot process binary; these bytes contain
        # only the canonical, content-free ZIP projection above.
        if archive is not None:
            cassette["interactions"][0]["response"]["body"]["string"] = archive
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(yaml.safe_dump(cassette, sort_keys=False), encoding="utf-8")
    status = interactions[0]["response"]["status"]["code"]
    print(f"Captured one redacted read-only ALM export response (HTTP {status}): {output}")


if __name__ == "__main__":
    main()
