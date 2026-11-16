"""The avatar player in a real browser (headless Edge, fake mic, WebGL in software). ~40 s.
    python tests/avatar_smoke.py

No licensed file: the body is tests/test_glb.py's synthetic SMPL-X, converted by tools/smplx_to_glb.py, and the
model is the in-process mock (SADIH_MODEL_URL=mock). It checks:
  1. the page loads the avatar only because the server has a model and a body file
  2. three.js poses each of the 41 driven joints exactly where SMPL-X math puts it (numpy reference)
  3. speaking: one clip per clause arrives, plays, and the player keeps count; no page errors
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))
os.chdir(ROOT)
import utf8  # noqa: F401,E402
import websockets  # noqa: E402

import smplx_to_glb as sg  # noqa: E402
import test_glb as tg  # noqa: E402
from demo_smoke import EDGE, Tab, wait_http  # noqa: E402

PORT, CDP = 8015, 9336
# feature offset -> joint, as in web/avatar.js and CONTRACT-MOTION.md
MAP = [(3 * k, 12 + k) for k in range(10)] + [(30 + 3 * k, 25 + k) for k in range(15)] + \
      [(75 + 3 * k, 40 + k) for k in range(15)] + [(120, 22)]


async def main():
    tmp = Path(tempfile.mkdtemp(prefix="sadih_avatar_"))
    tg.synthetic_npz(tmp / "synthetic.npz")
    data = sg.build_glb(sg.load_model(tmp / "synthetic.npz"))
    (tmp / "avatar.glb").write_bytes(data)
    js_glb, bin_glb = sg.read_glb(data)
    env = {**os.environ, "PYTHONUTF8": "1", "SADIH_MODEL_URL": "mock", "SADIH_AVATAR_GLB": str(tmp / "avatar.glb"),
           "SADIH_LOG_TRANSCRIPTS": "0"}
    for k in ("SADIH_ACCESS_CODE", "MUNSIT_API_KEY"):
        env.pop(k, None)
    server = subprocess.Popen([sys.executable, "server.py", "--mock", "--port", str(PORT)], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    profile = tempfile.mkdtemp(prefix="sadih-edge-")
    edge = None
    passed = []
    try:
        wait_http(f"http://127.0.0.1:{PORT}/healthz")
        edge = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={CDP}", f"--user-data-dir={profile}",
                                 "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                 "--autoplay-policy=no-user-gesture-required", "--window-size=430,932",
                                 "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--no-first-run",
                                 "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        page = next(t for t in wait_http(f"http://127.0.0.1:{CDP}/json").json() if t["type"] == "page")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            tab = Tab(ws)
            await tab.call("Page.enable")
            await tab.call("Network.setCacheDisabled", cacheDisabled=True)
            await tab.call("Page.addScriptToEvaluateOnNewDocument", source=(
                "window.__errs = []; addEventListener('error', e => __errs.push(String(e.message)));"
                "addEventListener('unhandledrejection', e => __errs.push(String(e.reason)));"))
            await tab.call("Page.navigate", url=f"http://localhost:{PORT}/app?mode=bare")
            await tab.until("window.sadihAvatar && (sadihAvatar.stats.loaded || sadihAvatar.stats.error)", 30,
                            "the avatar never loaded")
            st = await tab.js("sadihAvatar.stats")
            assert st["loaded"] and not st["error"], st
            assert await tab.js("!document.getElementById('sd-avatar').hidden && document.querySelector('.av-canvas') !== null")
            passed.append("avatar shown because the server has a model and a body file; WebGL canvas up")

            rng = np.random.default_rng(3)
            worst = 0.0
            for _ in range(3):
                row = rng.normal(0, 0.5, 133)
                pose = np.zeros((55, 3))
                for off, j in MAP:
                    pose[j] = row[off:off + 3]
                _, ref = tg.gltf_pose(js_glb, bin_glb, pose)
                got = await tab.js(f"(() => {{ sadihAvatar.poseForTest({json.dumps(row.tolist())});"
                                   f" return {json.dumps([j for _, j in MAP])}.map(j => sadihAvatar.jointWorld(j)); }})()")
                worst = max(worst, float(np.abs(np.array(got) - ref[[j for _, j in MAP]]).max()))
            assert worst < 1e-4, worst
            passed.append(f"three.js joint positions == SMPL-X math for 41 driven joints, 3 random poses (max error {worst:.1e} m)")

            await tab.js("document.getElementById('sd-mic').click()")
            await tab.until("window.sadihAvatar.stats.received >= 3 && sadihAvatar.stats.played >= 1", 45,
                            "clips never arrived or never played")
            mid = await tab.js("sadihAvatar.stats")
            await tab.shot(ROOT / "out" / "avatar-smoke.png") if (ROOT / "out").is_dir() else None
            await tab.until("client.state === 'idle' || client.units.length >= 7", 30, "the session did not finish")
            await tab.js("client.state === 'live' && client.stop()")
            await tab.until("client.state === 'idle'", 40, "the session never ended")
            await tab.until("sadihAvatar.stats.received === client.units.length", 20, "a clip went missing")
            end = await tab.js("({...sadihAvatar.stats, units: client.units.length, errs: window.__errs})")
            try:
                await tab.call("Browser.close")
            except Exception:  # noqa: BLE001
                pass
        print("while speaking:", json.dumps(mid))
        print("at the end:", json.dumps(end, ensure_ascii=False))
        assert end["received"] == end["units"] >= 4, end
        assert mid["model"] == "mock" and not end["errs"], end
        passed.append(f"speaking: {end['received']} clips for {end['units']} clauses, {end['played']} played so far, "
                      f"{end['queued']} queued, no page errors")
        for p in passed:
            print("ok  ", p)
        print(f"{len(passed)} passed\nAVATAR SMOKE PASSED")
    finally:
        for p in (edge, server):
            if p and p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    asyncio.run(main())
