"""Speech -> clauses -> model -> motion, through the real server, without a browser or a GPU. ~90 s.
    python tests/e2e_model.py

Five sessions on one server (mock Munsit), changing only where clauses go:
  off          SADIH_MODEL_URL unset: no motion messages at all (the live app as it was)
  mock         the in-process stand-in
  service      serve/model_server.py --mock in its own process, with a bearer secret
  bad secret   every clause gets motion_error 401, captions unchanged
  unreachable  every clause gets motion_error, captions unchanged
plus /config's avatar flag and /avatar.glb behind the access code.
"""
import asyncio
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.chdir(ROOT)
os.environ["SADIH_MOCK"] = "1"
os.environ["SADIH_LOG_TRANSCRIPTS"] = "0"
os.environ.pop("MUNSIT_API_KEY", None)
for k in ("SADIH_MODEL_URL", "SADIH_MODEL_SECRET", "SADIH_ACCESS_CODE"):
    os.environ.pop(k, None)

import utf8  # noqa: F401,E402
import uvicorn  # noqa: E402
import websockets  # noqa: E402

import server  # noqa: E402
from e2e_mock import EXPECTED  # noqa: E402
from sources import silence_source  # noqa: E402

PORT = 8013
PASSED = []


def ok(msg):
    PASSED.append(msg)
    print("ok  ", msg)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def heuristic_frames(text: str) -> int:
    return 4 * max(10, min(100, int(round(17.41 + 4.05 * max(1, len(text.split()))))))


async def session() -> list:
    msgs = []
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/audio", max_size=None) as ws:
        async def send():
            async for chunk in silence_source(16):
                await ws.send(chunk)
            await ws.send(json.dumps({"type": "stop"}))
        st = asyncio.create_task(send())
        async for raw in ws:
            m = json.loads(raw)
            msgs.append(m)
            if m["type"] == "done":
                break
        await st
    return msgs


def check_captions(msgs, label):
    units = [m for m in msgs if m["type"] == "unit"]
    assert [u["text"] for u in units] == EXPECTED, (label, [u["text"] for u in units])
    assert msgs[-1]["type"] == "done", label
    return units


