"""Gera os icones do iPhone e do .exe. Rode de novo se mudar o desenho."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
S = 1024
VOID, FACE, AMBER = (10, 13, 14), (20, 26, 28), (255, 165, 36)

img = Image.new("RGB", (S, S), VOID)
d = ImageDraw.Draw(img)
# moldura do display, como o vidro do KX155
d.rounded_rectangle((120, 120, S - 120, S - 120), radius=110, fill=FACE, outline=(41, 49, 52), width=14)
cx, cy = S // 2, S // 2
d.ellipse((cx - 56, cy - 56, cx + 56, cy + 56), fill=AMBER)
# ondas para os dois lados, cada uma mais apagada
for i, r in enumerate((135, 210, 285)):
    tom = tuple(int(VOID[k] + (AMBER[k] - VOID[k]) * (1 - i * 0.28)) for k in range(3))
    box = (cx - r, cy - r, cx + r, cy + r)
    d.arc(box, -40, 40, fill=tom, width=38)
    d.arc(box, 140, 220, fill=tom, width=38)

static = ROOT / "static"
img.resize((180, 180), Image.LANCZOS).save(static / "icon-180.png")
img.resize((512, 512), Image.LANCZOS).save(static / "icon-512.png")
img.save(ROOT / "assets" / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
print("ok")
