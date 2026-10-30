"""Servidor local do radio no celular.

Junta simulador, audio e Whazzup num estado unico e transmite pro telefone
por WebSocket. O telefone so manda eventos; toda decisao mora aqui.

Uso:
    py app/server.py
    py app/server.py --fake-sim       roda sem o MSFS aberto
    py app/server.py --list-audio     mostra quem esta tocando som, para achar o IVAO
    py app/server.py --test-ptt       confere se a tecla de PTT sai de verdade
    py app/server.py --meter          nivel de audio ao vivo, para o squelch
    py app/server.py --doctor         checa tudo de uma vez e diz o que falta
    py app/server.py --test-sim       escreve no radio do MSFS e desfaz
"""

import argparse
import asyncio
import json
import logging
import os
import re
import socket
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import audio as audio_mod
import certs
import ptt as ptt_mod
import sim as sim_mod
from whazzup import WhazzupFeed

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s  %(name)-8s  %(message)s", datefmt="%H:%M:%S"
)
log = logging.getLogger("server")

# o pacote SimConnect loga um erro por variavel a cada leitura falha, o que
# com o MSFS fechado enche o terminal cinco vezes por segundo. O diagnostico
# util sai por sim.py, que resume o estado.
logging.getLogger("SimConnect").setLevel(logging.CRITICAL)
logging.getLogger("httpx").setLevel(logging.WARNING)

DATA = Path(os.environ.get("APPDATA", Path.home())) / "COM Radio"

if getattr(sys, "frozen", False):
    # instalado em Arquivos de Programas, que nao aceita escrita: config e log
    # vao para a pasta de dados. Na primeira abertura o config vem do .exe
    # portatil antigo, se houver um ao lado, ou do padrao empacotado
    ROOT = Path(sys._MEIPASS)
    HOME = DATA
    if not (HOME / "config.json").exists():
        HOME.mkdir(parents=True, exist_ok=True)
        for origem in (Path(sys.executable).parent / "config.json", ROOT / "config.json"):
            if origem.exists():
                (HOME / "config.json").write_bytes(origem.read_bytes())
                break
else:
    # o codigo mora em app/, o config.json na raiz do repositorio
    ROOT = Path(__file__).parent
    HOME = ROOT.parent
CFG = json.loads((HOME / "config.json").read_text(encoding="utf-8"))
# um lugar so para o .exe e o 'py app/server.py': o iPhone confia em uma CA, e
# duas pastas gerariam duas CAs diferentes
CERTS = DATA / "certs"
PORT = int(CFG.get("port", 8443))
SETUP_PORT = int(CFG.get("setup_port", 8080))

MIN_FREQ, MAX_FREQ = 118.0, 136.975


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class Hub:
    """Guarda os clientes e garante que o PTT nunca fique preso."""

    def __init__(self, key: ptt_mod.PttKey, deadman_ms: int):
        self.key = key
        self.deadman = deadman_ms / 1000.0
        self.clients: set[WebSocket] = set()
        self.holder: WebSocket | None = None
        self.last_beat = 0.0

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)
        log.info("celular conectado (%d ativo(s))", len(self.clients))

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)
        if self.holder is ws:
            self.key.force_release("cliente desconectou")
            self.holder = None
        log.info("celular saiu (%d ativo(s))", len(self.clients))

    def ptt_down(self, ws: WebSocket) -> None:
        if self.holder is not None and self.holder is not ws:
            return
        self.holder = ws
        self.last_beat = time.monotonic()
        self.key.press()

    def ptt_up(self, ws: WebSocket) -> None:
        if self.holder is ws or self.holder is None:
            self.key.release()
            self.holder = None

    def beat(self, ws: WebSocket) -> None:
        if self.holder is ws:
            self.last_beat = time.monotonic()

    def check_deadman(self) -> None:
        """Se o Wi-Fi cair com o PTT apertado, solta a tecla.

        Sem isto um soluco de rede te deixa transmitindo pra sempre e trava
        a frequencia inteira para todo mundo.
        """
        if self.holder is None or not self.key.is_down:
            return
        if time.monotonic() - self.last_beat > self.deadman:
            self.key.force_release("sem heartbeat do celular")
            self.holder = None

    async def broadcast(self, payload: dict) -> None:
        if not self.clients:
            return
        text = json.dumps(payload)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


# ------------------------------------------------------------------- estado

KEY: ptt_mod.PttKey
HUB: Hub
SIM: sim_mod.SimBridge
RX: audio_mod.RxDetector | audio_mod.NullDetector
FEED: WhazzupFeed


