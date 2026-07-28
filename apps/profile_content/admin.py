from django.contrib import admin

from .models import HelpFaqEntry, ProfileContentBlock


@admin.register(ProfileContentBlock)
class ProfileContentBlockAdmin(admin.ModelAdmin):
    list_display = ("key", "updated_by", "updated_at")


@admin.register(HelpFaqEntry)
class HelpFaqEntryAdmin(admin.ModelAdmin):
    list_display = ("question", "display_order", "is_active", "updated_by", "updated_at")
    list_filter = ("is_active",)
