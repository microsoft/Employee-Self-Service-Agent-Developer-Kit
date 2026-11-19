# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Bundled topic text and byte identity, independent of the converter runtime."""

from dataclasses import dataclass
import hashlib
from pathlib import Path

from topic_actions_discovery import _fail


CONTENT_ROOT = Path(__file__).resolve().parents[1] / "src" / "reference" / "topic-actions" / "content"


@dataclass(frozen=True)
class TopicContent:
    stem: str
    yaml: str
    digest: str


def load_set_content(topic_set: dict) -> tuple[TopicContent, ...]:
    if "contentFolder" not in topic_set:
        return ()
    contents = []
    try:
        root = CONTENT_ROOT.resolve()
        relative = Path(topic_set["contentFolder"])
        folder = (root / relative).resolve()
        if relative.is_absolute() or not folder.is_relative_to(root) or folder == root:
            _fail("invalid_content_path")
        if not folder.is_dir():
            _fail("content_unreadable")
        paths = sorted(folder.glob("*.mcs.yml"))
        stems = {path.name.removesuffix(".mcs.yml") for path in paths}
        for variant in topic_set["sourceVariants"]:
            members = [name.partition(".topic.")[2] for name in variant["memberSchemaNames"]]
            if not all(members) or len(set(members)) != len(members) or set(members) != stems:
                _fail("content_members_mismatch")
        for path in paths:
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                _fail("invalid_content_path")
            data = resolved.read_bytes()
            contents.append(TopicContent(
                path.name.removesuffix(".mcs.yml"), data.decode("utf-8"), hashlib.sha256(data).hexdigest(),
            ))
    except (OSError, UnicodeError):
        _fail("content_unreadable")
    return tuple(contents)