def build(fake_sim: bool = False) -> None:
    global KEY, HUB, SIM, RX, FEED
    KEY = ptt_mod.PttKey(CFG.get("ptt_key", "leftctrl"))
    HUB = Hub(KEY, int(CFG.get("ptt_deadman_ms", 700)))
    SIM = (
        sim_mod.FakeSim(CFG.get("sim_poll_hz", 5))
        if fake_sim or not CFG.get("sim_enabled", True)
        else sim_mod.SimBridge(CFG.get("sim_poll_hz", 5))
    )
    RX = audio_mod.RxDetector(CFG) if CFG.get("audio_enabled", True) else audio_mod.NullDetector()
    FEED = WhazzupFeed(CFG)


def set_ptt_key(name: str) -> str | None:
    """Troca a tecla de PTT com o servidor rodando e salva no config.json.

    Devolve o erro para mostrar, ou None. Recusa no meio de uma transmissao:
    trocar com a tecla antiga apertada a deixaria presa.
    """
    global KEY
    if KEY.is_down or HUB.holder is not None:
        return "solte o PTT antes de trocar a tecla"
    antiga, nova = KEY, ptt_mod.PttKey(name)
    KEY = HUB.key = nova
    # o celular pode ter apertado entre a checagem e a troca
    antiga.force_release("tecla de PTT trocada")
    log.info("PTT agora na tecla '%s'", nova.name)
    erro = save_config("ptt_key", nova.name)
    return "tecla trocada, mas " + erro if erro else None


def save_config(key: str, value) -> str | None:
    """Grava uma chave no config.json. Devolve o erro para mostrar, ou None.

    Troca so o valor daquela chave, para nao reformatar o arquivo que o
    usuario edita a mao. Chave que ainda nao existe reescreve o arquivo.
    """
    CFG[key] = value
    path = HOME / "config.json"
    try:
        texto = path.read_text(encoding="utf-8")
        novo, achou = re.subn(
            r'("%s"\s*:\s*)(?:"[^"]*"|\[[^\]]*\]|[^,\s}]+)' % re.escape(key),
            lambda m: m.group(1) + json.dumps(value, ensure_ascii=False),
            texto,
            count=1,
        )
        path.write_text(
            novo if achou else json.dumps(CFG, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as exc:
        return "não consegui salvar o config.json: %s" % exc
    return None


def build_state() -> dict:
    s = SIM.snapshot()
    a = RX.snapshot()
    return {
        "type": "state",
        "sim": {
            "connected": s.get("connected", False),
            "callsign": s.get("callsign"),
            "error": s.get("error"),
            "com1": {"active": s.get("com1_active"), "standby": s.get("com1_standby")},
            "com2": {"active": s.get("com2_active"), "standby": s.get("com2_standby")},
        },
        "rx": a["rx"],
        "level": a["level"],
        "audio": a["running"],
        "audio_error": a.get("error"),
        "tx": KEY.is_down,
        "ptt_key": KEY.name,
        "atc": FEED.nearby(s.get("lat"), s.get("lon")),
        "atc_error": FEED.error,
    }


async def pump(stop: asyncio.Event) -> None:
    while not stop.is_set():
        HUB.check_deadman()
        await HUB.broadcast(build_state())
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.1)
        except asyncio.TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    SIM.start()
    RX.start()
    # de proposito sem self_test aqui: ele aperta a tecla de verdade e, com o
    # Altitude aberto, isso e uma transmissao curta na frequencia. Para testar
    # use 'py app/server.py --test-ptt' antes de entrar na rede.
    log.info("PTT na tecla '%s'", KEY.name)
    tasks = [asyncio.create_task(pump(stop))]
    if CFG.get("whazzup_enabled", True):
        tasks.append(asyncio.create_task(FEED.run(stop)))
    log.info("radio em https://%s.local:%s", certs.hostname(), PORT)
    log.info("instalar no iPhone:  http://%s:%s", lan_ip(), SETUP_PORT)
    try:
        yield
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        KEY.force_release("servidor encerrando")
        SIM.stop()
        RX.stop()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/sw.js")
async def service_worker():
    # na raiz, e nao em /static, para o escopo cobrir a pagina inteira
    return FileResponse(
        ROOT / "static" / "sw.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache"},
    )


