from django.contrib import admin

from .models import BrandedVideoExport, MediaExportBrandingConfig


@admin.register(MediaExportBrandingConfig)
class MediaExportBrandingConfigAdmin(admin.ModelAdmin):
    list_display = ("version", "is_enabled", "watermark_text", "updated_by", "updated_at")


@admin.register(BrandedVideoExport)
class BrandedVideoExportAdmin(admin.ModelAdmin):
    list_display = ("testimony", "branding_version", "status", "retry_count", "updated_at")
    list_filter = ("status", "branding_version")
    search_fields = ("testimony__title", "error_message")
