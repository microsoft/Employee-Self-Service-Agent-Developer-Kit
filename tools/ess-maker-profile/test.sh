#!/usr/bin/env bash
# ESS Maker profile POC: structural validation.
# Does not exercise the VS Code runtime — that requires a desktop session.

set -euo pipefail
cd "$(dirname "$0")"

echo "=== ess-maker-profile: JSON validation ==="

NODE="${NODE:-node}"
if ! command -v "$NODE" >/dev/null 2>&1; then
    echo "  node not installed, skipping (non-blocking on this CI image)"
    exit 0
fi

for f in settings.json ess-maker.code-profile extension/package.json; do
    echo "  - $f"
    "$NODE" -e "JSON.parse(require('fs').readFileSync('$f','utf8'))"
done

echo "=== ess-maker-profile: walkthrough markdown files exist ==="
"$NODE" -e "
const fs = require('fs');
const path = require('path');
const pkg = JSON.parse(fs.readFileSync('extension/package.json','utf8'));
const steps = pkg.contributes.walkthroughs[0].steps;
let missing = 0;
for (const s of steps) {
    const p = path.join('extension', s.media.markdown);
    if (!fs.existsSync(p)) {
        console.error('  MISSING:', p);
        missing++;
    } else {
        console.log('  -', p);
    }
}
if (missing > 0) {
    console.error('Walkthrough markdown files missing:', missing);
    process.exit(1);
}
"

echo "=== ess-maker-profile: command bindings cross-check ==="
"$NODE" -e "
const fs = require('fs');
const pkg = JSON.parse(fs.readFileSync('extension/package.json','utf8'));
const ext = fs.readFileSync('extension/extension.js','utf8');
const declared = new Set(pkg.contributes.commands.map(c => c.command));
let bad = 0;
// Dynamic per-action commands must have a registration loop.
if (!ext.includes('registerCommand(\`essMaker.run_')) {
    console.error('  extension.js missing dynamic per-action registerCommand'); bad++;
}
// Statically-declared commands must each be registered AND declared.
const must = ['essMaker.runSetup','essMaker.runCreate','essMaker.runScan','essMaker.runFlightcheck','essMaker.runPush','essMaker.applyMakerLayout','essMaker.restoreStandardLayout','essMaker.openWalkthrough','essMaker.focusActions','essMaker.startChatOnly'];
for (const r of must) {
    if (!declared.has(r)) { console.error('  package.json missing command:', r); bad++; }
    if (!ext.includes(r)) { console.error('  extension.js missing command:', r); bad++; }
}
if (bad > 0) process.exit(1);
console.log('  all commands declared and wired');
"

echo "=== ess-maker-profile: all checks passed ==="
