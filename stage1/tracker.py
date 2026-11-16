"""Pure logic, no I/O. Two jobs:

StabilityTracker  which words of a changing hypothesis are safe to commit
Segmenter         where to cut committed words into clauses, and the unit handed to text-to-gloss

Vendor semantics this is written against (Munsit /listen):
  interim Results   whole hypothesis of the open segment; "may revise earlier words"
  is_final          that segment's text is frozen -> hard commit of whatever we had not committed yet
  speech_final      the speaker really stopped    -> end of sentence
Finals only arrive on silence or every ~60 s, so during continuous speech the interims are all we get.
"""
from __future__ import annotations

from dataclasses import dataclass

from textnorm import clean_word, lang_of, ends_with, SENT_END, CLAUSE_PUNCT, Q_MARKS, Q_WORDS


@dataclass
class Tok:
    w: str
    t0: float | None = None
    t1: float | None = None
    conf: float | None = None
    approx: bool = False   # timing taken from the audio clock, not from the vendor
    seg: int = 0           # vendor segment serial
    pos: int = 0           # position inside that segment


class StabilityTracker:
    """A word is committed once it has sat unchanged at the same position for stable_ms.
    The newest word of an interim is never committed (hold_last): it is the one still growing."""

    def __init__(self, stable_ms: int = 600, hold_last: bool = True):
        self.stable = stable_ms / 1000
        self.hold_last = hold_last
        self.seg = 0
        self.n_committed = 0
        self.committed: list[str] = []
        self.seen: dict[tuple[int, str], float] = {}
        self.revisions = 0               # committed words the vendor later changed — cannot be un-sent
        self._flagged: set[tuple[int, int]] = set()

    def _check_revisions(self, words: list[Tok]):
        for i, w in enumerate(self.committed):
            if (i >= len(words) or words[i].w != w) and (self.seg, i) not in self._flagged:
                self._flagged.add((self.seg, i))
                self.revisions += 1

    def on_interim(self, words: list[Tok], now: float) -> list[Tok]:
        live = {(i, t.w) for i, t in enumerate(words)}
        self.seen = {k: v for k, v in self.seen.items() if k in live}
        for k in live:
            self.seen.setdefault(k, now)
        self._check_revisions(words)

        n = self.n_committed
        while n < len(words) and now - self.seen[(n, words[n].w)] >= self.stable:
            n += 1
        if self.hold_last:
            n = min(n, len(words) - 1)
        n = max(n, self.n_committed)
        new = words[self.n_committed:n]
        self.committed += [t.w for t in new]
        self.n_committed = n
        return new

    def on_final(self, words: list[Tok]) -> list[Tok]:
        self._check_revisions(words)
        new = words[self.n_committed:]
        self.seg += 1
        self.n_committed = 0
        self.committed = []
        self.seen = {}
        return new


# --- clause boundaries -------------------------------------------------------------------------
MARKERS = {"بعدين", "لكن", "بس", "يعني", "عشان", "علشان", "لأن", "لان", "لأنه", "لانه", "ثم", "طيب",
           "إذا", "اذا", "لو", "عقب", "عقبها"}
# words that start with و where the و is part of the word, not "and"
WAW_STOP = {"وين", "وش", "ويش", "وشلون", "وقت", "وقتها", "ولد", "واحد", "وحده", "وحدة", "ورقة", "ورقه", "وزن",
            "وجه", "وضع", "وصل", "وصلت", "وصفة", "وصفه", "وريد", "وراء", "ورا", "وسط", "وزارة", "وزاره",
            "وظيفة", "وظيفه", "وكالة", "ولا", "والله", "وايد", "واجد", "واضح", "وجع", "ورم", "وعي",
            "وقف", "وقفت", "وافق", "وافقت"}


def is_marker(w: str) -> bool:
    """True if this word opens a new clause. Spoken Arabic chains clauses with و + verb (وقابلت، وقال),
    so that is the main signal; و + ال… is usually a noun list (الدكتور والممرضة) and is left alone."""
    if w in MARKERS:
        return True
    if len(w) >= 4 and w[0] == "و" and w not in WAW_STOP:
        rest = w[1:]
        return rest in MARKERS or not rest.startswith("ال")
    return False


class Segmenter:
    def __init__(self, on_unit, session_id: str, max_words: int = 12, max_sec: float = 3.0, min_words: int = 2):
        self.on_unit = on_unit
        self.session_id = session_id
        self.max_words, self.max_sec, self.min_words = max_words, max_sec, min_words
        self.buf: list[Tok] = []
        self.unit_id = 0
        self.cuts = {"marker": 0, "punct": 0, "forced": 0, "endpoint": 0}

    def push(self, toks: list[Tok], clock: float):
        for t in toks:
            if len(self.buf) >= self.min_words and is_marker(clean_word(t.w)):
                self._flush("marker", clock)
            self.buf.append(t)
            if ends_with(t.w, SENT_END):
                self._flush("punct", clock, sentence_final=True)
            elif ends_with(t.w, CLAUSE_PUNCT) and len(self.buf) >= self.min_words:
                self._flush("punct", clock)
            elif self._forced():
                self._flush("forced", clock)

    def end_of_turn(self, clock: float):
        if self.buf:
            self._flush("endpoint", clock, sentence_final=True)

    def _forced(self) -> bool:
        if len(self.buf) >= self.max_words:
            return True
        a, b = self.buf[0].t0, self.buf[-1].t1
        return a is not None and b is not None and (b - a) >= self.max_sec

    def _flush(self, why: str, clock: float, sentence_final: bool = False):
        toks, self.buf = self.buf, []
        kept = [(t, clean_word(t.w)) for t in toks]
        kept = [(t, c) for t, c in kept if c]
        if not kept:
            return
        self.unit_id += 1
        self.cuts[why] += 1
        confs = [t.conf for t, _ in kept if t.conf is not None]
        unit = {
            "unit_id": self.unit_id,
            "session_id": self.session_id,
            "text": " ".join(c for _, c in kept),
            "text_raw": " ".join(t.w for t in toks),
            "tokens": [{"w": c, "t0": t.t0, "t1": t.t1, "lang": lang_of(c), "conf": t.conf} for t, c in kept],
            "t_start": kept[0][0].t0,
            "t_end": kept[-1][0].t1,
            "boundary": why,
            "sentence_final": sentence_final,
            "is_question": any(ends_with(t.w, Q_MARKS) for t in toks) or kept[0][1] in Q_WORDS,
            "confidence": round(sum(confs) / len(confs), 3) if confs else None,
            "timing": "approx" if any(t.approx for t, _ in kept) else "exact",
        }
        self.on_unit(unit, [t for t, _ in kept], clock)
