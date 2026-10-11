from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.bible.exceptions import BiblePackError
from apps.bible.services.pack_builds import fetch_source, parse_verse_text, sha256_of_file, write_version_pack
from apps.bible.sources import SOURCES, VERSIONS

DEFAULT_SOURCES_DIR = Path.home() / ".cache" / "itestified-bible-sources"


class Command(BaseCommand):
    help = (
        "Build downloadable Bible packs (gzip SQLite) from the pinned source datasets in "
        "apps/bible/sources.py. Sources are downloaded and checksum-verified; packs are "
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
            dest="versions",
            action="append",
            choices=sorted(VERSIONS),
            help="Build only this Bible version code (repeatable). Default: every version.",
        )

    def handle(self, *args, **options):
        out_dir = Path(options["out"])
        sources_dir = Path(options["sources_dir"])
        codes = options["versions"] or sorted(VERSIONS)

        for code in codes:
            definition = VERSIONS[code]
            dataset = SOURCES[definition.text_source]
            try:
                source_path = fetch_source(dataset, sources_dir)
                parsed = parse_verse_text(source_path)
                pack_path = write_version_pack(
                    definition=definition, parsed=parsed, source_sha256=dataset.sha256, out_dir=out_dir
                )
            except BiblePackError as exc:
                raise CommandError(str(exc)) from exc

            books = len({verse.book_id for verse in parsed.verses})
            self.stdout.write(
                self.style.SUCCESS(
                    f"{definition.abbreviation}: {len(parsed.verses)} verses in {books} books "
                    f"({len(parsed.omitted)} left out by the translation) -> {pack_path} "
                    f"({pack_path.stat().st_size:,} bytes, sha256 {sha256_of_file(pack_path)})"
                )
            )
