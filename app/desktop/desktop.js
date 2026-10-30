// Painel do PC. Fala com o Python pela ponte do pywebview (window.pywebview.api),
// nunca pela rede. Le o estado 8 vezes por segundo e desenha.

const $ = (id) => document.getElementById(id);
const PAGES = {
  painel: ["Painel", "Tudo o que liga o iPhone ao IVAO, num lugar só."],
  audio: ["Áudio", "O indicador de RX mede o som do IVAO no Windows."],
  ptt: ["Tecla PTT", "A tecla que o COM aperta para o IVAO Altitude transmitir."],
  iphone: ["iPhone", "Instale o rádio na tela de início do celular."],
  config: ["Configurações", "Tudo é salvo na hora no config.json."],
};

let api = null;
let S = null;
let cfg = {};
let busy = false;

/* ---------- navegação ---------- */

function go(page) {
  for (const b of document.querySelectorAll("nav button")) b.classList.toggle("on", b.dataset.page === page);
  for (const p of document.querySelectorAll(".page")) p.hidden = p.id !== "page-" + page;
  $("title").textContent = PAGES[page][0];
  $("subtitle").textContent = PAGES[page][1];
  sizeCharts();
}
for (const b of document.querySelectorAll("nav button")) b.onclick = () => go(b.dataset.page);
for (const b of document.querySelectorAll("[data-goto]")) b.onclick = () => go(b.dataset.goto);

/* ---------- aviso ---------- */

let toastTimer = null;
function toast(text, kind = "ok") {
  const t = $("toast");
  t.textContent = text;
  t.className = "toast" + (kind === "ok" ? "" : " " + kind);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), kind === "bad" ? 5000 : 2600);
}

/* ---------- gráfico do nível ---------- */

// pico do medidor do Windows, 30 s de historia. Escala de raiz: os limites do
// squelch (0.01 a 0.05) ficam longe do chao e a fala ainda cabe
const HIST = 240;
const hist = new Array(HIST).fill(0);
const TOP = Math.sqrt(0.5);
const yOf = (v, h) => h - (Math.sqrt(Math.max(0, v)) / TOP) * (h - 8) - 4;
let thr = { open: 0.03, close: 0.01 };

function sizeCharts() {
  for (const c of document.querySelectorAll("canvas")) {
    const r = c.getBoundingClientRect();
    if (!r.width) continue;
    c.width = Math.round(r.width * devicePixelRatio);
    c.height = Math.round(r.height * devicePixelRatio);
  }
}
window.addEventListener("resize", sizeCharts);

function drawChart(c, rx) {
  if (!c.offsetParent || !c.width) return;
  const g = c.getContext("2d");
  const w = c.width, h = c.height, d = devicePixelRatio;
  g.clearRect(0, 0, w, h);

  g.strokeStyle = "rgba(255,255,255,0.05)";
  g.lineWidth = d;
  for (let i = 1; i < 4; i++) {
    const y = Math.round((h / 4) * i) + 0.5;
    g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke();
  }

  const color = rx ? "98,227,155" : "255,165,36";
  const step = w / (HIST - 1);
  g.beginPath();
  g.moveTo(0, h);
  hist.forEach((v, i) => g.lineTo(i * step, yOf(v, h)));
  g.lineTo(w, h);
  g.closePath();
  const fill = g.createLinearGradient(0, 0, 0, h);
  fill.addColorStop(0, `rgba(${color},0.35)`);
  fill.addColorStop(1, `rgba(${color},0)`);
  g.fillStyle = fill;
  g.fill();

  g.beginPath();
  hist.forEach((v, i) => (i ? g.lineTo(i * step, yOf(v, h)) : g.moveTo(0, yOf(v, h))));
  g.strokeStyle = `rgb(${color})`;
  g.lineWidth = 2 * d;
  g.lineJoin = "round";
  g.stroke();

  g.setLineDash([6 * d, 5 * d]);
  g.lineWidth = 1.5 * d;
  for (const [v, col] of [[thr.open, "#FFA524"], [thr.close, "#6C7A80"]]) {
    const y = Math.round(yOf(v, h)) + 0.5;
    g.strokeStyle = col;
    g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke();
  }
  g.setLineDash([]);
}

/* ---------- estado ---------- */

const fmt = (mhz) => (mhz == null ? "---.---" : mhz.toFixed(3));

function paintStat(id, tone, detail) {
  const card = $(id);
  card.className = "card stat " + tone;
  card.querySelector(".lamp").className = "lamp " + tone;
  const d = card.querySelector(".detail");
  if (d.textContent !== detail) { d.textContent = detail; d.title = detail; }
}

