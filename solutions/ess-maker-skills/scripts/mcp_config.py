# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Safely materialize and configure the workspace MCP configuration."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit, urlunsplit


SOLUTION_ROOT = Path(__file__).resolve().parent.parent
DEFAULTS_PATH = Path(".vscode/mcp.defaults.json")
CONFIG_PATH = Path(".vscode/mcp.json")
STATE_PATH = Path(".local/mcp-defaults-state.json")
DESCRIPTORS_PATH = Path("src/mcp")
ENV_ARGUMENT = "--env"
_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class McpConfigError(ValueError):
    """Raised when MCP configuration cannot be reconciled safely."""


class _DuplicateJsonKeyError(ValueError):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(key)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(key)
        result[key] = value
    return result


def _read_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except json.JSONDecodeError as exc:
        raise McpConfigError(
            f"{path} is not valid JSON: line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}"
        ) from exc
    except _DuplicateJsonKeyError as exc:
        raise McpConfigError(
            f"{path} contains duplicate JSON key '{exc.key}'."
        ) from exc
    except OSError as exc:
        raise McpConfigError(f"Could not read {path}: {exc}") from exc


def _validate_document(document: Any, path: Path) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise McpConfigError(f"{path} must contain a JSON object.")

    servers = document.get("servers", {})
    if not isinstance(servers, dict):
        raise McpConfigError(f"{path}: 'servers' must be a JSON object.")
    for name, definition in servers.items():
        if not isinstance(name, str) or not name:
            raise McpConfigError(f"{path}: every server must have a non-empty name.")
        if not isinstance(definition, dict):
            raise McpConfigError(
                f"{path}: server '{name}' must contain a JSON object."
            )

    inputs = document.get("inputs", [])
    if not isinstance(inputs, list):
        raise McpConfigError(f"{path}: 'inputs' must be a JSON array.")
    seen_inputs: set[str] = set()
    for item in inputs:
        if not isinstance(item, dict):
            raise McpConfigError(f"{path}: every input must contain a JSON object.")
        input_id = item.get("id")
        if not isinstance(input_id, str) or not input_id:
            raise McpConfigError(f"{path}: every input must have a non-empty 'id'.")
        if input_id in seen_inputs:
            raise McpConfigError(f"{path}: duplicate input id '{input_id}'.")
        seen_inputs.add(input_id)

    return document


def _read_config(root: Path) -> tuple[dict[str, Any], bool]:
    path = root / CONFIG_PATH
    if not path.exists():
        return {"servers": {}}, False
    return _validate_document(_read_json(path), path), True


def _read_defaults(root: Path) -> dict[str, Any]:
    path = root / DEFAULTS_PATH
    if not path.exists():
        raise McpConfigError(f"Default MCP catalog not found: {path}")
    defaults = _validate_document(_read_json(path), path)
    if "servers" not in defaults:
        raise McpConfigError(f"{path}: default catalog must define 'servers'.")
    unexpected = set(defaults) - {"servers", "inputs"}
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise McpConfigError(
            f"{path}: unsupported top-level default field(s): {names}."
        )
    return _render_runtime_values(defaults)


def _empty_state() -> dict[str, Any]:
    return {"schemaVersion": 1, "servers": {}, "inputs": {}}


def _read_state(root: Path) -> dict[str, Any]:
    path = root / STATE_PATH
    if not path.exists():
        return _empty_state()
    state = _read_json(path)
    if not isinstance(state, dict) or state.get("schemaVersion") != 1:
        raise McpConfigError(
            f"{path} must contain MCP defaults state with schemaVersion 1."
        )
    for collection in ("servers", "inputs"):
        values = state.get(collection)
        if not isinstance(values, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in values.items()
        ):
            raise McpConfigError(
                f"{path}: '{collection}' must map names to fingerprints."
            )
    return state


