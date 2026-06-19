// ESS Maker POC extension — chat-only layout.
//
// Goal: the customer sees Copilot Chat in the center, a column of big
// buttons on the right, and nothing else. No file explorer, no editor
// tabs, no menu bar, no status bar.

const vscode = require('vscode');
const _fs = require('fs');
const _path = require('path');

// Debug log file for troubleshooting activation/wizard detection
const _logFile = _path.join(process.env.APPDATA || process.env.HOME || '/tmp', 'ess-maker-debug.log');
function _log(msg) {
    const line = `[${new Date().toISOString()}] ${msg}\n`;
    try { _fs.appendFileSync(_logFile, line); } catch (_) {}
}

const EXT_ID = 'microsoft-ess.ess-maker-profile';
const APPLIED_KEY = 'essMaker.chatOnlyApplied.v7';
const LITE_MODE_KEY = 'essMaker.liteMode.v1';

// Settings that strip developer chrome to the bone. Applied at GLOBAL (user)
// scope because workspace-scope leaves menu/title-bar/activity-bar visible
// until the user reloads — and even then those are not reliably overridden
// from a workspace setting on Windows.
const CHAT_ONLY_LAYOUT = {
    'workbench.activityBar.location': 'hidden',
    'workbench.statusBar.visible': false,
    'workbench.editor.showTabs': 'none',
    'workbench.editor.editorActionsLocation': 'hidden',
    'workbench.editor.empty.hint': 'hidden',
    'workbench.layoutControl.enabled': false,
    'workbench.tips.enabled': false,
    'workbench.sideBar.location': 'left',
    'workbench.startupEditor': 'none',
    'window.menuBarVisibility': 'hidden',
    'window.commandCenter': false,
    'window.customTitleBarVisibility': 'never',
    'window.titleBarStyle': 'custom',
    'editor.minimap.enabled': false,
    'editor.lineNumbers': 'off',
    'editor.glyphMargin': false,
    'editor.folding': false,
    'editor.renderLineHighlight': 'none',
    'breadcrumbs.enabled': false,
    'outline.icons': false,
    'scm.alwaysShowProviders': false,
    'problems.decorations.enabled': false,
    'chat.commandCenter.enabled': false,
    'zenMode.hideTabs': true,
    'zenMode.hideStatusBar': true,
    'zenMode.hideActivityBar': true,
    'zenMode.hideLineNumbers': true,
    'zenMode.fullScreen': false,
    'zenMode.centerLayout': false,
    'zenMode.silentNotifications': true,
    'telemetry.telemetryLevel': 'error',
};

// Slash commands the user can fire via the right-hand button rail.
// `requires` lists action ids that must already be "done" before this one
// becomes clickable. The state is tracked in globalState and is also
// inferred from workspace contents (e.g. presence of topic yaml files).
const ACTIONS = [
    { id: 'setup',       icon: '🔌', label: 'Connect',              sub: 'Sign in to your environment',  slash: '/setup',       requires: [] },
    { id: 'create',      icon: '✨', label: 'Create a topic',       sub: 'Describe a new conversation',  slash: '/create',      requires: ['setup'] },
    { id: 'update',      icon: '✏️', label: 'Update a topic',       sub: 'Tweak an existing topic',      slash: '/update',      requires: ['setup'] },
    { id: 'scan',        icon: '🔍', label: 'Scan for issues',      sub: 'Find broken bindings',         slash: '/scan',        requires: ['setup'] },
    { id: 'flightcheck', icon: '✈️', label: 'Run a flightcheck',    sub: '41+ readiness checks',         slash: '/flightcheck', requires: ['setup'] },
    { id: 'evaluate',    icon: '📊', label: 'Generate tests',       sub: 'Build evaluation test sets',   slash: '/evaluate',    requires: ['setup', 'flightcheck'] },
    { id: 'push',        icon: '🚀', label: 'Push to Copilot Studio', sub: 'Safely deploy your changes', slash: '/push',        requires: ['setup', 'flightcheck'] },
];

const STATE_KEY = 'essMaker.completedActions.v3';

let _tutorialPanel = null;
let _prereqWatcher = null;

function getCompleted(context) {
    return new Set(context.globalState.get(STATE_KEY, []));
}

async function markCompleted(context, id) {
    const set = getCompleted(context);
    set.add(id);
    await context.globalState.update(STATE_KEY, Array.from(set));
}

async function unmarkCompleted(context, id) {
    const set = getCompleted(context);
    set.delete(id);
    await context.globalState.update(STATE_KEY, Array.from(set));
}

async function resetCompleted(context) {
    await context.globalState.update(STATE_KEY, []);
}

// Check workspace files to determine which prerequisites are actually met.
// Returns the set of action IDs whose artifacts exist on disk.
async function checkPrerequisites() {
    const met = new Set();
    const folders = vscode.workspace.workspaceFolders;
    if (!folders || !folders.length) return met;
    const root = folders[0].uri;

    // /setup is complete when .local/config.json exists with "setup": "complete"
    try {
        const configUri = vscode.Uri.joinPath(root, '.local', 'config.json');
        const content = await vscode.workspace.fs.readFile(configUri);
        const json = JSON.parse(Buffer.from(content).toString('utf8'));
        if (json.setup === 'complete') {
            met.add('setup');
        }
    } catch (_) { /* file doesn't exist or invalid */ }

    // /flightcheck is complete when workspace/flightcheck/results.json exists
    try {
        const resultsUri = vscode.Uri.joinPath(root, 'workspace', 'flightcheck', 'results.json');
        await vscode.workspace.fs.stat(resultsUri);
        met.add('flightcheck');
    } catch (_) { /* file doesn't exist */ }

    return met;
}

