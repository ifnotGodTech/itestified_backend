"""Word links: which span of a version's verse text translates which
original word (Phase 34 Slice 5).

A link is (verse, start, end) character offsets into the verse text exactly
as stored in the pack, plus the Strong's number and, when known, the
`position` of the original word in that verse (a key into the study pack's
`original_words`). Readers select text; the app finds the links under the
selection.

- BSB: placed from its translation tables, phrase by phrase in BSB order.
  This is the riskiest data step in the phase, so it reports coverage and
  the build fails below MIN_BSB_PLACED_RATIO.
- KJV: from the Strong's tags in its USFM (the offsets are found the same
  way: tagged words, in order), then matched to the original word in the
  same verse with the same Strong's number, for its form and parsing.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import NamedTuple

from apps.bible.exceptions import BibleSourceFormatError
from apps.bible.services.original_text import OriginalWord, VerseKey

# Share of translated BSB phrases that must land in the verse text.
MIN_BSB_PLACED_RATIO = 0.999
# Share of KJV tagged words that must find their original word.
MIN_KJV_MATCHED_RATIO = 0.93
# "Translated in this version as": the most frequent renderings kept.
MAX_RENDERINGS_PER_WORD = 12

_UNTRANSLATED = {"", "-", ". . ."}
_HTML = re.compile(r"<[^>]*>")
_SPACE_BEFORE = re.compile(r"\s+([,.;:!?’”)\]—])")
_SPACE_AFTER = re.compile(r"([“‘(\[—])\s+")
_EDGE_PUNCTUATION = re.compile(r"^[^\w’]+|[^\w’]+$")


class WordLink(NamedTuple):
    book_id: int
    chapter: int
    verse: int
    start: int
    end: int
    strongs: str
    position: int | None


class LinkReport(NamedTuple):
    links: list[WordLink]
    placed: int
    expected: int
    problems: list[str]  # a sample of what couldn't be placed, for the build log

    @property
    def ratio(self) -> float:
        return self.placed / self.expected if self.expected else 1.0


def link_bsb(
    texts: dict[VerseKey, str], originals: dict[VerseKey, list[OriginalWord]]
) -> LinkReport:
    """Places every translated BSB phrase into its verse's text, in order."""
    links: list[WordLink] = []
    placed = expected = 0
    problems: list[str] = []
    for key in sorted(originals):
        text = texts.get(key)
        if text is None:
            continue  # a verse the BSB leaves empty (Matthew 17:21 …)
        cursor = 0
        # "vvv" words are translated inside the next phrase ("μὴ" in "shall
        # not perish"), so they share its span.
        waiting: list[OriginalWord] = []
        for word in originals[key]:
            phrase = _phrase(word.english)
            if word.english.strip() == "vvv":
                waiting.append(word)
                continue
            if phrase is None:
                continue
            expected += 1
            span = _find(text, phrase, cursor)
            if span is None:
                if len(problems) < 20:
                    problems.append(f"{key}: {word.english!r} after {text[cursor:cursor + 40]!r}")
                waiting = []
                continue
            placed += 1
            start, end = span
            for linked in [*waiting, word]:
                links.append(WordLink(*key, start, end, linked.strongs, linked.position))
            waiting = []
            cursor = end
    return LinkReport(links=links, placed=placed, expected=expected, problems=problems)


def link_tagged(
    texts: dict[VerseKey, str],
    tags: dict[VerseKey, list[tuple[str, str]]],
    originals: dict[VerseKey, list[OriginalWord]],
) -> LinkReport:
    """KJV-style: each verse's tagged words (as they read in the text, with
    their Strong's numbers) in order. Each is found in the verse text, then
    matched to the first not-yet-used original word with the same number."""
    links: list[WordLink] = []
    placed = expected = 0
    problems: list[str] = []
    for key in sorted(tags):
        text = texts.get(key)
        if text is None:
            continue
        by_number: dict[str, list[int]] = defaultdict(list)
        for original in originals.get(key, []):
            if original.strongs:
                by_number[original.strongs].append(original.position)
        for positions in by_number.values():
            positions.sort()
        used: set[int] = set()
        cursor = 0
        for words, strongs in tags[key]:
            if not strongs:
                continue
            expected += 1
            span = _find(text, words, cursor)
            if span is None:
                if len(problems) < 20:
                    problems.append(f"{key}: {words!r} not found after {text[cursor:cursor + 40]!r}")
                continue
            candidates = by_number.get(strongs, [])
            position = next((p for p in candidates if p not in used), candidates[0] if candidates else None)
            if position is not None:
                used.add(position)
                placed += 1
            links.append(WordLink(*key, span[0], span[1], strongs, position))
            cursor = span[1]
    return LinkReport(links=links, placed=placed, expected=expected, problems=problems)


def renderings(texts: dict[VerseKey, str], links: list[WordLink]) -> list[tuple[str, str, int]]:
    """(strongs, rendering, count): how this version translates each word,
    most frequent first. Spans shared by several original words (a "vvv"
    group) count once per word, which is what readers expect: "not" is
    part of how μὴ is rendered."""
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for link in links:
        if not link.strongs:
            continue
        rendering = _EDGE_PUNCTUATION.sub("", texts[(link.book_id, link.chapter, link.verse)][link.start:link.end])
        if rendering:
            counts[link.strongs][rendering] += 1
    rows: list[tuple[str, str, int]] = []
    for strongs in sorted(counts):
        # "Love" at a sentence start and "love" are one rendering; show the
        # casing used most.
        merged: dict[str, Counter[str]] = defaultdict(Counter)
        for rendering, count in counts[strongs].items():
            merged[rendering.lower()][rendering] += count
        totals = sorted(
            ((sum(forms.values()), forms.most_common(1)[0][0]) for forms in merged.values()),
            key=lambda item: (-item[0], item[1]),
        )
        rows.extend((strongs, rendering, count) for count, rendering in totals[:MAX_RENDERINGS_PER_WORD])
    return rows


def require_coverage(report: LinkReport, *, minimum: float, label: str) -> None:
    if report.ratio < minimum:
        sample = "\n  ".join(report.problems)
        raise BibleSourceFormatError(
            f"{label}: only {report.placed}/{report.expected} words linked ({report.ratio:.3%}, "
            f"minimum {minimum:.1%}). First problems:\n  {sample}"
        )


def _phrase(english: str) -> str | None:
    """The words of a tables phrase as they appear in the verse text:
    supplied-word brackets, ellipses, markup and "vvv" markers removed, and
    spacing around punctuation as the text has it."""
    if english.strip() in _UNTRANSLATED:
        return None
    phrase = _HTML.sub(" ", english).replace(". . .", " ").replace("vvv", " ")
    phrase = re.sub(r"[\[\]{}]", "", phrase)
    phrase = re.sub(r"\s+", " ", phrase).strip()
    phrase = _SPACE_AFTER.sub(r"\1", _SPACE_BEFORE.sub(r"\1", phrase))
    # Punctuation alone ("( -": an untranslated word inside parentheses)
    # isn't a translation of anything.
    return phrase if re.search(r"\w", phrase) else None


def _find(text: str, phrase: str, cursor: int) -> tuple[int, int] | None:
    index = text.find(phrase, cursor)
    if index >= 0:
        return index, index + len(phrase)
    # Case or spacing differences ("Nevertheless , the" / "1 ,700"): match
    # word by word, allowing any whitespace between.
    words = [re.escape(part) for part in phrase.split()]
    if not words:
        return None
    pattern = re.compile(r"\s*".join(words), re.IGNORECASE)
    match = pattern.search(text, cursor)
    return (match.start(), match.end()) if match else None
