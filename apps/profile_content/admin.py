from django.contrib import admin

from .models import ProfileContentBlock


@admin.register(ProfileContentBlock)
class ProfileContentBlockAdmin(admin.ModelAdmin):
    list_display = ("key", "updated_by", "updated_at")
