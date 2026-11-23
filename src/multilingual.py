"""Script-aware helpers so captions and timing work in any language, not only Bangla or English.

The script is read from the text itself, so nothing depends on how the language was named.
"""
import unicodedata

# (first, last code point, Windows caption font). First match wins; Latin, Cyrillic, Greek and
# Vietnamese fall through to Segoe UI.
_SCRIPT_FONTS = (
    (0x0980, 0x09FF, "Nirmala UI"),        # Bengali
    (0x0900, 0x0DFF, "Nirmala UI"),        # Devanagari, Gurmukhi, Gujarati, Odia, Tamil, Telugu, Kannada, Malayalam, Sinhala
    (0x0600, 0x08FF, "Segoe UI"),          # Arabic, Urdu, Persian, Pashto
    (0xFB50, 0xFEFF, "Segoe UI"),          # Arabic presentation forms
    (0x0590, 0x05FF, "Segoe UI"),          # Hebrew
    (0x0E00, 0x0E7F, "Leelawadee UI"),     # Thai
    (0x0E80, 0x0EFF, "Leelawadee UI"),     # Lao
    (0x1000, 0x109F, "Myanmar Text"),      # Myanmar
    (0x1780, 0x17FF, "Leelawadee UI"),     # Khmer
    (0x1200, 0x139F, "Ebrima"),            # Ethiopic
    (0x3040, 0x30FF, "Yu Gothic UI"),      # Japanese kana
    (0xAC00, 0xD7AF, "Malgun Gothic"),     # Korean Hangul
    (0x1100, 0x11FF, "Malgun Gothic"),
    (0x4E00, 0x9FFF, "Microsoft YaHei"),   # Han (Chinese unless kana is present)
    (0x3400, 0x4DBF, "Microsoft YaHei"),
)


def caption_font(text):
    """The Windows font that draws this text's main script; Japanese wins over Chinese when kana appear."""
    counts = {}
    for ch in text:
        for lo, hi, font in _SCRIPT_FONTS:
            if lo <= ord(ch) <= hi:
                counts[font] = counts.get(font, 0) + 1
                break
    if not counts:
        return "Segoe UI"
    if "Yu Gothic UI" in counts:
        return "Yu Gothic UI"
    return max(counts, key=counts.get)


def _wide(ch):
    return unicodedata.east_asian_width(ch) in ("W", "F")


def wrap_unspaced(text, limit=18):
    """Chinese and Japanese have no spaces for the subtitle renderer to wrap at: break long lines evenly."""
    lines = []
    for line in text.splitlines() or [""]:
        wide = sum(_wide(ch) for ch in line)
        if wide <= limit or " " in line.strip():
            lines.append(line)
            continue
        parts = -(-len(line) // limit)
        size = -(-len(line) // parts)
        lines.extend(line[i:i + size] for i in range(0, len(line), size))
    return "\n".join(lines)


def speech_units(text):
    """Letter-equivalents for timing estimates in any script.

    Letters count once, including spacing vowel signs in Indic scripts. A Chinese character is a
    whole syllable (about three letters of speech); a kana or Hangul syllable about two.
    """
    units = 0.0
    for ch in text:
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
            units += 3
        elif 0x3040 <= o <= 0x30FF or 0xAC00 <= o <= 0xD7AF:
            units += 2
        elif ch.isalpha() or unicodedata.category(ch) == "Mc":
            units += 1
    return units
