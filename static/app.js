const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let devices = [];
let selectedDevice = null;
let diagWs = null;

const HISTORY_SEC = 300;
const POLL_MS = 1000;
const history = { spo2: [], bpm: [], perfusion: [] };
const graphColors = { spo2: "#58a6ff", bpm: "#3fb950", perfusion: "#f0883e" };
const graphRanges = { spo2: [80, 100], bpm: [40, 180], perfusion: [0, 100] };

document.addEventListener("DOMContentLoaded", async () => {
  await loadDevices();
  await loadConfig();
  setupListeners();
  connectDiagWs();
  requestAnimationFrame(() => { sizeCanvases(); });
  window.addEventListener("resize", sizeCanvases);
});

async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json", "X-UI-Token": window.UI_TOKEN || "" } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`/api${path}`, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || data.error || "Request failed");
  return data;
}

async function loadDevices() {
  devices = await api("GET", "/devices");
  const sel = $("#sel-device");
  sel.innerHTML = '<option value="">— choose —</option>';
  devices.forEach((d) => {
    const opt = document.createElement("option");
    opt.value = d.slug;
    opt.textContent = d.name;
    sel.appendChild(opt);
  });
}

async function loadConfig() {
  const cfg = await api("GET", "/config");
  if (cfg.device_type) { $("#sel-device").value = cfg.device_type; onDeviceChange(cfg.device_type); }
  if (cfg.connection_mode) {
    const radio = $(`input[name="conn"][value="${cfg.connection_mode}"]`);
    if (radio) { radio.checked = true; onConnModeChange(cfg.connection_mode); }
  }
  if (cfg.usb_port) $("#sel-port").value = cfg.usb_port;
  if (cfg.baud_rate) $("#sel-baud").value = String(cfg.baud_rate);
  if (cfg.lan_listen_port) $("#inp-lan-port").value = cfg.lan_listen_port;
  updatePairUI(cfg);
  updateRunningUI(cfg.is_running);
  loadMqttUI(cfg);
}

function setupListeners() {
  $("#sel-device").addEventListener("change", (e) => onDeviceChange(e.target.value));
  $$('input[name="conn"]').forEach((r) => r.addEventListener("change", (e) => onConnModeChange(e.target.value)));
  $("#btn-refresh-ports").addEventListener("click", refreshPorts);
  $("#btn-save-config").addEventListener("click", saveConfig);
  $("#btn-unpair").addEventListener("click", unpair);
  $("#btn-start").addEventListener("click", start);
  $("#btn-stop").addEventListener("click", stop);
  $("#chk-mqtt").addEventListener("change", onMqttToggle);
  $("#btn-save-mqtt").addEventListener("click", saveMqtt);

  $("#btn-settings-open").addEventListener("click", () => openModal("modal-settings"));
  $("#btn-settings-close").addEventListener("click", () => closeModal("modal-settings"));
  $("#btn-diag-open").addEventListener("click", () => { openModal("modal-diag"); loadDiagBuffer(); });
  $("#btn-diag-close").addEventListener("click", () => closeModal("modal-diag"));
  $("#btn-pair-allow").addEventListener("click", () => respondToPair(true));
  $("#btn-pair-deny").addEventListener("click", () => respondToPair(false));

  $$(".modal-overlay").forEach((el) => {
    if (el.id === "modal-pair") return; // must be answered via Allow/Deny
    el.addEventListener("click", (e) => { if (e.target === el) el.classList.add("hidden"); });
  });
}

function openModal(id) { $("#" + id).classList.remove("hidden"); }
function closeModal(id) { $("#" + id).classList.add("hidden"); }

function onDeviceChange(slug) {
  selectedDevice = devices.find((d) => d.slug === slug) || null;
  if (!selectedDevice) { $("#sec-connection").classList.add("hidden"); return; }
  $("#sec-connection").classList.remove("hidden");
  const modes = selectedDevice.supported_connections;
  $$('input[name="conn"]').forEach((r) => {
    r.closest("label").classList.toggle("hidden", !modes.includes(r.value));
    r.checked = false;
  });
  if (modes.length === 1) {
    $(`input[name="conn"][value="${modes[0]}"]`).checked = true;
    onConnModeChange(modes[0]);
  } else {
    $("#usb-opts").classList.add("hidden");
    $("#lan-opts").classList.add("hidden");
  }
  $("#sel-baud").value = String(selectedDevice.default_baud_rate);
}

function onConnModeChange(mode) {
  $("#usb-opts").classList.toggle("hidden", mode !== "usb");
  $("#lan-opts").classList.toggle("hidden", mode !== "lan");
  if (mode === "usb") refreshPorts();
}

async function refreshPorts() {
  const ports = await api("GET", "/ports");
  const sel = $("#sel-port");
  sel.innerHTML = '<option value="">—</option>';
  ports.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p.device;
    opt.textContent = `${p.device}  (${p.description})`;
    sel.appendChild(opt);
  });
}

