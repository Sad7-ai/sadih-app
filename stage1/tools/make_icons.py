"""Render the app icons from one SVG using headless Edge's --screenshot flag. No image library,
no debugger protocol — one Edge run per icon, which is slower but cannot get wedged.

  python tools/make_icons.py     ->  web/icons/{icon-192,icon-512,maskable-512,apple-touch-180}.png

`maskable-512` carries extra padding so Android can crop it to a circle or squircle without cutting
the figure. The plain icons keep the rounded-square shape. The PNGs are committed, so a normal
checkout needs no browser — re-run this only when the mark changes.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import utf8  # noqa: F401,E402

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
OUT = ROOT / "web" / "icons"

WORDMARK = "صادِح"   # صادِح — the name, nothing else

# name, px, corner radius, padding % around the figure
SPECS = [
    ("icon-192.png", 192, "22%", 16),
    ("icon-512.png", 512, "22%", 16),
    ("maskable-512.png", 512, "0", 27),      # safe zone: keep the figure inside the middle ~46%
    ("apple-touch-180.png", 180, "0", 15),   # iOS rounds it itself
]


def html(size: int, radius: str, pad: float) -> str:
    inner = 100 - pad * 2
    return f"""<!doctype html><meta charset="utf-8"><style>
  html,body{{margin:0;width:{size}px;height:{size}px;background:transparent;overflow:hidden}}
  .b{{position:absolute;inset:0;border-radius:{radius};
      background:#000}}
  .w{{position:absolute;inset:{pad}%;display:grid;place-items:center;color:#fff;
      font-family:"Thmanyah Serif Display","Thmanyah Serif Text","IBM Plex Sans Arabic",Tahoma,serif;
      font-weight:500;font-size:{size*0.30:.0f}px;line-height:1;letter-spacing:.01em}}
</style><div class="b"></div><div class="w">{WORDMARK}</div>"""


def main():
    if not Path(EDGE).exists():
        raise SystemExit(f"Edge not found at {EDGE}")
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="sadih-icons-"))
    for name, size, radius, pad in SPECS:
        src = tmp / (name + ".html")
        src.write_text(html(size, radius, pad), encoding="utf-8")
        dst = OUT / name
        dst.unlink(missing_ok=True)
        r = subprocess.run(
            [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
             f"--window-size={size},{size}", "--default-background-color=00000000",
             f"--user-data-dir={tmp / ('profile-' + name)}",
             f"--screenshot={dst}", src.as_uri()],
            capture_output=True, text=True, timeout=120)
        if not dst.exists():
            raise SystemExit(f"{name} was not written\n{r.stdout}\n{r.stderr}")
        print(f"  {name:<22} {size}x{size}  {dst.stat().st_size:>6} bytes")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
