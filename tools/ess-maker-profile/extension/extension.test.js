// Unit tests for extension.js pure logic (no VS Code dependency needed).
// Run with: node extension.test.js

const assert = require('assert');
const fs = require('fs');
const path = require('path');

// --- Extract testable constants and functions from extension.js ---
// We parse the source to avoid requiring vscode.
const src = fs.readFileSync(path.join(__dirname, 'extension.js'), 'utf8');

// Extract ACTIONS array
const actionsMatch = src.match(/const ACTIONS = (\[[\s\S]*?\]);/);
if (!actionsMatch) throw new Error('Could not find ACTIONS in extension.js');
const ACTIONS = eval(actionsMatch[1]);

// Extract CHAT_ONLY_LAYOUT
const layoutMatch = src.match(/const CHAT_ONLY_LAYOUT = (\{[\s\S]*?\});/);
if (!layoutMatch) throw new Error('Could not find CHAT_ONLY_LAYOUT in extension.js');
const CHAT_ONLY_LAYOUT = eval(`(${layoutMatch[1]})`);

// Extract actionState function
const actionStateFn = src.match(/function actionState\(action, completed\) \{[\s\S]*?return \{[^}]+\};\s*\}/);
if (!actionStateFn) throw new Error('Could not find actionState in extension.js');
const actionState = eval(`(${actionStateFn[0].replace('function actionState', 'function')})`);

// Extract the auto-update pure helpers. They are self-contained (no vscode)
// so we pull their source out of extension.js and eval them together in one
// scope (extensionIsStale calls compareVersions).
function _extractFn(name) {
    const re = new RegExp(`function ${name}\\([\\s\\S]*?\\n\\}`, 'm');
    const m = src.match(re);
    if (!m) throw new Error(`Could not find ${name} in extension.js`);
    return m[0];
}
const _updateHelpersSrc = [
    'parseLsRemoteSha', 'localIsBehind', 'compareVersions',
    'extensionIsStale', 'classifyPullError',
].map(_extractFn).join('\n\n');
const { parseLsRemoteSha, localIsBehind, compareVersions, extensionIsStale, classifyPullError } =
    eval(`(function () { ${_updateHelpersSrc}\n return { parseLsRemoteSha, localIsBehind, compareVersions, extensionIsStale, classifyPullError }; })()`);

// --- Tests ---

let passed = 0;
let failed = 0;

function test(name, fn) {
    try {
        fn();
        passed++;
        console.log(`  ✓ ${name}`);
    } catch (e) {
        failed++;
        console.log(`  ✗ ${name}`);
        console.log(`    ${e.message}`);
    }
}

console.log('ACTIONS structure:');

test('has 7 actions', () => {
    assert.strictEqual(ACTIONS.length, 7);
});

test('every action has required fields', () => {
    for (const a of ACTIONS) {
        assert.ok(a.id, `missing id`);
        assert.ok(a.icon, `missing icon for ${a.id}`);
        assert.ok(a.label, `missing label for ${a.id}`);
        assert.ok(a.sub, `missing sub for ${a.id}`);
        assert.ok(a.slash, `missing slash for ${a.id}`);
        assert.ok(Array.isArray(a.requires), `requires not array for ${a.id}`);
    }
});

test('every slash command starts with /', () => {
    for (const a of ACTIONS) {
        assert.ok(a.slash.startsWith('/'), `${a.id}: slash "${a.slash}" doesn't start with /`);
    }
});

test('setup has no requirements', () => {
    const setup = ACTIONS.find(a => a.id === 'setup');
    assert.deepStrictEqual(setup.requires, []);
});

test('evaluate and push require setup', () => {
    const evaluate = ACTIONS.find(a => a.id === 'evaluate');
    const push = ACTIONS.find(a => a.id === 'push');
    assert.ok(evaluate.requires.includes('setup'));
    assert.ok(push.requires.includes('setup'));
});

test('all requires reference valid action ids', () => {
    const ids = new Set(ACTIONS.map(a => a.id));
    for (const a of ACTIONS) {
        for (const r of a.requires) {
            assert.ok(ids.has(r), `${a.id} requires "${r}" which is not a valid action id`);
        }
    }
});

test('no duplicate action ids', () => {
    const ids = ACTIONS.map(a => a.id);
    assert.strictEqual(ids.length, new Set(ids).size);
});

console.log('\nactionState logic:');

test('action with no requires is always enabled', () => {
    const result = actionState(ACTIONS[0], new Set());
    assert.strictEqual(result.enabled, true);
    assert.strictEqual(result.blockedBy, null);
});

test('action is disabled when requires are unmet', () => {
    const create = ACTIONS.find(a => a.id === 'create');
    const result = actionState(create, new Set());
    assert.strictEqual(result.enabled, false);
    assert.ok(Array.isArray(result.blockedBy));
    assert.ok(result.blockedBy.length > 0);
});

test('action is enabled when all requires are met', () => {
    const create = ACTIONS.find(a => a.id === 'create');
    const result = actionState(create, new Set(['setup']));
    assert.strictEqual(result.enabled, true);
    assert.strictEqual(result.blockedBy, null);
});

test('evaluate requires setup', () => {
    const evaluate = ACTIONS.find(a => a.id === 'evaluate');
    // Not enabled before setup.
    let result = actionState(evaluate, new Set());
    assert.strictEqual(result.enabled, false);
    // Enabled once setup is done.
    result = actionState(evaluate, new Set(['setup']));
    assert.strictEqual(result.enabled, true);
});

