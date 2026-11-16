"""Write Saudi-dialect test sentences with a Groq LLM -> fixtures/tts/cases_tts.jsonl

Each case: {id, category, text, tashkeel, english_terms, scene}
  text          plain, no tashkeel — this is the scoring reference
  tashkeel      diacritised copy for the TTS (Groq recommends it for pronunciation)
  english_terms Latin-script terms embedded in the sentence, scored separately by score.py
Long takes: category "long", with "parts" (each <= 200 chars for the TTS limit).

A Saudi should skim the output. LLM "dialect" drifts toward MSA.
"""
import utf8  # noqa: F401  must come before anything prints
import argparse
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

load_dotenv()
OUT = Path("fixtures/tts/cases_tts.jsonl")
TTS_MAX = 200

SCENES = {
    "clinic": "a doctor or nurse speaking to a patient in a Saudi hospital or clinic",
    "gov": "a clerk at a Saudi government office (Absher, passport office, municipality) speaking to a visitor",
    "bank": "a bank teller or customer service agent in Saudi Arabia speaking to a customer",
    "codeswitch": "any of the above, but every sentence contains 1-3 English words the way Saudis actually mix them "
                  "(drug names, 'appointment', 'X-ray', 'IBAN', 'update', 'OTP', 'app', 'report'), written in Latin script",
}

PROMPT = """You write test sentences in SAUDI ARABIC DIALECT (Najdi or Hijazi, not Modern Standard Arabic) for a speech-recognition test.
Scene: {scene}.
Write {n} sentences a real person would say out loud in that scene. Natural, spoken, 6 to 20 words each.
Use dialect words where a Saudi would (وين، ليش، كذا، الحين، بعدين، عشان، أبي، ودّي، خلاص، طيب، إن شاء الله).
{extra}
Return JSON only: {{"sentences": [{{"text": "...plain, no tashkeel...", "tashkeel": "...same sentence fully diacritised...", "english_terms": ["..."]}}]}}
english_terms lists the Latin-script words in the sentence, or [] if none. Every English word in "text" must also appear in "tashkeel" unchanged."""

LONG_PROMPT = """You write a monologue in SAUDI ARABIC DIALECT (Najdi or Hijazi) for a speech-recognition test.
Scene: {scene}. One person talks continuously, explaining something step by step, for about {minutes} minutes of speech
(roughly {words} words). No pauses, no dialogue, no headings — one flowing spoken explanation, with the small words a real
speaker uses (طيب، يعني، بعدين، عشان، الحين). Include a few English words the way Saudis mix them.
Return JSON only: {{"sentences": [{{"text": "...", "tashkeel": "...", "english_terms": ["..."]}}]}} where each item is one
spoken sentence in order, each under 180 characters."""


def chat_json(client, model, prompt):
    r = client.chat.completions.create(
        model=model, temperature=0.9,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    return json.loads(r.choices[0].message.content)


def split_for_tts(text: str, limit=TTS_MAX) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for w in text.split():
        if len(cur) + len(w) + 1 > limit:
            parts.append(cur.strip())
            cur = w
        else:
            cur = f"{cur} {w}"
    if cur.strip():
        parts.append(cur.strip())
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-category", type=int, default=30)
    ap.add_argument("--long-minutes", type=float, default=5, help="length of the long take; 0 to skip")
    ap.add_argument("--categories", default="clinic,gov,bank,codeswitch")
    ap.add_argument("--model", default=os.environ.get("GROQ_LLM", "llama-3.3-70b-versatile"))
    ap.add_argument("--list-models", action="store_true")
    a = ap.parse_args()

    client = Groq()
    if a.list_models:
        for m in client.models.list().data:
            print(m.id)
        return

    OUT.parent.mkdir(parents=True, exist_ok=True)
    cases = []
    for cat in a.categories.split(","):
        extra = "" if cat != "codeswitch" else "EVERY sentence must contain at least one English word in Latin script."
        got = []
        while len(got) < a.per_category:
            n = min(15, a.per_category - len(got))
            data = chat_json(client, a.model, PROMPT.format(scene=SCENES[cat], n=n, extra=extra))
            for s in data.get("sentences", []):
                t = (s.get("text") or "").strip()
                if not t or len(t) > TTS_MAX:
                    continue
                got.append({"text": t, "tashkeel": (s.get("tashkeel") or t).strip(),
                            "english_terms": [e.strip() for e in s.get("english_terms", []) if e.strip()]})
        for i, s in enumerate(got, 1):
            cases.append({"id": f"tts-{cat}-{i:03d}", "category": cat, "scene": cat, **s})
        print(f"{cat}: {len(got)} sentences")

    if a.long_minutes > 0:
        words = int(a.long_minutes * 130)
        data = chat_json(client, a.model, LONG_PROMPT.format(scene=SCENES["clinic"], minutes=a.long_minutes, words=words))
        sents = [s for s in data.get("sentences", []) if (s.get("text") or "").strip()]
        parts = []
        for s in sents:
            for piece in split_for_tts((s.get("tashkeel") or s["text"]).strip()):
                parts.append(piece)
        full = " ".join(s["text"].strip() for s in sents)
        terms = sorted({e.strip() for s in sents for e in s.get("english_terms", []) if e.strip()})
        cases.append({"id": f"tts-long-{int(a.long_minutes):02d}m", "category": "long", "scene": "clinic",
                      "text": full, "tashkeel": None, "parts": parts, "english_terms": terms})
        print(f"long: {len(sents)} sentences, {len(full.split())} words, {len(parts)} TTS parts")

    with OUT.open("w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"wrote {len(cases)} cases -> {OUT}")


if __name__ == "__main__":
    main()
