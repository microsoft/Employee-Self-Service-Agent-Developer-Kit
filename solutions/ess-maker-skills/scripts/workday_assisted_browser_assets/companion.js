"use strict";

const guidance = document.getElementById("guidance");
const connection = document.getElementById("connection");
const evidence = document.getElementById("evidence");
const collection = document.getElementById("collection");
const entry = document.getElementById("entry");
const confirmation = document.getElementById("confirmation");
const targetRail = document.getElementById("target-rail");
const targetPointers = document.getElementById("target-pointers");
const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
const vscodeApi =
  typeof acquireVsCodeApi === "function" ? acquireVsCodeApi() : null;
const pendingBridgeRequests = new Map();
let bridgeRequestSequence = 0;
let renderedRevision = 0;
let acknowledgedRevision = 0;
let renderedVisualHelpKey = null;
let evidenceImageUrl = null;
let renderedEntryKey = null;
let renderedConfirmationKey = null;
let renderedTargetPointerKey = null;

window.addEventListener("message", (event) => {
  const message = event.data;
  if (
    !message ||
    message.type !== "apiResponse" ||
    typeof message.id !== "string"
  ) {
    return;
  }
  const pending = pendingBridgeRequests.get(message.id);
  if (!pending) {
    return;
  }
  pendingBridgeRequests.delete(message.id);
  clearTimeout(pending.timeout);
  if (message.ok) {
    pending.resolve(message.body);
  } else {
    pending.reject(new Error(message.error || "Guidance request failed."));
  }
});

/** Route webview requests through the extension host so the session token stays outside the DOM. */
function bridgeRequest(path, options = {}, responseType = "json") {
  const id = `request-${Date.now()}-${++bridgeRequestSequence}`;
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      pendingBridgeRequests.delete(id);
      reject(new Error("Guidance request timed out."));
    }, 30000);
    pendingBridgeRequests.set(id, { resolve, reject, timeout });
    vscodeApi.postMessage({
      type: "apiRequest",
      id,
      path,
      method: options.method || "GET",
      body: options.body || "",
      responseType,
    });
  });
}

/** Create text-only DOM nodes so companion data never becomes executable markup. */
function textElement(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) {
    element.className = className;
  }
  return element;
}

/** Render each published revision once while preserving interaction state returned by the server. */
function render(payload) {
  const view = payload.view;
  if (!view || payload.revision === renderedRevision) {
    return;
  }
  renderedRevision = payload.revision;
  const nodes = [
    textElement("p", view.phase, "phase"),
    textElement("h1", view.title),
    textElement("p", view.summary, "summary"),
  ];

  if (view.fields.length) {
    const list = document.createElement("dl");
    list.className = "fields";
    for (const field of view.fields) {
      list.append(
        textElement("dt", field.label),
        textElement("dd", field.value),
      );
    }
    nodes.push(list);
  }

  if (view.steps.length) {
    const heading = textElement("h2", "What to do");
    const list = document.createElement("ol");
    for (const step of view.steps) {
      const item = textElement("li", step);
      list.append(item);
    }
    nodes.push(heading, list);
  }

  if (view.waitingFor) {
    nodes.push(textElement("p", view.waitingFor, "waiting"));
  }
  const actions = view.actions || (view.action ? [view.action] : []);
  if (actions.length) {
    const actionGroup = document.createElement("div");
    actionGroup.className = "action-group";
    for (const action of actions) {
      const button = textElement("button", action.label, "primary-action");
      button.type = "button";
      const active =
        payload.collection?.operation === action.operation &&
        payload.collection?.mode === action.mode &&
        ["authorized", "navigated"].includes(payload.collection?.status);
      if (active) {
        button.disabled = true;
      } else {
        // Convert one explicit human click into revision-bound row authorization.
        button.addEventListener("click", async () => {
          for (const candidate of actionGroup.querySelectorAll("button")) {
            candidate.disabled = true;
          }
          button.textContent =
            action.mode === "navigate-only"
              ? "Navigating..."
              : "Navigating and authorizing capture...";
          renderCollection({
            operation: action.operation,
            mode: action.mode,
            status: "collecting",
          });
          try {
            const response = await request("/api/action", {
              method: "POST",
              body: JSON.stringify({
                operation: action.operation,
                mode: action.mode,
                revision: renderedRevision,
              }),
            });
            renderCollection(response.collection);
            button.textContent = action.label;
          } catch (error) {
            renderCollection({
              status: "failed",
              error: error.message,
            });
            for (const candidate of actionGroup.querySelectorAll("button")) {
              candidate.disabled = false;
            }
            button.textContent = action.label;
          }
        });
      }
      actionGroup.append(button);
    }
    nodes.push(actionGroup);
    const disclaimers = [
      // Present each action disclaimer once even when multiple modes share it.
      ...new Set(actions.map((action) => action.disclaimer).filter(Boolean)),
    ];
    for (const disclaimer of disclaimers) {
      nodes.push(textElement("p", disclaimer, "navigation-disclaimer"));
    }
  }
  guidance.dataset.status = view.status;
  guidance.replaceChildren(...nodes);
}

