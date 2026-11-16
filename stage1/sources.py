"""Audio sources. Each one is an async generator of 100 ms chunks of 16 kHz mono int16 PCM."""
import asyncio
import time

import numpy as np

SR = 16000
CHUNK_MS = 100
CHUNK_BYTES = SR * 2 * CHUNK_MS // 1000


async def _paced(pcm: bytes):
    t0 = time.perf_counter()
    for i, off in enumerate(range(0, len(pcm), CHUNK_BYTES)):
        delay = (t0 + i * CHUNK_MS / 1000) - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        yield pcm[off:off + CHUNK_BYTES]


def decode(path: str) -> bytes:
    """Any audio file -> 16 kHz mono int16 PCM. wav/flac/ogg are read directly; anything else
    (iPhone .m4a, .mp3, .mp4) goes through ffmpeg."""
    import subprocess
    from pathlib import Path
    if Path(path).suffix.lower() not in {".wav", ".flac", ".ogg"}:
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                           capture_output=True, check=True)
        return r.stdout
    import soundfile as sf
    from scipy.signal import resample_poly
    data, sr = sf.read(path, dtype="float32", always_2d=False)
    if data.ndim == 2:
        data = data.mean(axis=1)
    if sr != SR:
        g = np.gcd(sr, SR)
        data = resample_poly(data, SR // g, sr // g)
    return (np.clip(data, -1, 1) * 32767).astype(np.int16).tobytes()


async def wav_source(path: str):
    async for c in _paced(decode(path)):
        yield c


async def silence_source(seconds: float):
    """For the mock server, which drives its transcript from the audio clock, not the audio."""
    async for c in _paced(bytes(int(SR * seconds) * 2)):
        yield c


async def mic_source(stop: asyncio.Event, seconds: float | None = None):
    import sounddevice as sd
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def cb(indata, frames, time_info, status):
        loop.call_soon_threadsafe(q.put_nowait, bytes(indata))

    with sd.RawInputStream(samplerate=SR, channels=1, dtype="int16", blocksize=SR * CHUNK_MS // 1000, callback=cb):
        t0 = time.perf_counter()
        while not stop.is_set() and (seconds is None or time.perf_counter() - t0 < seconds):
            try:
                yield await asyncio.wait_for(q.get(), 0.5)
            except asyncio.TimeoutError:
                continue
