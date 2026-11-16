"""Load anything, hand back 16 kHz mono int16. Pacing generator for the streaming adapters."""
import asyncio
import io
import random
import time

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SR = 16000
BYTES_PER_S = SR * 2  # int16 mono


def to_16k_mono(data: np.ndarray, sr: int) -> np.ndarray:
    if data.ndim == 2:
        data = data.mean(axis=1)
    if sr != SR:
        g = np.gcd(sr, SR)
        data = resample_poly(data, SR // g, sr // g)
    data = np.clip(data, -1.0, 1.0)
    return (data * 32767).astype(np.int16)


def load(path) -> np.ndarray:
    """wav/flac/ogg directly; anything else (iPhone .m4a, .mp3) through ffmpeg."""
    import subprocess
    from pathlib import Path
    if Path(path).suffix.lower() not in {".wav", ".flac", ".ogg"}:
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                           capture_output=True, check=True)
        return np.frombuffer(r.stdout, dtype=np.int16)
    data, sr = sf.read(path, dtype="float32", always_2d=False)
    return to_16k_mono(data, sr)


def load_bytes(wav_bytes: bytes) -> np.ndarray:
    data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=False)
    return to_16k_mono(data, sr)


def write(path, pcm: np.ndarray):
    sf.write(path, pcm, SR, subtype="PCM_16")


def duration_s(pcm: np.ndarray) -> float:
    return len(pcm) / SR


def silence(ms: int) -> np.ndarray:
    return np.zeros(int(SR * ms / 1000), dtype=np.int16)


def stitch(parts: list[np.ndarray], gap_ms=(300, 600), seed=0) -> np.ndarray:
    """Join short clips into one long take with a random pause between each."""
    rng = random.Random(seed)
    out = []
    for i, p in enumerate(parts):
        out.append(p)
        if i < len(parts) - 1:
            out.append(silence(rng.randint(*gap_ms)))
    return np.concatenate(out)


async def paced(pcm_bytes: bytes, chunk_ms: int = 100, realtime: bool = True):
    """Yield audio in chunks. With realtime=True the chunks come out on a wall-clock schedule
    (no drift: each chunk is scheduled from the start time, not from the previous chunk)."""
    frame = int(BYTES_PER_S * chunk_ms / 1000)
    t0 = time.perf_counter()
    for i, off in enumerate(range(0, len(pcm_bytes), frame)):
        if realtime:
            delay = (t0 + i * chunk_ms / 1000) - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
        yield pcm_bytes[off:off + frame]
