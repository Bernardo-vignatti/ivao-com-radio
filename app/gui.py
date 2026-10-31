"""Janela do COM Radio no PC. E o que vira o .exe.

Roda o mesmo servidor do terminal numa thread e mostra o painel numa janela
pywebview, com o HTML de app/desktop/. Fechar a janela esconde o app na
bandeja e o servidor continua. Sair pela bandeja desliga pelo caminho normal
do uvicorn, que passa pelo lifespan e solta a tecla de PTT.

A pagina fala com o Python pela ponte do pywebview (Api), nunca pela rede:
as configuracoes nao ficam acessiveis pelo Wi-Fi, so o radio.

Os modos de diagnostico (--doctor, --meter...) continuam em 'py app/server.py'.
Aqui: --tray abre escondido na bandeja (o que o Iniciar com o Windows usa),
--fake-sim roda sem o MSFS, --debug abre as ferramentas do navegador.
"""

import ctypes
import hashlib
import os
import subprocess
import sys
import tempfile
import threading
import time
import winreg
from pathlib import Path

VERSION = "2.1.0"  # o instalador tem a sua copia em installer.iss
APP = "COM Radio"
FROZEN = getattr(sys, "frozen", False)
DATA = Path(os.environ.get("APPDATA", Path.home())) / APP
HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
ICON = HERE / "assets" / "icon.ico" if FROZEN else HERE.parent / "assets" / "icon.ico"

CAPTURE_S = 10  # quanto tempo o Mudar espera a tecla
# de onde vem a atualizacao. Pre-releases contam: quem testa a versao nova
# tambem recebe a seguinte
RELEASES = "https://api.github.com/repos/Bernardo-vignatti/ivao-com-radio/releases"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

if FROZEN:
    # o .exe nao tem console: sem isto o log some e o uvicorn quebra tentando
    # perguntar se o stdout e um terminal. Recomeca a cada abertura
    DATA.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(DATA / "com-radio.log", "w", encoding="utf-8", buffering=1)

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateMutexW.restype = ctypes.c_void_p
_k32.CreateEventW.restype = ctypes.c_void_p
_k32.OpenEventW.restype = ctypes.c_void_p
_k32.SetEvent.argtypes = [ctypes.c_void_p]
_k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]


def fail(text: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, APP, 0x10)
    raise SystemExit(1)


# uma instancia so. Abrir de novo, com o app escondido na bandeja, so pede
# para a janela que ja existe aparecer. O instalador usa o mesmo mutex para
# saber que o app esta aberto antes de atualizar ou desinstalar
ctypes.set_last_error(0)
_MUTEX = _k32.CreateMutexW(None, False, "COMRadio.Instance")
if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
    outro = _k32.OpenEventW(0x0002, False, "COMRadio.Show")
    if outro:
        _k32.SetEvent(outro)
    raise SystemExit(0)
SHOW_EVENT = _k32.CreateEventW(None, False, False, "COMRadio.Show")

try:
    import httpx
    import pystray
    import qrcode
    import webview
    from PIL import Image, ImageDraw

    import server
except Exception as exc:  # config.json quebrado, tecla invalida, etc.
    fail("Não deu para iniciar:\n\n%s" % exc)

if "--fake-sim" in sys.argv:
    server.build(fake_sim=True)

try:
    SRV = server.make_server()
except OSError:
    fail(
        "As portas %s ou %s já estão em uso por outro programa.\n\n"
        "Feche o programa que usa essas portas, ou troque 'port' e "
        "'setup_port' no config.json." % (server.SETUP_PORT, server.PORT)
    )

THREAD = threading.Thread(target=SRV.run, daemon=True, name="uvicorn")
THREAD.start()

LAN = server.lan_ip()
SETUP_URL = "http://%s:%s" % (LAN, server.SETUP_PORT)
RADIO_URL = "https://%s.local:%s" % (server.certs.hostname(), server.PORT)

# o que a pagina pode mudar, com os limites. Fora daqui nada e gravado
NUMBERS = {
    "squelch_open": (float, 0.001, 0.5),
    "squelch_close": (float, 0.0, 0.5),
    "squelch_hang_ms": (int, 0, 3000),
    "whazzup_radius_nm": (int, 10, 3000),
    "whazzup_max_stations": (int, 1, 50),
    # a IVAO pede no minimo 15 s entre consultas da Whazzup
    "whazzup_interval_s": (int, 15, 600),
}
SWITCHES = {"audio_enabled", "sim_enabled", "whazzup_enabled", "tray_on_close"}
RESTART = {"audio_enabled", "sim_enabled", "whazzup_enabled"}


def autostart() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP)
        return True
    except OSError:
        return False


