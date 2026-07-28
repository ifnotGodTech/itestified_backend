from django.contrib import admin

from .models import SocialLink


@admin.register(SocialLink)
class SocialLinkAdmin(admin.ModelAdmin):
    list_display = ("platform", "url", "is_active", "display_order", "updated_by", "updated_at")
    list_filter = ("platform", "is_active")
