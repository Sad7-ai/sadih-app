"""Feed every clip to every adapter, N times, at real-time pace. Raw results -> results/{adapter}/{id}.r{n}.json

Vendors run one after another per clip, never in parallel, so latency numbers are not fighting each
other for the network. Existing results are skipped unless --force.
"""
import utf8  # noqa: F401  must come before anything prints
import argparse
import asyncio
import json
import time
from pathlib import Path

from dotenv import load_dotenv

import audio
from adapters import build

load_dotenv()
DEFAULT_CASES = ["fixtures/tts/cases_tts.jsonl", "fixtures/human/cases_human.jsonl"]
RESULTS = Path("results")


def load_cases(paths):
    cases = []
    for p in paths:
        p = Path(p)
        if not p.exists():
            continue
        for line in p.open(encoding="utf-8"):
            if not line.strip():
                continue
            c = json.loads(line)
            wav = Path(c["audio"]) if c.get("audio") else p.parent / "audio" / f"{c['id']}.wav"
            if not wav.is_absolute():
                wav = (p.parent / wav) if c.get("audio") else wav
            c["_wav"] = wav
            c["_source"] = p.name
            cases.append(c)
    return cases


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="*", default=DEFAULT_CASES)
    ap.add_argument("--adapters", default="fake")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--fast", action="store_true", help="no real-time pacing (groq/fake only)")
    ap.add_argument("--only", default="", help="comma list of case ids")
    ap.add_argument("--category", default="", help="comma list of categories")
    ap.add_argument("--hotwords", default="", help="comma list passed to Munsit")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    cases = load_cases(a.cases)
    if a.only:
        keep = set(a.only.split(","))
        cases = [c for c in cases if c["id"] in keep]
    if a.category:
        keep = set(a.category.split(","))
        cases = [c for c in cases if c.get("category") in keep]
    cases = [c for c in cases if c["_wav"].exists()]
    if not cases:
        print("no cases with audio found — run gen_audio.py or add human recordings")
        return

    adapters = []
    for name in a.adapters.split(","):
        kw = {"hotwords": [h for h in a.hotwords.split(",") if h]} if name == "munsit" else {}
        adapters.append(build(name, **kw))

    total = len(cases) * len(adapters) * a.repeats
    done = 0
    for c in cases:
        pcm = audio.load(c["_wav"]).tobytes()
        dur = len(pcm) / audio.BYTES_PER_S
        for ad in adapters:
            for r in range(1, a.repeats + 1):
                out = RESULTS / ad.name / f"{c['id']}.r{r}.json"
                done += 1
                if out.exists() and not a.force:
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                realtime = not a.fast
                t0 = time.perf_counter()
                res = await ad.transcribe(pcm, realtime=realtime, hint=c.get("text"))
                wall = time.perf_counter() - t0
                rec = {"case_id": c["id"], "category": c.get("category"), "source": c["_source"],
                       "audio_s": round(dur, 2), "wall_s": round(wall, 2), "repeat": r,
                       "ref": c.get("text"), "english_terms": c.get("english_terms", []), **res.to_dict()}
                out.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
                flag = "ERR " if res.error else "ok  "
                print(f"[{done:>4}/{total}] {flag}{ad.name:<7} {c['id']:<22} audio {dur:5.1f}s  wall {wall:5.1f}s  "
                      f"first {res.first_partial_s if res.first_partial_s is None else round(res.first_partial_s, 2)}  "
                      f"lag {res.final_lag_s if res.final_lag_s is None else round(res.final_lag_s, 2)}"
                      + (f"  {res.error[:80]}" if res.error else ""))


if __name__ == "__main__":
    asyncio.run(main())