function render(s) {
  // servidor
  let tone, text;
  if (!s.server.alive) [tone, text] = ["red", "parou; veja o registro"];
  else if (s.server.started) [tone, text] = ["green", "no ar"];
  else [tone, text] = ["amber", "iniciando…"];
  paintStat("st-server", tone, text);
  $("side-lamp").className = "lamp " + tone;
  $("side-text").textContent = s.server.started ? "Rádio no ar" : text;

  // simulador
  const sim = s.sim;
  paintStat("st-sim", sim.connected ? "green" : "", sim.connected ? sim.callsign || "conectado" : sim.error || "fechado ou fora do voo");

  // audio
  const a = s.audio;
  if (a.running) paintStat("st-audio", "green", a.rx ? "recebendo alguém" : "medindo " + a.source);
  else if (a.error) paintStat("st-audio", "amber", "abra o IVAO para ter RX");
  else paintStat("st-audio", "", a.enabled ? "procurando o IVAO…" : "desligado");

  // celular
  paintStat("st-phone", s.clients ? "green" : "", s.clients ? `${s.clients} conectado${s.clients > 1 ? "s" : ""}` : "aguardando o iPhone");

  // ptt
  const p = s.ptt;
  if (p.down) paintStat("st-ptt", "red", "TRANSMITINDO");
  else if (p.capture != null) paintStat("st-ptt", "amber", `aperte a tecla… ${p.capture}s`);
  else paintStat("st-ptt", "", "tecla " + p.key);

  // radio
  const rx = a.rx && !p.down;
  $("act").textContent = fmt(sim.active);
  $("sby").textContent = fmt(sim.standby);
  $("callsign").textContent = sim.callsign || "—";
  $("p-rx").className = "pill" + (rx ? " rx" : "");
  $("p-tx").className = "pill" + (p.down ? " tx" : "");
  $("radio").className = "card radio" + (p.down ? " tx" : rx ? " rx" : "");
  $("radio-note").textContent = sim.connected ? "espelho do rádio do simulador" : "MSFS fechado";

  // nivel
  hist.push(a.peak || 0);
  hist.shift();
  if (a.open != null && !dragging) thr = { open: a.open, close: a.close };
  $("aud-src").textContent = a.source || (a.enabled ? "IVAO não encontrado" : "desligado");
  $("aud-rx").textContent = rx ? "recebendo" : a.running ? "silêncio" : "sem medição";
  $("aud-level").textContent = (a.level || 0).toFixed(4);
  $("aud-peak").textContent = (a.peak || 0).toFixed(4);
  drawChart($("chart-mini"), rx);
  drawChart($("chart-big"), rx);

  renderPtt(p);
  renderAtc(s.atc, s.atc_error, sim.active);
  $("phones").textContent = s.clients ? `${s.clients} conectado${s.clients > 1 ? "s" : ""}` : "nenhum conectado";
}

let atcSig = "";
function renderAtc(list, error, active) {
  const sig = JSON.stringify(list) + error + active;
  if (sig === atcSig) return;
  atcSig = sig;
  const box = $("atc-list");
  box.replaceChildren();
  $("atc-count").textContent = error ? "sem contato" : list.length ? `${list.length} ${list.length > 1 ? "estações" : "estação"}` : "nenhuma";
  if (error || !list.length) {
    const p = document.createElement("p");
    p.className = error ? "error" : "empty";
    p.textContent = error ? "sem contato com a Whazzup da IVAO" : "nenhum controlador no raio configurado";
    box.append(p);
    return;
  }
  for (const st of list) {
    const row = document.createElement("div");
    row.className = "atc-row" + (active != null && Math.abs(st.frequency - active) < 0.001 ? " tuned" : "");
    for (const [cls, txt, tag] of [
      ["", st.callsign, "b"],
      ["role", st.role || "–", "span"],
      ["dist", st.distance == null ? "–" : `${st.distance} NM`, "span"],
      ["rf", st.frequency.toFixed(3), "span"],
    ]) {
      const e = document.createElement(tag);
      if (cls) e.className = cls;
      e.textContent = txt;
      row.append(e);
    }
    box.append(row);
  }
}

/* ---------- PTT ---------- */

let testArmed = null;

function renderPtt(p) {
  const cap = $("keycap");
  const line = $("ptt-line");
  cap.textContent = p.key;
  cap.className = "keycap mono" + (p.down ? " down" : p.capture != null ? " wait" : "");
  $("capture").disabled = p.capture != null;
  $("capture").textContent = p.capture != null ? `Aguardando… ${p.capture}s` : "Mudar tecla";
  let text = "É a tecla que o COM aperta quando você segura o PTT no iPhone.", tone = "";
  if (p.down) [text, tone] = ["Transmitindo agora.", "red"];
  else if (p.capture != null) [text, tone] = ["Aperte a tecla ou o botão do mouse que o IVAO usa.", "amber"];
  else if (p.notice) [text, tone] = [p.notice.text, p.notice.tone];
  if (line.textContent !== text) line.textContent = text;
  line.className = "ptt-line " + tone;
}

$("capture").onclick = () => api.capture_key();

