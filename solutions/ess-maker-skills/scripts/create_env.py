# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Power Platform Environment Creator (PAC CLI wrapper)

Wraps `pac admin create` with capacity pre-checks and argument validation.

Usage:
    python scripts/create_env.py --ring preprod --name essdev-foo-wd-20260511
    python scripts/create_env.py --ring prod --name myorg-test --type Developer

Exit codes: 0 success, 1 auth/tool, 2 capacity/naming, 3 unexpected.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys  # noqa: E402  (sys imported before re-use in module-level regex)


# Ring -> PAC --cloud flag mapping.
# PAC's cloud names: Preprod (PPE) and Public (Prod).
CLOUD_FOR_RING = {
    "preprod": "Preprod",
    "prod": "Public",
}


def _run(cmd, capture=True, timeout=1800):
    """Run a shell command, return (returncode, stdout, stderr).

    shell=True on Windows because pac is a .CMD batch file. Caller must
    validate all argv values before calling (see _VALID_*_RE patterns).
    """
    try:
        proc = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=(sys.platform == "win32"),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        return 124, "", f"subprocess timed out after {timeout}s: {e}"
    return proc.returncode, proc.stdout or "", proc.stderr or ""


# Allowlists for shell-passed arguments (defense against injection via shell=True).
_VALID_ENV_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_VALID_REGION_RE = re.compile(r"^[a-zA-Z]{1,40}$")
_VALID_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_VALID_LANGUAGE_RE = re.compile(r"^[0-9]{1,5}$")


def check_pac_installed():
    """Verify PAC CLI is on PATH. Exit 1 with install instructions if not."""
    if shutil.which("pac") is None:
        print(
            "ERROR: pac CLI not found on PATH.\n"
            "Install with: dotnet tool install --global Microsoft.PowerApps.CLI.Tool\n"
            "If dotnet is also missing, install the .NET SDK first: https://dotnet.microsoft.com/download",
            file=sys.stderr,
        )
        sys.exit(1)


def check_auth_for_cloud(cloud):
    """Confirm an active pac auth profile exists for the target cloud. Exit 1 if not."""
    rc, out, _ = _run(["pac", "auth", "list"])
    if rc != 0:
        # First run with no profiles - pac sometimes returns non-zero
        out = ""

    # pac auth list output marks the active profile with '*'. The cloud
    # column is one of {Public, Preprod, ...}. We accept any profile that
    # mentions the target cloud, active or not.
    if cloud.lower() not in out.lower():
        print(
            f"ERROR: no pac auth profile for cloud '{cloud}'.\n\n"
            f"Run this command yourself (so you can see the device code):\n\n"
            f"    pac auth create --cloud {cloud} --deviceCode\n\n"
            "Open https://microsoft.com/devicelogin and enter the code shown.\n"
            f"Sign in with your {cloud} tenant account, then re-run /provision.",
            file=sys.stderr,
        )
        sys.exit(1)


def select_auth_profile(cloud):
    """Switch the active pac auth profile to one matching the target cloud."""
    rc, out, _ = _run(["pac", "auth", "list"])
    if rc != 0:
        return  # Will surface as failure on next pac call

    # Each profile line: [1]  *  USER  user@tenant.com  Universal  Preprod
    for line in out.splitlines():
        m = re.match(r"\s*\[(\d+)\]", line)
        if m and cloud.lower() in line.lower():
            idx = m.group(1)
            _run(["pac", "auth", "select", "--index", idx])
            return


# Per-tenant env type limits. Developer is per-user (3) but pac admin list
# shows all tenant envs, so we warn but can't block precisely.
_ENV_TYPE_LIMITS = {
    "Trial": 1,
}
_DEVELOPER_PER_USER_LIMIT = 3