/** Show transient collection progress or a collected worksheet value without retaining stale results. */
function renderCollection(result) {
  if (!result) {
    collection.hidden = true;
    collection.replaceChildren();
    return;
  }
  const nodes = [];
  if (result.status === "collecting") {
    nodes.push(
      textElement("h2", "Collection in progress"),
      textElement(
        "p",
        "Browser assistance is navigating the authorized application pane and reading the requested row.",
      ),
    );
    collection.dataset.status = "checking";
  } else if (["authorized", "navigated"].includes(result.status)) {
    collection.hidden = true;
    collection.replaceChildren();
    return;
  } else if (result.status === "collected") {
    const values = document.createElement("dl");
    values.className = "fields";
    values.append(
      textElement("dt", result.worksheetRow),
      textElement("dd", result.value),
    );
    nodes.push(textElement("h2", "Collected value"), values);
    collection.dataset.status = "success";
  } else {
    nodes.push(
      textElement("h2", "Collection needs attention"),
      textElement(
        "p",
        result.error || "The requested value was not collected.",
      ),
    );
    collection.dataset.status = "error";
  }
  collection.hidden = false;
  collection.replaceChildren(...nodes);
}

/** Load one authorized screenshot through the active browser host. */
async function loadEvidenceImage() {
  if (vscodeApi) {
    const response = await bridgeRequest("/api/evidence-image", {}, "binary");
    const bytes = Uint8Array.from(atob(response.base64), (character) =>
      character.charCodeAt(0),
    );
    return new Blob([bytes], { type: response.contentType });
  }
  const response = await fetch("/api/evidence-image", {
    cache: "no-store",
    headers: {
      Authorization: "Bearer " + token,
    },
  });
  if (!response.ok) {
    throw new Error("Context screenshot could not be loaded.");
  }
  return response.blob();
}

/** Request and render contextual visual help independently of candidate confirmation. */
async function renderVisualHelp(
  view,
  visualHelp,
  metadata,
  revision,
  pointerStatus,
) {
  if (!view?.visualHelp || !visualHelp) {
    evidence.hidden = true;
    evidence.replaceChildren();
    renderedVisualHelpKey = null;
    if (evidenceImageUrl) {
      URL.revokeObjectURL(evidenceImageUrl);
      evidenceImageUrl = null;
    }
    return;
  }
  const key = [
    revision,
    visualHelp.status,
    visualHelp.requestedAt || "",
    visualHelp.failedAt || "",
    visualHelp.completedAt || "",
    metadata?.id || "",
    pointerStatus?.status || "",
    pointerStatus?.updatedAt || "",
  ].join(":");
  if (key === renderedVisualHelpKey) {
    return;
  }
  renderedVisualHelpKey = key;
  if (evidenceImageUrl) {
    URL.revokeObjectURL(evidenceImageUrl);
    evidenceImageUrl = null;
  }
  if (visualHelp.status === "succeeded" && metadata) {
    try {
      const imageBlob = await loadEvidenceImage();
      evidenceImageUrl = URL.createObjectURL(imageBlob);
      const image = document.createElement("img");
      image.src = evidenceImageUrl;
      image.alt = "Portal context for " + metadata.label;
      evidence.replaceChildren(
        textElement("h2", "What to select"),
        image,
        textElement(
          "p",
          "In the application pane, locate: " + metadata.label,
          "evidence-caption",
        ),
      );
      evidence.hidden = false;
      return;
    } catch (error) {
      evidence.replaceChildren(
        textElement("h2", "Screenshot unavailable"),
        textElement("p", error.message, "decision-error"),
      );
      evidence.hidden = false;
      return;
    }
  }
  const button = textElement("button", "", "secondary-action");
  button.type = "button";
  if (visualHelp.status === "requested") {
    button.textContent = "Preparing screenshot...";
    button.disabled = true;
  } else if (pointerStatus?.status !== "ready") {
    button.textContent =
      pointerStatus?.status === "failed"
        ? "Visual guidance unavailable"
        : "Locating target...";
    button.disabled = true;
  } else {
    button.textContent =
      visualHelp.status === "failed"
        ? "Screenshot unsuccessful"
        : "Show me what to click";
    // The click requests a fresh screenshot; the session performs it afterward.
    button.addEventListener("click", async () => {
      button.disabled = true;
      button.textContent = "Preparing screenshot...";
      try {
        await request("/api/visual-help", {
          method: "POST",
          body: JSON.stringify({
            operation: view.visualHelp.operation,
            revision,
          }),
        });
      } catch (error) {
        button.disabled = false;
        button.textContent = "Show me what to click";
        evidence.append(textElement("p", error.message, "decision-error"));
      }
    });
  }
  const nodes = [textElement("h2", "Need visual help?"), button];
  if (visualHelp.status === "failed") {
    nodes.push(
      textElement(
        "p",
        visualHelp.error || "The screenshot could not be prepared.",
        "decision-error",
      ),
    );
  } else if (pointerStatus?.status === "failed") {
    nodes.push(
      textElement(
        "p",
        pointerStatus.error || "The target could not be positioned.",
        "decision-error",
      ),
    );
  }
  evidence.replaceChildren(...nodes);
  evidence.hidden = false;
}