def _fingerprint(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise McpConfigError(f"Could not write {path}: {exc}") from exc


def _reconcile_named_values(
    current: dict[str, Any],
    desired: dict[str, Any],
    managed_fingerprints: dict[str, str],
) -> tuple[list[str], list[str], list[str]]:
    added: list[str] = []
    updated: list[str] = []
    preserved: list[str] = []

    for name, desired_value in desired.items():
        desired_fingerprint = _fingerprint(desired_value)
        if name not in current:
            current[name] = copy.deepcopy(desired_value)
            managed_fingerprints[name] = desired_fingerprint
            added.append(name)
            continue

        current_fingerprint = _fingerprint(current[name])
        previous_fingerprint = managed_fingerprints.get(name)
        if current_fingerprint == desired_fingerprint:
            managed_fingerprints[name] = desired_fingerprint
        elif previous_fingerprint and current_fingerprint == previous_fingerprint:
            current[name] = copy.deepcopy(desired_value)
            managed_fingerprints[name] = desired_fingerprint
            updated.append(name)
        else:
            preserved.append(name)

    return added, updated, preserved


def _inputs_by_id(inputs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in inputs}


def materialize_defaults(root: Path = SOLUTION_ROOT) -> dict[str, Any]:
    """Merge ready-to-run defaults into the generated workspace config."""

    defaults = _read_defaults(root)
    config, config_existed = _read_config(root)
    state = _read_state(root)
    original_config = copy.deepcopy(config)
    original_state = copy.deepcopy(state)

    servers = config.setdefault("servers", {})
    added_servers, updated_servers, preserved_servers = _reconcile_named_values(
        servers,
        defaults["servers"],
        state["servers"],
    )

    added_inputs: list[str] = []
    updated_inputs: list[str] = []
    preserved_inputs: list[str] = []
    if defaults.get("inputs"):
        current_inputs = config.setdefault("inputs", [])
        inputs_by_id = _inputs_by_id(current_inputs)
        desired_inputs = _inputs_by_id(defaults["inputs"])
        added_inputs, updated_inputs, preserved_inputs = _reconcile_named_values(
            inputs_by_id,
            desired_inputs,
            state["inputs"],
        )
        for item in defaults["inputs"]:
            if item["id"] in added_inputs:
                current_inputs.append(inputs_by_id[item["id"]])
        if updated_inputs:
            replacements = set(updated_inputs)
            config["inputs"] = [
                inputs_by_id[item["id"]] if item["id"] in replacements else item
                for item in current_inputs
            ]

    config_changed = config != original_config
    state_changed = state != original_state
    if config_changed:
        _write_json_atomic(root / CONFIG_PATH, config)
    if state_changed:
        _write_json_atomic(root / STATE_PATH, state)

    if config_changed and not config_existed:
        action = "created"
    elif config_changed:
        action = "updated"
    else:
        action = "unchanged"

    return {
        "action": action,
        "addedInputs": added_inputs,
        "addedServers": added_servers,
        "path": CONFIG_PATH.as_posix(),
        "preservedInputOverrides": preserved_inputs,
        "preservedServerOverrides": preserved_servers,
        "updatedInputs": updated_inputs,
        "updatedServers": updated_servers,
    }


def validate_config(
    server_name: str | None = None,
    root: Path = SOLUTION_ROOT,
) -> dict[str, Any]:
    """Validate the generated config and report an optional server's presence."""

    path = root / CONFIG_PATH
    if not path.exists():
        return {
            "path": CONFIG_PATH.as_posix(),
            "server": server_name,
            "status": "missing-file",
        }

    config = _validate_document(_read_json(path), path)
    if server_name and server_name not in config.get("servers", {}):
        status = "missing-server"
    else:
        status = "configured"
    return {
        "path": CONFIG_PATH.as_posix(),
        "server": server_name,
        "status": status,
    }


def _load_descriptor(descriptor_id: str, root: Path) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for path in sorted((root / DESCRIPTORS_PATH).glob("*/mcp.server.json")):
        descriptor = _read_json(path)
        if not isinstance(descriptor, dict):
            raise McpConfigError(f"{path} must contain a JSON object.")
        if descriptor.get("id") == descriptor_id:
            descriptor["_path"] = path
            matches.append(descriptor)

    if not matches:
        raise McpConfigError(
            f"Unknown contextual MCP server '{descriptor_id}'."
        )
    if len(matches) > 1:
        raise McpConfigError(
            f"Contextual MCP server id '{descriptor_id}' is defined more than once."
        )
    return matches[0]


def _normalize_parameter(value: str, specification: dict[str, Any]) -> str:
    if specification.get("format") != "https-url":
        return value

    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise McpConfigError(f"Expected an absolute HTTPS URL, received: {value}")
    path = parsed.path.rstrip("/") if specification.get("stripTrailingSlash") else parsed.path
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _render_runtime_values(value: Any) -> Any:
    if value == "{pythonExecutable}":
        return str(Path(sys.executable).resolve())
    if isinstance(value, list):
        return [_render_runtime_values(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _render_runtime_values(item)
            for key, item in value.items()
        }
    return value


def _parse_env_override(value: str) -> tuple[str, str]:
    name, separator, environment_value = value.partition("=")
    if not separator:
        raise McpConfigError(
            f"{ENV_ARGUMENT} expects NAME=VALUE, received: {value}"
        )
    if not _ENV_NAME_PATTERN.match(name):
        raise McpConfigError(
            f"{ENV_ARGUMENT} name must match [A-Za-z_][A-Za-z0-9_]*, "
            f"received: {name}"
        )
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in environment_value):
        raise McpConfigError(
            f"{ENV_ARGUMENT} value for '{name}' must not contain control characters."
        )
    return name, environment_value


def _parse_env_overrides(values: Sequence[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for value in values:
        name, environment_value = _parse_env_override(value)
        if name in overrides:
            raise McpConfigError(f"{ENV_ARGUMENT} name '{name}' was supplied twice.")
        overrides[name] = environment_value
    return overrides


def _parse_descriptor_arguments(
    descriptor: dict[str, Any],
    arguments: Sequence[str],
) -> tuple[dict[str, str], dict[str, str]]:
    parameters = descriptor.get("parameters", {})
    if not isinstance(parameters, dict):
        raise McpConfigError(
            f"{descriptor['_path']}: 'parameters' must be a JSON object."
        )

    parser = argparse.ArgumentParser(
        prog=f"mcp_config.py configure {descriptor['id']}"
    )
    for name, specification in parameters.items():
        if not isinstance(specification, dict):
            raise McpConfigError(
                f"{descriptor['_path']}: parameter '{name}' must be an object."
            )
        argument = specification.get("argument")
        if not isinstance(argument, str) or not argument.startswith("--"):
            raise McpConfigError(
                f"{descriptor['_path']}: parameter '{name}' needs a '--' argument."
            )
        if argument == ENV_ARGUMENT:
            raise McpConfigError(
                f"{descriptor['_path']}: parameter '{name}' must not claim the "
                f"reserved '{ENV_ARGUMENT}' argument."
            )
        parser.add_argument(
            argument,
            dest=name,
            required=bool(specification.get("required")),
        )
    parser.add_argument(
        ENV_ARGUMENT,
        dest="_env",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Set one environment variable on the rendered server definition.",
    )

    parsed = vars(parser.parse_args(arguments))
    rendered = {
        name: _normalize_parameter(parsed[name], specification)
        for name, specification in parameters.items()
        if parsed[name] is not None
    }
    return rendered, _parse_env_overrides(parsed["_env"])


def _render_template(value: Any, parameters: dict[str, str]) -> Any:
    if isinstance(value, str):
        for name, replacement in parameters.items():
            value = value.replace(f"{{{name}}}", replacement)
        return value
    if isinstance(value, list):
        return [_render_template(item, parameters) for item in value]
    if isinstance(value, dict):
        return {
            key: _render_template(item, parameters)
            for key, item in value.items()
        }
    return value


def configure_server(
    descriptor_id: str,
    arguments: Sequence[str],
    root: Path = SOLUTION_ROOT,
) -> dict[str, Any]:
    """Render and upsert one contextual server definition."""

    descriptor = _load_descriptor(descriptor_id, root)
    server_name = descriptor.get("serverName")
    server_template = descriptor.get("server")
    if not isinstance(server_name, str) or not server_name:
        raise McpConfigError(
            f"{descriptor['_path']}: 'serverName' must be a non-empty string."
        )
    if not isinstance(server_template, dict):
        raise McpConfigError(
            f"{descriptor['_path']}: 'server' must be a JSON object."
        )

    parameters, env_overrides = _parse_descriptor_arguments(descriptor, arguments)
    rendered_server = _render_runtime_values(
        _render_template(server_template, parameters)
    )
    if env_overrides:
        environment = rendered_server.setdefault("env", {})
        if not isinstance(environment, dict):
            raise McpConfigError(
                f"{descriptor['_path']}: 'server.env' must be a JSON object to "
                f"accept {ENV_ARGUMENT} values."
            )
        environment.update(env_overrides)
    rendered_inputs = _render_template(descriptor.get("inputs", []), parameters)
    _validate_document(
        {"servers": {server_name: rendered_server}, "inputs": rendered_inputs},
        descriptor["_path"],
    )

    config, config_existed = _read_config(root)
    original_config = copy.deepcopy(config)
    config.setdefault("servers", {})[server_name] = rendered_server

    if rendered_inputs:
        current_inputs = config.setdefault("inputs", [])
        indexes = {item["id"]: index for index, item in enumerate(current_inputs)}
        for item in rendered_inputs:
            input_id = item["id"]
            if input_id in indexes:
                current_inputs[indexes[input_id]] = item
            else:
                indexes[input_id] = len(current_inputs)
                current_inputs.append(item)

    changed = config != original_config
    if changed:
        _write_json_atomic(root / CONFIG_PATH, config)

    if changed and not config_existed:
        action = "created"
    elif changed:
        action = "updated"
    else:
        action = "unchanged"
    return {
        "action": action,
        "path": CONFIG_PATH.as_posix(),
        "server": server_name,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely manage the ESS Maker Kit MCP configuration."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "materialize-defaults",
        help="Merge every ready-to-run default server into .vscode/mcp.json.",
    )
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate .vscode/mcp.json and optionally check one server.",
    )
    validate_parser.add_argument("--server")
    configure_parser = subparsers.add_parser(
        "configure",
        help="Render and upsert one contextual server.",
    )
    configure_parser.add_argument("server")
    configure_parser.add_argument(
        "server_arguments",
        nargs=argparse.REMAINDER,
        help=(
            "Descriptor parameters, plus repeatable "
            f"'{ENV_ARGUMENT} NAME=VALUE' environment overrides."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "materialize-defaults":
            result = materialize_defaults()
            marker = "MCP_CONFIG_RESULT_JSON"
        elif arguments.command == "validate":
            result = validate_config(arguments.server)
            marker = "MCP_CONFIG_STATUS_JSON"
        else:
            result = configure_server(
                arguments.server,
                arguments.server_arguments,
            )
            marker = "MCP_CONFIG_RESULT_JSON"
    except McpConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"{marker}: {json.dumps(result, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
