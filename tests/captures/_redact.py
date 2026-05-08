# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Post-recording cassette redactor.

Use this if you've already captured a cassette without the inline redaction
applied by tests/captures/_common.py (for example, an older cassette, or one
you captured outside the build_cassette() helper).

Usage:
    python tests/captures/_redact.py path/to/raw_cassette.yaml \\
                                     path/to/redacted_cassette.yaml

Applies the same REDACT_TABLE + REDACT_REGEX from _common.py to URLs,
request bodies, response bodies, and headers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

# Reuse the redaction primitives from _common.py.
sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    SCRUB_HEADERS,
    _redact_text,
    _scrub_headers,
)


def redact_cassette(src: Path, dst: Path) -> None:
    raw = yaml.safe_load(src.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "interactions" not in raw:
        raise ValueError(
            f"{src} does not look like a vcrpy cassette (no 'interactions' key)."
        )

    for interaction in raw.get("interactions", []):
        req = interaction.get("request", {})
        if "headers" in req:
            req["headers"] = _scrub_headers(req["headers"])
        if "uri" in req:
            req["uri"] = _redact_text(req["uri"])
        if "body" in req and req["body"] is not None:
            body = req["body"]
            if isinstance(body, dict) and "string" in body:
                body["string"] = _redact_text(body["string"] or "")
            elif isinstance(body, str):
                req["body"] = _redact_text(body)

        resp = interaction.get("response", {})
        if "headers" in resp:
            resp["headers"] = _scrub_headers(resp["headers"])
        if "body" in resp and resp["body"] is not None:
            body = resp["body"]
            if isinstance(body, dict) and "string" in body:
                body["string"] = _redact_text(body["string"] or "")

    dst.write_text(yaml.safe_dump(raw, default_flow_style=False), encoding="utf-8")
    print(f"Redacted: {src.name} → {dst}")
    print(f"  scrubbed headers: {sorted(SCRUB_HEADERS)}")


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    if not src.exists():
        print(f"ERROR: {src} does not exist.")
        sys.exit(1)
    redact_cassette(src, dst)


if __name__ == "__main__":
    main()
