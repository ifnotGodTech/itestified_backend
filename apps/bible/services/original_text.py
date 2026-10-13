"""Reading the Berean Bible translation tables (Phase 34 Slice 5).

`bsb_tables.tsv` has one row per Hebrew, Aramaic or Greek word, listed in
BSB English order, each with:
- the original word (WLC for the OT; the Berean Greek base text for the NT),
  its transliteration and its parsing, as a code and in words,
- its Strong's number,
- the BSB English that translates it, plus the punctuation that follows.

That gives both halves of word study: the version-independent original text
(-> the study pack) and where each word sits in the BSB's English (-> the
BSB's word links, see word_links.py).
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

from apps.bible.canon import book_id_for_source_name
from apps.bible.exceptions import BibleSourceFormatError

# Columns of bsb_tables.tsv (0-based).
_HEB_SORT, _GREEK_SORT, _BSB_SORT = 0, 1, 2
_LANGUAGE, _WORD, _TRANSLIT, _PARSING_CODE, _PARSING_WORDS = 4, 5, 7, 8, 9
_STRONGS_HEBREW, _STRONGS_GREEK, _VERSE_ID, _ENGLISH = 10, 11, 12, 18
_MIN_COLUMNS = 19

# Hebrew cantillation marks and verse/section punctuation: reading aids for
# chanting, noise in a lookup. Vowel points and the maqaf hyphen stay.
_HEBREW_ACCENTS = re.compile("[֑-ֽ֯׀׃׆]")

# Hebrew verb stems keep their capital in parsing text; every other
# descriptive segment after the first is lower-cased ("Verb · aorist ...").
_HEBREW_STEMS = {
    "Qal", "Niphal", "Piel", "Pual", "Hiphil", "Hophal", "Hithpael", "Hithpalel", "Hithpolel",
    "Polel", "Pilel", "Poel", "Pulal", "Polal", "Pilpel", "Hishtaphel", "Nithpael",
    "Peal", "Peil", "Pael", "Haphel", "Aphel", "Ithpeel", "Ithpaal", "Hithpeel", "Shaphel",
}


class OriginalWord(NamedTuple):
    """One word of the Hebrew/Aramaic/Greek text, at `position` (0-based,
    in original-language order) within its verse."""

    book_id: int
    chapter: int
    verse: int
    position: int
    word: str
    translit: str
    strongs: str  # "H0430" / "G0025"; "" when the tables give none
    parsing_code: str
    parsing: str  # in words, ready to show
    english: str  # the BSB phrase as the tables give it ("" / "-" = untranslated)
    bsb_order: float  # where the phrase falls in the BSB's English order


VerseKey = tuple[int, int, int]


def parse_bsb_tables(path: Path) -> dict[VerseKey, list[OriginalWord]]:
    """Every verse's original words, each verse's list in BSB English order.
    Raises BibleSourceFormatError if the file isn't the tables layout."""
    rows_by_verse: dict[VerseKey, list[list[str]]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        header = next(reader, None)
        if not header or len(header) < _MIN_COLUMNS or "BSB" not in header[_ENGLISH]:
            raise BibleSourceFormatError(f"{path} doesn't look like the BSB translation tables.")
        current: VerseKey | None = None
        for row in reader:
            if len(row) < _MIN_COLUMNS:
                continue
            if row[_VERSE_ID]:
                current = _verse_key(row[_VERSE_ID])
            if current is None or not row[_WORD].strip():
                continue  # blank padding rows between verses
            rows_by_verse[current].append(row)

    verses: dict[VerseKey, list[OriginalWord]] = {}
    for key, rows in rows_by_verse.items():
        # Position within the verse follows the original language's order.
        greek = rows[0][_LANGUAGE] == "Greek"
        sort_column = _GREEK_SORT if greek else _HEB_SORT
        original_order = sorted(rows, key=lambda row: float(row[sort_column]))
        position_of = {id(row): index for index, row in enumerate(original_order)}
        verses[key] = [
            OriginalWord(
                *key,
                position=position_of[id(row)],
                word=_HEBREW_ACCENTS.sub("", row[_WORD].strip()),
                translit=row[_TRANSLIT].strip(),
                strongs=strongs_key(row[_STRONGS_GREEK] if greek else row[_STRONGS_HEBREW], greek=greek),
                parsing_code=row[_PARSING_CODE].strip(),
                parsing=readable_parsing(row[_PARSING_WORDS]),
                english=row[_ENGLISH].strip(),
                bsb_order=float(row[_BSB_SORT]),
            )
            for row in sorted(rows, key=lambda row: float(row[_BSB_SORT]))
        ]
    return verses


def strongs_key(number: str, *, greek: bool) -> str:
    """"430" -> "H0430", "25" -> "G0025": the lexicon's key format."""
    digits = number.strip()
    if not digits.isdigit():
        return ""
    return ("G" if greek else "H") + digits.zfill(4)


def readable_parsing(words: str) -> str:
    """"Verb - Aorist Indicative Active - 3rd Person Singular" ->
    "Verb · aorist indicative active · 3rd person singular"; Hebrew
    prefixes joined with " | " become " + "."""
    parts = []
    for part in words.split("|"):
        segments = [segment.strip() for segment in part.split(" - ") if segment.strip()]
        if not segments:
            continue
        shown = [segments[0]] + [
            segment if segment in _HEBREW_STEMS else segment[:1].lower() + segment[1:].lower()
            for segment in segments[1:]
        ]
        parts.append(" · ".join(shown))
    return " + ".join(parts)


def _verse_key(verse_id: str) -> VerseKey:
    match = re.fullmatch(r"(.+?) (\d+):(\d+)", verse_id.strip())
    if match is None:
        raise BibleSourceFormatError(f"Unreadable verse reference {verse_id!r} in the BSB tables.")
    book_id = book_id_for_source_name(match[1])
    if book_id is None:
        raise BibleSourceFormatError(f"Unknown book name {match[1]!r} in the BSB tables.")
    return (book_id, int(match[2]), int(match[3]))
