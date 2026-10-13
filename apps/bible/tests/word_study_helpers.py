"""Synthetic word-study sources (BSB tables rows, lexicon lines) for fast,
offline Slice 5 tests. Shapes match the real files' columns."""

from __future__ import annotations

from pathlib import Path

TABLES_HEADER = [
    "Heb Sort", "Greek Sort", "BSB Sort", "Verse", "Language",
    "WLC / Nestle Base TR RP WH NE NA SBL", "WLC / Nestle Base {TR} ⧼RP⧽ (WH) 〈NE〉 [NA] ‹SBL› [[ECM]]",
    "Translit", "Parsing", "Parsing", "Str Heb", "Str Grk", "VerseId", "Hdg", "Crossref", "Par", "Space",
    "begQ", " BSB version ", "pnc", "endQ", "footnotes", "End text",
]

# John 3:16, first words, in BSB order: (greek sort, word, translit, code,
# parsing in words, Strong's, BSB English, punctuation after).
JOHN_3_16_WORDS = [
    (80598, "γὰρ", "gar", "Conj", "Conjunction", "1063", " For ", ""),
    (80600, "ὁ", "ho", "Art-NMS", "Article - Nominative Masculine Singular", "3588", " - ", ""),
    (80601, "Θεὸς", "Theos", "N-NMS", "Noun - Nominative Masculine Singular", "2316", " God ", ""),
    (80597, "Οὕτως", "Houtōs", "Adv", "Adverb", "3779", " so ", ""),
    (80599, "ἠγάπησεν", "ēgapēsen", "V-AIA-3S", "Verb - Aorist Indicative Active - 3rd Person Singular", "25", " loved ", ""),
    (80616, "μὴ", "mē", "Adv", "Adverb", "3361", " vvv ", ""),
    (80617, "ἀπόληται", "apolētai", "V-ASM-3S", "Verb - Aorist Subjunctive Middle - 3rd Person Singular", "622", " shall not perish ", ""),
    (80621, "αἰώνιον", "aiōnion", "Adj-AFS", "Adjective - Accusative Feminine Singular", "166", " eternal ", ""),
    (80620, "ζωὴν", "zōēn", "N-AFS", "Noun - Accusative Feminine Singular", "2222", " life ", "."),
]

# Genesis 1:1, with a supplied-word bracket and Hebrew accents to strip.
GENESIS_1_1_WORDS = [
    (1, "בְּרֵאשִׁ֖ית", "bə·rê·šîṯ", "Prep-b | N-fs", "Preposition-b | Noun - feminine singular", "7225", " In the beginning ", ""),
    (3, "אֱלֹהִ֑ים", "’ĕ·lō·hîm", "N-mp", "Noun - masculine plural", "430", " God ", ""),
    (4, "אֵ֥ת", "’êṯ", "DirObjM", "Direct object marker", "853", " - ", ""),
    (2, "בָּרָ֣א", "bā·rā", "V-Qal-Perf-3ms", "Verb - Qal - Perfect - third person masculine singular", "1254", " created ", ""),
    (5, "הַשָּׁמַ֖יִם", "haš·šā·ma·yim", "Art | N-mp", "Article | Noun - masculine plural", "8064", " [the] heavens ", ""),
]


def write_tables(directory: Path) -> Path:
    rows = ["\t".join(TABLES_HEADER)]
    bsb_sort = 0
    for verse_id, words, greek in (("Genesis 1:1", GENESIS_1_1_WORDS, False), ("John 3:16", JOHN_3_16_WORDS, True)):
        for index, (sort, word, translit, code, parsing, strongs, english, punctuation) in enumerate(words):
            bsb_sort += 1
            row = [""] * len(TABLES_HEADER)
            row[0] = "999999" if greek else str(sort)
            row[1] = str(sort) if greek else "0"
            row[2] = str(bsb_sort)
            row[3] = "1"
            row[4] = "Greek" if greek else "Hebrew"
            row[5] = row[6] = word
            row[7], row[8], row[9] = translit, code, parsing
            row[11 if greek else 10] = strongs
            row[12] = verse_id if index == 0 else ""
            row[18], row[19] = english, punctuation
            rows.append("\t".join(row))
        # The real file pads verses with blank rows.
        blank = [""] * len(TABLES_HEADER)
        blank[0], blank[2], blank[4] = "999999", str(bsb_sort + 1000), "Greek" if greek else "Hebrew"
        rows.append("\t".join(blank))
    path = directory / "bsb_tables.tsv"
    path.write_text("﻿" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def write_lexicon(directory: Path, name: str, lines: list[list[str]]) -> Path:
    header = "TBESX - Translators Brief lexicon - STEPBible.org CC BY\n=====\nFields: explained here\n"
    path = directory / name
    path.write_text(header + "\n".join("\t".join(line) for line in lines) + "\n", encoding="utf-8")
    return path


GREEK_LEXICON = [
    ["G0025", "G0025 =", "G0025", "ἀγαπάω", "agapaō", "G:V", "to love",
     " <b>ἀγαπάω</b>, -ῶ, <BR /><b>to love</b>, <ref='Mat.5.43'>Mat.5:43</ref>; __1. of God &amp; men"],
    ["G2316", "G2316 =", "G2316", "θεός", "theos", "G:N-M/F", "God", "<b>θεός</b>, a god or deity"],
]
HEBREW_LEXICON = [
    # Only sub-meanings for H0430: the first one wins.
    ["H0430", "H0430G = a Name of", "H3068G", "אֱלֹהִים", "e.lo.him", "H:N-M", "God", "This name means \"God\"<BR>Another name"],
    ["H0430", "H0430H = a Part of", "H3068G", "אֱלֹהִים", "e.lo.him", "H:N-M", "(LORD)-Elohe", "Combined"],
    # Split numbers: the "a" entry, and its main entry over sub-meanings.
    ["H1121a", "H1121G = a Meaning of", "H1121A", "בֵּן", "ben", "H:N-M", "son: descendant", ": descendants"],
    ["H1121a", "H1121A =", "H1121A", "בֵּן", "ben", "H:N-M", "son: child", ": child/son"],
    ["H1121b", "H1121B =", "H1121B", "בְּנוֹ", "be.no", "N:N-M-P", "Beno", "A man"],
    ["H3068", "H3068G =", "H3068G", "יְהֹוָה", "ye.ho.vah", "N:N--T", "LORD", "the proper name of the one true God"],
]
