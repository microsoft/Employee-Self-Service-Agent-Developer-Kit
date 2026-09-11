#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SCRIPTS_DIR="$REPO_ROOT/solutions/ess-maker-skills/scripts"

if ! command -v nuget >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends ca-certificates curl mono-complete
    sudo install -d /usr/local/share/nuget
    sudo curl --proto '=https' --tlsv1.2 -fsSL \
        https://dist.nuget.org/win-x86-commandline/latest/nuget.exe \
        -o /usr/local/share/nuget/nuget.exe
    sudo tee /usr/local/bin/nuget >/dev/null <<'EOF'
#!/usr/bin/env bash
exec mono /usr/local/share/nuget/nuget.exe "$@"
EOF
    sudo chmod +x /usr/local/bin/nuget
fi

pip install --quiet --disable-pip-version-check -r "$SCRIPTS_DIR/requirements.txt"
python "$SCRIPTS_DIR/install_agentbuilder_object_model.py"

echo ""
echo "=== ESS Maker Kit ready! ==="
echo "Open File > Open Folder and select solutions/ess-maker-skills, then run /setup in Copilot Chat."
echo ""