def handle(ws: WebSocket, msg: dict) -> dict | None:
    """Trata um evento do celular. Devolve uma resposta ou None."""
    kind = msg.get("type")
    if kind == "ptt":
        HUB.ptt_down(ws) if msg.get("down") else HUB.ptt_up(ws)
    elif kind == "beat":
        HUB.beat(ws)
    elif kind == "standby":
        com = 1 if msg.get("com") != 2 else 2
        try:
            freq = float(msg.get("mhz", 0))
        except (TypeError, ValueError):
            return {"type": "error", "text": "frequencia invalida"}
        if not (MIN_FREQ <= freq <= MAX_FREQ):
            return {"type": "error", "text": "frequencia fora da faixa"}
        if not SIM.set_standby(com, freq):
            return {"type": "error", "text": "o MSFS nao aceitou a frequencia"}
    elif kind == "swap":
        if not SIM.swap(1 if msg.get("com") != 2 else 2):
            return {"type": "error", "text": "o MSFS nao aceitou a troca"}
    return None


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await HUB.connect(ws)
    try:
        await ws.send_text(json.dumps(build_state()))
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            reply = handle(ws, msg)
            if reply is not None:
                await ws.send_text(json.dumps(reply))
    except WebSocketDisconnect:
        HUB.disconnect(ws)
    except Exception as exc:
        log.warning("erro no socket: %s", exc)
        HUB.disconnect(ws)


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


# ------------------------------------------------------------------ doctor


def doctor() -> int:
    """Checa cada peca e diz exatamente o que esta faltando."""
    import httpx

    falhas = 0

    def linha(ok, titulo, detalhe=""):
        nonlocal falhas
        if not ok:
            falhas += 1
        print("  %s  %-22s %s" % ("ok  " if ok else "FALHA", titulo, detalhe))

    print("\n1. PTT")
    print("     este teste aperta a tecla de verdade. Se o Altitude estiver")
    print("     conectado, sai uma transmissao curta na frequencia.")
    try:
        key = ptt_mod.PttKey(CFG.get("ptt_key", "leftctrl"))
        ok, msg = key.self_test()
        linha(ok, "tecla %s" % key.name, msg)
        print("     confira que essa e a mesma tecla configurada no Altitude")
    except ValueError as exc:
        linha(False, "config ptt_key", str(exc))

    print("\n2. Audio")
    if not CFG.get("audio_enabled", True):
        print("  --   desligado no config.json")
    else:
        det = audio_mod.RxDetector(CFG)
        det.start()
        time.sleep(1.0)  # a primeira procura roda na thread do audio
        s = det.snapshot()
        linha(
            det.running,
            "IVAO no mixer",
            s["source"] or (det.error or "nao achado")
            + ". Rode 'py app/server.py --list-audio' com o IVAO aberto.",
        )
        det.stop()

    print("\n3. Whazzup da IVAO")
    try:
        r = httpx.get(whazzup_url(), timeout=15.0)
        r.raise_for_status()
        atcs = WhazzupFeed._parse(r.json())
        linha(bool(atcs), "api.ivao.aero", "%d controladores online" % len(atcs))
    except Exception as exc:
        linha(False, "api.ivao.aero", str(exc))

    print("\n4. MSFS via SimConnect")
    if not CFG.get("sim_enabled", True):
        print("  --   desligado no config.json")
    else:
        bridge = sim_mod.SimBridge(CFG.get("sim_poll_hz", 5))
        bridge.start()
        for _ in range(40):
            if bridge.connected:
                break
            time.sleep(0.25)
        if bridge.connected:
            time.sleep(1.0)
            s = bridge.snapshot()
            linha(True, "conexao", "callsign %s" % (s.get("callsign") or "?"))
            linha(
                s.get("com1_active") is not None,
                "leitura de COM1",
                "ativa %s / standby %s" % (s.get("com1_active"), s.get("com1_standby")),
            )
            linha(
                s.get("lat") is not None,
                "posicao do aviao",
                "%s, %s" % (s.get("lat"), s.get("lon")),
            )
        else:
            linha(False, "conexao", bridge.error or "MSFS nao esta aberto num voo")
        bridge.stop()
        print("     a escrita de frequencia se testa com 'py app/server.py --test-sim'")

    print("\n5. Rede")
    print("     instalar no iPhone:  http://%s:%s" % (lan_ip(), SETUP_PORT))
    print("     radio:               https://%s.local:%s" % (certs.hostname(), PORT))
    print("     o iPhone precisa estar no mesmo Wi-Fi, e o firewall do Windows")
    print("     precisa liberar o programa na rede privada.")

    print("\n%s\n" % ("tudo pronto" if falhas == 0 else "%d item(ns) para resolver" % falhas))
    return 1 if falhas else 0


