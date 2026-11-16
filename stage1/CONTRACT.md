# Stage 1 → Stage 2 contract

Stage 1 (Ziyad, speech → text) hands stage 2 (Raid, text → gloss) **one JSON object per clause**.
Transport: one JSON per WebSocket text message on `ws://<host>:8765`, and the same lines in `out/<session>.units.jsonl`.

```json
{
  "unit_id": 3,
  "session_id": "e0ac440d",
  "text": "وقال لي إن التحاليل طبيعية",
  "text_raw": "وقال لي إن التحاليل طبيعية",
  "tokens": [
    {"w": "وقال", "t0": 3.8, "t1": 4.2, "lang": "ar", "conf": null},
    {"w": "Panadol", "t0": 11.3, "t1": 11.7, "lang": "en", "conf": 0.98}
  ],
  "t_start": 3.8,
  "t_end": 5.9,
  "boundary": "marker",
  "sentence_final": false,
  "is_question": false,
  "confidence": null,
  "timing": "approx"
}
```

## Guarantees

- **Append-only.** `unit_id` goes 1, 2, 3… with no gaps. A unit is never revised or retracted. If the
  recogniser changes its mind about a word already sent, stage 1 counts it (`revisions_after_commit` in the
  session stats) and moves on — stage 2 never sees it.
- **One clause per unit**, 1–12 words. Reordering into sign order happens inside a unit, never across units.

## Fields

| field | meaning |
|---|---|
| `text` | the clause, cleaned: no tashkeel, no tatweel, no punctuation, Western digits. **Spelling is untouched** (ة ى أ stay as recognised). This is what you translate. |
| `text_raw` | exactly what the recogniser returned, punctuation included. For debugging. |
| `tokens[].lang` | `en` if the word has Latin letters, else `ar`. English words inside Arabic speech (drug names, "appointment") arrive here — fingerspell or map them. |
| `tokens[].t0/t1` | seconds from the start of the session's audio. |
| `timing` | `exact` = times came from the recogniser. `approx` = the unit was cut from interim results, which carry no word times, so times are the audio clock at commit (about 1–1.5 s late). Order is always right; do not use `approx` times for lip-tight alignment. |
| `boundary` | why the clause ended here: `marker` (next word opens a clause: وقال، بس، بعدين…), `punct` (recogniser punctuation), `forced` (12 words or 3 s with no better cut — the clause may be incomplete), `endpoint` (the speaker stopped). |
| `sentence_final` | `true` when the speaker paused or a sentence mark (؟ . !) closed the clause. `false` means more of the same sentence is probably coming — hold any end-of-sentence face marker. |
| `is_question` | a `؟` was recognised, or the clause opens with a question word (وين، ليش، كيف، هل…). Drives the question face. |
| `confidence` | mean word confidence, `null` when the unit was cut from interims (the recogniser gives none there). |

## Build against it today

```
python replay.py samples/hospital.units.jsonl        # fake stage 1 on ws://localhost:8765
python consumer.py                                   # prints what stage 2 would receive
```
