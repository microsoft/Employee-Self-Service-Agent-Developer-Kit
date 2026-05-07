# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Bulk Extract Script

Reads a JSON file containing agent components from Dataverse and writes
each component's data to a local file.

Usage: python scripts/extract.py <components_json> <output_dir>

The agent calls this during onboarding Step 4. The agent:
1. Queries Dataverse for all components in one read_query call
2. Writes the JSON result to a temp file
3. Runs this script to write all files at once
"""
import json
import os
import re
import sys

TYPE_MAP = {
    9:  ("topics", ".mcs.yml"),
    12: ("variables", ".mcs.yml"),
    15: (None, "agent.mcs.yml"),
    18: (None, "settings.mcs.yml"),
    16: ("knowledge", ".mcs.yml"),
    14: ("attachments", ".mcs.yml"),
}

def friendly_filename(name, schemaname):
    """Derive a short, readable filename from the friendly name or schema."""
    raw = name if name else schemaname.rsplit(".", 1)[-1]
    raw = re.sub(r"^\[.*?\]\s*[-\u2013\u2014]\s*", "", raw)
    slug = raw.strip().replace("_", "-")
    slug = re.sub(r"[^a-zA-Z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-").lower()
    return slug or schemaname.rsplit(".", 1)[-1].lower()

def extract(components_path, output_dir):
    with open(components_path, "r", encoding="utf-8") as f:
        components = json.load(f)
    os.makedirs(output_dir, exist_ok=True)
    written = skipped = 0
    for comp in components:
        data = comp.get("data")
        if not data:
            print(f"  SKIP (no data): {comp.get('name', 'unknown')}")
            skipped += 1
            continue
        ctype = comp.get("componenttype")
        schemaname = comp.get("schemaname", "unknown")
        name = comp.get("name", schemaname)
        mapping = TYPE_MAP.get(ctype)
        if mapping is None:
            subfolder, filename = "other", f"{friendly_filename(name, schemaname)}.mcs.yml"
        else:
            subfolder, ext = mapping
            if subfolder is None:
                subfolder, filename = "", ext
            else:
                filename = f"{friendly_filename(name, schemaname)}{ext}"
        if subfolder:
            folder = os.path.join(output_dir, subfolder)
            os.makedirs(folder, exist_ok=True)
            filepath = os.path.join(folder, filename)
        else:
            filepath = os.path.join(output_dir, filename)
        content = data.replace("\r\n", "\n")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  OK: {name} -> {os.path.relpath(filepath, output_dir)}")
        written += 1
    print(f"\nDone: {written} written, {skipped} skipped")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} <components_json> <output_dir>")
        sys.exit(1)
    extract(sys.argv[1], sys.argv[2])
