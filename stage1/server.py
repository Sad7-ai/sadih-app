"""صادِح · live server. The browser streams the mic here; this process talks to Munsit, runs the
tracker + segmenter, and streams text back. The API key never reaches the browser.

  python server.py                 http://localhost:8000      (needs MUNSIT_API_KEY in .env)
  python server.py --mock          no key: a local mock plays a scripted transcript as you "speak"

  /            the playground (internal)      /app   the demo (a mock iPhone)
  /healthz     liveness, for the host         /config  what the page needs to know before connecting
  /ws/audio    browser -> server: binary PCM16 16 kHz mono, and {"type":"stop"}
               server -> browser: hello, interim, unit, latency, motion, motion_error, stats, error, done
  /ws/units    stage 2 connects here and receives every unit (the CONTRACT.md JSON)
  /avatar.glb  the SMPL-X body for the phone's avatar player (same access code as the mic)

Deployment knobs, all env vars (see render.yaml):
  MUNSIT_API_KEY          required unless --mock
  SADIH_ACCESS_CODE       if set, /ws/audio and /ws/units need ?code=… — anyone with the URL can
                          otherwise spend our Munsit credits
  SADIH_MAX_SESSIONS      how many people may listen at once (Munsit allows 5 per key)   default 3
  SADIH_MAX_SESSION_S     hard stop on one session, seconds                              default 900
  SADIH_LOG_TRANSCRIPTS   write what people said to out/. Off by default on a host, on locally.
  SADIH_MODEL_URL         where each clause goes to become motion (CONTRACT-MOTION.md): empty = off, the
                          app is captions only; "mock" = a still pose, no GPU; else the model service URL
  SADIH_MODEL_SECRET      the model service's bearer secret
  SADIH_SIGNER            signer token for the avatar's style                             default 02
  SADIH_AVATAR_GLB        the avatar body file (tools/smplx_to_glb.py)        default private/avatar.glb
"""
import utf8  # noqa: F401  must come before anything prints
import argparse
import asyncio
import hashlib
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import model_relay
from model_relay import ModelRelay
from munsit_client import MunsitClient
from pipeline import Pipeline

load_dotenv()
ROOT = Path(__file__).resolve().parent
WEB, OUT = ROOT / "web", ROOT / "out"
MOCK_PORT = 8766
subscribers: set[WebSocket] = set()
live_sessions: set[str] = set()
munsit_status = "unchecked"   # set once at startup — see check_key()
model_status = "off"          # set once at startup — model_relay.check()


def env(name: str, default: str = "") -> str:
    """Pasted secrets arrive with trailing newlines and sometimes wrapping quotes. Munsit answers
    a malformed key with a 1008 close and nothing else, so clean it here rather than guess later."""
    v = os.environ.get(name, default) or ""
    return v.strip().strip('"').strip("'")


def fingerprint(secret: str) -> str:
    """Enough to compare a key across two machines, never enough to use it."""
    if not secret:
        return "MISSING"
    return f"{len(secret)} chars, sha256:{hashlib.sha256(secret.encode()).hexdigest()[:12]}"