def test_sim() -> int:
    """Escreve no radio do MSFS e confere se pegou, depois desfaz.

    E o unico pedaco que nao da para verificar sem o simulador aberto: os
    nomes dos eventos do SimConnect mudam entre versoes do MSFS. Mexe so na
    standby e no swap, nunca em outra coisa, e devolve tudo como estava.
    """
    bridge = sim_mod.SimBridge(CFG.get("sim_poll_hz", 5))
    bridge.start()
    for _ in range(40):
        if bridge.connected:
            break
        time.sleep(0.25)
    if not bridge.connected:
        print("MSFS nao esta respondendo. Carregue um voo ate estar no cockpit.")
        bridge.stop()
        return 1

    inicio = bridge.snapshot()
    ativa0, standby0 = inicio.get("com1_active"), inicio.get("com1_standby")
    print("COM1 agora: ativa %s / standby %s" % (ativa0, standby0))
    if standby0 is None:
        print("nao consegui ler a standby de COM1, nao da para testar a escrita.")
        bridge.stop()
        return 1

    falhas = 0

    def espera(chave, alvo, segundos=3.0):
        limite = time.monotonic() + segundos
        while time.monotonic() < limite:
            valor = bridge.snapshot().get(chave)
            if valor is not None and abs(valor - alvo) < 0.0006:
                return True
            time.sleep(0.2)
        return False

    alvo = 124.425 if abs(standby0 - 124.425) > 0.001 else 132.075
    print("\nescrevendo %.3f na standby..." % alvo)
    if not bridge.set_standby(1, alvo):
        print("  FALHA  o evento COM_STBY_RADIO_SET_HZ nao foi aceito")
        falhas += 1
    elif espera("com1_standby", alvo):
        print("  ok     a standby mudou para %.3f" % alvo)
    else:
        print("  FALHA  o evento saiu mas a standby nao mudou.")
        print("         Confira o master avionics e a energia do aviao.")
        falhas += 1

    print("\ntestando o swap...")
    antes = bridge.snapshot()
    if not bridge.swap(1):
        print("  FALHA  o evento COM1_RADIO_SWAP nao foi aceito")
        falhas += 1
    elif espera("com1_active", antes.get("com1_standby") or alvo):
        print("  ok     a ativa recebeu a standby")
        bridge.swap(1)
        time.sleep(1.0)
    else:
        print("  FALHA  o swap saiu mas nada trocou")
        falhas += 1

    print("\ndevolvendo a standby original (%.3f)..." % standby0)
    bridge.set_standby(1, standby0)
    time.sleep(1.5)
    fim = bridge.snapshot()
    print("COM1 no fim: ativa %s / standby %s" % (fim.get("com1_active"), fim.get("com1_standby")))
    bridge.stop()

    print("\n%s\n" % ("escrita funcionando" if not falhas else "%d falha(s)" % falhas))
    return 1 if falhas else 0


def make_server() -> uvicorn.Server:
    """Sobe a pagina de instalacao e devolve o servidor HTTPS pronto.

    Quem chama decide onde rodar: no terminal roda na thread principal, na
    janela do .exe roda numa thread e para com should_exit.
    """
    crt, key = certs.ensure(CERTS, lan_ip())
    certs.serve_setup(SETUP_PORT, ROOT / "static" / "setup.html", CERTS / "ca.crt", PORT)
    return uvicorn.Server(
        uvicorn.Config(
            app, host="0.0.0.0", port=PORT, log_level="warning",
            ssl_certfile=str(crt), ssl_keyfile=str(key),
        )
    )


def whazzup_url() -> str:
    from whazzup import URL

    return URL


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-audio", action="store_true")
    parser.add_argument("--fake-sim", action="store_true")
    parser.add_argument("--test-ptt", action="store_true")
    parser.add_argument("--meter", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--test-sim", action="store_true")
    args = parser.parse_args()

    if args.list_audio:
        audio_mod.list_sessions(CFG)
        raise SystemExit(0)

    if args.test_ptt:
        key = ptt_mod.PttKey(CFG.get("ptt_key", "leftctrl"))
        ok, msg = key.self_test()
        print(("ok: " if ok else "falhou: ") + msg)
        raise SystemExit(0 if ok else 1)

    if args.meter:
        audio_mod.meter(CFG)
        raise SystemExit(0)

    if args.doctor:
        raise SystemExit(doctor())

    if args.test_sim:
        raise SystemExit(test_sim())

    try:
        build(fake_sim=args.fake_sim)
    except ValueError as exc:
        print("config.json: %s" % exc)
        raise SystemExit(2) from None

    make_server().run()
else:
    build(fake_sim=False)
