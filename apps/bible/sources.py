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


SOURCES: dict[str, SourceDataset] = {
    "bsb_text": SourceDataset(
        key="bsb_text",
        url="https://bereanbible.com/bsb.txt",
        sha256="2ac3af1de52d4e68261cba91d85c320b7eadc6560e830d99e591767b8ff5ca96",
        licence="Public domain (dedicated 2023-04-30), berean.bible/licensing.htm",
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
}
