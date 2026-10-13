"""Building the shared word-study pack (Phase 34 Slice 5).

One pack serves every version that has word links: the links point at
(verse, position) here and carry a Strong's number. It holds:
- `original_words`: the Hebrew, Aramaic and Greek text word by word, with
  transliteration, parsing and Strong's number; indexed by Strong's number,
  it's also the concordance ("every verse where G25 occurs"),
- `lexicon`: one entry per Strong's number (STEPBible TBESH / TBESG),
- `morphology`: each parsing code once, in words,
- `strongs_counts`: how often each word occurs, for "Used N times".
"""

from __future__ import annotations

import sqlite3
import tempfile
from collections import Counter
from pathlib import Path

from apps.bible.exceptions import BibleSourceFormatError
from apps.bible.services.lexicon import LexiconEntry
from apps.bible.services.original_text import OriginalWord, VerseKey
from apps.bible.services.pack_builds import PACK_FORMAT_VERSION, compress_pack
from apps.bible.sources import StudyDefinition

# Every Strong's number in the original text must have a lexicon entry,
# give or take a handful of oddities; a broken lexicon fails the build.
MAX_MISSING_LEXICON_ENTRIES = 25


def write_study_pack(
    *,
    definition: StudyDefinition,
    originals: dict[VerseKey, list[OriginalWord]],
    lexicon: dict[str, LexiconEntry],
    source_sha256s: dict[str, str],
    out_dir: Path,
) -> tuple[Path, dict[str, int]]:
    """Writes `<code>.sqlite.gz` into `out_dir`; returns its path and a few
    counts for the build log."""
    out_dir.mkdir(parents=True, exist_ok=True)
    words = sorted(
        (word for verse_words in originals.values() for word in verse_words),
        key=lambda word: (word.book_id, word.chapter, word.verse, word.position),
    )
    counts = Counter(word.strongs for word in words if word.strongs)
    missing = sorted(number for number in counts if number not in lexicon)
    if len(missing) > MAX_MISSING_LEXICON_ENTRIES:
        raise BibleSourceFormatError(
            f"{len(missing)} Strong's numbers have no lexicon entry (e.g. {', '.join(missing[:8])})."
        )

    morphology: dict[str, tuple[int, str]] = {}
    for word in words:
        if word.parsing_code and word.parsing_code not in morphology:
            morphology[word.parsing_code] = (len(morphology) + 1, word.parsing)

    with tempfile.TemporaryDirectory() as workdir:
        database_path = Path(workdir) / "pack.sqlite"
        connection = sqlite3.connect(database_path)
        try:
            connection.executescript(
                """
                PRAGMA page_size = 4096;
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
                CREATE TABLE lexicon (
                    strongs TEXT PRIMARY KEY,
                    lemma TEXT NOT NULL,
                    translit TEXT NOT NULL,
                    part_of_speech TEXT NOT NULL,
                    gloss TEXT NOT NULL,
                    definition TEXT NOT NULL
                ) WITHOUT ROWID;
                CREATE TABLE morphology (
                    id INTEGER PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL
                );
                CREATE TABLE original_words (
                    book_id INTEGER NOT NULL,
                    chapter INTEGER NOT NULL,
                    verse INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    word TEXT NOT NULL,
                    translit TEXT NOT NULL,
                    strongs TEXT NOT NULL,
                    morphology_id INTEGER REFERENCES morphology(id),
                    PRIMARY KEY (book_id, chapter, verse, position)
                ) WITHOUT ROWID;
                CREATE TABLE strongs_counts (
                    strongs TEXT PRIMARY KEY,
                    total INTEGER NOT NULL
                ) WITHOUT ROWID;
                """
            )
            meta = {
                "format_version": str(PACK_FORMAT_VERSION),
                "kind": "study",
                "code": definition.code,
                "name": definition.name,
                "abbreviation": definition.abbreviation,
                "description": definition.description,
                "attribution": definition.attribution,
                "has_word_links": "0",
                "sort_order": str(definition.sort_order),
                "word_count": str(len(words)),
                **{f"source_sha256_{key}": value for key, value in sorted(source_sha256s.items())},
            }
            connection.executemany("INSERT INTO meta VALUES (?, ?)", sorted(meta.items()))
            used_entries = [lexicon[number] for number in sorted(counts) if number in lexicon]
            connection.executemany("INSERT INTO lexicon VALUES (?, ?, ?, ?, ?, ?)", used_entries)
            connection.executemany(
                "INSERT INTO morphology VALUES (?, ?, ?)",
                [(identifier, code, description) for code, (identifier, description) in morphology.items()],
            )
            connection.executemany(
                "INSERT INTO original_words VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        word.book_id,
                        word.chapter,
                        word.verse,
                        word.position,
                        word.word,
                        word.translit,
                        word.strongs,
                        morphology[word.parsing_code][0] if word.parsing_code else None,
                    )
                    for word in words
                ],
            )
            # The concordance: every occurrence of a word, in canonical order.
            connection.execute(
                "CREATE INDEX original_words_by_strongs ON original_words (strongs, book_id, chapter, verse)"
            )
            connection.executemany("INSERT INTO strongs_counts VALUES (?, ?)", sorted(counts.items()))
            connection.commit()
            connection.execute("VACUUM")
        finally:
            connection.close()
        pack_path = compress_pack(database_path, out_dir / f"{definition.code}.sqlite.gz")

    return pack_path, {
        "words": len(words),
        "lexicon_entries": len(used_entries),
        "parsings": len(morphology),
        "missing_lexicon_entries": len(missing),
    }
