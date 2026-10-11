"""The 66-book Protestant canon in canonical order, keyed by OSIS book id.

Pack `books.id` is the 1-based position in this tuple, so every version pack
agrees on book numbering and word links / concordance rows can reference a
verse as (book_id, chapter, verse) across packs.
"""

from __future__ import annotations

from typing import NamedTuple


class CanonBook(NamedTuple):
    osis: str
    name: str
    testament: str  # "OT" or "NT"


CANON: tuple[CanonBook, ...] = (
    CanonBook("Gen", "Genesis", "OT"),
    CanonBook("Exod", "Exodus", "OT"),
    CanonBook("Lev", "Leviticus", "OT"),
    CanonBook("Num", "Numbers", "OT"),
    CanonBook("Deut", "Deuteronomy", "OT"),
    CanonBook("Josh", "Joshua", "OT"),
    CanonBook("Judg", "Judges", "OT"),
    CanonBook("Ruth", "Ruth", "OT"),
    CanonBook("1Sam", "1 Samuel", "OT"),
    CanonBook("2Sam", "2 Samuel", "OT"),
    CanonBook("1Kgs", "1 Kings", "OT"),
    CanonBook("2Kgs", "2 Kings", "OT"),
    CanonBook("1Chr", "1 Chronicles", "OT"),
    CanonBook("2Chr", "2 Chronicles", "OT"),
    CanonBook("Ezra", "Ezra", "OT"),
    CanonBook("Neh", "Nehemiah", "OT"),
    CanonBook("Esth", "Esther", "OT"),
    CanonBook("Job", "Job", "OT"),
    CanonBook("Ps", "Psalms", "OT"),
    CanonBook("Prov", "Proverbs", "OT"),
    CanonBook("Eccl", "Ecclesiastes", "OT"),
    CanonBook("Song", "Song of Solomon", "OT"),
    CanonBook("Isa", "Isaiah", "OT"),
    CanonBook("Jer", "Jeremiah", "OT"),
    CanonBook("Lam", "Lamentations", "OT"),
    CanonBook("Ezek", "Ezekiel", "OT"),
    CanonBook("Dan", "Daniel", "OT"),
    CanonBook("Hos", "Hosea", "OT"),
    CanonBook("Joel", "Joel", "OT"),
    CanonBook("Amos", "Amos", "OT"),
    CanonBook("Obad", "Obadiah", "OT"),
    CanonBook("Jonah", "Jonah", "OT"),
    CanonBook("Mic", "Micah", "OT"),
    CanonBook("Nah", "Nahum", "OT"),
    CanonBook("Hab", "Habakkuk", "OT"),
    CanonBook("Zeph", "Zephaniah", "OT"),
    CanonBook("Hag", "Haggai", "OT"),
    CanonBook("Zech", "Zechariah", "OT"),
    CanonBook("Mal", "Malachi", "OT"),
    CanonBook("Matt", "Matthew", "NT"),
    CanonBook("Mark", "Mark", "NT"),
    CanonBook("Luke", "Luke", "NT"),
    CanonBook("John", "John", "NT"),
    CanonBook("Acts", "Acts", "NT"),
    CanonBook("Rom", "Romans", "NT"),
    CanonBook("1Cor", "1 Corinthians", "NT"),
    CanonBook("2Cor", "2 Corinthians", "NT"),
    CanonBook("Gal", "Galatians", "NT"),
    CanonBook("Eph", "Ephesians", "NT"),
    CanonBook("Phil", "Philippians", "NT"),
    CanonBook("Col", "Colossians", "NT"),
    CanonBook("1Thess", "1 Thessalonians", "NT"),
    CanonBook("2Thess", "2 Thessalonians", "NT"),
    CanonBook("1Tim", "1 Timothy", "NT"),
    CanonBook("2Tim", "2 Timothy", "NT"),
    CanonBook("Titus", "Titus", "NT"),
    CanonBook("Phlm", "Philemon", "NT"),
    CanonBook("Heb", "Hebrews", "NT"),
    CanonBook("Jas", "James", "NT"),
    CanonBook("1Pet", "1 Peter", "NT"),
    CanonBook("2Pet", "2 Peter", "NT"),
    CanonBook("1John", "1 John", "NT"),
    CanonBook("2John", "2 John", "NT"),
    CanonBook("3John", "3 John", "NT"),
    CanonBook("Jude", "Jude", "NT"),
    CanonBook("Rev", "Revelation", "NT"),
)

# Source datasets name a few books differently from our display names.
_SOURCE_NAME_ALIASES = {"Psalm": "Psalms"}

_BOOK_ID_BY_NAME = {book.name: index for index, book in enumerate(CANON, start=1)}


def book_id_for_source_name(name: str) -> int | None:
    """1-based canonical book id for a book name as a source file spells it."""
    return _BOOK_ID_BY_NAME.get(_SOURCE_NAME_ALIASES.get(name, name))
