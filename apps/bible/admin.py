from django.contrib import admin

from .models import BiblePack


@admin.register(BiblePack)
class BiblePackAdmin(admin.ModelAdmin):
    list_display = ("abbreviation", "code", "kind", "data_version", "size_bytes", "is_enabled", "is_default", "updated_at")
    list_filter = ("kind", "is_enabled")
    readonly_fields = ("sha256", "size_bytes", "data_version", "created_at", "updated_at")
