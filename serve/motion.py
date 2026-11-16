"""The motion format the model service sends (stage1/CONTRACT-MOTION.md). numpy only.

stage1/model_relay.py carries a copy of decode() for its own tests, so the hosted app never imports this
folder. If the format changes, change both, and the contract file first.
"""
import base64

import numpy as np

FORMAT = "soke133"
FPS = 24                    # avatar/avatar_config.py FPS: the rate the SOKE tokenizer was trained at
DIM = 133
UNIT = 4                    # frames per token (SOKE / MaDiS down-sample time by 4)
MIN_FRAMES, MAX_FRAMES = 40, 400


def encode(feat) -> str:
    """(T, 133) float -> base64 of little-endian float16, row by row."""
    a = np.asarray(feat, dtype=np.float32)
    if a.ndim != 2 or a.shape[1] != DIM:
        raise ValueError(f"motion must be (frames, {DIM}), got {a.shape}")
    if not np.isfinite(a).all():
        raise ValueError("motion holds NaN or inf")
    return base64.b64encode(a.astype("<f2").tobytes()).decode("ascii")


def decode(b64: str, frames: int) -> np.ndarray:
    """base64 -> (frames, 133) float32. Raises if the size does not match."""
    raw = base64.b64decode(b64)
    if len(raw) != frames * DIM * 2:
        raise ValueError(f"motion is {len(raw)} bytes, expected {frames} x {DIM} x 2")
    return np.frombuffer(raw, dtype="<f2").astype(np.float32).reshape(frames, DIM)


def heuristic_tokens(n_words: int) -> int:
    """The team's length heuristic WITHOUT the signer factor (avatar/exp4_generator/PLAN.md: (17.41 + 4.05 x words)
    tokens). Used only by the mock backend, so a mock clip is as long as a real one would roughly be."""
    t = int(round(17.41 + 4.05 * max(1, n_words)))
    return max(MIN_FRAMES // UNIT, min(MAX_FRAMES // UNIT, t))
