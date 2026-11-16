"""Drive the /app demo in a real headless Edge with a fake mic, against server.py --mock.
Walks the whole flow: lock -> unlock -> floating button -> floating window -> listen -> drag -> resize
-> open a mock app (bubble must survive) -> expand to the full app. Screenshots land in out/demo-*.png.

  python tests/demo_smoke.py
"""
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import utf8  # noqa: F401,E402

import requests  # noqa: E402
import websockets  # noqa: E402

EDGE = os.environ.get("SADIH_EDGE") or (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
                                      if os.name == "nt" else "/usr/bin/microsoft-edge")
PORT, CDP = 8014, 9335


def wait_http(url, secs=25):
    t = time.time()
    while time.time() - t < secs:
        try:
            return requests.get(url, timeout=1)
        except requests.RequestException:
            time.sleep(0.2)
    raise SystemExit(f"timeout waiting for {url}")


class Tab:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def call(self, method, **params):
        self.n += 1
        mid = self.n
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            m = json.loads(await self.ws.recv())
            if m.get("id") == mid:
                if "error" in m:
                    raise SystemExit(f"{method} -> {m['error']}")
                return m.get("result", {})

    async def js(self, expr):
        r = await self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            raise SystemExit("JS error: " + json.dumps(r["exceptionDetails"])[:400])
        return r.get("result", {}).get("value")

    async def until(self, expr, secs, what):
        for _ in range(int(secs / 0.25)):
            if await self.js(expr):
                return
            await asyncio.sleep(0.25)
        raise SystemExit(f"timeout: {what}")

    async def drag(self, x0, y0, x1, y1, steps=8):
        await self.call("Input.dispatchMouseEvent", type="mousePressed", x=x0, y=y0, button="left", clickCount=1)
        for i in range(1, steps + 1):
            await self.call("Input.dispatchMouseEvent", type="mouseMoved", button="left",
                            x=x0 + (x1 - x0) * i / steps, y=y0 + (y1 - y0) * i / steps)
            await asyncio.sleep(0.02)
        await self.call("Input.dispatchMouseEvent", type="mouseReleased", x=x1, y=y1, button="left", clickCount=1)

    async def shot(self, path):
        r = await self.call("Page.captureScreenshot", format="png")
        Path(path).write_bytes(base64.b64decode(r["data"]))


