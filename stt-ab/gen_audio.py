"""Voice the TTS cases with Groq's Saudi Orpheus model -> fixtures/tts/audio/{id}.wav (16 kHz mono).

Rotates the six voices so no vendor gets to overfit one speaker. Long takes are stitched from their
<=200-char parts with 300-600 ms of silence between, changing voice every few parts.
Prints the cost before spending anything: $40 per million characters.
"""
import utf8  # noqa: F401  must come before anything prints
import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

import audio

load_dotenv()
CASES = Path("fixtures/tts/cases_tts.jsonl")
AUDIO = Path("fixtures/tts/audio")
VOICES = ["abdullah", "fahad", "sultan", "lulwa", "noura", "aisha"]
PRICE_PER_CHAR = 40 / 1_000_000


def tts(client, model, voice, text) -> bytes:
    r = client.audio.speech.create(model=model, voice=voice, input=text, response_format="wav")
    return r.read() if hasattr(r, "read") else r.content


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("GROQ_TTS", "canopylabs/orpheus-arabic-saudi"))
    ap.add_argument("--limit", type=int, default=0, help="only the first N cases")
    ap.add_argument("--only", default="", help="comma list of case ids")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="cost only")
    a = ap.parse_args()

    cases = [json.loads(l) for l in CASES.open(encoding="utf-8") if l.strip()]
    if a.only:
        keep = set(a.only.split(","))
        cases = [c for c in cases if c["id"] in keep]
    if a.limit:
        cases = cases[:a.limit]
    AUDIO.mkdir(parents=True, exist_ok=True)

    todo = [c for c in cases if a.force or not (AUDIO / f"{c['id']}.wav").exists()]
    chars = sum(sum(len(p) for p in c["parts"]) if c.get("parts") else len(c.get("tashkeel") or c["text"]) for c in todo)
    print(f"{len(todo)} clips to synthesise, {chars:,} chars ≈ ${chars * PRICE_PER_CHAR:.2f}")
    if a.dry_run or not todo:
        return

    client = Groq()
    vi = 0
    for c in todo:
        out = AUDIO / f"{c['id']}.wav"
        try:
            if c.get("parts"):
                pcm_parts = []
                for j, part in enumerate(c["parts"]):
                    voice = VOICES[(vi + j // 3) % len(VOICES)]
                    pcm_parts.append(audio.load_bytes(tts(client, a.model, voice, part)))
                vi += 1
                pcm = audio.stitch(pcm_parts, seed=hash(c["id"]) & 0xFFFF)
            else:
                voice = VOICES[vi % len(VOICES)]
                vi += 1
                pcm = audio.load_bytes(tts(client, a.model, voice, c.get("tashkeel") or c["text"]))
            audio.write(out, pcm)
            print(f"  {c['id']:<22} {audio.duration_s(pcm):6.1f}s")
        except Exception as e:  # noqa: BLE001
            print(f"  {c['id']:<22} FAILED {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
