"""A local stand-in for Munsit's /listen socket, so stage 1 can be tested with no key and no credits.

It ignores the audio content and drives a scripted transcript from the AUDIO CLOCK (bytes received),
which is how the real thing behaves from the client's side:
  - opening Metadata
  - an interim Results every 200 ms; some words first appear misspelled and are corrected one interim later
  - a final Results + UtteranceEnd once `endpointing` ms of "silence" follow a segment  ("|" in the script)
  - a forced final (speech_final false) after 60 s of unbroken speech
  - CloseStream -> last final, closing Metadata with audio_seconds_billed, close 1000

  python mock_munsit.py            # ws://localhost:8766
  python stage1.py --silence 17 --url ws://localhost:8766
"""
import utf8  # noqa: F401  must come before anything prints
import argparse
import asyncio
import json
import urllib.parse

import websockets

SCRIPT = ("أمس رحت للمستشفى وقابلت الدكتور وقال لي إن التحاليل طبيعية بس لازم أرجع بعد أسبوع | "
          "وين المختبر؟ | "
          "خذ Panadol حبتين بعد الأكل وبعدين ارجع لل appointment الجاي")
WORD_S, GAP_S, PAUSE_S = 0.35, 0.08, 1.0


def build(script: str, t0: float = 0.5, idx0: int = 0):
    segs, cur, t, idx = [], [], t0, idx0
    for tok in script.split():
        if tok == "|":
            if cur:
                segs.append(cur)
                cur = []
            t += PAUSE_S
            continue
        cur.append({"idx": idx, "word": tok, "start": round(t, 2), "end": round(t + WORD_S, 2)})
        t += WORD_S + GAP_S
        idx += 1
    if cur:
        segs.append(cur)
    return segs


def results(words, final, speech_final, turn, texts=None):
    texts = texts or [w["word"] for w in words]
    ev = {"type": "Results", "channel": 0, "turn_id": turn, "transcript": " ".join(texts),
          "is_final": final, "speech_final": speech_final, "language": "ar",
          "confidence": 0.97 if final else None}
    if final or ARGS.interim_words:
        ev["words"] = [{"word": x, "start": w["start"], "end": w["end"], "confidence": 0.98 if final else None}
                       for x, w in zip(texts, words)]
    return json.dumps(ev, ensure_ascii=False)


async def handler(ws):
    q = urllib.parse.parse_qs(urllib.parse.urlparse(ws.request.path).query)
    ep = int(q.get("endpointing", ["800"])[0]) / 1000
    segs = build(ARGS.script or SCRIPT)
    await ws.send(json.dumps({"type": "Metadata", "session_id": "mock", "model": "mock-munsit", "protocol_version": 1,
                              "channels": 1, "sample_rate": 16000, "dropped_hotwords": []}))
    got, si, turn, last_i, shown, seg_from = 0, 0, 0, -1.0, set(), 0

    async def finalize(words, speech_final):
        nonlocal turn
        await ws.send(results(words, True, speech_final, turn))
        if speech_final:
            await ws.send(json.dumps({"type": "UtteranceEnd", "channel": 0, "turn_id": turn, "last_word_end": words[-1]["end"]}))
            turn += 1

    async for msg in ws:
        if isinstance(msg, (bytes, bytearray)):
            got += len(msg)
            t = got / 32000
            while si < len(segs) and t >= segs[si][-1]["end"] + ep:
                await finalize(segs[si][seg_from:], True)
                si, seg_from = si + 1, 0
            if si >= len(segs) and getattr(ARGS, "loop", False):      # live demo: start the script again
                segs = build(ARGS.script or SCRIPT, t0=t + 3.0, idx0=segs[-1][-1]["idx"] + 1)
                si, seg_from = 0, 0
            if si < len(segs):
                open_words = segs[si][seg_from:]
                if open_words and t - open_words[0]["start"] >= 60:          # forced split
                    heard = [w for w in open_words if w["end"] <= t - 0.25]
                    if heard:
                        await finalize(heard, False)
                        seg_from += len(heard)
                elif t - last_i >= 0.2:
                    heard = [w for w in open_words if w["end"] <= t - 0.25]
                    if heard:
                        texts = [w["word"] for w in heard]
                        newest = heard[-1]
                        if newest["idx"] not in shown:
                            shown.add(newest["idx"])
                            if newest["idx"] % 4 == 2 and len(newest["word"]) > 2:
                                texts[-1] = newest["word"][:-1]           # misheard; corrected next interim
                        await ws.send(results(heard, False, False, turn, texts))
                        last_i = t
        else:
            m = json.loads(msg)
            if m.get("type") == "CloseStream":
                t = got / 32000
                if si < len(segs):
                    heard = [w for w in segs[si][seg_from:] if w["start"] <= t]
                    if heard:
                        await finalize(heard, True)
                await ws.send(json.dumps({"type": "Metadata", "session_id": "mock", "audio_seconds_billed": round(t, 1), "turn_count": turn}))
                await ws.close(1000)
                return


async def serve(port: int):
    return await websockets.serve(handler, "localhost", port)


ARGS = argparse.Namespace(interim_words=False, script=None, loop=False)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--interim-words", action="store_true", help="put words[] timings on interims too")
    ap.add_argument("--script", help='custom script, "|" marks a pause')
    ap.add_argument("--loop", action="store_true", help="restart the script when it runs out")
    ARGS = ap.parse_args()

    async def main():
        await serve(ARGS.port)
        print(f"mock Munsit on ws://localhost:{ARGS.port}")
        await asyncio.Future()

    asyncio.run(main())
