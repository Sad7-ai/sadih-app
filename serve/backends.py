"""What actually makes the motion. Two backends with one interface:

  MockBackend   no GPU, no weights. A still pose (or a recorded clip you point it at), as long as the length
                heuristic says. For building and testing the app. Every reply says model "mock".
  DemoBackend   the team's generator through avatar/exp4_generator/demo_generate.py's Demo class -- the same
                code path as notebooks/exp4_demo.ipynb section 5, minus the video render. The model branch is
                whatever is checked out at SADIH_MODEL_CODE, so a new checkpoint or a new branch never needs a
                change here.

Both return {feat (T,133) absolute hands, tokens, normalised, unseen_words, generate_s, decode_s, confidence}.
"""
import os
import re
import sys
import threading
import time
from pathlib import Path

import numpy as np

import motion

ARABIC_TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
# avatar/exp4_generator/saudi_data.py normalize_text, copied exactly, so a spoken clause meets the recorded
# sentences the way the generator meets its captions
_TASHKEEL = re.compile("[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
_PUNCT = re.compile("[\u060c\u061b\u061f\u06d4.,!?:;\"'()\\[\\]{}\xab\xbb\\-]")
_CHAR_MAP = str.maketrans({"\u0623": "\u0627", "\u0625": "\u0627", "\u0622": "\u0627", "\u0671": "\u0627",
                           "\u0629": "\u0647", "\u0640": None,
                           **{str(d): chr(0x0660 + d) for d in range(10)},
                           **{chr(0x06f0 + d): chr(0x0660 + d) for d in range(10)}})


def normalize_text(s: str) -> str:
    s = _TASHKEEL.sub("", s).translate(_CHAR_MAP)
    s = _PUNCT.sub(" ", s)
    return " ".join(s.split())


class BackendError(RuntimeError):
    pass


class NoRecording(BackendError):
    """The recorded backend has no clip of this sentence. Not a failure: the app shows the caption only."""


class MockBackend:
    """No GPU. With clips: each clause gets the next recorded clip at its OWN length and speed (real signing, not
    the clause's meaning). Without: a still arms-down pose as long as the length heuristic says."""
    name = "mock"

    def __init__(self, clip_path: str | None = None):
        self.clips = load_clips(clip_path) if clip_path else []
        self.next = 0
        self.load_s = 0.0
        self.device = "cpu"
        self.model_id = "mock"
        self.smplx = smplx_file(os.environ.get("SADIH_SMPLX"))

    def info(self) -> dict:
        return {"backend": self.name, "model": self.model_id, "device": self.device, "load_s": self.load_s,
                "clips": len(self.clips) or "still pose"}

    def sign(self, text: str, signer: str) -> dict:
        t0 = time.perf_counter()
        norm = " ".join(ARABIC_TASHKEEL.sub("", text).split())
        if not norm:
            raise BackendError("nothing left of the text after cleaning")
        if self.clips:
            feat = self.clips[self.next % len(self.clips)]
            self.next += 1
        else:
            feat = np.zeros((motion.heuristic_tokens(len(norm.split())) * motion.UNIT, motion.DIM), np.float32)
            feat[:, 3 * 4 + 2], feat[:, 3 * 5 + 2] = -1.2, 1.2     # arms down, as web/avatar.js IDLE (zeros = T-pose)
        return {"feat": feat, "tokens": len(feat) // motion.UNIT, "normalised": norm, "unseen_words": [],
                "generate_s": round(time.perf_counter() - t0, 3), "decode_s": 0.0, "confidence": None,
                "source": "mock", "model": self.model_id}


def smplx_file(path) -> Path | None:
    """SMPLX_NEUTRAL.npz from a file or a folder (searched), or None."""
    if not path:
        return None
    p = Path(path).expanduser()
    if p.is_file():
        return p
    found = sorted(p.rglob("SMPLX_NEUTRAL.npz")) if p.is_dir() else []
    return found[0] if found else None


def hands_mean(smplx: Path | None) -> np.ndarray:
    if smplx is None:
        raise BackendError("a clip stores RELATIVE hands; set SADIH_SMPLX so the hand mean can be added")
    with np.load(smplx, allow_pickle=False) as z:
        return np.concatenate([np.asarray(z["hands_meanl"], np.float32).reshape(45),
                               np.asarray(z["hands_meanr"], np.float32).reshape(45)])


def load_clips(path: str) -> list:
    """A recorded fit (.npy (frames, 133) at 24 fps, as in motion/<variant>/feat/) or a folder of them. Each is cut
    to a whole number of tokens within the generator's limits. Hands are made absolute when the clip's meta file
    (../meta/<clip>.json) says they are relative, exactly as render_dev.fit_feat does."""
    p = Path(path)
    files = sorted(p.glob("*.npy")) if p.is_dir() else [p]
    if not files:
        raise BackendError(f"no .npy clips in {p}")
    out, mean = [], None
    for f in files:
        a = np.load(f)
        a = np.asarray(a["feat"] if hasattr(a, "files") else a, np.float32)
        if a.ndim != 2 or a.shape[1] != motion.DIM:
            raise BackendError(f"{f}: expected (frames, {motion.DIM}), got {a.shape}")
        meta = f.parent.parent / "meta" / f"{f.stem}.json"
        if meta.exists():
            import json
            m = json.loads(meta.read_text(encoding="utf-8"))
            if m.get("fps", motion.FPS) != motion.FPS:
                raise BackendError(f"{meta}: fps {m.get('fps')}, the avatar plays {motion.FPS}")
            if m.get("hand_convention") == "relative":
                if mean is None:
                    mean = hands_mean(smplx_file(os.environ.get("SADIH_SMPLX")))
                a = a.copy()
                a[:, 30:120] += mean
        n = min(motion.MAX_FRAMES, len(a)) // motion.UNIT * motion.UNIT
        if n < motion.MIN_FRAMES:
            continue
        out.append(a[:n])
    if not out:
        raise BackendError(f"every clip in {p} is shorter than {motion.MIN_FRAMES} frames")
    return out


class RecordedBackend:
    """The team's "lookup" reference, NOT the generator: a spoken clause that is one of the recorded Isharah sentences
    (cleaned as above) gets that signer's real recorded clip; a clause that contains one gets the longest such.
    Anything else gets NoRecording, so the avatar never signs something other than what was said.
    variant_dir = motion/<fit variant>/ from the team's motion pack (feat/*.npy + meta/*.json, 24 fps)."""
    name = "recorded"

    def __init__(self, variant_dir: str, signer: str = "02"):
        import json
        v = Path(variant_dir)
        self.signer, self.smplx = signer, smplx_file(os.environ.get("SADIH_SMPLX"))
        self.index, other = {}, {}
        for m in sorted((v / "meta").glob("*.json")):
            j = json.loads(m.read_text(encoding="utf-8"))
            text = normalize_text(j.get("text") or "")
            f = v / "feat" / f"{j['clip_id']}.npy"
            if not text or not f.exists() or j.get("fps", motion.FPS) != motion.FPS:
                continue
            entry = (f, j.get("hand_convention", "absolute"))
            if j["clip_id"].split("_")[0] == signer:
                self.index.setdefault(text, entry)
            else:
                other.setdefault(text, entry)
        for t, e in other.items():                      # a sentence this signer never recorded: another signer's
            self.index.setdefault(t, e)
        if not self.index:
            raise BackendError(f"no recorded clips with text in {v}")
        self.mean = None
        self.load_s, self.device, self.model_id = 0.0, "cpu", f"recorded:{signer}"

    def info(self) -> dict:
        return {"backend": self.name, "model": self.model_id, "device": self.device, "load_s": self.load_s,
                "sentences": len(self.index)}

    def match(self, text: str):
        norm = normalize_text(text)
        if norm in self.index:
            return norm, norm
        words = norm.split()
        best = None
        for n in range(len(words) - 1, 1, -1):          # the longest recorded sentence inside the clause, 2+ words
            for i in range(len(words) - n + 1):
                cand = " ".join(words[i:i + n])
                if cand in self.index:
                    best = cand
                    break
            if best:
                break
        return norm, best

    def sign(self, text: str, signer: str) -> dict:
        t0 = time.perf_counter()
        norm, hit = self.match(text)
        if not hit:
            raise NoRecording("No recording of this sentence.")
        f, conv = self.index[hit]
        feat = np.load(f, allow_pickle=False).astype(np.float32)
        if conv == "relative":
            if self.mean is None:
                self.mean = hands_mean(self.smplx)
            feat[:, 30:120] += self.mean
        n = (len(feat) // motion.UNIT) * motion.UNIT    # lengths.crop_to_unit: the centre multiple of 4
        a = (len(feat) - n) // 2
        feat = feat[a:a + n][:motion.MAX_FRAMES]
        if len(feat) < motion.MIN_FRAMES:                # hold the last frame up to the generator's minimum
            feat = np.concatenate([feat, np.repeat(feat[-1:], motion.MIN_FRAMES - len(feat), 0)])
        return {"feat": feat, "tokens": len(feat) // motion.UNIT, "normalised": norm, "unseen_words": [],
                "generate_s": round(time.perf_counter() - t0, 3), "decode_s": 0.0, "confidence": None,
                "matched": hit, "source": "recorded", "model": self.model_id}


def _env_path(name: str, default=None) -> str:
    v = os.environ.get(name) or default
    if not v:
        raise BackendError(f"{name} is not set")
    return str(Path(v).expanduser().resolve())


class DemoBackend:
    """Loads Demo once. Generation runs under a lock: one GPU, one clause at a time, in arrival order."""
    name = "demo"

    def __init__(self):
        code = Path(_env_path("SADIH_MODEL_CODE"))            # a checkout of the model branch (kitchen repo root)
        gen = code / "avatar" / "exp4_generator"
        if not (gen / "demo_generate.py").exists():
            raise BackendError(f"{gen}/demo_generate.py not found: SADIH_MODEL_CODE must be a kitchen checkout "
                               "of a branch that has the generator (e.g. raed_SMPL-X)")
        self.run_id = os.environ.get("SADIH_RUN_ID", "madis_a_v4_joint_r2")
        data = Path(_env_path("SADIH_DATA"))                  # the Drive root copy: tokens/, tokenizer/, deps/, exp4_generator/
        run_dir = Path(_env_path("SADIH_RUN_DIR", str(data / "exp4_generator" / "runs" / self.run_id)))
        smplx = os.environ.get("SADIH_SMPLX")
        if not smplx:
            found = sorted((data / "deps" / "smpl_models").rglob("SMPLX_NEUTRAL.npz"))
            if not found:
                raise BackendError(f"no SMPLX_NEUTRAL.npz under {data}/deps/smpl_models (or set SADIH_SMPLX)")
            smplx = str(found[0].parent)
        self.smplx = smplx_file(smplx)
        work = (Path(_env_path("SADIH_WORK", "/tmp/sadih_serve"))
                / f"{self.run_id}_{time.strftime('%Y%m%d_%H%M%S')}_{os.urandom(3).hex()}")   # Demo wants a NEW folder
        work.parent.mkdir(parents=True, exist_ok=True)
        argv = ["--config", str(gen / "configs" / f"{self.run_id}.json"),
                "--ckpt", str(run_dir / "checkpoints" / "best.ckpt"),
                "--data", str(data),
                "--madis", _env_path("SADIH_MADIS", str(code / "third_party" / "madis")),
                "--soke", _env_path("SADIH_SOKE", str(code / "third_party" / "SOKE")),
                "--probe", str(run_dir / "probe.npz"),
                "--length-model", str(run_dir / "length_model.json"),
                "--vocab", str(run_dir / "known_vocab.json"),
                "--smplx-models", smplx,
                "--run-id", self.run_id,
                "--signer", os.environ.get("SADIH_SIGNER", "02"),
                "--out", str(work)]
        lp = os.environ.get("SADIH_LENGTH_PREDICTOR", "heuristic")
        if lp != "heuristic":                                 # older branches have no such flag: pass it only when chosen
            argv += ["--length-predictor", lp]
        if os.environ.get("SADIH_DEVICE"):
            argv += ["--device", os.environ["SADIH_DEVICE"]]
        sys.path.insert(0, str(gen))
        import demo_generate as dg                             # noqa: E402  only now: it pulls torch, MaDiS, SOKE
        self.dg = dg
        a = dg.parser().parse_args(argv)
        for k in dg.PATH_ARGS:
            if getattr(a, k, None):
                setattr(a, k, str(Path(getattr(a, k)).resolve()))
        Path(a.out).mkdir(parents=True)
        self.demo = dg.Demo(a)
        self.device = self.demo.device
        self.load_s = self.demo.load_s
        self.model_id = self.run_id
        self.lock = threading.Lock()
        self.argv = argv
        free = getattr(dg, "FREE_SENTENCES", None)
        if free:                                              # warm the GPU so the first real clause is not the slow one
            self.sign(free[0], os.environ.get("SADIH_SIGNER", "02"))

    def info(self) -> dict:
        i = {"backend": self.name, "model": self.model_id, "device": self.device, "load_s": self.load_s,
             "length_predictor": getattr(self.demo, "length_info", {}).get("length_predictor", "heuristic")}
        try:
            import torch
            if torch.cuda.is_available():
                i["gpu"] = torch.cuda.get_device_name(0)
                i["peak_gpu_gb"] = round(torch.cuda.max_memory_allocated() / 2 ** 30, 2)
        except Exception:  # noqa: BLE001
            pass
        return i

    def sign(self, text: str, signer: str) -> dict:
        with self.lock:
            try:
                g = self.demo.generate(text, signer)
            except self.dg.DemoError as e:
                raise BackendError(str(e)) from e
        return {"feat": g["feat"], "tokens": int(g["tokens"]), "normalised": g["normalised"],
                "unseen_words": list(g["unseen_words"]), "generate_s": g["generate_s"], "decode_s": g["decode_s"],
                "confidence": g.get("confidence"), "source": "generated", "model": self.model_id}


class CombinedBackend:
    """Ziyad's choice (2026-11-08): a clause that IS one of the recorded sentences plays the real recording; anything
    else goes to the generator. "Is" allows one extra word around the sentence (a filler such as طيب); a longer
    clause goes to the generator, which signs all of it instead of dropping words. Every reply says its source."""
    name = "combined"
    EXTRA_WORDS = 1

    def __init__(self, recorded, generator):
        self.recorded, self.generator = recorded, generator
        self.smplx = getattr(generator, "smplx", None) or recorded.smplx
        self.model_id, self.device, self.load_s = generator.model_id, generator.device, generator.load_s

    def info(self) -> dict:
        return {**self.generator.info(), "backend": self.name, "recorded_sentences": len(self.recorded.index)}

    def sign(self, text: str, signer: str) -> dict:
        norm, hit = self.recorded.match(text)
        if hit and len(norm.split()) - len(hit.split()) <= self.EXTRA_WORDS:
            return self.recorded.sign(text, signer)
        return self.generator.sign(text, signer)


def make(kind: str, clip: str | None = None):
    if kind == "mock":
        return MockBackend(clip)
    if kind == "recorded":
        if not clip:
            raise BackendError("recorded needs the motion folder (--recorded <motion/<variant>>)")
        return RecordedBackend(clip, os.environ.get("SADIH_SIGNER", "02"))
    if kind == "demo":
        gen = DemoBackend()
        rec = os.environ.get("SADIH_RECORDED")                 # the motion pack: recorded sentences first
        return CombinedBackend(RecordedBackend(rec, os.environ.get("SADIH_SIGNER", "02")), gen) if rec else gen
    raise BackendError(f"unknown backend {kind!r} (mock | recorded | demo)")
