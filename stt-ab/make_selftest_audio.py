"""Generate the three noise clips the smoke test needs (they are not kept in git — it is 4 MB of noise).
44.1 kHz stereo on purpose, so loading them exercises the resampler and the mixdown.

  python make_selftest_audio.py
  python run_ab.py --cases fixtures/selftest/cases_selftest.jsonl --adapters fake --fast
  python score.py
"""
import utf8  # noqa: F401
import json
from pathlib import Path

import numpy as np
import soundfile as sf

D = Path("fixtures/selftest")
(D / "audio").mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(0)
for line in (D / "cases_selftest.jsonl").open(encoding="utf-8"):
    c = json.loads(line)
    secs = 20 if c["category"] == "long" else 2.5
    noise = (rng.standard_normal((int(44100 * secs), 2)) * 0.05).astype("float32")
    sf.write(D / "audio" / f"{c['id']}.wav", noise, 44100)
    print(f"{c['id']}.wav  {secs}s")
