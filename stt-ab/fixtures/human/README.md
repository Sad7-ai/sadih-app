# Human recordings — the gold set

One line per clip in `cases_human.jsonl`:

```json
{"id": "human-007", "category": "dialect", "speaker": "nawaf", "audio": "human-007.wav",
 "text": "وين المختبر؟ الدكتور قال أسوي X-ray بعدين أرجع له", "english_terms": ["X-ray"]}
```

- `text` — exactly what you said, in dialect spelling, no tashkeel. This is the reference. Be honest; if you stumbled, write the stumble.
- `category` — `dialect` (pure Saudi phrasing) or `codeswitch` (English words inside).
- `english_terms` — the English words, Latin script, as you meant them.
- `audio` — wav or m4a in this folder; `audio.py` resamples on load.

Rules: phone mic only. No AirPods, no Bluetooth, no laptop browser. Quiet room for half the clips, a
normal noisy place for the other half. Ten clips per person.

`human-001` is reserved for the sentence that failed in the Munsit browser demo.
