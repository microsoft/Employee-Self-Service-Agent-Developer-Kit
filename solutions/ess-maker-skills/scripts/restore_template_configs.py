# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""ESS Maker Kit - Restore Workday HCM template config records from a backup.

Reads a backup JSON file produced by ``backup_template_configs.py`` and PATCHes
each ``msdyn_value`` back into the corresponding record in the target
Dataverse environment. Records are matched by ``msdyn_uniquename`` (the
stable identifier across envs), so the same backup file can be used to
restore into the env it came from OR into a different env (warns once,
proceed-or-cancel).

Records present in the backup but missing from the target env (e.g. an ESS
agent that was uninstalled) are skipped with a clear warning rather than
treated as a failure.

Usage::

    python scripts/restore_template_configs.py \
        --url https://orgX.crm10.dynamics.com \
        --input workspace/template-config-backups/orgX-20260624T1530Z.json

    # Skip cross-env confirmation when porting backups between envs:
    python scripts/restore_template_configs.py --url ... --input ... --force

    # Skip the final overwrite prompt (scripted runs):
    python scripts/restore_template_configs.py --url ... --input ... --yes
"""

import argparse
import json
import os
import sys

# Add scripts/ to path so siblings (auth, http_errors) import without setup.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import (  # noqa: E402
    authenticate,
    query_all,
    update_record,
    AuthExpiredError,
)
from http_errors import APIError  # noqa: E402


SCHEMA_VERSION = "v1"
ENTITY_SET = "msdyn_employeeselfservicetemplateconfigs"
FILTER_SUBSTRING = "WorkdayHCMReferenceData_"


class _AuthHolder:
    """Mutable token wrapper for the 401-retry helper.

    The restore loop can take longer than a single MSAL access-token lifetime
    (~1 hour) on large multi-agent envs. update_record() / query_all() calls
    go through _call_with_refresh() which catches AuthExpiredError,
    re-authenticates, and retries once.

    Mirrors the pattern in push.py so the codebase has one approach to
    long-lived auth.
    """

    def __init__(self, env_url):
        self.env_url = env_url
        self.token = None

    def acquire(self):
        self.token = authenticate(self.env_url)
        return self.token

    def refresh(self):
        print("  ! Access token expired - re-authenticating...")
        return self.acquire()


def _call_with_refresh(auth, fn, *args, **kwargs):
    """Call a Dataverse helper with one auto-retry on 401."""
    try:
        return fn(*args, **kwargs)
    except AuthExpiredError:
        auth.refresh()
        # By convention, the second positional argument of update_record /
        # query_all is `token`. Replace it with the freshly-acquired one and
        # try once more.
        new_args = list(args)
        if len(new_args) >= 2:
            new_args[1] = auth.token
        return fn(*new_args, **kwargs)


def load_backup(path):
    """Load a backup file, validate its schema version, return the dict.

    Exits non-zero on schema mismatch with a clear message - the alternative
    is a misleading KeyError deep in the restore loop.
    """
    with open(path, "r", encoding="utf-8") as f:
        backup = json.load(f)
    schema = backup.get("schemaVersion")
    if schema != SCHEMA_VERSION:
        print(
            f"ERROR: Backup schema version is {schema!r}; this script "
            f"handles {SCHEMA_VERSION!r}."
        )
        print(
            "Use a matching version of this script or re-create the backup "
            "with the current version."
        )
        sys.exit(1)
    return backup


def build_unique_name_index(env_url, token):
    """Query the target env and return ``{uniqueName: record_id}``.

    Lets the restore loop look up record IDs in O(1) instead of per-record
    queries.
    """
    select = (
        "msdyn_employeeselfservicetemplateconfigid,"
        "msdyn_uniquename"
    )
    filter_expr = f"contains(msdyn_uniquename, '{FILTER_SUBSTRING}')"
    print("Indexing current template configs in target env...")
    records = query_all(
        env_url, token, ENTITY_SET, select, filter_expr=filter_expr,
    )
    return {
        r["msdyn_uniquename"]: r["msdyn_employeeselfservicetemplateconfigid"]
        for r in records
        if r.get("msdyn_uniquename")
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Restore ESS Workday HCM template configs from a backup file "
            "produced by backup_template_configs.py. Run after installing "
            "a new ESS Workday HCM package version."
        ),
    )
    parser.add_argument(
        "--url",
        required=True,
        help=(
            "Power Platform environment URL to restore INTO "
            "(e.g. https://orgXXX.crm10.dynamics.com)."
        ),
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to backup JSON file produced by backup_template_configs.py.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Skip the cross-env-mismatch confirmation (the backup was "
            "captured from a different env URL than the one being restored "
            "into)."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the final overwrite prompt (useful in scripted runs).",
    )
    args = parser.parse_args()
    env_url = args.url.rstrip("/")

    if not os.path.exists(args.input):
        print(f"ERROR: Backup file not found: {args.input}")
        sys.exit(1)

    backup = load_backup(args.input)
    records = backup.get("records", [])
    if not records:
        print("ERROR: Backup file contains no records.")
        sys.exit(1)

    meta = backup.get("metadata", {})
    backup_env = meta.get("envUrl", "")
    captured_at = meta.get("capturedAt", "?")
    agents_detected = meta.get("agentsDetected", [])

    print(f"Backup file: {args.input}")
    print(f"  Captured at: {captured_at}")
    print(f"  Source env : {backup_env or '(unknown)'}")
    print(f"  Records    : {len(records)} across {agents_detected}")
    print()

    if backup_env and backup_env.rstrip("/") != env_url and not args.force:
        print("! Env URL mismatch.")
        print(f"  Backup captured from: {backup_env}")
        print(f"  Restoring into:       {env_url}")
        print(
            "  This is fine for porting customisations dev->prod, but worth "
            "confirming."
        )
        answer = input(
            "  Proceed with cross-env restore? [y/N] "
        ).strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled.")
            sys.exit(0)
        print()

    auth = _AuthHolder(env_url)
    print("Authenticating to Dataverse...")
    auth.acquire()
    print("Authenticated.\n")

    try:
        index = _call_with_refresh(
            auth, build_unique_name_index, env_url, auth.token,
        )
    except APIError as e:
        print(e.format_for_terminal())
        sys.exit(1)

    matched = [r for r in records if r.get("uniqueName") in index]
    missing = [r for r in records if r.get("uniqueName") not in index]

    print()
    print(f"Records to restore: {len(matched)}")
    print(
        f"Records to skip   : {len(missing)} "
        "(present in backup, not in target env)"
    )
    if missing:
        # Show up to 8 so the customer can sanity-check; truncate the rest.
        print("  Skipped uniqueNames:")
        for r in missing[:8]:
            print(f"    - {r.get('uniqueName')}")
        if len(missing) > 8:
            print(f"    ... and {len(missing) - 8} more")
    print()

    if not matched:
        print(
            "Nothing to restore - none of the backup's records exist in this "
            "env. Confirm the ESS Workday HCM solution(s) are installed."
        )
        sys.exit(2)

    if not args.yes:
        answer = input(
            f"Proceed with full overwrite of {len(matched)} record(s)? "
            "[Y/n] "
        ).strip().lower()
        if answer not in ("", "y", "yes"):
            print("Cancelled.")
            sys.exit(0)

    print("Restoring...")
    restored = 0
    failed = 0
    failures = []
    for i, rec in enumerate(matched, start=1):
        unique_name = rec.get("uniqueName")
        record_id = index[unique_name]
        try:
            _call_with_refresh(
                auth, update_record,
                env_url, auth.token, ENTITY_SET, record_id,
                {"msdyn_value": rec.get("value")},
            )
            restored += 1
            print(f"  [{i:3d}/{len(matched):3d}]  {unique_name}  OK")
        except APIError as e:
            failed += 1
            # Compact one-liner per failure; the full friendly message is
            # printed at the end so the customer doesn't get drowned mid-loop.
            first_line = str(e).splitlines()[0]
            failures.append((unique_name, first_line, e))
            print(f"  [{i:3d}/{len(matched):3d}]  {unique_name}  FAIL")
            print(f"      {first_line}")

    print()
    print(
        f"Restore complete: {restored} restored, "
        f"{len(missing)} skipped, {failed} failed."
    )

    # On failures, print the first error's full diagnostic block so the user
    # has tip + request id without scrolling back.
    if failures:
        print()
        print("First failure detail (re-run for the rest):")
        print(failures[0][2].format_for_terminal())

    sys.exit(0 if failed == 0 else 4)


if __name__ == "__main__":
    main()