// Sync the completed state with actual file artifacts on disk.
// Adds IDs whose files now exist, removes IDs whose files are gone.
async function syncPrerequisites(context) {
    const onDisk = await checkPrerequisites();
    const stored = getCompleted(context);
    let changed = false;

    // Mark as complete if artifact appeared
    for (const id of onDisk) {
        if (!stored.has(id)) {
            stored.add(id);
            changed = true;
        }
    }
    // Un-mark if artifact was deleted (e.g. user re-ran setup and it failed)
    for (const id of ['setup', 'flightcheck']) {
        if (stored.has(id) && !onDisk.has(id)) {
            stored.delete(id);
            changed = true;
        }
    }

    if (changed) {
        await context.globalState.update(STATE_KEY, Array.from(stored));
    }
    return changed;
}

// Start a FileSystemWatcher that monitors prerequisite artifacts and
// updates button states when they appear or disappear.
function startPrereqWatcher(context) {
    if (_prereqWatcher) return;

    const folders = vscode.workspace.workspaceFolders;
    if (!folders || !folders.length) return;

    // Watch for .local/config.json and workspace/flightcheck/results.json
    const configPattern = new vscode.RelativePattern(folders[0], '.local/config.json');
    const flightcheckPattern = new vscode.RelativePattern(folders[0], 'workspace/flightcheck/results.json');

    const configWatcher = vscode.workspace.createFileSystemWatcher(configPattern);
    const flightcheckWatcher = vscode.workspace.createFileSystemWatcher(flightcheckPattern);

    const refresh = async () => {
        const changed = await syncPrerequisites(context);
        if (changed && _actionsViewProvider) {
            _actionsViewProvider.refresh();
        }
    };

    // Trigger on create, change, or delete
    configWatcher.onDidCreate(refresh);
    configWatcher.onDidChange(refresh);
    configWatcher.onDidDelete(refresh);
    flightcheckWatcher.onDidCreate(refresh);
    flightcheckWatcher.onDidChange(refresh);
    flightcheckWatcher.onDidDelete(refresh);

    _prereqWatcher = { configWatcher, flightcheckWatcher };

    // Also poll every 10s as a fallback (file watchers can miss events
    // when files are written by external processes like the MCP server).
    const interval = setInterval(refresh, 10000);

    // Register disposables
    context.subscriptions.push(configWatcher, flightcheckWatcher, {
        dispose: () => clearInterval(interval)
    });

    // Initial sync
    refresh();
}

function actionState(action, completed) {
    const unmet = action.requires.filter(r => !completed.has(r));
    const enabled = unmet.length === 0;
    const blockedBy = unmet.length === 0 ? null
        : unmet.map(id => ACTIONS.find(a => a.id === id)?.label || id);
    return { enabled, blockedBy, done: completed.has(action.id) };
}

async function applySettings(settings, target) {
    const cfg = vscode.workspace.getConfiguration();
    for (const [key, value] of Object.entries(settings)) {
        try { await cfg.update(key, value, target); } catch (err) {
            console.warn(`[ess-maker] could not set ${key}:`, err.message);
        }
    }
}

async function clearSettings(keys, target) {
    const cfg = vscode.workspace.getConfiguration();
    for (const key of keys) {
        try { await cfg.update(key, undefined, target); } catch (err) {
            console.warn(`[ess-maker] could not clear ${key}:`, err.message);
        }
    }
}

async function tryRun(commandId, ...args) {
    try { await vscode.commands.executeCommand(commandId, ...args); return true; }
    catch (err) { console.warn(`[ess-maker] ${commandId} failed:`, err.message); return false; }
}

function isLiteMode() {
    const cfg = vscode.workspace.getConfiguration();
    return cfg.get('workbench.activityBar.location') === 'hidden';
}


// Wait for the VS Code welcome wizard to be dismissed or completed.
// Reads the global state.vscdb file (SQLite) as raw bytes and searches for
// the `welcomeOnboarding.state` key which VS Code writes when the wizard
// is closed (either completed or dismissed). Pure Node.js — no external
// processes. The key does not exist in the DB before the wizard finishes.
function waitForWelcomeWizard(timeoutMs = 300000) {
    // Resolve state.vscdb path per platform
    let resolvedDbPath;
    if (process.platform === 'win32') {
        resolvedDbPath = _path.join(process.env.APPDATA, 'Code', 'User', 'globalStorage', 'state.vscdb');
    } else if (process.platform === 'darwin') {
        resolvedDbPath = _path.join(require('os').homedir(), 'Library', 'Application Support', 'Code', 'User', 'globalStorage', 'state.vscdb');
    } else {
        resolvedDbPath = _path.join(process.env.XDG_CONFIG_HOME || _path.join(require('os').homedir(), '.config'), 'Code', 'User', 'globalStorage', 'state.vscdb');
    }

    const needle = Buffer.from('welcomeOnboarding.state');
    _log(`waitForWelcomeWizard: watching ${resolvedDbPath}`);

    return new Promise((resolve, reject) => {
        const startTime = Date.now();
        let interval;
        let pollCount = 0;

        function checkDb() {
            pollCount++;
            if (Date.now() - startTime > timeoutMs) {
                _log('waitForWelcomeWizard: TIMEOUT');
                clearInterval(interval);
                reject(new Error('Timed out waiting for welcome wizard'));
                return;
            }

            try {
                if (!_fs.existsSync(resolvedDbPath)) {
                    if (pollCount <= 3) _log(`waitForWelcomeWizard: DB not found yet (poll #${pollCount})`);
                    return;
                }

                const data = _fs.readFileSync(resolvedDbPath);
                const found = data.indexOf(needle) !== -1;

                if (pollCount <= 5 || pollCount % 10 === 0) {
                    _log(`waitForWelcomeWizard: poll #${pollCount}, found=${found}`);
                }

                if (found) {
                    _log('waitForWelcomeWizard: RESOLVED - wizard done');
                    clearInterval(interval);
                    resolve();
                }
            } catch (e) {
                _log(`waitForWelcomeWizard: ERROR on poll #${pollCount}: ${e && e.message}`);
            }
        }

        // Check immediately, then poll every 2 seconds
        checkDb();
        interval = setInterval(checkDb, 2000);
    });
}

