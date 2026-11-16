# Model ⇄ app contract (motion)

Stage 1 (speech → text) hands each clause to the **model service**, and the model service hands back the
motion for that clause. The phone draws the avatar from that motion. This file is the only thing the app
and the model agree on: anything behind it (checkpoint, length predictor, tokenizer, GPU) can change
without touching the app.

```
phone ──audio──▶ our server ──clause──▶ model service (GPU)
phone ◀─motion── our server ◀─motion─── model service
```

The text side is unchanged: it is the stage 1 unit in [`CONTRACT.md`](CONTRACT.md).

## 1. Our server → model service

`POST /sign` with `Authorization: Bearer <SADIH_MODEL_SECRET>` and a JSON body:

```json
{ "unit_id": 7, "text": "متى الدرس غدا", "signer": "02", "is_question": true, "session_id": "e0ac440d" }
```

| field | meaning |
|---|---|
| `unit_id` | the stage 1 unit this clause came from. Echoed back. |
| `text` | the unit's `text` exactly as stage 1 sent it. The model service applies the generator's own cleaning (`saudi_data.normalize_text`), so the app never has to know it. |
| `signer` | the signer token whose style to produce. Default `"02"`. |
| `is_question`, `session_id` | passed through for logs. The generator does not read them yet. |

Our server sends one clause at a time per session, in `unit_id` order, and waits for each reply.

## 2. Model service → our server → phone

```json
{
  "type": "motion",
  "unit_id": 7,
  "model": "madis_a_v4_joint_r2",
  "source": "generated",
  "format": "soke133",
  "fps": 24,
  "frames": 120,
  "dtype": "float16",
  "motion": "<base64 of frames × 133 little-endian float16, row by row>",
  "tokens": 30,
  "normalised": "متى الدرس غدا",
  "unseen_words": [],
  "generate_s": 0.0,
  "decode_s": 0.0
}
```

The model service returns everything except `type`; our server adds `"type": "motion"` before it relays
the object to the phone on the `/ws/audio` socket. If a clause fails, the phone gets
`{"type": "motion_error", "unit_id": 7, "message": "..."}` instead, and the session carries on.

`source` is `generated` (the generator made it), `recorded` (the clause is one of the recorded Isharah sentences,
so this is a real signer's recording; `model` is then `recorded:<signer>`) or `mock` (a test stand-in).

### The 133 numbers of one frame (`format: "soke133"`)

Fixed by SOKE's tokenizer (`avatar/exp1_tokenizer/soke_format.py`). Every group is SMPL-X **axis-angle**
(3 numbers per joint, the joint's rotation relative to its parent):

| slice | what | SMPL-X joints |
|---|---|---|
| `0:30` | upper body, 10 joints | 12 neck, 13 left collar, 14 right collar, 15 head, 16 left shoulder, 17 right shoulder, 18 left elbow, 19 right elbow, 20 left wrist, 21 right wrist |
| `30:75` | left hand, 15 joints | 25–39 (index 1-3, middle 1-3, pinky 1-3, ring 1-3, thumb 1-3) |
| `75:120` | right hand, 15 joints | 40–54, same order |
| `120:123` | jaw | 22 |
| `123:133` | face | the first 10 SMPL-X expression coefficients |

- Hands are **absolute**: the SMPL-X hand mean is already added (`hand_convention.to_absolute`), so a
  value is the joint's rotation, and zero means a flat hand. This is exactly what Nawaf's renders pose.
- Root, legs and spine are not in the motion: they stay at zero, body facing the camera (as in the renders).
- Neutral SMPL-X body, zero shape (betas).

## 3. Rules

- **Append-only, in order.** One reply per `unit_id`, in the order the units were cut.
- **The model id is in every reply**, so the app can always say which checkpoint it is showing.
- **Swapping a checkpoint does not change this file.** Changing the frame rate, the 133 layout, the
  hand convention or adding body parts does. That needs a new `format` name and both sides together.
- `frames` is always `4 × tokens`, between 40 and 400 (the generator's limits: 1.7 to 16.7 s).
