"use strict";

const byId = id => document.getElementById(id);
const invoke = (action, data = {}) => window.__TAURI__.core.invoke("manager", { action, data });
const mobile = /Android/i.test(navigator.userAgent);
const projectUrl = "https://github.com/Ashena1017/zombie-farm-touchhle-cn";
const palette = [
  ["豆沙粉", "#B57B98"], ["珊瑚红", "#CB705D"], ["琥珀橙", "#B57732"],
  ["青绿", "#469782"], ["湖蓝", "#568EB5"], ["丁香紫", "#7957A7"], ["石墨灰", "#75818D"]
];
const defaults = { theme: "system", accent: palette[0][1], custom: palette[0][1], isCustom: false };
const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
const calendar = new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "long", day: "numeric", weekday: "long" });
const clock = new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
const number = new Intl.NumberFormat("zh-CN");
let appearance = { ...defaults };
let snapshot = null;
let busyLaunch = false;
let appQueue = Promise.resolve();
let themeQueue = Promise.resolve();
let startupNoticeHandled = false;
let pendingIntegrityWarning = false;
let verification;
let verifyResult = null;

if (mobile) {
  document.documentElement.classList.add("mobile");
  for (const id of ["fullscreen", "wheel_zoom"]) byId(id).closest(".setting").hidden = true;
  byId("settings-fields").querySelector(".subhead").hidden = true;
  byId("open-saves").hidden = true;
  byId("browse").textContent = "导入 IPA";
  byId("hours").max = "100000";
  byId("import-save").hidden = false;
  byId("import-save").disabled = true;
  byId("export-backup").hidden = false;
  byId("reset-time").onclick = () => enqueue(async () => {
    if (await ask("重置累计快进时间", "模拟时间将恢复为手机当前时间。", "重置时间"))
      drawSnapshot(await invoke("resetTime"));
  });
  byId("import-save").onclick = () => enqueue(async () => {
    if (await ask("导入存档或备份", "选择完整备份 ZIP 或 saveGame.bin2。导入会自动备份当前进度。", "选择文件"))
      drawSnapshot(await invoke("importSave", { appId: snapshot.appId }));
  });
  byId("export-backup").onclick = () => enqueue(async () => {
    const [name] = listSelection();
    if (name) drawSnapshot(await invoke("exportBackup", { appId: snapshot.appId, name }));
  });
  window.managerBack = () => {
    const open = document.querySelector("dialog[open]");
    if (open) { open.close(); return true; }
    if (byId("game").hidden) { document.querySelector('[data-page="game"]').click(); return true; }
    return false;
  };
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && snapshot) refresh();
  });
  // Android may resume this page before SDL finishes releasing the save lock.
  let checkingGameExit = false;
  setInterval(async () => {
    if (document.hidden || !snapshot?.running || checkingGameExit) return;
    checkingGameExit = true;
    try {
      if (!(await invoke("gameRunning")).running) await refresh();
    } catch (error) {
      report(error);
    } finally {
      checkingGameExit = false;
    }
  }, 1000);
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function notify(message, error = false) {
  const feedback = byId("feedback");
  feedback.textContent = message;
  feedback.classList.toggle("bad", error);
  feedback.hidden = !message;
}

function report(error) {
  notify(String(error?.message || error), true);
}

// Keep edits in user order when the next interaction changes the selected app ID.
function enqueue(work) {
  appQueue = appQueue.then(work).catch(report);
  return appQueue;
}

for (const link of document.querySelectorAll("nav button")) {
  link.addEventListener("click", () => {
    for (const other of document.querySelectorAll("nav button")) {
      const active = other === link;
      byId(other.dataset.page).hidden = !active;
      if (active) other.setAttribute("aria-current", "page");
      else other.removeAttribute("aria-current");
    }
    byId("heading").textContent = link.lastChild.textContent.trim();
    byId("heading").focus({ preventScroll: true });
    document.querySelector("main").scrollTop = 0;
    if (!byId("feedback").classList.contains("bad")) notify("");
  });
}

