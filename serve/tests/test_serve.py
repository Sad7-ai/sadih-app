"""The model service without a GPU: the HTTP contract on the mock backend, and the real backend's wiring to
demo_generate.Demo checked against a stand-in Demo (same constructor arguments as notebooks/exp4_demo.ipynb).
    python serve/tests/test_serve.py
"""
import asyncio
import json
import os
import socket
import sys
import tempfile
import textwrap
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import backends  # noqa: E402
import motion  # noqa: E402

PASSED = []


def ok(msg):
    PASSED.append(msg)
    print("ok  ", msg)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def post(url, body, secret=None):
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode(),
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {secret}"} if secret else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_motion_format():
    a = np.random.default_rng(0).normal(0, 0.5, (40, 133)).astype(np.float32)
    back = motion.decode(motion.encode(a), 40)
    assert back.shape == (40, 133) and np.abs(back - a).max() < 2e-3
    for bad in (np.zeros((10, 132)), np.full((10, 133), np.nan)):
        try:
            motion.encode(bad)
            raise AssertionError("bad motion was encoded")
        except ValueError:
            pass
    assert motion.heuristic_tokens(3) == 30 and motion.heuristic_tokens(0) == 21 and motion.heuristic_tokens(99) == 100
    ok("motion: float16 round trip < 2e-3, bad shapes and NaN refused, length heuristic 3 words = 30 tokens")


def test_http_mock():
    import uvicorn
    import model_server as ms
    os.environ["SADIH_MODEL_SECRET"] = "s3cret"
    ms.STATE.update(kind="mock", clip=None, backend=None, error=None, requests=0, failures=0)
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(ms.app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=lambda: asyncio.run(srv.serve()), daemon=True)
    th.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            with urllib.request.urlopen(base + "/healthz", timeout=2) as r:
                h = json.loads(r.read())
            if h["ok"]:
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.05)
    assert h["ok"] and h["model"] == "mock" and h["needs_secret"] is True and "s3cret" not in json.dumps(h)
    ok("healthz: ready, model mock, says a secret is needed without showing it")

    st, r = post(base + "/sign", {"unit_id": 7, "text": "متى الدرس غدا"}, "s3cret")
    assert st == 200, r
    assert r["unit_id"] == 7 and r["format"] == "soke133" and r["fps"] == 24 and r["dtype"] == "float16"
    assert r["tokens"] == 30 and r["frames"] == 120 and r["model"] == "mock"
    assert motion.decode(r["motion"], r["frames"]).shape == (120, 133)
    ok("sign: 3 words -> 30 tokens = 120 frames of soke133 at 24 fps, unit id echoed, model id in the reply")

    st, r = post(base + "/sign", {"unit_id": 8, "text": "مَتى الدَّرسُ"}, "s3cret")
    assert st == 200 and r["normalised"] == "متى الدرس"
    ok("sign: tashkeel is removed before counting words")

    assert post(base + "/sign", {"unit_id": 1, "text": "x"})[0] == 401
    assert post(base + "/sign", {"unit_id": 1, "text": "x"}, "wrong")[0] == 401
    ok("sign: no secret and a wrong secret both get 401")
    st, r = post(base + "/sign", {"unit_id": 2, "text": "  "}, "s3cret")
    assert st == 400 and r["error"] == "no_text" and r["unit_id"] == 2
    st, r = post(base + "/sign", {"unit_id": 3, "text": "ا" * 301}, "s3cret")
    assert st == 400 and r["error"] == "too_long"
    ok("sign: empty and over-long text refused with 400 and the unit id")
    srv.should_exit = True
    th.join(5)
    os.environ.pop("SADIH_MODEL_SECRET", None)


def synthetic_smplx(d: Path) -> Path:
    sys.path.insert(0, str(HERE.parent / "stage1" / "tests"))
    import test_glb
    f = d / "SMPLX_NEUTRAL.npz"
    test_glb.synthetic_npz(f)
    z = dict(np.load(f))
    z["hands_meanl"], z["hands_meanr"] = np.full(45, 0.1), np.full(45, -0.2)
    np.savez(f, **z)
    return f


