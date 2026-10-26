"""Aciona a tecla de PTT configurada no Altitude.

Usa SendInput com scancode em vez de virtual key porque o MSFS em tela cheia
usa DirectInput, que ignora eventos de virtual key. O hook do Altitude e
global, entao ele captura a tecla mesmo com o simulador em foco.

As structs abaixo precisam bater byte a byte com as do Windows. Em x64 o
INPUT tem 40 bytes: DWORD type, 4 de padding e uma union de 32 dominada pelo
MOUSEINPUT. Declarar a union menor faz o SendInput devolver erro 87 e nao
enviar tecla nenhuma, em silencio.
"""

import ctypes
import logging
import sys
import threading
import time
from ctypes import wintypes

log = logging.getLogger("ptt")

# scancodes do set 1. True significa tecla estendida (prefixo E0).
SCANCODES = {
    "esc": (0x01, False),
    "tab": (0x0F, False),
    "capslock": (0x3A, False),
    "space": (0x39, False),
    "enter": (0x1C, False),
    "backspace": (0x0E, False),
    "leftctrl": (0x1D, False),
    "rightctrl": (0x1D, True),
    "leftalt": (0x38, False),
    "rightalt": (0x38, True),
    "leftshift": (0x2A, False),
    "rightshift": (0x36, False),
    "minus": (0x0C, False),
    "equal": (0x0D, False),
    "leftbracket": (0x1A, False),
    "rightbracket": (0x1B, False),
    "semicolon": (0x27, False),
    "apostrophe": (0x28, False),
    "grave": (0x29, False),
    "backslash": (0x2B, False),
    "comma": (0x33, False),
    "period": (0x34, False),
    "slash": (0x35, False),
    "insert": (0x52, True),
    "delete": (0x53, True),
    "home": (0x47, True),
    "end": (0x4F, True),
    "pageup": (0x49, True),
    "pagedown": (0x51, True),
    "up": (0x48, True),
    "down": (0x50, True),
    "left": (0x4B, True),
    "right": (0x4D, True),
    "numpad0": (0x52, False),
    "numpad1": (0x4F, False),
    "numpad2": (0x50, False),
    "numpad3": (0x51, False),
    "numpad4": (0x4B, False),
    "numpad5": (0x4C, False),
    "numpad6": (0x4D, False),
    "numpad7": (0x47, False),
    "numpad8": (0x48, False),
    "numpad9": (0x49, False),
    "numpaddot": (0x53, False),
    "numpadplus": (0x4E, False),
    "numpadminus": (0x4A, False),
    "numpadmultiply": (0x37, False),
    "numpaddivide": (0x35, True),
    "numpadenter": (0x1C, True),
}

# digitos da fileira de cima
for _i, _sc in enumerate((0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B)):
    SCANCODES[str((_i + 1) % 10)] = (_sc, False)

# letras, na ordem fisica do teclado
for _row, _base in (("qwertyuiop", 0x10), ("asdfghjkl", 0x1E), ("zxcvbnm", 0x2C)):
    for _i, _ch in enumerate(_row):
        SCANCODES[_ch] = (_base + _i, False)

# F1 a F24
for _i, _sc in enumerate((0x3B, 0x3C, 0x3D, 0x3E, 0x3F, 0x40, 0x41, 0x42, 0x43, 0x44, 0x57, 0x58)):
    SCANCODES["f%d" % (_i + 1)] = (_sc, False)
for _i, _sc in enumerate((0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x6B, 0x6C, 0x6D, 0x6E, 0x76)):
    SCANCODES["f%d" % (_i + 13)] = (_sc, False)

# botoes do mouse. Nao sao scancode: vao pelo MOUSEINPUT da mesma union.
# O valor e (flag de descer, flag de subir, mouseData, virtual key).
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
XBUTTON1 = 0x0001
XBUTTON2 = 0x0002

