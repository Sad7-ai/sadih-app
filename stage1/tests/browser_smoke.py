"""Real-browser smoke test: headless Edge with a FAKE microphone, against server.py --mock.
Proves the page, the AudioWorklet and the websocket work in an actual browser, and saves screenshots.

  python tests/browser_smoke.py        -> out/smoke-live.png, out/smoke-done.png
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import utf8  # noqa: F401,E402

import requests
import websockets

ROOT = Path(__file__).resolve().parent.parent
EDGE = os.environ.get("SADIH_EDGE") or (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
                                      if os.name == "nt" else "/usr/bin/microsoft-edge")
PORT, CDP = 8012, 9333


def wait_http(url, secs=20):
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
                return m.get("result", {})

    async def js(self, expr):
        r = await self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    async def shot(self, path):
        r = await self.call("Page.captureScreenshot", format="png")
        Path(path).write_bytes(base64.b64decode(r["data"]))


async def main():
    (ROOT / "out").mkdir(exist_ok=True)
    server = subprocess.Popen([sys.executable, "server.py", "--mock", "--port", str(PORT)], cwd=ROOT,
                              env={**__import__("os").environ, "PYTHONUTF8": "1"})
    profile = tempfile.mkdtemp(prefix="sadih-edge-")
    edge = None
    try:
        wait_http(f"http://127.0.0.1:{PORT}/")
        edge = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={CDP}", f"--user-data-dir={profile}",
                                 "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                 "--autoplay-policy=no-user-gesture-required", "--window-size=1366,768",
                                 "--disable-gpu", "--no-first-run", "about:blank"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        targets = wait_http(f"http://127.0.0.1:{CDP}/json").json()
        page = next(t for t in targets if t["type"] == "page")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            tab = Tab(ws)
            await tab.call("Page.enable")
            await tab.call("Network.enable")
            await tab.call("Network.setCacheDisabled", cacheDisabled=True)
            await tab.call("Page.navigate", url=f"http://localhost:{PORT}/")

            async def until(expr, secs, what):
                for _ in range(int(secs / 0.25)):
                    if await tab.js(expr):
                        return
                    await asyncio.sleep(0.25)
                raise SystemExit(f"timeout: {what}")

            await until("typeof start === 'function' && document.readyState === 'complete'", 15, "page script never ran")
            await tab.js("document.getElementById('mic').click()")
            await until("state === 'live' || state === 'error'", 15, "mic never went live")
            await asyncio.sleep(12.5)
            live = json.loads(await tab.js(
                "JSON.stringify({state, units: units.map(u => u.text), buffer, pending, err: document.getElementById('err').textContent,"
                " rate: ctx ? ctx.sampleRate : null, mock: !document.getElementById('mock').hidden})"))
            await tab.shot(ROOT / "out" / "smoke-live.png")
            await tab.js("document.getElementById('mic').click()")
            await asyncio.sleep(2.5)
            done = json.loads(await tab.js(
                "JSON.stringify({state, units: units.length, rev: document.getElementById('t-rev').textContent,"
                " lat: document.getElementById('t-lat').textContent})"))
            await tab.shot(ROOT / "out" / "smoke-done.png")
            try:
                await tab.call("Browser.close")
            except Exception:  # noqa: BLE001  the socket dies with the browser
                pass
        print("live:", json.dumps(live, ensure_ascii=False))
        print("done:", json.dumps(done, ensure_ascii=False))
        assert live["state"] == "live" and not live["err"], live
        assert live["rate"] == 16000, f"AudioContext ran at {live['rate']} Hz"
        assert len(live["units"]) >= 4 and live["units"][0] == "أمس رحت للمستشفى", live["units"]
        assert done["state"] == "idle" and done["rev"] == "0", done
        print("BROWSER SMOKE PASSED")
    finally:
        for p in (edge, server):
            if p and p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    asyncio.run(main())