def _get(path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


async def get(path):
    """The server runs on this event loop, so a blocking request must leave it free to answer."""
    return await asyncio.to_thread(_get, path)


async def main():
    tmp = Path(tempfile.mkdtemp(prefix="sadih_e2e_model_"))
    glb = tmp / "avatar.glb"
    glb.write_bytes(b"glTF-test-bytes")
    os.environ["SADIH_AVATAR_GLB"] = str(glb)
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=PORT, log_level="warning"))
    stask = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.05)
    model = None
    try:
        # ---- off
        cf = json.loads((await get("/config"))[1])
        assert cf["avatar"] is False
        msgs = await session()
        check_captions(msgs, "off")
        assert not [m for m in msgs if m["type"].startswith("motion")]
        ok("off: no SADIH_MODEL_URL -> captions only, no motion messages, /config says no avatar")

        # ---- mock
        os.environ["SADIH_MODEL_URL"] = "mock"
        cf = json.loads((await get("/config"))[1])
        assert cf["avatar"] is True and cf["avatar_mock"] is True
        msgs = await session()
        units = check_captions(msgs, "mock")
        mot = [m for m in msgs if m["type"] == "motion"]
        assert [m["unit_id"] for m in mot] == [u["unit_id"] for u in units], "one clip per unit, in order"
        for u, m in zip(units, mot):
            assert m["frames"] == heuristic_frames(u["text"]) and m["fps"] == 24 and m["format"] == "soke133"
            assert len(base64.b64decode(m["motion"])) == m["frames"] * 133 * 2
            assert msgs.index(m) > msgs.index(u), "a clip never arrives before its caption"
        assert msgs.index(mot[-1]) < len(msgs) - 1 and msgs[-1]["type"] == "done"
        ok(f"mock: {len(mot)} clips for {len(units)} units, in unit order, each after its caption, all before 'done'")

        # ---- service: the real HTTP path, model service in its own process
        mport = free_port()
        env = {**os.environ, "SADIH_MODEL_SECRET": "s3cret", "PYTHONUTF8": "1"}
        sys.path.insert(0, str(ROOT / "tests"))
        import test_glb
        test_glb.synthetic_npz(tmp / "SMPLX_NEUTRAL.npz")
        env["SADIH_SMPLX"] = str(tmp / "SMPLX_NEUTRAL.npz")
        model = subprocess.Popen([sys.executable, str(REPO / "serve" / "model_server.py"), "--mock", "--port", str(mport)],
                                 env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{mport}/healthz", timeout=1) as r:
                    if json.loads(r.read())["ok"]:
                        break
            except Exception:  # noqa: BLE001
                time.sleep(0.1)
        os.environ.update(SADIH_MODEL_URL=f"http://127.0.0.1:{mport}", SADIH_MODEL_SECRET="s3cret")
        msgs = await session()
        units = check_captions(msgs, "service")
        mot = [m for m in msgs if m["type"] == "motion"]
        assert [m["unit_id"] for m in mot] == [u["unit_id"] for u in units] and all(m["model"] == "mock" for m in mot)
        assert all(m["frames"] == heuristic_frames(u["text"]) for u, m in zip(units, mot))
        assert not [m for m in msgs if m["type"] == "motion_error"]
        ok(f"service: serve/model_server.py over HTTP with a secret -> {len(mot)} clips, same order, same lengths")
        # health now reports the model service
        os.environ["SADIH_MODEL_URL"] = f"http://127.0.0.1:{mport}"
        import model_relay
        assert await asyncio.to_thread(model_relay.check) == "ok (mock)"
        ok("health: the model service is reported as 'ok (mock)'")
        os.environ["SADIH_AVATAR_GLB"] = str(tmp / "no-local-file.glb")
        assert json.loads((await get("/config"))[1])["avatar"] is True
        st, body = await get("/avatar.glb")
        assert st == 200 and body[:4] == b"glTF"
        os.environ["SADIH_AVATAR_GLB"] = str(glb)
        ok("avatar.glb with no local file: fetched from the model service (built from its SMPL-X), /config says avatar")

        # every request names itself: RunPod's proxy refuses urllib's default User-Agent with 403
        seen = []
        real = urllib.request.urlopen
        urllib.request.urlopen = lambda req, *a, **k: (seen.append(req), real(req, *a, **k))[1]
        try:
            model_relay._INFO["at"] = 0.0
            await asyncio.to_thread(model_relay.post_sign, os.environ["SADIH_MODEL_URL"], "s3cret",
                                    {"unit_id": 1, "text": "ماذا تعمل"}, 30)
            await asyncio.to_thread(model_relay.remote_info, 5.0, 0.0)
        finally:
            urllib.request.urlopen = real
        assert seen and all(isinstance(r, urllib.request.Request) and r.get_header("User-agent", "").startswith("sadih-app")
                            for r in seen), [getattr(r, "headers", r) for r in seen]
        ok("every request to the model service carries the sadih-app User-Agent (RunPod's proxy 403s urllib's default)")

        # ---- bad secret
        os.environ["SADIH_MODEL_SECRET"] = "wrong"
        msgs = await session()
        check_captions(msgs, "bad secret")
        errs = [m for m in msgs if m["type"] == "motion_error"]
        assert len(errs) == len(EXPECTED) and all("401" in e["message"] for e in errs), errs[:2]
        ok("bad secret: every clause gets motion_error 401, captions unchanged")

        # ---- unreachable
        os.environ.update(SADIH_MODEL_URL=f"http://127.0.0.1:{free_port()}", SADIH_MODEL_SECRET="s3cret")
        msgs = await session()
        check_captions(msgs, "unreachable")
        errs = [m for m in msgs if m["type"] == "motion_error"]
        assert len(errs) == len(EXPECTED) and all("unreachable" in e["message"] for e in errs), errs[:2]
        ok("unreachable model: every clause gets motion_error, captions unchanged, session ends normally")

        # ---- the avatar file sits behind the access code
        os.environ["SADIH_ACCESS_CODE"] = "letmein"
        assert (await get("/avatar.glb"))[0] == 403 and (await get("/avatar.glb?code=nope"))[0] == 403
        st, body = await get("/avatar.glb?code=letmein")
        assert st == 200 and body == b"glTF-test-bytes"
        os.environ.pop("SADIH_ACCESS_CODE")
        os.environ["SADIH_AVATAR_GLB"] = str(tmp / "missing.glb")
        assert (await get("/avatar.glb"))[0] == 404 and json.loads((await get("/config"))[1])["avatar"] is False
        ok("avatar.glb: 403 without the code, served with it, 404 + no avatar in /config when the file is missing")
    finally:
        if model and model.poll() is None:
            model.terminate()
        srv.should_exit = True
        await stask
    print(f"\n{len(PASSED)} passed\nMODEL E2E PASSED")


if __name__ == "__main__":
    asyncio.run(main())