def _flag(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() not in ("0", "false", "no", "off", "")


def cfg():
    """Read every time, so a test can change the environment between runs."""
    return {
        "code": env("SADIH_ACCESS_CODE"),
        "max_sessions": int(os.environ.get("SADIH_MAX_SESSIONS", "3")),
        "max_session_s": int(os.environ.get("SADIH_MAX_SESSION_S", "900")),
        # on a host, never write what people said unless we are explicitly told to
        "log": _flag("SADIH_LOG_TRANSCRIPTS", default=not os.environ.get("RENDER")),
    }


def load_hotwords(path) -> list[str]:
    p = Path(path)
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


async def check_key() -> str:
    """Open one socket to Munsit at startup and read the first reply. No audio, so it costs nothing,
    and it answers the question the logs otherwise cannot: is the key ON THIS HOST actually valid?
    Munsit greets a good key with Metadata and closes a bad one with 1008."""
    import websockets
    key, url = env("MUNSIT_API_KEY"), env("MUNSIT_URL")
    if os.environ.get("SADIH_MOCK") == "1":
        return "mock"
    if not key:
        return "no_key"
    try:
        client = MunsitClient(key, url=url or None, correlation_id="startup-check")
        async with websockets.connect(client._url(), open_timeout=15, close_timeout=5) as ws:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            await ws.close()
            if msg.get("type") == "Metadata":
                return "ok"
            if msg.get("type") == "Error":
                return f"auth_failed ({msg.get('code')})"
            return f"unexpected ({msg.get('type')})"
    except websockets.exceptions.ConnectionClosed as e:
        return "auth_failed" if e.code == 1008 else f"closed_{e.code}"
    except asyncio.TimeoutError:
        return "timeout"
    except Exception as e:  # noqa: BLE001
        return f"unreachable ({type(e).__name__})"


@asynccontextmanager
async def lifespan(app: FastAPI):
    mock = None
    if os.environ.get("SADIH_MOCK") == "1":
        import mock_munsit
        mock_munsit.ARGS.loop = True
        mock = await mock_munsit.serve(MOCK_PORT)
        os.environ["MUNSIT_URL"] = f"ws://localhost:{MOCK_PORT}"
        print(f"MOCK MODE — scripted transcript, no Munsit, no credits (ws://localhost:{MOCK_PORT})")
    c = cfg()
    # so a key that differs between laptop and host is obvious in the log, without printing it
    print(f"MUNSIT_API_KEY: {fingerprint(env('MUNSIT_API_KEY'))}"
          + ("   (mock mode — the key is not used)" if os.environ.get("SADIH_MOCK") == "1" else ""))
    print(f"access code: {'ON' if c['code'] else 'off — anyone with the URL can use the mic'}  ·  "
          f"max {c['max_sessions']} at once  ·  session cap {c['max_session_s']}s  ·  "
          f"transcripts {'WRITTEN to out/' if c['log'] else 'not written'}")
    global munsit_status, model_status
    munsit_status = await check_key()
    model_status = await asyncio.to_thread(model_relay.check)
    print(f"model service: {model_status}")
    print(f"Munsit key check: {munsit_status.upper()}"
          + ("   <-- the key on THIS server is wrong. Fix MUNSIT_API_KEY in the host's environment."
             if munsit_status in ("auth_failed", "no_key") else ""))
    yield
    if mock:
        mock.close()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB), name="static")

NO_CACHE = {"Cache-Control": "no-store"}


@app.get("/healthz")
async def healthz():
    """`munsit` is the startup key check. It carries no secret — just whether this host's key works,
    which is the one thing a log-less deployment cannot otherwise tell us."""
    # the model service may start after this server (a pod), so ask it again, at most every 30 s
    return {"ok": munsit_status in ("ok", "mock"), "munsit": munsit_status,
            "model": await asyncio.to_thread(model_relay.check),
            "sessions": len(live_sessions)}


@app.get("/config")
async def config():
    """What the page needs before it connects — never the code itself, only whether one is needed."""
    c = cfg()
    m = model_relay.settings()
    has_body = avatar_file().exists() or (bool(m["url"]) and m["url"] != "mock"
                                          and await asyncio.to_thread(model_relay.remote_has_avatar))
    return JSONResponse({"needs_code": bool(c["code"]), "mock": os.environ.get("SADIH_MOCK") == "1",
                         "max_session_s": c["max_session_s"],
                         "avatar": bool(m["url"]) and has_body, "avatar_mock": m["url"] == "mock"},
                        headers=NO_CACHE)


def avatar_file() -> Path:
    return Path(env("SADIH_AVATAR_GLB") or ROOT / "private" / "avatar.glb")


@app.get("/avatar.glb")
async def avatar_glb(code: str = ""):
    """The SMPL-X body. Licensed, so it sits behind the same access code as the mic and is never in git."""
    want = cfg()["code"]
    if want and code != want:
        return JSONResponse({"error": "bad_code"}, status_code=403)
    f = avatar_file()
    if f.exists():
        return FileResponse(f, media_type="model/gltf-binary", headers={"Cache-Control": "private, max-age=3600"})
    data = await asyncio.to_thread(model_relay.fetch_avatar)     # the model service builds it from its SMPL-X file
    if data:
        return Response(data, media_type="model/gltf-binary", headers={"Cache-Control": "private, max-age=3600"})
    return JSONResponse({"error": "no avatar", "how": "give the model service SADIH_SMPLX, or run tools/smplx_to_glb.py "
                         "on SMPLX_NEUTRAL.npz and put the result at private/avatar.glb (or set SADIH_AVATAR_GLB)"},
                        status_code=404)


