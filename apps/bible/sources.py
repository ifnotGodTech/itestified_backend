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


SOURCES: dict[str, SourceDataset] = {
    "bsb_text": SourceDataset(
        key="bsb_text",
        url="https://bereanbible.com/bsb.txt",
        sha256="2ac3af1de52d4e68261cba91d85c320b7eadc6560e830d99e591767b8ff5ca96",
        licence="Public domain (dedicated 2023-04-30), berean.bible/licensing.htm",
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
    ),
}
