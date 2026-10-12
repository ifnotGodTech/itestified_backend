"""Building downloadable Bible packs from pinned source datasets (Phase 34).

A pack is a gzip-compressed SQLite file. Builds are reproducible: the same
source input always yields byte-identical output, so a rebuild that changed
nothing produces the same sha256 and publishing it is a no-op.
"""

from __future__ import annotations

import gzip
import hashlib
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import NamedTuple

import requests

from apps.bible.canon import CANON, book_id_for_source_name
from apps.bible.exceptions import BibleSourceChecksumError, BibleSourceFormatError
from apps.bible.sources import SourceDataset, VersionDefinition

PACK_FORMAT_VERSION = 1
SOURCE_DOWNLOAD_TIMEOUT_SECONDS = 60
# Modern translations deliberately leave out a few verses absent from the
# earliest manuscripts (the BSB lists 16, e.g. Matthew 17:21, John 5:4) as
# empty lines. Far more than that means a broken source, not a translation
# choice.
MAX_OMITTED_VERSES = 40
_VERSE_LINE = re.compile(r"^(?P<book>.+?) (?P<chapter>\d+):(?P<verse>\d+)\t(?P<text>.*)$")


class Verse(NamedTuple):
    book_id: int
    chapter: int
    verse: int
    text: str


class Heading(NamedTuple):
    """Text printed above a verse that isn't part of it: a psalm title
    ("A Psalm of David.") or a section heading (Psalm 119's "א ALEPH.")."""

    book_id: int
    chapter: int
    before_verse: int
    text: str


