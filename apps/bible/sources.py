"""Pinned upstream datasets and per-version metadata for building packs.

Datasets are downloaded at build time, never committed. Each is pinned by
sha256: if upstream changes a file, the build stops until someone reviews
the change and updates the pin here.
"""

from __future__ import annotations

from typing import NamedTuple


class SourceDataset(NamedTuple):
    key: str
    url: str
    sha256: str
    licence: str


class VersionDefinition(NamedTuple):
    code: str
    name: str
    abbreviation: str
    description: str
    attribution: str
    text_source: str  # SourceDataset.key
    sort_order: int
    # How text_source is laid out: "verse_lines" (BSB's "Book C:V<TAB>text")
    # or "usfm_zip" (a zip of one USFM file per book).
    text_format: str = "verse_lines"
    # Where its word links (Slice 5) come from: "bsb_tables" (the BSB's own
    # translation tables, placed into the verse text) or "usfm_strongs" (the
    # Strong's tags already in a USFM source). Empty: no word study.
    word_links: str = ""


class StudyDefinition(NamedTuple):
    """The shared word-study pack (Slice 5): lexicon, parsing and the
    original-language text every version's word links point into."""

    code: str
    name: str
    abbreviation: str
    description: str
    attribution: str
    original_text_source: str  # SourceDataset.key (the BSB tables)
    hebrew_lexicon_source: str
    greek_lexicon_source: str
    sort_order: int


# STEPBible-Data is pinned to one commit, so its files can't change under a pin.
_STEPBIBLE_COMMIT = "81450441d7c5a60672448b590201a0e042deb2a0"
_STEPBIBLE_LEXICONS = f"https://raw.githubusercontent.com/STEPBible/STEPBible-Data/{_STEPBIBLE_COMMIT}/Lexicons"


SOURCES: dict[str, SourceDataset] = {
    "bsb_text": SourceDataset(
        key="bsb_text",
        url="https://bereanbible.com/bsb.txt",
        sha256="2ac3af1de52d4e68261cba91d85c320b7eadc6560e830d99e591767b8ff5ca96",
        licence="Public domain (dedicated 2023-04-30), berean.bible/licensing.htm",
    ),
    "bsb_tables": SourceDataset(
        key="bsb_tables",
        url="https://bereanbible.com/bsb_tables.tsv",
        sha256="09bbee6f9fe4fa22b5df28e8a9ffa99bf9c33435f4eb8c47c2dc221d855d35cb",
        licence=(
            "Public domain (the BSB and its translation tables, dedicated 2023-04-30), "
            "berean.bible/licensing.htm. One row per Hebrew/Aramaic/Greek word: the original "
            "word (WLC for the OT), transliteration, parsing, Strong's number and the BSB English "
            "it is translated by, in BSB order. ~85 MB."
        ),
    ),
    "stepbible_tbesh": SourceDataset(
        key="stepbible_tbesh",
        url=f"{_STEPBIBLE_LEXICONS}/TBESH%20-%20Translators%20Brief%20lexicon%20of%20Extended%20Strongs%20for%20Hebrew%20-%20STEPBible.org%20CC%20BY.txt",
        sha256="464dccadd95fd8620dd05fa0d7a4caba58ec3c4d5db3ebf38e43d046ca25b591",
        licence="STEPBible.org data, Tyndale House Cambridge, CC BY 4.0 (attribution and a note of changes).",
    ),
    "stepbible_tbesg": SourceDataset(
        key="stepbible_tbesg",
        url=f"{_STEPBIBLE_LEXICONS}/TBESG%20-%20Translators%20Brief%20lexicon%20of%20Extended%20Strongs%20for%20Greek%20-%20STEPBible.org%20CC%20BY.txt",
        sha256="312f723d7b8ef263bbdfb0451c9b8057125804dfff390b6f8544cff2a84b57f4",
        licence="STEPBible.org data, Tyndale House Cambridge, CC BY 4.0 (attribution and a note of changes).",
    ),
    "kjv_usfm": SourceDataset(
        key="kjv_usfm",
        url="https://eBible.org/Scriptures/eng-kjv2006_usfm.zip",
        sha256="5789dcd000d60a554abb4cf9b37ce10a53628bfc686e11ada2d6c981455239c1",
        licence=(
            "KJV text: public domain outside the UK (Crown letters patent apply in the UK). "
            "Strong's tagging: CrossWire Bible Society, GNU GPL (Phase 34 KJV decision, option 1). "
            "Courtesy of the CrossWire Bible Society and eBible.org (eng-kjv2006, source files "
            "dated 2026-09-26). eBible regenerates this zip periodically, so expect the pin to "
            "need reviewing on a rebuild."
        ),
    ),
}

VERSIONS: dict[str, VersionDefinition] = {
    "bsb": VersionDefinition(
        code="bsb",
        name="Berean Standard Bible",
        abbreviation="BSB",
        description="Modern English",
        attribution=(
            "The Holy Bible, Berean Standard Bible (BSB). This text of God's Word "
            "has been dedicated to the public domain. BereanBible.com"
        ),
        text_source="bsb_text",
        sort_order=10,
        word_links="bsb_tables",
    ),
    "kjv": VersionDefinition(
        code="kjv",
        name="King James Version",
        abbreviation="KJV",
        description="Classic English",
        attribution=(
            "The Holy Bible, King James Version (1769 standardized text). Public domain outside "
            "the United Kingdom; in the UK the Crown's letters patent apply. Text courtesy of "
            "the CrossWire Bible Society and eBible.org. Strong's number tagging is the work of "
            "the CrossWire Bible Society, used under the GNU General Public License."
        ),
        text_source="kjv_usfm",
        sort_order=20,
        text_format="usfm_zip",
        word_links="usfm_strongs",
    ),
}

STUDY = StudyDefinition(
    code="study",
    name="Word study & concordance",
    abbreviation="STUDY",
    description="Greek & Hebrew meanings, every use",
    attribution=(
        "Lexicon: STEPBible.org data (Translators Brief lexicons of Extended Strong's for "
        "Hebrew and Greek), Tyndale House Cambridge, CC BY 4.0. Changes: reformatted for this "
        "app (markup removed) and keyed by Strong's number. Hebrew, Aramaic and Greek text, "
        "transliteration and parsing: the Berean Bible translation tables, public domain, "
        "BereanBible.com."
    ),
    original_text_source="bsb_tables",
    hebrew_lexicon_source="stepbible_tbesh",
    greek_lexicon_source="stepbible_tbesg",
    sort_order=100,
)
