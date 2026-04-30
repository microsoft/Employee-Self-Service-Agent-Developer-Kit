# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Copilot Kit - Sync Official ESS Samples

Fetches the latest Employee Self-Service samples from the
microsoft/CopilotStudioSamples repo and saves them to
src/examples/ess-samples/.

Usage:
    python scripts/sync_samples.py          — Fetch all samples
    python scripts/sync_samples.py --force  — Re-download even if files exist

Source: https://github.com/microsoft/CopilotStudioSamples/tree/main/EmployeeSelfServiceAgent
"""

import os
import re
import sys

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package not found. Run: pip install requests")
    sys.exit(1)

REPO = "microsoft/CopilotStudioSamples"
BRANCH = "main"
SOURCE_PATH = "EmployeeSelfServiceAgent"
API_BASE = f"https://api.github.com/repos/{REPO}/contents"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"

OUTPUT_DIR = os.path.join("src", "examples", "ess-samples")

SKIP_FILES = {".gitignore", "LICENSE"}
# Skip media/image files — not useful for agent context
SKIP_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico"}


def get_headers():
    """Build GitHub API headers, with optional auth token."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def list_contents(path):
    """List contents of a GitHub directory. Returns list of items."""
    url = f"{API_BASE}/{path}?ref={BRANCH}"
    resp = requests.get(url, headers=get_headers(), timeout=30)
    if resp.status_code == 403:
        print("ERROR: GitHub API rate limit hit. Set GITHUB_TOKEN env var.")
        sys.exit(1)
    resp.raise_for_status()
    return resp.json()


def fetch_raw_file(github_path):
    """Download a file from raw.githubusercontent.com."""
    url = f"{RAW_BASE}/{github_path}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def strip_frontmatter(content):
    """Remove YAML frontmatter (--- delimited) from markdown."""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:].lstrip("\n")
    return content


def clean_markdown(content):
    """Strip frontmatter from markdown files."""
    content = strip_frontmatter(content)
    # Remove multiple consecutive blank lines
    content = re.sub(r'\n{3,}', '\n\n', content)
    return content.strip() + "\n"


def walk_and_fetch(github_path, local_base, force=False):
    """Recursively walk a GitHub directory and download all files."""
    created = 0
    skipped = 0

    items = list_contents(github_path)

    for item in sorted(items, key=lambda x: x["name"]):
        name = item["name"]
        item_type = item["type"]
        item_path = item["path"]  # full path in repo

        # Compute local destination relative to SOURCE_PATH
        rel_path = item_path[len(SOURCE_PATH):].lstrip("/")
        local_path = os.path.join(local_base, rel_path)

        if item_type == "dir":
            # Recurse into subdirectory
            c, s = walk_and_fetch(item_path, local_base, force)
            created += c
            skipped += s

        elif item_type == "file":
            # Skip unwanted files
            if name in SKIP_FILES:
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in SKIP_EXTENSIONS:
                continue

            # Check if already exists
            if os.path.exists(local_path) and not force:
                print(f"  SKIP {local_path} (exists)")
                skipped += 1
                continue

            print(f"  Fetching {rel_path}...", end=" ")
            try:
                raw = fetch_raw_file(item_path)

                # Clean markdown files
                if name.endswith(".md"):
                    raw = clean_markdown(raw)

                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(raw)
                print(f"→ {local_path}")
                created += 1
            except Exception as e:
                print(f"FAILED: {e}")

    return created, skipped


def main():
    force = "--force" in sys.argv

    print(f"Fetching ESS samples from {REPO}/{SOURCE_PATH}...")
    print(f"Output: {OUTPUT_DIR}/\n")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    created, skipped = walk_and_fetch(SOURCE_PATH, OUTPUT_DIR, force)

    print(f"\nDone. {created} files written, {skipped} skipped.")
    print(f"Output: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