async function saveConfig() {
  const mode = $('input[name="conn"]:checked')?.value;
  if (!selectedDevice || !mode) return;
  const body = { device_type: selectedDevice.slug, connection_mode: mode };
  if (mode === "usb") {
    body.usb_port = $("#sel-port").value;
    body.baud_rate = parseInt($("#sel-baud").value, 10);
  } else {
    body.lan_listen_port = parseInt($("#inp-lan-port").value, 10);
  }
  try {
    const res = await api("POST", "/config", body);
    updatePairUI(res);
    updateRunningUI(res.is_running);
  } catch (e) { alert(e.message); }
}

function updatePairUI(cfg) {
  if (!cfg) return;
  if (cfg.is_paired) {
    $("#pair-text").textContent = `Paired — Reader #${cfg.reader_id ?? "?"}`;
    $("#btn-unpair").classList.remove("hidden");
  } else {
    $("#pair-text").textContent = "Not paired. Initiate pairing from the host app.";
    $("#btn-unpair").classList.add("hidden");
  }
  updatePairRequestModal(cfg);
}

function updatePairRequestModal(cfg) {
  if (cfg.pending_pair) {
    $("#pair-hub-ip").textContent = cfg.pending_pair.hub_ip || "unknown";
    openModal("modal-pair");
  } else {
    closeModal("modal-pair");
  }
}

async function respondToPair(accept) {
  try {
    await api("POST", "/pair/respond", { accept });
  } catch (e) { alert(e.message); }
  closeModal("modal-pair");
  await loadConfig();
}

function updateRunningUI(running) {
  const badge = $("#status-badge");
  badge.textContent = running ? "Running" : "Stopped";
  badge.className = `badge ${running ? "on" : "off"}`;
  $("#btn-start").disabled = running;
  $("#btn-stop").disabled = !running;
}

function sizeCanvases() {
  ["spo2", "bpm", "perf"].forEach((id) => {
    const canvas = $("#graph-" + id);
    if (!canvas) return;
    const parent = canvas.parentElement;
    const w = parent.offsetWidth;
    const h = parent.offsetHeight;
    if (w === 0 || h === 0) return;
    canvas.width = Math.round(w * devicePixelRatio);
    canvas.height = Math.round(h * devicePixelRatio);
  });
  drawAllGraphs();
}

function pushHistory(key, value) {
  if (value == null || value < 0) return;   // skip sentinel / missing
  const now = Date.now();
  const arr = history[key];
  arr.push({ t: now, v: value });
  const cutoff = now - HISTORY_SEC * 1000;
  while (arr.length && arr[0].t < cutoff) arr.shift();
}

function ensureCanvasSize(canvas) {
  const parent = canvas.parentElement;
  const w = parent.offsetWidth;
  const h = parent.offsetHeight;
  if (w === 0 || h === 0) return;
  const bw = Math.round(w * devicePixelRatio);
  const bh = Math.round(h * devicePixelRatio);
  if (canvas.width !== bw || canvas.height !== bh) {
    canvas.width = bw;
    canvas.height = bh;
  }
}

