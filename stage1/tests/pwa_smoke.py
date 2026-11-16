"""Check the app is installable and that a real phone gets the app, not a drawing of a phone.

Serves with --mock, then in headless Edge under true phone emulation (390x844, mobile, touch):
  - /manifest.webmanifest is valid and points at icons that exist
  - a phone viewport auto-enters bare mode with NO ?bare flag
  - nothing overflows sideways, and the transcript still runs
  - ?frame=1 forces the phone shell back, for showing the floating button on a laptop

  python tests/pwa_smoke.py        -> out/pwa-bare.png
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
PORT, CDP = 8021, 9345
BASE = f"http://localhost:{PORT}"


def wait_http(url, secs=30):
    t = time.time()
    while time.time() - t < secs:
        try:
            return requests.get(url, timeout=1)
        except requests.RequestException:
            time.sleep(0.25)
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

    async def ready(self, secs=25):
        for _ in range(int(secs / 0.25)):
            if await self.js("document.readyState === 'complete' && typeof client === 'object'"):
                return
            await asyncio.sleep(0.25)
        raise SystemExit("page never became ready")


async def main():
    (ROOT / "out").mkdir(exist_ok=True)
    srv = subprocess.Popen([sys.executable, "server.py", "--mock", "--port", str(PORT)], cwd=ROOT,
                           env={**os.environ, "PYTHONUTF8": "1"})
    prof = tempfile.mkdtemp(prefix="sadih-pwa-")
    edge = None
    try:
        wait_http(f"{BASE}/app")

        # --- manifest and icons, straight over HTTP ---
        r = requests.get(f"{BASE}/manifest.webmanifest", timeout=5)
        assert r.status_code == 200, r.status_code
        assert "manifest" in r.headers.get("content-type", ""), r.headers.get("content-type")
        m = r.json()
        for k in ("name", "start_url", "scope", "display", "icons", "background_color", "theme_color"):
            assert m.get(k), f"manifest is missing {k}"
        assert m["display"] == "standalone", m["display"]
        sizes = set()
        for ic in m["icons"]:
            ir = requests.get(BASE + ic["src"], timeout=5)
            assert ir.status_code == 200 and ir.headers["content-type"] == "image/png", ic["src"]
            assert ir.content[:8] == b"\x89PNG\r\n\x1a\n", f"{ic['src']} is not a PNG"
            sizes.add(ic["sizes"])
        assert "512x512" in sizes, "need a 512px icon to be installable"
        assert any(ic.get("purpose") == "maskable" for ic in m["icons"]), "need a maskable icon for Android"
        apple = requests.get(f"{BASE}/static/icons/apple-touch-180.png", timeout=5)
        assert apple.status_code == 200, "apple-touch icon missing"
        print(f"manifest ok: {m['name']} · start_url {m['start_url']} · {len(m['icons'])} icons {sorted(sizes)}")

        # the service worker must come from the ROOT, or its scope cannot cover /app
        sw = requests.get(f"{BASE}/sw.js", timeout=5)
        assert sw.status_code == 200, "no /sw.js — Chrome will not offer to install"
        assert "javascript" in sw.headers.get("content-type", ""), sw.headers.get("content-type")
        assert sw.headers.get("Service-Worker-Allowed") == "/", "missing Service-Worker-Allowed: /"
        assert "addEventListener(\"fetch\"" in sw.text, "the worker has no fetch handler, which is the whole point"
        for never in ("/ws/", "/config", "/healthz"):
            assert never in sw.text, f"the worker does not exempt {never}"

        # EVERY page in scope must declare the manifest and register the worker. A scanner
        # (PWABuilder, Lighthouse) hits whatever URL it is given — usually the root.
        for path in ("/", "/app"):
            html = requests.get(BASE + path, timeout=5).text
            assert 'rel="manifest"' in html, f"{path} does not link the manifest — a scanner sees no app"
            assert "serviceWorker.register" in html, f"{path} does not register the service worker"
        print("both / and /app declare the manifest and register the worker")

        # assetlinks: absent is fine and must say so clearly, not 500
        al = requests.get(f"{BASE}/.well-known/assetlinks.json", timeout=5)
        assert al.status_code in (200, 404), al.status_code
        print(f"sw.js ok ({len(sw.content)} B, scope /) · assetlinks {al.status_code}"
              + ("" if al.status_code == 200 else " (not configured yet — the APK will show a URL bar)"))

        edge = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={CDP}", f"--user-data-dir={prof}",
                                 "--disable-gpu", "--no-first-run", "--use-fake-ui-for-media-stream",
                                 "--use-fake-device-for-media-stream", "about:blank"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        target, t0 = None, time.time()
        while time.time() - t0 < 25 and target is None:
            try:
                target = next((t for t in requests.get(f"http://127.0.0.1:{CDP}/json", timeout=1).json()
                               if t["type"] == "page"), None)
            except requests.RequestException:
                pass
            if target is None:
                time.sleep(0.3)
        if target is None:
            raise SystemExit("Edge never opened a page target")

        async with websockets.connect(target["webSocketDebuggerUrl"], max_size=None) as ws:
            tab = Tab(ws)
            await tab.call("Page.enable")
            await tab.call("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=2,
                           mobile=True, screenOrientation={"type": "portraitPrimary", "angle": 0})
            await tab.call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)

            # --- a phone gets SHELL: the whole simulation, no drawn bezel ---
            await tab.call("Page.navigate", url=f"{BASE}/app")
            await tab.ready()
            swreg = await tab.js(
                "navigator.serviceWorker.getRegistration('/').then(r => !!r && !!(r.active||r.installing||r.waiting))")
            auto = json.loads(await tab.js(
                "JSON.stringify({mode: MODE,"
                " frameShown: getComputedStyle(document.querySelector('.island')).display !== 'none',"
                " overflow: document.documentElement.scrollWidth - innerWidth,"
                " icons: document.querySelectorAll('#g1 .app').length,"
                " screenW: document.getElementById('screen').clientWidth,"
                " bubbleIn: (() => { const b = document.getElementById('bubble').getBoundingClientRect();"
                "   return b.right <= innerWidth + 1 && b.left >= -1; })(),"
                " vw: innerWidth})"))

            # unlock, then the floating button must be reachable and open its window
            await tab.js("document.getElementById('lock').click()")
            await asyncio.sleep(0.6)
            await tab.js("document.getElementById('bubble').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,clientX:0,clientY:0}));"
                         "document.getElementById('bubble').dispatchEvent(new PointerEvent('pointerup',{bubbles:true,clientX:0,clientY:0}))")
            await asyncio.sleep(0.4)
            float_ok = json.loads(await tab.js(
                "JSON.stringify({pip: pip.open, w: pip.w, h: pip.h, scW: SC.w, scH: SC.h,"
                " inside: pip.x >= 0 && pip.x + pip.w <= SC.w + 1})"))
            await tab.js("document.getElementById('pip-close').click(); openSadih()")

            await tab.js("document.getElementById('sd-mic').click()")
            for _ in range(60):
                if await tab.js("client.state === 'live' || client.state === 'error'"):
                    break
                await asyncio.sleep(0.25)
            await asyncio.sleep(9)
            live = json.loads(await tab.js(
                "JSON.stringify({state: client.state, units: client.units.length,"
                " overflow: document.documentElement.scrollWidth - innerWidth,"
                " err: document.getElementById('sd-err').textContent,"
                " badgeOverPill: (() => { const b = document.getElementById('mockbadge').getBoundingClientRect();"
                "   const p = document.getElementById('sd-pill').getBoundingClientRect();"
                "   return !(b.right < p.left || b.left > p.right || b.bottom < p.top || b.top > p.bottom); })()})"))
            r = await tab.call("Page.captureScreenshot", format="png")
            (ROOT / "out" / "pwa-bare.png").write_bytes(base64.b64decode(r["data"]))

            # --- ?frame=1 forces the drawn iPhone back, even on a phone viewport ---
            await tab.call("Page.navigate", url=f"{BASE}/app?frame=1")
            await tab.ready()
            forced = json.loads(await tab.js(
                "JSON.stringify({mode: MODE,"
                " island: getComputedStyle(document.querySelector('.island')).display !== 'none'})"))
            await tab.call("Page.navigate", url=f"{BASE}/app?mode=bare")
            await tab.ready()
            bare = json.loads(await tab.js(
                "JSON.stringify({mode: MODE, home: getComputedStyle(document.getElementById('home')).display !== 'none'})"))
            # the shipped APK asks for ?bare=1 — that URL is baked in and must now give the simulation
            await tab.call("Page.navigate", url=f"{BASE}/app?bare=1")
            await tab.ready()
            legacy = json.loads(await tab.js("JSON.stringify({mode: MODE})"))
            try:
                await tab.call("Browser.close")
            except Exception:  # noqa: BLE001  the socket dies with the browser
                pass

        print("service worker registered in the browser:", swreg)
        print("phone viewport:", json.dumps(auto))
        print("floating window:", json.dumps(float_ok))
        print("listening     :", json.dumps(live, ensure_ascii=False))
        print("?frame=1      :", json.dumps(forced))
        print("?mode=bare    :", json.dumps(bare))
        print("?bare=1 (APK) :", json.dumps(legacy))

        assert swreg is True, "the page did not register a service worker"
        assert auto["mode"] == "shell", f"a phone should get the full simulation, got {auto['mode']}"
        assert auto["frameShown"] is False, "the drawn bezel is still there inside a real phone"
        assert auto["icons"] == 20, f"the home screen lost its icons: {auto['icons']}"
        assert auto["overflow"] <= 0, f"page scrolls sideways by {auto['overflow']}px"
        assert abs(auto["screenW"] - auto["vw"]) <= 1, "the simulation is not using the full screen"
        assert auto["bubbleIn"] is True, "the floating button sits outside the real screen"
        assert float_ok["pip"] is True and float_ok["inside"] is True, float_ok
        assert abs(float_ok["scW"] - auto["vw"]) <= 1, "bounds still use the fake screen size"
        assert live["state"] == "live" and not live["err"], live
        assert live["units"] >= 3, live
        assert live["overflow"] <= 0, "text made the page scroll sideways"
        assert live["badgeOverPill"] is False, "the mock badge covers the status pill"
        assert forced["mode"] == "frame" and forced["island"] is True, "?frame=1 did not restore the drawn iPhone"
        assert bare["mode"] == "bare" and bare["home"] is False, "?mode=bare did not strip the simulation"
        assert legacy["mode"] == "shell", "the URL baked into the shipped APK does not give the simulation"
        man = requests.get(f"{BASE}/manifest.webmanifest", timeout=5).json()
        assert "shell" in man["start_url"], f"installed app would not open the simulation: {man['start_url']}"
        print("\nPWA SMOKE PASSED")
    finally:
        for p in (edge, srv):
            if p and p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    asyncio.run(main())
