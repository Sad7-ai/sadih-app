"""Clause -> model service -> motion, one session at a time, in unit order (CONTRACT-MOTION.md).

The server makes one ModelRelay per /ws/audio session. Each stage 1 unit is queued; a single worker sends them to
the model service one by one and hands every reply to `emit` as {"type": "motion", ...}, or
{"type": "motion_error", ...} when a clause fails. Nothing here can stop the captions: a slow, broken or missing
model only delays or drops avatar clips.

SADIH_MODEL_URL decides where clauses go:
  ""        off (the default). The app is exactly what it was: captions only.
  "mock"    an in-process stand-in: a still pose of roughly the right length. No GPU, no network.
  "https://..."   the model service (serve/model_server.py), with SADIH_MODEL_SECRET as its bearer secret.

Standard library only, so the hosted server needs no new package.
"""
import asyncio
import base64
import json
import os
import re
import struct
import time
import urllib.error
import urllib.request

DIM, FPS, UNIT = 133, 24, 4
# RunPod's proxy (Cloudflare) answers 403 to urllib's default "Python-urllib/x.y" User-Agent before the request ever
# reaches the model service (found 2026-11-08 on the first pod), so every request names itself.
UA = {"User-Agent": "sadih-app/1.0 (model relay)"}
TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")


def settings() -> dict:
    url = (os.environ.get("SADIH_MODEL_URL") or "").strip().rstrip("/")
    return {"url": url, "secret": (os.environ.get("SADIH_MODEL_SECRET") or "").strip(),
            "signer": (os.environ.get("SADIH_SIGNER") or "02").strip(),
            "timeout_s": float(os.environ.get("SADIH_MODEL_TIMEOUT_S", "60"))}


def enabled() -> bool:
    return bool(settings()["url"])


def mock_reply(unit_id, text: str) -> dict:
    """What serve/backends.MockBackend answers, without the HTTP hop: a still arms-down pose of the heuristic length."""
    words = " ".join(TASHKEEL.sub("", text).split()).split()
    tokens = max(10, min(100, int(round(17.41 + 4.05 * max(1, len(words))))))
    frames = tokens * UNIT
    row = [0.0] * DIM
    row[3 * 4 + 2], row[3 * 5 + 2] = -1.2, 1.2      # arms down (web/avatar.js IDLE); zeros would be the T-pose
    still = struct.pack(f"<{DIM}e", *row) * frames
    return {"unit_id": unit_id, "model": "mock", "source": "mock", "format": "soke133", "fps": FPS, "frames": frames,
            "dtype": "float16", "motion": base64.b64encode(still).decode("ascii"), "tokens": tokens,
            "normalised": " ".join(words), "unseen_words": [], "generate_s": 0.0, "decode_s": 0.0}


