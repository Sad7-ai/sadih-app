# صادِح · stage 1 — live speech → clause units

Browser mic → **our server** → Munsit live streaming (`munsit-en-ar`) → stability tracker → clause segmenter →
JSON units for text-to-gloss. The unit format is in [CONTRACT.md](CONTRACT.md).

```
browser mic ──PCM16 16 kHz──▶ server.py ──▶ Munsit
     ▲                           │  tracker + segmenter
     └── live text + units ◀─────┴──▶ /ws/units   (stage 2 connects here)
     └── avatar motion ◀──── model service, when SADIH_MODEL_URL is set (see "The avatar" below)
```

The API key lives in `.env` on the server and never reaches the browser.

```
pip install -r requirements.txt
copy .env.example .env            # MUNSIT_API_KEY=...

python server.py                  # then open one of the two pages below
python server.py --mock           # no key: a local mock plays a scripted transcript while you "speak"
python consumer.py --url ws://localhost:8000/ws/units      # what stage 2 receives, live
```

Two surfaces on the same server, same session, same `/ws/audio`:

| page | who it is for |
|---|---|
| **`/app`** — the **demo** | What we show people. A mock iPhone: lock screen, home screen, mock apps, and صادِح inside it in Arabic. A floating button sits over every screen; tap it for a small window you can drag, resize and expand — so the app is reachable without leaving whatever you are in. |
| **`/app` on a real phone** | Same demo, using the real screen. See the three modes below. |

### Three ways `/app` can render

| mode | what you see | when |
|---|---|---|
| **`frame`** | The drawn iPhone sitting on a desk | a laptop — presenting to a room. Force with `?frame=1` |
| **`shell`** | The same simulation full screen: lock screen, home screen, 20 icons, dock, mock apps, and the floating button — but no drawn bezel, because the real phone has its own | **a real phone, and what the installed app opens**. Force with `?shell=1` |
| **`bare`** | صادِح alone, no simulation | what the finished product would look like. Force with `?bare=1` |

An installed app gets `shell`, not `bare`: the home screen, the icons and the floating button *are*
the demo. Only the drawn bezel makes no sense inside a real phone.
| **`/`** — the **playground** | What we use. Every unit, why it was cut, how late it was, how many words the recogniser took back. |

`localhost` counts as a secure origin, so the mic works with plain http. To open it from a real phone you
need https — put a tunnel in front of port 8000.

Command line, for testing without a browser: `python stage1.py --mic` · `--wav clip.m4a` · `--silence 17 --url ws://localhost:8766`

No key yet? Everything runs against a local mock that speaks Munsit's protocol:

```
python tests/test_tracker.py                 # logic, instant
python tests/e2e_mock.py                     # mock Munsit + CLI pipeline, ~17 s
python tests/e2e_server.py                   # mock Munsit + web server + a fake browser client, ~17 s
python tests/browser_smoke.py                # the playground in real headless Edge, fake mic
python tests/demo_smoke.py                   # the /app demo: unlock, float, listen, drag, resize, expand
python tests/pwa_smoke.py                    # manifest + icons + a real phone viewport gets bare mode
python tests/deploy_smoke.py                 # access code, session caps, transcript logging off
```

## Why it is built this way

Munsit, like every streaming STT, is built for voice agents: it finalises text when the speaker **pauses**
(`endpointing`) or every ~60 s. A person explaining something does not pause. So finals alone would put us up
to a minute behind. Two settings and one component fix that:

- `endpointing=300`, `smart_turn=false` — we caption, we do not take turns; we want finals as early as they come.
- **StabilityTracker** — commits a word from the *interim* results once it has sat unchanged at the same
  position for `--stable-ms` (600). The newest word is always held back; it is the one still changing.
  A final is a hard commit of whatever is left.
- **Segmenter** — cuts committed words into clauses: before a clause opener (وقال، بس، بعدين، عشان…), after
  recogniser punctuation, or forced at 12 words / 3 s. A real pause closes the sentence.

## Files each session writes to `out/`

| file | what |
|---|---|
| `<session>.units.jsonl` | the units — the product of this stage |
| `<session>.raw.jsonl` | every event Munsit sent, with our audio clock. **Read this first.** |
| `<session>.stats.json` | units, cut reasons, interims/finals, `revisions_after_commit`, latency median / p90 |

`latency_*` = how far behind the audio a unit was when it left stage 1, measured against the recogniser's
own word-end times. On the mock it is ~1.4 s; most of that is the 600 ms stability window plus holding the last word.

## Two things to check on the first real run (open the raw log)

1. Do interim `Results` carry `words[]` with timings? If yes, units cut from interims get `timing: exact`
   for free. If no, they are `approx` (audio clock at commit).
2. After an `is_final`, does the next interim start from empty? The tracker assumes it does.

## Knobs worth turning

| flag | effect |
|---|---|
| `--stable-ms 400` | faster, more risk that a committed word is later revised — watch `revisions_after_commit` |
| `--no-hold-last` | saves about one word of delay, same risk |
| `--min-words 3` | fewer, longer clauses |
| `--endpointing 500` | fewer mid-thought finals; docs say 300 costs ~2 WER |
| `hotwords.txt` | one term per line, ≤200 × 40 chars, sent at connect; dropped ones are printed |

