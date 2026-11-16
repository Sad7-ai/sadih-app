"""One adapter per vendor. Every adapter takes 16 kHz mono int16 PCM bytes and returns a Result.

Timing fields are wall-clock, measured from the sender's point of view:
  first_partial_s  = first partial transcript  - first audio byte sent
  final_lag_s      = final transcript received - last audio byte sent
Both only mean something when the audio was paced at real time.
"""
import asyncio
import json
import os
import random
import tempfile
import time
import urllib.parse
from dataclasses import dataclass, field, asdict

import httpx
import websockets

from audio import paced

MAX_RAW = 400  # raw events kept per result, for debugging


@dataclass
class Result:
    vendor: str
    text: str = ""
    words: list = field(default_factory=list)      # [{"w","t0","t1","lang","conf"}]
    first_partial_s: float | None = None
    final_lag_s: float | None = None
    partials: int = 0
    error: str | None = None
    raw: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


class Adapter:
    name = "base"
    streaming = True

    async def transcribe(self, pcm: bytes, realtime: bool = True, hint: str | None = None) -> Result:
        raise NotImplementedError


# --------------------------------------------------------------------------- fake
class FakeAdapter(Adapter):
    """Returns the reference with ~10% of words swapped, so scoring has something to score."""
    name = "fake"

    async def transcribe(self, pcm, realtime=True, hint=None):
        rng = random.Random(len(pcm))
        words = (hint or "").split()
        out = []
        for w in words:
            r = rng.random()
            if r < 0.06:
                continue                      # deletion
            if r < 0.12:
                out.append(w[::-1])           # substitution
            else:
                out.append(w)
        n = len(pcm) / 32000
        return Result(self.name, " ".join(out),
                      [{"w": w, "t0": i * n / max(len(out), 1), "t1": (i + 1) * n / max(len(out), 1), "lang": None, "conf": 0.9}
                       for i, w in enumerate(out)],
                      first_partial_s=0.35, final_lag_s=0.6, partials=len(out))


# --------------------------------------------------------------------------- soniox
class SonioxAdapter(Adapter):
    """wss://stt-rt.soniox.com/transcribe-websocket — config JSON, binary audio, empty frame to end.
    Tokens are sub-word pieces; a piece starting with a space starts a new word."""
    name = "soniox"
    URL = "wss://stt-rt.soniox.com/transcribe-websocket"

    def __init__(self):
        self.key = os.environ["SONIOX_API_KEY"]
        self.model = os.environ.get("SONIOX_MODEL", "stt-rt-v5")

    @staticmethod
    def _words(tokens):
        words, cur = [], None
        for t in tokens:
            txt = t.get("text", "")
            if txt in ("<end>", ""):
                continue
            starts_word = txt.startswith(" ") or cur is None
            if starts_word:
                if cur and cur["w"]:
                    words.append(cur)
                cur = {"w": txt.strip(), "t0": t.get("start_ms", 0) / 1000, "t1": t.get("end_ms", 0) / 1000,
                       "lang": t.get("language"), "conf": t.get("confidence")}
            else:
                cur["w"] += txt
                cur["t1"] = t.get("end_ms", 0) / 1000
        if cur and cur["w"]:
            words.append(cur)
        return words

    async def transcribe(self, pcm, realtime=True, hint=None):
        res = Result(self.name)
        finals = []
        t_first_send = t_last_send = t_first_partial = t_final = None
        try:
            async with websockets.connect(self.URL, max_size=None) as ws:
                await ws.send(json.dumps({
                    "api_key": self.key, "model": self.model,
                    "audio_format": os.environ.get("SONIOX_AUDIO_FORMAT", "pcm_s16le"),
                    "sample_rate": 16000, "num_channels": 1,
                    "language_hints": ["ar", "en"],
                    "enable_language_identification": True,
                    "enable_endpoint_detection": False,
                }))

                async def sender():
                    nonlocal t_first_send, t_last_send
                    async for chunk in paced(pcm, realtime=realtime):
                        if t_first_send is None:
                            t_first_send = time.perf_counter()
                        await ws.send(chunk)
                    t_last_send = time.perf_counter()
                    await ws.send(b"")            # end of audio

                send_task = asyncio.create_task(sender())
                async for raw in ws:
                    msg = json.loads(raw)
                    if len(res.raw) < MAX_RAW:
                        res.raw.append(msg)
                    if "error_code" in msg:
                        res.error = f"{msg.get('error_code')} {msg.get('error_type')}: {msg.get('error_message')}"
                        break
                    toks = msg.get("tokens", [])
                    if toks and t_first_partial is None:
                        t_first_partial = time.perf_counter()
                    if any(not t.get("is_final") for t in toks):
                        res.partials += 1
                    finals.extend(t for t in toks if t.get("is_final"))
                    if msg.get("finished"):
                        t_final = time.perf_counter()
                        break
                await send_task
        except Exception as e:  # noqa: BLE001
            res.error = res.error or f"{type(e).__name__}: {e}"
        res.words = self._words(finals)
        res.text = " ".join(w["w"] for w in res.words)
        if t_first_send and t_first_partial:
            res.first_partial_s = t_first_partial - t_first_send
        if t_last_send and t_final:
            res.final_lag_s = t_final - t_last_send
        return res


