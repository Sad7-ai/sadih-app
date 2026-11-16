"""Munsit live streaming client: wss://api.munsit.com/api/v1/listen

Sends binary PCM frames, yields the server's JSON events. When the source ends it sends CloseStream and
KEEPS READING until the server closes — closing first loses the last finals and the billing record.
The URL carries the API key, so it is never printed.
"""
import asyncio
import json
import urllib.parse

import websockets

DEFAULT_URL = "wss://api.munsit.com/api/v1/listen"


class MunsitClient:
    def __init__(self, api_key: str | None, url: str | None = None, model: str = "munsit-en-ar",
                 endpointing: int = 300, smart_turn: bool = False, hotwords: list[str] | None = None,
                 correlation_id: str | None = None):
        self.api_key, self.base = api_key, url or DEFAULT_URL
        self.model, self.endpointing, self.smart_turn = model, endpointing, smart_turn
        self.hotwords, self.correlation_id = hotwords or [], correlation_id
        self.bytes_sent = 0

    @property
    def audio_clock(self) -> float:
        """Seconds of audio sent so far."""
        return self.bytes_sent / 32000

    def _url(self) -> str:
        q = {"encoding": "linear16", "sample_rate": 16000, "channels": 1,      # sample_rate DEFAULTS TO 8000
             "model": self.model, "interim_results": "true",
             "endpointing": self.endpointing, "smart_turn": "true" if self.smart_turn else "false"}
        if self.api_key:
            q["api_key"] = self.api_key
        if self.hotwords:
            q["hotwords"] = ",".join(self.hotwords[:200])
        if self.correlation_id:
            q["correlation_id"] = self.correlation_id
        return f"{self.base}?{urllib.parse.urlencode(q)}"

    async def events(self, source):
        async with websockets.connect(self._url(), max_size=None) as ws:
            async def sender():
                try:
                    async for chunk in source:
                        await ws.send(chunk)
                        self.bytes_sent += len(chunk)
                finally:
                    try:
                        await ws.send(json.dumps({"type": "CloseStream"}))
                    except Exception:  # noqa: BLE001
                        pass

            task = asyncio.create_task(sender())
            try:
                async for raw in ws:
                    if isinstance(raw, (bytes, bytearray)):
                        continue
                    yield json.loads(raw)
            except websockets.exceptions.ConnectionClosed as e:
                yield {"type": "_Closed", "code": e.code, "reason": e.reason}
            finally:
                if not task.done():
                    task.cancel()
