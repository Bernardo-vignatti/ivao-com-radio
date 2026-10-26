"""Detecta se alguem esta transmitindo na frequencia.

O Altitude nao expoe nenhuma API, entao a unica forma de saber que chegou
audio e medir. O Windows ja mede o volume de cada programa separado (as
barrinhas do Mixer de Volume), e este modulo le so a do IVAO.

Nao captura audio nenhum: o IVAO toca direto no headset, sem VB-Cable, sem
roteamento e sem passthrough. Se este servidor cair, voce continua ouvindo.

Captura de audio por processo so existe do Windows 11 em diante; o medidor
por sessao existe no 10, e para o indicador de RX ele basta.
"""

import logging
import threading
import time
from pathlib import Path

import comtypes
import psutil
from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
from pycaw.constants import CLSID_MMDeviceEnumerator
from pycaw.pycaw import IAudioMeterInformation, IAudioSessionControl2, IAudioSessionManager2

log = logging.getLogger("audio")

E_RENDER, DEVICE_STATE_ACTIVE = 0, 1
POLL_S = 0.02   # 50 Hz: o pico do Windows cobre o intervalo inteiro
SCAN_S = 2.0    # procura o IVAO de novo, ele pode abrir depois do servidor


def sessions() -> list[tuple[str, object]]:
    """(caminho do exe, medidor) de toda sessao, em toda saida ativa.

    Todas as saidas e nao so a padrao: o IVAO pode estar mandando para um
    dispositivo diferente do resto do Windows.
    """
    enum = comtypes.CoCreateInstance(
        CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER
    )
    devices = enum.EnumAudioEndpoints(E_RENDER, DEVICE_STATE_ACTIVE)
    found = []
    for i in range(devices.GetCount()):
        mgr = devices.Item(i).Activate(IAudioSessionManager2._iid_, comtypes.CLSCTX_ALL, None)
        lista = mgr.QueryInterface(IAudioSessionManager2).GetSessionEnumerator()
        for j in range(lista.GetCount()):
            ctl = lista.GetSession(j)
            pid = ctl.QueryInterface(IAudioSessionControl2).GetProcessId()
            if pid == 0:
                continue  # sons do sistema
            try:
                exe = psutil.Process(pid).exe()
            except (psutil.Error, OSError):
                continue
            found.append((exe, ctl.QueryInterface(IAudioMeterInformation)))
    return found


def matches(exe: str, needles: list[str]) -> bool:
    # o caminho inteiro, nao so o nome: um processo auxiliar com nome
    # generico ainda mora dentro da pasta do IVAO
    low = exe.lower()
    return any(n in low for n in needles)


class RxDetector:
    def __init__(self, cfg: dict):
        self.open_th = float(cfg.get("squelch_open", 0.03))
        self.close_th = float(cfg.get("squelch_close", 0.01))
        self.hang = float(cfg.get("squelch_hang_ms", 350)) / 1000.0
        self.needles = [n.lower() for n in cfg.get("audio_process", ["ivao", "altitude"])]

        self.rx = False
        self.level = 0.0
        self.peak = 0.0
        self.running = False      # achou o IVAO e esta medindo
        self.source: str | None = None
        self.error: str | None = None
        self._last_loud = 0.0
        self._lock = threading.Lock()
        self._parar = threading.Event()

    def _measure(self, valor: float) -> None:
        now = time.monotonic()
        with self._lock:
            self.level = valor
            self.peak = max(self.peak * 0.92, valor)
            if valor > self.open_th:
                self._last_loud = now
                self.rx = True
            elif self.rx and valor < self.close_th and now - self._last_loud > self.hang:
                self.rx = False

    def _scan(self) -> list:
        try:
            meus = [(exe, m) for exe, m in sessions() if matches(exe, self.needles)]
        except Exception as exc:
            self.error = "não consegui ler o mixer do Windows: %s" % exc
            return []
        nome = Path(meus[0][0]).name if meus else None
        if nome != self.source:
            log.info("audio: %s", ("medindo " + nome) if nome else "IVAO sem som aberto")
        self.source = nome
        self.error = None if meus else "IVAO não encontrado no som do Windows: abra o IVAO para ter RX"
        return [m for _, m in meus]

    def _run(self) -> None:
        comtypes.CoInitialize()  # COM por thread, senao o mixer nao abre
        medidores, scan_at = [], 0.0
        try:
            while not self._parar.is_set():
                if time.monotonic() - scan_at > SCAN_S:
                    medidores, scan_at = self._scan(), time.monotonic()
                    self.running = bool(medidores)
                valor = 0.0
                try:
                    for m in medidores:
                        valor = max(valor, m.GetPeakValue())
                except Exception:
                    # o IVAO fechou ou o dispositivo sumiu: procura de novo ja
                    medidores, scan_at = [], 0.0
                self._measure(valor)
                self._parar.wait(POLL_S)
        finally:
            self.running = False
            comtypes.CoUninitialize()

    def start(self) -> None:
        self._parar.clear()
        threading.Thread(target=self._run, daemon=True, name="audio").start()

    def stop(self) -> None:
        self._parar.set()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "rx": self.rx,
                "level": round(self.level, 5),
                "peak": round(self.peak, 5),
                "running": self.running,
                "source": self.source,
                "error": self.error,
            }