class ParsedText(NamedTuple):
    verses: list[Verse]
    # "Book C:V" references the translation deliberately leaves empty.
    omitted: list[str]
    headings: list[Heading] = []


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_source(dataset: SourceDataset, cache_dir: Path) -> Path:
    """Returns a local copy of `dataset` whose sha256 matches its pin,
    reusing a cached copy when it still matches. Raises
    BibleSourceChecksumError when upstream no longer serves the pinned file."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{dataset.key}{Path(dataset.url).suffix}"
    if target.exists() and sha256_of_file(target) == dataset.sha256:
        return target

    with tempfile.NamedTemporaryFile(dir=cache_dir, delete=False) as handle:
        partial = Path(handle.name)
        with requests.get(dataset.url, stream=True, timeout=SOURCE_DOWNLOAD_TIMEOUT_SECONDS) as response:
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                handle.write(chunk)

    actual = sha256_of_file(partial)
    if actual != dataset.sha256:
        partial.unlink(missing_ok=True)
        raise BibleSourceChecksumError(
            f"{dataset.key}: {dataset.url} has sha256 {actual}, pinned {dataset.sha256}. "
            "Review the upstream change before updating the pin in apps/bible/sources.py."
        )
    partial.replace(target)
    return target


def parse_verse_text(path: Path) -> ParsedText:
    """Parses a "Book C:V<TAB>text" verse-per-line file (the BSB's plain-text
    format) into canonical-order verses. A verse listed with no text is a
    deliberate omission: it isn't stored (readers see the numbering skip, as
    in print) but is reported. Refuses anything incomplete: a missing book,
    an unknown book name, a duplicate verse, or more omissions than any
    translation makes."""
    verses: list[Verse] = []
    omitted: list[str] = []
    seen: set[tuple[int, int, int]] = set()
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        match = _VERSE_LINE.match(raw_line.rstrip("\r"))
        if match is None:
            continue  # title, licence and column-header lines
        book_id = book_id_for_source_name(match["book"])
        if book_id is None:
            raise BibleSourceFormatError(f"Unknown book name {match['book']!r}.")
        key = (book_id, int(match["chapter"]), int(match["verse"]))
        text = match["text"].strip()
        if key in seen:
            raise BibleSourceFormatError(f"Duplicate verse {match['book']} {key[1]}:{key[2]}.")
        seen.add(key)
        if text:
            verses.append(Verse(*key, text))
        else:
            omitted.append(f"{CANON[book_id - 1].name} {key[1]}:{key[2]}")
    return finish_parsed_text(verses, omitted)


def finish_parsed_text(
    verses: list[Verse], omitted: list[str], headings: list[Heading] | None = None
) -> ParsedText:
    """Shared completeness rules for every source format: all 66 books
    present, and no more omitted verses than a translation plausibly makes.
    Returns the verses in canonical order."""
    present_books = {verse.book_id for verse in verses}
    missing = [book.name for index, book in enumerate(CANON, start=1) if index not in present_books]
    if missing:
        raise BibleSourceFormatError(f"Missing books: {', '.join(missing)}.")
    if len(omitted) > MAX_OMITTED_VERSES:
        raise BibleSourceFormatError(
            f"{len(omitted)} empty verses (more than {MAX_OMITTED_VERSES}); the source looks broken."
        )
    verses.sort(key=lambda verse: (verse.book_id, verse.chapter, verse.verse))
    ordered_headings = sorted(headings or [], key=lambda h: (h.book_id, h.chapter, h.before_verse))
    return ParsedText(verses=verses, omitted=omitted, headings=ordered_headings)


def parse_source(definition: VersionDefinition, path: Path) -> ParsedText:
    """Parses a downloaded source in the layout its version definition names."""
    if definition.text_format == "usfm_zip":
        from apps.bible.services.usfm_text import parse_usfm_zip

        return parse_usfm_zip(path)
    if definition.text_format == "verse_lines":
        return parse_verse_text(path)
    raise BibleSourceFormatError(f"Unknown text format {definition.text_format!r}.")


def write_version_pack(*, definition: VersionDefinition, parsed: ParsedText, source_sha256: str, out_dir: Path) -> Path:
    """Writes `<code>.sqlite.gz` into `out_dir` and returns its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    verses = parsed.verses
    chapter_counts: dict[int, int] = {}
    for verse in verses:
        chapter_counts[verse.book_id] = max(chapter_counts.get(verse.book_id, 0), verse.chapter)

    with tempfile.TemporaryDirectory() as workdir:
        database_path = Path(workdir) / "pack.sqlite"
        connection = sqlite3.connect(database_path)
        try:
            connection.executescript(
                """
                PRAGMA page_size = 4096;
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
                CREATE TABLE books (
                    id INTEGER PRIMARY KEY,
                    osis TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    testament TEXT NOT NULL,
                    chapter_count INTEGER NOT NULL
                );
                CREATE TABLE verses (
                    book_id INTEGER NOT NULL REFERENCES books(id),
                    chapter INTEGER NOT NULL,
                    verse INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    PRIMARY KEY (book_id, chapter, verse)
                ) WITHOUT ROWID;
                """
            )
            meta = {
                "format_version": str(PACK_FORMAT_VERSION),
                "kind": "version",
                "code": definition.code,
                "name": definition.name,
                "abbreviation": definition.abbreviation,
                "description": definition.description,
                "attribution": definition.attribution,
                "source_sha256": source_sha256,
                "verse_count": str(len(verses)),
                "has_word_links": "0",
                "omitted_verses": "; ".join(parsed.omitted),
                "sort_order": str(definition.sort_order),
            }
            connection.executemany("INSERT INTO meta VALUES (?, ?)", sorted(meta.items()))
            connection.executemany(
                "INSERT INTO books VALUES (?, ?, ?, ?, ?)",
                [
                    (index, book.osis, book.name, book.testament, chapter_counts[index])
                    for index, book in enumerate(CANON, start=1)
                ],
            )
            connection.executemany("INSERT INTO verses VALUES (?, ?, ?, ?)", verses)
            # Only versions with headings get the table, so a version without
            # any (the BSB) still rebuilds byte-for-byte as before; readers
            # treat a missing table as "no headings".
            if parsed.headings:
                connection.execute(
                    """
                    CREATE TABLE headings (
                        book_id INTEGER NOT NULL REFERENCES books(id),
                        chapter INTEGER NOT NULL,
                        before_verse INTEGER NOT NULL,
                        position INTEGER NOT NULL,
                        text TEXT NOT NULL,
                        PRIMARY KEY (book_id, chapter, before_verse, position)
                    ) WITHOUT ROWID
                    """
                )
            # Several headings can precede one verse; `position` keeps their order.
            positions: dict[tuple[int, int, int], int] = {}
            heading_rows = []
            for heading in parsed.headings:
                key = (heading.book_id, heading.chapter, heading.before_verse)
                positions[key] = positions.get(key, -1) + 1
                heading_rows.append((*key, positions[key], heading.text))
            if heading_rows:
                connection.executemany("INSERT INTO headings VALUES (?, ?, ?, ?, ?)", heading_rows)
            connection.commit()
            connection.execute("VACUUM")
        finally:
            connection.close()

        pack_path = out_dir / f"{definition.code}.sqlite.gz"
        with database_path.open("rb") as source, pack_path.open("wb") as target:
            # filename="" and mtime=0 keep the gzip header free of anything
            # that would change between otherwise identical builds.
            with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0, compresslevel=9) as compressed:
                shutil.copyfileobj(source, compressed)
    return pack_path
