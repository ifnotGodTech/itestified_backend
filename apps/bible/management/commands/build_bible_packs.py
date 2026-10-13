from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.bible.exceptions import BiblePackError
from apps.bible.services.lexicon import parse_lexicon
from apps.bible.services.original_text import OriginalWord, VerseKey, parse_bsb_tables
from apps.bible.services.pack_builds import fetch_source, parse_source, sha256_of_file, write_version_pack
from apps.bible.services.study_pack import write_study_pack
from apps.bible.services.word_links import (
    MIN_BSB_PLACED_RATIO,
    MIN_KJV_MATCHED_RATIO,
    link_bsb,
    link_tagged,
    renderings,
    require_coverage,
)
from apps.bible.sources import SOURCES, STUDY, VERSIONS

DEFAULT_SOURCES_DIR = Path.home() / ".cache" / "itestified-bible-sources"


class Command(BaseCommand):
    help = (
        "Build downloadable Bible packs (gzip SQLite) from the pinned source datasets in "
        "apps/bible/sources.py: each Bible version (text, and word links where it has them) and "
        "the shared word-study pack. Sources are downloaded and checksum-verified; packs are "
        "written to --out. Upload the result with the AWS CLI, then run publish_bible_pack."
    )

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="Directory to write the .sqlite.gz packs into.")
        parser.add_argument(
            "--sources-dir",
            default=str(DEFAULT_SOURCES_DIR),
            help=f"Where downloaded source datasets are cached (default {DEFAULT_SOURCES_DIR}).",
        )
        parser.add_argument(
            "--bible",
            dest="codes",
            action="append",
            choices=sorted([*VERSIONS, STUDY.code]),
            help=f"Build only this pack (repeatable): a version code or {STUDY.code!r}. Default: all.",
        )

    def handle(self, *args, **options):
        self.out_dir = Path(options["out"])
        self.sources_dir = Path(options["sources_dir"])
        self._originals: dict[VerseKey, list[OriginalWord]] | None = None
        codes = options["codes"] or [*sorted(VERSIONS), STUDY.code]
        try:
            for code in codes:
                if code == STUDY.code:
                    self._build_study()
                else:
                    self._build_version(code)
        except BiblePackError as exc:
            raise CommandError(str(exc)) from exc

    def _originals_text(self) -> dict[VerseKey, list[OriginalWord]]:
        # ~85 MB to parse; shared by the BSB links, the KJV match and the study pack.
        if self._originals is None:
            path = fetch_source(SOURCES[STUDY.original_text_source], self.sources_dir)
            self._originals = parse_bsb_tables(path)
        return self._originals

    def _build_version(self, code: str) -> None:
        definition = VERSIONS[code]
        dataset = SOURCES[definition.text_source]
        parsed = parse_source(definition, fetch_source(dataset, self.sources_dir))
        texts = {(verse.book_id, verse.chapter, verse.verse): verse.text for verse in parsed.verses}

        report = None
        if definition.word_links == "bsb_tables":
            report = link_bsb(texts, self._originals_text())
            require_coverage(report, minimum=MIN_BSB_PLACED_RATIO, label=f"{definition.abbreviation} word links")
        elif definition.word_links == "usfm_strongs":
            report = link_tagged(texts, parsed.word_tags, self._originals_text())
            require_coverage(report, minimum=MIN_KJV_MATCHED_RATIO, label=f"{definition.abbreviation} word links")

        pack_path = write_version_pack(
            definition=definition,
            parsed=parsed,
            source_sha256=dataset.sha256,
            out_dir=self.out_dir,
            word_links=report.links if report else None,
            renderings=renderings(texts, report.links) if report else None,
        )
        books = len({verse.book_id for verse in parsed.verses})
        links = (
            f"; {len(report.links):,} word links, {report.placed:,}/{report.expected:,} "
            f"({report.ratio:.3%}) {'placed' if definition.word_links == 'bsb_tables' else 'matched to the original word'}"
            if report
            else "; no word links"
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"{definition.abbreviation}: {len(parsed.verses)} verses in {books} books "
                f"({len(parsed.omitted)} left out by the translation){links} -> {pack_path} "
                f"({pack_path.stat().st_size:,} bytes, sha256 {sha256_of_file(pack_path)})"
            )
        )
        if report and report.problems:
            self.stdout.write("  Not linked (sample):\n  " + "\n  ".join(report.problems[:10]))

    def _build_study(self) -> None:
        hebrew = fetch_source(SOURCES[STUDY.hebrew_lexicon_source], self.sources_dir)
        greek = fetch_source(SOURCES[STUDY.greek_lexicon_source], self.sources_dir)
        lexicon = {**parse_lexicon(hebrew), **parse_lexicon(greek)}
        pack_path, counts = write_study_pack(
            definition=STUDY,
            originals=self._originals_text(),
            lexicon=lexicon,
            source_sha256s={
                key: SOURCES[key].sha256
                for key in (STUDY.original_text_source, STUDY.hebrew_lexicon_source, STUDY.greek_lexicon_source)
            },
            out_dir=self.out_dir,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"{STUDY.name}: {counts['words']:,} original words, {counts['lexicon_entries']:,} lexicon "
                f"entries, {counts['parsings']:,} parsings, {counts['missing_lexicon_entries']} without an "
                f"entry -> {pack_path} ({pack_path.stat().st_size:,} bytes, sha256 {sha256_of_file(pack_path)})"
            )
        )
