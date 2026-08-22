import logging
import os
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from apps.common.services.media_uploads import configure_cloudinary
from apps.testimonies.models import Testimony, TestimonyStatus, TestimonyType

from .models import (
    BrandedVideoExport,
    BrandedVideoExportStatus,
    MediaExportBrandingConfig,
)

logger = logging.getLogger(__name__)


class MediaExportError(Exception):
    pass


@dataclass(frozen=True)
class GeneratedMediaExport:
    branded_video_url: str


def get_branding_config() -> MediaExportBrandingConfig:
    config, _ = MediaExportBrandingConfig.objects.get_or_create(pk=1)
    return config


def testimony_share_url(testimony_id: int) -> str:
    base = os.environ.get("PUBLIC_SHARE_BASE_URL", "https://itestified.com/share").rstrip("/")
    return f"{base}/{testimony_id}"


def build_share_caption(*, title: str, testimony_id: int) -> str:
    return f"{title}\n\nWatch more inspiring testimonies on iTestified: {testimony_share_url(testimony_id)}"


def enqueue_branded_video_export(export_id: int) -> None:
    """Queue an export without allowing a broker outage to become HTTP 500."""
    from .tasks import run_branded_video_export

    try:
        run_branded_video_export.delay(export_id)
    except Exception as exc:  # noqa: BLE001 - broker exceptions vary by transport.
        logger.exception("Unable to enqueue branded video export %s", export_id)
        BrandedVideoExport.objects.filter(id=export_id).update(
            status=BrandedVideoExportStatus.FAILED,
            error_message="The export queue is unavailable. Please try again shortly.",
        )
        raise MediaExportError("The export queue is temporarily unavailable. Please try again shortly.") from exc


def request_branded_video_export(*, testimony_id: int, requested_by=None) -> BrandedVideoExport:
    testimony = Testimony.objects.filter(
        id=testimony_id,
        status=TestimonyStatus.APPROVED,
        testimony_type=TestimonyType.VIDEO,
    ).first()
    if testimony is None or not testimony.video_url.strip():
        raise MediaExportError("Only approved video testimonies can be exported.")

    branding = get_branding_config()
    if not branding.is_enabled:
        raise MediaExportError("Branded video exports are temporarily unavailable.")

    export, created = BrandedVideoExport.objects.get_or_create(
        testimony=testimony,
        branding_version=branding.version,
        defaults={
            "source_video_url": testimony.video_url,
            "requested_by": requested_by,
        },
    )
    if created:
        transaction.on_commit(lambda: enqueue_branded_video_export(export.id))
        return export
    if not created and export.status == BrandedVideoExportStatus.DONE:
        return export
    if export.status in {BrandedVideoExportStatus.PENDING, BrandedVideoExportStatus.PROCESSING}:
        return export

    export.status = BrandedVideoExportStatus.PENDING
    export.error_message = ""
    export.source_video_url = testimony.video_url
    export.requested_by = requested_by or export.requested_by
    export.save(update_fields=["status", "error_message", "source_video_url", "requested_by", "updated_at"])
    transaction.on_commit(lambda: enqueue_branded_video_export(export.id))
    return export


def generate_branded_video_export(*, source_video_url: str, export_id: int, branding: MediaExportBrandingConfig) -> GeneratedMediaExport:
    """Generate a Cloudinary derivative without replacing the source asset.

    Cloudinary performs the video transformation server-side. Configured logo
    and end-card assets are fetched as overlays, while the watermark and CTA
    are rendered as text. The original testimony asset is never replaced.
    """
    configure_cloudinary()
    try:
        from cloudinary import uploader
    except ImportError as exc:
        raise MediaExportError("cloudinary package is not installed.") from exc

    folder = os.environ.get("CLOUDINARY_BRANDED_EXPORT_FOLDER", "itestified/exports").strip()
    public_id = f"{folder}/testimony_{export_id}_v{branding.version}"
    watermark = branding.watermark_text.strip()
    cta = branding.call_to_action.strip()
    overlays = [part for part in (watermark, cta) if part]
    base_transformation = {
        "width": 1080,
        "height": 1920,
        "crop": "limit",
        "quality": "auto",
        "fetch_format": "auto",
    }
    transformations = [base_transformation]
    if branding.logo_url.strip():
        transformations.append({
            "overlay": {"url": f"fetch:{branding.logo_url.strip()}"},
            "width": 220,
            "crop": "scale",
            "gravity": "north_west",
            "x": 32,
            "y": 32,
        })
    if branding.end_card_url.strip():
        transformations.append({
            "overlay": {"url": f"fetch:{branding.end_card_url.strip()}"},
            "width": 900,
            "crop": "limit",
            "gravity": "south",
            "y": 96,
        })
    if overlays:
        transformations.append({
            "overlay": {"text": " • ".join(overlays), "font_family": "Arial", "font_size": 28},
            "gravity": "south",
            "y": 40,
        })
    try:
        result = uploader.upload(
            source_video_url,
            resource_type="video",
            public_id=public_id,
            overwrite=True,
            eager=[{"transformation": transformations}],
            context={"end_card_url": branding.end_card_url.strip(), "branding_version": str(branding.version)},
        )
    except Exception as exc:  # noqa: BLE001 - Cloudinary exception types vary by SDK version.
        reason = str(exc).strip() or "Cloudinary export failed."
        raise MediaExportError(reason) from exc

    eager = result.get("eager") or []
    branded_url = str((eager[0] if eager else result).get("secure_url") or "").strip()
    if not branded_url:
        raise MediaExportError("Cloudinary did not return a branded video URL.")
    return GeneratedMediaExport(branded_video_url=branded_url)
