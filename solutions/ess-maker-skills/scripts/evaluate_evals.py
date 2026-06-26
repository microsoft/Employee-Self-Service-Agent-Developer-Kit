#!/usr/bin/env python3
"""
evaluate_evals.py — Quality validation for generated evaluation test sets.

Reads eval YAML files from an agent's evaluations/ folder, sends them to a
LLM judge via GitHub Copilot API, and reports quality scores per dimension.

Uses 'gh auth token' for credentials — no extra setup required.

Usage:
    python scripts/evaluate_evals.py
    python scripts/evaluate_evals.py --agent employee-self-service-hr
    python scripts/evaluate_evals.py --category topic-triggering
    python scripts/evaluate_evals.py --sample 20
    python scripts/evaluate_evals.py --output results/eval-quality.json
"""

import argparse
import json
import os
import random
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# Ensure UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError for box-drawing chars)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ─── Config ───────────────────────────────────────────────────────────────────

MODELS_API_URL = "https://api.githubcopilot.com/chat/completions"
# No model specified — Copilot API uses the plan default (gpt-4o-mini for most accounts).
# Avoids failures on Business/Enterprise accounts where specific models may be restricted.
DEFAULT_SAMPLE = 100  # cases per category to send to judge (100 = eval set cap, i.e. all cases)

QUALITY_DIMENSIONS = {
    "Validity": "Each input is grammatically correct and plausible as a real user utterance.",
    "Realism": "Inputs sound like things real employees would actually say — not textbook sentences or formal policy language.",
    "Assertion Quality": "Each expectedOutput is specific, actionable, and testable — not vague like 'agent should respond'. It describes observable user-facing behavior, not implementation details.",
    "Coverage": "The category covers a meaningful spread of sub-topics and scenario types (positive, boundary, negative) rather than clustering around one scenario.",
    "Diversity": (
        "Utterances cover two distinct types: (1) natural-language — complete sentences a real employee would say, "
        "and (2) keyword-style — short, sparse inputs with no grammar (e.g. 'open tkts', 'employee ID'). "
        "The ideal pattern is one natural-language input and one keyword-style input per topic. "
        "Score high when both types are present across the set. "
        "Score low when all inputs are natural-language near-synonyms of each other, "
        "or when keyword inputs dominate without any natural-language representation."
    ),
    "Redundancy": (
        "No two cases test the exact same thing. Two cases are redundant if they have "
        "nearly identical inputs AND nearly identical expected outputs — changing only a single word does not make them distinct. "
        "IMPORTANT EXCEPTION: a boundary case (typo, abbreviation, very short input) intentionally shares its expectedOutput "
        "with the corresponding positive case — this is by design and is NOT redundant, because the inputs are meaningfully different "
        "(imperfect vs natural phrasing). Do NOT flag positive/boundary pairs as redundant. "
        "Note: two cases can have similar phrasing (low Diversity) but still test different behaviors (not Redundant). "
        "For negative cases specifically: also flag when multiple negatives share the same sentence structure "
        "(e.g. all written as 'Show me [person]'s [X]', or all as '[name] [resource]') even if they test different failure modes — "
        "structural uniformity across negatives reduces discriminative value."
    ),
    "Failure Mode Coverage": "For negative/edge cases: the failures tested are realistic scenarios employees would actually trigger, not contrived or trivially obvious refusals.",
    "Discriminative Power": "Inputs are clearly scoped to what the topic handles. Positive inputs would not accidentally trigger a different topic; negative inputs would not accidentally pass.",
}

SCORE_LABELS = {5: "✓ Excellent", 4: "✓ Good", 3: "⚠ Fair", 2: "✗ Weak", 1: "✗ Poor"}

# Short one-liner shown under each dimension score in the report
QUALITY_DIMENSION_HINTS = {
    "Validity": "Inputs are grammatically correct and plausible as real user utterances",
    "Realism": "Inputs sound like things real employees would say, not formal policy language",
    "Assertion Quality": "Expected outputs are specific and describe observable agent behavior",
    "Coverage": "Cases span a meaningful spread of sub-topics and positive/boundary/negative types",
    "Diversity": "Inputs use genuinely different vocabulary, structure, and formality levels",
    "Redundancy": "No two cases test the exact same input and expected behavior",
    "Failure Mode Coverage": "Negative/edge cases reflect realistic failure modes, not contrived refusals",
    "Discriminative Power": "Inputs are clearly scoped so they won't accidentally trigger the wrong topic",
    "Topic Alignment": "Each case matches what its corresponding topic actually does",
}

