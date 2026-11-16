# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Short-lived, single-use pending reviews; never persist an approval or token."""

from contextlib import contextmanager
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid

from topic_actions_planning import _digest


class TopicReviewError(ValueError):
    def __init__(self, reason):
        super().__init__("A fresh topic review and explicit approval are required.")
        self.reason = reason


class TopicReviewStore:
    def __init__(self, root: Path, *, clock=time.time, monotonic=time.monotonic):
        self.root = root.resolve()
        self.path = self.root / ".local" / "topic-actions" / "reviews.sqlite3"
        self.clock = clock
        self.monotonic = monotonic

    @contextmanager
    def _connection(self, *, create=False):
        connection = None
        try:
            if create:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(self.path, timeout=0)
            else:
                connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=0)
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            if create:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS pending_reviews ("
                    "id TEXT PRIMARY KEY, payload TEXT NOT NULL, checksum TEXT NOT NULL, expires REAL NOT NULL)"
                )
            yield connection
            connection.commit()
        except (OSError, sqlite3.Error):
            raise TopicReviewError("review_storage_unavailable") from None
        finally:
            if connection is not None:
                connection.close()

    def create(self, request: dict, binding: str) -> dict:
        # Caller progress belongs to the calling conversation, not durable storage.
        request = {
            key: request[key] for key in
            ("contractVersion", "target", "action", "setKeys")
        }
        request["entry"] = "direct"
        now = self.clock()
        # Older reviews included original-state capture and cannot authorize this contract.
        payload = {
            "version": 2, "workspace": str(self.root), "request": request,
            "binding": binding, "createdAt": now, "createdMonotonic": self.monotonic(),
        }
        review_id = uuid.uuid4().hex
        with self._connection(create=True) as connection:
            connection.execute("DELETE FROM pending_reviews WHERE expires <= ?", (now,))
            connection.execute(
                "INSERT INTO pending_reviews VALUES (?, ?, ?, ?)",
                (review_id, json.dumps(payload, sort_keys=True, allow_nan=False), _digest(payload), now + 300),
            )
        return {"reviewId": review_id, "expiresAt": now + 300, "expiresInSeconds": 300}

    def consume(self, review_id: str) -> dict:
        if not isinstance(review_id, str) or re.fullmatch(r"[0-9a-f]{32}", review_id) is None:
            raise TopicReviewError("review_unavailable")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload, checksum FROM pending_reviews WHERE id=?", (review_id,),
            ).fetchone()
            if row is None:
                raise TopicReviewError("review_unavailable")
            connection.execute("DELETE FROM pending_reviews WHERE id=?", (review_id,))
        # Consumption commits before validation or network work. Failures never replay.
        try:
            payload = json.loads(row[0])
            if (
                not isinstance(payload, dict) or _digest(payload) != row[1]
                or set(payload) != {
                    "version", "workspace", "request", "binding", "createdAt", "createdMonotonic",
                }
                or type(payload["version"]) is not int or payload["version"] != 2
                or payload["workspace"] != str(self.root)
                or not isinstance(payload["request"], dict)
                or not isinstance(payload["binding"], str)
                or re.fullmatch(r"[0-9a-f]{64}", payload["binding"]) is None
                or any(
                    type(payload[key]) not in (int, float) or not math.isfinite(payload[key])
                    for key in ("createdAt", "createdMonotonic")
                )
            ):
                raise ValueError
            elapsed = (
                self.clock() - payload["createdAt"],
                self.monotonic() - payload["createdMonotonic"],
            )
            if any(not math.isfinite(value) or value < 0 or value >= 300 for value in elapsed):
                raise TopicReviewError("approval_expired")
            payload["remainingSeconds"] = 300 - max(elapsed)
            return payload
        except TopicReviewError:
            raise
        except (ValueError, TypeError, KeyError):
            raise TopicReviewError("review_invalid") from None
