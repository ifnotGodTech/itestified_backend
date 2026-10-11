import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.bible.exceptions import BiblePackError
from apps.bible.services.commands import register_bible_pack
from apps.bible.services.pack_files import fetch_published_pack, read_pack_file, verify_published_copy


class Command(BaseCommand):
    help = (
        "Register an uploaded Bible pack in the download manifest, refusing anything that isn't "
        "byte-for-byte the built pack. Either pass the built file (it's compared with --url), or, "
        "on a server that doesn't have it (Render), pass --sha256 with the checksum "
        "build_bible_packs printed. Upload the .sqlite.gz as-is (Content-Type application/gzip, "
        "no Content-Encoding header)."
    )

    def add_arguments(self, parser):
        parser.add_argument("pack", nargs="?", help="Path to the built .sqlite.gz pack, if it's on this machine.")
        parser.add_argument("--url", required=True, help="Public URL the uploaded pack is served from.")
        parser.add_argument("--sha256", help="Expected sha256 of the uploaded pack, when the built file isn't here.")
        parser.add_argument("--enable", action="store_true", help="Make the pack visible to readers.")
        parser.add_argument(
            "--default",
            dest="make_default",
            action="store_true",
            help="Make this version the one new readers download first (implies --enable).",
        )

    def handle(self, *args, **options):
        url = options["url"].strip()
        if not url.startswith("https://") and not url.startswith("http://"):
            raise CommandError("--url must be an http(s) URL.")
        if not options["pack"] and not options["sha256"]:
            raise CommandError("Pass the built pack file, or --sha256 <checksum printed by build_bible_packs>.")

        try:
            with tempfile.TemporaryDirectory() as workdir:
                if options["pack"]:
                    pack_file = read_pack_file(Path(options["pack"]))
                    verify_published_copy(pack=pack_file, url=url)
                else:
                    pack_file = fetch_published_pack(
                        url=url, expected_sha256=options["sha256"], workdir=Path(workdir)
                    )
                result = register_bible_pack(
                    pack_file=pack_file,
                    file_url=url,
                    enable=options["enable"],
                    make_default=options["make_default"],
                )
        except BiblePackError as exc:
            raise CommandError(str(exc)) from exc

        pack = result.pack
        if result.created:
            action = "Registered"
        elif result.file_changed:
            action = "Updated"
        else:
            action = "Unchanged"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {pack.abbreviation} ({pack.code}): data version {pack.data_version}, "
                f"{pack.size_bytes:,} bytes, enabled={pack.is_enabled}, default={pack.is_default}"
            )
        )
