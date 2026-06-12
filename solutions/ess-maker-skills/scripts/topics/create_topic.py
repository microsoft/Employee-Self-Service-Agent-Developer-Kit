#!/usr/bin/env python3
"""
create_topic.py — Create a new ESS topic YAML file and push to Copilot Studio.

Generates a topic .mcs.yml file following the ADK topic format, writes it to
the agent's topics/ folder, and pushes it to Copilot Studio via Dataverse.

Usage:
    python scripts/topics/create_topic.py --name VacationBalance --connector Workday --description "Check vacation balance"
"""

import argparse
import json
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from auth import authenticate, create_record, load_config


def slugify(value):
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "custom-topic"


def pascal_case(value):
    parts = re.findall(r"[A-Za-z0-9]+", value)
    return "".join(p[:1].upper() + p[1:] for p in parts) if parts else "CustomTopic"


def connector_response_key(connector):
    normalized = re.sub(r"[^a-z0-9]", "", connector.lower())
    if normalized.startswith("workday"):
        return "workdayResponse"
    if normalized.startswith("servicenow"):
        return "ServiceNowData"
    return "systemResponse"


def build_topic_yaml(topic_name, description, connector, schema_name):
    """Build the topic YAML structure."""
    connector_pascal = pascal_case(connector)
    topic_pascal = pascal_case(topic_name)
    response_key = connector_response_key(connector)
    model_desc = f"{description.strip()}\n\nDo NOT trigger for unrelated scenarios."

    trigger_phrases = [
        topic_name.replace("-", " ").lower(),
        f"help me with {topic_name.replace('-', ' ').lower()}",
        f"I need {topic_name.replace('-', ' ').lower()} information",
    ]

    parameter_binding = (
        '="{""params"":[{""key"":""{Employee_ID}"",""value"":""" '
        "& Global.ESS_UserContext_Employee_Id & "
        '"""}]}"'
    )

    payload = {
        "kind": "AdaptiveDialog",
        "modelDescription": model_desc,
        "beginDialog": {
            "kind": "OnRecognizedIntent",
            "id": "main",
            "intent": {
                "triggerQueries": trigger_phrases,
            },
            "actions": [
                {
                    "kind": "SetVariable",
                    "id": "set_intro_msg",
                    "variable": "Topic.introMsg",
                    "value": '="Let me look that up for you."',
                },
                {
                    "kind": "SendActivity",
                    "id": "intro",
                    "activity": "{Topic.introMsg}",
                },
                {
                    "kind": "BeginDialog",
                    "id": "call_system",
                    "displayName": f"Call {connector_pascal} system execution",
                    "input": {
                        "binding": {
                            "parameters": parameter_binding,
                            "scenarioName": f"msdyn_{topic_pascal}",
                        }
                    },
                    "dialog": f"{schema_name}.topic.{connector_pascal}SystemGetCommonExecution",
                    "output": {
                        "binding": {
                            "errorResponse": "Topic.errorResponse",
                            "isSuccess": "Topic.isSuccess",
                            response_key: "Topic.systemResponse",
                        }
                    },
                },
                {
                    "kind": "ConditionGroup",
                    "id": "handle_result",
                    "conditions": [
                        {
                            "id": "success",
                            "condition": "=Topic.isSuccess = true",
                            "actions": [
                                {
                                    "kind": "AnswerQuestionWithAI",
                                    "id": "format_response",
                                    "autoSend": True,
                                    "variable": "Topic.FormattedResponse",
                                    "userInput": "=Topic.systemResponse",
                                    "additionalInstructions": (
                                        "Format the response in a friendly way and tie it back "
                                        "to the user's original question."
                                    ),
                                }
                            ],
                        }
                    ],
                    "elseActions": [
                        {
                            "kind": "SendActivity",
                            "id": "error_msg",
                            "activity": (
                                f"I wasn't able to retrieve that information right now. "
                                f"Please try again or check directly in {connector}."
                            ),
                        }
                    ],
                },
            ],
        },
        "inputType": {},
        "outputType": {},
    }
    return yaml.dump(payload, default_flow_style=False, sort_keys=False, allow_unicode=True)


def main():
    parser = argparse.ArgumentParser(description="Create a new ESS topic")
    parser.add_argument("--name", required=True, help="Topic name (e.g., VacationBalance)")
    parser.add_argument("--connector", default="Workday", help="Connector type")
    parser.add_argument("--description", default="", help="Topic description")
    parser.add_argument("--no-push", action="store_true", help="Skip pushing to Copilot Studio")
    args = parser.parse_args()

    config = load_config()
    agent_config = config.get("agent") or {}
    agent_dir = agent_config.get("folder", "")
    if agent_dir and not os.path.isabs(agent_dir):
        agent_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), agent_dir)

    schema_name = agent_config.get("schemaName", "")
    env_url = config.get("dataverseEndpoint", "")
    bot_id = agent_config.get("botId", "")

    topic_slug = slugify(args.name)
    topic_pascal = pascal_case(args.name)

    # Generate YAML
    description = args.description or f"Handle {args.name.replace('-', ' ')} inquiries"
    yaml_content = build_topic_yaml(args.name, description, args.connector, schema_name)

    # Write to file
    topics_dir = os.path.join(agent_dir, "topics")
    os.makedirs(topics_dir, exist_ok=True)
    file_path = os.path.join(topics_dir, f"{topic_slug}.mcs.yml")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(yaml_content)

    # Push to Copilot Studio
    pushed = False
    component_id = None
    if not args.no_push and env_url and bot_id:
        try:
            token = authenticate(env_url)
            record = {
                "data": yaml_content,
                "componenttype": 9,
                "_parentbotid_value": bot_id,
                "schemaname": f"{schema_name}.topic.{topic_pascal}",
            }
            component_id = create_record(env_url, token, "botcomponents", record)
            pushed = True
        except Exception as e:
            print(f"⚠️  Push failed: {e}", file=sys.stderr)

    result = {
        "topicName": topic_pascal,
        "filePath": file_path,
        "connector": args.connector,
        "description": description,
        "pushedToCopilotStudio": pushed,
        "componentId": str(component_id) if component_id else None,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
