# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Static checks for samples/ topic changes.

Each check returns a Result. The CLI aggregates Results into a summary block
matching .github/agents/skills/validate-sample-topic/SKILL.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Iterable

import yaml
from defusedxml.ElementTree import ParseError as _XMLParseError
from defusedxml.ElementTree import fromstring as _xml_fromstring

SAMPLES_ROOT = "samples"


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NA = "N-A"


@dataclass
class Result:
    name: str
    status: Status
    details: list[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.details.append(msg)
        if self.status is Status.NA:
            self.status = Status.FAIL
        elif self.status is Status.PASS:
            self.status = Status.FAIL


@dataclass
class ChangedFile:
    path: str  # forward-slash, repo-relative
    change_type: str  # "A" added, "M" modified, "D" deleted, "R" renamed, etc.

    @property
    def is_new(self) -> bool:
        return self.change_type.upper().startswith("A")

    @property
    def is_deleted(self) -> bool:
        return self.change_type.upper().startswith("D")


# ---- helpers ----------------------------------------------------------------

_PASCAL_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")

# Secrets / internal URL signatures. Conservative on purpose.
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    ("private-key-block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}\b", re.IGNORECASE)),
    ("password-assignment", re.compile(r"\b(?:password|passwd|client_secret|api_key)\s*[:=]\s*['\"][^'\"\s]{6,}", re.IGNORECASE)),
    ("internal-host", re.compile(r"\b[a-z0-9-]+\.(?:corp\.microsoft\.com|redmond\.corp\.microsoft\.com|msft\.net)\b", re.IGNORECASE)),
]


def _read_text(repo_root: Path, rel: str) -> str | None:
    p = repo_root / rel
    if not p.exists() or not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="utf-8", errors="replace")


def _topic_folder_for(path: str) -> str | None:
    """Return the samples/<Area>/.../<TopicFolder>/ prefix for a path, or None."""
    parts = PurePosixPath(path).parts
    if len(parts) < 3 or parts[0] != SAMPLES_ROOT:
        return None
    # samples/<Area>/<Topic>/...  (Facilities, ServiceNow — flat)
    # samples/<Area>/<Sub>/<Topic>/...  (Workday*)
    if parts[1] in {"WorkdayCustomEngineAgent", "WorkdayDeclarativeAgent"}:
        # Require a file *inside* the topic folder, i.e. at least
        # samples/<Area>/<Sub>/<Topic>/<file>. Otherwise a subgroup-level
        # file such as samples/WorkdayDeclarativeAgent/Employee/README.md
        # would be misidentified as its own topic folder.
        if len(parts) < 5:
            return None
        return "/".join(parts[:4])
    # Require a file *inside* the topic folder for flat areas too: an
    # area-level file such as samples/Facilities/README.md must not be
    # treated as its own topic folder.
    if len(parts) < 4:
        return None
    return "/".join(parts[:3])


# ---- checks -----------------------------------------------------------------


def check_yaml_parse(repo_root: Path, changed: list[ChangedFile]) -> Result:
    res = Result("YAML parse", Status.NA)
    yamls = [c for c in changed if c.path.endswith(".yaml") and not c.is_deleted and c.path.startswith(SAMPLES_ROOT + "/")]
    if not yamls:
        return res
    res.status = Status.PASS
    for c in yamls:
        text = _read_text(repo_root, c.path)
        if text is None:
            continue
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            res.add(f"{c.path}: {exc.__class__.__name__}: {exc}")
    return res


def check_adaptive_dialog_kind(repo_root: Path, changed: list[ChangedFile]) -> Result:
    res = Result("AdaptiveDialog kind", Status.NA)
    topics = [c for c in changed if c.path.endswith("/topic.yaml") and not c.is_deleted]
    if not topics:
        return res
    res.status = Status.PASS
    for c in topics:
        text = _read_text(repo_root, c.path)
        if text is None:
            continue
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError:
            # YAML-parse check already reports it; skip here.
            continue
        if not isinstance(doc, dict) or doc.get("kind") != "AdaptiveDialog":
            res.add(f"{c.path}: missing or wrong top-level 'kind: AdaptiveDialog'")
    return res


def check_xml_parse(repo_root: Path, changed: list[ChangedFile]) -> Result:
    res = Result("XML parse", Status.NA)
    xmls = [c for c in changed if c.path.endswith(".xml") and not c.is_deleted and c.path.startswith(SAMPLES_ROOT + "/")]
    if not xmls:
        return res
    res.status = Status.PASS
    for c in xmls:
        text = _read_text(repo_root, c.path)
        if text is None:
            continue
        try:
            _xml_fromstring(text)
        except _XMLParseError as exc:
            res.add(f"{c.path}: {exc}")
    return res


def check_filename_convention(
    repo_root: Path, changed: list[ChangedFile], whitelist: dict
) -> Result:
    res = Result("Filename convention (new)", Status.NA)
    exempt_paths = set(whitelist.get("filename_exemptions") or [])
    exempt_substrings = list(whitelist.get("filename_exemption_substrings") or [])
    new_xmls = [
        c for c in changed
        if c.is_new and c.path.endswith(".xml") and c.path.startswith(SAMPLES_ROOT + "/")
    ]
    if not new_xmls:
        return res
    res.status = Status.PASS
    for c in new_xmls:
        if c.path in exempt_paths:
            continue
        base = PurePosixPath(c.path).name
        if any(s in base for s in exempt_substrings):
            continue
        if not base.startswith("msdyn_"):
            res.add(f"{c.path}: new XML must start with 'msdyn_'")
        if base.endswith("..xml"):
            res.add(f"{c.path}: trailing-dot filename not allowed for new files")
    return res


