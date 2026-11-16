"""Light text cleaning for stage 1.

NOT the scoring normaliser from stt-ab: that one maps ة->ه and ى->ي, which is right for WER and
wrong for the gloss model. Here we only remove what carries no meaning: tashkeel, tatweel, edge
punctuation, and we unify digits. Spelling is left alone.
"""
import re

_TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
_TATWEEL = "ـ"
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_EDGE = "،؛؟.,;:!?\"'()[]{}«»…-–—۔"
_LATIN = re.compile(r"[A-Za-z]")

Q_MARKS = ("؟", "?")
SENT_END = ("؟", "?", ".", "!", "۔")
CLAUSE_PUNCT = SENT_END + ("،", ",", "؛", ";")
Q_WORDS = {"وين", "ليش", "ليه", "كيف", "متى", "هل", "كم", "وش", "ويش", "ايش", "إيش", "اش", "مين", "منو", "شلون", "وشلون"}


def clean_word(w: str) -> str:
    w = _TASHKEEL.sub("", w).replace(_TATWEEL, "").translate(_DIGITS)
    return w.strip(_EDGE).strip()


def lang_of(w: str) -> str:
    return "en" if _LATIN.search(w) else "ar"


def ends_with(w: str, marks) -> bool:
    return w.rstrip().endswith(tuple(marks))