/** Render one revision-bound confirmation and prevent duplicate decisions. */
function renderConfirmation(view, result, revision) {
  if (!view || !view.confirmation || !result) {
    confirmation.hidden = true;
    confirmation.replaceChildren();
    renderedConfirmationKey = null;
    return;
  }
  const key = [
    revision,
    result.status,
    result.requestedAt || "",
    result.decidedAt || "",
  ].join(":");
  if (key === renderedConfirmationKey) {
    return;
  }
  const nodes = [];
  if (result.status === "waiting") {
    nodes.push(textElement("h2", view.confirmation.prompt));
    const actions = document.createElement("div");
    actions.className = "confirmation-actions";
    const confirmButton = textElement(
      "button",
      view.confirmation.confirmLabel,
      "primary-action",
    );
    const rejectButton = textElement(
      "button",
      view.confirmation.rejectLabel,
      "secondary-action",
    );
    for (const button of [confirmButton, rejectButton]) {
      button.type = "button";
    }
    // Submit exactly one human decision for the confirmation currently on screen.
    const decide = async (decision) => {
      confirmButton.disabled = true;
      rejectButton.disabled = true;
      try {
        const response = await request("/api/confirmation", {
          method: "POST",
          body: JSON.stringify({
            operation: view.confirmation.operation,
            revision,
            decision,
          }),
        });
        renderConfirmation(view, response.confirmation, revision);
      } catch (error) {
        nodes.push(textElement("p", error.message, "decision-error"));
        confirmButton.disabled = false;
        rejectButton.disabled = false;
      }
    };
    // Bind the primary choice to the confirmed terminal state.
    confirmButton.addEventListener("click", () => void decide("confirmed"));
    // Bind the secondary choice to the rejected terminal state.
    rejectButton.addEventListener("click", () => void decide("rejected"));
    actions.append(confirmButton, rejectButton);
    nodes.push(actions);
    confirmation.dataset.status = "checking";
  } else if (result.status === "confirmed") {
    nodes.push(
      textElement(
        "p",
        "Confirmed. The session can now record this worksheet row.",
      ),
    );
    confirmation.dataset.status = "success";
  } else {
    nodes.push(
      textElement(
        "p",
        "Review again requested. The existing row authorization remains active.",
      ),
    );
    confirmation.dataset.status = "checking";
  }
  confirmation.hidden = false;
  confirmation.replaceChildren(...nodes);
  renderedConfirmationKey = key;
}