class NullDetector:
    running = False
    error = None

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def snapshot(self) -> dict:
        return {"rx": False, "level": 0.0, "peak": 0.0, "running": False,
                "source": None, "error": None}


def list_sessions(cfg: dict, seconds: float = 5.0) -> None:
    """Mostra quem esta tocando som e quanto, para achar o processo do IVAO."""
    needles = [n.lower() for n in cfg.get("audio_process", ["ivao", "altitude"])]
    comtypes.CoInitialize()
    try:
        achados = sessions()
        if not achados:
            print("nenhum programa com som aberto no Windows.")
            return
        print("medindo por %.0f s; fale ou espere alguem transmitir no IVAO...\n" % seconds)
        picos = [0.0] * len(achados)
        fim = time.monotonic() + seconds
        while time.monotonic() < fim:
            for i, (_, m) in enumerate(achados):
                try:
                    picos[i] = max(picos[i], m.GetPeakValue())
                except Exception:
                    pass
            time.sleep(POLL_S)
        for (exe, _), pico in zip(achados, picos):
            marca = "IVAO" if matches(exe, needles) else "    "
            print("  %s  pico %.4f  %s" % (marca, pico, exe))
        print(
            "\nAs linhas marcadas IVAO sao as que o servidor mede. Se a voz do IVAO"
            "\nsai de outro processo, ponha um pedaco do caminho dele em"
            "\n'audio_process' no config.json."
        )
    finally:
        comtypes.CoUninitialize()


def meter(cfg: dict) -> None:
    """Mostra o nivel ao vivo para calibrar squelch_open e squelch_close.

    Espere alguem transmitir e olhe o pico da fala. Ponha squelch_open um
    pouco abaixo dele e squelch_close mais ou menos na metade.
    """
    det = RxDetector(cfg)
    det.start()
    print("abre em %.4f, fecha em %.4f. Ctrl+C para sair." % (det.open_th, det.close_th))
    inicio = time.monotonic()
    giro = "|/-\\"
    quadro = 0
    try:
        while True:
            s = det.snapshot()
            barra = "#" * min(40, int(s["level"] * 100))
            # o giro e o relogio existem para a linha nao parecer travada
            # quando o nivel fica em zero: sem eles, zero e crash sao iguais
            aviso = s["source"] or s["error"] or "procurando o IVAO..."
            print(
                "\r%s %4.0fs  nivel %.4f  pico %.4f  %-2s |%-40s| %s"
                % (giro[quadro % 4], time.monotonic() - inicio, s["level"], s["peak"],
                   "RX" if s["rx"] else "", barra, aviso[:40]),
                end="", flush=True,
            )
            quadro += 1
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        print()
        det.stop()


if __name__ == "__main__":
    # o squelch abre na fala, segura nas pausas curtas e fecha no silencio
    det = RxDetector({"squelch_open": 0.03, "squelch_close": 0.01, "squelch_hang_ms": 100})
    det._measure(0.2)
    assert det.rx, "nao abriu com fala"
    det._measure(0.02)
    assert det.rx, "fechou entre os limites"
    det._measure(0.0)
    assert det.rx, "fechou antes do hang"
    time.sleep(0.12)
    det._measure(0.0)
    assert not det.rx, "nao fechou depois do hang"
    assert matches(r"C:\Program Files\IVAO\Altitude\voice.exe", ["ivao"])
    assert not matches(r"C:\Windows\explorer.exe", ["ivao", "altitude"])
    print("ok")
