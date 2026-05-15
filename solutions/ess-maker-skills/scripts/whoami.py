# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Environment Probe (WhoAmI)

Authenticates via MSAL and calls WhoAmI to verify Dataverse access.

Usage:  python scripts/whoami.py --env-url https://orgxyz.crm.dynamics.com
Exit codes: 0 ok, 1 auth/permissions, 2 network/DNS, 3 unexpected.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package not found. Run: pip install requests", file=sys.stderr)
    sys.exit(3)

from auth import authenticate


def main():
    parser = argparse.ArgumentParser(description="Probe a Power Platform env via WhoAmI")
    parser.add_argument("--env-url", required=True, help="Dataverse env URL")
    args = parser.parse_args()

    env_url = args.env_url.rstrip("/")

    # JSON on stdout; all errors to stderr.
    try:
        token = authenticate(env_url)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        print(f"ERROR: auth failed: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        resp = requests.get(
            f"{env_url}/api/data/v9.2/WhoAmI()",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=10,
        )
    except requests.exceptions.Timeout as e:
        print(f"ERROR: timeout reaching {env_url}: {e}", file=sys.stderr)
        sys.exit(2)
    except requests.exceptions.SSLError as e:
        print(f"ERROR: TLS failure on {env_url}: {e}", file=sys.stderr)
        sys.exit(2)
    except requests.exceptions.ConnectionError as e:
        print(f"ERROR: cannot reach {env_url}: {e}", file=sys.stderr)
        sys.exit(2)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        print(f"ERROR: unexpected: {e}", file=sys.stderr)
        sys.exit(3)

    if resp.status_code == 200:
        try:
            data = resp.json()
        except Exception as e:
            print(f"ERROR: WhoAmI 200 but body was not JSON: {e}", file=sys.stderr)
            sys.exit(3)
        out = {
            "status": "ok",
            "userId": data.get("UserId"),
            "organizationId": data.get("OrganizationId"),
            "businessUnitId": data.get("BusinessUnitId"),
        }
        print(json.dumps(out))
        sys.exit(0)
    elif resp.status_code in (401, 403):
        print(f"ERROR: access denied ({resp.status_code}). User lacks Dataverse permission on this env.", file=sys.stderr)
        sys.exit(1)
    elif resp.status_code == 404:
        print(f"ERROR: env not found ({resp.status_code}). Verify the URL.", file=sys.stderr)
        sys.exit(2)
    else:
        print(f"ERROR: unexpected status {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
