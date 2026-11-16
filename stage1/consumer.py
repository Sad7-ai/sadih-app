"""Minimal stage-2 stand-in: connect to stage 1 (or replay.py) and print every unit as it arrives.
Start it before or after the emitter — it retries until the socket is there.

  python consumer.py [--url ws://localhost:8765]
"""
import utf8  # noqa: F401  must come before anything prints
import argparse
import asyncio
import json

import websockets


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://localhost:8765")
    ap.add_argument("--once", action="store_true", help="exit when the emitter closes")
    a = ap.parse_args()
    while True:
        try:
            async with websockets.connect(a.url) as ws:
                print("connected", a.url)
                async for raw in ws:
                    u = json.loads(raw)
                    en = [t["w"] for t in u["tokens"] if t["lang"] == "en"]
                    print(f"#{u['unit_id']:<3} {u['boundary']:<8} {'Q' if u['is_question'] else ' '}"
                          f"{'.' if u['sentence_final'] else ' '}  {u['text']}" + (f"   [en: {', '.join(en)}]" if en else ""))
            if a.once:
                return
        except (OSError, websockets.exceptions.WebSocketException):
            await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(main())
