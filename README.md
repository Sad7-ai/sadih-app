# صادِح · kitchen

Arabic speech → Saudi Sign Language on an avatar, live. A Deaf person opens the app and hands the phone to
whoever is speaking; what they say is signed back.

This repo is where we cook it. It is private.

```
mic ─▶ 01 Speech → Text ─▶ 02 Text → Gloss ─▶ 03 Gloss → Avatar ─▶ phone
        Ziyad                Raid               Nawaf
        └──────────── backend: Mohammed · app: Sultan ────────────┘
```

## What is here

| folder | what | state |
|---|---|---|
| [`stage1/`](stage1/) | The live app: browser mic → our server → Munsit → clause units. Two front ends — **`/app`** the iPhone demo we show people, **`/`** the playground we test with. | works end to end; real speech not yet tuned |
| [`stage1/CONTRACT.md`](stage1/CONTRACT.md) | **The JSON stage 1 hands to stage 2.** Read this before building stage 2. | v1 |
| [`stt-ab/`](stt-ab/) | Benchmark harness for speech-to-text vendors (Munsit, Soniox, Gladia, Groq Whisper). The seed of our STT benchmarks. | built, not yet run on real vendors |
| [`docs/`](docs/) | The pitch deck and the script that generates it. | |
| [`render.yaml`](render.yaml) | The whole deployment: one web service, Frankfurt, with the access code and session caps wired in. | **live at sadih.onrender.com** |
| [`docs/APK.md`](docs/APK.md) | Turning the live site into an Android APK with PWABuilder, and the asset-links step that removes the browser bar. | |

## Run the app in two minutes — no key needed

```
cd stage1
pip install -r requirements.txt
python server.py --mock
```

Open **http://localhost:8000/app** for the phone demo, or **/** for the playground, and tap the mic.
`--mock` plays a scripted transcript while you talk, so you can see the whole flow without credits. With a real key: copy `.env.example` to `.env`, put `MUNSIT_API_KEY=` in it,
and run `python server.py`.

Building stage 2? You do not need the mic or Munsit at all:

```
cd stage1
python replay.py samples/hospital.units.jsonl      # a fake stage 1 on ws://localhost:8765
python consumer.py                                 # what your stage will receive
```

## House rules

1. **No keys in git.** Keys go in `.env`, which is ignored. `.env.example` stays blank. If a key is ever
   committed, tell the team and rotate it the same day — deleting the commit is not enough.
2. **No datasets in git.** Isharah, KArSL and JUMLA are research-licensed. Keep them outside the repo.
3. **No transcripts in git.** `out/` holds what people said into the mic. It is ignored; keep it that way.
4. `main` always runs. Work on a branch, open a pull request, get one teammate to look at it.
5. Each stage owns its folder. Changing `CONTRACT.md` needs a yes from both sides of that contract.

On Windows, Arabic in the terminal is handled for you (`utf8.py`), so nothing crashes; the terminal may still
draw the letters unjoined. The files and the web page are always right.