def qr_svg(url: str) -> str:
    qr = qrcode.QRCode(border=2)
    qr.add_data(url)
    qr.make(fit=True)
    m = qr.get_matrix()
    cells = "".join(
        "M%d %dh1v1h-1z" % (x, y) for y, row in enumerate(m) for x, dark in enumerate(row) if dark
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" shape-rendering="crispEdges">'
        '<rect width="100%%" height="100%%" fill="#fff"/><path d="%s" fill="#000"/></svg>'
        % (len(m), len(m), cells)
    )


def version_tuple(tag: str) -> tuple:
    try:
        return tuple(int(p) for p in tag.lstrip("vV").split("-")[0].split("."))
    except ValueError:
        return ()


def find_update() -> dict | None:
    """A release mais nova que esta, com o instalador anexado, ou None."""
    r = httpx.get(RELEASES, timeout=10.0, follow_redirects=True,
                  headers={"Accept": "application/vnd.github+json"})
    r.raise_for_status()
    melhor = None
    for rel in r.json():
        v = version_tuple(rel.get("tag_name", ""))
        if rel.get("draft") or not v or v <= version_tuple(VERSION):
            continue
        setup = next((a for a in rel.get("assets", [])
                      if a["name"].startswith("COM-Radio-Setup-") and a["name"].endswith(".exe")), None)
        if setup and (melhor is None or v > melhor["_v"]):
            melhor = {
                "_v": v,
                "version": rel["tag_name"].lstrip("vV"),
                "page": rel.get("html_url"),
                "url": setup["browser_download_url"],
                "name": setup["name"],
                "size": setup.get("size", 0),
                # o GitHub publica o sha256 de cada anexo desde 2025
                "sha256": (setup.get("digest") or "").removeprefix("sha256:") or None,
            }
    if melhor:
        melhor.pop("_v")
    return melhor


