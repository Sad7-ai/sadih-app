# serve/ · the model service

The generator, behind one HTTP endpoint, for the app. Clause text in, avatar motion out
([`stage1/CONTRACT-MOTION.md`](../stage1/CONTRACT-MOTION.md)).

```
phone ──audio──▶ stage1/server.py ──clause──▶ serve/model_server.py (GPU) ──▶ Demo.generate (Nawaf's demo code)
phone ◀─motion── stage1/server.py ◀─motion──┘
```

It wraps `avatar/exp4_generator/demo_generate.py`'s `Demo` class: the same code path and the same arguments as
`notebooks/exp4_demo.ipynb` section 5, without the video render. The phone draws the avatar itself.

## Swapping the model

The model branch is whatever is checked out at `SADIH_MODEL_CODE`, and the checkpoint is `SADIH_RUN_ID`.
A new checkpoint = copy its run folder, set `SADIH_RUN_ID`, restart. The app does not change, because the
motion format does not change (the contract file says what would).

## Run it

| how | command | needs |
|---|---|---|
| mock, still pose | `python model_server.py --mock` | nothing |
| mock, real recorded signing | `SADIH_SMPLX=<dir> python model_server.py --mock --clip <motion/…/feat>` | fitted clips (`.npy`, 133 per frame, 24 fps); SMPL-X only if a clip's meta says its hands are relative |
| recorded signing of the sentence said (the team's "lookup", no generator) | `SADIH_SMPLX=<file> python model_server.py --recorded <motion/<variant>>` | the team's `motion_v1` pack (499 Isharah sentences, all 15 signers; signer 02 first). A sentence with no recording gets 404 `no_recording`, so the avatar never signs something other than what was said |
| the real generator, recorded sentences first (**what the pod runs**) | `serve/runpod/prep.sh` then `serve/runpod/serve.sh` on a RunPod pod ([runpod/README.md](runpod/README.md)) | the team secret `RCLONE_CONF_B64` (written with spaces inside the braces), a new `SADIH_MODEL_SECRET`, HTTP port 8100 exposed. A clause that is a recorded sentence, plus at most one extra word, plays the real recording; anything else is generated. Each reply's `source` says which |

Then point the app at it: on the app server set `SADIH_MODEL_URL=https://<pod id>-8100.proxy.runpod.net` and
`SADIH_MODEL_SECRET` to the same secret. Its `/healthz` then shows `"model": "ok (<run id>)"`.

Run on a real pod on 2026-11-08 (L4): a new clause generates in about 0.5 s, a recorded one returns in about 0.2 s.

## Endpoints

- `POST /sign` with `Authorization: Bearer <SADIH_MODEL_SECRET>`: the contract's request and reply.
- `GET /healthz`: ready or loading, model id, device, GPU, load time, last timings. Never a secret.
- `GET /avatar.glb` (same secret): the SMPL-X body for the phone, built from this box's SMPL-X file by
  `stage1/tools/smplx_to_glb.py`. The app server fetches it once and keeps it in memory, so the licensed file never
  has to sit in git or on the app's host.

## Rules this follows

- The checkpoint and `sadih_tok_v1` never leave the GPU box. Nothing here serves a weight file
  (team rule, `avatar/exp4_generator/runpod/README.md`).
- One GPU, one clause at a time. The app server sends clauses in order and waits.
- A failure never returns a traceback, only a message the app logs. The captions never wait for the model.

## Tests

`python serve/tests/test_serve.py`: the HTTP contract on the mock, the avatar file, clip replay, and the real
backend's wiring checked against a stand-in `Demo` (the same constructor arguments as the notebook).
