"""Drive /app as a real touch phone (390x844, shell mode) and prove the mobile gestures work.

The other smoke tests use mouse events, which never exercise touch-action, scrolling, or the
bottom strip that Android's own gesture bar fights over. This one dispatches real touch events
on an emulated device:

  short swipe unlocks -> pages track the finger -> flick and dot taps turn the page ->
  the transcript scrolls and sticks to the newest line -> the home bar is tappable.

  python tests/touch_smoke.py
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import utf8  # noqa: F401,E402

import websockets  # noqa: E402
from demo_smoke import EDGE, Tab, wait_http  # noqa: E402

PORT, CDP = 8016, 9337
W, H = 390, 844

# collected before any page script runs, so a crash during boot is still reported
ERR_HOOK = """
window.__errs = [];
addEventListener('error', e => window.__errs.push(String(e.message)));
addEventListener('unhandledrejection', e => window.__errs.push('reject: ' + e.reason));
"""


async def touch(tab, pts, kind):
    await tab.call("Input.dispatchTouchEvent", type=kind,
                   touchPoints=[{"x": x, "y": y} for x, y in pts])


async def swipe(tab, x0, y0, x1, y1, steps=12, watch=None, pause=0.016):
    """A finger, not a mouse. Returns whatever `watch` evaluated to mid-swipe."""
    seen = None
    await touch(tab, [(x0, y0)], "touchStart")
    for i in range(1, steps + 1):
        await touch(tab, [(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)], "touchMove")
        if watch and i == max(1, steps // 2):
            seen = await tab.js(watch)
        await asyncio.sleep(pause)
    await touch(tab, [(x1, y1)], "touchEnd")
    return seen


async def tap(tab, x, y):
    await touch(tab, [(x, y)], "touchStart")
    await asyncio.sleep(0.04)
    await touch(tab, [(x, y)], "touchEnd")
    await asyncio.sleep(0.3)


async def box(tab, sel):
    return json.loads(await tab.js(
        "JSON.stringify(document.querySelector(" + json.dumps(sel) + ").getBoundingClientRect())"))


async def centre(tab, sel):
    b = await box(tab, sel)
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


async def main():
    (ROOT / "out").mkdir(exist_ok=True)
    server = subprocess.Popen([sys.executable, "server.py", "--mock", "--port", str(PORT)], cwd=ROOT,
                              env={**os.environ, "PYTHONUTF8": "1"})
    profile = tempfile.mkdtemp(prefix="sadih-touch-")
    edge = None
    fails = []
    try:
        wait_http("http://127.0.0.1:%d/app" % PORT)
        edge = subprocess.Popen([EDGE, "--headless=new", "--remote-debugging-port=%d" % CDP,
                                 "--user-data-dir=" + profile,
                                 "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                 "--autoplay-policy=no-user-gesture-required",
                                 "--window-size=%d,%d" % (W, H),
                                 "--disable-gpu", "--no-first-run", "about:blank"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        page = next(t for t in wait_http("http://127.0.0.1:%d/json" % CDP).json() if t["type"] == "page")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            tab = Tab(ws)
            await tab.call("Page.enable")
            await tab.call("Network.enable")
            await tab.call("Network.setCacheDisabled", cacheDisabled=True)
            # a real phone: device pixels, touch only, no mouse
            await tab.call("Emulation.setDeviceMetricsOverride", width=W, height=H,
                           deviceScaleFactor=3, mobile=True)
            await tab.call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
            await tab.call("Page.addScriptToEvaluateOnNewDocument", source=ERR_HOOK)
            await tab.call("Page.navigate", url="http://localhost:%d/app?shell=1" % PORT)
            await tab.until("typeof client === 'object' && document.readyState === 'complete'",
                            20, "page script never ran")

            def check(name, ok, detail=""):
                print(("ok   " if ok else "FAIL ") + name + (("  " + str(detail)) if detail != "" else ""))
                if not ok:
                    fails.append(name)

            check("shell mode on a phone-sized screen", await tab.js("MODE") == "shell", await tab.js("MODE"))
            check("the page itself never scrolls sideways",
                  await tab.js("document.documentElement.scrollWidth <= innerWidth + 1"))

            # 1. a short swipe is enough to unlock
            await swipe(tab, W / 2, H * 0.72, W / 2, H * 0.48)
            await tab.until("unlocked === true", 6, "a short swipe did not unlock")
            await asyncio.sleep(0.5)
            check("a short swipe unlocks", True)
            await tab.shot(ROOT / "out" / "touch-1-home.png")

            # 2. the pages follow the finger, then settle on page 2
            mid = await swipe(tab, W * 0.8, H * 0.42, W * 0.15, H * 0.42,
                              watch="getComputedStyle(document.getElementById('pages')).transform")
            tracked = bool(mid) and mid != "none" and "matrix(1, 0, 0, 1, 0, 0)" not in mid
            check("the pages track the finger mid-swipe", tracked, mid)
            await asyncio.sleep(0.6)
            check("the swipe lands on page 2", await tab.js("page === 1"), await tab.js("page"))
            await tab.shot(ROOT / "out" / "touch-2-page2.png")

            # 3. a short fast flick counts too
            await swipe(tab, W * 0.2, H * 0.42, W * 0.52, H * 0.42, steps=4, pause=0.008)
            await asyncio.sleep(0.6)
            check("a short fast flick still turns the page", await tab.js("page === 0"), await tab.js("page"))

            # 4. the dots are a tap target, not decoration
            await tap(tab, *await centre(tab, "#dots i:last-child"))
            await asyncio.sleep(0.4)
            check("tapping a dot turns the page", await tab.js("page === 1"), await tab.js("page"))
            await tap(tab, *await centre(tab, "#dots i:first-child"))
            await asyncio.sleep(0.4)

            # 5. tapping an icon opens the app
            await tap(tab, *await centre(tab, '#g1 .app[data-key="sadih"]'))
            await tab.until("view === 'sadih'", 5, "tapping the icon did not open the app")
            await asyncio.sleep(0.5)
            await tab.shot(ROOT / "out" / "touch-3-sadih.png")

            # 6. a long transcript scrolls, and follows the newest line until you scroll back
            await tab.js("client.units = Array.from({length: 26}, (_, i) =>"
                         " ({text: 'سطر رقم ' + (i + 1) + ' من النص الطويل', state: 'final'})); render();")
            await asyncio.sleep(0.4)
            m = json.loads(await tab.js(
                "(b => JSON.stringify({sh: b.scrollHeight, ch: b.clientHeight, top: b.scrollTop}))"
                "(document.getElementById('sd-body'))"))
            check("the transcript overflows, so scrolling is the only way to read it",
                  m["sh"] > m["ch"] + 40, m)
            check("it opens pinned to the newest line", m["top"] >= m["sh"] - m["ch"] - 4, m)

            sb = await box(tab, "#sd-body")
            await swipe(tab, W / 2, sb["y"] + sb["height"] * 0.25, W / 2, sb["y"] + sb["height"] * 0.9, steps=14)
            await asyncio.sleep(0.6)
            top = await tab.js("document.getElementById('sd-body').scrollTop")
            check("dragging down scrolls back through the transcript", top < m["top"] - 40,
                  "%s -> %s" % (m["top"], top))

            await tab.js("client.units.push({text: 'سطر جديد بعد التمرير', state: 'final'}); render();")
            await asyncio.sleep(0.3)
            kept = await tab.js("document.getElementById('sd-body').scrollTop")
            check("new speech does not yank the view while reading back", abs(kept - top) < 40,
                  "%s -> %s" % (top, kept))
            await tab.shot(ROOT / "out" / "touch-4-scrolled.png")

            # 7. the way out of the app has to be visible, tappable, and clear of Android's bar
            ind = json.loads(await tab.js(
                "(n => { const b = n.getBoundingClientRect(); const s = getComputedStyle(n);"
                " return JSON.stringify({shown: s.display !== 'none', pe: s.pointerEvents,"
                " x: b.x, y: b.y, w: b.width, h: b.height, fromBottom: innerHeight - b.bottom}); })"
                "(document.querySelector('.indicator'))"))
            check("the home bar is visible in shell mode", ind["shown"], ind)
            check("the home bar accepts taps", ind["pe"] == "auto", ind["pe"])
            check("the home bar sits clear of Android's gesture area", ind["fromBottom"] >= 8, ind["fromBottom"])
            check("the home bar is a finger-sized target", ind["w"] >= 44 and ind["h"] >= 24,
                  "%sx%s" % (ind["w"], ind["h"]))
            check("nothing covers the home bar", await tab.js(
                "(() => { const b = document.querySelector('.indicator').getBoundingClientRect();"
                " const t = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2);"
                " return !!(t && t.closest('.indicator')); })()"))

            await tap(tab, ind["x"] + ind["w"] / 2, ind["y"] + ind["h"] / 2)
            await asyncio.sleep(0.6)
            check("tapping the home bar leaves the app", await tab.js("view === 'home'"), await tab.js("view"))
            await tab.shot(ROOT / "out" / "touch-5-back-home.png")

            errs = await tab.js("JSON.stringify(window.__errs || [])")
            check("no JavaScript errors", errs == "[]", errs)

            # 8. a small, short phone: the last row of icons must still be reachable
            await tab.call("Emulation.setDeviceMetricsOverride", width=360, height=640,
                           deviceScaleFactor=3, mobile=True)
            await asyncio.sleep(0.6)
            small = json.loads(await tab.js(
                "(p => { const g = p.querySelector('.grid'); const pb = p.getBoundingClientRect();"
                " const last = g.lastElementChild.getBoundingClientRect();"
                " return JSON.stringify({cut: last.bottom > pb.bottom + 1,"
                " scrollable: p.scrollHeight > p.clientHeight + 1,"
                " touch: getComputedStyle(document.getElementById('home')).touchAction}); })"
                "(document.querySelector('#pages .page'))"))
            check("a short phone can reach the last row of icons",
                  (not small["cut"]) or small["scrollable"], small)
            check("the home screen still allows vertical panning", small["touch"] == "pan-y", small["touch"])
            await tab.shot(ROOT / "out" / "touch-6-small.png")

            # and the horizontal swipe must survive pan-y
            await swipe(tab, 360 * 0.8, 640 * 0.4, 360 * 0.15, 640 * 0.4)
            await asyncio.sleep(0.6)
            check("the page swipe still works on a short phone", await tab.js("page === 1"),
                  await tab.js("page"))
    finally:
        for p in (edge, server):
            if p and p.poll() is None:
                p.terminate()
        await asyncio.sleep(0.4)

    print()
    if fails:
        print("TOUCH SMOKE FAILED: " + ", ".join(fails))
        raise SystemExit(1)
    print("TOUCH SMOKE PASSED")


if __name__ == "__main__":
    asyncio.run(main())