/** Render the bounded manual-entry fallback for the current worksheet row. */
function renderEntry(view, result, revision) {
  if (!view || !view.entry || !result) {
    entry.hidden = true;
    entry.replaceChildren();
    renderedEntryKey = null;
    return;
  }
  const key = [
    revision,
    result.status,
    result.requestedAt || "",
    result.submittedAt || "",
  ].join(":");
  if (key === renderedEntryKey) {
    return;
  }
  if (result.status === "submitted") {
    const submittedMultiple =
      result.values && typeof result.values === "object";
    entry.replaceChildren(
      textElement(
        "h2",
        submittedMultiple
          ? "Worksheet values submitted"
          : "Worksheet value submitted",
      ),
      textElement(
        "p",
        submittedMultiple
          ? "The session will record these worksheet values."
          : "The session will record this worksheet value.",
      ),
    );
    entry.dataset.status = "success";
    entry.hidden = false;
    renderedEntryKey = key;
    return;
  }
  const submitValue = async (payload, buttons) => {
    for (const button of buttons) {
      button.disabled = true;
    }
    try {
      const response = await request("/api/entry", {
        method: "POST",
        body: JSON.stringify({
          operation: view.entry.operation,
          revision,
          ...payload,
        }),
      });
      renderEntry(view, response.entry, revision);
    } catch (error) {
      for (const button of buttons) {
        button.disabled = false;
      }
      entry.append(textElement("p", error.message, "decision-error"));
    }
  };
  if (Array.isArray(view.entry.options)) {
    const actions = document.createElement("div");
    actions.className = "confirmation-actions";
    const buttons = view.entry.options.map((option, index) => {
      const button = textElement(
        "button",
        option,
        index === 0 ? "primary-action" : "secondary-action",
      );
      button.type = "button";
      button.addEventListener("click", () => {
        void submitValue({ value: option }, buttons);
      });
      actions.append(button);
      return button;
    });
    entry.replaceChildren(
      textElement("h2", "Choose the worksheet response"),
      textElement("p", view.entry.label),
      actions,
    );
    entry.dataset.status = "checking";
    entry.hidden = false;
    renderedEntryKey = key;
    return;
  }
  if (Array.isArray(view.entry.inputs)) {
    const inputs = view.entry.inputs.map((inputDefinition, index) => {
      const label = textElement("label", inputDefinition.label);
      const input = document.createElement("input");
      input.id = `manual-entry-value-${index}`;
      input.type = "text";
      input.placeholder = inputDefinition.placeholder;
      input.autocomplete = "off";
      input.spellcheck = false;
      label.htmlFor = input.id;
      return { inputDefinition, label, input };
    });
    const button = textElement(
      "button",
      view.entry.submitLabel,
      "primary-action",
    );
    button.type = "button";
    button.addEventListener("click", () => {
      const values = Object.fromEntries(
        inputs.map(({ inputDefinition, input }) => [
          inputDefinition.key,
          input.value,
        ]),
      );
      void submitValue({ values }, [button]);
    });
    entry.replaceChildren(
      textElement("h2", "Enter the values manually"),
      textElement("p", view.entry.label),
      ...inputs.flatMap(({ label, input }) => [label, input]),
      button,
    );
    entry.dataset.status = "checking";
    entry.hidden = false;
    renderedEntryKey = key;
    return;
  }
  const label = textElement("label", view.entry.label);
  label.htmlFor = "manual-entry-value";
  const input = document.createElement("input");
  input.id = "manual-entry-value";
  input.type = "text";
  input.placeholder = view.entry.placeholder;
  input.autocomplete = "off";
  input.spellcheck = false;
  const button = textElement(
    "button",
    view.entry.submitLabel,
    "primary-action",
  );
  button.type = "button";
  // Submit manual text only through the entry contract for the displayed revision.
  button.addEventListener("click", () => {
    void submitValue({ value: input.value }, [button]);
  });
  entry.replaceChildren(
    textElement("h2", "Enter the value manually"),
    label,
    input,
    button,
  );
  entry.dataset.status = "checking";
  entry.hidden = false;
  renderedEntryKey = key;
}

/** Spread nearby targets so every authorized application pointer remains usable. */
function layoutTargetPointers(metadata) {
  const pointers = Array.isArray(metadata) ? metadata : [];
  const positioned = pointers
    .map((pointer) => ({
      pointer,
      desired: Math.max(
        5,
        Math.min(95, Number(pointer.positionRatio) * 100),
      ),
    }))
    .sort((left, right) => left.desired - right.desired);
  const minimumGap = 5;
  for (let start = 0; start < positioned.length; ) {
    let end = start + 1;
    while (
      end < positioned.length &&
      positioned[end].desired - positioned[end - 1].desired < minimumGap
    ) {
      end += 1;
    }
    const group = positioned.slice(start, end);
    const center =
      group.reduce((total, item) => total + item.desired, 0) / group.length;
    const span = minimumGap * (group.length - 1);
    const first = Math.max(5, Math.min(95 - span, center - span / 2));
    for (let index = 0; index < group.length; index += 1) {
      group[index].position = first + minimumGap * index;
    }
    start = end;
  }
  for (let index = 1; index < positioned.length; index += 1) {
    positioned[index].position = Math.max(
      positioned[index].position,
      positioned[index - 1].position + minimumGap,
    );
  }
  if (
    positioned.length &&
    positioned[positioned.length - 1].position > 95
  ) {
    const shift = positioned[positioned.length - 1].position - 95;
    for (const item of positioned) {
      item.position -= shift;
    }
  }
  if (positioned.length && positioned[0].position < 5) {
    const shift = 5 - positioned[0].position;
    for (const item of positioned) {
      item.position += shift;
    }
  }
  return positioned;
}

