"""Name normalization for Arabic + English football entity matching.

This is the piece every commercial API gets wrong for Arab football: the same
club is written a dozen ways across scripts ("الهلال" / "Al-Hilal" / "Al Hilal" /
"AlHilal SFC"), and namesakes are everywhere (three different "Al Ahli"s).

`norm()` maps any spelling to a comparable key. It is deliberately aggressive:
matching is always scoped by country/competition upstream, so over-normalizing
inside a scope is safe while under-normalizing silently splits one club in two.
"""
from __future__ import annotations

import re
import unicodedata

# Arabic diacritics (tashkeel) + tatweel carry no identity information.
_AR_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")

# Orthographic variants that are the SAME letter for matching purposes.
_AR_FOLD = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي", "ئ": "ي",
    "ؤ": "و",
    "ة": "ه",
})

# Words that carry no distinguishing information in club names. "al" is the
# Arabic definite article — present or absent almost at random across sources.
_STOP_EN = {
    "al", "el", "fc", "sc", "cf", "sfc", "club", "team", "the", "of",
    "football", "soccer", "sporting", "united", "city",
}
_STOP_AR = {"نادي", "ال", "الرياضي", "لكرة", "القدم", "فريق"}


def _strip_diacritics_latin(s: str) -> str:
    """é -> e, ü -> u. Latin transliterations of Arabic names vary wildly."""
    decomposed = unicodedata.normalize("NFD", s)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def is_arabic(s: str) -> bool:
    return any("؀" <= c <= "ۿ" for c in s or "")


def script_of(s: str) -> str:
    return "ar" if is_arabic(s) else "en"


def norm(name: str) -> str:
    """Normalize a team/player name to a comparison key ('' if unusable).

    Arabic: strip diacritics, fold letter variants, drop stopwords.
    Latin:  lowercase, strip accents, drop punctuation and stopwords.
    """
    if not name:
        return ""
    s = str(name).strip()
    if is_arabic(s):
        s = _AR_DIACRITICS.sub("", s)
        s = s.translate(_AR_FOLD)
        s = re.sub(r"[^؀-ۿ\s]", " ", s)
        tokens = [t for t in s.split() if t and t not in _STOP_AR]
        # the definite article fuses to the word: الهلال -> هلال
        tokens = [t[2:] if len(t) > 3 and t.startswith("ال") else t for t in tokens]
        return "".join(tokens)
    s = _strip_diacritics_latin(s).lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    tokens = [t for t in s.split() if t and t not in _STOP_EN]
    # the article also fuses in Latin transliterations: "AlHilal" -> "hilal"
    tokens = [t[2:] if len(t) > 4 and t.startswith(("al", "el")) else t for t in tokens]
    # transliteration of ي is arbitrary: Ahly/Ahli, Faysaly/Faisaly
    return "".join(tokens).replace("y", "i")


# Arabic letter -> Latin, for the cross-script skeleton below.
_TRANSLIT = {
    "ا": "a", "ب": "b", "ت": "t", "ث": "th", "ج": "j", "ح": "h", "خ": "kh",
    "د": "d", "ذ": "th", "ر": "r", "ز": "z", "س": "s", "ش": "sh", "ص": "s",
    "ض": "d", "ط": "t", "ظ": "z", "ع": "a", "غ": "gh", "ف": "f", "ق": "q",
    "ك": "k", "ل": "l", "م": "m", "ن": "n", "ه": "h", "و": "w", "ي": "i",
}
_VOWELS = str.maketrans("", "", "aeiou")


def xkey(name: str) -> str:
    """Cross-script key: a consonant skeleton comparable ACROSS Arabic and Latin.

    Arabic omits short vowels, so "الهلال" carries h-l-l while "Al Hilal" carries
    h-(i)-l-(a)-l. Transliterating the Arabic and dropping vowels from both makes
    them meet: both -> "hll". Short skeletons collide easily, so this is only
    ever used inside a country/type scope and never as the sole evidence.
    """
    n = norm(name)
    if not n:
        return ""
    if is_arabic(n):
        n = "".join(_TRANSLIT.get(c, "") for c in n)
    return n.translate(_VOWELS)


def similarity(a: str, b: str) -> float:
    """Normalized-token similarity in [0,1] — for fuzzy fallback only.

    Uses a character-bigram Dice coefficient: robust to the transliteration
    noise ("Faisaly"/"Faysaly") that trips exact matching, without pulling in a
    dependency.
    """
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if len(na) < 2 or len(nb) < 2:
        return 0.0
    ga = {na[i:i + 2] for i in range(len(na) - 1)}
    gb = {nb[i:i + 2] for i in range(len(nb) - 1)}
    return 2 * len(ga & gb) / (len(ga) + len(gb))
