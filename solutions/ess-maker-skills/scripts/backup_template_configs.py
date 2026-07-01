# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""ESS Maker Kit - Backup Workday HCM template config records.

Captures the customer's Workday HCM reference-data template config customisations
so they can be restored after an ESS Workday HCM package update. Targets every
record whose ``msdyn_uniquename`` matches ``*WorkdayHCMReferenceData_*``, which
auto-discovers all four ESS agent flavours installed in the env::

  - msdyn_HRWorkdayHCMReferenceData_*    (ESS HR + Workday)
  - msdyn_ITWorkdayHCMReferenceData_*    (ESS IT + Workday)
  - msdyn_DAHRWorkdayHCMReferenceData_*  (ESS DA-HR + Workday)
  - msdyn_DAITWorkdayHCMReferenceData_*  (ESS DA-IT + Workday)

A single env may have one or several of these installed; the script picks up
whatever is present. Pair with ``restore_template_configs.py`` to put the
captured records back after a package update.

Usage::

    python scripts/backup_template_configs.py --url https://orgX.crm10.dynamics.com
    python scripts/backup_template_configs.py --url ... --output mybackup.json
    python scripts/backup_template_configs.py --url ... --yes
"""

import argparse
import datetime
import json
import os
import sys

# Add scripts/ to path so siblings (auth, http_errors) import without setup.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import (  # noqa: E402
    authenticate,
    query_all,
    AuthExpiredError,
)
from http_errors import APIError  # noqa: E402


SCHEMA_VERSION = "v1"
ENTITY_SET = "msdyn_employeeselfservicetemplateconfigs"
FILTER_SUBSTRING = "WorkdayHCMReferenceData_"
DEFAULT_OUTPUT_DIR = os.path.join("workspace", "template-config-backups")


def infer_agent(unique_name):
    """Derive the ESS agent flavour from a template config's uniqueName prefix.

    DA flavours must be checked BEFORE plain HR/IT because they share the
    same uniqueName suffix and ``in`` is substring-not-prefix.
    """
    if "_DAHRWorkdayHCMReferenceData_" in unique_name:
        return "DAHR"
    if "_DAITWorkdayHCMReferenceData_" in unique_name:
        return "DAIT"
    if "_HRWorkdayHCMReferenceData_" in unique_name:
        return "HR"
    if "_ITWorkdayHCMReferenceData_" in unique_name:
        return "IT"
    return "Unknown"


def fetch_records(env_url, token):
    """Query every template config whose uniqueName contains the WD HCM marker.

    Returns a list of records with the four fields we serialise.
    """
    select = (
        "msdyn_employeeselfservicetemplateconfigid,"
        "msdyn_uniquename,"
        "msdyn_name,"
        "msdyn_value"
    )
    filter_expr = f"contains(msdyn_uniquename, '{FILTER_SUBSTRING}')"
    print(
        "Querying template configs matching "
        f"'contains(msdyn_uniquename, {FILTER_SUBSTRING!r})'..."
    )
    return query_all(
        env_url, token, ENTITY_SET, select, filter_expr=filter_expr,
    )


def summarise(records):
    """Return {agent_flavour: record_count} for a flat record list."""
    summary = {}
    for r in records:
        agent = infer_agent(r.get("msdyn_uniquename", ""))
        summary[agent] = summary.get(agent, 0) + 1
    return summary


def to_backup_json(env_url, records, captured_at):
    """Build the v1 backup payload."""
    agents = summarise(records)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "metadata": {
            "envUrl": env_url,
            "capturedAt": captured_at,
            "filterSubstring": FILTER_SUBSTRING,
            "agentsDetected": sorted(agents.keys()),
            "recordCountsByAgent": agents,
            "recordCount": len(records),
        },
        "records": [
            {
                "id": r.get("msdyn_employeeselfservicetemplateconfigid"),
                "uniqueName": r.get("msdyn_uniquename"),
                "name": r.get("msdyn_name"),
                "agent": infer_agent(r.get("msdyn_uniquename", "")),
                "value": r.get("msdyn_value"),
            }
            for r in records
        ],
    }


def default_output_path(env_url, captured_at_iso):
    """Derive ``workspace/template-config-backups/<envslug>-<utc-stamp>.json``."""
    # Slug = hostname's first label (e.g. "orgXXX" from
    # https://orgXXX.crm10.dynamics.com). Falls back to "env" if URL is odd.
    safe_env = "env"
    if "//" in env_url:
        host = env_url.split("//", 1)[1]
        first_label = host.split(".", 1)[0]
        if first_label:
            safe_env = first_label
    stamp = captured_at_iso.replace(":", "").replace("-", "").split(".")[0]
    # stamp ends with 'Z' from to_iso(); keep it for clarity.
    return os.path.join(DEFAULT_OUTPUT_DIR, f"{safe_env}-{stamp}.json")


def atomic_write_json(path, data):
    """Write JSON atomically via tmp + os.replace, mkdir -p first."""
    out_dir = os.path.dirname(path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            # Some filesystems do not support fsync; the os.replace below is
            # still atomic on POSIX/Windows.
            pass
    os.replace(tmp, path)


def utc_iso_now():
    """UTC ISO-8601 with seconds precision and trailing 'Z'."""
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Backup ESS Workday HCM template configs so they survive a "
            "package update. Run before installing a new ESS Workday HCM "
            "package version; pair with restore_template_configs.py after."
        ),
    )
    parser.add_argument(
        "--url",
        required=True,
        help=(
            "Power Platform environment URL "
            "(e.g. https://orgXXX.crm10.dynamics.com)."
        ),
    )
    parser.add_argument(
        "--output",
        help=(
            f"Output JSON path. Defaults to {DEFAULT_OUTPUT_DIR}/"
            "<envslug>-<utc-stamp>.json (gitignored by the kit). The backup "
            "contains customer-specific reference data from the env - treat "
            "it as customer data, not as code, and avoid checking it into a "
            "shared repo."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the pre-flight prompt (useful in scripted runs).",
    )
    args = parser.parse_args()
    env_url = args.url.rstrip("/")

    print("Authenticating to Dataverse...")
    try:
        token = authenticate(env_url)
    except SystemExit:
        # authenticate() prints its own friendly error and exits 1.
        raise
    print("Authenticated.\n")

    try:
        records = fetch_records(env_url, token)
    except AuthExpiredError as e:
        # On a fresh token this should not happen, but surface cleanly if it does.
        print(e.format_for_terminal())
        sys.exit(1)
    except APIError as e:
        print(e.format_for_terminal())
        sys.exit(1)

    if not records:
        print()
        print("No matching records found.")
        print(
            f"  Filter: contains(msdyn_uniquename, {FILTER_SUBSTRING!r})"
        )
        print(
            "  Confirm the ESS Workday HCM solution is installed in this "
            "environment, or pick the env that has it."
        )
        sys.exit(2)

    captured_at = utc_iso_now()
    output_path = args.output or default_output_path(env_url, captured_at)
    summary = summarise(records)

    print()
    print(
        f"Found {len(records)} record(s) across "
        f"{len(summary)} ESS Workday HCM agent installation(s):"
    )
    for agent in sorted(summary.keys()):
        print(f"  - {agent:5s}  {summary[agent]:3d} records")
    print()
    print(f"Backup target: {output_path}")

    if not args.yes:
        answer = input("\nProceed? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes"):
            print("Cancelled.")
            sys.exit(0)

    payload = to_backup_json(env_url, records, captured_at)
    atomic_write_json(output_path, payload)
    size_bytes = os.path.getsize(output_path)
    print(
        f"Backup complete: {len(records)} record(s) "
        f"({size_bytes // 1024} KB) -> {output_path}"
    )


if __name__ == "__main__":
    main()