def check_folder_convention(
    repo_root: Path, changed: list[ChangedFile], whitelist: dict
) -> Result:
    """For each *new* topic folder represented in the diff, verify PascalCase
    + presence of topic.yaml, at least one *.xml, and README.md."""
    res = Result("Folder convention (new, incl. README.md)", Status.NA)
    exempt_folders = set(whitelist.get("folder_exemptions") or [])

    by_topic: dict[str, list[ChangedFile]] = {}
    for c in changed:
        tf = _topic_folder_for(c.path)
        if tf:
            by_topic.setdefault(tf, []).append(c)

    # A topic folder is "new" only if its topic.yaml is being added in this
    # diff. Otherwise additions (e.g. a missing README.md) to an existing
    # topic would be misclassified as a new topic and re-validated against
    # PascalCase / required-files rules — making it impossible to backfill
    # docs in documented/legacy non-PascalCase folders.
    new_topic_folders = [
        tf for tf, files in by_topic.items()
        if any(f.is_new and PurePosixPath(f.path).name == "topic.yaml" for f in files)
    ]
    if not new_topic_folders:
        return res
    res.status = Status.PASS

    for tf in new_topic_folders:
        if tf in exempt_folders:
            continue
        folder_name = PurePosixPath(tf).name
        if not _PASCAL_RE.match(folder_name):
            res.add(f"{tf}: folder name must be PascalCase")
        folder_path = repo_root / tf
        if not folder_path.is_dir():
            res.add(f"{tf}: folder not found on disk")
            continue
        names = {p.name for p in folder_path.iterdir() if p.is_file()}
        if "topic.yaml" not in names:
            res.add(f"{tf}: missing topic.yaml")
        if not any(n.endswith(".xml") for n in names):
            res.add(f"{tf}: missing at least one *.xml")
        if "README.md" not in names:
            res.add(f"{tf}: missing README.md (required for new topics)")
    return res


# Doc/scaffolding files allowed at samples/ or area/sub-grouping level without
# being inside a topic folder.
_DOC_BASENAMES = {"README.md", "AGENTS.md", ".gitkeep"}


def check_diff_scope(repo_root: Path, changed: list[ChangedFile]) -> Result:
    """Every changed path must be under samples/, and the diff must touch at
    most one topic folder. Area- and root-level README/AGENTS docs are allowed
    outside a topic folder."""
    res = Result("Diff scope (samples/ only)", Status.PASS)
    if not changed:
        res.status = Status.NA
        return res
    topic_folders: set[str] = set()
    for c in changed:
        if not c.path.startswith(SAMPLES_ROOT + "/"):
            res.add(f"{c.path}: outside samples/")
            continue
        tf = _topic_folder_for(c.path)
        if tf is None:
            if PurePosixPath(c.path).name in _DOC_BASENAMES:
                continue
            res.add(f"{c.path}: not inside a topic folder and not a doc file")
            continue
        topic_folders.add(tf)
    if len(topic_folders) > 1:
        res.add(f"diff touches multiple topic folders: {sorted(topic_folders)}")
    return res


def check_secrets(repo_root: Path, changed: list[ChangedFile]) -> Result:
    # Note: scans the *full current contents* of each changed file, not just
    # the added/removed hunks. Pre-existing matches elsewhere in a touched
    # file will be reported, and secrets that were removed by the PR will
    # not appear here (the file may no longer be in `changed`, and if it is,
    # only the post-change contents are scanned).
    res = Result("Secrets / internal URLs", Status.PASS)
    scanned = 0
    for c in changed:
        if c.is_deleted:
            continue
        if not c.path.startswith(SAMPLES_ROOT + "/"):
            continue
        text = _read_text(repo_root, c.path)
        if text is None:
            continue
        scanned += 1
        for label, pat in _SECRET_PATTERNS:
            m = pat.search(text)
            if m:
                # Do not log the matched value: it may be a real secret.
                # Report file, label, and 1-based line number only.
                line_no = text.count("\n", 0, m.start()) + 1
                res.add(f"{c.path}:{line_no}: {label} match (value redacted)")
    if scanned == 0:
        res.status = Status.NA
    return res


# ---- runner -----------------------------------------------------------------


CHECK_ORDER = [
    "YAML parse",
    "AdaptiveDialog kind",
    "XML parse",
    "Filename convention (new)",
    "Folder convention (new, incl. README.md)",
    "Diff scope (samples/ only)",
    "Secrets / internal URLs",
]


def run_all_checks(
    repo_root: Path, changed: Iterable[ChangedFile], whitelist: dict | None = None
) -> list[Result]:
    whitelist = whitelist or {}
    changed_list = list(changed)
    return [
        check_yaml_parse(repo_root, changed_list),
        check_adaptive_dialog_kind(repo_root, changed_list),
        check_xml_parse(repo_root, changed_list),
        check_filename_convention(repo_root, changed_list, whitelist),
        check_folder_convention(repo_root, changed_list, whitelist),
        check_diff_scope(repo_root, changed_list),
        check_secrets(repo_root, changed_list),
    ]