// Inject /setup into the Copilot Chat panel (for standard mode — no layout changes).
async function injectSetup() {
    _log('injectSetup: starting');
    // Use the chat open command with query parameter (VS Code 1.102+).
    // isPartialQuery: false makes it submit immediately.
    try {
        await vscode.commands.executeCommand('workbench.action.chat.open', {
            query: '/setup',
            isPartialQuery: false,
        });
        _log('injectSetup: submitted via chat.open query');
        return;
    } catch (e) {
        _log(`injectSetup: chat.open with query failed: ${e && e.message}, falling back to clipboard`);
    }

    // Fallback: open chat, paste /setup via clipboard, and submit.
    const chatCmds = [
        'workbench.action.chat.open',
        'workbench.action.chat.newChat',
    ];
    for (const c of chatCmds) {
        if (await tryRun(c)) break;
    }
    await new Promise((r) => setTimeout(r, 700));
    await tryRun('workbench.action.chat.focusInput');
    await new Promise((r) => setTimeout(r, 200));
    try {
        const prev = await vscode.env.clipboard.readText();
        await vscode.env.clipboard.writeText('/setup');
        await tryRun('editor.action.clipboardPasteAction');
        await new Promise((r) => setTimeout(r, 200));
        await tryRun('workbench.action.chat.submit');
        await new Promise((r) => setTimeout(r, 200));
        await vscode.env.clipboard.writeText(prev || '');
    } catch (e) {
        _log(`injectSetup: clipboard fallback failed: ${e && e.message}`);
    }
}

function openTutorialPanel(column = vscode.ViewColumn.Beside) {
    if (_tutorialPanel) {
        _tutorialPanel.reveal(column);
        return;
    }
    _tutorialPanel = vscode.window.createWebviewPanel(
        'essMaker.tutorial',
        'ESS Maker Tutorial',
        column,
        { enableScripts: true }
    );
    _tutorialPanel.webview.html = getTutorialHtml();
    _tutorialPanel.onDidDispose(() => {
        _tutorialPanel = null;
        _notifyTutorialState(false);
    });
    _tutorialPanel.webview.onDidReceiveMessage((msg) => {
        if (msg?.type === 'closeTutorial') {
            _tutorialPanel?.dispose();
        }
    });
    _notifyTutorialState(true);
}

function closeTutorialPanel() {
    if (_tutorialPanel) {
        _tutorialPanel.dispose();
    }
}

function toggleTutorialPanel() {
    if (_tutorialPanel) {
        closeTutorialPanel();
    } else {
        openTutorialPanel(vscode.ViewColumn.Beside);
    }
}

// Notify the Quick Actions webview about tutorial open/close state.
let _actionsViewProvider = null;
function _notifyTutorialState(open) {
    if (_actionsViewProvider?._view) {
        try {
            _actionsViewProvider._view.webview.postMessage({ type: 'tutorialState', open });
        } catch {}
    }
}

