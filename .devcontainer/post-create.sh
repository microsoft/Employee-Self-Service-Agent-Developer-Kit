#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SCRIPTS_DIR="$REPO_ROOT/solutions/ess-maker-skills/scripts"

has_dotnet_runtime() {
    if command -v dotnet >/dev/null 2>&1 &&
        dotnet --list-runtimes 2>/dev/null | grep -q '^Microsoft\.NETCore\.App 10\.'; then
        return 0
    fi
    compgen -G "$HOME/.dotnet/shared/Microsoft.NETCore.App/10.*" >/dev/null
}

install_dotnet_runtime() {
    local installer
    installer="$(mktemp)"
    if ! curl --proto '=https' --tlsv1.2 -fsSL \
        https://dot.net/v1/dotnet-install.sh \
        -o "$installer"; then
        rm -f "$installer"
        return 1
    fi
    bash "$installer" \
        --channel 10.0 \
        --runtime dotnet \
        --install-dir "$HOME/.dotnet"
    local result=$?
    rm -f "$installer"
    return "$result"
}

install_nuget() {
    sudo apt-get update -qq &&
        sudo apt-get install -y --no-install-recommends ca-certificates curl mono-complete &&
        sudo install -d /usr/local/share/nuget &&
        sudo curl --proto '=https' --tlsv1.2 -fsSL \
            https://dist.nuget.org/win-x86-commandline/latest/nuget.exe \
            -o /usr/local/share/nuget/nuget.exe &&
        sudo tee /usr/local/bin/nuget >/dev/null <<'EOF' &&
#!/usr/bin/env bash
exec mono /usr/local/share/nuget/nuget.exe "$@"
EOF
        sudo chmod +x /usr/local/bin/nuget
}

if ! has_dotnet_runtime; then
    if ! install_dotnet_runtime; then
        echo "WARNING: Serialization support dependency '.NET 10 Runtime' was not installed."
        echo "Codespace setup will continue."
        echo "After installing the .NET 10 runtime, run:"
        echo "  python $SCRIPTS_DIR/install_agentbuilder_object_model.py"
    fi
fi

if ! command -v nuget >/dev/null 2>&1; then
    if ! install_nuget; then
        echo "WARNING: Serialization support dependencies were not installed."
        echo "Codespace setup will continue."
        echo "After installing Mono and NuGet, run:"
        echo "  python $SCRIPTS_DIR/install_agentbuilder_object_model.py"
    fi
fi

pip install --quiet --disable-pip-version-check -r "$SCRIPTS_DIR/requirements.txt"
if command -v nuget >/dev/null 2>&1; then
    if ! python "$SCRIPTS_DIR/install_agentbuilder_object_model.py"; then
        echo "WARNING: Serialization support dependencies were not installed."
        echo "Codespace setup will continue."
        echo "After resolving the reported NuGet issue, run:"
        echo "  python $SCRIPTS_DIR/install_agentbuilder_object_model.py"
    fi
fi

echo ""
echo "=== ESS Maker Kit ready! ==="
echo "Open File > Open Folder and select solutions/ess-maker-skills, then run /setup in Copilot Chat."
echo ""
