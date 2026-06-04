#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record a Dataverse cassette covering ``/connectionreferences`` for the
purpose of fingerprinting which flavor of Workday integration is
installed in the environment.

Background — why this endpoint and not ``/solutions``
-----------------------------------------------------
An earlier scaffolding attempt assumed the OOTB simplified-Workday
package and the full/legacy SOAP+custom package would each register as
distinct managed Dataverse solutions with recognisable ``uniquename``
strings (e.g. ``WorkdayHCM`` vs. ``WorkdayConnectorCertified``). Real
captures against both flavors disproved this: neither install adds any
Workday-named row to the ``solutions`` table. Both tenants list the
same ~500 Microsoft platform-foundation solutions.

A subsequent PPAC check confirmed that all six Workday connections
across both tenants (2 on the simplified env, 4 on the legacy env) bind
to the same connector definition — ``shared_workdaysoap`` — so the
*connector identity* alone also can't distinguish the two flavors.

What DOES distinguish them is the **set of ``connectionreference``
rows** shipped by the two different Microsoft-owned solutions that
install the simplified vs. full integration. Connection references are
emitted by the solution publisher at build time and embedded in the
solution XML. They exist in Dataverse from the moment the solution is
installed, regardless of whether the customer has wired up any
connections — so they're a deterministic install-time fingerprint that
survives partial wire-up. The simplified solution ships one
connectionref (OBO / OAuthUser); the full / legacy solution ships
three (OBO + two SOAP ISU roles: Generic User and Context Generic
User). The exact ``connectionreferencelogicalname`` strings per
flavor are the ground truth this recorder captures.

(Note: the per-tenant BAP-side connection counts are larger — 2 on
simplified, 4 on legacy — because each install layers an additional
unbound service-account connection on top of the bound refs. WD-PKG-001
fingerprints the Dataverse-side ref counts, not the BAP-side connection
counts.)

Exercises
---------
- ``GET /api/data/v9.2/connectionreferences?$select=connectionreferenceid,connectionreferencelogicalname,connectionreferencedisplayname,connectorid,connectionid,statuscode``

  Returns every connection reference in the environment. The select set
  matches what ``solutions/ess-maker-skills/scripts/flightcheck/checks/environment.py``
  already queries for ``ENV-004`` (connection-binding state), so a
  cassette captured here is replayable by both ``ENV-004`` and the
  forthcoming ``WD-PKG-001`` check.

No server-side filter is applied. Connection-reference tables run to
tens of rows per environment, so the unfiltered payload stays small,
and filtering Workday rows out of the resulting list is a trivial
post-processing step. Pulling the full inventory also gives the
follow-up PR free coverage for any future checks that want to inspect
non-Workday connection refs.

Output
------
``tests/fixtures/cassettes/dataverse_workday_connection_refs.yaml``

After the run, the script prints a summary table flagging every
connection reference whose ``connectionreferencelogicalname``,
``connectionreferencedisplayname``, or ``connectorid`` contains the
substring ``workday``. The operator uses this table to confirm the
capture is useful before renaming and committing.

Operator workflow
-----------------
1. Clear the MSAL token cache if you need to authenticate as a
   different user than the last recorder run:
   ``Remove-Item solutions/ess-maker-skills/.local/.token_cache.bin``
2. ``$env:ESS_DATAVERSE_URL = "https://<your-tenant>.crm.dynamics.com"``
3. ``python tests/captures/record_dataverse_workday_connection_refs.py``
4. Inspect the on-screen summary; confirm the Workday-flagged rows
   match the install flavor you expected (1 row on a simplified
   tenant, 3 rows on a legacy tenant).
5. Rename the cassette per the captured flavor:
     * OOTB simplified:    ``dataverse_workday_connection_refs_simplified.yaml``
     * full / legacy SOAP: ``dataverse_workday_connection_refs_full.yaml``
6. Repeat against the other flavor's tenant (clearing the token cache
   again first).

