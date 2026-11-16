"""Logic tests, no network. Run:  python tests/test_tracker.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utf8  # noqa: F401,E402
from tracker import StabilityTracker, Segmenter, Tok, is_marker  # noqa: E402


def toks(s, seg=0):
    return [Tok(w, None, None, None, True, seg, i) for i, w in enumerate(s.split())]


def test_revised_word_is_never_committed():
    tr = StabilityTracker(600)
    assert tr.on_interim(toks("امس روح"), 0.0) == []
    assert tr.on_interim(toks("امس رحت"), 0.2) == []           # "روح" revised before it was stable
    got = tr.on_interim(toks("امس رحت للمستشفى"), 0.9)
    assert [t.w for t in got] == ["امس", "رحت"], [t.w for t in got]   # newest word held back
    assert tr.revisions == 0


def test_final_commits_only_the_remainder():
    tr = StabilityTracker(600)
    tr.on_interim(toks("امس رحت للمستشفى"), 0.0)
    tr.on_interim(toks("امس رحت للمستشفى"), 0.7)               # commits 2 (last held)
    rest = tr.on_final(toks("امس رحت للمستشفى"))
    assert [t.w for t in rest] == ["للمستشفى"]
    assert tr.seg == 1 and tr.n_committed == 0


def test_revision_after_commit_is_counted():
    tr = StabilityTracker(600)
    tr.on_interim(toks("خذ بندول حبتين"), 0.0)
    tr.on_interim(toks("خذ بندول حبتين"), 0.7)                 # "خذ بندول" committed
    tr.on_final(toks("خذ Panadol حبتين"))
    assert tr.revisions == 1


def test_markers():
    assert is_marker("وقابلت") and is_marker("وقال") and is_marker("بس") and is_marker("وبعدين")
    assert not is_marker("وين") and not is_marker("والدكتور") and not is_marker("وقت") and not is_marker("ولا")


def units_for(text, **kw):
    out = []
    sg = Segmenter(lambda u, t, c: out.append(u), "s", **kw)
    ws = [Tok(w, i * 0.4, i * 0.4 + 0.3, 0.9, False, 0, i) for i, w in enumerate(text.split())]
    sg.push(ws, 99.0)
    sg.end_of_turn(99.0)
    return out


def test_clause_cuts():
    us = units_for("أمس رحت للمستشفى وقابلت الدكتور وقال لي إن التحاليل طبيعية بس لازم أرجع بعد أسبوع", max_sec=99)
    assert [u["text"] for u in us] == ["أمس رحت للمستشفى", "وقابلت الدكتور", "وقال لي إن التحاليل طبيعية", "بس لازم أرجع بعد أسبوع"], [u["text"] for u in us]
    assert [u["boundary"] for u in us] == ["marker", "marker", "marker", "endpoint"]
    assert us[-1]["sentence_final"] and not us[0]["sentence_final"]


def test_question_and_english():
    (u,) = units_for("وين المختبر؟")
    assert u["is_question"] and u["sentence_final"] and u["boundary"] == "punct" and u["text"] == "وين المختبر"
    (u,) = units_for("خذ Panadol حبتين")
    assert [t["lang"] for t in u["tokens"]] == ["ar", "en", "ar"]


def test_forced_cut():
    us = units_for(" ".join(["كلمة"] * 30), max_sec=99, max_words=12)
    assert [len(u["tokens"]) for u in us] == [12, 12, 6] and us[0]["boundary"] == "forced"


def test_spelling_is_left_alone():
    (u,) = units_for("التَّحاليل طبيعية في المستشفى")
    assert u["text"] == "التحاليل طبيعية في المستشفى"        # tashkeel gone, ة and ى untouched


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f()
        print("ok  ", f.__name__)
    print(f"{len(fns)} passed")
