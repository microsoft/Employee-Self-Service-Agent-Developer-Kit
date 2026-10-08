import json
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
PROMPTS = REPO_ROOT / "solutions" / "ess-maker-skills" / ".github" / "prompts"
WORKSPACE_SETTINGS = (
    REPO_ROOT / "solutions" / "ess-maker-skills" / ".vscode" / "settings.json"
)


def prompt_model(path: Path) -> str:
    frontmatter = path.read_text(encoding="utf-8").split("---", 2)[1]
    for line in frontmatter.splitlines():
        if line.startswith("model:"):
            return line.partition(":")[2].strip().strip('"\'')
    return ""


def test_workspace_default_model_is_gpt_6_sol():
    settings = json.loads(WORKSPACE_SETTINGS.read_text(encoding="utf-8"))
    assert settings["sessions.chat.defaultModel"] == "gpt6.1-sol"


def test_every_adk_prompt_pins_gpt_6_sol():
    prompt_files = sorted(PROMPTS.glob("*.prompt.md"))
    assert prompt_files
    assert all(prompt_model(path) == "gpt6.1-sol" for path in prompt_files)
