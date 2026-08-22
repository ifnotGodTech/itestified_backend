from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.common.services.media_uploads import CloudinaryUploadError, configure_cloudinary
from apps.media_exports.services import DEFAULT_LOGO_PUBLIC_ID, default_logo_url

LOGO_ASSET_PATH = Path(__file__).resolve().parents[2] / "assets" / "default_logo.png"


class Command(BaseCommand):
    """One-off setup command: uploads the bundled iTestified mark to
    Cloudinary under DEFAULT_LOGO_PUBLIC_ID, a fixed id that always gets
    overwritten in place rather than versioned, so re-running this never
    grows storage. Safe to run again any time the bundled asset changes;
    every branded export falls back to this logo whenever an admin hasn't
    uploaded a custom one (see generate_branded_video_export)."""

    help = "Upload the default branded-export logo to Cloudinary (idempotent)."

    def handle(self, *args, **options):
        if not LOGO_ASSET_PATH.exists():
            raise CommandError(f"Logo asset not found at {LOGO_ASSET_PATH}")

        configure_cloudinary()
        try:
            from cloudinary import uploader
        except ImportError as exc:
            raise CommandError("cloudinary package is not installed.") from exc

        try:
            uploader.upload(
                str(LOGO_ASSET_PATH),
                resource_type="image",
                public_id=DEFAULT_LOGO_PUBLIC_ID,
                overwrite=True,
                invalidate=True,
            )
        except CloudinaryUploadError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Uploaded default logo to {DEFAULT_LOGO_PUBLIC_ID}"))
        self.stdout.write(f"Delivery URL: {default_logo_url()}")
