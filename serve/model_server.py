"""صادِح · model service. Loads the generator once and answers one clause at a time (stage1/CONTRACT-MOTION.md).

  python model_server.py --mock                    no GPU, no weights: a still pose of the right length
  python model_server.py --mock --clip <dir>       ... or replay recorded clips in turn, at their own length
  python model_server.py --recorded <motion/<variant>>   real recorded signing of the sentence said (team "lookup")
  python model_server.py                           the real generator (env vars below), e.g. on a RunPod pod

  POST /sign      {"unit_id", "text", "signer"?}  ->  motion reply (see the contract)
  GET  /healthz   loaded?, which model, which device, load time, last timings. Never a secret.
  GET  /avatar.glb the SMPL-X body for the phone, built from the SMPL-X file this box already has (same secret).
                  So the licensed file never has to sit in git or on the app's host.

Env:
  SADIH_MODEL_SECRET   callers must send "Authorization: Bearer <it>". Required unless --mock on 127.0.0.1.
  SADIH_MODEL_CODE     kitchen checkout of the MODEL branch (has avatar/exp4_generator/demo_generate.py)
  SADIH_DATA           the Drive root copy (tokens/, tokenizer/, deps/smpl_models/, exp4_generator/runs/)
  SADIH_RUN_ID         which checkpoint (default madis_a_v4_joint_r2). Swapping models = change this, restart.
  SADIH_RUN_DIR        default $SADIH_DATA/exp4_generator/runs/$SADIH_RUN_ID
  SADIH_MADIS, SADIH_SOKE, SADIH_SMPLX, SADIH_SIGNER (02), SADIH_LENGTH_PREDICTOR (heuristic), SADIH_DEVICE
  SADIH_MOCK_CLIP      with --mock: a recorded clip or a folder of them (same as --clip)
  SADIH_RECORDED       with the real generator: the motion pack folder motion/<variant>/. A clause that is one of its
                       recorded sentences plays the real recording; anything else is generated ("source" says which)
"""
import argparse
import asyncio
import hmac
import os
import sys
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse, Response  # noqa: E402

import backends  # noqa: E402
import motion  # noqa: E402

MAX_TEXT = 300
APP_TOOLS = Path(__file__).resolve().parent.parent / "stage1" / "tools"     # smplx_to_glb.py lives with the app
_AVATAR: dict = {}
STATE = {"backend": None, "error": None, "kind": os.environ.get("SADIH_BACKEND", "demo"),
         "clip": os.environ.get("SADIH_MOCK_CLIP") or None, "requests": 0, "failures": 0, "last": deque(maxlen=20)}


def secret() -> str:
    return (os.environ.get("SADIH_MODEL_SECRET") or "").strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    t0 = time.perf_counter()
    try:
        # loading takes a while on a GPU box; the event loop stays free so /healthz answers "loading"
        STATE["backend"] = await asyncio.to_thread(backends.make, STATE["kind"], STATE["clip"])
        print(f"model service ready: {STATE['backend'].info()}  ({time.perf_counter() - t0:.1f} s)", flush=True)
    except Exception as e:  # noqa: BLE001
        STATE["error"] = f"{type(e).__name__}: {e}"
        print(f"model service FAILED to load: {STATE['error']}", flush=True)
    yield


app = FastAPI(lifespan=lifespan)


def _err(status: int, code: str, message: str, unit_id=None):
    return JSONResponse({"error": code, "message": message, "unit_id": unit_id}, status_code=status)


def _authorised(req: Request) -> bool:
    want = secret()
    if not want:
        return True
    got = req.headers.get("authorization", "")
    return hmac.compare_digest(got.encode(), f"Bearer {want}".encode())


@app.get("/healthz")
async def healthz():
    b = STATE["backend"]
    last = list(STATE["last"])
    return {"ok": b is not None, "state": "ready" if b else ("failed" if STATE["error"] else "loading"),
            "error": STATE["error"], **(b.info() if b else {}), "format": motion.FORMAT, "fps": motion.FPS,
            "avatar": bool(b and getattr(b, "smplx", None)),
            "requests": STATE["requests"], "failures": STATE["failures"], "needs_secret": bool(secret()),
            "last": last[-5:]}


