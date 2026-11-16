"""Arabic text normalisation shared by the scorer and, later, by stage 1 itself.

Both the reference and every vendor hypothesis go through the same function before WER,
otherwise spelling variance (tashkeel, alef forms, ة/ه, digits) inflates every number.
"""
import re

_TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
_TATWEEL = "ـ"
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_PUNCT = re.compile(r"[،؛؟٪-٭۔.,;:!?\"'()\[\]{}«»…\-–—/\\|*_~`]")
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9'\-]*")


def normalize(text: str) -> str:
    t = text.translate(_AR_DIGITS).translate(_FA_DIGITS)
    t = _TASHKEEL.sub("", t).replace(_TATWEEL, "")
    t = re.sub("[إأآٱ]", "ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه")
    t = _PUNCT.sub(" ", t)
    t = t.lower()
    return re.sub(r"\s+", " ", t).strip()


def latin_tokens(text: str) -> list[str]:
    """English words as they appear (before normalisation), lower-cased."""
    return [m.lower() for m in _LATIN.findall(text)]


if __name__ == "__main__":
    for s in ["أَمْسِ رُحْتُ لِلمُسْتَشْفَى ٣ مرّات؟", "خذ Panadol حبتين، بعدين ارجع."]:
        print(repr(s), "->", repr(normalize(s)), latin_tokens(s))