class Api:
    """O que a pagina do PC pode chamar. Nomes com _ nao sao expostos."""

    def __init__(self):
        self._capture_until: float | None = None
        self._notice: tuple[str, str, float] | None = None
        self._update: dict = {"state": "idle"}

    def info(self) -> dict:
        return {
            "version": VERSION,
            "frozen": FROZEN,
            "setup_url": SETUP_URL,
            "radio_url": RADIO_URL,
            "qr": qr_svg(SETUP_URL),
            "data_dir": str(server.HOME),
            "deadman_ms": int(server.CFG.get("ptt_deadman_ms", 700)),
            "config": self._config(),
        }

    @staticmethod
    def _config() -> dict:
        cfg = server.CFG
        out = {k: cfg.get(k) for k in NUMBERS}
        out.update({k: bool(cfg.get(k, True)) for k in SWITCHES})
        out["audio_process"] = cfg.get("audio_process", ["ivao", "altitude"])
        out["autostart"] = autostart()
        out["port"], out["setup_port"] = server.PORT, server.SETUP_PORT
        return out

    def state(self) -> dict:
        s = server.SIM.snapshot()
        a = server.RX.snapshot()
        rx = server.RX
        agora = time.monotonic()
        notice = None
        if self._notice and agora < self._notice[2]:
            notice = {"text": self._notice[0], "tone": self._notice[1]}
        return {
            "server": {"alive": THREAD.is_alive(), "started": bool(SRV.started)},
            "sim": {
                "connected": s.get("connected", False),
                "callsign": s.get("callsign"),
                "error": s.get("error"),
                "active": s.get("com1_active"),
                "standby": s.get("com1_standby"),
            },
            "audio": dict(
                a,
                enabled=bool(server.CFG.get("audio_enabled", True)),
                open=getattr(rx, "open_th", None),
                close=getattr(rx, "close_th", None),
            ),
            "clients": len(server.HUB.clients),
            "ptt": {
                "key": server.KEY.name,
                "down": server.KEY.is_down,
                "held": server.HUB.holder is not None,
                "capture": max(0, round(self._capture_until - agora)) if self._capture_until else None,
                "notice": notice,
            },
            "atc": server.FEED.nearby(s.get("lat"), s.get("lon")),
            "atc_error": server.FEED.error,
        }

    def _say(self, text: str, tone: str, seconds: float) -> None:
        self._notice = (text, tone, time.monotonic() + seconds)

    def capture_key(self) -> None:
        # definir a tecla apertando ela, em vez de achar o nome e editar o
        # config.json. Recusa com PTT apertado: a tecla antiga ficaria presa
        if self._capture_until:
            return
        if server.KEY.is_down or server.HUB.holder is not None:
            self._say("solte o PTT antes de trocar", "amber", 3)
            return
        self._capture_until = time.monotonic() + CAPTURE_S

        def run():
            nome = server.ptt_mod.capture(CAPTURE_S)
            self._capture_until = None
            if not nome:
                self._say("nenhuma tecla apertada; nada mudou", "amber", 4)
                return
            erro = server.set_ptt_key(nome)
            self._say(erro, "red", 6) if erro else self._say("tecla %s salva" % nome, "green", 3)

        threading.Thread(target=run, daemon=True, name="captura").start()

    def test_ptt(self) -> dict:
        # aperta a tecla de verdade: com o Altitude conectado, isso transmite
        if self._capture_until or server.KEY.is_down or server.HUB.holder is not None:
            return {"ok": False, "text": "o PTT está em uso agora; tente de novo"}
        ok, msg = server.KEY.self_test()
        return {"ok": ok, "text": msg}

    def set_config(self, key: str, value) -> dict:
        try:
            if key in NUMBERS:
                kind, lo, hi = NUMBERS[key]
                value = kind(value)
                if not lo <= value <= hi:
                    return {"error": "valor fora do limite (%s a %s)" % (lo, hi)}
            elif key in SWITCHES:
                value = bool(value)
            elif key == "audio_process":
                value = [str(v).strip().lower() for v in value if str(v).strip()]
                if not value:
                    return {"error": "informe ao menos um pedaço do caminho do IVAO"}
            elif key == "autostart":
                return self._set_autostart(bool(value))
            else:
                return {"error": "configuração desconhecida"}
        except (TypeError, ValueError):
            return {"error": "valor inválido"}

        cfg = server.CFG
        if key == "squelch_open" and value <= float(cfg.get("squelch_close", 0.01)):
            return {"error": "o limite de abrir tem que ficar acima do de fechar"}
        if key == "squelch_close" and value >= float(cfg.get("squelch_open", 0.03)):
            return {"error": "o limite de fechar tem que ficar abaixo do de abrir"}

        erro = server.save_config(key, value)
        # o que da para aplicar sem reabrir entra na hora
        rx, feed = server.RX, server.FEED
        live = {
            "squelch_open": lambda: setattr(rx, "open_th", value),
            "squelch_close": lambda: setattr(rx, "close_th", value),
            "squelch_hang_ms": lambda: setattr(rx, "hang", value / 1000.0),
            "audio_process": lambda: setattr(rx, "needles", value),
            "whazzup_radius_nm": lambda: setattr(feed, "radius", float(value)),
            "whazzup_max_stations": lambda: setattr(feed, "limit", value),
            "whazzup_interval_s": lambda: setattr(feed, "interval", float(value)),
        }
        if key in live:
            live[key]()
        return {"error": erro, "restart": key in RESTART, "value": value}

    @staticmethod
    def _set_autostart(on: bool) -> dict:
        if not FROZEN:
            return {"error": "só funciona no COM Radio instalado"}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                if on:
                    winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, '"%s" --tray' % sys.executable)
                else:
                    try:
                        winreg.DeleteValue(k, APP)
                    except FileNotFoundError:
                        pass
        except OSError as exc:
            return {"error": "não consegui mudar a inicialização: %s" % exc}
        return {"error": None, "value": on}

    def scan_audio(self) -> list[dict]:
        return server.audio_mod.measure_sessions(server.CFG.get("audio_process", []), 4.0)

    # ---------------------------------------------------------- atualizacao

    def update_status(self) -> dict:
        return {k: v for k, v in self._update.items() if k not in ("url", "sha256")}

    def check_update(self) -> None:
        if self._update["state"] in ("checking", "downloading", "installing"):
            return
        self._update = {"state": "checking"}

        def run():
            try:
                novo = find_update()
            except Exception as exc:
                print("atualizacao: %s" % exc)
                self._update = {"state": "error", "error": "não consegui falar com o GitHub"}
                return
            self._update = dict(novo, state="available") if novo else {"state": "current"}

        threading.Thread(target=run, daemon=True, name="atualizacao").start()

    def install_update(self) -> dict:
        u = self._update
        if u["state"] != "available":
            return {"error": "nenhuma atualização disponível"}
        if not FROZEN:
            return {"error": "rodando pelo código: atualize com git pull"}
        # o app fecha para instalar, e fechar com o PTT apertado cortaria a
        # transmissao no meio. O lifespan soltaria a tecla, mas melhor esperar
        if server.KEY.is_down or server.HUB.holder is not None:
            return {"error": "solte o PTT antes de atualizar"}
        self._update = dict(u, state="downloading", done=0)

        def run():
            destino = Path(tempfile.gettempdir()) / u["name"]
            try:
                h = hashlib.sha256()
                with httpx.stream("GET", u["url"], timeout=30.0, follow_redirects=True) as r,                         open(destino, "wb") as f:
                    r.raise_for_status()
                    for bloco in r.iter_bytes(1 << 16):
                        f.write(bloco)
                        h.update(bloco)
                        self._update["done"] = self._update.get("done", 0) + len(bloco)
                if u.get("sha256") and h.hexdigest() != u["sha256"].lower():
                    raise ValueError("o arquivo baixado não confere com o do GitHub")
            except Exception as exc:
                print("atualizacao: %s" % exc)
                destino.unlink(missing_ok=True)
                self._update = dict(u, state="available", error="o download falhou: %s" % exc)
                return
            self._update = dict(u, state="installing")
            # o instalador recusa rodar com o app aberto (AppMutex), entao ele
            # espera uns segundos o app sair. /SILENT so mostra o progresso, e
            # o instalador reabre o app no fim
            subprocess.Popen(
                'cmd /c ping -n 4 127.0.0.1 >nul & start "" "%s" /SILENT /NORESTART' % destino,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            quit_app()

        threading.Thread(target=run, daemon=True, name="atualizacao").start()
        return {"error": None}

    def open_data(self) -> None:
        os.startfile(server.HOME)

    def quit(self) -> None:
        quit_app()


# ------------------------------------------------------------------ bandeja

OFF, GREEN, RED = "#5A666B", "#62E39B", "#FF4B2B"


def tray_image(color: str) -> "Image.Image":
    img = Image.open(ICON).convert("RGBA").resize((64, 64))
    draw = ImageDraw.Draw(img)
    draw.ellipse((36, 36, 63, 63), fill=color, outline="#0A0D0E", width=4)
    return img


IMAGES = {c: tray_image(c) for c in (OFF, GREEN, RED)}
QUITTING = False
HINTED = False


def show_window() -> None:
    WINDOW.show()
    WINDOW.restore()


def quit_app() -> None:
    global QUITTING
    QUITTING = True
    WINDOW.destroy()


def on_closing():
    global HINTED
    if QUITTING or not server.CFG.get("tray_on_close", True):
        return True
    threading.Thread(target=WINDOW.hide, daemon=True).start()
    if not HINTED:
        HINTED = True
        TRAY.notify("O COM Radio continua rodando aqui. Para fechar de vez, use Sair.", APP)
    return False


def on_shown(window) -> None:
    # barra de titulo escura do Windows, para combinar com o painel. Sem o
    # SetWindowPos com FRAMECHANGED ela so escurece no proximo redesenho
    try:
        hwnd = ctypes.c_void_p(window.native.Handle.ToInt64())
        on = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)
        ctypes.windll.user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x27)
    except Exception as exc:
        print("barra escura: %s" % exc)


