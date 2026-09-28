# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Emit a validated Dataverse token for the flow-authorization PowerShell script."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import auth  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", required=True)
    args = parser.parse_args()

    token = auth.authenticate(args.environment.rstrip("/"))
    print(f"ESS_DATAVERSE_TOKEN={token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
