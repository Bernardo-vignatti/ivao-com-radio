const $ = (id) => document.getElementById(id);

const el = {
  frame: $("frame"), lamp: $("lamp"), utc: $("utc"),
  active: $("active"), standby: $("standby"),
  pillRx: $("pill-rx"), pillTx: $("pill-tx"),
  swap: $("swap"), padToggle: $("padtoggle"), pad: $("pad"),
  padVal: $("padval"), padErr: $("paderr"), keys: $("keys"),
  ptt: $("ptt"), pttLabel: $("pttlabel"), pttSub: $("pttsub"),
  atcList: $("atclist"), atcCount: $("atccount"),
  link: $("link"), audioStat: $("audiostat"),
  callsign: $("callsign"), alert: $("alert"),
  meterBar: $("meterbar"), pttKey: $("pttkey"),
  waiting: $("waiting"),
};

let ws = null;
let live = false;
let txHeld = false;
let rxOn = false;
let beatTimer = null;
let backoff = 500;
let waitTimer = null;

/* ---------- conexão ---------- */

function connect() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);

  ws.onopen = () => {
    live = true;
    backoff = 500;
    clearTimeout(waitTimer);
    el.waiting.hidden = true;
    el.link.textContent = "conectado";
    el.lamp.classList.add("on");
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
    el.lamp.classList.remove("on");
    el.link.textContent = "reconectando…";
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
  el.active.textContent = fmt(s.sim.com1.active);
  el.standby.textContent = fmt(s.sim.com1.standby);
  el.callsign.textContent = s.sim.callsign || "—";

  rxOn = s.rx && !s.tx;
  el.ptt.classList.toggle("rx", rxOn && !txHeld);
  // o PTT só depende do WebSocket. A tecla vai para o Altitude mesmo com o
  // MSFS fechado, então apagar o botão por causa do simulador seria mentira
  el.ptt.classList.toggle("off", !live);
  el.pillRx.className = "pill" + (rxOn ? " rx" : "");
  el.pillTx.className = "pill" + (s.tx ? " tx" : "");

  if (!txHeld) {
    el.pttLabel.textContent = rxOn ? "recebendo" : "ouvindo";
    el.pttSub.textContent = rxOn ? "alguém na frequência" : "segure para falar";
  }

  const color = txHeld ? "var(--tx)" : rxOn ? "var(--phosphor)" : "var(--bezel)";
  document.documentElement.style.setProperty("--frame", color);

  // o nivel e o pico do medidor do Windows, nao RMS. Escala de raiz com
  // folga: fala com pico 0.2 fica perto de 60% e sobra espaco em cima
  el.meterBar.style.width = Math.min(100, Math.sqrt(s.level || 0) * 130) + "%";

  el.link.textContent = s.sim.connected ? "MSFS conectado" : "MSFS fechado";
  el.audioStat.textContent = s.audio ? "áudio ativo" : "áudio parado";
  el.pttKey.textContent = s.ptt_key ? "PTT " + s.ptt_key : "";

  renderAlert(s);
  renderAtc(s.atc, s.atc_error);
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

function renderAtc(list, error) {
  const signature = JSON.stringify(list) + (error || "");
  if (signature === atcSignature) return;
  atcSignature = signature;

  const semPosicao = list.length > 0 && list[0].distance == null;
  el.atcCount.textContent = semPosicao
    ? list.length + " · sem posição"
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
    row.className = "row";
    const where = station.distance == null ? station.role : `${station.role} · ${station.distance} NM`;
    row.innerHTML =
      `<span class="cs"><b></b><small></small></span><span class="rf"></span>`;
    row.querySelector("b").textContent = station.callsign;
    row.querySelector("small").textContent = where;
    row.querySelector(".rf").textContent = station.frequency.toFixed(3);
    row.onclick = () => send({ type: "standby", com: 1, mhz: station.frequency });
    el.atcList.append(row);
  }
}

function flashError(text) {
  el.padErr.textContent = text;
  el.padErr.hidden = false;
  setTimeout(() => (el.padErr.hidden = true), 2500);
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

/* ---------- teclado numérico ---------- */

let buf = "";
const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "limpar", "0", "ok"];

for (const k of KEYS) {
  const b = document.createElement("button");
  b.textContent = k;
  if (k.length > 1) b.className = "word";
  b.onclick = () => pressKey(k);
  el.keys.append(b);
}

function pressKey(k) {
  el.padErr.hidden = true;
  if (k === "limpar") { buf = ""; }
  else if (k === "ok") {
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
  el.padToggle.textContent = el.pad.hidden ? "digitar" : "fechar";
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

paintPad();
keepAwake();
connect();
