"""Ponte com o MSFS2020 via SimConnect.

Le frequencia ativa e standby de COM1 e COM2 mais a posicao do aviao, e
escreve standby e swap. O Altitude segue o radio do simulador, entao mudar
aqui muda na rede da IVAO. Nunca tente escrever no Altitude direto.

Se o simulador nao estiver aberto o modulo entra em modo offline e devolve
valores neutros, sem derrubar o servidor.

Sobre o pacote Python-SimConnect: o AircraftRequests guarda um unico objeto
Request por nome de variavel e troca o indice nele a cada chamada. Pedir
COM1 e COM2 alternadamente forcaria um redefine a cada leitura e devolveria
valor do indice errado. Por isso montamos os Request na mao, um por
variavel ja com o indice fixo, e reusamos os mesmos objetos.
"""

import ctypes
import logging
import math
import threading
import time

log = logging.getLogger("sim")

# nome e unidade exatos do SimConnect, como o pacote espera
VARS = {
    "com1_active": (b"COM ACTIVE FREQUENCY:1", b"MHz"),
    "com1_standby": (b"COM STANDBY FREQUENCY:1", b"MHz"),
    "com2_active": (b"COM ACTIVE FREQUENCY:2", b"MHz"),
    "com2_standby": (b"COM STANDBY FREQUENCY:2", b"MHz"),
    "lat": (b"PLANE LATITUDE", b"Degrees"),
    "lon": (b"PLANE LONGITUDE", b"Degrees"),
    "callsign": (b"ATC ID", b"String"),
}

FREQ_KEYS = ("com1_active", "com1_standby", "com2_active", "com2_standby")
MIN_FREQ, MAX_FREQ = 118.0, 136.995

# quanto tempo esperar a standby aparecer com o valor novo antes de reclamar
WRITE_TIMEOUT = 2.0

# o SimConnect.dll abre a conexao mesmo com o MSFS fechado e so depois falha
# em toda definicao de dado. "conectado" aqui significa dado chegando, nao
# handle aberto: senao o celular anuncia MSFS conectado com o jogo fechado.
DATA_GRACE = 4.0
RELINK_AFTER = 12.0