@app.post("/sign")
async def sign(req: Request):
    if not _authorised(req):
        return _err(401, "bad_secret", "Missing or wrong Authorization bearer secret.")
    b = STATE["backend"]
    if b is None:
        return _err(503, "not_ready", STATE["error"] or "The model is still loading.")
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        return _err(400, "bad_json", "Body must be JSON.")
    unit_id = body.get("unit_id")
    text = body.get("text")
    signer = str(body.get("signer") or os.environ.get("SADIH_SIGNER", "02"))
    if not isinstance(text, str) or not text.strip():
        return _err(400, "no_text", "text is empty.", unit_id)
    if len(text) > MAX_TEXT:
        return _err(400, "too_long", f"text is longer than {MAX_TEXT} characters.", unit_id)
    STATE["requests"] += 1
    t0 = time.perf_counter()
    try:
        g = await asyncio.to_thread(b.sign, text, signer)
        feat = g["feat"]
        payload = motion.encode(feat)
    except backends.NoRecording as e:
        return _err(404, "no_recording", str(e), unit_id)
    except Exception as e:  # noqa: BLE001  never a traceback to the caller; the message is enough to act on
        STATE["failures"] += 1
        print(f"sign failed for unit {unit_id}: {type(e).__name__}: {e}", flush=True)
        return _err(500, "generate_failed", f"{type(e).__name__}: {e}"[:300], unit_id)
    frames = int(len(feat))
    conf = g.get("confidence")
    try:
        conf = None if conf is None else round(float(conf), 4)
    except (TypeError, ValueError):
        conf = None
    total = round(time.perf_counter() - t0, 3)
    STATE["last"].append({"unit_id": unit_id, "frames": frames, "generate_s": g["generate_s"],
                          "decode_s": g["decode_s"], "total_s": total})
    if g.get("matched"):
        STATE["last"][-1]["matched"] = g["matched"]
    return {"unit_id": unit_id, "model": g.get("model", b.model_id), "source": g.get("source", b.name),
            "format": motion.FORMAT, "fps": motion.FPS, "frames": frames,
            "dtype": "float16", "motion": payload, "tokens": g["tokens"], "normalised": g["normalised"],
            "unseen_words": g["unseen_words"], "confidence": conf, "generate_s": g["generate_s"],
            "decode_s": g["decode_s"], "total_s": total}


@app.get("/avatar.glb")
async def avatar_glb(req: Request):
    if not _authorised(req):
        return _err(401, "bad_secret", "Missing or wrong Authorization bearer secret.")
    b = STATE["backend"]
    src = getattr(b, "smplx", None) if b else None
    if not src:
        return _err(404, "no_smplx", "This model service has no SMPLX_NEUTRAL.npz (set SADIH_SMPLX).")
    if src not in _AVATAR:
        sys.path.insert(0, str(APP_TOOLS))
        import smplx_to_glb as sg
        _AVATAR[src] = await asyncio.to_thread(lambda: sg.build_glb(sg.load_model(src)))
    return Response(_AVATAR[src], media_type="model/gltf-binary", headers={"Cache-Control": "no-store"})


def main():
    import uvicorn
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock", action="store_true", help="no GPU: still pose (or --clip), right length")
    ap.add_argument("--clip", help="with --mock: a recorded (frames, 133) .npy, or a folder of them, to replay")
    ap.add_argument("--recorded", help="the motion folder motion/<variant>/ (feat/ + meta/): play the real recording "
                    "of the sentence said; no generator, no GPU")
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8100")))
    a = ap.parse_args()
    STATE["kind"] = "recorded" if a.recorded else "mock" if a.mock else STATE["kind"]
    STATE["clip"] = a.recorded or a.clip or STATE["clip"]
    if not secret() and not ((a.mock or a.recorded) and a.host in ("127.0.0.1", "localhost")):
        sys.exit("set SADIH_MODEL_SECRET: anyone who finds this address could otherwise use the GPU")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
