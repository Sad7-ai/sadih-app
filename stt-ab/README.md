# صادِح · STT A/B harness

Automated comparison of real-time speech-to-text vendors on Saudi Arabic with English mixed in.
Stage 1 of the pipeline (Ziyad) picks its vendor from this.

## Arms

| adapter | what it is | why it is here |
|---|---|---|
| `munsit` | Munsit `munsit-en-ar` over WebSocket | built for Saudi dialect, has a code-switching model |
| `soniox` | Soniox `stt-rt-v5` over WebSocket | verified mid-sentence Arabic/English switching, cheapest |
| `gladia` | Gladia live v2, `code_switching: true` | second bilingual contender |
| `groq` | Groq `whisper-large-v3`, batch | sanity baseline — not a candidate, no streaming |
| `fake` | returns the reference with a few words changed | lets the whole pipeline run before you have any key |

## Test set = two layers

**Gold (human).** The five of you record real sentences on a **phone mic, no Bluetooth, no laptop**.
Type what you said, word for word, in dialect. Put the wav in `fixtures/human/` and the line in
`fixtures/human/cases_human.jsonl`. This layer decides the winner. Fixture #1 is the sentence that
failed in the Munsit browser demo.

**Synthetic (Groq).** `gen_sentences.py` writes Saudi-dialect sentences with a Groq LLM,
`gen_audio.py` voices them with `canopylabs/orpheus-arabic-saudi`. Hundreds of clips for pennies.
Good for volume, the long take, the 50-minute socket, regression. Not a substitute for real speakers.

## Run

```bash
pip install -r requirements.txt
copy .env.example .env        # fill in the keys you have; leave the rest blank

python gen_sentences.py --per-category 30 --long-minutes 5      # Groq LLM  -> fixtures/tts/cases_tts.jsonl
python gen_audio.py                                             # Groq TTS  -> fixtures/tts/audio/*.wav
python make_selftest_audio.py                                   # 3 noise clips for the smoke test (not kept in git)
python run_ab.py --cases fixtures/selftest/cases_selftest.jsonl --adapters fake --fast   # smoke test, no keys
python score.py && rmdir /s /q results\fake                     # look, then clear the fake results
python run_ab.py --adapters munsit,soniox,groq --repeats 3      # the real thing, paced at 1x
python score.py                                                 # -> results/report.md
```

`run_ab.py` always feeds audio at real-time pace for the streaming vendors. Munsit closes the
socket if audio gets more than 60 s ahead of real time (code 4008), and the latency numbers only mean something at 1x.
Use `--fast` only with `groq` or `fake`.

## What score.py reports

- **WER** per vendor per category, after both sides go through `normalize.py`
  (tashkeel stripped, alef unified, ة→ه, ى→ي, one digit system, punctuation out).
- **English-term recall** — for every English term the sentence contained, did it come out at all:
  Latin script, or an accepted Arabic spelling from `translit.json`. Kept separate from WER because
  this is the number that hurts users in a clinic.
- **Latency** — median time to first partial, and median lag from last audio byte to final transcript.
- **Long-take survival** — did the socket hold, did text go missing.
- **Worst clips** — reference and hypothesis side by side. Read these; the averages hide everything.

## Rules for recordings

- phone mic, never AirPods or any Bluetooth headset (the codec drops to phone-call quality when the mic is on)
- record on the phone, not through a browser on a laptop
- 16 kHz mono wav is the target; `audio.py` resamples anything else on load