async def main():
    (ROOT / "out").mkdir(exist_ok=True)
    server = subprocess.Popen([sys.executable, "server.py", "--mock", "--port", str(PORT)], cwd=ROOT,
                              env={**os.environ, "PYTHONUTF8": "1"})
    profile = tempfile.mkdtemp(prefix="sadih-demo-")
    edge = None
    try:
        wait_http(f"http://127.0.0.1:{PORT}/app")
        edge = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={CDP}", f"--user-data-dir={profile}",
                                 "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                 "--autoplay-policy=no-user-gesture-required", "--window-size=1100,1000",
                                 "--disable-gpu", "--no-first-run", "about:blank"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        page = next(t for t in wait_http(f"http://127.0.0.1:{CDP}/json").json() if t["type"] == "page")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            tab = Tab(ws)
            await tab.call("Page.enable"); await tab.call("Network.enable")
            await tab.call("Network.setCacheDisabled", cacheDisabled=True)
            await tab.call("Page.navigate", url=f"http://localhost:{PORT}/app")
            await tab.until("typeof client === 'object' && document.readyState === 'complete'", 20, "page script never ran")

            # icons drawn?
            grid = await tab.js("document.querySelectorAll('#g1 .app').length + ':' + document.querySelectorAll('#gd .app').length")
            await tab.shot(ROOT / "out" / "demo-1-lock.png")

            # unlock by swiping up on the lock screen
            box = json.loads(await tab.js("JSON.stringify(document.getElementById('lock').getBoundingClientRect())"))
            cx = box["x"] + box["width"] / 2
            await tab.drag(cx, box["y"] + box["height"] * 0.75, cx, box["y"] + box["height"] * 0.25)
            await tab.until("unlocked === true && document.getElementById('lock').hidden", 6, "did not unlock")
            await asyncio.sleep(0.5)
            await tab.shot(ROOT / "out" / "demo-2-home.png")
            bub = await tab.js("!document.getElementById('bubble').classList.contains('hide')")

            # floating button -> floating window
            await tab.js("document.getElementById('bubble').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,clientX:0,clientY:0}));"
                         "document.getElementById('bubble').dispatchEvent(new PointerEvent('pointerup',{bubbles:true,clientX:0,clientY:0}))")
            await tab.until("pip.open === true", 4, "floating window did not open")

            # listen
            await tab.js("document.getElementById('pip-mic').click()")
            await tab.until("client.state === 'live' || client.state === 'error'", 15, "mic never went live")
            await asyncio.sleep(9)
            mid = json.loads(await tab.js(
                "JSON.stringify({state: client.state, units: client.units.map(u=>u.text), mock: !!client.mock,"
                " err: document.getElementById('sd-err').textContent, pipText: document.getElementById('pip-body').innerText.trim().slice(0,60)})"))
            await tab.shot(ROOT / "out" / "demo-3-pip-live.png")

            # drag the window, then resize it
            before = json.loads(await tab.js("JSON.stringify(pip)"))
            bar = json.loads(await tab.js("JSON.stringify(document.getElementById('pip-bar').getBoundingClientRect())"))
            await tab.drag(bar["x"] + bar["width"] / 2, bar["y"] + 8, bar["x"] + bar["width"] / 2 - 40, bar["y"] - 90)
            moved = json.loads(await tab.js("JSON.stringify(pip)"))
            rs = json.loads(await tab.js("JSON.stringify(document.getElementById('pip-rs').getBoundingClientRect())"))
            await tab.drag(rs["x"] + 8, rs["y"] + 16, rs["x"] - 55, rs["y"] + 70)
            sized = json.loads(await tab.js("JSON.stringify(pip)"))
            await tab.shot(ROOT / "out" / "demo-4-pip-resized.png")

            # a mock app — the floating button must stay on top of it
            await tab.js("document.querySelector('#g1 .app[data-key=\"msg\"]').click()")
            await tab.until("view === 'app'", 4, "mock app did not open")
            await asyncio.sleep(0.5)
            over = await tab.js("(() => { const b = document.getElementById('bubble').getBoundingClientRect();"
                                " const t = document.elementFromPoint(b.x + b.width/2, b.y + b.height/2);"
                                " return !!(t && t.closest('#bubble')); })()")
            await tab.shot(ROOT / "out" / "demo-5-mock-app.png")

            # expand to the full app
            await tab.js("document.getElementById('bubble').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,clientX:0,clientY:0}));"
                         "document.getElementById('bubble').dispatchEvent(new PointerEvent('pointerup',{bubbles:true,clientX:0,clientY:0}))")
            await asyncio.sleep(0.3)
            await tab.js("document.getElementById('pip-max').click()")
            await tab.until("view === 'sadih'", 4, "full app did not open")
            await asyncio.sleep(1.2)
            full = json.loads(await tab.js(
                "JSON.stringify({view, state: client.state, units: client.units.length,"
                " text: document.getElementById('sd-text').innerText.trim().slice(0,70)})"))
            await tab.shot(ROOT / "out" / "demo-6-full-app.png")

            await tab.js("document.getElementById('sd-mic').click()")
            await asyncio.sleep(2)
            try:
                await tab.call("Browser.close")
            except Exception:  # noqa: BLE001  the socket dies with the browser
                pass

        print(f"icons page1:dock = {grid}   bubble shown after unlock = {bub}")
        print("live :", json.dumps(mid, ensure_ascii=False))
        print("drag :", f"{before['x']},{before['y']} -> {moved['x']},{moved['y']}")
        print("size :", f"{before['w']}x{before['h']} -> {sized['w']}x{sized['h']}")
        print("bubble on top of a mock app:", over)
        print("full :", json.dumps(full, ensure_ascii=False))

        assert grid == "20:4", f"home grid wrong: {grid}"
        assert bub, "floating button did not appear after unlocking"
        assert mid["state"] == "live" and not mid["err"], mid
        assert mid["mock"] is True
        assert len(mid["units"]) >= 3, mid["units"]
        assert mid["units"][0] == "أمس رحت للمستشفى", mid["units"]
        assert mid["pipText"], "floating window showed no text"
        assert (moved["x"], moved["y"]) != (before["x"], before["y"]), "window did not move"
        assert sized["w"] > before["w"] and sized["h"] > before["h"], "window did not resize"
        assert over, "floating button is NOT on top of an open app"
        assert full["view"] == "sadih" and full["state"] == "live", full
        assert full["units"] >= len(mid["units"]), "session did not survive the expand"
        print("\nDEMO SMOKE PASSED")
    finally:
        for p in (edge, server):
            if p and p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    asyncio.run(main())
