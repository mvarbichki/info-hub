"""Readable Latin page addresses from Bulgarian titles."""

from django.utils.text import slugify

# Official Bulgarian transliteration, so addresses read "/it/printerat-ne-pechata/".
TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z", "и": "i", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sht", "ъ": "a", "ь": "y", "ю": "yu", "я": "ya",
})


def unique_slug(parent, title):
    """A free address under `parent`: "printerat-ne-pechata", else "printerat-ne-pechata-2" …"""
    base = slugify(title.lower().translate(TRANSLIT))[:80].strip("-") or "publikatsiya"
    siblings = parent.get_children()
    slug, n = base, 2
    while siblings.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug
