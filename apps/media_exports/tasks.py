import logging

from celery import shared_task

from .models import BrandedVideoExport, BrandedVideoExportStatus
from .services import MediaExportError, generate_branded_video_export

logger = logging.getLogger(__name__)


@shared_task
def run_branded_video_export(export_id: int) -> None:
    try:
        export = BrandedVideoExport.objects.select_related("testimony").get(id=export_id)
    except BrandedVideoExport.DoesNotExist:
        logger.warning("run_branded_video_export: export %s no longer exists", export_id)
        return

    export.status = BrandedVideoExportStatus.PROCESSING
    export.save(update_fields=["status", "updated_at"])
    try:
        from .services import get_branding_config

        branding = get_branding_config()
        if branding.version != export.branding_version:
            raise MediaExportError(
                "This export was superseded by a newer branding configuration."
            )
        generated = generate_branded_video_export(
            source_video_url=export.source_video_url,
            export_id=export.id,
            branding=branding,
        )
    except MediaExportError as exc:
        export.status = BrandedVideoExportStatus.FAILED
        export.error_message = str(exc)
        export.retry_count += 1
        export.save(update_fields=["status", "error_message", "retry_count", "updated_at"])
        logger.warning("run_branded_video_export: export %s failed: %s", export_id, exc)
        return

    export.status = BrandedVideoExportStatus.DONE
    export.branded_video_url = generated.branded_video_url
    export.error_message = ""
    export.save(update_fields=["status", "branded_video_url", "error_message", "updated_at"])