@app.get("/")
async def index():
    """The playground — internal testing: every unit, why it was cut, how late it was."""
    return FileResponse(WEB / "index.html", headers=NO_CACHE)


@app.get("/app")
async def phone():
    """The demo — a mock iPhone with صادِح inside it. This is what we show people.
    ?bare=1 drops the fake phone (what an installed app opens); ?frame=1 forces it back."""
    return FileResponse(WEB / "phone.html", headers=NO_CACHE)


@app.get("/manifest.webmanifest")
async def manifest():
    """Served from the root so `scope` covers the whole site — installable, and what
    PWABuilder reads to generate an APK."""
    return FileResponse(WEB / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker():
    """Must come from the root, or its scope would be /static/ and it could not control /app.
    Never cached, so a new deploy is picked up on the next visit."""
    return FileResponse(WEB / "sw.js", media_type="text/javascript",
                        headers={**NO_CACHE, "Service-Worker-Allowed": "/"})


@app.get("/.well-known/assetlinks.json")
async def assetlinks():
    """Digital Asset Links: proves this site and the APK belong together. Without it an installed
    APK shows Chrome's address bar across the top. Paste PWABuilder's file into web/assetlinks.json."""
    f = WEB / "assetlinks.json"
    if not f.exists():
        return JSONResponse({"error": "not configured",
                             "how": "put PWABuilder's assetlinks.json at stage1/web/assetlinks.json and redeploy"},
                            status_code=404)
    return FileResponse(f, media_type="application/json")


def code_ok(ws: WebSocket) -> bool:
    want = cfg()["code"]
    return not want or ws.query_params.get("code", "") == want


@app.websocket("/ws/units")
async def units_ws(ws: WebSocket):
    await ws.accept()
    if not code_ok(ws):
        await ws.send_text(json.dumps({"type": "error", "code": "bad_code", "message": "Wrong or missing access code."}))
        await ws.close(code=1008)
        return
    subscribers.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        subscribers.discard(ws)


async def refuse(ws: WebSocket, code: str, message: str):
    await ws.send_text(json.dumps({"type": "error", "code": code, "message": message}, ensure_ascii=False))
    await ws.send_text(json.dumps({"type": "done"}))
    await ws.close()


@app.websocket("/ws/audio")
async def audio_ws(ws: WebSocket):
    await ws.accept()
    c = cfg()

    if not code_ok(ws):
        return await refuse(ws, "bad_code", "رمز الدخول غير صحيح. · Wrong or missing access code.")
    if len(live_sessions) >= c["max_sessions"]:
        return await refuse(ws, "busy", f"الخدمة مشغولة الآن، حاول بعد قليل. · Busy: {c['max_sessions']} sessions already running.")

    session = uuid.uuid4().hex[:8]
    url, key = env("MUNSIT_URL"), env("MUNSIT_API_KEY")
    if not key and not url:
        return await refuse(ws, "no_key", "No MUNSIT_API_KEY set. Add it, or start the server with --mock.")

    live_sessions.add(session)
    outq: asyncio.Queue = asyncio.Queue()      # one ordered writer to the browser

    async def writer():
        while (m := await outq.get()) is not None:
            try:
                await ws.send_text(json.dumps(m, ensure_ascii=False))
            except Exception:  # noqa: BLE001  browser went away
                return

    wtask = asyncio.create_task(writer())
    relay = ModelRelay(outq.put_nowait, session) if model_relay.enabled() else None

    units_f = raw_f = None
    if c["log"]:
        OUT.mkdir(exist_ok=True)
        units_f = (OUT / f"{session}.units.jsonl").open("w", encoding="utf-8")
        raw_f = (OUT / f"{session}.raw.jsonl").open("w", encoding="utf-8")

    audio_q: asyncio.Queue = asyncio.Queue()

    async def source():
        while (chunk := await audio_q.get()) is not None:
            yield chunk

    def on_unit(unit: dict):
        line = json.dumps(unit, ensure_ascii=False)
        if units_f:
            units_f.write(line + "\n")
            units_f.flush()
        outq.put_nowait({"type": "unit", **unit})
        if relay:
            relay.submit(unit)
        for sub in list(subscribers):
            asyncio.create_task(sub.send_text(line))

    client = MunsitClient(key, url=url, model=env("MUNSIT_MODEL", "munsit-en-ar"),
                          endpointing=int(env("MUNSIT_ENDPOINTING", "300")), smart_turn=False,
                          hotwords=load_hotwords(ROOT / "hotwords.txt"), correlation_id=session)
    pipe = Pipeline(session, on_unit,
                    on_interim=lambda buf, pend: outq.put_nowait({"type": "interim", "buffer": buf, "pending": pend}),
                    on_latency=lambda uid, s: outq.put_nowait({"type": "latency", "unit_id": uid, "latency_s": s}),
                    stable_ms=int(env("SADIH_STABLE_MS", "600")))

    async def cap():
        """Hard stop, so a forgotten tab cannot bill us for an hour."""
        await asyncio.sleep(c["max_session_s"])
        outq.put_nowait({"type": "error", "code": "time_cap",
                         "message": f"انتهت مدة الجلسة ({c['max_session_s'] // 60} دقيقة). · Session time limit reached."})
        audio_q.put_nowait(None)

    async def pump():
        try:
            async for ev in client.events(source()):
                clock = client.audio_clock
                if raw_f:
                    raw_f.write(json.dumps({"clock": round(clock, 2), **ev}, ensure_ascii=False) + "\n")
                pipe.handle(ev, clock)
                typ = ev.get("type")
                if typ == "Metadata" and "audio_seconds_billed" not in ev:
                    outq.put_nowait({"type": "hello", "session": session, "model": ev.get("model"),
                                     "mock": bool(url and "localhost" in url),
                                     "max_session_s": c["max_session_s"],
                                     "dropped_hotwords": ev.get("dropped_hotwords") or []})
                elif typ == "Error":
                    outq.put_nowait({"type": "error", "message": f"Munsit {ev.get('code')}: {ev.get('message')}"})
                elif typ == "_Closed" and ev.get("code") not in (1000, None):
                    # 1008 is the one that looks like our bug but never is: bad key, no wallet
                    # balance, or too many sessions on the key. Name all three.
                    msg = (f"Munsit rejected the server's API key ({ev.get('reason') or 'authentication required'}). "
                           f"Check MUNSIT_API_KEY on the server, and that the Munsit wallet has credit."
                           if ev.get("code") == 1008 else
                           f"Munsit closed the socket ({ev.get('code')}): {ev.get('reason') or 'see raw log'}")
                    outq.put_nowait({"type": "error", "code": "munsit_" + str(ev.get("code")), "message": msg})
        except Exception as e:  # noqa: BLE001
            outq.put_nowait({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            stats = pipe.finish(client.audio_clock)
            if c["log"]:
                (OUT / f"{session}.stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
            outq.put_nowait({"type": "stats", **stats})
            if relay:       # the last clips are still being made: "done" must come after them
                await relay.drain(float(os.environ.get("SADIH_MODEL_DRAIN_S", "90")))
            outq.put_nowait({"type": "done"})

    ptask = asyncio.create_task(pump())
    ctask = asyncio.create_task(cap())
    t0 = time.perf_counter()
    gone = False
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                gone = True
                break
            if msg.get("bytes"):
                audio_q.put_nowait(msg["bytes"])
            elif msg.get("text") and json.loads(msg["text"]).get("type") == "stop":
                audio_q.put_nowait(None)      # -> CloseStream; keep the socket open for the last units
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        ctask.cancel()
        audio_q.put_nowait(None)
        if relay and gone:
            relay.cancel()      # nobody to show the clips to: stop spending GPU on them
        try:
            await asyncio.wait_for(ptask, 15 + (float(os.environ.get("SADIH_MODEL_DRAIN_S", "90")) if relay else 0))
        except asyncio.TimeoutError:
            ptask.cancel()
        outq.put_nowait(None)
        await wtask
        for f in (units_f, raw_f):
            if f:
                f.close()
        live_sessions.discard(session)
        print(f"session {session} ended after {time.perf_counter() - t0:.0f}s  ·  {len(live_sessions)} still running")


if __name__ == "__main__":
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="no key needed: scripted transcript driven by your audio clock")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    a = ap.parse_args()
    if a.mock:
        os.environ["SADIH_MOCK"] = "1"
    print(f"صادِح — demo  http://localhost:{a.port}/app     playground  http://localhost:{a.port}/")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
