CYRILLIC = "Cyrillic"
LATIN = "Latin"

_CYRILLIC_RANGES = ((0x0400, 0x04FF), (0x0500, 0x052F))
_LATIN_RANGES = ((0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F))


def _count(text: str, ranges: tuple[tuple[int, int], ...]) -> int:
    return sum(1 for ch in text
               for low, high in ranges if low <= ord(ch) <= high)


def dominant_script(text: str) -> str:
    """CYRILLIC or LATIN, whichever has more letters. Ties and neither go to Latin."""
    return CYRILLIC if _count(text, _CYRILLIC_RANGES) > _count(text, _LATIN_RANGES) \
        else LATIN
