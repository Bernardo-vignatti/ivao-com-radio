const $ = (id) => document.getElementById(id);

const el = {
  frame: $("frame"), utc: $("utc"),
  active: $("active"), standby: $("standby"),
  flagRx: $("flag-rx"), flagTx: $("flag-tx"), flag833: $("flag-833"),
  msg: $("msg"), signal: $("signal"),
  swap: $("swap"), padToggle: $("padtoggle"), pad: $("pad"),
  padVal: $("padval"), padErr: $("paderr"), keys: $("keys"),
  knob: $("knob"), knobOuter: $("knob-outer"), knobInner: $("knob-inner"),
  ptt: $("ptt"), pttLabel: $("pttlabel"), pttSub: $("pttsub"), pttKey: $("pttkey"),
  atcList: $("atclist"), atcCount: $("atccount"),
  annPc: $("ann-pc"), annSim: $("ann-sim"), annAud: $("ann-aud"),
  callsign: $("callsign"), alert: $("alert"),
  waiting: $("waiting"),
};

let ws = null;
let live = false;
let txHeld = false;
let rxOn = false;
let beatTimer = null;
let backoff = 500;
let waitTimer = null;
let lastStandby = null;

/* ---------- display de sete segmentos ---------- */

// cada digito e um SVG com os sete segmentos sempre desenhados: o apagado
// fica como fantasma ambar, igual ao display de descarga de gas do KX155
const T = 1.8;
const hseg = (x1, x2, y) =>
  `${x1},${y} ${x1 + T / 2},${y - T / 2} ${x2 - T / 2},${y - T / 2} ${x2},${y} ${x2 - T / 2},${y + T / 2} ${x1 + T / 2},${y + T / 2}`;
const vseg = (x, y1, y2) =>
  `${x},${y1} ${x + T / 2},${y1 + T / 2} ${x + T / 2},${y2 - T / 2} ${x},${y2} ${x - T / 2},${y2 - T / 2} ${x - T / 2},${y1 + T / 2}`;
const POLY = {
  a: hseg(1.6, 10.4, 1.2), g: hseg(1.6, 10.4, 10), d: hseg(1.6, 10.4, 18.8),
  f: vseg(1.2, 1.6, 9.6), b: vseg(10.8, 1.6, 9.6),
  e: vseg(1.2, 10.4, 18.4), c: vseg(10.8, 10.4, 18.4),
};
const DIGITS = {
  0: "abcdef", 1: "bc", 2: "abged", 3: "abgcd", 4: "fgbc",
  5: "afgcd", 6: "afgedc", 7: "abc", 8: "abcdefg", 9: "abcdfg", "-": "g",
};
const NS = "http://www.w3.org/2000/svg";

function buildSeg(box) {
  box._digits = [];
  for (let i = 0; i < 6; i++) {
    if (i === 3) {
      const dp = document.createElementNS(NS, "svg");
      dp.setAttribute("viewBox", "0 0 3 20");
      dp.classList.add("dp");
      const c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", "1.5"); c.setAttribute("cy", "18.6"); c.setAttribute("r", "1.3");
      c.classList.add("s");
      dp.append(c);
      box.append(dp);
      box._dp = c;
    }
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 12 20");
    const segs = {};
    for (const [k, pts] of Object.entries(POLY)) {
      const p = document.createElementNS(NS, "polygon");
      p.setAttribute("points", pts);
      p.classList.add("s");
      svg.append(p);
      segs[k] = p;
    }
    box.append(svg);
    box._digits.push(segs);
  }
  box._value = null;
}

function setSeg(box, text) {
  if (box._value === text) return;
  box._value = text;
  const chars = text.replace(".", "");
  box._digits.forEach((segs, i) => {
    const on = DIGITS[chars[i]] || "";
    for (const k in segs) segs[k].classList.toggle("on", on.includes(k));
  });
  box._dp.classList.toggle("on", /\d\.\d/.test(text));
}

document.querySelectorAll(".seg7").forEach(buildSeg);

for (let i = 0; i < 10; i++) {
  const bar = document.createElement("i");
  bar.style.height = 3 + i * 0.9 + "px";
  el.signal.append(bar);
}

/* ---------- conexão ---------- */

