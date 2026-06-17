// ESS Maker POC extension — chat-only layout.
//
// Goal: the customer sees Copilot Chat in the center, a column of big
// buttons on the right, and nothing else. No file explorer, no editor
// tabs, no menu bar, no status bar.

const vscode = require('vscode');

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
    { id: 'setup',       icon: '🔌', label: 'Connect',           sub: 'Sign in to your environment',  slash: '/setup',       requires: [] },
    { id: 'create',      icon: '✨', label: 'Create a topic',    sub: 'Describe a new conversation',  slash: '/create',      requires: ['setup'] },
    { id: 'update',      icon: '✏️', label: 'Update a topic',    sub: 'Tweak an existing topic',      slash: '/update',      requires: ['setup'] },
    { id: 'scan',        icon: '🔍', label: 'Scan for issues',   sub: 'Find broken bindings',         slash: '/scan',        requires: ['setup'] },
    { id: 'flightcheck', icon: '✈️', label: 'Validate readiness',sub: '41+ readiness checks',         slash: '/flightcheck', requires: ['setup'] },
    { id: 'evaluate',    icon: '📊', label: 'Generate tests',    sub: 'Build evaluation test sets',   slash: '/evaluate',    requires: ['setup'] },
    { id: 'push',        icon: '🚀', label: 'Push to Copilot',   sub: 'Safely deploy your changes',   slash: '/push',        requires: ['setup'] },
];

const STATE_KEY = 'essMaker.completedActions.v3';

function getCompleted(context) {
    return new Set(context.globalState.get(STATE_KEY, []));
}

async function markCompleted(context, id) {
    const set = getCompleted(context);
    set.add(id);
    await context.globalState.update(STATE_KEY, Array.from(set));
}

async function resetCompleted(context) {
    await context.globalState.update(STATE_KEY, []);
}

// Look in the workspace for signals that prerequisites are met without the
// user having to click through every button in order (e.g. a returning user
// already has topics from a previous session).
async function inferFromWorkspace(context) {
    const completed = getCompleted(context);
    // Auto-inference removed: the workspace (ess-maker-skills) always
    // contains YAML files under solutions/, which caused setup + create
    // to appear completed on every fresh install. Buttons now start
    // unchecked and are only marked done when the user actually clicks them.
    return completed;
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
        // First-run: open the Getting Started walkthrough on the left and
        // a /setup chat on the right, side-by-side.
        await vscode.commands.executeCommand(
            'workbench.action.openWalkthrough',
            { category: `${EXT_ID}#essMaker.welcome`, step: `${EXT_ID}#essMaker.welcome#overview` },
            false
        );
        await new Promise((r) => setTimeout(r, 500));
        // Split right — the new (right) editor group gets focus.
        await tryRun('workbench.action.splitEditorRight');
        await new Promise((r) => setTimeout(r, 300));
        // Open chat in the now-focused right group.
        const chatCmds = [
            'workbench.action.chat.openInEditor',
            'workbench.action.chat.openInNewEditor',
            'workbench.action.chat.newChat',
        ];
        for (const c of chatCmds) {
            if (await tryRun(c)) break;
        }
        await new Promise((r) => setTimeout(r, 700));
        // Paste /setup into the chat and submit.
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
            console.warn('[ess-maker] paste /setup failed:', e && e.message);
        }
    } else {
        // Subsequent runs: open a chat editor with /setup pre-filled.
        //
        // The installer launches `code .` (not `code chat /setup`) when
        // this extension is installed, so we open the chat editor ourselves,
        // inject /setup via clipboard paste, submit, then hide the aux bar
        // for a clean single-chat full-screen layout.
        const openCmds = [
            'workbench.action.chat.openInEditor',
            'workbench.action.chat.openInNewEditor',
            'workbench.action.chat.newChat',
        ];
        for (const c of openCmds) {
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
            console.warn('[ess-maker] paste /setup failed:', e && e.message);
        }
    }
    // Hide the aux bar if it's open (it will be empty since the
    // installer no longer requests `code chat /setup`).
    await tryRun('workbench.action.closeAuxiliaryBar');

    if (!silent) {
        // Hide menu bar for this session (the setting picks it up on
        // next reload but the toggle takes effect immediately).
        await tryRun('workbench.action.toggleMenuBar');
    }

    // Collapse the explorer tree LAST — VS Code's async tree restore and
    // editor operations above can re-expand it if we collapse too early.
    await tryRun('workbench.view.explorer');
    await new Promise((r) => setTimeout(r, 300));
    await tryRun('workbench.files.action.collapseExplorerFolders');
    await tryRun('list.collapseAll');

    // Open + focus the Quick Actions view container wherever it lives.
    // Per package.json this is the auxiliary bar; if a previous session
    // moved it to the primary sidebar, it'll appear there instead.
    await tryRun('workbench.view.extension.essMakerActions');
    await tryRun('essMaker.actionsView.focus');

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
                const completed = await inferFromWorkspace(this._context);
                const { enabled } = actionState(action, completed);
                if (!enabled) return;
                await openChatWithQuery(action.slash);
                // Optimistically mark as completed so downstream actions unlock.
                await markCompleted(this._context, action.id);
                await this.refresh();
            } else if (msg?.type === 'restoreLayout') {
                await this._context.globalState.update(LITE_MODE_KEY, false);
                await clearSettings(Object.keys(CHAT_ONLY_LAYOUT), vscode.ConfigurationTarget.Global);
                await clearSettings(Object.keys(CHAT_ONLY_LAYOUT), vscode.ConfigurationTarget.Workspace);
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
            } else if (msg?.type === 'ready') {
                await this.refresh();
            }
        });

        await this.refresh();
    }

    async refresh() {
        if (!this._view) return;
        const completed = await inferFromWorkspace(this._context);
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
            vscode.commands.executeCommand(
                'workbench.action.openWalkthrough',
                { category: `${EXT_ID}#essMaker.welcome` },
                false
            )
        ),
        vscode.window.registerWebviewViewProvider(
            'essMaker.actionsView',
            new ActionsViewProvider(context.extensionUri, context),
            { webviewOptions: { retainContextWhenHidden: true } }
        )
    );

    // First-run vs subsequent runs:
    // - First run after install: apply layout + prompt to reload (menu bar needs reload).
    // - Subsequent activations: silently re-close the sidebar/aux bar/menu so they stay closed
    //   even after VS Code restores its previous layout from cache.
    const alreadyApplied = context.globalState.get(APPLIED_KEY, false);
    const userWantsLite = context.globalState.get(LITE_MODE_KEY, true); // default to lite
    if (vscode.workspace.workspaceFolders?.length) {
        if (!alreadyApplied) {
            // First install: show the Getting Started walkthrough so new
            // users get a guided tour. They click "Connect now" to start
            // /setup when ready.
            context.globalState.update(LITE_MODE_KEY, true);
            applyChatOnlyLayout({ silent: false, showWalkthrough: true })
                .then(() => context.globalState.update(APPLIED_KEY, true));
        } else if (userWantsLite) {
            // Defer slightly so VS Code finishes its own layout restore first.
            setTimeout(() => { applyChatOnlyLayout({ silent: true }).catch(() => {}); }, 400);
        }
        // If userWantsLite is false, skip re-applying — user chose standard mode.
    }
}

function deactivate() {}

module.exports = { activate, deactivate };