# --------------------------------------------------------------------------- munsit
class MunsitAdapter(Adapter):
    """wss://api.munsit.com/api/v1/listen — query-string config, binary audio, {"type":"CloseStream"} to end.
    Rejects audio sent faster than real time (close code 4008), so realtime is forced on."""
    name = "munsit"
    URL = "wss://api.munsit.com/api/v1/listen"

    def __init__(self, hotwords: list[str] | None = None):
        self.key = os.environ["MUNSIT_API_KEY"]
        self.model = os.environ.get("MUNSIT_MODEL", "munsit-en-ar")
        self.hotwords = hotwords or []

    def _url(self):
        q = {"api_key": self.key, "encoding": "linear16", "sample_rate": 16000,
             "interim_results": "true", "model": self.model, "endpointing": 800}
        if self.hotwords:
            q["hotwords"] = ",".join(self.hotwords)
        return f"{self.URL}?{urllib.parse.urlencode(q)}"

    async def transcribe(self, pcm, realtime=True, hint=None):
        res = Result(self.name)
        texts, words = [], []
        t_first_send = t_last_send = t_first_partial = t_final = None
        try:
            async with websockets.connect(self._url(), max_size=None) as ws:
                async def sender():
                    nonlocal t_first_send, t_last_send
                    async for chunk in paced(pcm, realtime=True):   # forced: 4008 otherwise
                        if t_first_send is None:
                            t_first_send = time.perf_counter()
                        await ws.send(chunk)
                    t_last_send = time.perf_counter()
                    await ws.send(json.dumps({"type": "CloseStream"}))

                send_task = asyncio.create_task(sender())
                async for raw in ws:
                    msg = json.loads(raw)
                    if len(res.raw) < MAX_RAW:
                        res.raw.append(msg)
                    typ = msg.get("type")
                    if typ == "Results":
                        if t_first_partial is None:
                            t_first_partial = time.perf_counter()
                        if msg.get("is_final"):
                            if msg.get("transcript"):
                                texts.append(msg["transcript"])
                            for w in msg.get("words", []):
                                words.append({"w": w.get("word", ""), "t0": w.get("start"), "t1": w.get("end"),
                                              "lang": msg.get("language"), "conf": w.get("confidence")})
                            t_final = time.perf_counter()
                        else:
                            res.partials += 1
                    elif typ == "Error":
                        res.error = f"{msg.get('code')}: {msg.get('message')}"
                        if not msg.get("recoverable", False):
                            break
                    elif typ == "Metadata" and "audio_seconds_billed" in msg:
                        t_final = t_final or time.perf_counter()
                        break
                await send_task
        except websockets.exceptions.ConnectionClosed as e:
            if e.code != 1000:
                res.error = res.error or f"closed {e.code}: {e.reason}"
        except Exception as e:  # noqa: BLE001
            res.error = res.error or f"{type(e).__name__}: {e}"
        res.text = " ".join(texts).strip()
        res.words = words
        if t_first_send and t_first_partial:
            res.first_partial_s = t_first_partial - t_first_send
        if t_last_send and t_final:
            res.final_lag_s = t_final - t_last_send
        return res


