"""Janela do COM Radio no PC. E o que vira o .exe.

Roda o mesmo servidor do terminal numa thread e mostra o estado de cada
ponta com luzes. Fechar a janela desliga o radio pelo caminho normal do
uvicorn, que passa pelo lifespan e solta a tecla de PTT.

Os modos de diagnostico (--doctor, --meter...) continuam em 'py server.py'.
"""

import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

HOME = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
ROOT = Path(getattr(sys, "_MEIPASS", HOME))

if getattr(sys, "frozen", False):
    # o .exe nao tem console: sem isto o log some e o uvicorn quebra tentando
    # perguntar se o stdout e um terminal. Recomeca a cada abertura
    sys.stdout = sys.stderr = open(HOME / "com-radio.log", "w", encoding="utf-8", buffering=1)

VOID, FACE, BEZEL = "#0A0D0E", "#141A1C", "#293134"
LEGEND, INK, AMBER = "#7F8D93", "#E4EAEC", "#FFA524"
GREEN, RED, OFF = "#62E39B", "#FF4B2B", "#3A4346"


def fail(text: str) -> None:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("COM Radio", text)
    raise SystemExit(1)


try:
    import qrcode

    import server
except Exception as exc:  # config.json quebrado, tecla invalida, etc.
    fail("Não deu para iniciar:\n\n%s" % exc)

try:
    SRV = server.make_server()
except OSError:
    fail(
        "As portas %s ou %s já estão em uso.\n\n"
        "O COM Radio provavelmente já está aberto. Feche a outra janela "
        "e tente de novo." % (server.SETUP_PORT, server.PORT)
    )

THREAD = threading.Thread(target=SRV.run, daemon=True, name="uvicorn")
THREAD.start()


class Window:
    ROWS = ("Servidor", "MSFS", "Áudio", "Celular", "PTT")

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("COM Radio")
        root.configure(bg=VOID)
        root.resizable(False, False)
        try:
            root.iconbitmap(ROOT / "assets" / "icon.ico")
        except tk.TclError:
            pass

        tk.Label(root, text="COM", bg=VOID, fg=AMBER, font=("Consolas", 26, "bold")).pack(
            anchor="w", padx=20, pady=(16, 0)
        )
        tk.Label(
            root, text="rádio no celular para o IVAO Altitude", bg=VOID, fg=LEGEND,
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=20)

        panel = tk.Frame(root, bg=FACE, highlightbackground=BEZEL, highlightthickness=1)
        panel.pack(fill="x", padx=20, pady=14)
        self.lamps, self.details = {}, {}
        for i, name in enumerate(self.ROWS):
            lamp = tk.Canvas(panel, width=12, height=12, bg=FACE, highlightthickness=0)
            lamp.create_oval(1, 1, 11, 11, fill=OFF, outline="", tags="dot")
            lamp.grid(row=i, column=0, padx=(14, 8), pady=7)
            tk.Label(panel, text=name, bg=FACE, fg=INK, font=("Segoe UI", 10, "bold"), width=8,
                     anchor="w").grid(row=i, column=1, sticky="w")
            detail = tk.Label(panel, text="", bg=FACE, fg=LEGEND, font=("Segoe UI", 10),
                              anchor="w", width=34)
            detail.grid(row=i, column=2, sticky="w", padx=(0, 14))
            self.lamps[name], self.details[name] = lamp, detail

        setup_url = "http://%s:%s" % (server.lan_ip(), server.SETUP_PORT)
        bottom = tk.Frame(root, bg=VOID)
        bottom.pack(fill="x", padx=20, pady=(0, 18))
        self.draw_qr(bottom, setup_url).pack(side="left")
        text = tk.Frame(bottom, bg=VOID)
        text.pack(side="left", padx=16, anchor="n")
        tk.Label(text, text="Instalar no iPhone", bg=VOID, fg=INK,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(
            text, bg=VOID, fg=LEGEND, font=("Segoe UI", 9), justify="left",
            text="Aponte a câmera para o código\nou abra no Safari:",
        ).pack(anchor="w", pady=(2, 4))
        tk.Label(text, text=setup_url, bg=VOID, fg=AMBER, font=("Consolas", 11)).pack(anchor="w")
        tk.Label(
            text, bg=VOID, fg=LEGEND, font=("Segoe UI", 9), justify="left",
            text="\nDepois de instalado, é só abrir o\nícone COM no iPhone.",
        ).pack(anchor="w")

        root.protocol("WM_DELETE_WINDOW", self.close)
        self.tick()

    @staticmethod
    def draw_qr(parent, url: str) -> tk.Canvas:
        qr = qrcode.QRCode(border=2)
        qr.add_data(url)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        cell = max(3, 132 // len(matrix))
        size = cell * len(matrix)
        canvas = tk.Canvas(parent, width=size, height=size, bg="white", highlightthickness=0)
        for y, row in enumerate(matrix):
            for x, dark in enumerate(row):
                if dark:
                    canvas.create_rectangle(x * cell, y * cell, (x + 1) * cell, (y + 1) * cell,
                                            fill="black", outline="")
        return canvas

    def show(self, name: str, color: str, text: str) -> None:
        self.lamps[name].itemconfigure("dot", fill=color)
        self.details[name].configure(text=text[:60])

    def tick(self) -> None:
        if not THREAD.is_alive():
            self.show("Servidor", RED, "parou; veja com-radio.log")
        elif SRV.started:
            self.show("Servidor", GREEN, "https://%s.local:%s" % (server.certs.hostname(), server.PORT))
        else:
            self.show("Servidor", AMBER, "iniciando…")

        s = server.SIM.snapshot()
        if s.get("connected"):
            self.show("MSFS", GREEN, s.get("callsign") or "conectado")
        else:
            self.show("MSFS", OFF, s.get("error") or "fechado ou fora do voo")

        a = server.RX.snapshot()
        if a["running"]:
            self.show("Áudio", GREEN, "recebendo alguém" if a["rx"] else "medindo " + a["source"])
        elif a.get("error"):
            # IVAO fechado e normal antes do voo: ambar, nao vermelho
            self.show("Áudio", AMBER, "abra o IVAO para ter o indicador de RX")
        else:
            self.show("Áudio", OFF, "desligado")

        n = len(server.HUB.clients)
        self.show("Celular", GREEN if n else OFF,
                  ("%d conectado" % n) + ("s" if n > 1 else "") if n else "aguardando o iPhone")

        if server.KEY.is_down:
            self.show("PTT", RED, "TRANSMITINDO")
        else:
            self.show("PTT", OFF, "tecla %s" % server.KEY.name)

        self.root.after(250, self.tick)

    def close(self) -> None:
        # o mesmo desligamento do Ctrl+C: o lifespan solta a tecla e fecha
        # simulador e audio antes da janela sumir
        SRV.should_exit = True
        THREAD.join(timeout=5)
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    Window(root)
    root.mainloop()
