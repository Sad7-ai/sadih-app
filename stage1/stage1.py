"""صادِح · stage 1 from the command line — for testing without the browser. The live app is server.py.

  python stage1.py --mic                     laptop mic, Ctrl+C to stop
  python stage1.py --wav clip.m4a            a file, paced at real time
  python stage1.py --silence 17 --url ws://localhost:8766     against mock_munsit.py

Writes out/<session>.units.jsonl (the contract), .raw.jsonl (every vendor event), .stats.json.
"""
import utf8  # noqa: F401  must come before anything prints
import argparse
import asyncio
import json
import os
import signal
import uuid
from pathlib import Path

import websockets
from dotenv import load_dotenv

from munsit_client import MunsitClient
from pipeline import Pipeline
from sources import mic_source, wav_source, silence_source

load_dotenv()


class Emitter:
    def __init__(self, path: Path, port: int | None, quiet: bool = False):
        self.f = path.open("w", encoding="utf-8")
        self.port, self.quiet = port, quiet
        self.clients: set = set()
        self.server = None

    async def start(self):
        if self.port:
            self.server = await websockets.serve(self._handler, "0.0.0.0", self.port)
            print(f"serving units on ws://localhost:{self.port}")

    async def _handler(self, ws):
        self.clients.add(ws)
        try:
            await ws.wait_closed()
        finally:
            self.clients.discard(ws)

    def emit(self, unit: dict):
        line = json.dumps(unit, ensure_ascii=False)
        self.f.write(line + "\n")
        self.f.flush()
        if not self.quiet:
            ts, te = unit["t_start"], unit["t_end"]
            span = f"{ts:6.2f}-{te:6.2f}" if ts is not None and te is not None else "   ?  -   ?  "
            flags = ("Q" if unit["is_question"] else " ") + ("." if unit["sentence_final"] else " ")
            print(f"#{unit['unit_id']:<3} [{unit['boundary']:<8}] {flags} {span}  {unit['text']}")
        for ws in list(self.clients):
            asyncio.create_task(ws.send(line))

    async def close(self):
        self.f.close()
        if self.server:
            self.server.close()
            await self.server.wait_closed()


def load_hotwords(path: str | None) -> list[str]:
    if path and Path(path).exists():
        return [l.strip() for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    return []


async def run(a) -> dict:
    session = uuid.uuid4().hex[:8]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    raw_log = (out / f"{session}.raw.jsonl").open("w", encoding="utf-8")
    emitter = Emitter(out / f"{session}.units.jsonl", a.serve, quiet=a.quiet)
    await emitter.start()

    client = MunsitClient(os.environ.get("MUNSIT_API_KEY"), url=a.url, model=a.model, endpointing=a.endpointing,
                          smart_turn=a.smart_turn, hotwords=load_hotwords(a.hotwords), correlation_id=session)
    show = (lambda buf, pend: print(f"      ~ {buf} | {pend}")) if a.show_interims else None
    pipe = Pipeline(session, emitter.emit, show, stable_ms=a.stable_ms, hold_last=not a.no_hold_last,
                    max_words=a.max_words, max_sec=a.max_sec, min_words=a.min_words)

    stop = asyncio.Event()
    try:
        signal.signal(signal.SIGINT, lambda *_: stop.set())
    except ValueError:
        pass      # not in the main thread (tests)

    if a.wav:
        source = wav_source(a.wav)
    elif a.silence:
        source = silence_source(a.silence)
    else:
        source = mic_source(stop, a.seconds)
        print("listening — Ctrl+C to stop")

    async for ev in client.events(source):
        clock = client.audio_clock
        raw_log.write(json.dumps({"clock": round(clock, 2), **ev}, ensure_ascii=False) + "\n")
        pipe.handle(ev, clock)
        typ = ev.get("type")
        if typ == "Metadata":
            if "audio_seconds_billed" in ev:
                print(f"billed {ev['audio_seconds_billed']} s of audio, {ev.get('turn_count')} turns")
            else:
                print(f"session {session}  model {ev.get('model')}")
                if ev.get("dropped_hotwords"):
                    print("  dropped hotwords:", ev["dropped_hotwords"])
        elif typ == "Error":
            print(f"ERROR {ev.get('code')}: {ev.get('message')} (recoverable={ev.get('recoverable')})")
        elif typ == "_Closed" and ev.get("code") not in (1000, None):
            print(f"socket closed {ev.get('code')}: {ev.get('reason')}")

    stats = pipe.finish(client.audio_clock)
    raw_log.close()
    await emitter.close()
    (out / f"{session}.stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    if not a.quiet:
        print("\n" + json.dumps(stats, ensure_ascii=False, indent=1))
    return stats


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--mic", action="store_true")
    src.add_argument("--wav")
    src.add_argument("--silence", type=float, help="seconds of silence (for the mock server)")
    ap.add_argument("--seconds", type=float, help="stop the mic after N seconds")
    ap.add_argument("--url", default=os.environ.get("MUNSIT_URL"), help="override, e.g. ws://localhost:8766 for the mock")
    ap.add_argument("--model", default="munsit-en-ar")
    ap.add_argument("--endpointing", type=int, default=300)
    ap.add_argument("--smart-turn", action="store_true", help="off by default: we caption, we do not take turns")
    ap.add_argument("--hotwords", default="hotwords.txt", help="one term per line, max 200 x 40 chars")
    ap.add_argument("--stable-ms", type=int, default=600)
    ap.add_argument("--no-hold-last", action="store_true")
    ap.add_argument("--max-words", type=int, default=12)
    ap.add_argument("--max-sec", type=float, default=3.0)
    ap.add_argument("--min-words", type=int, default=2)
    ap.add_argument("--serve", type=int, help="broadcast units on this websocket port")
    ap.add_argument("--out", default="out")
    ap.add_argument("--show-interims", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    return ap


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