function showNotice() {
  const dialog = byId("notice-dialog");
  if (!dialog.open) {
    byId("copy-project").textContent = "复制链接";
    dialog.showModal();
  }
  if (verifyResult?.level !== "ok") pendingIntegrityWarning = false;
}

function showPendingWarning() {
  if (startupNoticeHandled && pendingIntegrityWarning && !document.querySelector("dialog[open]")) showNotice();
}

for (const close of document.querySelectorAll("[data-close]")) {
  close.addEventListener("click", () => close.closest("dialog").close());
}
for (const dialog of document.querySelectorAll("dialog")) dialog.addEventListener("close", showPendingWarning);
byId("notice-link").addEventListener("click", showNotice);
byId("project").addEventListener("click", () => invoke("openProject").catch(error => {
  byId("notice-verify").textContent = String(error);
}));
byId("copy-project").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(projectUrl);
    byId("copy-project").textContent = "已复制";
  } catch {
    const range = document.createRange();
    range.selectNodeContents(byId("project"));
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    byId("copy-project").textContent = document.execCommand("copy") ? "已复制" : "按 Ctrl+C 复制";
  }
});

function ask(title, message, yes) {
  const dialog = byId("question");
  byId("question-title").textContent = title;
  byId("question-message").textContent = message;
  byId("question-yes").textContent = yes;
  dialog.returnValue = "";
  return new Promise(resolve => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "yes"), { once: true });
    dialog.showModal();
  });
}
byId("question-no").addEventListener("click", () => byId("question").close());
byId("question-yes").addEventListener("click", () => byId("question").close("yes"));

function updateTheme() {
  const mode = appearance.theme === "system" ? (systemDark.matches ? "dark" : "light") : appearance.theme;
  document.documentElement.dataset.mode = mode;
  document.documentElement.dataset.customColor = String(appearance.isCustom);
  document.documentElement.style.setProperty("--accent", appearance.accent);
  if (mobile && !CSS.supports("color", "color-mix(in srgb, black, white)")) {
    const channels = appearance.accent.slice(1).match(/../g).map(c => parseInt(c, 16));
    const dark = mode === "dark";
    const mix = (base, weight) => "rgb(" + channels.map((c, i) => Math.round(c * weight + base[i] * (1 - weight))).join(",") + ")";
    const style = document.documentElement.style;
    style.setProperty("--accent-ink", mix(dark ? [255,246,254] : [23,20,25], appearance.isCustom ? .39 : .57));
    style.setProperty("--tint", mix(dark ? [44,41,45] : [255,254,252], .19));
  }
  for (const radio of document.querySelectorAll("input[name=theme]")) radio.checked = radio.value === appearance.theme;
  for (const button of byId("swatches").children) {
    const custom = !button.dataset.color;
    const color = custom ? appearance.custom : button.dataset.color;
    const selected = custom ? appearance.isCustom : !appearance.isCustom && color === appearance.accent;
    button.setAttribute("aria-pressed", String(selected));
    const dot = button.firstElementChild;
    dot.style.backgroundColor = color;
    if (custom) {
      const [r, g, b] = color.slice(1).match(/../g).map(channel => parseInt(channel, 16));
      dot.style.color = .299 * r + .587 * g + .114 * b > 145 ? "#201e21" : "#fff";
    }
  }
}

function saveAppearance(changes) {
  const next = { ...appearance, ...changes };
  appearance = next;
  updateTheme();
  themeQueue = themeQueue.then(() => invoke("setAppearance", next)).catch(async error => {
    report(error);
    if (appearance !== next) return;
    const stored = await invoke("appearance");
    if (appearance === next) applyAppearance(stored);
  }).catch(report);
}

function applyAppearance(stored) {
  appearance = { theme: stored.theme, accent: stored.accent.toUpperCase(), custom: stored.custom.toUpperCase(), isCustom: stored.isCustom };
  updateTheme();
}