function getTutorialHtml() {
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<style>
    body {
        font-family: var(--vscode-font-family, -apple-system, BlinkMacSystemFont, sans-serif);
        color: var(--vscode-foreground);
        background: var(--vscode-editor-background);
        padding: 24px 32px 48px;
        max-width: 680px;
        margin: 0 auto;
        line-height: 1.65;
        font-size: 13px;
    }
    h1 { font-size: 20px; margin: 0 0 4px; font-weight: 600; }
    .subtitle {
        color: var(--vscode-descriptionForeground);
        margin: 0 0 20px;
        font-size: 13px;
    }
    nav {
        background: var(--vscode-sideBar-background, var(--vscode-editor-background));
        border: 1px solid var(--vscode-panel-border, rgba(128,128,128,0.2));
        border-radius: 6px;
        padding: 12px 16px;
        margin-bottom: 24px;
        line-height: 2;
    }
    nav a {
        color: var(--vscode-textLink-foreground);
        text-decoration: none;
        white-space: nowrap;
    }
    nav a:hover { text-decoration: underline; }
    .sep { opacity: 0.4; margin: 0 6px; }
    h2 {
        font-size: 16px;
        margin: 32px 0 8px;
        padding-bottom: 6px;
        border-bottom: 1px solid var(--vscode-panel-border, rgba(128,128,128,0.2));
        font-weight: 600;
    }
    h3 { font-size: 14px; margin: 18px 0 6px; font-weight: 600; }
    ul, ol { padding-left: 20px; margin: 8px 0; }
    li { margin: 4px 0; }
    blockquote {
        border-left: 3px solid var(--vscode-textLink-foreground, #007acc);
        margin: 12px 0;
        padding: 8px 16px;
        background: var(--vscode-textBlockQuote-background, rgba(128,128,128,0.05));
        border-radius: 0 4px 4px 0;
    }
    blockquote p { margin: 4px 0; }
    strong { font-weight: 600; }
    code {
        background: var(--vscode-textCodeBlock-background, rgba(128,128,128,0.1));
        padding: 1px 5px;
        border-radius: 3px;
        font-size: 12px;
    }
    .close-bar {
        display: flex;
        justify-content: flex-end;
        margin-bottom: 8px;
    }
    .close-btn {
        background: var(--vscode-button-secondaryBackground, rgba(128,128,128,0.2));
        color: var(--vscode-button-secondaryForeground, var(--vscode-foreground));
        border: none;
        border-radius: 4px;
        padding: 4px 12px;
        cursor: pointer;
        font-size: 12px;
        font-family: inherit;
    }
    .close-btn:hover {
        background: var(--vscode-button-secondaryHoverBackground, rgba(128,128,128,0.3));
    }
</style>
</head>
<body>
    <div class="close-bar"><button class="close-btn" id="close-tutorial">✕ Close tutorial</button></div>
    <h1>Welcome to the ESS Maker Kit</h1>
    <p class="subtitle">Build, update, and publish your Employee Self-Service agent with plain English. No code required.</p>

    <nav>
        <a href="#how">How it works</a><span class="sep">·</span>
        <a href="#connect">Connect</a><span class="sep">·</span>
        <a href="#create">Create</a><span class="sep">·</span>
        <a href="#update">Update</a><span class="sep">·</span>
        <a href="#scan">Scan</a><span class="sep">·</span>
        <a href="#flightcheck">FlightCheck</a><span class="sep">·</span>
        <a href="#tests">Generate tests</a><span class="sep">·</span>
        <a href="#push">Push</a>
    </nav>

    <section id="how">
        <h2>\u{1f527} How the kit works</h2>
        <p>You\u2019re about to customize your Employee Self-Service agent \u2014 the assistant your employees use for HR, IT and facilities requests.</p>
        <h3>The workflow</h3>
        <ol>
            <li><strong>Connect</strong> \u2014 Sign in to your Power Platform environment.</li>
            <li><strong>Create a topic</strong> \u2014 Describe what you want in plain English. The kit generates everything.</li>
            <li><strong>Update a topic</strong> \u2014 Modify an existing topic by describing the change.</li>
            <li><strong>Scan</strong> \u2014 Check for broken references and configuration issues.</li>
            <li><strong>Run a flightcheck</strong> \u2014 Run 41+ automated readiness checks.</li>
            <li><strong>Generate tests</strong> \u2014 Create evaluation test sets for regression testing.</li>
            <li><strong>Push</strong> \u2014 Safely deploy your changes to Copilot Studio.</li>
        </ol>
        <p>Each step is available as a button in the <strong>Quick Actions</strong> panel on the left. Click any button to open a guided chat \u2014 just answer the prompts.</p>
        <p>You don\u2019t need to know YAML, JSON or any code.</p>
    </section>

    <section id="connect">
        <h2>\u{1f50c} Connect</h2>
        <p>The <strong>Connect</strong> button signs you in to your Power Platform environment so the kit can:</p>
        <ul>
            <li>Discover your deployed ESS agent and its components.</li>
            <li>Create a local working copy for safe editing.</li>
            <li>Validate connectivity before any changes are pushed.</li>
        </ul>
        <p>When you click Connect, a chat opens with the <code>/setup</code> command \u2014 just answer the prompts (environment URL, then sign-in).</p>
        <blockquote><p>First time? You\u2019ll see a browser pop-up asking you to sign in with your work account. That\u2019s expected.</p></blockquote>
    </section>

    <section id="create">
        <h2>\u2728 Create a topic</h2>
        <p>A <strong>topic</strong> is one conversation your agent can handle \u2014 for example, \u201csubmit a time-off request\u201d or \u201creset my password\u201d.</p>
        <p>When you click <strong>Create a topic</strong>, a chat opens where you describe what you want in plain English. The kit will:</p>
        <ul>
            <li>Generate trigger phrases (the things employees might say).</li>
            <li>Build the conversation flow and adaptive cards.</li>
            <li>Wire up the integration to ServiceNow, Workday, or your custom system if needed.</li>
            <li>Save everything to your local working copy.</li>
        </ul>
        <p>Nothing is pushed to production yet \u2014 that comes later with the Push button.</p>
        <h3>Examples</h3>
        <blockquote><p>\u201cWhen someone asks about their PTO balance, look it up in Workday and show how many days they have left this year.\u201d</p></blockquote>
        <blockquote><p>\u201cLet employees submit IT tickets for laptop issues. Ask for the make/model, what\u2019s wrong, and urgency, then file the ticket in ServiceNow.\u201d</p></blockquote>
    </section>

    <section id="update">
        <h2>\u270f\ufe0f Update a topic</h2>
        <p>The <strong>Update a topic</strong> button lets you modify an existing conversation topic. Describe the change you want in plain English and the kit will:</p>
        <ul>
            <li>Find the matching topic in your local working copy.</li>
            <li>Apply the change \u2014 add new branches, update card layouts, rewire integrations.</li>
            <li>Preserve everything else in the topic untouched.</li>
        </ul>
        <h3>Examples</h3>
        <blockquote><p>\u201cAdd a follow-up question to the PTO topic that asks whether they want to notify their manager.\u201d</p></blockquote>
        <blockquote><p>\u201cChange the IT ticket topic to also ask for the employee\u2019s office location.\u201d</p></blockquote>
    </section>

    <section id="scan">
        <h2>\u{1f50d} Scan for issues</h2>
        <p>The <strong>Scan</strong> button checks your agent for common problems before you push to Copilot Studio:</p>
        <ul>
            <li>Broken references between topics and variables.</li>
            <li>Missing workflow bindings.</li>
            <li>Malformed configuration.</li>
            <li>Dependency conflicts.</li>
        </ul>
        <p>The kit lists any issues grouped by severity and offers to fix them for you. You confirm each fix before it\u2019s applied.</p>
    </section>

    <section id="flightcheck">
        <h2>\u2708\ufe0f Run a flightcheck</h2>
        <p>The <strong>Run a flightcheck</strong> button runs FlightCheck \u2014 41+ automated checks across eight categories before you go to production:</p>
        <ul>
            <li><strong>Prerequisites</strong> \u2014 licenses and admin roles.</li>
            <li><strong>Environment</strong> \u2014 Power Platform environment and Dataverse provisioning.</li>
            <li><strong>Authentication</strong> \u2014 Entra ID configuration and Conditional Access.</li>
            <li><strong>External systems</strong> \u2014 Workday, ServiceNow, SAP integrations.</li>
            <li><strong>Workday deep checks</strong> \u2014 17 SOAP workflow tests against the live API.</li>
            <li><strong>Agent files</strong> \u2014 instructions, prompts, required topics.</li>
            <li><strong>Configuration</strong> \u2014 per-agent validation across all extracted agents.</li>
            <li><strong>Publishing readiness</strong> \u2014 golden prompts, UAT sign-off, managed solution export.</li>
        </ul>
        <p>When it finishes you\u2019ll get an HTML report you can share with stakeholders, with color-coded results and clickable remediation links for anything that needs fixing.</p>
    </section>

    <section id="tests">
        <h2>\u{1f4ca} Generate tests</h2>
        <p>The <strong>Generate tests</strong> button creates evaluation test sets for your agent. It will:</p>
        <ul>
            <li>Analyze your topics and generate representative user utterances.</li>
            <li>Create expected-response pairs for automated regression testing.</li>
            <li>Cover edge cases and variations the agent should handle.</li>
        </ul>
        <p>The generated tests help you validate that future changes don\u2019t break existing conversations. This button is available after a flightcheck has passed.</p>
    </section>

    <section id="push">
        <h2>\u{1f680} Push to Copilot Studio</h2>
        <p>The <strong>Push to Copilot Studio</strong> button safely deploys your changes:</p>
        <ol>
            <li><strong>Checkpoint</strong> \u2014 back up the current state so you can roll back.</li>
            <li><strong>Dry-run diff</strong> \u2014 preview exactly what will change.</li>
            <li><strong>Push</strong> \u2014 apply the changes to your Copilot Studio environment.</li>
            <li><strong>Verify</strong> \u2014 confirm the deployment succeeded.</li>
        </ol>
        <p>You\u2019ll see a preview of every change before anything is committed, and you can cancel at any point.</p>
        <blockquote><p>Rollback is always one command away \u2014 just ask the chat to \u201croll back the last push\u201d if something goes wrong.</p></blockquote>
    </section>
<script>
    const vscode = acquireVsCodeApi();
    document.getElementById('close-tutorial').addEventListener('click', () => {
        vscode.postMessage({ type: 'closeTutorial' });
    });
</script>
</body>
</html>`;
}

async function openChatInEditor() {
    // Try the newer chat-in-editor command first, then fall back.
    const candidates = [
        'workbench.action.chat.openInEditor',
        'workbench.action.chat.openEditor',
        'workbench.action.chat.open',
    ];
    for (const c of candidates) {
        if (await tryRun(c)) return true;
    }
    return false;
}

async function openChatInEditorWithQuery(query) {
    // Open a Copilot Chat in the EDITOR area (full-screen) with the
    // given query pre-filled and submitted.
    //
    // We tried several documented chat.open shapes ({ query, location:
    // 'editor' } etc.) and none of them reliably injected the query
    // into the resulting editor chat — they opened the editor pane but
    // dropped the query on the floor. So we fall back to a robust three
    // step dance:
    //
    //   1. workbench.action.chat.openInEditor — opens an empty chat
    //      editor.
    //   2. workbench.action.chat.focusInput — puts caret in the input.
    //   3. type the query via the built-in `type` command, then submit.
    //
    // The `type` command is the same low-level keystroke handler the
    // editor itself uses for typing, so it works on any focused input
    // including chat. This is the same trick the VS Code "Run Selection
    // in Terminal" feature uses.
    await tryRun('workbench.action.chat.openInEditor');
    await new Promise((r) => setTimeout(r, 500));
    await tryRun('workbench.action.chat.focusInput');
    await new Promise((r) => setTimeout(r, 150));
    try {
        await vscode.commands.executeCommand('type', { text: query });
    } catch (_) {
        // `type` may be blocked if no editor is focused — last-resort
        // path through the public chat.open with a query.
        await tryRun('workbench.action.chat.open', { query, isPartialQuery: false });
    }
    await new Promise((r) => setTimeout(r, 150));
    await tryRun('workbench.action.chat.submit');
    return true;
}

async function applyChatOnlyLayout({ silent = false, showWalkthrough = false } = {}) {
    await applySettings(CHAT_ONLY_LAYOUT, vscode.ConfigurationTarget.Global);

    // Wait for VS Code to finish wiring up surfaces and restoring state.
    await new Promise((r) => setTimeout(r, 2000));

    // Close all editor tabs (welcome page, restored files, etc).
    try {
        const allTabs = [];
        for (const group of vscode.window.tabGroups.all || []) {
            for (const tab of group.tabs || []) {
                allTabs.push(tab);
            }
        }
        if (allTabs.length) {
            await vscode.window.tabGroups.close(allTabs, true);
        }
    } catch (e) {
        console.warn('[ess-maker] tabGroups.close failed:', e && e.message);
    }
    await tryRun('workbench.action.closeAllEditors');

    if (showWalkthrough) {
        // First-run: open the tutorial on the left and an empty chat on the right.
        openTutorialPanel(vscode.ViewColumn.One);
        await new Promise((r) => setTimeout(r, 500));
        await tryRun('workbench.action.splitEditorRight');
        await new Promise((r) => setTimeout(r, 300));
        const chatCmds = [
            'workbench.action.chat.openInEditor',
            'workbench.action.chat.openInNewEditor',
            'workbench.action.chat.newChat',
        ];
        for (const c of chatCmds) {
            if (await tryRun(c)) break;
        }
    } else {
        // Open a chat editor (no /setup — the user clicks the Connect button).
        const openCmds = [
            'workbench.action.chat.openInEditor',
            'workbench.action.chat.openInNewEditor',
            'workbench.action.chat.newChat',
        ];
        for (const c of openCmds) {
            if (await tryRun(c)) break;
        }
    }
    // Close the auxiliary bar to remove VS Code's built-in Chat panel
    // (which would duplicate the chat editor we just opened).

    if (!silent) {
        // Hide menu bar for this session (the setting picks it up on
        // next reload but the toggle takes effect immediately).
        await tryRun('workbench.action.toggleMenuBar');
    }

    // Open Quick Actions in the primary sidebar (replaces the explorer view).
    // Then close the auxiliary bar to remove any duplicate Chat panel.
    await tryRun('workbench.view.extension.essMakerActions');
    await tryRun('essMaker.actionsView.focus');
    await new Promise((r) => setTimeout(r, 300));
    await tryRun('workbench.action.closeAuxiliaryBar');

    // VS Code may re-open the explorer after folder restore. Re-focus Quick Actions
    // with staggered delays to ensure it stays as the active primary sidebar view.
    for (const delay of [500, 1500, 3000]) {
        setTimeout(() => {
            vscode.commands.executeCommand('workbench.view.extension.essMakerActions').then(() => {}, () => {});
        }, delay);
    }

    if (!silent) {
        const sel = await vscode.window.showInformationMessage(
            'ESS Maker chat-only layout applied. Reload the window for the menu bar and title bar to disappear.',
            'Reload Window',
            'Later'
        );
        if (sel === 'Reload Window') {
            await vscode.commands.executeCommand('workbench.action.reloadWindow');
        }
    }
}

async function restoreStandardLayout() {
    await clearSettings(Object.keys(CHAT_ONLY_LAYOUT), vscode.ConfigurationTarget.Global);
    await clearSettings(Object.keys(CHAT_ONLY_LAYOUT), vscode.ConfigurationTarget.Workspace);
    const sel = await vscode.window.showInformationMessage(
        'ESS Maker: standard layout restored. Reload the window to see all changes.',
        'Reload Window'
    );
    if (sel === 'Reload Window') {
        await vscode.commands.executeCommand('workbench.action.reloadWindow');
    }
}

async function openChatWithQuery(query) {
    // Strategy: focus the chat view, then call `workbench.action.chat.open`
    // with the query. The `{ query }` payload populates the input; some
    // VS Code builds also auto-submit when isPartialQuery is false.
    const attempts = [
        () => vscode.commands.executeCommand('workbench.action.chat.open', { query, isPartialQuery: false }),
        () => vscode.commands.executeCommand('workbench.action.chat.open', query),
        () => vscode.commands.executeCommand('workbench.action.chat.openInEditor', { query }),
        () => vscode.commands.executeCommand('workbench.panel.chat.view.copilot.focus')
            .then(() => vscode.commands.executeCommand('workbench.action.chat.open', { query })),
    ];
    let lastErr;
    for (const a of attempts) {
        try {
            await a();
            // Try to submit if the query was only inserted.
            await tryRun('workbench.action.chat.submit');
            return;
        } catch (err) {
            lastErr = err;
        }
    }
    // Everything failed — copy to clipboard and pop a modal so the user can't miss it.
    await vscode.env.clipboard.writeText(query);
    vscode.window.showWarningMessage(
        `ESS Maker couldn't open Copilot Chat directly (${lastErr?.message || 'unknown error'}). The command "${query}" was copied to your clipboard — open Copilot Chat and paste it.`,
        { modal: true },
        'OK'
    );
}

