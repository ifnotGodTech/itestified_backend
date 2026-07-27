from django.contrib import admin

from .models import AppVersionConfig


@admin.register(AppVersionConfig)
class AppVersionConfigAdmin(admin.ModelAdmin):
    list_display = ("platform", "minimum_version", "latest_version", "updated_by", "updated_at")
    list_filter = ("platform",)