## Deploying

`render.yaml` at the repo root is the whole deployment. In Render: **New → Blueprint → Sad7-ai/kitchen**.
It asks for `MUNSIT_API_KEY` and `SADIH_ACCESS_CODE`, then builds `requirements-server.txt`
(four packages, no numpy) and runs uvicorn.

Nothing is public without these, and all four are checked by `tests/deploy_smoke.py`:

| env var | default | what it stops |
|---|---|---|
| `SADIH_ACCESS_CODE` | none | anyone with the URL spending our Munsit credits. The page asks for it once and remembers it; a code the server rejects is forgotten. |
| `SADIH_MAX_SESSIONS` | 3 | more than Munsit's 5-per-key limit at once. The next person is told the service is busy. |
| `SADIH_MAX_SESSION_S` | 900 | a forgotten tab billing us for an hour. |
| `SADIH_LOG_TRANSCRIPTS` | on locally, **off on a host** | writing what people said onto a server. `out/` is where we debug; it has no business existing in production. |

The free plan sleeps after 15 minutes idle and takes about a minute to wake. For a demo day, switch
that one service to `starter` (~$7/month) so nobody waits on a cold start.

## The avatar (stage 3 in the app)

Each unit also goes to the **model service** ([`../serve/`](../serve/README.md)), which answers with that clause's
motion. The phone plays it on the SMPL-X body above the captions. Format: [CONTRACT-MOTION.md](CONTRACT-MOTION.md).

```
phone ──audio──▶ server.py ──unit──▶ model service (GPU) ──▶ motion ──▶ server.py ──▶ phone: avatar + captions
```

It is **off unless `SADIH_MODEL_URL` is set**, so without it the app is exactly the captions-only app.

| env var | what |
|---|---|
| `SADIH_MODEL_URL` | empty = off. `mock` = a still pose of the right length, no GPU. Otherwise the model service, e.g. `https://<pod id>-8100.proxy.runpod.net`. |
| `SADIH_MODEL_SECRET` | the model service's bearer secret. |
| `SADIH_SIGNER` | signer token for the avatar's style, default `02`. |
| `SADIH_AVATAR_GLB` | a local body file (default `private/avatar.glb`). Without one, the body comes from the model service. |
| `SADIH_MODEL_TIMEOUT_S`, `SADIH_MODEL_DRAIN_S` | 60 s per clause; 90 s to finish the queue after the speaker stops. |

- One clip per unit, in unit order, always after its caption and before `done`. A slow or broken model only costs
  avatar clips (`motion_error`); the captions never wait for it.
- The player (`web/avatar.js`, three.js 0.160.0 vendored in `web/vendor/three`, MIT) blends 0.25 s between clips and
  plays up to 1.25× while clips are waiting. It shows «متأخر N ث» when it is 2 s or more behind the speaker.
- The body: `python tools/smplx_to_glb.py SMPLX_NEUTRAL.npz private/avatar.glb` (licensed; `private/` and `*.glb`
  are git-ignored). Its bones are the SMPL-X joints, so the motion is set straight on them, with no retargeting.
- Run it all locally with no GPU: `SADIH_MODEL_URL=mock python server.py --mock` (plus a body file).

Tests: `tests/test_glb.py` (glTF skinning == SMPL-X), `tests/e2e_model.py` (five ways the model can be set up or
fail), `tests/avatar_smoke.py` (the player in headless Edge; three.js joints == SMPL-X math).

## Installing it on a phone

The app is installable: `/manifest.webmanifest`, icons in `web/icons/` (regenerate with
`python tools/make_icons.py` — it needs Edge, and the PNGs are committed so nobody else does).

Three routes, **all of which need the server reachable over https** — a phone cannot reach your laptop's
`localhost`, and the microphone is blocked on anything that is not a secure origin:

| route | gives you | needs |
|---|---|---|
| **Add to Home Screen** | icon, full screen, no browser bar; iPhone *and* Android | nothing more |
| **PWABuilder → APK** | an `.apk` file you can hand out | the https URL — step by step in [docs/APK.md](../docs/APK.md) |
| **Capacitor** | a full native shell | Android Studio + SDK |

For a quick test on a real phone, `ngrok http 8000` gives an https URL in seconds. Anyone holding that
link can spend the Munsit credits, so close the tunnel afterwards — or wait for the access code.

One thing no web route can do: **float over other apps**. That needs a native Android app with overlay
permission, and on iOS it is not possible at all. The mock phone at `/app?frame=1` is the only way to
show that idea today.

## Known limitations (on purpose, it is a prototype)

- No reconnect. If the socket drops, the session ends.
- Mic mode streams silence too, so Munsit's 12 s idle timeout cannot fire — and silence is billed.
- A word committed from an interim and later changed by the recogniser cannot be recalled; it is only counted.
- The و-rule is a heuristic: و + verb opens a clause, و + ال… does not, and a stop-list covers words where و is
  part of the root (وين، وقت، واحد…). It will be wrong sometimes; `cuts` in the stats shows how much it fires.
- The API key rides in the URL. Fine on a laptop; the app must go through the backend.