// Webview view provider — renders the button rail.
class ActionsViewProvider {
    constructor(extensionUri, context) {
        this._extensionUri = extensionUri;
        this._context = context;
        this._view = null;
    }

    async resolveWebviewView(webviewView) {
        this._view = webviewView;
        webviewView.webview.options = { enableScripts: true, localResourceRoots: [this._extensionUri] };
        webviewView.webview.html = this._html(webviewView.webview);

        webviewView.webview.onDidReceiveMessage(async (msg) => {
            if (msg?.type === 'action') {
                const action = ACTIONS.find(a => a.id === msg.id);
                if (!action) return;
                const completed = getCompleted(this._context);
                const { enabled } = actionState(action, completed);
                if (!enabled) return;
                await openChatWithQuery(action.slash);
                // Don't optimistically mark as completed — the file watcher
                // will detect when the actual artifact appears on disk and
                // enable dependent buttons at that point.
            } else if (msg?.type === 'restoreLayout') {
                await this._context.globalState.update(LITE_MODE_KEY, false);
                await clearSettings(Object.keys(CHAT_ONLY_LAYOUT), vscode.ConfigurationTarget.Global);
                await clearSettings(Object.keys(CHAT_ONLY_LAYOUT), vscode.ConfigurationTarget.Workspace);
                // Expand the workspace folder in the explorer
                await tryRun('workbench.view.explorer');
                await new Promise((r) => setTimeout(r, 150));
                await tryRun('workbench.files.action.expandRecursively');
                await this.refresh();
                const sel = await vscode.window.showInformationMessage(
                    'Standard layout restored. Reload the window for full effect.',
                    'Reload Window'
                );
                if (sel === 'Reload Window') {
                    await vscode.commands.executeCommand('workbench.action.reloadWindow');
                }
            } else if (msg?.type === 'reapplyLayout') {
                await this._context.globalState.update(LITE_MODE_KEY, true);
                await applySettings(CHAT_ONLY_LAYOUT, vscode.ConfigurationTarget.Global);
                await this.refresh();
                const sel = await vscode.window.showInformationMessage(
                    'Lite mode applied. Reload the window for full effect.',
                    'Reload Window'
                );
                if (sel === 'Reload Window') {
                    await vscode.commands.executeCommand('workbench.action.reloadWindow');
                }
            } else if (msg?.type === 'resetProgress') {
                const sel = await vscode.window.showWarningMessage(
                    'Reset Quick Actions progress? All buttons will be re-locked except Connect.',
                    'Reset', 'Cancel'
                );
                if (sel === 'Reset') {
                    await resetCompleted(this._context);
                    await this.refresh();
                }
            } else if (msg?.type === 'openWalkthrough') {
                toggleTutorialPanel();
            } else if (msg?.type === 'ready') {
                await this.refresh();
            }
        });

        await this.refresh();
    }