function drawGraph(canvasId, key, color) {
  const canvas = $("#graph-" + canvasId);
  if (!canvas) return;
  ensureCanvasSize(canvas);
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  if (w === 0 || h === 0) return;
  ctx.clearRect(0, 0, w, h);

  const arr = history[key];
  if (arr.length < 2) return;

  const now = Date.now();
  const tMin = now - HISTORY_SEC * 1000;

  // Auto-range: scale to actual data with padding so small changes are visible
  const dataMin = Math.min(...arr.map(p => p.v));
  const dataMax = Math.max(...arr.map(p => p.v));
  const span = dataMax - dataMin;
  const padding = Math.max(1, span * 0.15);
  let vMin = Math.floor(dataMin - padding);
  let vMax = Math.ceil(dataMax + padding);
  if (vMax - vMin < 3) { vMin -= 2; vMax += 2; }
  const pad = 4 * devicePixelRatio;

  // grid lines
  ctx.strokeStyle = "rgba(255,255,255,.06)";
  ctx.lineWidth = 1;
  for (let i = 1; i < 5; i++) {
    const y = pad + ((h - 2 * pad) * i) / 5;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }
  for (let i = 1; i < 5; i++) {
    const x = (w * i) / 5;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  }

  // data line
  ctx.strokeStyle = color;
  ctx.lineWidth = 2 * devicePixelRatio;
  ctx.lineJoin = "round";
  ctx.beginPath();
  let started = false;
  for (const pt of arr) {
    const x = ((pt.t - tMin) / (HISTORY_SEC * 1000)) * w;
    const ratio = Math.max(0, Math.min(1, (pt.v - vMin) / (vMax - vMin)));
    const y = h - pad - ratio * (h - 2 * pad);
    if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // glow fill
  const last = arr[arr.length - 1];
  const lx = ((last.t - tMin) / (HISTORY_SEC * 1000)) * w;
  const ly = h - pad - Math.max(0, Math.min(1, (last.v - vMin) / (vMax - vMin))) * (h - 2 * pad);
  ctx.lineTo(lx, h);
  ctx.lineTo(((arr[0].t - tMin) / (HISTORY_SEC * 1000)) * w, h);
  ctx.closePath();
  ctx.fillStyle = `${color}11`;
  ctx.fill();
}

function drawAllGraphs() {
  drawGraph("spo2", "spo2", graphColors.spo2);
  drawGraph("bpm", "bpm", graphColors.bpm);
  drawGraph("perf", "perfusion", graphColors.perfusion);
}

function updateVitals(parsed) {
  if (parsed.spo2 != null) { $("#val-spo2").textContent = parsed.spo2 < 0 ? "--" : parsed.spo2; pushHistory("spo2", parsed.spo2); }
  if (parsed.bpm != null) { $("#val-bpm").textContent = parsed.bpm < 0 ? "--" : parsed.bpm; pushHistory("bpm", parsed.bpm); }
  if (parsed.perfusion != null) { $("#val-perf").textContent = parsed.perfusion < 0 ? "--" : parsed.perfusion; pushHistory("perfusion", parsed.perfusion); }
  $("#alarm-spo2").classList.toggle("hidden", !parsed.spo2_alarm);
  $("#alarm-bpm").classList.toggle("hidden", !parsed.bpm_alarm);
  drawAllGraphs();
}

async function unpair() { await api("POST", "/unpair"); await loadConfig(); }

function loadMqttUI(cfg) {
  if (cfg.mqtt_enabled != null) $("#chk-mqtt").checked = cfg.mqtt_enabled;
  $("#mqtt-opts").classList.toggle("hidden", !cfg.mqtt_enabled);
  if (cfg.mqtt_broker != null) $("#inp-mqtt-broker").value = cfg.mqtt_broker;
  if (cfg.mqtt_port != null) $("#inp-mqtt-port").value = cfg.mqtt_port;
  if (cfg.mqtt_username != null) $("#inp-mqtt-user").value = cfg.mqtt_username;
  if (cfg.mqtt_password != null && cfg.mqtt_password !== "") $("#inp-mqtt-pass").value = cfg.mqtt_password;
  if (cfg.mqtt_topic1 != null) $("#inp-mqtt-topic1").value = cfg.mqtt_topic1;
  if (cfg.mqtt_topic2 != null) $("#inp-mqtt-topic2").value = cfg.mqtt_topic2;
  if (cfg.mqtt_topic3 != null) $("#inp-mqtt-topic3").value = cfg.mqtt_topic3;
  if (cfg.mqtt_client_id != null) $("#inp-mqtt-clientid").value = cfg.mqtt_client_id;
}

function onMqttToggle() {
  $("#mqtt-opts").classList.toggle("hidden", !$("#chk-mqtt").checked);
}

async function saveMqtt() {
  const body = {
    mqtt_enabled: $("#chk-mqtt").checked,
    mqtt_broker: $("#inp-mqtt-broker").value.trim(),
    mqtt_port: parseInt($("#inp-mqtt-port").value, 10) || 1883,
    mqtt_username: $("#inp-mqtt-user").value.trim(),
    mqtt_password: $("#inp-mqtt-pass").value,
    mqtt_topic1: $("#inp-mqtt-topic1").value.trim(),
    mqtt_topic2: $("#inp-mqtt-topic2").value.trim(),
    mqtt_topic3: $("#inp-mqtt-topic3").value.trim(),
    mqtt_client_id: $("#inp-mqtt-clientid").value.trim() || "shh-reader",
  };
  try {
    await api("POST", "/mqtt", body);
  } catch (e) { alert(e.message); }
}

async function start() {
  try { await api("POST", "/start"); updateRunningUI(true); }
  catch (e) { alert(e.message); }
}

async function stop() {
  try { await api("POST", "/stop"); updateRunningUI(false); }
  catch (e) { alert(e.message); }
}

function connectDiagWs() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  diagWs = new WebSocket(`${proto}//${location.host}/api/diagnostics/ws`);
  diagWs.onmessage = (ev) => appendDiag(ev.data);
  diagWs.onclose = () => setTimeout(connectDiagWs, 3000);
  diagWs.onerror = () => diagWs.close();
}

async function loadDiagBuffer() {
  try {
    const res = await api("GET", "/diagnostics");
    $("#diag-log").textContent = "";
    (res.lines || []).forEach((l) => appendDiag(l));
  } catch (_) {}
}

function appendDiag(line) {
  const log = $("#diag-log");
  log.textContent += line + "\n";
  log.scrollTop = log.scrollHeight;
}

// Poll config for pairing changes and latest vitals
// (2s so an incoming pairing request prompts quickly)
setInterval(async () => {
  try {
    const cfg = await api("GET", "/config");
    updatePairUI(cfg);
    updateRunningUI(cfg.is_running);
  } catch (_) {}
}, 2000);

setInterval(async () => {
  try {
    const res = await api("GET", "/latest");
    if (res && res.spo2 == null && res.bpm == null) return;
    if (res && res.spo2 !== undefined) updateVitals(res);
  } catch (_) {}
}, 1000);