# Categories where topic alignment check applies
TOPIC_ALIGNMENT_CATEGORIES = {"topic-triggering", "integration-data"}

def load_eval_file(path: Path) -> dict | None:
    """Load and parse a single .mcs.yml eval file. Returns None if unreadable."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    try:
        import yaml
        data = yaml.safe_load(text)
    except ImportError:
        print(
            "ERROR: PyYAML is required to parse .mcs.yml evaluation files. "
            "Install deps with: pip install -r scripts/requirements.txt",
            file=sys.stderr,
        )
        sys.exit(1)
    except yaml.YAMLError:
        return None

    if not isinstance(data, dict):
        return None

    return {"path": path, "raw": text, "data": data}


def extract_cases(files: list[dict]) -> list[dict]:
    """
    Extract (input, expected_output) pairs from loaded eval files.
    Only handles EvaluationData (single-turn). MultiTurnEvaluationCase files
    are skipped — multi-turn scoring is not supported by this script.
    """
    cases = []
    for f in files:
        data = f["data"]
        name = f["path"].name
        kind = data.get("kind", "")

        if kind == "EvaluationData":
            for row in data.get("rows", []):
                cases.append({
                    "file": name,
                    "kind": "single-turn",
                    "input": row.get("input", ""),
                    "expected": row.get("expectedOutput", ""),
                })

        elif kind == "MultiTurnEvaluationCase":
            pass  # skipped — multi-turn scoring not supported

    return cases


# ─── Topic context loader ─────────────────────────────────────────────────────

def load_topic_context(topics_dir: Path) -> dict[str, str]:
    """
    Load modelDescription from all topic files that have one.
    Returns {topic-file-stem: model_description}.
    Only topics with a modelDescription are included — system topics are skipped.
    """
    context = {}
    if not topics_dir.exists():
        return context

    for yml_file in sorted(topics_dir.glob("*.mcs.yml")):
        try:
            text = yml_file.read_text(encoding="utf-8")
            try:
                import yaml
                data = yaml.safe_load(text)
            except ImportError:
                print(
                    "ERROR: PyYAML is required to parse .mcs.yml evaluation files. "
                    "Install deps with: pip install -r scripts/requirements.txt",
                    file=sys.stderr,
                )
                sys.exit(1)

            if not isinstance(data, dict):
                continue

            model_desc = data.get("modelDescription", "") or ""
            model_desc = model_desc.strip()
            if not model_desc:
                continue

            context[yml_file.stem] = model_desc
        except (OSError, yaml.YAMLError) as e:
            print(f"WARNING: could not parse {yml_file.name} for topic alignment: {e}", file=sys.stderr)
            continue

    return context


# ─── Copilot API ──────────────────────────────────────────────────────────────

def get_gh_token() -> str:
    """Get the current GitHub token via gh auth token."""
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            err = (result.stderr or "").strip()
            print(
                f"ERROR: 'gh auth token' failed (exit {result.returncode}). {err}",
                file=sys.stderr,
            )
            sys.exit(1)
        token = result.stdout.strip()
        if not token:
            print("ERROR: gh auth token returned empty. Run 'gh auth login' first.", file=sys.stderr)
            sys.exit(1)
        return token
    except FileNotFoundError:
        print("ERROR: 'gh' CLI not found. Install it from https://cli.github.com/", file=sys.stderr)
        sys.exit(1)


def call_judge(prompt: str, token: str, _retry: bool = True) -> str:
    """Call the Copilot API LLM judge. Returns the response text."""
    payload = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert evaluator of AI agent test sets. "
                    "Your job is to assess the quality of evaluation test cases "
                    "for an employee-facing IT support chatbot. "
                    "Be precise, critical, and actionable. "
                    "Always respond with valid JSON matching the schema provided."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 4000,
        "temperature": 0.2,
    }

    req = urllib.request.Request(
        MODELS_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Copilot-Integration-Id": "copilot-chat",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            choice = body["choices"][0]
            if choice.get("finish_reason") == "length":
                print(
                    "\nERROR: Model response was truncated (finish_reason=length). "
                    "The sample may be too large — try reducing with --sample.",
                    file=sys.stderr,
                )
                sys.exit(1)
            return choice["message"]["content"]
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            print(
                "\nERROR: GitHub Copilot API returned 401 Unauthorized.\n"
                "Ensure you have an active GitHub Copilot subscription and run:\n"
                "  gh auth login\n"
                f"Details: {err_body}",
                file=sys.stderr,
            )
            sys.exit(1)
        elif e.code == 429:
            if _retry:
                import time
                print("\nRate limited — waiting 10 seconds before retrying...", file=sys.stderr)
                time.sleep(10)
                return call_judge(prompt, token, _retry=False)
            print("\nERROR: Rate limited by Copilot API. Wait a moment and retry.", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"\nERROR: Copilot API returned {e.code}: {err_body}", file=sys.stderr)
            sys.exit(1)
    except urllib.error.URLError as e:
        print(f"\nERROR: Could not reach Copilot API: {e.reason}", file=sys.stderr)
        sys.exit(1)


# ─── Prompt builder ───────────────────────────────────────────────────────────

def build_judge_prompt(
    category: str,
    cases: list[dict],
    topic_context: dict[str, str] | None = None,
) -> str:
    # Build dimension list — add Topic Alignment when topic context is available
    dims = dict(QUALITY_DIMENSIONS)
    include_alignment = bool(topic_context) and category in TOPIC_ALIGNMENT_CATEGORIES
    if include_alignment:
        dims["Topic Alignment"] = (
            "Each test case's input and expected output match the actual behavior "
            "described by the corresponding topic definition. A positive input should "
            "clearly trigger the right topic; an expected output should describe what "
            "that topic actually does — not a different topic's behavior."
        )

    dims_text = "\n".join(f"  - {name}: {desc}" for name, desc in dims.items())

    # Build topic context section
    topic_section = ""
    if include_alignment and topic_context:
        topic_lines = []
        for stem, desc in topic_context.items():
            short = desc[:400] + "..." if len(desc) > 400 else desc
            topic_lines.append(f"**{stem}**:\n{short}")
        topic_section = (
            "\n\n## Available Topic Definitions\n"
            "Use these to assess Topic Alignment — each test case should match "
            "what its corresponding topic actually does:\n\n"
            + "\n\n".join(topic_lines)
        )

    cases_text_parts = []
    for i, c in enumerate(cases, 1):
        cases_text_parts.append(
            f"Case {i} ({c['file']}):\n"
            f"  input: {c['input']}\n"
            f"  expectedOutput: {c['expected']}"
        )
    cases_text = "\n\n".join(cases_text_parts)

    alignment_schema = ',\n    "Topic Alignment": <1-5 or null>' if include_alignment else ""

    return f"""You are reviewing a sample of evaluation test cases for the "{category}" category of an IT support chatbot.{topic_section}

