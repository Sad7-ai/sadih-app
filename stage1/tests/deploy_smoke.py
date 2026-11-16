"""The things that only matter once this is on the internet. No browser — plain HTTP and websockets.

  python tests/deploy_smoke.py

Checks, each against a server started with the relevant env:
  1. /healthz and /config answer, and /config never leaks the code itself
  2. with SADIH_ACCESS_CODE set: /ws/audio and /ws/units refuse without it, accept with it
  3. SADIH_MAX_SESSIONS is enforced — the (n+1)th listener is told the service is busy
  4. SADIH_MAX_SESSION_S stops a session that will not stop itself
  5. SADIH_LOG_TRANSCRIPTS=0 writes NOTHING to out/, which is what a host must do
  6. the server-only requirements are enough to import server.py
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import utf8  # noqa: F401,E402

import requests  # noqa: E402
import websockets  # noqa: E402

CODE = "letmein-7Q"
SILENCE = bytes(3200)            # 100 ms of 16 kHz mono PCM16


class Server:
    """A server with a given environment, torn down afterwards."""

    def __init__(self, port, **env):
        self.port = port
        self.env = {**os.environ, "PYTHONUTF8": "1", "SADIH_MOCK": "1", **{k: str(v) for k, v in env.items()}}
        self.env.pop("MUNSIT_API_KEY", None)
        self.p = None

    def __enter__(self):
        self.p = subprocess.Popen([sys.executable, "server.py", "--mock", "--port", str(self.port)],
                                  cwd=ROOT, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        t0 = time.time()
        while time.time() - t0 < 40:
            try:
                requests.get(f"{self.url}/healthz", timeout=1)
                return self
            except requests.RequestException:
                time.sleep(0.25)
        raise SystemExit("server did not start")

    def __exit__(self, *a):
        if self.p and self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.p.kill()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    @property
    def ws(self):
        return f"ws://127.0.0.1:{self.port}"


async def first_message(url, send_audio=False, seconds=0.0):
    """Open /ws/audio, optionally feed silence, return every message until done (or the timeout)."""
    msgs = []
    async with websockets.connect(url, max_size=None) as ws:
        async def feed():
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < seconds:
                await ws.send(SILENCE)
                await asyncio.sleep(0.1)

        task = asyncio.create_task(feed()) if send_audio else None
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(4.0, seconds + 6))
                m = json.loads(raw)
                msgs.append(m)
                if m.get("type") == "done":
                    break
        except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
            pass
        finally:
            if task:
                task.cancel()
    return msgs


def kinds(msgs):
    return [m.get("type") for m in msgs]


async def main():
    out = ROOT / "out"

    # ---------- 1 + 2: health, config, and the access code ----------
    with Server(8031, SADIH_ACCESS_CODE=CODE, SADIH_LOG_TRANSCRIPTS=1) as s:
        h = requests.get(f"{s.url}/healthz", timeout=5).json()
        c = requests.get(f"{s.url}/config", timeout=5).json()
        assert h.get("ok") is True, h
        assert c["needs_code"] is True and c["mock"] is True, c
        assert CODE not in json.dumps(c), "/config leaked the access code"
        print(f"1. /healthz {h}  ·  /config {c}")

        no_code = await first_message(f"{s.ws}/ws/audio")
        assert no_code and no_code[0].get("code") == "bad_code", no_code
        wrong = await first_message(f"{s.ws}/ws/audio?code=nope")
        assert wrong and wrong[0].get("code") == "bad_code", wrong
        ok = await first_message(f"{s.ws}/ws/audio?code={CODE}", send_audio=True, seconds=2.0)
        assert "hello" in kinds(ok), kinds(ok)
        print(f"2. no code -> {no_code[0]['code']} · wrong -> {wrong[0]['code']} · right -> {kinds(ok)[:3]}")

        async with websockets.connect(f"{s.ws}/ws/units") as u:
            m = json.loads(await asyncio.wait_for(u.recv(), timeout=5))
            assert m.get("code") == "bad_code", m
        print("   /ws/units also refuses without the code")

    # ---------- 3: how many at once ----------
    with Server(8032, SADIH_MAX_SESSIONS=1, SADIH_LOG_TRANSCRIPTS=0) as s:
        held = await websockets.connect(f"{s.ws}/ws/audio", max_size=None)
        await held.send(SILENCE)
        await asyncio.sleep(0.8)
        second = await first_message(f"{s.ws}/ws/audio")
        await held.close()
        assert second and second[0].get("code") == "busy", second
        print(f"3. 2nd listener with max=1 -> {second[0]['code']}: {second[0]['message'][:48]}…")

    # ---------- 4: the time cap ----------
    with Server(8033, SADIH_MAX_SESSION_S=3, SADIH_LOG_TRANSCRIPTS=0) as s:
        t0 = time.perf_counter()
        msgs = await first_message(f"{s.ws}/ws/audio", send_audio=True, seconds=12.0)
        took = time.perf_counter() - t0
        caps = [m for m in msgs if m.get("code") == "time_cap"]
        assert caps, kinds(msgs)
        assert took < 11, f"cap fired but the session ran {took:.1f}s"
        print(f"4. cap 3s -> {caps[0]['code']} after {took:.1f}s, then {kinds(msgs)[-2:]}")

    # ---------- 5: a host must not keep what people said ----------
    before = {p.name for p in out.glob("*")} if out.exists() else set()
    with Server(8034, SADIH_LOG_TRANSCRIPTS=0) as s:
        msgs = await first_message(f"{s.ws}/ws/audio", send_audio=True, seconds=8.0)
    after = {p.name for p in out.glob("*")} if out.exists() else set()
    units = [m for m in msgs if m.get("type") == "unit"]
    assert units, "no units came back, so this proves nothing about logging"
    assert after == before, f"transcripts were written with logging off: {sorted(after - before)}"
    print(f"5. logging off: {len(units)} units streamed, {len(after - before)} files written to out/")

    with Server(8035, SADIH_LOG_TRANSCRIPTS=1) as s:
        msgs = await first_message(f"{s.ws}/ws/audio", send_audio=True, seconds=8.0)
    wrote = {p.name for p in out.glob("*")} - after
    assert wrote, "logging ON wrote nothing — the flag is not doing anything"
    for p in wrote:
        (out / p).unlink(missing_ok=True)
    print(f"   logging on : wrote {len(wrote)} files (removed again)")

    # ---------- 6: the deploy only installs requirements-server.txt ----------
    req = (ROOT / "requirements-server.txt").read_text(encoding="utf-8")
    need = {l.split(">")[0].split("[")[0].strip().lower()
            for l in req.splitlines() if l.strip() and not l.startswith("#")}
    assert {"fastapi", "uvicorn", "websockets", "python-dotenv"} <= need, need
    for heavy in ("sounddevice", "soundfile", "scipy", "numpy"):
        assert heavy not in need, f"{heavy} would be installed on the server but is not needed there"
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "from stage1 import" not in src, "server.py still imports the CLI, which drags numpy/scipy in"
    print(f"6. server needs only {sorted(need)}")

    print("\nDEPLOY SMOKE PASSED")


if __name__ == "__main__":
    asyncio.run(main())
