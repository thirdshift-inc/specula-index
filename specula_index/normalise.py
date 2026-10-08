import unicodedata

_STROKE_LETTERS = str.maketrans({"ł": "l", "đ": "d", "ø": "o", "ħ": "h", "ı": "i"})


def _is_alphanumeric(ch):
    return unicodedata.category(ch)[0] in "LMN"


def _words(text):
    words, current = [], []
    for ch in text:
        if _is_alphanumeric(ch):
            current.append(ch)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return words


def match_key(title):
    lowered = "".join(ch.lower() for ch in title)
    return "-".join(_words(lowered.replace("&", "and")))


def fold(key):
    folded = unicodedata.normalize("NFD", key.casefold())
    folded = "".join(ch for ch in folded if unicodedata.category(ch) != "Mn")
    folded = unicodedata.normalize("NFC", folded.translate(_STROKE_LETTERS))
    return "-".join(part for part in folded.split("-") if part)


def index_key(title):
    return fold(match_key(title))