def check_env_capacity(env_type):
    """Count existing envs of the requested type and block/warn if at limit."""
    limit = _ENV_TYPE_LIMITS.get(env_type)
    if limit is None and env_type != "Developer":
        return  # No fixed limit to check

    rc, out, _ = _run(["pac", "admin", "list"])
    if rc != 0:
        # Can't list envs — skip the check, let pac admin create surface
        # the real error.
        return

    # Count envs by type. The type column appears in pac admin list output
    # as a word like "Developer", "Trial", "Sandbox", "Production", etc.
    type_counts = {}
    type_re = re.compile(r"\b(Developer|Trial|Sandbox|Production|Default|Teams)\b", re.IGNORECASE)
    for line in (out or "").splitlines():
        m = type_re.search(line)
        if m:
            t = m.group(1).capitalize()
            type_counts[t] = type_counts.get(t, 0) + 1

    current = type_counts.get(env_type, 0)

    # Print capacity summary
    print(f"\nEnvironment capacity check:", file=sys.stderr)
    if env_type == "Developer":
        print(f"  {env_type} environments in tenant: {current} (limit: {_DEVELOPER_PER_USER_LIMIT} per user)", file=sys.stderr)
    else:
        print(f"  {env_type} environments: {current} / {limit}", file=sys.stderr)
    for t, count in sorted(type_counts.items()):
        if t != env_type:
            t_limit = _ENV_TYPE_LIMITS.get(t)
            t_limit_str = str(t_limit) if t_limit else "∞"
            if t == "Developer":
                t_limit_str = f"{_DEVELOPER_PER_USER_LIMIT}/user"
            print(f"  {t} environments: {count} ({t_limit_str})", file=sys.stderr)

    # For Trial: tenant-wide limit, can block precisely
    if limit is not None and current >= limit:
        alternatives = []
        if env_type != "Developer":
            dev_current = type_counts.get("Developer", 0)
            alternatives.append(f"  --type Developer ({dev_current} in tenant, limit {_DEVELOPER_PER_USER_LIMIT}/user)")
        if env_type not in ("Sandbox", "Production"):
            alternatives.append("  --type Sandbox (requires tenant DB capacity)")

        alt_text = "\n".join(alternatives) if alternatives else "  (none available)"
        print(
            f"\nERROR: {env_type} environment limit reached ({current}/{limit}).\n"
            f"You must delete an existing {env_type} env or use a different type.\n\n"
            f"Available alternatives:\n{alt_text}",
            file=sys.stderr,
        )
        sys.exit(2)

    # For Developer: warn but don't block (can't tell per-user count)
    if env_type == "Developer" and current >= _DEVELOPER_PER_USER_LIMIT:
        print(
            f"  ⚠ Warning: {current} Developer envs in tenant (limit is {_DEVELOPER_PER_USER_LIMIT} per user).\n"
            f"    If you already have {_DEVELOPER_PER_USER_LIMIT}, this will fail. "
            f"Consider --type Trial or --type Sandbox instead.",
            file=sys.stderr,
        )
    else:
        remaining = (limit - current) if limit else "?"
        print(f"  ✓ Capacity OK\n", file=sys.stderr)


def create_env(name, env_type, region, currency, language):
    """Run `pac admin create` and look up the result via `pac admin list`.

    PAC's create stdout is unstable across versions; list is more reliable
    for extracting URL + GUIDs. PAC sometimes returns rc=0 on failure,
    so output text is checked for error patterns regardless of exit code.
    """
    cmd = [
        "pac", "admin", "create",
        "--name", name,
        "--type", env_type,
        "--region", region,
        "--currency", currency,
        "--language", language,
    ]
    rc, out, err = _run(cmd, capture=True)
    combined = (out or "") + "\n" + (err or "")
    lower = combined.lower()

    # PAC rc=0 doesn't guarantee success — check output for error patterns.
    if rc != 0 or "error" in lower:
        if "capacity" in lower or "quota" in lower or "limit" in lower:
            print(f"ERROR: tenant out of {env_type} capacity or env limit reached. {combined.strip()[:500]}", file=sys.stderr)
            sys.exit(2)
        if "already exists" in lower or "duplicate" in lower or "name is taken" in lower:
            print(f"ERROR: env name '{name}' already in use. {combined.strip()[:500]}", file=sys.stderr)
            sys.exit(2)
        if "unauthorized" in lower or "forbidden" in lower or "401" in lower or "403" in lower:
            print(f"ERROR: pac auth expired or insufficient permissions. {combined.strip()[:500]}", file=sys.stderr)
            sys.exit(1)
        if rc != 0:
            print(f"ERROR: pac admin create failed (rc={rc}). {combined.strip()[:800]}", file=sys.stderr)
            sys.exit(3)

    # Look up via `pac admin list` — more reliable than parsing create stdout.
    return _lookup_env_in_list(name)