systemDark.addEventListener("change", updateTheme);
for (const radio of document.querySelectorAll("input[name=theme]")) {
  radio.addEventListener("change", () => saveAppearance({ theme: radio.value }));
}
for (const [name, color] of [...palette, ["自定义", null]]) {
  const button = element("button", undefined, "swatch");
  if (color) button.dataset.color = color;
  const dot = element("span", color ? "" : "+", "dot");
  dot.setAttribute("aria-hidden", "true");
  button.append(dot, element("span", name));
  button.addEventListener("click", () => {
    if (color) saveAppearance({ accent: color, isCustom: false });
    else {
      byId("color-picker").value = appearance.custom;
      byId("hex").value = appearance.custom;
      byId("custom-dialog").showModal();
    }
  });
  byId("swatches").append(button);
}
byId("reset-appearance").addEventListener("click", () => saveAppearance(defaults));
byId("color-picker").addEventListener("input", () => { byId("hex").value = byId("color-picker").value.toUpperCase(); });
byId("hex").addEventListener("input", () => {
  if (/^#[0-9a-f]{6}$/i.test(byId("hex").value)) byId("color-picker").value = byId("hex").value;
});
byId("custom-form").addEventListener("submit", event => {
  event.preventDefault();
  const color = byId("hex").value.toUpperCase();
  saveAppearance({ accent: color, custom: color, isCustom: true });
  byId("custom-dialog").close();
});

const customSettings = {
  fps_limit: { options: ["30", "60", "90", "120", "off"], label: v => v === "off" ? "不限帧" : v + " 帧", initial: "75", min: 1, max: 1000 },
  wheel_zoom: { options: ["1.1", "1.2", "1.5"], label: v => "×" + v, initial: "1.1", min: 1.01, max: 2 },
  window_scale: { options: ["1", "1.25", "1.5", "1.75", "2", "3", "4", "5", "6"], label: v => "×" + v, initial: "7/4", min: 1, max: 6 }
};

function settingNumber(key, text) {
  if (key === "window_scale" && /^[0-9]+\/[0-9]+$/.test(text)) {
    const [n, d] = text.split("/").map(Number);
    return n / d;
  }
  const pattern = key === "fps_limit" ? /^[0-9]+$/ : /^[0-9]+(?:\.[0-9]+)?$/;
  return pattern.test(text) ? Number(text) : NaN;
}

function showResolution() {
  const value = byId("window_scale").value;
  const scale = settingNumber("window_scale", value === "custom" ? byId("custom-window_scale").value : value);
  if (!(scale >= 1 && scale <= 6)) {
    byId("resolution").textContent = "可输入 1 至 6 的小数或分数。";
    return;
  }
  const base = byId("window_family").value === "iphone" ? [480, 320] : [1024, 768];
  const [w, h] = base.map(side => Math.round(side * scale));
  const screenScale = window.devicePixelRatio || 1;
  const tooLarge = w > screen.availWidth * screenScale || h > screen.availHeight * screenScale;
  byId("resolution").textContent = "窗口 " + w + " × " + h + (tooLarge ? " · 超出当前屏幕" : "");
}

function writeSetting(key, value) {
  if (!snapshot) return;
  const select = byId(key);
  const stillSelected = () => (select.value === "custom" ? byId("custom-" + key).value.trim() : select.value) === value;
  enqueue(async () => {
    try {
      const updated = await invoke("setSetting", { key, value });
      snapshot.settings = updated.settings;
      if (stillSelected() && !byId("settings").hidden) notify("设置已保存。");
    } catch (error) {
      if (stillSelected()) {
        showSetting(select, String(snapshot.settings[key]));
        showResolution();
      }
      throw error;
    }
  });
}

for (const select of byId("settings-fields").querySelectorAll("select")) {
  const key = select.id;
  const config = customSettings[key];
  const editor = byId("custom-" + key);
  if (config) {
    for (const value of config.options) select.add(new Option(config.label(value), value));
    select.add(new Option("自定义", "custom"));
    editor.addEventListener("input", () => {
      const value = editor.value.trim();
      const numeric = settingNumber(key, value);
      const valid = numeric >= config.min && numeric <= config.max;
      editor.setAttribute("aria-invalid", String(!valid));
      if (key === "window_scale") showResolution();
      if (valid) writeSetting(key, value);
      else notify("请输入 " + config.min + " 至 " + config.max + " 的有效值。", true);
    });
  }
  select.addEventListener("change", () => {
    if (config) editor.hidden = select.value !== "custom";
    if (select.value === "custom") {
      editor.focus();
      editor.select();
      editor.dispatchEvent(new Event("input"));
    } else {
      writeSetting(key, select.value);
    }
    showResolution();
  });
}

function showSetting(select, value) {
  const key = select.id;
  const config = customSettings[key];
  const custom = config && !config.options.includes(value);
  select.value = custom ? "custom" : value;
  if (config) {
    const editor = byId("custom-" + key);
    editor.hidden = !custom;
    editor.value = custom ? value : config.initial;
    editor.removeAttribute("aria-invalid");
  }
}

function simulatedDate(addSeconds = 0) {
  if (!snapshot || snapshot.offset == null) return null;
  const time = (snapshot.fixedTime ?? Math.floor(Date.now() / 1000)) + snapshot.offset + addSeconds;
  return time >= 0 && time <= 2147483647 ? new Date(time * 1000) : null;
}

function updateClock() {
  if (!snapshot) return;
  const date = simulatedDate();
  if (!byId("game").hidden) {
    byId("clock").textContent = date ? clock.format(date) : "--:--:--";
    const day = date ? calendar.format(date) : "无法读取模拟时间，请检查累计时间偏移。";
    if (byId("clock-date").textContent !== day) byId("clock-date").textContent = day;
  }
  if (!byId("skip-dialog").open) return;
  const hours = byId("hours"), minutes = byId("minutes");
  const valid = hours.validity.valid && minutes.validity.valid;
  const after = valid ? simulatedDate(hours.valueAsNumber * 3600 + minutes.valueAsNumber * 60) : null;
  byId("skip-preview").textContent = after ? calendar.format(after) + " " + clock.format(after) : "超出支持的时间范围";
  byId("skip-submit").disabled = !after;
}
setInterval(updateClock, 1000);
byId("hours").addEventListener("input", updateClock);
byId("minutes").addEventListener("input", updateClock);
byId("skip").addEventListener("click", () => {
  byId("hours").value = snapshot.skip.hours;
  byId("minutes").value = snapshot.skip.minutes;
  byId("skip-dialog").showModal();
  updateClock();
});
byId("skip-form").addEventListener("submit", event => {
  event.preventDefault();
  if (byId("skip-submit").disabled) return;
  byId("skip-dialog").close();
  launch(byId("hours").valueAsNumber, byId("minutes").valueAsNumber, true);
});
byId("start").addEventListener("click", () => launch(0, 0, false));

function updateLaunchButtons() {
  byId("start").disabled = busyLaunch || !snapshot?.selected || (mobile && snapshot.running);
  byId("skip").disabled = byId("start").disabled || snapshot.offset == null;
}

function launch(hours, minutes, remember) {
  if (busyLaunch) return;
  busyLaunch = true;
  updateLaunchButtons();
  enqueue(async () => {
    try {
      const data = { hours, minutes, remember, allowModified: false };
      let result = await invoke("launch", data);
      while (!result.started) {
        if (result.warning && !data.allowModified) {
          if (!await ask("文件校验", result.warning, "继续启动")) return;
          data.allowModified = true;
        } else if (result.orphan && !data.orphan) {
          if (!await ask("残留的游戏进程", "发现没有窗口的游戏进程（PID " + result.orphan.pid + "），要结束它并继续启动吗？", "结束并启动")) return;
          data.orphan = result.orphan;
        } else throw new Error("游戏进程状态已变化，请重新启动。");
        result = await invoke("launch", data);
      }
      notify("游戏已启动。");
    } finally {
      busyLaunch = false;
      updateLaunchButtons();
    }
  });
}

function listSelection() {
  return Array.from(byId("save-list").querySelectorAll("input:checked"), box => box.value);
}
function updateSelection() {
  const count = listSelection().length;
  const total = byId("save-list").querySelectorAll("input").length;
  byId("selection-count").textContent = "已选 " + count + " / " + total + " 个备份";
  byId("restore").disabled = count !== 1 || snapshot.running;
  byId("delete").disabled = count === 0 || snapshot.running;
  if (mobile) byId("export-backup").disabled = count !== 1 || snapshot.running;
}
for (const id of ["all", "none", "invert"]) {
  byId(id).addEventListener("click", () => {
    for (const box of byId("save-list").querySelectorAll("input")) box.checked = id === "all" || (id === "invert" && !box.checked);
    updateSelection();
  });
}
const saveMetadata = file => number.format(file.size) + " 字节 · " + file.modified;
function drawSaves(previousSelection) {
  const live = snapshot.saves.find(file => file.live);
  byId("live-save").textContent = live ? live.name + " · " + saveMetadata(live) : "尚未找到当前存档。";
  byId("gold").value = snapshot.currency?.gold ?? "";
  byId("brains").value = snapshot.currency?.brains ?? "";
  byId("currency-fields").disabled = !snapshot.currency || snapshot.running;
  byId("open-saves").disabled = !snapshot.saveDir;
  byId("backup").disabled = !live || snapshot.running;
  const backups = snapshot.saves.filter(file => !file.live);
  const list = byId("save-list");
  list.replaceChildren();
  for (const file of backups) {
    const row = element("label", undefined, "backup-row");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = file.name;
    box.checked = previousSelection.includes(file.name);
    box.addEventListener("change", updateSelection);
    const meta = document.createElement("div");
    meta.append(element("span", file.name), element("small", file.kind + " · " + saveMetadata(file)));
    row.append(box, meta);
    list.append(row);
  }
  if (!backups.length) list.append(element("p", "暂无存档备份。", "detail"));
  byId("backup-tools").hidden = !backups.length;
  updateSelection();
}

function drawSnapshot(updated) {
  const previousSelection = snapshot?.selected === updated.selected ? listSelection() : [];
  snapshot = updated;
  const ipa = byId("ipa");
  ipa.replaceChildren();
  for (const file of snapshot.ipas) ipa.add(new Option(file.name, file.path));
  if (!snapshot.ipas.length) ipa.add(new Option("未找到 IPA，请浏览选择…", ""));
  const picked = snapshot.ipas.find(file => file.path.toLowerCase() === snapshot.selected?.toLowerCase());
  ipa.value = picked?.path ?? "";
  ipa.disabled = !snapshot.ipas.length;
  byId("ipa-info").textContent = picked?.error ? "无法管理此 IPA 的设置和存档。" + picked.error :
    [picked?.appId, picked?.version].filter(Boolean).join(" · ");
  byId("verify-selection").textContent = picked ? "当前选择：" + picked.name : "当前未选择游戏包。";
  byId("browse").disabled = false;
  byId("settings-fields").disabled = !picked?.appId || (mobile && snapshot.running);
  if (mobile) {
    byId("import-save").disabled = !picked?.appId || snapshot.running;
    byId("reset-time").hidden = !snapshot.offset || !picked?.appId;
    byId("reset-time").disabled = snapshot.running;
  }
  byId("retry").hidden = true;
  for (const select of byId("settings-fields").querySelectorAll("select")) showSetting(select, String(snapshot.settings[select.id]));
  showResolution();
  drawSaves(previousSelection);
  updateClock();
  updateLaunchButtons();
}

function refresh() {
  return enqueue(async () => {
    try { drawSnapshot(await invoke("snapshot")); }
    catch (error) { byId("retry").hidden = false; throw error; }
  });
}
byId("retry").addEventListener("click", refresh);
byId("refresh-saves").addEventListener("click", refresh);
byId("open-saves").addEventListener("click", () => invoke("openSaves").catch(report));

function changeIpa(action, data) {
  byId("ipa").disabled = true;
  byId("browse").disabled = true;
  byId("start").disabled = true;
  byId("skip").disabled = true;
  byId("settings-fields").disabled = true;
  byId("saves").inert = true;
  enqueue(async () => {
    try {
      drawSnapshot(await invoke(action, data));
      notify("");
    } catch (error) {
      if (snapshot) drawSnapshot(snapshot);
      throw error;
    } finally {
      byId("saves").inert = false;
    }
  });
}
byId("ipa").addEventListener("change", event => changeIpa("selectIpa", { path: event.target.value }));
byId("browse").addEventListener("click", () => changeIpa("browseIpa", {}));

function saveAction(id, action, buildData) {
  byId(id).addEventListener("click", () => {
    byId(id).disabled = true;
    enqueue(async () => {
      try {
        const data = await buildData();
        if (!data) return;
        drawSnapshot(await invoke(action, data));
        notify({ backup: "已创建备份。", delete: "已删除所选备份。", restore: "已还原备份。", setCurrency: "已写入存档。" }[action]);
      } finally {
        if (id === "backup") byId(id).disabled = !snapshot.saves.some(file => file.live) || snapshot.running;
        else if (id === "write-currency") byId(id).disabled = false;
        updateSelection();
      }
    });
  });
}
saveAction("backup", "backup", () => ({}));
saveAction("restore", "restore", async () => {
  const [name] = listSelection();
  if (name && await ask("还原存档", "要用以下备份覆盖当前存档吗？当前存档将先自动备份。\n\n" + name, "还原备份")) return { name };
});
saveAction("delete", "delete", async () => {
  const names = listSelection();
  const preview = names.slice(0, 5).join("\n") + (names.length > 5 ? "\n…" : "");
  if (names.length && await ask("删除备份", "确定永久删除选中的 " + names.length + " 个备份吗？\n\n" + preview, "删除")) return { names };
});
saveAction("write-currency", "setCurrency", async () => {
  const values = [byId("gold").value.trim(), byId("brains").value.trim()];
  if (values.some(value => !/^[0-9]{1,10}$/.test(value) || Number(value) > 2147483647)) throw new Error("金币与脑子必须是 0 至 2147483647 的整数。");
  const [gold, brains] = values.map(Number);
  if (await ask("修改存档", "金币 " + number.format(gold) + "，脑子 " + number.format(brains) + "。写入前将自动备份当前存档。", "确认写入")) return { gold, brains };
});

function drawIntegrity(result) {
  verifyResult = result;
  for (const id of ["verify-headline", "notice-verify"]) {
    byId(id).textContent = result.text;
    byId(id).classList.toggle("bad", result.level !== "ok");
    byId(id).classList.toggle("ok", result.level === "ok");
  }
  const list = byId("verify-list");
  list.replaceChildren();
  const verdict = { ok: "与官方一致", bad: "与官方不一致", missing: "文件不存在", unreadable: "无法读取", info: "仅显示指纹" };
  for (const row of result.rows) {
    const details = element("details", undefined, "integrity-item");
    const title = element("summary", row.name);
    title.append(element("span", verdict[row.state] || row.state, row.state === "ok" ? "ok" : row.state === "info" ? "detail" : "bad"));
    const dl = element("dl");
    for (const [label, value] of [["文件路径", row.path], ["官方 SHA-256", row.expected], ["本机 SHA-256", row.actual]]) {
      if (value) dl.append(element("dt", label), element("dd", value));
    }
    details.append(title, dl);
    list.append(details);
  }
}

function verify() {
  if (verification) return verification;
  byId("reverify").disabled = true;
  verification = invoke("verify").catch(error => ({ text: "文件校验失败：" + String(error), level: "warn", rows: [] })).then(result => {
    const initial = !verifyResult;
    drawIntegrity(result);
    if (result.level !== "ok" && initial && !byId("notice-dialog").open) {
      pendingIntegrityWarning = true;
      showPendingWarning();
    }
  }).finally(() => {
    verification = null;
    byId("reverify").disabled = false;
  });
  return verification;
}
byId("reverify").addEventListener("click", () => verify());

updateTheme();
invoke("appearance").then(stored => {
  applyAppearance(stored);
  byId("appearance-fields").disabled = false;
  if (stored.notice) showNotice();
}).catch(error => { report(error); showNotice(); }).finally(() => {
  startupNoticeHandled = true;
  showPendingWarning();
});
window.__TAURI__.event.listen("game-exit", event => {
  notify(event.payload.message, event.payload.error);
  refresh();
}).catch(report);
// The storage worker is serial. Let the player reach Start before hashing the package.
refresh().then(verify);
