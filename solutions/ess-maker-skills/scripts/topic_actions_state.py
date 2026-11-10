# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Local original topic states and durable, non-replayable write bookkeeping."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from topic_actions_components import normalize_state
from topic_actions_discovery import _identity, _target
from topic_actions_planning import _digest


class TopicStateError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__("Original topic states could not be safely established.")
        self.reason = reason


def _valid_topic(topic) -> bool:
    return (
        isinstance(topic, dict) and set(topic) == {"schemaName", "state", "contentDigest"}
        and isinstance(topic["schemaName"], str) and bool(topic["schemaName"].strip())
        and topic["state"] in ("On", "Off")
        and isinstance(topic["contentDigest"], str) and len(topic["contentDigest"]) == 64
        and not set(topic["contentDigest"]) - set("0123456789abcdef")
    )


def _topics(evidence) -> dict:
    from topic_actions_execution import _component_map, _preservation_content

    result, schemas = {}, set()
    for identity, component in _component_map(evidence.body).items():
        if component.get("$kind") != "DialogComponent":
            continue
        schema = component.get("schemaName")
        state = normalize_state(component.get("state"), component.get("status"))[0]
        if (
            not isinstance(schema, str) or not schema.strip()
            or schema.casefold() in schemas or state not in ("On", "Off")
            or _identity(component.get("parentBotId")) != evidence.snapshot.evidence.target.agent_id
        ):
            raise TopicStateError("baseline_topic_evidence_unavailable")
        schemas.add(schema.casefold())
        result[identity] = {
            "schemaName": schema, "state": state,
            "contentDigest": _digest(_preservation_content(component, state_change=True)),
        }
    if not result:
        raise TopicStateError("baseline_topic_evidence_unavailable")
    return result


