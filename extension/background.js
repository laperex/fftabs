"use strict";

// Talks to the `fftabs` native messaging host over a long-lived port.
// The host forwards requests from the CLI as {id, cmd, ...}; we answer with
// {id, ok, result} or {id, ok:false, error}.

const HOST = "fftabs";
const MIN_DELAY = 1000;
const MAX_DELAY = 30000;
let port = null;
let retryDelay = MIN_DELAY;

function connect() {
  try {
    port = browser.runtime.connectNative(HOST);
  } catch (e) {
    port = null;
    scheduleReconnect();
    return;
  }
  port.onMessage.addListener(onRequest);
  port.onDisconnect.addListener(() => {
    port = null;
    scheduleReconnect();
  });
}

function scheduleReconnect() {
  setTimeout(connect, retryDelay);
  retryDelay = Math.min(retryDelay * 2, MAX_DELAY);
}

async function onRequest(msg) {
  retryDelay = MIN_DELAY;
  let reply;
  try {
    reply = { id: msg.id, ok: true, result: await handle(msg) };
  } catch (e) {
    reply = { id: msg.id, ok: false, error: String((e && e.message) || e) };
  }
  if (port) port.postMessage(reply);
}

async function handle(msg) {
  switch (msg.cmd) {
    case "ping":
      return "pong";
    case "list":
      return listTabs();
    case "switch":
      return switchTab(msg.tabId);
    case "close":
      return closeTab(msg.tabId);
    default:
      throw new Error("unknown command: " + msg.cmd);
  }
}

async function containers() {
  try {
    if (!browser.contextualIdentities) return new Map();
    const list = (await browser.contextualIdentities.query({})) || [];
    return new Map(list.map((c) => [c.cookieStoreId, { name: c.name, color: c.color }]));
  } catch (e) {
    return new Map();
  }
}

async function listTabs() {
  const [tabs, windows, ctx] = await Promise.all([
    browser.tabs.query({}),
    browser.windows.getAll({ windowTypes: ["normal"] }),
    containers(),
  ]);

  const wins = new Map();
  windows
    .slice()
    .sort((a, b) => a.id - b.id)
    .forEach((w, i) => wins.set(w.id, { id: w.id, n: i + 1, focused: w.focused, private: w.incognito }));

  return tabs
    .filter((t) => wins.has(t.windowId))
    .map((t) => ({
      id: t.id,
      index: t.index,
      window: wins.get(t.windowId),
      title: t.title || "",
      url: t.url || "",
      favIconUrl: t.favIconUrl || "",
      active: !!t.active,
      pinned: !!t.pinned,
      audible: !!t.audible,
      muted: !!(t.mutedInfo && t.mutedInfo.muted),
      discarded: !!t.discarded,
      lastAccessed: t.lastAccessed || 0,
      container: ctx.get(t.cookieStoreId) || null,
    }));
}

async function switchTab(tabId) {
  const tab = await browser.tabs.get(tabId);
  await browser.tabs.update(tabId, { active: true });
  await browser.windows.update(tab.windowId, { focused: true });
  return { windowId: tab.windowId, title: tab.title || "" };
}

async function closeTab(tabId) {
  await browser.tabs.remove(tabId);
  return true;
}

connect();