function connect() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);

  ws.onopen = () => {
    live = true;
    backoff = 500;
    clearTimeout(waitTimer);
    el.waiting.hidden = true;
    el.annPc.className = "ann on";
  };

  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "state") render(msg);
    else if (msg.type === "error") flashError(msg.text);
  };

  ws.onclose = () => {
    live = false;
    // solta o botão na tela também: o dead-man switch do servidor já largou
    // a tecla, e deixar o vermelho aceso faria parecer que ainda transmite
    pttUp();
    el.annPc.className = "ann bad";
    el.ptt.classList.add("off");
    // um soluco de Wi-Fi nao merece cobrir a tela; so cai para a espera se
    // a queda durar
    if (el.waiting.hidden && !waitTimer) {
      waitTimer = setTimeout(() => { el.waiting.hidden = false; waitTimer = null; }, 1500);
    }
    setTimeout(connect, backoff);
    // teto baixo: quando o PC abre, o radio tem que aparecer logo
    backoff = Math.min(backoff * 1.6, 2000);
  };

  ws.onerror = () => ws.close();
}

function send(obj) {
  if (live && ws.readyState === 1) ws.send(JSON.stringify(obj));
}

/* ---------- render ---------- */

const fmt = (mhz) => (mhz == null ? "---.---" : mhz.toFixed(3));

function render(s) {
  lastStandby = s.sim.com1.standby;
  setSeg(el.active, fmt(s.sim.com1.active));
  setSeg(el.standby, fmt(shownStandby(lastStandby)));
  el.callsign.textContent = s.sim.callsign || "—";

  rxOn = s.rx && !s.tx;
  el.ptt.classList.toggle("rx", rxOn && !txHeld);
  // o PTT só depende do WebSocket. A tecla vai para o Altitude mesmo com o
  // MSFS fechado, então apagar o botão por causa do simulador seria mentira
  el.ptt.classList.toggle("off", !live);
  el.flagRx.classList.toggle("on", rxOn);
  el.flagTx.classList.toggle("on", s.tx);

  if (!txHeld) {
    el.pttLabel.textContent = rxOn ? "recebendo" : "ouvindo";
    el.pttSub.textContent = rxOn ? "alguém na frequência" : "segure para falar";
  }

  const color = txHeld ? "var(--tx)" : rxOn ? "var(--phosphor)" : "var(--bezel)";
  document.documentElement.style.setProperty("--frame", color);

  // o nivel e o pico do medidor do Windows, nao RMS. Escala de raiz com
  // folga: fala com pico 0.2 fica perto de 60% e sobra espaco em cima
  const lit = Math.round(Math.min(1, Math.sqrt(s.level || 0) * 1.3) * 10);
  [...el.signal.children].forEach((b, i) => b.classList.toggle("on", i < lit));

  el.annSim.className = "ann" + (s.sim.connected ? " on" : s.sim.error ? " warn" : "");
  el.annAud.className = "ann" + (s.audio ? " on" : s.audio_error ? " warn" : "");
  el.pttKey.textContent = s.ptt_key ? "tecla " + s.ptt_key : "";

  renderAlert(s);
  renderAtc(s.atc, s.atc_error, s.sim.com1.active);
}

function renderAlert(s) {
  const avisos = [];
  if (s.sim.error) avisos.push(s.sim.error);
  if (s.audio_error) avisos.push(s.audio_error);
  else if (!s.audio) avisos.push("áudio parado: sem indicação de RX nesta tela");
  const texto = avisos.join(" · ");
  if (texto === el.alert.textContent && el.alert.hidden === !texto) return;
  el.alert.textContent = texto;
  el.alert.hidden = !texto;
}

let atcSignature = "";

function renderAtc(list, error, active) {
  const signature = JSON.stringify(list) + (error || "") + active;
  if (signature === atcSignature) return;
  atcSignature = signature;

  const semPosicao = list.length > 0 && list[0].distance == null;
  el.atcCount.textContent = semPosicao
    ? list.length + " · SEM POSIÇÃO"
    : list.length || "–";
  el.atcList.replaceChildren();

  if (error) {
    const p = document.createElement("p");
    p.className = "error";
    p.textContent = "sem contato com a Whazzup";
    el.atcList.append(p);
    return;
  }
  if (!list.length) {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = "nenhum controlador no raio configurado";
    el.atcList.append(p);
    return;
  }

  for (const station of list) {
    const row = document.createElement("button");
    row.className = "row" + (active != null && Math.abs(station.frequency - active) < 0.0005 ? " tuned" : "");
    const where = station.distance == null ? station.role : `${station.role} · ${station.distance} NM`;
    row.innerHTML =
      `<span class="cs"><b></b><small></small></span><span class="rf"></span>`;
    row.querySelector("b").textContent = station.callsign;
    row.querySelector("small").textContent = where;
    row.querySelector(".rf").textContent = station.frequency.toFixed(3);
    // carrega no standby, nao sintoniza na hora: e o swap que troca
    row.onclick = () => send({ type: "standby", com: 1, mhz: station.frequency });
    el.atcList.append(row);
  }
}