$("test").onclick = async () => {
  const b = $("test");
  // dois cliques: o teste aperta a tecla de verdade e pode transmitir
  if (!testArmed) {
    b.textContent = "Confirmar: vai transmitir";
    b.classList.add("danger");
    testArmed = setTimeout(disarm, 4000);
    return;
  }
  disarm();
  b.disabled = true;
  const r = await api.test_ptt();
  b.disabled = false;
  toast(r.text, r.ok ? "ok" : "bad");
};
function disarm() {
  clearTimeout(testArmed);
  testArmed = null;
  $("test").textContent = "Testar tecla";
  $("test").classList.remove("danger");
}

/* ---------- configurações ---------- */

let dragging = false;
const show = {
  squelch_open: (v) => (+v).toFixed(3),
  squelch_close: (v) => (+v).toFixed(3),
  squelch_hang_ms: (v) => `${v} ms`,
};

function paintInput(el) {
  const key = el.dataset.cfg;
  const v = cfg[key];
  if (el.type === "checkbox") el.checked = !!v;
  else if (key === "audio_process") el.value = (v || []).join(", ");
  else el.value = v;
  paintRange(el);
}

function paintRange(el) {
  if (el.type !== "range") return;
  const pct = ((el.value - el.min) / (el.max - el.min)) * 100;
  el.style.setProperty("--fill", pct + "%");
  const out = document.querySelector(`[data-show="${el.dataset.cfg}"]`);
  if (out) out.textContent = show[el.dataset.cfg](el.value);
}

async function save(el) {
  const key = el.dataset.cfg;
  let value = el.type === "checkbox" ? el.checked : el.value;
  if (key === "audio_process") value = value.split(",");
  const r = await api.set_config(key, value);
  if (r.error) {
    toast(r.error, "bad");
  } else {
    cfg[key] = r.value;
    toast(r.restart ? "Salvo. Vale na próxima vez que abrir o COM Radio." : "Salvo.", r.restart ? "info" : "ok");
  }
  paintInput(el);
}

for (const el of document.querySelectorAll("[data-cfg]")) {
  el.addEventListener("change", () => save(el));
  if (el.type === "range") {
    el.addEventListener("input", () => {
      dragging = true;
      paintRange(el);
      // o grafico acompanha o arraste antes de salvar
      if (el.dataset.cfg === "squelch_open") thr.open = +el.value;
      if (el.dataset.cfg === "squelch_close") thr.close = +el.value;
    });
    el.addEventListener("change", () => (dragging = false));
  }
}

/* ---------- procurar programas com som ---------- */

$("scan").onclick = async () => {
  const b = $("scan");
  b.disabled = true;
  $("scan-note").textContent = "medindo por 4 s… fale ou espere alguém transmitir";
  const list = await api.scan_audio();
  b.disabled = false;
  $("scan-note").textContent = list.length ? "" : "nenhum programa com som aberto";
  const box = $("scan-list");
  box.replaceChildren();
  const max = Math.max(0.05, ...list.map((s) => s.peak));
  for (const s of list.sort((x, y) => y.peak - x.peak)) {
    const name = s.exe.split("\\").pop();
    const row = document.createElement("div");
    row.className = "scan-row" + (s.ivao ? " ivao" : "");
    row.innerHTML = `<div><b></b><small></small></div><div class="bar"><span></span></div><div></div>`;
    row.querySelector("b").textContent = name;
    row.querySelector("small").textContent = s.exe;
    row.querySelector(".bar span").style.width = (Math.sqrt(s.peak / max) * 100).toFixed(0) + "%";
    const end = row.lastElementChild;
    if (s.ivao) {
      end.innerHTML = '<span class="tag">medido</span>';
    } else {
      const use = document.createElement("button");
      use.className = "btn small";
      use.textContent = "Usar este";
      use.onclick = async () => {
        const field = document.querySelector('[data-cfg="audio_process"]');
        const stem = name.replace(/\.exe$/i, "").toLowerCase();
        field.value = [...(cfg.audio_process || []), stem].join(", ");
        await save(field);
        $("scan").click();
      };
      end.append(use);
    }
    box.append(row);
  }
};

/* ---------- início ---------- */

setInterval(() => {
  $("utc").textContent = new Date().toISOString().slice(11, 19);
}, 500);

$("quit").onclick = () => api.quit();
$("open-data").onclick = () => api.open_data();

async function tick() {
  if (busy) return;
  busy = true;
  try {
    S = await api.state();
    render(S);
  } catch (e) {
    console.error(e);
  } finally {
    busy = false;
  }
}

window.addEventListener("pywebviewready", async () => {
  api = window.pywebview.api;
  const info = await api.info();
  cfg = info.config;
  for (const el of document.querySelectorAll("[data-cfg]")) paintInput(el);
  $("qr").innerHTML = info.qr;
  $("setup-url").textContent = info.setup_url;
  $("radio-url").textContent = info.radio_url;
  $("deadman").textContent = info.deadman_ms;
  $("version").textContent = "v" + info.version;
  $("data-dir").textContent = info.data_dir;
  $("port").textContent = cfg.port;
  $("setup-port").textContent = cfg.setup_port;
  sizeCharts();
  tick();
  setInterval(tick, 125);
});
