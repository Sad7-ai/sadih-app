"""Fake stage 1 for whoever builds stage 2: replays a units file over the same websocket, with the
original spacing between units, to every client that connects.

  python replay.py samples/hospital.units.jsonl [--port 8765] [--speed 1.0] [--loop]
"""
import utf8  # noqa: F401  must come before anything prints
import argparse
import asyncio
import json

import websockets


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--loop", action="store_true")
    a = ap.parse_args()
    units = [json.loads(l) for l in open(a.path, encoding="utf-8") if l.strip()]

    async def handler(ws):
        while True:
            prev = 0.0
            for u in units:
                t = u.get("t_end") or prev
                await asyncio.sleep(max(0.0, t - prev) / a.speed)
                prev = t
                await ws.send(json.dumps(u, ensure_ascii=False))
            if not a.loop:
                break
        await ws.close()

    async with websockets.serve(handler, "0.0.0.0", a.port):
        print(f"replaying {len(units)} units on ws://localhost:{a.port}")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
