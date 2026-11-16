"""The browser's path, without a browser: web server (mock mode) <- a client that streams PCM to /ws/audio
the way web/index.html does, plus a stage-2 subscriber on /ws/units. ~17 s.   python tests/e2e_server.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["SADIH_MOCK"] = "1"
os.environ.pop("MUNSIT_API_KEY", None)

import utf8  # noqa: F401,E402
import uvicorn  # noqa: E402
import websockets  # noqa: E402

import server  # noqa: E402
from sources import silence_source  # noqa: E402
from e2e_mock import EXPECTED  # noqa: E402

PORT = 8011


async def main():
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=PORT, log_level="warning"))
    stask = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.05)

    sub_units = []

    async def subscriber():
        async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/units") as s:
            async for raw in s:
                sub_units.append(json.loads(raw))

    sub = asyncio.create_task(subscriber())
    await asyncio.sleep(0.2)

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
            if m["type"] == "unit":
                print(f"  unit #{m['unit_id']} [{m['boundary']}] {m['text']}")
            if m["type"] == "done":
                break
        await st

    sub.cancel()
    srv.should_exit = True
    await stask

    kinds = [m["type"] for m in msgs]
    units = [m for m in msgs if m["type"] == "unit"]
    stats = next(m for m in msgs if m["type"] == "stats")
    print("\nmessage counts:", {k: kinds.count(k) for k in dict.fromkeys(kinds)})
    print("stats:", {k: stats[k] for k in ("units", "revisions_after_commit", "latency_median_s", "latency_p90_s")})

    assert kinds[0] == "hello" and msgs[0]["mock"] is True
    assert [u["text"] for u in units] == EXPECTED, [u["text"] for u in units]
    assert [u["text"] for u in sub_units] == EXPECTED, "stage-2 subscriber did not get the same units"
    assert any(m["type"] == "interim" and m["pending"] for m in msgs), "no pending text was ever shown"
    assert kinds.count("latency") == len(units), "every unit should get a latency"
    assert stats["revisions_after_commit"] == 0 and kinds[-1] == "done"
    # order: a unit is always announced before the interim that no longer contains it
    print("\nSERVER E2E PASSED")


if __name__ == "__main__":
    asyncio.run(main())
