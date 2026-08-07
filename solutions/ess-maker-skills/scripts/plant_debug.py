# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Plant a DBG SendActivity node into a deployed topic, then publish.

Concrete driver for the pure ``debug_plant`` core against the maker kit's own
Dataverse access (``auth.py``). Plants one DBG node after a named action so the
topic projects internal state into the transcript, PATCHes the topic, records
provenance for a guaranteed strip, and publishes so the change goes live.

Strip it afterwards with ``strip_debug.py`` (reads the provenance this writes).

Usage:
    python scripts/plant_debug.py --topic <schemaname> --after <action_id> \\
        --activity "DBG branch={Topic.SomeVar}" [--node-id <id>] [--yes]

The ``--after`` action id must exist in the topic; a mis-targeted plant refuses
to PATCH rather than instrument the wrong place.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from debug_plant import PlantSpec, plant_debug_nodes_live, strip_debug_nodes_live
from http_errors import APIError

# Provenance is written here by plant and read by strip. Lives under the kit's
# internal state dir so it is not mistaken for a user-edited file.
PROVENANCE_PATH = Path(".local") / ".dbg_provenance.json"

# Publish throttle tolerance: the PvaPublish bound action throttles under rapid
# get+patch+publish bursts, surfacing inconsistently as a bare 401 or a
# 400-wrapping-inner-429 — with a token that is otherwise valid. Treat those as
# transient and retry with backoff rather than as an auth failure.
_PUBLISH_ATTEMPTS = 5
_PUBLISH_BASE_DELAY = 3.0


def _is_transient_publish_error(err: APIError) -> bool:
    """True when a publish failure is throttling (retryable), not a real error.

    A bare 401 or 429 during publish is throttle noise on a valid token; a 400
    that wraps an inner 429 is the same throttle in a different envelope. A plain
    400/403/404 is a real error and must not be retried.
    """
    code = getattr(err, "status_code", None)
    if code in (401, 429):
        return True
    if code == 400 and "429" in str(err):
        return True
    return False


def publish_with_retry(publish_fn, *, attempts=_PUBLISH_ATTEMPTS,
                       base_delay=_PUBLISH_BASE_DELAY, sleep=time.sleep) -> None:
    """Call ``publish_fn()`` retrying transient throttle failures with backoff.

    ``publish_fn`` is a zero-arg callable (bind bot id / token at the call site).
    Non-transient APIErrors propagate immediately; a transient one backs off
    (base_delay * 2**attempt) and retries up to ``attempts`` times, re-raising
    the last error if it never clears.
    """
    for attempt in range(attempts):
        try:
            publish_fn()
            return
        except APIError as err:
            if not _is_transient_publish_error(err) or attempt == attempts - 1:
                if getattr(err, "status_code", None) == 401:
                    print("  Publish still returns 401 after retries. This is "
                          "usually publish throttling on a valid token, but a "
                          "persistent 401 can also mean the token expired — "
                          "re-run to re-authenticate if it does not clear.")
                raise
            delay = base_delay * (2 ** attempt)
            print(f"  Publish throttled ({getattr(err, 'status_code', '?')}); "
                  f"retrying in {delay:.0f}s...")
            sleep(delay)