def post_sign(url: str, secret: str, body: dict, timeout_s: float) -> dict:
    """Blocking POST (run in a thread). Returns the reply, or raises RuntimeError with a message a person can act on."""
    req = urllib.request.Request(url + "/sign", data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **UA,
                                          **({"Authorization": f"Bearer {secret}"} if secret else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("message", "")
        except Exception:  # noqa: BLE001
            detail = ""
        raise RuntimeError(f"model service answered {e.code}" + (f": {detail}" if detail else "")) from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"model service unreachable ({e.reason})") from None
    except TimeoutError:
        raise RuntimeError(f"model service took longer than {timeout_s:.0f} s") from None


_INFO = {"at": 0.0, "url": None, "info": {}}
_AVATAR = {"url": None, "bytes": None}


def remote_info(timeout_s: float = 5.0, max_age_s: float = 30.0) -> dict:
    """The model service's /healthz, cached for 30 s: the pod may come up after this server does."""
    s = settings()
    if not s["url"] or s["url"] == "mock":
        return {}
    if _INFO["url"] == s["url"] and time.monotonic() - _INFO["at"] < max_age_s:
        return _INFO["info"]
    try:
        with urllib.request.urlopen(urllib.request.Request(s["url"] + "/healthz", headers=UA), timeout=timeout_s) as r:
            info = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        info = {"ok": False, "state": f"unreachable ({type(e).__name__})"}
    _INFO.update(at=time.monotonic(), url=s["url"], info=info)
    return info


def check() -> str:
    """For /healthz: off | mock | ok (<model>) | loading | failed | unreachable. Never includes the secret."""
    s = settings()
    if not s["url"]:
        return "off"
    if s["url"] == "mock":
        return "mock"
    h = remote_info()
    return f"ok ({h.get('model')})" if h.get("ok") else str(h.get("state", "not ready"))


def remote_has_avatar() -> bool:
    return bool(remote_info().get("avatar"))


def fetch_avatar(timeout_s: float = 60.0) -> bytes | None:
    """The body file from the model service, kept in memory (about 2 MB), so it never sits on this host's disk."""
    s = settings()
    if not s["url"] or s["url"] == "mock":
        return None
    if _AVATAR["url"] == s["url"] and _AVATAR["bytes"]:
        return _AVATAR["bytes"]
    req = urllib.request.Request(s["url"] + "/avatar.glb",
                                 headers={**UA, **({"Authorization": f"Bearer {s['secret']}"} if s["secret"] else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            data = r.read()
    except Exception:  # noqa: BLE001
        return None
    if data[:4] != b"glTF":
        return None
    _AVATAR.update(url=s["url"], bytes=data)
    return data


class ModelRelay:
    def __init__(self, emit, session_id: str):
        self.emit, self.session_id = emit, session_id
        self.s = settings()
        self.q: asyncio.Queue = asyncio.Queue()
        self.sent = self.failed = 0
        self.task = asyncio.create_task(self._run())

    def submit(self, unit: dict):
        if (unit.get("text") or "").strip():
            self.q.put_nowait(unit)

    async def _one(self, unit: dict) -> dict:
        uid, text = unit.get("unit_id"), unit["text"]
        if self.s["url"] == "mock":
            return mock_reply(uid, text)
        body = {"unit_id": uid, "text": text, "signer": self.s["signer"], "is_question": bool(unit.get("is_question")),
                "session_id": self.session_id}
        return await asyncio.to_thread(post_sign, self.s["url"], self.s["secret"], body, self.s["timeout_s"])

    async def _run(self):
        while (unit := await self.q.get()) is not None:
            t0 = time.perf_counter()
            try:
                rep = await self._one(unit)
                if rep.get("unit_id") != unit.get("unit_id"):
                    raise RuntimeError(f"model answered unit {rep.get('unit_id')} for unit {unit.get('unit_id')}")
                if rep.get("format") != "soke133" or rep.get("fps") != FPS:
                    raise RuntimeError(f"model sent format {rep.get('format')} at {rep.get('fps')} fps; "
                                       "this app plays soke133 at 24 fps (CONTRACT-MOTION.md)")
                if len(base64.b64decode(rep.get("motion", ""))) != int(rep.get("frames", -1)) * DIM * 2:
                    raise RuntimeError("motion size does not match its frame count")
                rep.pop("type", None)
                self.emit({"type": "motion", **rep, "relay_s": round(time.perf_counter() - t0, 3)})
                self.sent += 1
            except Exception as e:  # noqa: BLE001  one bad clause must not end the session
                self.failed += 1
                self.emit({"type": "motion_error", "unit_id": unit.get("unit_id"), "message": str(e)[:300]})

    async def drain(self, timeout_s: float):
        """After the last unit: let queued clauses finish (so "done" comes after the last clip), then stop."""
        if self.task.done():
            return
        self.q.put_nowait(None)
        try:
            await asyncio.wait_for(asyncio.shield(self.task), timeout_s)
        except asyncio.CancelledError:
            return
        except asyncio.TimeoutError:
            self.task.cancel()
            self.emit({"type": "motion_error", "unit_id": None,
                       "message": f"stopped waiting for the model after {timeout_s:.0f} s"})

    def cancel(self):
        self.task.cancel()
