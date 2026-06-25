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

test('evaluate and push require flightcheck', () => {
    const evaluate = ACTIONS.find(a => a.id === 'evaluate');
    const push = ACTIONS.find(a => a.id === 'push');
    assert.ok(evaluate.requires.includes('flightcheck'));
    assert.ok(push.requires.includes('flightcheck'));
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

test('evaluate requires both setup and flightcheck', () => {
    const evaluate = ACTIONS.find(a => a.id === 'evaluate');
    // Only setup done
    let result = actionState(evaluate, new Set(['setup']));
    assert.strictEqual(result.enabled, false);
    // Only flightcheck done
    result = actionState(evaluate, new Set(['flightcheck']));
    assert.strictEqual(result.enabled, false);
    // Both done
    result = actionState(evaluate, new Set(['setup', 'flightcheck']));
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
    assert.ok(result.blockedBy.includes('Connect'));
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

// --- Summary ---
console.log(`\n${passed + failed} tests, ${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