/** Project authorized application targets into stable, accessible rail pointers. */
function renderTargetPointers(metadata) {
  const pointers = layoutTargetPointers(metadata);
  // Build a stable key so unchanged target sets are not rendered repeatedly.
  const key = pointers.map(({ pointer }) => pointer.id).join("|");
  if (key === renderedTargetPointerKey) {
    return;
  }
  targetPointers.replaceChildren();
  if (!pointers.length) {
    targetRail.dataset.active = "false";
    renderedTargetPointerKey = key;
    return;
  }
  for (let index = 0; index < pointers.length; index += 1) {
    const { pointer: metadata, position } = pointers[index];
    const ordinal =
      pointers.length > 1
        ? `Target ${index + 1} of ${pointers.length}. `
        : "";
    const guidance = metadata.centered
      ? ordinal + "Use " + metadata.label + " in the application pane."
      : ordinal +
        metadata.label +
        " is visible in the application pane but could not be centered.";
    const marker = document.createElement("div");
    marker.className = "target-marker";
    marker.style.setProperty("--target-y", position + "%");
    marker.dataset.open = "false";
    const pointer = document.createElement("button");
    pointer.className = "target-pointer";
    pointer.type = "button";
    pointer.textContent = "←";
    pointer.setAttribute("aria-label", guidance);
    pointer.setAttribute("aria-posinset", String(index + 1));
    pointer.setAttribute("aria-setsize", String(pointers.length));
    const tooltip = document.createElement("div");
    tooltip.className = "target-tooltip";
    tooltip.setAttribute("role", "tooltip");
    tooltip.textContent = guidance;
    // Toggle one pointer explanation while closing any previously opened sibling.
    pointer.addEventListener("click", (event) => {
      event.stopPropagation();
      const opening = marker.dataset.open !== "true";
      for (const sibling of targetPointers.children) {
        sibling.dataset.open = "false";
      }
      marker.dataset.open = opening ? "true" : "false";
    });
    marker.append(pointer, tooltip);
    targetPointers.append(marker);
  }
  targetRail.dataset.active = "true";
  renderedTargetPointerKey = key;
}

// Dismiss pointer explanations when the human clicks outside a marker.
document.addEventListener("click", () => {
  for (const marker of targetPointers.children) {
    marker.dataset.open = "false";
  }
});

/** Send authenticated, no-cache requests to the session-owned loopback server. */
async function request(path, options = {}) {
  if (vscodeApi) {
    return bridgeRequest(path, options);
  }
  if (!token) {
    throw new Error("The guidance link is missing its session token.");
  }
  const response = await fetch(path, {
    ...options,
    cache: "no-store",
    headers: {
      Authorization: "Bearer " + token,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    throw new Error("Guidance request failed.");
  }
  return response.json();
}

/** Report render and visibility liveness without encoding a user decision. */
async function sendEvent(type) {
  await request("/api/event", {
    method: "POST",
    body: JSON.stringify({
      type,
      revision: renderedRevision,
      visible: document.visibilityState === "visible",
    }),
  });
}

/** Acknowledge each rendered revision once so orchestration can verify readiness. */
async function acknowledgeRender() {
  if (renderedRevision === acknowledgedRevision) {
    return;
  }
  await sendEvent("rendered");
  acknowledgedRevision = renderedRevision;
}

/** Reconcile the browser UI with the latest companion state and maintain connection status. */
async function poll() {
  try {
    const payload = await request("/api/view");
    render(payload);
    renderCollection(payload.collection);
    renderEntry(payload.view, payload.entry, payload.revision);
    renderConfirmation(payload.view, payload.confirmation, payload.revision);
    renderTargetPointers(
      payload.targetPointers ||
        (payload.targetPointer ? [payload.targetPointer] : []),
    );
    void renderVisualHelp(
      payload.view,
      payload.visualHelp,
      payload.evidenceImage,
      payload.revision,
      payload.targetPointersStatus,
    );
    await acknowledgeRender();
    connection.textContent = "Guidance connected";
    connection.dataset.connected = "true";
  } catch (error) {
    connection.textContent = error.message;
    connection.dataset.connected = "false";
  }
}

// Refresh liveness immediately when page visibility changes.
document.addEventListener("visibilitychange", () => {
  void sendEvent("heartbeat");
});
// Keep companion content responsive to server-side revision changes.
setInterval(() => void poll(), 800);
// Maintain a lightweight connection heartbeat independently of view polling.
setInterval(() => void sendEvent("heartbeat"), 2000);
void poll();