MOUSE_BUTTONS = {
    "mouseback": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON1, 0x05),
    "mouseforward": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON2, 0x06),
    "mousemiddle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0, 0x04),
}
# apelidos: como o Windows e os drivers de mouse chamam os mesmos botoes
for _de, _para in (
    ("mouse4", "mouseback"),
    ("xbutton1", "mouseback"),
    ("mouse5", "mouseforward"),
    ("xbutton2", "mouseforward"),
    ("mouse3", "mousemiddle"),
    ("middleclick", "mousemiddle"),
):
    MOUSE_BUTTONS[_de] = MOUSE_BUTTONS[_para]

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
MAPVK_VSC_TO_VK_EX = 3

ULONG_PTR = wintypes.WPARAM  # 8 bytes em x64, 4 em x86


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
    _user32.SendInput.restype = wintypes.UINT
    _user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
    _user32.MapVirtualKeyW.restype = wintypes.UINT
    _user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    _user32.GetAsyncKeyState.restype = ctypes.c_short
else:
    _user32 = None


def _vk_names() -> dict[int, str]:
    """Virtual key -> nome do SCANCODES, para reconhecer a tecla apertada.

    Sai do proprio SCANCODES pelo MapVirtualKey, entao toda tecla que da para
    capturar tambem da para enviar. O numpad entra a mao: com Num Lock ligado
    ele gera VK_NUMPAD*, que o mapa por scancode nao devolve. O Enter do
    numpad cai como "enter": o Windows da o mesmo VK aos dois.
    """
    names: dict[int, str] = {}
    for name, (scan, ext) in SCANCODES.items():
        vk = _user32.MapVirtualKeyW(scan | (0xE000 if ext else 0), MAPVK_VSC_TO_VK_EX)
        if vk:
            names.setdefault(vk, name)  # o primeiro nome do dicionario ganha
    for i in range(10):
        names[0x60 + i] = "numpad%d" % i
    names.update({0x6E: "numpaddot", 0x6B: "numpadplus", 0x6D: "numpadminus",
                  0x6A: "numpadmultiply", 0x6F: "numpaddivide"})
    for name in ("mouseback", "mouseforward", "mousemiddle"):
        names[MOUSE_BUTTONS[name][3]] = name
    return names


def capture(timeout: float = 10.0) -> str | None:
    """Espera o usuario apertar uma tecla ou botao do mouse e devolve o nome.

    Le o estado global do Windows, entao funciona sem foco na janela e pega
    os botoes laterais do mouse, que o tkinter no Windows nao enxerga. Os
    botoes esquerdo e direito ficam de fora: o esquerdo e o que acabou de
    clicar em Mudar. Tecla que ja estava apertada no inicio so conta depois
    de soltar e apertar de novo.
    """
    names = _vk_names()
    ocupadas = {vk for vk in names if _user32.GetAsyncKeyState(vk) & 0x8000}
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        for vk, name in names.items():
            down = _user32.GetAsyncKeyState(vk) & 0x8000
            if not down:
                ocupadas.discard(vk)
            elif vk not in ocupadas:
                return name
        time.sleep(0.015)
    return None


