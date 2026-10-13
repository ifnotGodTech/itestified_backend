"""Reading STEPBible's brief lexicons, TBESH (Hebrew) and TBESG (Greek)
(Phase 34 Slice 5).

Each data line: extended Strong's, disambiguated Strong's ("H0430G = a Name
of"), unified Strong's, the word, transliteration, a morphology code
("H:N-M"), a short gloss ("God") and a definition with light HTML markup.

Version word links carry plain Strong's numbers ("H0430"), so one entry is
picked per number: the entry for the plain number, else its "a" entry
(H1121 -> H1121A "son"), preferring the main entry over STEPBible's finer
sub-meanings. The CC BY 4.0 licence asks for a note of changes; the study
pack's attribution states them (markup removed, keyed by Strong's number).
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import NamedTuple

_KEY = re.compile(r"^([HG]\d{4})([A-Za-z]?)$")
_MAIN_ENTRY = re.compile(r"^[HG]\d{4}[A-Za-z]? =\s*$")
_REF = re.compile(r"<ref='[^']*'>(.*?)</ref>", re.DOTALL)
_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t]+")

_PARTS_OF_SPEECH = {
    "N": "noun",
    "V": "verb",
    "A": "adjective",
    "ADV": "adverb",
    "Adv": "adverb",
    "PREP": "preposition",
    "Prep": "preposition",
    "CONJ": "conjunction",
    "Conj": "conjunction",
    "COND": "conditional",
    "Cond": "conditional",
    "PRT": "particle",
    "Part": "particle",
    "INJ": "interjection",
    "Intj": "interjection",
    "Intg": "interrogative",
    "Neg": "negative",
    "P": "pronoun",
    "PerP": "pronoun",
    "DemP": "pronoun",
    "RelP": "pronoun",
    "D": "pronoun",
    "R": "pronoun",
    "F": "pronoun",
}
_GENDERS = {"M": "masculine", "F": "feminine", "N": "neuter", "M/F": "masculine or feminine"}


class LexiconEntry(NamedTuple):
    strongs: str  # "H0430"
    lemma: str
    translit: str
    part_of_speech: str  # "noun · masculine", "verb", "proper name"
    gloss: str  # "God", "to love"
    definition: str  # plain text, paragraphs separated by "\n"


def parse_lexicon(path: Path) -> dict[str, LexiconEntry]:
    candidates: dict[str, list[tuple[int, list[str]]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) < 8:
            continue
        match = _KEY.match(fields[0].strip())
        if match is None:
            continue
        base, suffix = match[1], match[2].lower()
        if suffix not in ("", "a"):
            continue  # H1121B "Beno" is a different word from H1121A "son"
        main = bool(_MAIN_ENTRY.match(fields[1].strip()))
        # Plain number before its "a" entry; the main entry before sub-meanings.
        rank = (0 if suffix == "" else 2) + (0 if main else 1)
        candidates.setdefault(base, []).append((rank, fields))

    entries: dict[str, LexiconEntry] = {}
    for base, options in candidates.items():
        fields = min(options, key=lambda option: option[0])[1]
        lemma = fields[3].strip()
        entries[base] = LexiconEntry(
            strongs=base,
            lemma=lemma,
            translit=fields[4].strip(),
            part_of_speech=part_of_speech(fields[5].strip()),
            gloss=clean_definition(fields[6]),
            definition=_without_scholarly_preamble(clean_definition(fields[7]), lemma),
        )
    return entries


def part_of_speech(code: str) -> str:
    """"H:N-M" -> "noun · masculine", "G:V" -> "verb", "N:N-M-P" -> "proper name"."""
    language, _, rest = code.partition(":")
    if language == "N":
        return "proper name"
    head, _, gender = rest.partition("-")
    name = _PARTS_OF_SPEECH.get(head, "")
    if name == "noun" and gender in _GENDERS:
        return f"noun · {_GENDERS[gender]}"
    return name


def _without_scholarly_preamble(definition: str, lemma: str) -> str:
    """Abbott-Smith (Greek) entries open by repeating the headword with its
    endings ("ἀγαπάω, -ῶ,") and noting the Septuagint's Hebrew ("[in LXX
    chiefly for אהב ;]"): noise in a reader's word study."""
    lines = definition.split("\n")
    while lines and _is_preamble(lines[0], lemma):
        lines.pop(0)
    return "\n".join(lines)


def _is_preamble(line: str, lemma: str) -> bool:
    # "ἀπ-όλλυμι and ἀπολλύω": forms of the headword, no English but "and".
    return (
        line.startswith(lemma)
        or line.startswith("[in LXX")
        or not re.search(r"[A-Za-z]", line.replace(" and ", " "))
    )


def clean_definition(raw: str) -> str:
    text = _REF.sub(r"\1", raw)
    text = _BREAK.sub("\n", text)
    text = html.unescape(_TAG.sub("", text))
    text = text.replace("__", "")
    # Hebrew entries often open with ": child/son" (the gloss's tail).
    lines = [_SPACES.sub(" ", line).strip().lstrip(":").strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)