class TopicStateStore:
    """Keep the original baseline immutable; persist intent before dispatch."""

    def __init__(self, root: Path, target, *, first_use: bool = False) -> None:
        self.target = _target(target)
        name = "_".join(asdict(self.target).values())
        self.path = root / ".local" / "topic-actions" / f"{name}.sqlite3"
        self.first_use = first_use

    @contextmanager
    def _connection(self, *, write: bool = False):
        connection = None
        try:
            if write:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(self.path, timeout=0)
                connection.execute("PRAGMA synchronous=FULL")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS state ("
                    "id INTEGER PRIMARY KEY CHECK(id=1), baseline TEXT NOT NULL, "
                    "journal TEXT NOT NULL, checksum TEXT NOT NULL)"
                )
            else:
                connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=0)
            yield connection
            if write:
                connection.commit()
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as error:
            if isinstance(error, TopicStateError):
                raise
            raise TopicStateError("baseline_storage_unavailable") from None
        finally:
            if connection is not None:
                connection.close()

    def _read(self, connection) -> dict | None:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )}
        if not tables:
            return None
        if tables != {"state"}:
            raise TopicStateError("baseline_invalid")
        row = connection.execute("SELECT baseline, journal, checksum FROM state WHERE id=1").fetchone()
        if row is None:
            return None
        data = {"baseline": json.loads(row[0]), "journal": json.loads(row[1])}
        baseline, journal = data["baseline"], data["journal"]
        if (
            _digest(data) != row[2]
            or set(baseline) != {"version", "target", "capturedAt", "topics"}
            or type(baseline["version"]) is not int or baseline["version"] != 1
            or baseline["target"] != asdict(self.target)
            or not isinstance(baseline["capturedAt"], str)
            or not isinstance(baseline["topics"], dict) or not baseline["topics"]
            or set(journal) != {"sets", "tracked", "pending"}
            or not isinstance(journal["sets"], dict) or not isinstance(journal["tracked"], dict)
        ):
            raise TopicStateError("baseline_invalid")
        for identity, topic in baseline["topics"].items():
            if (
                _identity(identity) != identity
                or not _valid_topic(topic)
            ):
                raise TopicStateError("baseline_invalid")
        for identity, topic in journal["tracked"].items():
            if (
                identity not in baseline["topics"]
                or not _valid_topic(topic)
                or topic["schemaName"] != baseline["topics"][identity]["schemaName"]
            ):
                raise TopicStateError("baseline_invalid")
        for key, members in journal["sets"].items():
            if (
                not isinstance(key, str) or not key.strip()
                or not isinstance(members, dict) or not members
                or any(
                    identity not in baseline["topics"]
                    or baseline["topics"][identity]["schemaName"] != schema
                    for identity, schema in members.items()
                )
            ):
                raise TopicStateError("baseline_invalid")
        pending = journal["pending"]
        if pending is not None:
            if (
                not isinstance(pending, dict) or set(pending) != {"id", "status", "topics", "recovering"}
                or not isinstance(pending["id"], str)
                or str(uuid.UUID(pending["id"])) != pending["id"]
                or pending["status"] not in ("in_progress", "uncertain")
                or not isinstance(pending["topics"], dict) or not pending["topics"]
                or type(pending["recovering"]) is not bool
            ):
                raise TopicStateError("baseline_invalid")
            for identity, item in pending["topics"].items():
                if (
                    identity not in baseline["topics"]
                    or not isinstance(item, dict) or set(item) != {"before", "after"}
                    or not _valid_topic(item["before"]) or item["after"] not in ("On", "Off")
                    or item["before"]["schemaName"] != baseline["topics"][identity]["schemaName"]
                    or item["before"]["state"] == item["after"]
                ):
                    raise TopicStateError("baseline_invalid")
        return data

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        with self._connection() as connection:
            return self._read(connection)

    def _save(self, connection, data, *, new=False):
        values = (
            json.dumps(data["baseline"], sort_keys=True),
            json.dumps(data["journal"], sort_keys=True), _digest(data),
        )
        if new:
            connection.execute("INSERT INTO state VALUES (1, ?, ?, ?)", values)
        else:
            # There is deliberately no UPDATE path for the original baseline.
            connection.execute(
                "UPDATE state SET journal=?, checksum=? WHERE id=1", values[1:],
            )

    @staticmethod
    def _available(data, *, restoring: bool):
        pending = data["journal"]["pending"] if data else None
        if pending and pending["status"] == "in_progress":
            raise TopicStateError("topic_operation_in_progress_or_interrupted")
        if pending and not restoring:
            raise TopicStateError("previous_write_uncertain_restore_required")

    def review(self, evidence, *, restoring: bool) -> tuple[str, dict]:
        if evidence.snapshot.evidence.target != self.target:
            raise TopicStateError("baseline_target_mismatch")
        data = self.load()
        self._available(data, restoring=restoring)
        if data is None and (restoring or not self.first_use):
            raise TopicStateError("original_baseline_missing")
        topics = data["baseline"]["topics"] if data else _topics(evidence)
        return _digest(data), {
            "status": "saved_original" if data else "capture_before_first_write",
            "capturedAt": data["baseline"]["capturedAt"] if data else None,
            "topicCount": len(topics),
            "restoreScope": "only_topics_changed_by_skill",
            "message": (
                "Original baseline is retained across operations and sessions."
                if data else
                "Approval confirms these are the original states before any topic-actions changes. "
                "They will be saved before writing. Do not approve this as first use on an already-modified agent."
            ),
        }

    def restore_keys(self) -> tuple[str, ...]:
        data = self.load()
        if data is None:
            raise TopicStateError("original_baseline_missing")
        self._available(data, restoring=True)
        keys = tuple(sorted(data["journal"]["sets"]))
        if not keys:
            raise TopicStateError("no_recorded_topic_changes")
        return keys

    @staticmethod
    def _members(snapshot) -> dict:
        result = {key: {} for key in snapshot.evidence.selected_keys}
        for key, schema, identity in snapshot.members:
            if identity is None:
                raise TopicStateError("restore_membership_changed")
            result[key][identity] = schema
        return result

    def _restore_topics(self, data, evidence) -> tuple[dict, dict]:
        current = _topics(evidence)
        original, journal = data["baseline"]["topics"], data["journal"]
        if any(
            identity not in current or current[identity]["schemaName"] != item["schemaName"]
            for identity, item in original.items()
        ):
            raise TopicStateError("baseline_topic_identity_changed")
        if self._members(evidence.snapshot) != journal["sets"]:
            raise TopicStateError("restore_membership_changed")
        expected = dict(journal["tracked"])
        pending = journal["pending"]
        if pending:
            for identity, item in pending["topics"].items():
                actual = current.get(identity)
                if (
                    actual is None or actual["schemaName"] != item["before"]["schemaName"]
                    or actual["contentDigest"] != item["before"]["contentDigest"]
                    or actual["state"] not in (item["before"]["state"], item["after"])
                ):
                    raise TopicStateError("restore_conflict")
                expected[identity] = actual
        if any(current.get(identity) != item for identity, item in expected.items()):
            raise TopicStateError("restore_conflict")
        if set(expected) - set(evidence.snapshot.evidence.selected_member_ids):
            raise TopicStateError("restore_membership_changed")
        return current, expected

    def restore_snapshot(self, evidence):
        data = self.load()
        if data is None:
            raise TopicStateError("original_baseline_missing")
        self._available(data, restoring=True)
        current, expected = self._restore_topics(data, evidence)
        desired = tuple(
            (identity, data["baseline"]["topics"][identity]["state"]
             if identity in expected else current[identity]["state"])
            for identity in evidence.snapshot.evidence.selected_member_ids
        )
        warnings = list(evidence.snapshot.warnings)
        if data["journal"]["pending"]:
            warnings.append("previous_submission_outcome_uncertain")
        if any(
            identity not in expected and (
                identity not in data["baseline"]["topics"]
                or item["state"] != data["baseline"]["topics"][identity]["state"]
            ) for identity, item in current.items()
        ):
            warnings.append("unrelated_topic_states_differ_from_original_and_will_be_preserved")
        return replace(
            evidence.snapshot, restore_states=desired, restore_revision=_digest(data),
            warnings=tuple(warnings),
        )

    def begin(self, evidence, plan, reviewed_revision: str) -> str:
        with self._connection(write=True) as connection:
            data = self._read(connection)
            if _digest(data) != reviewed_revision:
                raise TopicStateError("baseline_changed_review_required")
            self._available(data, restoring=plan.action == "restore")
            current = _topics(evidence)
            new = data is None
            if new:
                if not self.first_use or plan.action == "restore":
                    raise TopicStateError("original_baseline_missing")
                data = {
                    "baseline": {
                        "version": 1, "target": asdict(self.target),
                        "capturedAt": datetime.now(timezone.utc).isoformat(), "topics": current,
                    },
                    "journal": {"sets": {}, "tracked": {}, "pending": None},
                }
            if evidence.snapshot.evidence.target != self.target:
                raise TopicStateError("baseline_target_mismatch")
            journal = data["journal"]
            if plan.action == "restore":
                _, expected = self._restore_topics(data, evidence)
                journal["tracked"].update(expected)
            for key, members in self._members(evidence.snapshot).items():
                if key in journal["sets"] and journal["sets"][key] != members:
                    raise TopicStateError("restore_membership_changed")
                journal["sets"][key] = members
            if any(
                item.component_id not in data["baseline"]["topics"]
                or current[item.component_id]["schemaName"]
                != data["baseline"]["topics"][item.component_id]["schemaName"]
                for item in plan.delta
            ):
                raise TopicStateError("baseline_topic_identity_changed")
            operation = str(uuid.uuid4())
            journal["pending"] = {
                "id": operation, "status": "in_progress",
                "recovering": journal["pending"] is not None,
                "topics": {
                    item.component_id: {"before": current[item.component_id], "after": item.after}
                    for item in plan.delta
                },
            }
            self._save(connection, data, new=new)
        return operation

    def finish(self, operation: str, after, *, verified: bool, attempted: bool = True):
        with self._connection(write=True) as connection:
            data = self._read(connection)
            if data is None or data["journal"]["pending"]["id"] != operation:
                raise TopicStateError("baseline_changed_review_required")
            journal = data["journal"]
            pending = journal["pending"]
            if not attempted:
                if pending["recovering"]:
                    pending["status"] = "uncertain"
                else:
                    journal["pending"] = None
            elif verified:
                current = _topics(after)
                for identity, item in pending["topics"].items():
                    if (
                        current[identity]["state"] != item["after"]
                        or current[identity]["contentDigest"] != item["before"]["contentDigest"]
                    ):
                        raise TopicStateError("restore_conflict")
                    journal["tracked"][identity] = current[identity]
                journal["pending"] = None
            else:
                pending["status"] = "uncertain"
            self._save(connection, data)

    def finish_restore_noop(self, evidence, reviewed_revision: str):
        with self._connection(write=True) as connection:
            data = self._read(connection)
            if data is None or _digest(data) != reviewed_revision:
                raise TopicStateError("baseline_changed_review_required")
            self._available(data, restoring=True)
            current, expected = self._restore_topics(data, evidence)
            if any(
                current[identity]["state"] != data["baseline"]["topics"][identity]["state"]
                for identity in expected
            ):
                raise TopicStateError("restore_conflict")
            data["journal"]["tracked"].update(expected)
            data["journal"]["pending"] = None
            self._save(connection, data)
