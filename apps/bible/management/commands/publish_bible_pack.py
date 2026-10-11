from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.bible.exceptions import BiblePackError
from apps.bible.services.commands import register_bible_pack
from apps.bible.services.pack_files import read_pack_file, verify_published_copy


class Command(BaseCommand):
    help = (
        "Register an uploaded Bible pack in the download manifest. Downloads --url and refuses "
        "to register unless it is byte-for-byte the local built file. Upload the .sqlite.gz "
        "as-is (Content-Type application/gzip, no Content-Encoding header), e.g. "
        "`aws s3 cp bsb.sqlite.gz s3://<bucket>/bible-packs/bsb-<sha12>.sqlite.gz "
        "--content-type application/gzip`."
    )

    def add_arguments(self, parser):
        parser.add_argument("pack", help="Path to the built .sqlite.gz pack.")
        parser.add_argument("--url", required=True, help="Public URL the uploaded pack is served from.")
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
        try:
            pack_file = read_pack_file(Path(options["pack"]))
            verify_published_copy(pack=pack_file, url=url)
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
