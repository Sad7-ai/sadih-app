"""Munsit events in, clause units out. No I/O — the CLI (stage1.py) and the web server (server.py)
both drive this same object, so what is tested against the mock is what runs live.
"""
import statistics
import time

from tracker import StabilityTracker, Segmenter, Tok


def toks_from_event(ev: dict, seg: int) -> list[Tok]:
    """Prefer the transcript's tokens for text (they keep punctuation) and words[] for timing."""
    parts = (ev.get("transcript") or "").split()
    ws = ev.get("words") or []
    if ws and len(ws) == len(parts):
        return [Tok(parts[i], w.get("start"), w.get("end"), w.get("confidence"), False, seg, i) for i, w in enumerate(ws)]
    if ws:
        return [Tok(w.get("word", ""), w.get("start"), w.get("end"), w.get("confidence"), False, seg, i) for i, w in enumerate(ws)]
    return [Tok(p, None, None, None, True, seg, i) for i, p in enumerate(parts)]


class Pipeline:
    def __init__(self, session_id: str, on_unit, on_interim=None, on_latency=None, *, stable_ms: int = 600,
                 hold_last: bool = True, max_words: int = 12, max_sec: float = 3.0, min_words: int = 2):
        self.session_id = session_id
        self.on_unit, self.on_interim, self.on_latency = on_unit, on_interim, on_latency
        self.trk = StabilityTracker(stable_ms, hold_last)
        self.seg = Segmenter(self._unit, session_id, max_words, max_sec, min_words)
        self.latencies: list[float] = []
        self._waiting: list[dict] = []   # units cut from interims: their true word-end time arrives with the final
        self._last_t1 = 0.0
        self.n_interim = self.n_final = 0

    # -- internals
    def _lat(self, unit_id: int, value: float):
        self.latencies.append(value)
        if self.on_latency:
            self.on_latency(unit_id, round(value, 2))

    def _unit(self, unit: dict, toks: list[Tok], clock: float):
        self.on_unit(unit)
        last = toks[-1]
        if last.approx:
            self._waiting.append({"unit_id": unit["unit_id"], "seg": last.seg, "pos": last.pos, "clock": clock})
        elif last.t1 is not None:
            self._lat(unit["unit_id"], clock - last.t1)

    def _stamp(self, toks: list[Tok], clock: float) -> list[Tok]:
        """Interims may carry no word timing; use the audio clock so units still have an order and a span."""
        for t in toks:
            if t.t1 is None:
                t.t0, t.t1, t.approx = max(self._last_t1, clock - 0.4), clock, True
            self._last_t1 = t.t1
        return toks

    def _show(self, pending: list[Tok]):
        if self.on_interim:
            self.on_interim(" ".join(t.w for t in self.seg.buf), " ".join(t.w for t in pending))

    # -- API
    def handle(self, ev: dict, clock: float):
        """Feed one Munsit event. `clock` = seconds of audio sent so far."""
        typ = ev.get("type")
        if typ == "Results":
            toks = toks_from_event(ev, self.trk.seg)
            if ev.get("is_final"):
                self.n_final += 1
                for w in [w for w in self._waiting if w["seg"] == self.trk.seg]:
                    if w["pos"] < len(toks) and not toks[w["pos"]].approx and toks[w["pos"]].t1 is not None:
                        self._lat(w["unit_id"], w["clock"] - toks[w["pos"]].t1)
                    self._waiting.remove(w)
                self.seg.push(self._stamp(self.trk.on_final(toks), clock), clock)
                if ev.get("speech_final"):
                    self.seg.end_of_turn(clock)
                self._show([])
            else:
                self.n_interim += 1
                self.seg.push(self._stamp(self.trk.on_interim(toks, time.perf_counter()), clock), clock)
                self._show(toks[self.trk.n_committed:])
        elif typ == "UtteranceEnd":
            self.seg.end_of_turn(clock)
            self._show([])

    def finish(self, clock: float) -> dict:
        self.seg.end_of_turn(clock)
        lat = sorted(self.latencies)
        return {
            "session": self.session_id, "units": self.seg.unit_id, "cuts": self.seg.cuts,
            "interims": self.n_interim, "finals": self.n_final,
            "revisions_after_commit": self.trk.revisions,
            "latency_median_s": round(statistics.median(lat), 2) if lat else None,
            "latency_p90_s": round(lat[int(len(lat) * 0.9) - 1], 2) if len(lat) >= 5 else None,
            "audio_s": round(clock, 1),
        }