class PttKey:
    """Mantem o estado da tecla e garante que ela nunca fique presa."""

    def __init__(self, key_name: str):
        key = key_name.lower().replace(" ", "").replace("_", "").replace("-", "")
        self.mouse = key in MOUSE_BUTTONS
        if not self.mouse and key not in SCANCODES:
            raise ValueError(
                "tecla '%s' desconhecida. Opcoes: %s"
                % (key_name, ", ".join(sorted(list(SCANCODES) + list(MOUSE_BUTTONS))))
            )
        self.name = key
        if self.mouse:
            self.down_flag, self.up_flag, self.data, self.vk = MOUSE_BUTTONS[key]
            self.scan, self.extended = 0, False
        else:
            self.scan, self.extended = SCANCODES[key]
        self._down = False
        self._lock = threading.Lock()
        self._windows = sys.platform == "win32"
        self._failed = False
        if not self._windows:
            log.warning("fora do Windows: PTT roda em modo simulado, sem enviar tecla")

    @property
    def is_down(self) -> bool:
        return self._down

    def _vk(self) -> int:
        """Virtual key equivalente, so para conferir se a tecla desceu."""
        if not self._windows:
            return 0
        if self.mouse:
            return self.vk
        code = self.scan | (0xE000 if self.extended else 0)
        return _user32.MapVirtualKeyW(code, MAPVK_VSC_TO_VK_EX)

    def _montar(self, keyup: bool) -> "_INPUT":
        if self.mouse:
            return _INPUT(
                type=INPUT_MOUSE,
                u=_INPUTUNION(
                    mi=_MOUSEINPUT(
                        dx=0,
                        dy=0,
                        mouseData=self.data,
                        dwFlags=self.up_flag if keyup else self.down_flag,
                        time=0,
                        dwExtraInfo=0,
                    )
                ),
            )
        flags = KEYEVENTF_SCANCODE
        if self.extended:
            flags |= KEYEVENTF_EXTENDEDKEY
        if keyup:
            flags |= KEYEVENTF_KEYUP
        return _INPUT(
            type=INPUT_KEYBOARD,
            u=_INPUTUNION(
                ki=_KEYBDINPUT(wVk=0, wScan=self.scan, dwFlags=flags, time=0, dwExtraInfo=0)
            ),
        )

    def _send(self, keyup: bool) -> bool:
        if not self._windows:
            return True
        inp = self._montar(keyup)
        sent = _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
        if sent != 1:
            err = ctypes.get_last_error()
            if not self._failed:
                self._failed = True
                log.error(
                    "SendInput falhou (erro %s). Se for 5, o Altitude ou o MSFS estao "
                    "abertos como administrador e o servidor nao. Abra o servidor "
                    "como administrador tambem.",
                    err,
                )
            return False
        self._failed = False
        return True

    def press(self) -> bool:
        with self._lock:
            if self._down:
                return False
            if not self._send(keyup=False):
                return False
            self._down = True
            log.info("PTT down (%s)", self.name)
            return True

    def release(self) -> bool:
        with self._lock:
            if not self._down:
                return False
            self._send(keyup=True)
            self._down = False
            log.info("PTT up (%s)", self.name)
            return True

    def force_release(self, reason: str) -> bool:
        """Solta a tecla incondicionalmente. Usado pelo dead-man switch."""
        if self._down:
            log.warning("soltando PTT a forca: %s", reason)
            return self.release()
        return False

    def self_test(self) -> tuple[bool, str]:
        """Aperta a tecla e confere no Windows se ela realmente desceu.

        Nao prova que o Altitude ouviu, mas separa "o servidor nao mandou" de
        "o Altitude nao esta escutando essa tecla", que e onde a depuracao
        costuma travar.
        """
        if not self._windows:
            return False, "fora do Windows"
        vk = self._vk()
        if vk and _user32.GetAsyncKeyState(vk) & 0x8000:
            return False, "a tecla %s ja estava apertada antes do teste" % self.name
        if not self._send(keyup=False):
            return False, "SendInput falhou (erro %s)" % ctypes.get_last_error()
        time.sleep(0.12)
        down = bool(vk and _user32.GetAsyncKeyState(vk) & 0x8000)
        self._send(keyup=True)
        time.sleep(0.05)
        if not vk:
            return True, "tecla %s enviada (sem virtual key para conferir)" % self.name
        if not down:
            if self.name.startswith("numpad"):
                return False, (
                    "o Windows nao registrou %s. Com o Num Lock desligado essa "
                    "tecla vira outra coisa; ligue o Num Lock e teste de novo" % self.name
                )
            return False, "o Windows nao registrou %s como apertada" % self.name
        if _user32.GetAsyncKeyState(vk) & 0x8000:
            return False, "a tecla %s ficou presa depois do release" % self.name
        return True, "tecla %s apertada e solta com sucesso" % self.name


if __name__ == "__main__":
    # toda tecla que da para enviar tem que dar para capturar, menos o Enter
    # do numpad, que o Windows nao distingue do Enter normal
    nomes = set(_vk_names().values())
    faltando = sorted(n for n in SCANCODES if n not in nomes and n != "numpadenter")
    assert not faltando, "sem captura: %s" % faltando
    assert {"leftctrl", "rightctrl", "mouseback", "mouseforward", "mousemiddle"} <= nomes
    assert ctypes.sizeof(_INPUT) == 40, "INPUT com tamanho errado, o SendInput falharia"
    print("ok")