The follow-up implementation of ``WD-PKG-001`` keys off the
``connectionreferencelogicalname`` set produced by each capture, so
both flavors must be captured before the check can be written.
"""

from __future__ import annotations

import sys

from _common import (
    announce,
    build_cassette,
    chdir_kit_root,
    confirm_or_exit,
    get_dataverse_url,
)

# Substring (case-insensitive) used to flag Workday-related rows in the
# stdout summary. Matches against connectionreferencelogicalname,
# connectionreferencedisplayname, and connectorid. The cassette captures
# every connection reference unconditionally — this flag is for
# operator triage only.
WORKDAY_MATCH = "workday"


def _looks_workday(ref: dict) -> bool:
    """Return True if any of the connection-reference name fields mention Workday."""
    fields = (
        ref.get("connectionreferencelogicalname") or "",
        ref.get("connectionreferencedisplayname") or "",
        ref.get("connectorid") or "",
    )
    return any(WORKDAY_MATCH in field.lower() for field in fields)


def _print_refs_table(refs: list[dict]) -> None:
    """Print a numbered table of connection references, flagging Workday rows."""
    if not refs:
        print("  (no connection references returned)")
        return

    logical_w = max(
        (len(r.get("connectionreferencelogicalname") or "") for r in refs),
        default=10,
    )
    logical_w = max(logical_w, 30)
    display_w = max(
        (len(r.get("connectionreferencedisplayname") or "") for r in refs),
        default=10,
    )
    display_w = max(display_w, 25)
    connector_w = max(
        (len(r.get("connectorid") or "") for r in refs), default=10
    )
    connector_w = max(connector_w, 25)

    header = (
        f"  {'WD?':<4} {'logicalname':<{logical_w}}  "
        f"{'displayname':<{display_w}}  "
        f"{'connectorid':<{connector_w}}  bound?"
    )
    sep = (
        f"  {'-' * 4} {'-' * logical_w}  "
        f"{'-' * display_w}  {'-' * connector_w}  ------"
    )
    print()
    print(header)
    print(sep)
    for r in refs:
        flag = " * " if _looks_workday(r) else "   "
        bound = "yes" if r.get("connectionid") else "no"
        print(
            f"  {flag:<4} "
            f"{(r.get('connectionreferencelogicalname') or ''):<{logical_w}}  "
            f"{(r.get('connectionreferencedisplayname') or ''):<{display_w}}  "
            f"{(r.get('connectorid') or ''):<{connector_w}}  {bound}"
        )
    print()
    print(f"  Rows marked '*' contain '{WORKDAY_MATCH}' in their logicalname,")
    print("  displayname, or connectorid. These are the rows WD-PKG-001 will")
    print("  fingerprint to tell simplified-vs-legacy install flavors apart.")
    print()


def main() -> None:
    announce("dataverse_workday_connection_refs")
    env_url = get_dataverse_url()
    confirm_or_exit()

    chdir_kit_root()

    import auth

    token = auth.authenticate(env_url)

    with build_cassette("dataverse_workday_connection_refs"):
        print("Querying /connectionreferences (full inventory)...")
        all_refs = auth.query_all(
            env_url,
            token,
            entity_set="connectionreferences",
            select=(
                "connectionreferenceid,connectionreferencelogicalname,"
                "connectionreferencedisplayname,connectorid,connectionid,"
                "statuscode"
            ),
        )

    # ---- Summary table for the operator ----
    print()
    print("=" * 78)
    print("Connection reference inventory (rows marked '*' mention 'workday')")
    print("=" * 78)
    _print_refs_table(all_refs)

    wd_refs = [r for r in all_refs if _looks_workday(r)]
    print(
        f"Total connection references: {len(all_refs)} "
        f"(Workday-flagged: {len(wd_refs)})"
    )
    print()
    print(
        "Cassette written to "
        "tests/fixtures/cassettes/dataverse_workday_connection_refs.yaml"
    )
    print()
    print("NEXT STEPS")
    print("----------")
    print(
        "1. Confirm the Workday-flagged row count matches the install flavor"
    )
    print("   you captured against (expect 1 for simplified, 3 for legacy).")
    print(
        "2. Eyeball the cassette body for any tenant-specific text the"
    )
    print(
        "   redactor missed. The display-name field can carry customer"
    )
    print("   branding; the logical-name field should be publisher-prefixed")
    print(
        "   and tenant-neutral (e.g. 'new_workdayOBO', 'cr12_workdayISURead')."
    )
    print(
        "3. Rename per the flavor you captured:"
    )
    print(
        "     - OOTB simplified:    dataverse_workday_connection_refs_simplified.yaml"
    )
    print(
        "     - full / legacy SOAP: dataverse_workday_connection_refs_full.yaml"
    )
    print(
        "4. Commit the renamed cassette and proceed to the WD-PKG-001"
    )
    print("   implementation. Both flavors must be captured first.")
    if not wd_refs:
        print()
        print(
            "WARNING: no connection references were flagged as Workday-"
            "related. Either the tenant does not have a Workday integration"
        )
        print(
            "installed, or the Workday connection refs use a non-obvious"
            f" naming convention (none of logicalname/displayname/connectorid"
            f" contained '{WORKDAY_MATCH}'). Inspect the full table above"
            " before deciding whether to keep the capture."
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
