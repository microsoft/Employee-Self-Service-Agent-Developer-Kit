# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Review Findings Catalog + Ledger

Persists /review findings and reconciles them across runs, following the ESS
hardening-analyzer's model (issue-catalog + resolved-issue-ledger) scoped to the
maker workflow. Two artifacts under .local/review-findings/ (gitignored):

  <solution>-catalog.json         per-scope findings catalog (this run's state)
  resolved-issue-ledger.jsonl     shared, append-only resolution evidence

The `solution` field is the review scope identifier — a single topic today, a
whole ISV or solution later. Nothing here assumes a single topic; a finding's
files[] can span several files, so widening the review needs no schema change.
(The field is named `solution` to stay valid against the ESS analyzer's ledger
schema; its value is whatever scope was reviewed.)

Why a script (not the agent): /review's lenses are agentic and LLM coverage is
nondeterministic — a finding missing from a later run is NOT evidence it was
fixed. Two things must therefore be mechanical: the carry-forward rule ("absence
is not resolution"), and staleness. This script computes a sha256 evidence hash of
each file a finding implicates; on a later run, a finding that was not re-detected
is still 'active' if its files are unchanged (hash matches), and is flagged
evidence-stale if any file changed (hash mismatch) — an objective signal to
re-verify, not an LLM guess.

Finding identity across runs is the semantic id (a stable kebab-case slug the
agent reuses). Status is 'active', 'suppressed', or 'resolved'; 'resolved' requires
a matching resolved-issue-ledger.jsonl entry (written when /update confirms a fix,
or when /review confirms an evidence-stale finding's node is gone). 'suppressed' is
a re-detected finding the maker dismissed (not-a-bug/wont-fix/false-positive), kept
out of the active report until its evidence changes.

Catalog integrity: this script is the ONLY sanctioned way to write a catalog, and
it validates every catalog-bound finding against the finding contract (required
fields id/title/severity/reachability/root_cause/concrete_fix + a non-empty files[]
for the evidence hash). A run whose findings use the wrong field names or omit
files[] is REJECTED (exit 2) and no catalog is written — so an improvised scanner
or hand-written catalog fails loudly instead of persisting schema-broken state.

Scope invariant: a finding belongs to exactly one catalog per review scope (the
`solution` value). The same semantic id can legitimately appear under different
scopes, so the shared ledger is keyed by (solution, issue_id) — any resolution
match against the ledger MUST scope by solution, never by issue_id alone, or one
scope's resolution would wrongly clear another's. (This merge reads the ledger
back to suppress dismissed findings and scopes that lookup by (solution, issue_id)
via _latest_ledger_record, so the requirement is enforced, not latent.)

Usage:
    # findings from a file (preferred — the command text is identical across runs,
    # so an approval sticks; the run-specific data lives in the file, not the command):
    python scripts/merge_findings.py --solution <id> --current run.json
    python scripts/merge_findings.py --solution <id> --current run.json --resolve resolved.json
    # or piped on stdin (also valid; no temp file, no shell heredoc):
    Get-Content run.json | python scripts/merge_findings.py --solution <id> --current -
    python scripts/merge_findings.py --solution <id> --show
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SCHEMA_VERSION = "1.0.0"
_SEVERITY_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
# Keys the agent must supply on every catalog-bound finding (the script assigns
# status / evidence_stale / evidence_hashes / first_seen / last_seen itself).
# Enforced so an improvised writer using the wrong field names (e.g. description /
# location / fix instead of root_cause / files / concrete_fix) fails loudly instead
# of persisting a schema-broken catalog. `verification` is optional (defaults static).
_REQUIRED_FINDING_KEYS = ("id", "title", "severity", "reachability", "root_cause", "concrete_fix")
# Canonical reachability enum (see finding-contract.md). Drives severity/report
# logic downstream, so a malformed value must be rejected, not persisted.
_REACHABILITY_KINDS = {
    "REACHABLE_NORMAL_UI",
    "REACHABLE_NORMAL_UI_WITH_DATA_PRECONDITION",
    "NOT_REACHABLE_VIA_BOT_UI",
    "OPERATOR_OR_HYGIENE_ONLY",
}
# Maker-facing resolutions are fixed / not-a-bug / wont-fix; the other two are
# retained for compatibility with the analyzer ledger enum (v1.2.0).
_RESOLUTION_KINDS = {"fixed", "wont-fix", "not-a-bug", "defense-in-depth", "false-positive"}
# Resolutions that mean "this is not a defect the maker will act on." A
# deterministic detector re-emits the same pattern every run, so once dismissed
# these must stay suppressed (not resurface as active) until the topic's evidence
# changes. `fixed` / `defense-in-depth` are code-change intents, so re-detection of
# those legitimately reopens the finding (a regression) and they are NOT dismissals.
_DISMISSAL_KINDS = {"not-a-bug", "wont-fix", "false-positive"}
_VERIFICATION_KINDS = {"static", "needs-runtime-test"}
_REVIEW_DIR = Path(".local") / "review-findings"
# Anchor for validating agent-supplied paths stay inside the maker-skills tree
# (scripts/ lives directly under it). Used to reject path traversal in --solution
# and in finding files[].path before any filesystem read/write.
_SKILL_ROOT = Path(__file__).resolve().parent.parent


def _safe_scope_id(value: str) -> str:
    """A review scope id (`--solution`) must be a bare stem, not a path.

    Rejects separators / `..` / absolute paths so it cannot steer catalog_path()
    to read or write a `*-catalog.json` outside _REVIEW_DIR.
    """
    if not value or "/" in value or "\\" in value or ".." in value or Path(value).is_absolute():
        print(
            f"ERROR: invalid --solution '{value}': must be a bare topic/scope id, not a path.",
            file=sys.stderr,
        )
        sys.exit(2)
    return value


def _safe_read_path(p: str) -> "Path | None":
    """Resolve a finding's files[].path inside the skill tree, or None if it escapes.

    Guards evidence hashing against reading an arbitrary file via an absolute or
    `..`-laden files[].path in agent-supplied findings.
    """
    if Path(p).is_absolute():
        return None
    resolved = (_SKILL_ROOT / p).resolve()
    try:
        resolved.relative_to(_SKILL_ROOT)
    except ValueError:
        return None
    return resolved


def _resolution_of(finding: dict) -> str:
    val = str(finding.get("resolution", "fixed")).strip()
    return val if val in _RESOLUTION_KINDS else "fixed"


def _verification_of(finding: dict) -> str:
    val = str(finding.get("verification", "static")).strip()
    return val if val in _VERIFICATION_KINDS else "static"


def _resolved_by_of(finding: dict) -> str:
    val = str(finding.get("resolved_by", "")).strip()
    return val or "review-skill"


def load_config() -> dict:
    config_path = Path(".local") / "config.json"
    if not config_path.is_file():
        print("ERROR: .local/config.json not found. Run /setup first.", file=sys.stderr)
        sys.exit(1)
    return json.loads(config_path.read_text(encoding="utf-8"))


def catalog_path(solution: str) -> Path:
    return _REVIEW_DIR / f"{solution}-catalog.json"


def ledger_path() -> Path:
    return _REVIEW_DIR / "resolved-issue-ledger.jsonl"


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_findings_source(value: str) -> tuple[object, str | None]:
    """Read a findings document from a file path or stdin.

    `value` of "-" reads from stdin, so the caller can pipe findings JSON
    directly, with no temp file to mis-path (a Unix `/tmp` path does not exist on
    Windows) and no shell heredoc (unsupported in PowerShell). Returns (doc, None)
    on success or (None, error) with a message that distinguishes not-found from
    invalid JSON.
    """
    if value == "-":
        raw = sys.stdin.read()
        if not raw.strip():
            return None, "no findings JSON received on stdin"
        try:
            return json.loads(raw), None
        except json.JSONDecodeError as e:
            return None, f"invalid JSON on stdin ({e})"
    path = Path(value)
    if not path.is_file():
        return None, f"file not found: {value}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as e:
        return None, f"invalid JSON in {value} ({e})"
    except OSError as e:
        return None, f"could not read {value} ({e})"


def _read_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        out.append(obj)
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return out


def _issues_of(doc) -> list[dict]:
    """Accept a bare list, {issues:[...]}, or {findings:[...]}."""
    if isinstance(doc, list):
        return [f for f in doc if isinstance(f, dict)]
    if isinstance(doc, dict):
        for key in ("issues", "findings"):
            if isinstance(doc.get(key), list):
                return [f for f in doc[key] if isinstance(f, dict)]
    return []


def sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _file_paths(finding: dict) -> list[str]:
    files = finding.get("files")
    paths: list[str] = []
    if isinstance(files, list):
        for f in files:
            if isinstance(f, dict) and isinstance(f.get("path"), str):
                paths.append(f["path"])
            elif isinstance(f, str):
                paths.append(f)
    return paths


def _nonempty_str(val) -> bool:
    return isinstance(val, str) and val.strip() != ""


def validate_current_findings(findings: list[dict]) -> list[str]:
    """Return a list of human-readable errors for catalog-bound findings.

    A finding must carry every _REQUIRED_FINDING_KEYS field as a non-empty string,
    a severity in {HIGH, MEDIUM, LOW}, and a non-empty files[] that yields at least
    one path (so evidence_hashes can be computed — an empty files[] silently breaks
    the whole staleness / /update-locate design). Empty in → empty error list.
    """
    errors: list[str] = []
    seen_ids: set[str] = set()
    for i, f in enumerate(findings):
        where = str(f.get("id", "")).strip() or f"#{i}"
        for key in _REQUIRED_FINDING_KEYS:
            if not _nonempty_str(f.get(key)):
                errors.append(f"[{where}] missing or empty required field '{key}'")
        sev = str(f.get("severity", "")).strip()
        if sev and sev not in _SEVERITY_RANK:
            errors.append(f"[{where}] severity '{sev}' is not one of HIGH/MEDIUM/LOW")
        reach = str(f.get("reachability", "")).strip()
        if reach and reach not in _REACHABILITY_KINDS:
            errors.append(
                f"[{where}] reachability '{reach}' is not one of "
                f"{'/'.join(sorted(_REACHABILITY_KINDS))}"
            )
        verif = str(f.get("verification", "")).strip()
        if verif and verif not in _VERIFICATION_KINDS:
            errors.append(
                f"[{where}] verification '{verif}' is not one of {'/'.join(sorted(_VERIFICATION_KINDS))}"
            )
        paths = _file_paths(f)
        if not paths:
            errors.append(f"[{where}] files[] is missing or has no usable path (evidence_hashes would be empty)")
        else:
            for p in paths:
                if _safe_read_path(p) is None:
                    errors.append(
                        f"[{where}] files[].path '{p}' is absolute or escapes the workspace; "
                        "evidence hashing would store sha256 null and misfire staleness"
                    )
        fid = str(f.get("id", "")).strip()
        if fid:
            if fid in seen_ids:
                errors.append(f"[{fid}] duplicate id within this run (ids are the cross-run identity)")
            seen_ids.add(fid)
    return errors


def validate_resolutions(resolved: list[dict]) -> list[str]:
    """Errors for `--resolve` findings whose `resolution` is present but not a valid
    kind. An absent `resolution` is fine (it legitimately defaults to `fixed`); a
    *wrong* value must be rejected, not coerced — the ledger is append-only, so a
    silent coercion of e.g. `not-a-bug` to `fixed` would permanently misrecord why
    the finding was resolved.
    """
    errors: list[str] = []
    for i, f in enumerate(resolved):
        where = str(f.get("id", "")).strip() or f"#{i}"
        res = str(f.get("resolution", "")).strip()
        if res and res not in _RESOLUTION_KINDS:
            errors.append(
                f"[{where}] resolution '{res}' is not one of {'/'.join(sorted(_RESOLUTION_KINDS))}"
            )
    return errors


def evidence_hashes(finding: dict) -> list[dict]:
    """Current sha256 of every file the finding implicates (files[].path).

    Only paths that resolve inside the skill tree are read; a path that escapes
    (absolute or via `..`) is recorded with sha256 None rather than being read.
    """
    out: list[dict] = []
    for p in _file_paths(finding):
        safe = _safe_read_path(p)
        out.append({"file": p, "sha256": sha256_file(safe) if safe else None})
    return out


def _hashes_match(stored: list[dict]) -> bool:
    """True if every stored evidence hash still equals the file's current hash.

    Resolve each stored path through `_safe_read_path` (the same skill-root
    anchoring `evidence_hashes` used to compute the stored value) so the check is
    independent of the current working directory. A path that no longer resolves
    inside the tree, or a stored hash of None (the file was unreadable at store
    time), counts as a mismatch — never as "unchanged".
    """
    if not stored:
        return False
    for entry in stored:
        if not isinstance(entry, dict):
            return False
        stored_sha = entry.get("sha256")
        if not stored_sha:
            return False
        safe = _safe_read_path(str(entry.get("file", "")))
        if safe is None or sha256_file(safe) != stored_sha:
            return False
    return True


def _higher_severity(a: str, b: str) -> str:
    return a if _SEVERITY_RANK.get(a, 0) >= _SEVERITY_RANK.get(b, 0) else b


def _next_resolution_ref(issue_id: str, ledger: list[dict]) -> str:
    n = sum(1 for e in ledger if e.get("issue_id") == issue_id) + 1
    return f"{issue_id}:r{n}"


def _latest_ledger_record(issue_id: str, solution: str, ledger: list[dict]) -> "dict | None":
    """The most recent ledger line for this (solution, issue_id), or None.

    The ledger is append-only, so the last matching line wins.
    """
    match = None
    for entry in ledger:
        if entry.get("issue_id") == issue_id and entry.get("solution") == solution:
            match = entry
    return match


def _active_dismissal(
    issue_id: str, solution: str, ledger: list[dict],
    resolutions: dict[str, dict], current_hashes: list[dict],
) -> "dict | None":
    """Return {ref, resolution} if a re-detected finding should stay suppressed.

    A finding is suppressed when it was dismissed (not-a-bug / wont-fix /
    false-positive) and its evidence is unchanged since the dismissal:

    - dismissed *this* run (in `resolutions`): evidence is current by definition;
    - dismissed in a *prior* run (latest ledger line): only while the stored
      evidence hash still matches the finding's current first-file hash. A topic
      edit moves the hash and reopens the finding as active for re-review.
    """
    this_run = resolutions.get(issue_id)
    if this_run is not None and this_run.get("resolution") in _DISMISSAL_KINDS:
        return {"ref": this_run.get("ref"), "resolution": this_run["resolution"]}

    latest = _latest_ledger_record(issue_id, solution, ledger)
    if latest is not None and latest.get("resolution") in _DISMISSAL_KINDS:
        stored_hash = latest.get("evidence_hash")
        current_hash = current_hashes[0]["sha256"] if current_hashes else None
        if stored_hash is not None and stored_hash == current_hash:
            return {"ref": latest.get("id"), "resolution": latest["resolution"]}
    return None


def merge(
    prior: list[dict], current: list[dict], resolutions: dict[str, dict], run_date: str,
    ledger: list[dict], solution: str,
) -> list[dict]:
    prior_by_id = {str(f.get("id", "")).strip(): f for f in prior}
    current_by_id = {str(f.get("id", "")).strip(): f for f in current}
    merged: list[dict] = []

    # Current findings are active — unless the maker dismissed them and the
    # evidence is unchanged, in which case they stay suppressed rather than
    # resurfacing every run. A re-detected finding that was previously *fixed*
    # reopens automatically here (the code came back).
    for issue_id, cur in current_by_id.items():
        rec = dict(cur)
        cur_hashes = evidence_hashes(cur)
        rec["evidence_stale"] = False
        rec["evidence_hashes"] = cur_hashes
        rec["verification"] = _verification_of(cur)
        rec.pop("resolution", None)
        rec.pop("resolution_ref", None)
        old = prior_by_id.get(issue_id)
        if old is not None:
            rec["severity"] = _higher_severity(
                str(rec.get("severity", "LOW")), str(old.get("severity", "LOW"))
            )
            rec["first_seen"] = old.get("first_seen", run_date)
        else:
            rec["first_seen"] = run_date
        rec["last_seen"] = run_date
        dismissal = _active_dismissal(issue_id, solution, ledger, resolutions, cur_hashes)
        if dismissal is not None:
            rec["status"] = "suppressed"
            rec["resolution"] = dismissal["resolution"]
            rec["resolution_ref"] = dismissal["ref"]
        else:
            rec["status"] = "active"
        merged.append(rec)

    # Prior findings not re-detected this run.
    for issue_id, old in prior_by_id.items():
        if issue_id in current_by_id:
            continue
        rec = dict(old)
        if issue_id in resolutions:
            # Resolved this run (fixed, or dismissed as not-a-bug / wont-fix).
            rec["status"] = "resolved"
            rec["resolution"] = resolutions[issue_id]["resolution"]
            rec["resolution_ref"] = resolutions[issue_id]["ref"]
        elif old.get("status") == "resolved":
            # Resolved in a prior run — prune from the catalog (the ledger is the
            # permanent record). Re-detection reopens it as active via the loop above.
            continue
        elif old.get("status") == "suppressed":
            # A dismissed finding that is no longer re-detected: keep it suppressed
            # rather than flipping it back to active on absence.
            rec["status"] = "suppressed"
        else:
            # Absence is not resolution. Keep the original evidence hashes so the
            # staleness signal persists; a file change flips it to evidence-stale.
            rec["status"] = "active"
            rec["evidence_stale"] = not _hashes_match(old.get("evidence_hashes", []))
        merged.append(rec)

    return merged


def append_resolutions(
    resolved_findings: list[dict], lookups: list[list[dict]], solution: str, run_date: str,
    ledger: list[dict],
) -> dict[str, dict]:
    """Append one ledger line per resolved issue; return issue_id -> {ref, resolution}.

    Each resolved finding may carry a `resolution` kind (default `fixed`; a maker
    dismisses a false positive with `not-a-bug` or declines with `wont-fix`) and a
    `resolved_by` identity (default `review-skill`; e.g. `update-skill` for a fix,
    `maker` for a dismissal). A resolved finding's files[] (for the evidence hash)
    are taken from its own entry if present, else from the first lookup list that
    has it (prior catalog, then current run).
    """
    resolved = {str(f.get("id", "")).strip(): f for f in resolved_findings if str(f.get("id", "")).strip()}
    if not resolved:
        return {}
    by_id: dict[str, dict] = {}
    for source in [resolved_findings, *lookups]:
        for f in source:
            fid = str(f.get("id", "")).strip()
            if fid and (fid not in by_id or not _file_paths(by_id[fid])):
                if _file_paths(f) or fid not in by_id:
                    by_id[fid] = f
    out: dict[str, dict] = {}
    lines: list[str] = []
    for issue_id in sorted(resolved):
        resolution = _resolution_of(resolved[issue_id])
        finding = by_id.get(issue_id, {})
        hashes = evidence_hashes(finding) if finding else []
        ev_hash = hashes[0]["sha256"] if hashes else None
        latest = _latest_ledger_record(issue_id, solution, ledger)
        if (
            latest is not None
            and latest.get("resolution") == resolution
            and latest.get("evidence_hash") == ev_hash
        ):
            # Idempotent: an identical resolution with identical evidence is already
            # recorded. Reuse the existing ref instead of appending a duplicate :rN
            # line (prevents append-only bloat when the same dismissal is re-passed).
            out[issue_id] = {"ref": latest.get("id"), "resolution": resolution}
            continue
        ref = _next_resolution_ref(issue_id, ledger + [{"issue_id": i} for i in out])
        out[issue_id] = {"ref": ref, "resolution": resolution}
        entry = {
            "id": ref,
            "solution": solution,
            "issue_id": issue_id,
            "resolution": resolution,
            "resolved_date": run_date,
            "resolved_by": _resolved_by_of(resolved[issue_id]),
            "evidence_hash": ev_hash,
        }
        lines.append(json.dumps(entry))
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")
    return out


def summarize(issues: list[dict]) -> dict[str, int]:
    counts = {"active": 0, "resolved": 0, "suppressed": 0, "evidence_stale": 0}
    for f in issues:
        status = f.get("status", "active")
        counts[status] = counts.get(status, 0) + 1
        if f.get("evidence_stale"):
            counts["evidence_stale"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge a /review run into the findings catalog + ledger.")
    parser.add_argument("--solution", "-s", required=True, help="Review scope id (a topic stem today; an ISV/solution later).")
    parser.add_argument("--current", "-c", help="Findings for this run: a file path, or '-' to read JSON from stdin (list, or {issues:[...]}).")
    parser.add_argument("--resolve", "-r", help="JSON listing findings resolved this run (appended to the ledger).")
    parser.add_argument("--show", action="store_true", help="Print the catalog and exit.")
    args = parser.parse_args()

    load_config()
    _safe_scope_id(args.solution)
    cpath = catalog_path(args.solution)

    if args.show:
        existing = _read_json(cpath)
        if existing is None:
            print(f"No findings catalog for '{args.solution}'.")
            return 0
        print(json.dumps(existing, indent=2))
        return 0

    if not args.current:
        print("ERROR: --current is required unless --show is used.", file=sys.stderr)
        return 1

    current_doc, read_err = read_findings_source(args.current)
    if read_err is not None:
        print(f"ERROR: could not read current findings ({read_err})", file=sys.stderr)
        return 1
    current = _issues_of(current_doc)

    errors = validate_current_findings(current)
    if errors:
        src = "stdin" if args.current == "-" else args.current
        print(
            f"ERROR: {len(errors)} finding(s) from {src} do not match the finding contract "
            "(id/title/severity/reachability/root_cause/concrete_fix + files[]). "
            "Catalog NOT written. A catalog may only be produced by this script from contract-shaped findings; "
            "do not hand-write catalogs or improvise a scanner.",
            file=sys.stderr,
        )
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 2

    resolved_findings: list[dict] = []
    if args.resolve:
        resolved_findings = _issues_of(_read_json(Path(args.resolve)) or [])
        res_errors = validate_resolutions(resolved_findings)
        if res_errors:
            src = args.resolve
            print(
                f"ERROR: {len(res_errors)} resolution(s) from {src} use an invalid kind. "
                "Nothing was written to the ledger (it is append-only). Fix and re-run.",
                file=sys.stderr,
            )
            for e in res_errors:
                print(f"  - {e}", file=sys.stderr)
            return 2

    if cpath.is_file():
        try:
            prior_doc = json.loads(cpath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(
                f"ERROR: existing catalog {cpath} is unreadable/corrupt ({e}). "
                "Refusing to overwrite it, which would silently drop the tracked findings "
                "and resolution history. Fix or remove the file, then re-run.",
                file=sys.stderr,
            )
            return 1
    else:
        prior_doc = None
    prior = _issues_of(prior_doc) if prior_doc is not None else []

    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger = _read_jsonl(ledger_path())
    resolutions = append_resolutions(
        resolved_findings, [prior, current], args.solution, run_date, ledger
    )

    merged = merge(prior, current, resolutions, run_date, ledger, args.solution)

    catalog = {
        "schema_version": _SCHEMA_VERSION,
        "solution": args.solution,
        "date": run_date,
        "mode": "review",
        "issues": merged,
    }
    cpath.parent.mkdir(parents=True, exist_ok=True)
    cpath.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")

    counts = summarize(merged)
    print(f"Catalog updated: {cpath}")
    print(
        f"  active={counts.get('active', 0)}  resolved={counts.get('resolved', 0)}  "
        f"suppressed={counts.get('suppressed', 0)}  evidence-stale={counts.get('evidence_stale', 0)}"
    )
    if counts.get("evidence_stale"):
        print("  NOTE: evidence-stale findings had their files change but were not re-detected — re-verify (likely fixed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
