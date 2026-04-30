# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Copilot Kit - Sync Official ESS Docs

Fetches the latest Employee Self-Service documentation from the
MicrosoftDocs/microsoft-365-docs repo and saves cleaned markdown
files to src/reference/ess-docs/.

Usage:
    python scripts/sync_docs.py          — Fetch all docs
    python scripts/sync_docs.py --force  — Re-download even if files exist

Source: https://github.com/MicrosoftDocs/microsoft-365-docs/tree/public/copilot/employee-self-service
"""

import os
import re
import sys

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package not found. Run: pip install requests")
    sys.exit(1)

REPO = "MicrosoftDocs/microsoft-365-docs"
BRANCH = "public"
SOURCE_PATH = "copilot/employee-self-service"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{SOURCE_PATH}"
API_URL = f"https://api.github.com/repos/{REPO}/contents/{SOURCE_PATH}?ref={BRANCH}"

OUTPUT_DIR = os.path.join("src", "reference", "ess-docs")

# Organize files into subdirectories by prefix/topic
CATEGORY_MAP = {
    "integrations": [
        "servicenow", "workday", "sap", "sharepoint-filtering",
    ],
    "deployment": [
        "deploy-overview-alm", "deployment-checklist", "prerequisites",
        "prepare", "publish", "install",
    ],
    "operations": [
        "evaluations", "usage-analytics", "auditing-logging",
        "known-issues-limitations", "feedback",
    ],
    "customization": [
        "customize", "agent-handoff", "design-best-practices",
        "emotional-quotient-ambiguity", "employee-self-service-multilingual",
        "optimization-sharepoint", "sharepoint-filtering",
    ],
}

SKIP_FILES = {"TOC.yml"}
SKIP_DIRS = {"media"}


def categorize(filename):
    """Determine which subdirectory a file belongs in."""
    base = filename.replace(".md", "")
    for category, prefixes in CATEGORY_MAP.items():
        for prefix in prefixes:
            if base.startswith(prefix):
                return category
    return ""  # root level


def strip_frontmatter(content):
    """Remove YAML frontmatter (--- delimited) from markdown."""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:].lstrip("\n")
    return content


def clean_content(content):
    """Strip frontmatter and clean up MS Learn-specific markup."""
    content = strip_frontmatter(content)

    # Remove MS Learn include references like [!INCLUDE [...](...)]
    content = re.sub(r'\[!INCLUDE\s*\[.*?\]\(.*?\)\]', '', content)

    # Remove zone pivot markers
    content = re.sub(r'::: ?zone .*?\n', '', content)
    content = re.sub(r'::: ?zone-end\n?', '', content)

    # Clean up image references to just show alt text
    # :::image ... alt-text="..." ... :::  →  [Image: alt-text]
    content = re.sub(
        r':::image[^:]*?alt-text="([^"]*)"[^:]*?:::',
        r'[Image: \1]',
        content
    )

    # Remove multiple consecutive blank lines
    content = re.sub(r'\n{3,}', '\n\n', content)

    return content.strip() + "\n"


def fetch_file_list():
    """Get list of files from GitHub API."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    # Check for GH token to avoid rate limits
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"

    resp = requests.get(API_URL, headers=headers, timeout=30)
    if resp.status_code == 403:
        print("ERROR: GitHub API rate limit hit. Set GITHUB_TOKEN env var.")
        sys.exit(1)
    resp.raise_for_status()
    return resp.json()


def fetch_raw_file(filename):
    """Download a single file from raw.githubusercontent.com."""
    url = f"{RAW_BASE}/{filename}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def main():
    force = "--force" in sys.argv

    print(f"Fetching file list from {SOURCE_PATH}...")
    items = fetch_file_list()

    md_files = [
        item["name"] for item in items
        if item["type"] == "file"
        and item["name"].endswith(".md")
        and item["name"] not in SKIP_FILES
    ]

    print(f"Found {len(md_files)} markdown files.\n")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    created = 0
    skipped = 0

    for filename in sorted(md_files):
        category = categorize(filename)
        if category:
            dest_dir = os.path.join(OUTPUT_DIR, category)
        else:
            dest_dir = OUTPUT_DIR

        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, filename)

        if os.path.exists(dest_path) and not force:
            print(f"  SKIP {dest_path} (exists, use --force to overwrite)")
            skipped += 1
            continue

        print(f"  Fetching {filename}...", end=" ")
        try:
            raw = fetch_raw_file(filename)
            cleaned = clean_content(raw)
            with open(dest_path, "w", encoding="utf-8") as f:
                f.write(cleaned)
            print(f"→ {dest_path}")
            created += 1
        except Exception as e:
            print(f"FAILED: {e}")

    print(f"\nDone. {created} files written, {skipped} skipped.")
    print(f"Output: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