# --------------------------------------------------------------------------- gladia
class GladiaAdapter(Adapter):
    """POST /v2/live to get a session url, then binary audio, then {"type":"stop_recording"}."""
    name = "gladia"
    INIT = "https://api.gladia.io/v2/live"

    def __init__(self):
        self.key = os.environ["GLADIA_API_KEY"]

    async def transcribe(self, pcm, realtime=True, hint=None):
        res = Result(self.name)
        texts, words = [], []
        t_first_send = t_last_send = t_first_partial = t_final = None
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                r = await http.post(self.INIT, headers={"x-gladia-key": self.key}, json={
                    "encoding": "wav/pcm", "sample_rate": 16000, "bit_depth": 16, "channels": 1,
                    "language_config": {"languages": ["ar", "en"], "code_switching": True},
                    "messages_config": {"receive_partial_transcripts": True},
                })
                r.raise_for_status()
                url = r.json()["url"]
            async with websockets.connect(url, max_size=None) as ws:
                async def sender():
                    nonlocal t_first_send, t_last_send
                    async for chunk in paced(pcm, realtime=realtime):
                        if t_first_send is None:
                            t_first_send = time.perf_counter()
                        await ws.send(chunk)
                    t_last_send = time.perf_counter()
                    await ws.send(json.dumps({"type": "stop_recording"}))

                send_task = asyncio.create_task(sender())
                async for raw in ws:
                    msg = json.loads(raw)
                    if len(res.raw) < MAX_RAW:
                        res.raw.append(msg)
                    typ = msg.get("type")
                    if typ == "transcript":
                        d = msg.get("data", {})
                        if t_first_partial is None:
                            t_first_partial = time.perf_counter()
                        if d.get("is_final"):
                            u = d.get("utterance", {})
                            if u.get("text"):
                                texts.append(u["text"])
                            ws_ = u.get("words") or []
                            if ws_:
                                words.extend({"w": w.get("word", "").strip(), "t0": w.get("start"), "t1": w.get("end"),
                                              "lang": u.get("language"), "conf": w.get("confidence")} for w in ws_)
                            else:
                                words.append({"w": u.get("text", ""), "t0": u.get("start"), "t1": u.get("end"),
                                              "lang": u.get("language"), "conf": None})
                            t_final = time.perf_counter()
                        else:
                            res.partials += 1
                    elif typ in ("post_final_transcript", "end_of_session"):
                        t_final = t_final or time.perf_counter()
                        break
                    elif typ == "error":
                        res.error = json.dumps(msg)[:300]
                        break
                await send_task
        except Exception as e:  # noqa: BLE001
            res.error = res.error or f"{type(e).__name__}: {e}"
        res.text = " ".join(texts).strip()
        res.words = words
        if t_first_send and t_first_partial:
            res.first_partial_s = t_first_partial - t_first_send
        if t_last_send and t_final:
            res.final_lag_s = t_final - t_last_send
        return res


# --------------------------------------------------------------------------- groq whisper (batch)
class GroqWhisperAdapter(Adapter):
    """Batch baseline. final_lag_s here is the whole request time; not comparable to streaming."""
    name = "groq"
    streaming = False

    def __init__(self, language: str | None = None):
        from groq import Groq
        self.client = Groq()
        self.model = os.environ.get("GROQ_WHISPER", "whisper-large-v3")
        self.language = language

    async def transcribe(self, pcm, realtime=True, hint=None):
        import soundfile as sf
        import numpy as np
        res = Result(self.name)
        arr = np.frombuffer(pcm, dtype=np.int16)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            sf.write(f.name, arr, 16000, subtype="PCM_16")
            path = f.name
        t0 = time.perf_counter()
        try:
            kw = dict(model=self.model, response_format="verbose_json", timestamp_granularities=["word"])
            if self.language:
                kw["language"] = self.language
            with open(path, "rb") as fh:
                resp = await asyncio.to_thread(self.client.audio.transcriptions.create, file=(os.path.basename(path), fh), **kw)
            data = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
            res.text = (data.get("text") or "").strip()
            res.words = [{"w": w.get("word", "").strip(), "t0": w.get("start"), "t1": w.get("end"), "lang": data.get("language"), "conf": None}
                         for w in (data.get("words") or [])]
            res.raw = [ {k: v for k, v in data.items() if k != "segments"} ]
        except Exception as e:  # noqa: BLE001
            res.error = f"{type(e).__name__}: {e}"
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        res.final_lag_s = time.perf_counter() - t0
        return res


REGISTRY = {
    "fake": FakeAdapter,
    "soniox": SonioxAdapter,
    "munsit": MunsitAdapter,
    "gladia": GladiaAdapter,
    "groq": GroqWhisperAdapter,
}


def build(name: str, **kw) -> Adapter:
    return REGISTRY[name](**kw)