let msgTimer = null;
function flashError(text) {
  el.msg.textContent = text.toUpperCase();
  clearTimeout(msgTimer);
  msgTimer = setTimeout(() => (el.msg.textContent = ""), 2500);
  if (!el.pad.hidden) {
    el.padErr.textContent = text;
    el.padErr.hidden = false;
    setTimeout(() => (el.padErr.hidden = true), 2500);
  }
}

/* ---------- PTT ---------- */

function pttDown(ev) {
  ev.preventDefault();
  if (txHeld || !live) return;
  txHeld = true;
  el.ptt.setPointerCapture(ev.pointerId);
  el.ptt.classList.remove("rx");
  el.ptt.classList.add("tx");
  el.pttLabel.textContent = "transmitindo";
  el.pttSub.textContent = "solte para ouvir";
  document.documentElement.style.setProperty("--frame", "var(--tx)");
  send({ type: "ptt", down: true });
  beatTimer = setInterval(() => send({ type: "beat" }), 200);
}

function pttUp() {
  if (!txHeld) return;
  txHeld = false;
  clearInterval(beatTimer);
  el.ptt.classList.remove("tx");
  el.pttLabel.textContent = "ouvindo";
  el.pttSub.textContent = "segure para falar";
  document.documentElement.style.setProperty("--frame", "var(--bezel)");
  send({ type: "ptt", down: false });
}

el.ptt.addEventListener("pointerdown", pttDown);
["pointerup", "pointercancel"].forEach((e) => el.ptt.addEventListener(e, pttUp));
document.addEventListener("visibilitychange", () => document.hidden && pttUp());
window.addEventListener("blur", pttUp);
window.addEventListener("pagehide", pttUp);

/* ---------- botão giratório ---------- */

// anel de fora: MHz, de 118 a 136 dando a volta. Miolo: kHz em passos de 25,
// ou nos canais de 8.33 depois de um toque no miolo, como o KX155A puxado.
// O kHz da a volta sem mexer no MHz, igual ao radio de verdade
const DETENT = 18; // graus por clique: 20 cliques por volta
let mode833 = false;
try { mode833 = localStorage.getItem("com-833") === "1"; } catch (_) { /* sem storage */ }
el.flag833.classList.toggle("on", mode833);

let tune = null;      // {mhz, khz} sendo girado, mostrado no lugar da standby
let tuneUntil = 0;    // depois de mandar, espera o simulador confirmar
let sentValue = null;
let sendTimer = null;
let drag = null;
const angles = { outer: 0, inner: 0 };

const tuneMhz = () => tune.mhz + tune.khz / 1000;

function shownStandby(sby) {
  if (tune && !drag) {
    const confirmed = sby != null && Math.abs(sby - tuneMhz()) < 0.0005;
    if (confirmed || Date.now() > tuneUntil) tune = null;
  }
  return tune ? tuneMhz() : sby;
}

function khzList(mhz) {
  const out = [];
  for (let b = 0; b < 1000; b += 25) {
    for (const o of mode833 ? [0, 5, 10, 15] : [0]) out.push(b + o);
  }
  return out.filter((k) => mhz * 1000 + k <= 136975);
}

function step(ring, dir) {
  if (ring === "outer") {
    tune.mhz = tune.mhz + dir > 136 ? 118 : tune.mhz + dir < 118 ? 136 : tune.mhz + dir;
    tune.khz = Math.min(tune.khz, Math.max(...khzList(tune.mhz)));
  } else {
    const list = khzList(tune.mhz);
    tune.khz = dir > 0
      ? list.find((k) => k > tune.khz) ?? list[0]
      : [...list].reverse().find((k) => k < tune.khz) ?? list[list.length - 1];
  }
  setSeg(el.standby, fmt(tuneMhz()));
  clearTimeout(sendTimer);
  sendTimer = setTimeout(sendTune, 450);
}

