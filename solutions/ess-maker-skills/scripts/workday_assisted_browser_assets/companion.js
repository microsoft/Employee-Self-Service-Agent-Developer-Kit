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
let renderedRevision = 0;
let acknowledgedRevision = 0;
let renderedEvidenceImageId = null;
let evidenceImageUrl = null;
let renderedEntryKey = null;
let renderedConfirmationKey = null;
let renderedTargetPointerKey = null;

function textElement(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) {
    element.className = className;
  }
  return element;
}

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
      ...new Set(actions.map((action) => action.disclaimer).filter(Boolean)),
    ];
    for (const disclaimer of disclaimers) {
      nodes.push(textElement("p", disclaimer, "navigation-disclaimer"));
    }
  }
  guidance.dataset.status = view.status;
  guidance.replaceChildren(...nodes);
}

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
        "Playwright is navigating the authorized Entra pane and reading the requested row.",
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
      textElement("dt", "Evidence"),
      textElement("dd", "Read from " + result.sourceSurface),
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

async function renderEvidenceImage(metadata) {
  if (!metadata) {
    evidence.hidden = true;
    evidence.replaceChildren();
    renderedEvidenceImageId = null;
    if (evidenceImageUrl) {
      URL.revokeObjectURL(evidenceImageUrl);
      evidenceImageUrl = null;
    }
    return;
  }
  if (metadata.id === renderedEvidenceImageId) {
    return;
  }
  if (evidenceImageUrl) {
    URL.revokeObjectURL(evidenceImageUrl);
    evidenceImageUrl = null;
  }
  const button = textElement(
    "button",
    "Show me what to click",
    "secondary-action",
  );
  button.type = "button";
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Loading screenshot...";
    try {
      const response = await fetch("/api/evidence-image", {
        cache: "no-store",
        headers: {
          Authorization: "Bearer " + token,
        },
      });
      if (!response.ok) {
        throw new Error("Context screenshot could not be loaded.");
      }
      evidenceImageUrl = URL.createObjectURL(await response.blob());
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
    } catch (error) {
      button.disabled = false;
      button.textContent = "Show me what to click";
      evidence.append(textElement("p", error.message, "decision-error"));
    }
  });
  evidence.replaceChildren(textElement("h2", "Need visual help?"), button);
  evidence.hidden = false;
  renderedEvidenceImageId = metadata.id;
}

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
    confirmButton.addEventListener("click", () => void decide("confirmed"));
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
        "Search again requested. The existing row authorization remains active.",
      ),
    );
    confirmation.dataset.status = "checking";
  }
  confirmation.hidden = false;
  confirmation.replaceChildren(...nodes);
  renderedConfirmationKey = key;
}

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
    entry.replaceChildren(
      textElement("h2", "Worksheet value submitted"),
      textElement("p", "The session will record this worksheet value."),
    );
    entry.dataset.status = "success";
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
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const response = await request("/api/entry", {
        method: "POST",
        body: JSON.stringify({
          operation: view.entry.operation,
          revision,
          value: input.value,
        }),
      });
      renderEntry(view, response.entry, revision);
    } catch (error) {
      button.disabled = false;
      entry.append(textElement("p", error.message, "decision-error"));
    }
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

function renderTargetPointers(metadata) {
  const pointers = Array.isArray(metadata) ? metadata : [];
  const key = pointers.map((pointer) => pointer.id).join("|");
  if (key === renderedTargetPointerKey) {
    return;
  }
  targetPointers.replaceChildren();
  if (!pointers.length) {
    targetRail.dataset.active = "false";
    renderedTargetPointerKey = key;
    return;
  }
  for (const metadata of pointers) {
    const percent = Math.max(
      5,
      Math.min(95, Number(metadata.positionRatio) * 100),
    );
    const guidance = metadata.centered
      ? "Use " + metadata.label + " in the application pane."
      : metadata.label +
        " is visible in the application pane but could not be centered.";
    const marker = document.createElement("div");
    marker.className = "target-marker";
    marker.style.setProperty("--target-y", percent + "%");
    marker.dataset.open = "false";
    const pointer = document.createElement("button");
    pointer.className = "target-pointer";
    pointer.type = "button";
    pointer.textContent = "←";
    pointer.setAttribute("aria-label", guidance);
    const tooltip = document.createElement("div");
    tooltip.className = "target-tooltip";
    tooltip.setAttribute("role", "tooltip");
    tooltip.textContent = guidance;
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

document.addEventListener("click", () => {
  for (const marker of targetPointers.children) {
    marker.dataset.open = "false";
  }
});

async function request(path, options = {}) {
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

async function acknowledgeRender() {
  if (renderedRevision === acknowledgedRevision) {
    return;
  }
  await sendEvent("rendered");
  acknowledgedRevision = renderedRevision;
}

async function poll() {
  try {
    const payload = await request("/api/view");
    render(payload);
    await renderEvidenceImage(payload.evidenceImage);
    renderCollection(payload.collection);
    renderEntry(payload.view, payload.entry, payload.revision);
    renderConfirmation(payload.view, payload.confirmation, payload.revision);
    renderTargetPointers(
      payload.targetPointers ||
        (payload.targetPointer ? [payload.targetPointer] : []),
    );
    await acknowledgeRender();
    connection.textContent = "Guidance connected";
    connection.dataset.connected = "true";
  } catch (error) {
    connection.textContent = error.message;
    connection.dataset.connected = "false";
  }
}

document.addEventListener("visibilitychange", () => {
  void sendEvent("heartbeat");
});
setInterval(() => void poll(), 800);
setInterval(() => void sendEvent("heartbeat"), 2000);
void poll();