class SimBridge:
    def __init__(self, poll_hz: float = 5.0):
        self.period = 1.0 / max(poll_hz, 1.0)
        self.connected = False
        self.error: str | None = None
        self.state = {
            "com1_active": None,
            "com1_standby": None,
            "com2_active": None,
            "com2_standby": None,
            "lat": None,
            "lon": None,
            "callsign": None,
        }
        self._sm = None
        self._req: dict = {}
        self._events: dict = {}
        self._pending: tuple[str, float, float] | None = None
        self._linked = False
        self._last_good = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    # ------------------------------------------------------------------ ciclo

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="simconnect")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        sm = self._sm
        self._sm = None
        if sm is not None:
            try:
                sm.exit()
            except Exception:
                pass

    def _connect(self) -> bool:
        try:
            from SimConnect import Request, SimConnect
        except ImportError:
            self.error = "pacote SimConnect nao instalado (pip install SimConnect)"
            log.error("%s", self.error)
            self._stop.wait(30.0)
            return False
        try:
            sm = SimConnect()
            # _time e o cache em ms: no maximo uma ida ao sim por variavel
            # dentro desse intervalo, mesmo que a gente peca mais vezes
            period_ms = int(self.period * 1000 * 0.8)
            req = {}
            for key, deff in VARS.items():
                req[key] = Request(deff, sm, _time=period_ms, _attemps=6)
            self._sm = sm
            self._req = req
            self._events = {}
            self._linked = True
            self._last_good = time.monotonic()
            log.debug("handle do SimConnect aberto, esperando dado")
            return True
        except Exception as exc:
            log.debug("MSFS ainda nao disponivel: %s", exc)
            self._drop(None)
            return False

    def _drop(self, reason: str | None) -> None:
        sm = self._sm
        self._sm = None
        self._req = {}
        self._events = {}
        self._linked = False
        self.connected = False
        self.error = reason
        if sm is not None:
            try:
                sm.exit()
            except Exception:
                pass

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self._linked:
                if not self._connect():
                    self._stop.wait(3.0)
                    continue
            try:
                self._poll_once()
            except Exception as exc:
                log.warning("perdeu o MSFS: %s", exc)
                self._drop("conexao com o MSFS caiu: %s" % exc)
            self._stop.wait(self.period)

    def _grade(self, snapshot: dict) -> None:
        """Decide se o que chegou conta como sim vivo.

        O handle abre com o jogo fechado, entao a prova de vida e ter lido
        alguma variavel de verdade. Sem dado por tempo demais, derruba e
        reabre em vez de ficar mostrando conectado para sempre.
        """
        vivo = snapshot.get("com1_active") is not None or snapshot.get("lat") is not None
        agora = time.monotonic()
        if vivo:
            self._last_good = agora
            if not self.connected:
                log.info("MSFS respondendo")
            self.connected = True
            self.error = None
            return
        parado = agora - self._last_good
        if parado > RELINK_AFTER:
            log.info("MSFS sem responder, reabrindo a conexao")
            self._drop("o MSFS nao esta aberto num voo")
        elif parado > DATA_GRACE and self.connected:
            self.connected = False
            self.error = "o MSFS parou de responder"

    def _poll_once(self) -> None:
        snapshot = {}
        for key in FREQ_KEYS:
            value = self._req[key].value
            snapshot[key] = self._clean_freq(value)
        for key, lim in (("lat", 90.0), ("lon", 180.0)):
            try:
                value = float(self._req[key].value)
            except (TypeError, ValueError):
                value = None
            # NaN ou lixo quebraria a conta de distancia da lista de ATC
            ok = value is not None and math.isfinite(value) and abs(value) <= lim
            snapshot[key] = value if ok else None
        raw = self._req["callsign"].value
        if isinstance(raw, bytes):
            raw = raw.decode("ascii", "ignore")
        snapshot["callsign"] = (raw or "").strip() or None

        with self._lock:
            self.state.update(snapshot)
        self._grade(snapshot)
        self._check_pending(snapshot)

    @staticmethod
    def _clean_freq(value) -> float | None:
        """Descarta leitura fora da banda aeronautica.

        Se a unidade vier errada numa versao futura do pacote, o numero cai
        fora da faixa e vira None em vez de virar uma frequencia inventada
        na tela do celular.
        """
        if value is None:
            return None
        try:
            mhz = round(float(value), 3)
        except (TypeError, ValueError):
            return None
        if not (MIN_FREQ <= mhz <= MAX_FREQ):
            return None
        return mhz

    def _check_pending(self, snapshot: dict) -> None:
        """Confere se a standby que mandamos escrever realmente entrou.

        Os nomes de evento do SimConnect variam entre versoes do MSFS. Sem
        esta conferencia uma escrita que nao pegou fica invisivel: o botao
        responde, a frequencia nao muda e nao ha nada no log.
        """
        if self._pending is None:
            return
        key, wanted, deadline = self._pending
        got = snapshot.get(key)
        if got is not None and abs(got - wanted) < 0.0006:
            self._pending = None
            self.error = None
            return
        if time.monotonic() > deadline:
            self._pending = None
            self.error = (
                "o MSFS aceitou a conexao mas nao mudou a standby para %.3f. "
                "Confira se o aviao tem COM1 e se o radio nao esta travado." % wanted
            )
            log.error("%s", self.error)

    def snapshot(self) -> dict:
        with self._lock:
            data = dict(self.state)
        data["connected"] = self.connected
        data["error"] = self.error
        return data

    # ---------------------------------------------------------------- escrita

    def _fire(self, event_name: str, value: int = 0) -> bool:
        sm = self._sm
        if not self.connected or sm is None:
            log.warning("evento %s ignorado: MSFS desconectado", event_name)
            return False
        try:
            evt = self._events.get(event_name)
            if evt is None:
                evt = sm.map_to_sim_event(event_name.encode("ascii"))
                if evt is None:
                    self.error = "o MSFS nao reconheceu o evento %s" % event_name
                    log.error("%s", self.error)
                    return False
                self._events[event_name] = evt
            return bool(sm.send_event(evt, ctypes.c_ulong(int(value))))
        except Exception as exc:
            log.error("falha ao enviar %s: %s", event_name, exc)
            self.error = "falha ao enviar %s: %s" % (event_name, exc)
            return False

    def set_standby(self, com: int, mhz: float) -> bool:
        """Escreve a standby em Hz.

        A variante _HZ e obrigatoria: o COM_STBY_RADIO_SET antigo usa BCD16 e
        nao consegue representar os canais de 8.33 kHz.
        """
        hz = int(round(mhz * 1_000_000))
        event = "COM_STBY_RADIO_SET_HZ" if com == 1 else "COM2_STBY_RADIO_SET_HZ"
        ok = self._fire(event, hz)
        if ok:
            self._pending = (
                "com%d_standby" % com,
                round(mhz, 3),
                time.monotonic() + WRITE_TIMEOUT,
            )
        return ok

    def swap(self, com: int) -> bool:
        return self._fire("COM1_RADIO_SWAP" if com == 1 else "COM2_RADIO_SWAP")


class FakeSim(SimBridge):
    """Modo de teste sem o simulador aberto, para ajustar a interface."""

    def __init__(self, poll_hz: float = 5.0):
        super().__init__(poll_hz)
        self.connected = True
        self.state = {
            "com1_active": 122.800,
            "com1_standby": 118.700,
            "com2_active": 121.500,
            "com2_standby": 121.200,
            "lat": -23.435,
            "lon": -46.473,
            "callsign": "FAKE01",
        }

    def start(self) -> None:
        log.warning("rodando com simulador falso")

    def stop(self) -> None:
        pass

    def set_standby(self, com: int, mhz: float) -> bool:
        with self._lock:
            self.state["com%d_standby" % com] = round(mhz, 3)
        return True

    def swap(self, com: int) -> bool:
        with self._lock:
            a, s = "com%d_active" % com, "com%d_standby" % com
            self.state[a], self.state[s] = self.state[s], self.state[a]
        return True