function sendTune() {
  clearTimeout(sendTimer);
  if (!tune) return;
  const mhz = Math.round(tuneMhz() * 1000) / 1000;
  tuneUntil = Date.now() + 2500;
  if (mhz === sentValue) return;
  sentValue = mhz;
  send({ type: "standby", com: 1, mhz });
}

const angleOf = (ev, r) =>
  (Math.atan2(ev.clientY - (r.top + r.height / 2), ev.clientX - (r.left + r.width / 2)) * 180) / Math.PI;

el.knob.addEventListener("pointerdown", (ev) => {
  ev.preventDefault();
  if (!live || drag) return;
  el.knob.setPointerCapture(ev.pointerId);
  const r = el.knob.getBoundingClientRect();
  const dist = Math.hypot(ev.clientX - (r.left + r.width / 2), ev.clientY - (r.top + r.height / 2));
  drag = { ring: dist < r.width * 0.25 ? "inner" : "outer", last: angleOf(ev, r), acc: 0, total: 0, r };
  if (!tune) {
    const base = lastStandby ?? 118;
    const mhz = Math.floor(base + 1e-6);
    tune = { mhz, khz: Math.round((base - mhz) * 1000) };
    sentValue = Math.round(base * 1000) / 1000;
  }
});

el.knob.addEventListener("pointermove", (ev) => {
  if (!drag) return;
  const a = angleOf(ev, drag.r);
  let d = a - drag.last;
  if (d > 180) d -= 360;
  if (d < -180) d += 360;
  drag.last = a;
  drag.acc += d;
  drag.total += Math.abs(d);
  angles[drag.ring] += d;
  (drag.ring === "outer" ? el.knobOuter : el.knobInner).style.setProperty("--a", angles[drag.ring] + "deg");
  while (drag.acc >= DETENT) { step(drag.ring, 1); drag.acc -= DETENT; }
  while (drag.acc <= -DETENT) { step(drag.ring, -1); drag.acc += DETENT; }
});

function knobUp() {
  if (!drag) return;
  const tap = drag.total < 6;
  const ring = drag.ring;
  drag = null;
  if (tap && ring === "inner") {
    mode833 = !mode833;
    el.flag833.classList.toggle("on", mode833);
    try { localStorage.setItem("com-833", mode833 ? "1" : "0"); } catch (_) { /* sem storage */ }
    return;
  }
  sendTune();
}
el.knob.addEventListener("pointerup", knobUp);
el.knob.addEventListener("pointercancel", knobUp);

/* ---------- teclado numérico ---------- */

let buf = "";
const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "LIMPAR", "0", "ENT"];

for (const k of KEYS) {
  const b = document.createElement("button");
  b.textContent = k;
  b.className = "hw" + (k.length > 1 ? " word" : "");
  b.onclick = () => pressKey(k);
  el.keys.append(b);
}

function pressKey(k) {
  el.padErr.hidden = true;
  if (k === "LIMPAR") { buf = ""; }
  else if (k === "ENT") {
    const mhz = parseFloat(`${buf.slice(0, 3)}.${buf.slice(3)}`);
    if (buf.length !== 6 || !(mhz >= 118 && mhz <= 136.975)) {
      el.padErr.textContent = "fora da faixa 118.000 – 136.975";
      el.padErr.hidden = false;
      return;
    }
    send({ type: "standby", com: 1, mhz });
    buf = "";
    togglePad();
    return;
  }
  else if (buf.length < 6) buf += k;
  paintPad();
}

function paintPad() {
  const p = (buf + "______").slice(0, 6);
  el.padVal.textContent = `${p.slice(0, 3)}.${p.slice(3)}`;
}

function togglePad() {
  el.pad.hidden = !el.pad.hidden;
  el.padToggle.classList.toggle("on", !el.pad.hidden);
  buf = "";
  paintPad();
}

el.padToggle.onclick = togglePad;
el.swap.onclick = () => send({ type: "swap", com: 1 });

/* ---------- relógio e tela acesa ---------- */

setInterval(() => {
  const d = new Date();
  el.utc.textContent =
    `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}z`;
}, 1000);

async function keepAwake() {
  if (!("wakeLock" in navigator)) return;
  try {
    await navigator.wakeLock.request("screen");
  } catch (_) { /* negado, segue sem */ }
}
document.addEventListener("visibilitychange", () => !document.hidden && keepAwake());

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => { /* sem HTTPS nao registra */ });
}

setSeg(el.active, fmt(null));
setSeg(el.standby, fmt(null));
paintPad();
keepAwake();
connect();