def test_mock_clips():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "feat").mkdir()
        (d / "meta").mkdir()
        np.save(d / "feat" / "00_0001.npy", np.zeros((50, 133), np.float32))
        np.save(d / "feat" / "00_0002.npy", np.ones((130, 133), np.float32))
        np.save(d / "feat" / "00_0003.npy", np.ones((20, 133), np.float32))          # too short: skipped
        (d / "meta" / "00_0001.json").write_text(json.dumps({"fps": 24, "hand_convention": "relative"}))
        os.environ["SADIH_SMPLX"] = str(synthetic_smplx(d))
        try:
            b = backends.MockBackend(str(d / "feat"))
        finally:
            os.environ.pop("SADIH_SMPLX")
        g1, g2, g3 = (b.sign("انا افهم الدرس", "02") for _ in range(3))
        assert g1["feat"].shape == (48, 133) and g1["tokens"] == 12
        assert np.allclose(g1["feat"][:, 30:75], 0.1) and np.allclose(g1["feat"][:, 75:120], -0.2)
        assert np.allclose(g1["feat"][:, :30], 0) and g2["feat"].shape == (128, 133) and g3["feat"].shape == (48, 133)
    ok("mock clips: each clause gets the next real clip at its own length; relative hands get the mean; short clips skipped")


