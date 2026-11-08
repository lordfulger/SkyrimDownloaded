"""Make the app icon from assets/logo.png: a square around the round emblem in the middle.

Writes assets/icon.ico (all Windows icon sizes) and assets/icon.png (256 px, the title bar and
taskbar icon).
Run by the Build workflow before PyInstaller; needs Pillow.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
logo = Image.open(ROOT / "assets" / "logo.png").convert("RGBA")
w, h = logo.size
side = int(min(w, h) * 0.97)            # the emblem fills the middle of the picture
left, top = (w - side) // 2, (h - side) // 2
square = logo.crop((left, top, left + side, top + side))
# Keep just the round emblem: corners transparent, so the icon sits cleanly on the taskbar.
from PIL import ImageDraw
mask = Image.new("L", (side * 4, side * 4), 0)
ImageDraw.Draw(mask).ellipse((0, 0, side * 4 - 1, side * 4 - 1), fill=255)
square.putalpha(mask.resize((side, side), Image.LANCZOS))
square.resize((256, 256), Image.LANCZOS).save(ROOT / "assets" / "icon.png")
square.save(ROOT / "assets" / "icon.ico",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon made from", logo.size)