def watch() -> None:
    """Cor e dica da bandeja, e o pedido de outra instancia para aparecer."""
    ultimo = None
    while not QUITTING:
        if _k32.WaitForSingleObject(SHOW_EVENT, 250) == 0:
            show_window()
        n = len(server.HUB.clients)
        cor = RED if server.KEY.is_down else GREEN if n else OFF
        partes = [APP]
        partes.append("TRANSMITINDO" if server.KEY.is_down else
                      ("iPhone conectado" if n else "aguardando o iPhone"))
        partes.append("MSFS conectado" if server.SIM.connected else "MSFS fechado")
        dica = " · ".join(partes)
        if (cor, dica) != ultimo:
            TRAY.icon, TRAY.title = IMAGES[cor], dica
            ultimo = (cor, dica)


TRAY = pystray.Icon(
    "COMRadio",
    IMAGES[OFF],
    APP,
    menu=pystray.Menu(
        pystray.MenuItem("Abrir o COM Radio", lambda: show_window(), default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sair", lambda: quit_app()),
    ),
)

API = Api()
WINDOW = webview.create_window(
    APP,
    url=str(HERE / "desktop" / "index.html"),
    js_api=API,
    width=1180,
    height=760,
    min_size=(980, 660),
    background_color="#0B0E10",
    hidden="--tray" in sys.argv,
)
WINDOW.events.closing += on_closing
WINDOW.events.shown += on_shown


if __name__ == "__main__":
    threading.Thread(target=TRAY.run, daemon=True, name="bandeja").start()
    threading.Thread(target=watch, daemon=True, name="vigia").start()
    if FROZEN:
        API.check_update()
    webview.start(gui="edgechromium", debug="--debug" in sys.argv)
    # a janela fechou de vez: o mesmo desligamento do Ctrl+C. O lifespan
    # solta a tecla e fecha simulador e audio antes de o processo sair
    QUITTING = True
    TRAY.stop()
    SRV.should_exit = True
    THREAD.join(timeout=5)