def test_avatar_from_model_service():
    import uvicorn
    import model_server as ms
    with tempfile.TemporaryDirectory() as d:
        os.environ.update(SADIH_MODEL_SECRET="s3cret", SADIH_SMPLX=str(synthetic_smplx(Path(d))))
        ms.STATE.update(kind="mock", clip=None, backend=None, error=None)
        ms._AVATAR.clear()
        port = free_port()
        srv = uvicorn.Server(uvicorn.Config(ms.app, host="127.0.0.1", port=port, log_level="warning"))
        th = threading.Thread(target=lambda: asyncio.run(srv.serve()), daemon=True)
        th.start()
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                with urllib.request.urlopen(base + "/healthz", timeout=2) as r:
                    h = json.loads(r.read())
                if h["ok"]:
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.05)
        assert h["avatar"] is True
        try:
            urllib.request.urlopen(base + "/avatar.glb", timeout=5)
            raise AssertionError("avatar served without the secret")
        except urllib.error.HTTPError as e:
            assert e.code == 401
        req = urllib.request.Request(base + "/avatar.glb", headers={"Authorization": "Bearer s3cret"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        assert data[:4] == b"glTF"
        srv.should_exit = True
        th.join(5)
        for k in ("SADIH_MODEL_SECRET", "SADIH_SMPLX"):
            os.environ.pop(k, None)
    ok("avatar.glb: built on the model service from its SMPL-X file, only with the secret")


def test_recorded():
    import uvicorn
    import model_server as ms
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "feat").mkdir()
        (d / "meta").mkdir()
        clips = {"02_0001": ("ماذا تريد ان تشرب", 122, 1.0), "05_0001": ("ماذا تريد ان تشرب", 90, 5.0),
                 "05_0002": ("متى موعد الولاده", 30, 2.0)}
        for cid, (text, n, val) in clips.items():
            np.save(d / "feat" / f"{cid}.npy", np.full((n, 133), val, np.float32))
            (d / "meta" / f"{cid}.json").write_text(json.dumps({"clip_id": cid, "text": text, "fps": 24,
                                                                "hand_convention": "relative"}, ensure_ascii=False))
        os.environ["SADIH_SMPLX"] = str(synthetic_smplx(d))
        try:
            r = backends.RecordedBackend(str(d), "02")
            g = r.sign("ماذا تُريد أن تشرب؟", "02")
            assert g["matched"] == "ماذا تريد ان تشرب" and g["feat"].shape == (120, 133)
            assert np.allclose(g["feat"][:, :30], 1.0) and np.allclose(g["feat"][:, 30:75], 1.1)
            ok("recorded: the cleaned sentence finds signer 02's clip, centre-cropped to 120 frames, hand mean added")
            assert r.sign("طيب ماذا تريد ان تشرب يا خالد", "02")["matched"] == "ماذا تريد ان تشرب"
            g = r.sign("متى موعد الولادة", "02")
            assert np.allclose(g["feat"][:, :30], 2.0) and g["feat"].shape == (40, 133)
            ok("recorded: a sentence inside a longer clause is found; another signer fills a gap; short clips held to 40 frames")
            try:
                r.sign("وين المختبر", "02")
                raise AssertionError("an unknown sentence got a clip")
            except backends.NoRecording:
                pass
            os.environ["SADIH_MODEL_SECRET"] = "s3cret"
            ms.STATE.update(kind="recorded", clip=str(d), backend=None, error=None)
            port = free_port()
            srv = uvicorn.Server(uvicorn.Config(ms.app, host="127.0.0.1", port=port, log_level="warning"))
            th = threading.Thread(target=lambda: asyncio.run(srv.serve()), daemon=True)
            th.start()
            base = f"http://127.0.0.1:{port}"
            for _ in range(100):
                try:
                    with urllib.request.urlopen(base + "/healthz", timeout=2) as resp:
                        if json.loads(resp.read())["ok"]:
                            break
                except Exception:  # noqa: BLE001
                    time.sleep(0.05)
            st, rep = post(base + "/sign", {"unit_id": 4, "text": "وين المختبر"}, "s3cret")
            assert st == 404 and rep["error"] == "no_recording" and rep["unit_id"] == 4, (st, rep)
            st, rep = post(base + "/sign", {"unit_id": 5, "text": "ماذا تريد أن تشرب"}, "s3cret")
            assert st == 200 and rep["model"] == "recorded:02" and rep["frames"] == 120
            srv.should_exit = True
            th.join(5)
            ok("recorded: no recording -> 404 no_recording (the app shows the caption only); a match -> 200, model recorded:02")
        finally:
            for k in ("SADIH_SMPLX", "SADIH_MODEL_SECRET"):
                os.environ.pop(k, None)


class FakeGenerator:
    name, model_id, device, load_s, smplx = "demo", "madis_test", "cpu", 1.0, None

    def info(self):
        return {"backend": self.name, "model": self.model_id}

    def sign(self, text, signer):
        return {"feat": np.zeros((48, 133), np.float32), "tokens": 12, "normalised": text, "unseen_words": [],
                "generate_s": 0.5, "decode_s": 0.1, "confidence": None, "source": "generated", "model": self.model_id}


def test_combined():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "feat").mkdir()
        (d / "meta").mkdir()
        np.save(d / "feat" / "02_0001.npy", np.ones((80, 133), np.float32))
        (d / "meta" / "02_0001.json").write_text(json.dumps({"clip_id": "02_0001", "text": "ماذا تريد ان تشرب",
                                                             "fps": 24, "hand_convention": "absolute"}, ensure_ascii=False))
        c = backends.CombinedBackend(backends.RecordedBackend(str(d), "02"), FakeGenerator())
        route = {t: c.sign(t, "02")["source"] for t in
                 ("ماذا تريد أن تشرب؟", "طيب ماذا تريد ان تشرب", "طيب يا خالد ماذا تريد ان تشرب الحين", "كيف حالك")}
        assert route == {"ماذا تريد أن تشرب؟": "recorded", "طيب ماذا تريد ان تشرب": "recorded",
                         "طيب يا خالد ماذا تريد ان تشرب الحين": "generated", "كيف حالك": "generated"}, route
        assert c.sign("ماذا تريد ان تشرب", "02")["model"] == "recorded:02" and c.sign("كيف حالك", "02")["model"] == "madis_test"
        assert c.info()["backend"] == "combined" and c.info()["recorded_sentences"] == 1
    ok("combined: a recorded sentence (plus at most one filler word) plays the recording; anything longer or new is generated")


FAKE_DEMO = textwrap.dedent('''
    import argparse, json
    from pathlib import Path
    import numpy as np
    FREE_SENTENCES = ["انا افهم الدرس"]
    PATH_ARGS = ("config", "ckpt", "data", "madis", "soke", "probe", "length_model", "vocab", "smplx_models", "out")
    CALLS = []
    class DemoError(RuntimeError):
        pass
    def parser():
        ap = argparse.ArgumentParser()
        for k in ("--config", "--ckpt", "--data", "--madis", "--soke", "--probe", "--length-model", "--vocab",
                  "--smplx-models", "--out"):
            ap.add_argument(k, required=True)
        ap.add_argument("--run-id"); ap.add_argument("--signer"); ap.add_argument("--device")
        ap.add_argument("--length-predictor", default="heuristic")
        return ap
    class Demo:
        def __init__(self, a):
            self.a, self.device, self.load_s = a, "cpu", 1.5
            self.length_info = {"length_predictor": a.length_predictor}
            Path(a.out, "args.json").write_text(json.dumps(vars(a)))
        def generate(self, text, signer, length=None):
            CALLS.append((text, signer))
            if text == "boom":
                raise DemoError("nothing left of 'boom' after normalisation")
            return {"feat": np.ones((48, 133), np.float32), "tokens": 12, "normalised": text, "unseen_words": ["x"],
                    "generate_s": 0.4, "decode_s": 0.1, "confidence": 0.9}
''')