    async refresh() {
        if (!this._view) return;
        const completed = getCompleted(this._context);
        const states = {};
        for (const a of ACTIONS) {
            states[a.id] = actionState(a, completed);
        }
        const liteMode = isLiteMode();
        try {
            await this._view.webview.postMessage({ type: 'state', states, liteMode });
        } catch {}
    }

    _html(webview) {
        const nonce = Array.from({length: 32}, () =>
            'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'.charAt(Math.floor(Math.random() * 62))
        ).join('');

        const buttons = ACTIONS.map(a => `
            <button class="action" data-id="${a.id}" disabled>
                <div class="icon">${a.icon}</div>
                <div class="text">
                    <div class="label">${a.label} <span class="badge" data-badge="${a.id}"></span></div>
                    <div class="sub" data-sub="${a.id}">${a.sub}</div>
                </div>
            </button>
        `).join('');

        return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';" />
<style>
    body {
        font-family: var(--vscode-font-family);
        font-size: var(--vscode-font-size);
        color: var(--vscode-foreground);
        padding: 12px 10px 16px;
        margin: 0;
    }
    h2 {
        margin: 4px 4px 12px;
        font-size: 13px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--vscode-descriptionForeground);
    }
    .action {
        display: flex;
        align-items: center;
        gap: 12px;
        width: 100%;
        margin: 0 0 8px;
        padding: 12px 12px;
        background: var(--vscode-button-secondaryBackground, var(--vscode-editor-background));
        color: var(--vscode-button-secondaryForeground, var(--vscode-foreground));
        border: 1px solid var(--vscode-panel-border, transparent);
        border-radius: 6px;
        cursor: pointer;
        text-align: left;
        transition: background-color 100ms ease, opacity 100ms ease;
        font-family: inherit;
    }
    .action:hover:not(:disabled) {
        background: var(--vscode-button-secondaryHoverBackground, var(--vscode-list-hoverBackground));
    }
    .action:focus { outline: 1px solid var(--vscode-focusBorder); outline-offset: 1px; }
    .action:disabled {
        opacity: 0.45;
        cursor: not-allowed;
        filter: grayscale(0.5);
    }
    .action.done {
        border-color: var(--vscode-charts-green, #4caf50);
    }
    .icon { font-size: 22px; line-height: 1; flex: 0 0 26px; text-align: center; }
    .text { flex: 1; min-width: 0; }
    .label { font-size: 13px; font-weight: 600; display: flex; align-items: center; gap: 6px; }
    .sub { font-size: 11px; opacity: 0.75; margin-top: 2px; }
    .badge {
        font-size: 10px;
        font-weight: 600;
        padding: 1px 6px;
        border-radius: 8px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .badge.done {
        background: var(--vscode-charts-green, #4caf50);
        color: var(--vscode-editor-background);
    }
    .badge.locked {
        background: var(--vscode-badge-background, rgba(128,128,128,0.25));
        color: var(--vscode-badge-foreground, var(--vscode-foreground));
    }
    hr {
        border: 0;
        border-top: 1px solid var(--vscode-panel-border, rgba(128,128,128,0.2));
        margin: 16px 0 12px;
    }
    .secondary {
        background: transparent;
        border: 1px dashed var(--vscode-panel-border, rgba(128,128,128,0.3));
    }
</style>
</head>
<body>
    <h2>Customize your ESS agent</h2>
    ${buttons}
    <hr />
    <button class="action secondary" data-action="reapplyLayout" id="btn-lite">
        <div class="icon">🪟</div>
        <div class="text">
            <div class="label">Switch to lite mode</div>
            <div class="sub">Chat-only layout with big buttons</div>
        </div>
    </button>
    <button class="action secondary" data-action="resetProgress">
        <div class="icon">↩️</div>
        <div class="text">
            <div class="label">Reset progress</div>
            <div class="sub">Re-lock the steps</div>
        </div>
    </button>
    <button class="action secondary" data-action="openWalkthrough" id="btn-tutorial">
        <div class="icon">📖</div>
        <div class="text">
            <div class="label" id="btn-tutorial-label">View tutorial</div>
            <div class="sub">How each button works</div>
        </div>
    </button>
    <button class="action secondary" data-action="restoreLayout" id="btn-standard">
        <div class="icon">⚙️</div>
        <div class="text">
            <div class="label">Switch to standard VS Code</div>
            <div class="sub">Show menus, files, status bar</div>
        </div>
    </button>
<script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const subs = {};
    document.querySelectorAll('button[data-id]').forEach(btn => {
        subs[btn.dataset.id] = btn.querySelector('.sub').textContent;
        btn.addEventListener('click', () => {
            if (btn.disabled) return;
            vscode.postMessage({ type: 'action', id: btn.dataset.id });
        });
    });
    document.querySelectorAll('button[data-action]').forEach(btn => {
        btn.addEventListener('click', () => vscode.postMessage({ type: btn.dataset.action }));
    });
    window.addEventListener('message', (e) => {
        if (e.data?.type === 'tutorialState') {
            const label = document.getElementById('btn-tutorial-label');
            if (label) label.textContent = e.data.open ? 'Hide tutorial' : 'View tutorial';
            return;
        }
        if (e.data?.type !== 'state') return;
        for (const [id, s] of Object.entries(e.data.states)) {
            const btn = document.querySelector('button[data-id="' + id + '"]');
            if (!btn) continue;
            btn.disabled = !s.enabled;
            btn.classList.toggle('done', !!s.done);
            const badge = btn.querySelector('[data-badge="' + id + '"]');
            const sub = btn.querySelector('[data-sub="' + id + '"]');
            if (s.done) {
                badge.className = 'badge done';
                badge.textContent = '✓';
            } else if (!s.enabled) {
                badge.className = 'badge locked';
                badge.textContent = 'locked';
            } else {
                badge.className = 'badge';
                badge.textContent = '';
            }
            if (!s.enabled && s.blockedBy) {
                btn.title = 'Complete first: ' + s.blockedBy.join(', ');
                sub.textContent = 'Complete first: ' + s.blockedBy.join(', ');
            } else {
                btn.title = '';
                sub.textContent = subs[id];
            }
        }
        // Show/hide mode-toggle buttons based on current layout.
        const btnLite = document.getElementById('btn-lite');
        const btnStandard = document.getElementById('btn-standard');
        if (e.data.liteMode) {
            btnLite.style.display = 'none';
            btnStandard.style.display = '';
        } else {
            btnLite.style.display = '';
            btnStandard.style.display = 'none';
        }
    });
    vscode.postMessage({ type: 'ready' });
</script>
</body>
</html>`;
    }
}

function activate(context) {
    _log(`activate: ENTRY. workspaceFolders=${JSON.stringify(vscode.workspace.workspaceFolders?.map(f => f.uri.fsPath))}`);
    // Register slash-command bridges (also available from the command palette).
    for (const a of ACTIONS) {
        context.subscriptions.push(
            vscode.commands.registerCommand(`essMaker.run_${a.id}`, () => openChatWithQuery(a.slash))
        );
    }
    // Legacy command IDs from 0.1.0 (still referenced by the walkthrough).
    const legacyMap = {
        'essMaker.runSetup': '/setup',
        'essMaker.runCreate': '/create',
        'essMaker.runScan': '/scan',
        'essMaker.runFlightcheck': '/flightcheck',
        'essMaker.runPush': '/push',
    };
    for (const [id, slash] of Object.entries(legacyMap)) {
        context.subscriptions.push(
            vscode.commands.registerCommand(id, () => openChatWithQuery(slash))
        );
    }

    context.subscriptions.push(
        vscode.commands.registerCommand('essMaker.applyMakerLayout', () => applyChatOnlyLayout()),
        vscode.commands.registerCommand('essMaker.startChatOnly', () => applyChatOnlyLayout()),
        vscode.commands.registerCommand('essMaker.restoreStandardLayout', () => restoreStandardLayout()),
        vscode.commands.registerCommand('essMaker.focusActions', () =>
            tryRun('workbench.view.extension.essMakerActions').then(() => tryRun('essMaker.actionsView.focus'))
        ),
        vscode.commands.registerCommand('essMaker.openWalkthrough', () =>
            toggleTutorialPanel()
        ),
        vscode.window.registerWebviewViewProvider(
            'essMaker.actionsView',
            _actionsViewProvider = new ActionsViewProvider(context.extensionUri, context),
            { webviewOptions: { retainContextWhenHidden: true } }
        )
    );

    // Start watching workspace files for prerequisite artifacts.
    // This enables/disables buttons based on actual file existence
    // (e.g. .local/config.json for setup, workspace/flightcheck/results.json).
    startPrereqWatcher(context);

    // First-run vs subsequent runs:
    // - First run: determine mode (lite vs standard) from VS Code setting
    //   written by the installer.
    //   Lite mode: applies chat-only layout; user clicks Connect to run /setup.
    //   Standard mode: injects /setup into Copilot Chat automatically.
    // - Subsequent lite activations: silently re-apply layout.
    const alreadyApplied = context.globalState.get(APPLIED_KEY, false);
    const userWantsLite = context.globalState.get(LITE_MODE_KEY, true); // default to lite
    const installerMode = vscode.workspace.getConfiguration().get('essMaker.mode', '');

    _log(`activate: alreadyApplied=${alreadyApplied}, userWantsLite=${userWantsLite}, installerMode="${installerMode}", workspaceFolders=${vscode.workspace.workspaceFolders?.length || 0}`);

    if (vscode.workspace.workspaceFolders?.length) {
        if (!alreadyApplied) {
            // First install. Check installer-provided mode setting.
            const isStandardMode = installerMode === 'standard';
            _log(`activate: first install, isStandardMode=${isStandardMode}`);
            context.globalState.update(LITE_MODE_KEY, !isStandardMode);

            if (isStandardMode) {
                // Standard mode: no layout changes.
                // Wait for welcome wizard to finish, then inject /setup.
                context.globalState.update(APPLIED_KEY, true);
                waitForWelcomeWizard()
                    .then(() => { _log('activate: wizard done (standard), waiting 3s...'); return new Promise(r => setTimeout(r, 3000)); })
                    .then(() => { _log('activate: calling injectSetup (standard)'); return injectSetup(); })
                    .then(() => _log('activate: injectSetup completed (standard)'))
                    .catch((err) => {
                        _log(`activate: ERROR in standard wizard chain: ${err && err.message}`);
                        console.warn('[ess-maker] Welcome wizard wait timed out, skipping auto /setup');
                    });
            } else {
                // Lite mode: apply layout, then wait for welcome wizard
                // to finish before injecting /setup.
                applyChatOnlyLayout({ silent: false })
                    .then(() => context.globalState.update(APPLIED_KEY, true))
                    .catch(() => {});
                waitForWelcomeWizard()
                    .then(() => { _log('activate: wizard done (lite), waiting 3s...'); return new Promise(r => setTimeout(r, 3000)); })
                    .then(() => { _log('activate: calling injectSetup (lite)'); return injectSetup(); })
                    .then(() => _log('activate: injectSetup completed (lite)'))
                    .catch((err) => {
                        _log(`activate: ERROR in lite wizard chain: ${err && err.message}`);
                        console.warn('[ess-maker] Welcome wizard wait timed out, skipping auto /setup');
                    });
            }
        } else if (userWantsLite) {
            // Subsequent lite mode launch: silently re-apply layout.
            setTimeout(() => { applyChatOnlyLayout({ silent: true }).catch(() => {}); }, 1500);
        }
        // If userWantsLite is false (standard mode), skip re-applying.
    }
}

function deactivate() {}

module.exports = { activate, deactivate };