def _lookup_env_in_list(name):
    """Find env by name in `pac admin list`, extract URL and GUIDs.

    PAC wraps each env across multiple lines; we use a 5-line window
    around the name match to extract URL + GUID pairs.
    """
    rc, out, err = _run(["pac", "admin", "list"])
    if rc != 0:
        print(f"ERROR: pac admin list failed after create. stderr: {(err or '').strip()[:500]}", file=sys.stderr)
        sys.exit(3)

    lines = (out or "").splitlines()
    guid_re = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", re.IGNORECASE)
    url_re = re.compile(r"https?://[a-z0-9.-]+\.dynamics\.com/?", re.IGNORECASE)

    for i, line in enumerate(lines):
        # Match the env name as a whole word so "v2test" doesn't match
        # "v2testing", and pac's leading whitespace is tolerated.
        if re.search(rf"\b{re.escape(name)}\b", line):
            chunk = " ".join(lines[i:i + 5])
            url_m = url_re.search(chunk)
            guids = guid_re.findall(chunk)
            if url_m and guids:
                # First GUID is env ID; second (if present) is organization ID.
                env_id = guids[0] if guids else None
                org_id = guids[1] if len(guids) >= 2 else None
                return {
                    "envUrl": url_m.group(0).rstrip("/"),
                    "envId": env_id,
                    "organizationId": org_id,
                }

    print(
        f"ERROR: pac admin create succeeded but env '{name}' was not found in pac admin list.\n"
        f"This usually means the active pac auth profile is for a different ring than the one that\n"
        f"received the new env. Check 'pac auth list' and 'pac auth select --index <N>'.",
        file=sys.stderr,
    )
    sys.exit(3)


def main():
    parser = argparse.ArgumentParser(description="Create a new Power Platform environment via PAC CLI")
    parser.add_argument("--ring", required=True, choices=list(CLOUD_FOR_RING.keys()))
    parser.add_argument("--name", required=True, help="Environment display name (alphanumeric + dash/underscore, 1-64 chars)")
    parser.add_argument("--type", default="Developer",
                        choices=["Developer", "Sandbox", "Production", "Trial"],
                        help="Environment type (default: Developer; no capacity required)")
    parser.add_argument("--region", default="unitedstates")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--language", default="1033")
    args = parser.parse_args()

    # Validate args before passing through shell=True (injection defense).
    if not _VALID_ENV_NAME_RE.match(args.name):
        print(
            f"ERROR: --name {args.name!r} is not valid. Must be 1-64 chars, "
            "alphanumeric plus '-' and '_' only.",
            file=sys.stderr,
        )
        sys.exit(2)

    if not _VALID_REGION_RE.match(args.region):
        print(f"ERROR: --region {args.region!r} is not valid. Must be alphabetic, 1-40 chars.", file=sys.stderr)
        sys.exit(2)
    if not _VALID_CURRENCY_RE.match(args.currency):
        print(f"ERROR: --currency {args.currency!r} is not valid. Must be a 3-letter ISO code (e.g. USD).", file=sys.stderr)
        sys.exit(2)
    if not _VALID_LANGUAGE_RE.match(args.language):
        print(f"ERROR: --language {args.language!r} is not valid. Must be a numeric LCID (e.g. 1033).", file=sys.stderr)
        sys.exit(2)

    check_pac_installed()

    cloud = CLOUD_FOR_RING[args.ring]
    check_auth_for_cloud(cloud)
    select_auth_profile(cloud)

    # Pre-flight: check if we have capacity for the requested env type
    # before wasting time on a doomed pac admin create.
    check_env_capacity(args.type)

    print(f"Creating env '{args.name}' (type={args.type}, ring={args.ring})...", file=sys.stderr)

    result = create_env(args.name, args.type, args.region, args.currency, args.language)
    result["envName"] = args.name
    result["ring"] = args.ring

    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