def test_demo_backend_wiring():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        gen = d / "kitchen" / "avatar" / "exp4_generator"
        gen.mkdir(parents=True)
        (gen / "demo_generate.py").write_text(FAKE_DEMO, encoding="utf-8")
        smplx = d / "drive" / "deps" / "smpl_models" / "smplx"
        smplx.mkdir(parents=True)
        (smplx / "SMPLX_NEUTRAL.npz").write_bytes(b"")
        env = {"SADIH_MODEL_CODE": str(d / "kitchen"), "SADIH_DATA": str(d / "drive"), "SADIH_RUN_ID": "madis_a_v5",
               "SADIH_WORK": str(d / "work"), "SADIH_SIGNER": "02"}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            b = backends.DemoBackend()
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        rec = d / "rec"
        (rec / "feat").mkdir(parents=True)
        (rec / "meta").mkdir()
        np.save(rec / "feat" / "02_0001.npy", np.ones((80, 133), np.float32))
        (rec / "meta" / "02_0001.json").write_text(json.dumps({"clip_id": "02_0001", "text": "ماذا تعمل", "fps": 24}, ensure_ascii=False))
        os.environ.update(env, SADIH_RECORDED=str(rec))
        try:
            both = backends.make("demo")
        finally:
            for k in list(env) + ["SADIH_RECORDED"]:
                os.environ.pop(k, None) if old.get(k) is None else os.environ.__setitem__(k, old[k])
        assert isinstance(both, backends.CombinedBackend) and both.sign("ماذا تعمل", "02")["source"] == "recorded"
        a = json.loads(next((d / "work").glob("madis_a_v5_*/args.json")).read_text())
        run = d / "drive" / "exp4_generator" / "runs" / "madis_a_v5"
        want = {"config": gen / "configs" / "madis_a_v5.json", "ckpt": run / "checkpoints" / "best.ckpt",
                "probe": run / "probe.npz", "length_model": run / "length_model.json",
                "vocab": run / "known_vocab.json", "smplx_models": smplx,
                "madis": d / "kitchen" / "third_party" / "madis", "soke": d / "kitchen" / "third_party" / "SOKE"}
        for k, v in want.items():
            assert Path(a[k]) == v.resolve(), (k, a[k], v)
        assert a["run_id"] == "madis_a_v5" and a["signer"] == "02" and a["length_predictor"] == "heuristic"
        assert "--length-predictor" not in b.argv, "the flag must not reach branches that do not have it"
        ok("demo backend: the same Demo arguments as the Colab notebook, from SADIH_RUN_ID alone; SMPL-X found on the Drive copy;"
           " with SADIH_RECORDED it becomes the combined backend")
        assert b.dg.CALLS[0] == ("انا افهم الدرس", "02")
        ok("demo backend: warms up once with the demo's first free sentence")
        g = b.sign("متى الدرس غدا", "02")
        assert g["feat"].shape == (48, 133) and g["tokens"] == 12 and g["unseen_words"] == ["x"]
        assert b.info()["model"] == "madis_a_v5" and b.info()["load_s"] == 1.5
        try:
            b.sign("boom", "02")
            raise AssertionError("DemoError was swallowed")
        except backends.BackendError as e:
            assert "normalisation" in str(e)
        ok("demo backend: sign() maps Demo.generate's fields; a DemoError becomes a BackendError with its message")


if __name__ == "__main__":
    test_motion_format()
    test_http_mock()
    test_mock_clips()
    test_avatar_from_model_service()
    test_recorded()
    test_combined()
    test_demo_backend_wiring()
    print(f"{len(PASSED)} passed")
