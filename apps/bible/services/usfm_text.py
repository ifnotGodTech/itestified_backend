"""Reading a zip of USFM books (eBible.org's layout) into verse text (Phase 34).

USFM interleaves markup with the text. For a version pack we keep what a
reader sees in a printed Bible:
- the words, without `\\w word|strong="G25"\\w*` tagging (the Strong's numbers
  become word links in Slice 5, built from the same source so offsets agree),
- supplied words (`\\add`, the KJV's italics), "LORD" (`\\nd`) and words of
  Jesus (`\\wj`) as plain text,
- psalm titles (`\\d`) and section headings (`\\s1`, e.g. Psalm 119's
  "א ALEPH.") as headings above the next verse, not inside it; a heading
  with no verse after it (the KJV's epistle subscriptions, "Written to the
  Romans from Corinthus…") is kept after the book's last verse
  (before_verse = last verse + 1),
and drop footnotes (`\\f … \\f*`), cross references and book furniture
(`\\id`, `\\h`, `\\toc`, `\\mt`).
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from apps.bible.canon import CANON, book_id_for_usfm_code
from apps.bible.exceptions import BibleSourceFormatError
from apps.bible.services.pack_builds import Heading, ParsedText, Verse, finish_parsed_text

_NOTE = re.compile(r"\\(f|fe|x)\s.*?\\\1\*", re.DOTALL)
_WORD = re.compile(r"\\\+?w\s+([^|\\]*?)(?:\|[^\\]*)?\\\+?w\*")
_TAGGED_WORD = re.compile(r"\\\+?w\s+([^|\\]*?)\|([^\\]*)\\\+?w\*")
_STRONG = re.compile(r'strong="([HG])0*(\d+)[a-zA-Z]?"')
_MARKER = re.compile(r"\\\+?[a-z]+[0-9]*\*?")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([,.;:!?])")
_LINE = re.compile(r"^\\([a-z]+[0-9]*)\s*(.*)$")

_HEADING_MARKERS = {"d", "s", "s1", "s2", "s3", "ms", "ms1", "mr", "sr"}
_SKIPPED_MARKERS = {"id", "ide", "h", "toc1", "toc2", "toc3", "mt", "mt1", "mt2", "mt3", "rem", "usfm", "sts"}


def clean_usfm_text(raw: str) -> str:
    """Plain reading text from a fragment of USFM."""
    text = _NOTE.sub("", raw)
    text = _WORD.sub(r"\1", text)
    text = _MARKER.sub("", text).replace("¶", "")
    text = re.sub(r"\s+", " ", text).strip()
    return _SPACE_BEFORE_PUNCTUATION.sub(r"\1", text)


def strong_tags(raw: str) -> list[tuple[str, str]]:
    """The Strong's-tagged words of a USFM fragment, in order, as
    (the words as they read in the clean text, "G0025")."""
    tags = []
    for match in _TAGGED_WORD.finditer(_NOTE.sub("", raw)):
        number = _STRONG.search(match[2])
        words = re.sub(r"\s+", " ", match[1]).strip()
        if number and words:
            tags.append((words, number[1] + number[2].zfill(4)))
    return tags


def parse_usfm_zip(path: Path) -> ParsedText:
    verses: list[Verse] = []
    omitted: list[str] = []
    headings: list[Heading] = []
    word_tags: dict[tuple[int, int, int], list[tuple[str, str]]] = {}
    seen: set[tuple[int, int, int]] = set()
    try:
        with zipfile.ZipFile(path) as archive:
            names = sorted(name for name in archive.namelist() if name.lower().endswith((".usfm", ".sfm")))
            for name in names:
                _parse_book(
                    archive.read(name).decode("utf-8-sig"), name, verses, omitted, headings, seen, word_tags
                )
    except zipfile.BadZipFile as exc:
        raise BibleSourceFormatError(f"{path} is not a valid zip of USFM books.") from exc
    return finish_parsed_text(verses, omitted, headings, word_tags)


def _parse_book(
    source: str,
    name: str,
    verses: list[Verse],
    omitted: list[str],
    headings: list[Heading],
    seen: set[tuple[int, int, int]],
    word_tags: dict[tuple[int, int, int], list[tuple[str, str]]],
) -> None:
    book_id: int | None = None
    chapter = 0
    last_verse: tuple[int, int, int] | None = None
    current: tuple[int, int, int] | None = None
    buffer: list[str] = []
    pending_headings: list[str] = []

    def flush() -> None:
        nonlocal current, buffer
        if current is not None:
            raw = " ".join(buffer)
            text = clean_usfm_text(raw)
            if text:
                verses.append(Verse(*current, text))
                tags = strong_tags(raw)
                if tags:
                    word_tags[current] = tags
            else:
                omitted.append(f"{CANON[current[0] - 1].name} {current[1]}:{current[2]}")
        current, buffer = None, []

    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _LINE.match(line)
        marker, rest = (match[1], match[2]) if match else ("", line)

        if marker == "id":
            code = rest.split()[0] if rest.split() else ""
            book_id = book_id_for_usfm_code(code)
            if book_id is None:
                raise BibleSourceFormatError(f"{name}: unknown USFM book code {code!r}.")
        elif marker == "c":
            flush()
            chapter = int(rest.split()[0])
        elif marker == "v":
            flush()
            if book_id is None or chapter == 0:
                raise BibleSourceFormatError(f"{name}: a verse appears before its book or chapter.")
            number, _, text = rest.partition(" ")
            if not number.isdigit():
                raise BibleSourceFormatError(f"{name}: unsupported verse number {number!r} in chapter {chapter}.")
            current = (book_id, chapter, int(number))
            last_verse = current
            if current in seen:
                raise BibleSourceFormatError(f"Duplicate verse {CANON[book_id - 1].name} {chapter}:{number}.")
            seen.add(current)
            buffer = [text]
            for heading in pending_headings:
                headings.append(Heading(book_id, chapter, int(number), heading))
            pending_headings = []
        elif marker in _HEADING_MARKERS:
            flush()
            heading = clean_usfm_text(rest)
            if heading:
                pending_headings.append(heading)
        elif marker in _SKIPPED_MARKERS:
            continue
        elif current is not None:
            # Paragraph / poetry markers (\p, \q1, \b, …) and continuation
            # lines carry on the verse that's open.
            buffer.append(rest if marker else line)
    flush()
    if pending_headings and last_verse is not None:
        book, last_chapter, verse = last_verse
        for heading in pending_headings:
            headings.append(Heading(book, last_chapter, verse + 1, heading))
