"""What a staff member may have meant by a search word: the same keys in the other keyboard layout,
Bulgarian written in Latin letters, or a close word from the posts (a typo).

Used by search.views.matching_guides, so the search page, „Често търсено“ and the statistics agree.
"""

import re
from difflib import SequenceMatcher

# The letter keys of a Latin keyboard and what they type in the Cyrillic layouts of Windows.
LATIN_KEYS = "qwertyuiop[]asdfghjkl;'zxcvbnm,./`\\"
PHONETIC = "явертъуиопшщасдфгхйкл;'зьцжбнм,./чю"  # „Bulgarian (Phonetic Traditional)“
BDS = ",уеишщксдзц;ьяаожгтнвмчюйъэфхпрлб`\\"  # „Bulgarian“ (БДС)
RUSSIAN = "йцукенгшщзхъфывапролджэячсмитьбю.ё\\"  # ЙЦУКЕН, set up on some PCs

LAYOUTS = [str.maketrans(LATIN_KEYS, layout) for layout in (PHONETIC, BDS, RUSSIAN)]  # meant Bulgarian, typed in Latin
LAYOUTS += [str.maketrans(layout, LATIN_KEYS) for layout in (PHONETIC, BDS, RUSSIAN)]  # meant "outlook", typed in Bulgarian

# Bulgarian in Latin letters as people type it: "zaplata", "smyana", "shtrihkod".
TRANSLIT = {
    "sht": "щ", "sh": "ш", "ch": "ч", "zh": "ж", "ts": "ц", "yu": "ю", "ya": "я", "ju": "ю", "ja": "я",
    "a": "а", "b": "б", "c": "ц", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х", "i": "и", "j": "й",
    "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "q": "я", "r": "р", "s": "с", "t": "т",
    "u": "у", "v": "в", "w": "в", "x": "кс", "y": "ъ", "z": "з",
}
TRANSLIT_RE = re.compile("|".join(TRANSLIT))  # longest first: the dict starts with "sht", "sh", …

# Typos are only looked for in words this long (shorter ones would match too much) ...
FUZZY_MIN_LENGTH = 4
# ... and only words at least this similar count (1 = the same word).
FUZZY_CUTOFF = 0.8
WORD = re.compile(r"\w{%d,}" % FUZZY_MIN_LENGTH)


def spellings(word):
    """The word itself and how it reads in the other layouts / as Bulgarian in Latin letters."""
    found = [word] + [word.translate(table) for table in LAYOUTS]
    if word.isascii():
        found.append(TRANSLIT_RE.sub(lambda m: TRANSLIT[m.group()], word))
    return list(dict.fromkeys(found))


def vocabulary(texts):
    """The words of the posts that a typo can be matched against."""
    words = set()
    for text in texts:
        words.update(WORD.findall(text))
    return words


def close_words(word, words, limit=5):
    """Words that look like a typo of `word`. A longer word counts by its start ("принетр" finds
    "принтерът"), because Bulgarian words change their endings."""
    if len(word) < FUZZY_MIN_LENGTH:
        return []
    scored = {}
    for candidate in words:
        if candidate[0] != word[0]:  # a typo in the first letter is rare; this keeps it fast
            continue
        score = max(_similar(word, candidate), _similar(word, candidate[: len(word)]))
        if score >= FUZZY_CUTOFF:
            scored[candidate] = score
    return sorted(scored, key=lambda w: (-scored[w], w))[:limit]


def _similar(a, b):
    return SequenceMatcher(None, a, b).ratio()