def save_provenance(provenance, path: Path = PROVENANCE_PATH) -> None:
    """Persist plant provenance so a later strip can restore byte-identically."""
    payload = {
        "topic": provenance.topic,
        "record_id": provenance.record_id,
        "planted_node_ids": list(provenance.planted_node_ids),
        "specs": [
            {"after_action_id": s.after_action_id, "node_id": s.node_id,
             "activity": s.activity}
            for s in provenance.specs
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_provenance(path: Path = PROVENANCE_PATH):
    """Reconstruct a PlantProvenance written by ``save_provenance``."""
    from debug_plant import PlantProvenance
    payload = json.loads(path.read_text(encoding="utf-8"))
    return PlantProvenance(
        topic=payload["topic"],
        record_id=payload["record_id"],
        planted_node_ids=list(payload["planted_node_ids"]),
        specs=[PlantSpec(**s) for s in payload["specs"]],
    )


def _map_stem(file_key: str) -> str:
    """The bare stem of a component-map key: 'topics/foo.mcs.yml' -> 'foo'."""
    base = file_key.rsplit("/", 1)[-1]
    for suffix in (".mcs.yml", ".mcs.yaml", ".yml", ".yaml"):
        if base.lower().endswith(suffix):
            return base[: -len(suffix)]
    return base


def resolve_topic_schema(topic: str, component_map: dict) -> str:
    """Resolve a user-supplied topic identifier to its immutable schemaname.

    A maker knows a topic by its file (``servicenow-hrsd-get-cases-by-status``),
    not by the immutable ``msdyn_...topic.<Stem>`` schemaname the Dataverse write
    needs. This maps the friendly form to the schemaname via the agent's
    ``.component-map.json``. Accepts, in order:

      * a value already containing ``.topic.``/``.component.`` -> returned as-is
        (already a schemaname; works without a map, so offline plants still run);
      * a full map key (``topics/foo.mcs.yml``);
      * a bare filename (``foo.mcs.yml``) or stem (``foo``);
      * a display name (the map entry's ``name``), case-insensitive.

    Raises ``LookupError`` when nothing matches and ``ValueError`` when a stem is
    ambiguous (same basename under two folders) — both with an actionable message.
    """
    if ".topic." in topic or ".component." in topic:
        return topic

    needle = topic.strip()
    low = needle.lower()
    matches: list[str] = []
    for file_key, entry in (component_map or {}).items():
        schema = (entry or {}).get("schemaname")
        if not schema:
            continue
        candidates = {
            file_key.lower(),
            file_key.rsplit("/", 1)[-1].lower(),
            _map_stem(file_key).lower(),
        }
        name = (entry or {}).get("name")
        if name:
            candidates.add(name.lower())
        if low in candidates:
            matches.append(schema)

    unique = sorted(set(matches))
    if len(unique) == 1:
        return unique[0]
    if not unique:
        raise LookupError(
            f"no topic matching {topic!r} in .component-map.json. Pass the file "
            "stem (e.g. 'servicenow-hrsd-get-cases-by-status'), the display name, "
            "or the full schemaname.")
    raise ValueError(
        f"{topic!r} is ambiguous — it matches multiple components: "
        f"{', '.join(unique)}. Pass the full schemaname to disambiguate.")


def _load_active_component_map() -> dict:
    """Load the active agent's ``.component-map.json`` (via .local/config.json)."""
    from auth import load_config
    cfg = load_config()
    agent_dir = cfg["agent"]["folder"]
    map_path = Path(agent_dir) / ".component-map.json"
    return json.loads(map_path.read_text(encoding="utf-8"))


class AuthDataverseClient:
    """DataverseClient backed by the maker kit's auth.py access layer.

    Satisfies the structural ``debug_plant.DataverseClient`` Protocol
    (get_topic / patch_topic / publish_bot) without importing this module into
    the pure core. Publish is throttle-tolerant.
    """

    _TOPIC_ENTITY_SET = "botcomponents"

    def __init__(self, env_url: str, token: str):
        self._env_url = env_url
        self._token = token

    def get_topic(self, schemaname: str) -> tuple[str, str]:
        from auth import query_all
        escaped = schemaname.replace("'", "''")
        rows = query_all(
            self._env_url, self._token, self._TOPIC_ENTITY_SET,
            select="botcomponentid,data",
            filter_expr=f"schemaname eq '{escaped}'",
        )
        if not rows:
            raise LookupError(f"no botcomponent found with schemaname {schemaname!r}")
        row = rows[0]
        return row["botcomponentid"], row.get("data") or ""

    def patch_topic(self, record_id: str, content: str) -> None:
        from auth import update_record
        update_record(self._env_url, self._token, self._TOPIC_ENTITY_SET,
                      record_id, {"data": content})

    def publish_bot(self, bot_id: str) -> None:
        from auth import publish_bot as _publish
        publish_with_retry(lambda: _publish(self._env_url, self._token, bot_id))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Plant a DBG SendActivity node into a deployed topic and publish.")
    parser.add_argument("--topic", required=True,
                        help="topic to instrument: the file stem "
                             "(e.g. 'servicenow-hrsd-get-cases-by-status'), the "
                             "display name, or the full schemaname")
    parser.add_argument("--after", required=True,
                        help="action id to plant the DBG node after")
    parser.add_argument("--activity", required=True,
                        help="DBG activity text, e.g. \"DBG branch={Topic.SomeVar}\"")
    parser.add_argument("--node-id", default=None,
                        help="id for the planted node (default: derived from --after)")
    parser.add_argument("--yes", action="store_true",
                        help="skip the confirmation prompt")
    args = parser.parse_args(argv)

    from auth import authenticate, load_config

    config = load_config()
    env_url = config["dataverseEndpoint"]
    bot_id = config["agent"]["botId"]
    node_id = args.node_id or f"sendActivity_DBG_{args.after}"

    # Resolve a friendly topic identifier (file stem / display name) to the
    # immutable schemaname the Dataverse write needs. A value that already looks
    # like a schemaname passes straight through, so offline use is unaffected.
    topic_schema = args.topic
    if ".topic." not in args.topic and ".component." not in args.topic:
        try:
            topic_schema = resolve_topic_schema(args.topic, _load_active_component_map())
            print(f"Resolved topic {args.topic!r} -> {topic_schema}")
        except (LookupError, ValueError) as exc:
            print(f"Could not resolve topic: {exc}")
            return 1

    if PROVENANCE_PATH.exists():
        print(f"Provenance already exists at {PROVENANCE_PATH}. Run strip_debug.py "
              "first (an un-stripped plant is still live in your topic).")
        return 1

    if not args.yes:
        resp = input(
            f"Plant DBG node {node_id!r} after {args.after!r} in topic "
            f"{topic_schema!r} and publish? (yes/no): ").strip().lower()
        if resp not in ("yes", "y"):
            print("Plant cancelled.")
            return 0

    token = authenticate(env_url)
    client = AuthDataverseClient(env_url, token)
    spec = PlantSpec(after_action_id=args.after, node_id=node_id, activity=args.activity)

    provenance = plant_debug_nodes_live(client, topic_schema, [spec])
    try:
        save_provenance(provenance)
    except OSError as exc:
        # The live topic is already patched but the strip record didn't persist —
        # an un-strippable mutation. Roll the plant back immediately using the
        # in-memory provenance rather than leaving debug noise in the topic.
        print(f"  Provenance write failed ({exc}); rolling back the plant...")
        strip_debug_nodes_live(client, provenance)
        client.publish_bot(bot_id)
        print("  Rolled back and published; topic restored. Nothing was left planted.")
        return 1
    print(f"  Planted {node_id!r}; provenance saved to {PROVENANCE_PATH}.")

    print("Publishing...")
    client.publish_bot(bot_id)
    print("  Published. Drive the topic, read the DBG line, then run strip_debug.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