test('done reflects whether action itself is completed', () => {
    const setup = ACTIONS[0];
    assert.strictEqual(actionState(setup, new Set()).done, false);
    assert.strictEqual(actionState(setup, new Set(['setup'])).done, true);
});

test('blockedBy contains human-readable labels', () => {
    const push = ACTIONS.find(a => a.id === 'push');
    const result = actionState(push, new Set());
    assert.ok(result.blockedBy.includes('Setup'));
});

console.log('\nCHAT_ONLY_LAYOUT settings:');

test('hides activity bar', () => {
    assert.strictEqual(CHAT_ONLY_LAYOUT['workbench.activityBar.location'], 'hidden');
});

test('hides menu bar', () => {
    assert.strictEqual(CHAT_ONLY_LAYOUT['window.menuBarVisibility'], 'hidden');
});

test('hides status bar', () => {
    assert.strictEqual(CHAT_ONLY_LAYOUT['workbench.statusBar.visible'], false);
});

test('hides editor tabs', () => {
    assert.strictEqual(CHAT_ONLY_LAYOUT['workbench.editor.showTabs'], 'none');
});

test('disables startup editor', () => {
    assert.strictEqual(CHAT_ONLY_LAYOUT['workbench.startupEditor'], 'none');
});

console.log('\npackage.json:');

const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, 'package.json'), 'utf8'));

test('view container is in activitybar (primary sidebar)', () => {
    assert.ok(pkg.contributes.viewsContainers.activitybar);
    assert.strictEqual(pkg.contributes.viewsContainers.activitybar[0].id, 'essMakerActions');
});

test('view is webview type', () => {
    const view = pkg.contributes.views.essMakerActions[0];
    assert.strictEqual(view.type, 'webview');
    assert.strictEqual(view.id, 'essMaker.actionsView');
});

test('activates on startup finished', () => {
    assert.ok(pkg.activationEvents.includes('onStartupFinished'));
});

test('exposes the essMaker.autoUpdateCheck opt-out setting', () => {
    const prop = pkg.contributes.configuration.properties['essMaker.autoUpdateCheck'];
    assert.ok(prop, 'essMaker.autoUpdateCheck missing from configuration');
    assert.strictEqual(prop.type, 'boolean');
    assert.strictEqual(prop.default, true);
});

console.log('\nauto-update: parseLsRemoteSha:');

test('extracts sha from a ls-remote line', () => {
    const out = 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678\trefs/heads/main\n';
    assert.strictEqual(parseLsRemoteSha(out), 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678');
});

test('lowercases and picks the first non-empty line', () => {
    const out = '\n\nABCDEF1234567890ABCDEF1234567890ABCDEF12\trefs/heads/main';
    assert.strictEqual(parseLsRemoteSha(out), 'abcdef1234567890abcdef1234567890abcdef12');
});

test('returns null for empty or non-sha output', () => {
    assert.strictEqual(parseLsRemoteSha(''), null);
    assert.strictEqual(parseLsRemoteSha(null), null);
    assert.strictEqual(parseLsRemoteSha('fatal: could not read from remote'), null);
});

console.log('\nauto-update: localIsBehind:');

test('true when shas differ', () => {
    assert.strictEqual(localIsBehind('aaaaaaa', 'bbbbbbb'), true);
});

test('false when shas match (case/space-insensitive)', () => {
    assert.strictEqual(localIsBehind('ABCDEF0', ' abcdef0 '), false);
});

test('false when either sha is missing', () => {
    assert.strictEqual(localIsBehind('', 'abcdef0'), false);
    assert.strictEqual(localIsBehind('abcdef0', null), false);
});

console.log('\nauto-update: compareVersions / extensionIsStale:');

test('compareVersions orders correctly', () => {
    assert.strictEqual(compareVersions('0.4.24', '0.4.23'), 1);
    assert.strictEqual(compareVersions('0.4.23', '0.4.24'), -1);
    assert.strictEqual(compareVersions('0.4.24', '0.4.24'), 0);
    assert.strictEqual(compareVersions('1.0', '0.9.9'), 1);
});

test('extensionIsStale true only when repo version is newer', () => {
    assert.strictEqual(extensionIsStale('0.4.23', '0.4.24'), true);
    assert.strictEqual(extensionIsStale('0.4.24', '0.4.24'), false);
    assert.strictEqual(extensionIsStale('0.4.25', '0.4.24'), false);
});

test('extensionIsStale false when a version is missing', () => {
    assert.strictEqual(extensionIsStale(undefined, '0.4.24'), false);
    assert.strictEqual(extensionIsStale('0.4.24', null), false);
});

console.log('\nauto-update: classifyPullError:');

test('classifies offline errors', () => {
    assert.strictEqual(classifyPullError('fatal: unable to access ... Could not resolve host: github.com').kind, 'offline');
});

test('classifies non-fast-forward / diverged errors', () => {
    assert.strictEqual(classifyPullError('fatal: Not possible to fast-forward, aborting.').kind, 'diverged');
});

test('classifies dirty working tree errors', () => {
    assert.strictEqual(classifyPullError('error: Your local changes to the following files would be overwritten by merge').kind, 'dirty');
});

test('falls back to unknown with actionable guidance', () => {
    const r = classifyPullError('some other git failure');
    assert.strictEqual(r.kind, 'unknown');
    assert.ok(/re-run the ESS installer/i.test(r.guidance));
});

// --- Summary ---
console.log(`\n${passed + failed} tests, ${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