## Quality Dimensions to Assess
{dims_text}

## Test Cases (sample of {len(cases)})
{cases_text}

## Your Task
Score this sample on each quality dimension (1–5 scale) and identify specific flagged cases.

Respond with ONLY valid JSON in this exact schema:
{{
  "scores": {{
    "Validity": <1-5>,
    "Realism": <1-5>,
    "Assertion Quality": <1-5>,
    "Coverage": <1-5>,
    "Diversity": <1-5>,
    "Redundancy": <1-5>,
    "Failure Mode Coverage": <1-5 or null>,
    "Discriminative Power": <1-5>{alignment_schema}
  }},
  "overall": <1-5>,
  "flagged": [
    {{
      "file": "<filename.mcs.yml>",
      "dimension": "<dimension name>",
      "issue": "<one sentence description of the issue>"
    }}
  ],
  "recommendation": "<one to two sentences of the most important improvement for this category>"
}}

Notes:
- Score each dimension based on what you observe in the sample.
- For "Failure Mode Coverage", if there are no negative/edge cases in this category, score it null.
- For "Topic Alignment", if topic definitions were not provided, score it null.
- Keep "flagged" to the top 10 most important issues only.
- "recommendation" should be actionable and specific to this category.
"""


# ─── Report renderer ─────────────────────────────────────────────────────────

def render_report(results: list[dict], agent_name: str, total_cases: int) -> None:
    now = datetime.now().strftime("%B %-d, %Y") if os.name != "nt" else datetime.now().strftime("%B %d, %Y")

    print()
    print("=" * 65)
    print("  EVAL QUALITY REPORT")
    print("=" * 65)
    print(f"  Agent   : {agent_name}")
    print(f"  Cases   : {total_cases} total across {len(results)} categories")
    print(f"  Date    : {now}")
    print("  Model   : Copilot default")
    print("=" * 65)

    for r in results:
        category = r["category"]
        total = r["total_cases"]
        sampled = r["sampled"]
        result = r.get("result")
        error = r.get("error")

        print(f"\n{'─' * 65}")
        print(f"  {category}  ({total} cases, sampled {sampled})")
        print(f"{'─' * 65}")

        if error:
            print(f"  ERROR: {error}")
            continue

        if not result:
            print("  No result.")
            continue

        scores = result.get("scores", {})
        overall = result.get("overall", "?")
        flagged = result.get("flagged", [])
        recommendation = result.get("recommendation", "")

        # Group flagged cases by dimension for inline display
        flagged_by_dim: dict[str, list[dict]] = {}
        for f in flagged:
            flagged_by_dim.setdefault(f["dimension"], []).append(f)

        label = SCORE_LABELS.get(overall, "")
        print(f"  Overall quality: {overall}/5  {label}")
        print()

        for dim, score in scores.items():
            if score is None:
                continue
            bar = "█" * score + "░" * (5 - score)
            dim_label = SCORE_LABELS.get(score, "")
            hint = QUALITY_DIMENSION_HINTS.get(dim, "")
            print(f"  {dim:<28} {bar}  {score}/5  {dim_label}")
            if hint:
                print(f"    → {hint}")
            # Show flagged test cases inline under their dimension
            if dim in flagged_by_dim:
                for fc in flagged_by_dim[dim]:
                    print(f"      ⚠  {fc['file']}: {fc['issue']}")

        # Print any flagged cases whose dimension was null-scored or not in scores
        # (e.g. judge mis-spelled a dimension name) so they're never silently dropped
        printed_dims = {dim for dim, score in scores.items() if score is not None}
        orphaned = {dim: cases for dim, cases in flagged_by_dim.items() if dim not in printed_dims}
        if orphaned:
            print("\n  ⚠  Other flagged cases:")
            for dim, cases in orphaned.items():
                for fc in cases:
                    print(f"      ⚠  {fc['file']} [{dim}]: {fc['issue']}")

        if recommendation:
            print(f"\n  Recommendation: {recommendation}")

    print(f"\n{'=' * 65}")
    print()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Quality validation for generated evaluation test sets."
    )
    parser.add_argument(
        "--agent", "-a",
        help="Agent slug (e.g. employee-self-service-hr). Auto-detected if only one agent exists.",
    )
    parser.add_argument(
        "--category", "-c",
        help="Evaluate only this category (e.g. topic-triggering).",
    )
    parser.add_argument(
        "--sample", "-s",
        type=int,
        default=DEFAULT_SAMPLE,
        help=f"Max cases per category to send to the quality evaluator (default: {DEFAULT_SAMPLE} = all, since eval sets are capped at 100).",
    )
    parser.add_argument(
        "--output", "-o",
        help="Save full results to this JSON file.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for sampling (default: 42, for reproducibility).",
    )
    parser.add_argument(
        "--topics-dir", "-t",
        help="Path to the agent's topics/ folder for Topic Alignment checks. Auto-detected if omitted.",
    )
    args = parser.parse_args()

    try:
        import adk_telemetry

        adk_telemetry.emit_capability_use("evaluations")
    except Exception:  # noqa: BLE001 — telemetry must never break evaluation
        pass

    # ── Locate agent folder ──────────────────────────────────────────────────
    repo_root = Path(__file__).parent.parent
    agents_dir = repo_root / "workspace" / "agents"

    if not agents_dir.exists():
        print(f"ERROR: No workspace/agents/ folder found at {agents_dir}", file=sys.stderr)
        sys.exit(1)

    if args.agent:
        agent_dir = agents_dir / args.agent
        if not agent_dir.exists():
            print(f"ERROR: Agent folder not found: {agent_dir}", file=sys.stderr)
            sys.exit(1)
    else:
        agent_dirs = [d for d in agents_dir.iterdir() if d.is_dir()]
        if not agent_dirs:
            print("ERROR: No agent folders found in workspace/agents/", file=sys.stderr)
            sys.exit(1)
        if len(agent_dirs) > 1:
            print("Multiple agents found. Specify one with --agent:", file=sys.stderr)
            for d in agent_dirs:
                print(f"  {d.name}", file=sys.stderr)
            sys.exit(1)
        agent_dir = agent_dirs[0]

    evals_dir = agent_dir / "evaluations"
    if not evals_dir.exists():
        print(f"ERROR: No evaluations/ folder found at {evals_dir}", file=sys.stderr)
        sys.exit(1)

    agent_name = agent_dir.name

    # ── Discover categories ───────────────────────────────────────────────────
    if args.category:
        category_dirs = [evals_dir / args.category]
        if not category_dirs[0].exists():
            print(f"ERROR: Category folder not found: {category_dirs[0]}", file=sys.stderr)
            sys.exit(1)
    else:
        category_dirs = sorted(
            [d for d in evals_dir.iterdir() if d.is_dir()]
        )

    if not category_dirs:
        print("No evaluation categories found.", file=sys.stderr)
        sys.exit(1)

    # ── Load topic context ────────────────────────────────────────────────────
    topics_dir = Path(args.topics_dir) if args.topics_dir else agent_dir / "topics"
    topic_context = load_topic_context(topics_dir)
    if topic_context:
        print(f"  Loaded {len(topic_context)} topic definitions for alignment checks.")

    # ── Get auth token once ───────────────────────────────────────────────────
    print(f"\nLoading eval test cases from {agent_name}...")
    token = get_gh_token()

    # ── Process each category ─────────────────────────────────────────────────
    random.seed(args.seed)
    all_results = []
    total_cases = 0

    for cat_dir in category_dirs:
        category = cat_dir.name
        yml_files = sorted(cat_dir.glob("*.mcs.yml"))

        loaded = [f for f in (load_eval_file(p) for p in yml_files) if f]
        cases = extract_cases(loaded)
        total_cases += len(cases)

        if not cases:
            print(f"  {category}: no cases found, skipping.")
            all_results.append({
                "category": category,
                "total_cases": 0,
                "sampled": 0,
                "error": "No cases found.",
            })
            continue

        sample_size = min(args.sample, len(cases))
        sampled = random.sample(cases, sample_size) if sample_size < len(cases) else cases

        print(f"  {category}: {len(cases)} cases — sending {sample_size} to quality evaluator...", end="", flush=True)

        prompt = build_judge_prompt(category, sampled, topic_context=topic_context or None)
        raw_response = call_judge(prompt, token)

        # Strip markdown code fences if the model wrapped the JSON
        clean = raw_response.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.split("\n")[1:])
        if clean.endswith("```"):
            clean = "\n".join(clean.split("\n")[:-1])
        clean = clean.strip()

        try:
            result = json.loads(clean)
            print(" done.")
        except json.JSONDecodeError as e:
            print(f" parse error ({e})")
            all_results.append({
                "category": category,
                "total_cases": len(cases),
                "sampled": sample_size,
                "error": f"Could not parse JSON response: {e}",
                "raw_response": raw_response,
            })
            continue

        all_results.append({
            "category": category,
            "total_cases": len(cases),
            "sampled": sample_size,
            "result": result,
        })

    # ── Render report ─────────────────────────────────────────────────────────
    render_report(all_results, agent_name, total_cases)

    # ── Optionally save JSON ──────────────────────────────────────────────────
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "agent": agent_name,
                    "date": datetime.now().isoformat(),
                    "model": "Copilot default",
                    "total_cases": total_cases,
                    "categories": all_results,
                },
                f,
                indent=2,
                default=str,
            )
        print(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()
