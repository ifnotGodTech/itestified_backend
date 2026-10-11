"""Small synthetic Bible sources and built packs for fast, offline tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

from apps.bible.canon import CANON
from apps.bible.services.pack_builds import parse_verse_text, write_version_pack
from apps.bible.sources import VERSIONS

JOHN_3_16 = (
    "For God so loved the world that He gave His one and only Son, that everyone "
    "who believes in Him shall not perish but have eternal life."
)


def write_source(directory: Path, *, skip_book: str | None = None, extra_lines: list[str] | None = None) -> Path:
    """A BSB-format source with one verse per book (John 3:16 included),
    using the source file's own "Psalm" spelling."""
    lines = [
        "﻿The Holy Bible, Berean Standard Bible\t",
        "This text of God's Word has been dedicated to the public domain.\t",
        "Verse\tBerean Standard Bible",
    ]
    for book in CANON:
        if book.name == skip_book:
            continue
        source_name = "Psalm" if book.name == "Psalms" else book.name
        if book.name == "John":
            lines.append(f"John 3:16\t{JOHN_3_16}")
        else:
            lines.append(f"{source_name} 1:1\tText of {book.name} one one.")
    lines.extend(extra_lines or [])
    path = directory / "bsb.txt"
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return path


def build_test_pack(out_dir: Path, *, attribution: str | None = None) -> Path:
    definition = VERSIONS["bsb"]
    if attribution is not None:
        definition = definition._replace(attribution=attribution)
    with tempfile.TemporaryDirectory() as workdir:
        parsed = parse_verse_text(write_source(Path(workdir)))
    return write_version_pack(definition=definition, parsed=parsed, source_sha256="0" * 64, out_dir=out_dir)
