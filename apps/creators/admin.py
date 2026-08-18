from django.contrib import admin

from .models import CreatorFollow, CreatorProfile


@admin.register(CreatorProfile)
class CreatorProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "display_name", "is_verified", "created_at")
    list_filter = ("is_verified",)
    search_fields = ("display_name", "user__email")


@admin.register(CreatorFollow)
class CreatorFollowAdmin(admin.ModelAdmin):
    list_display = ("id", "follower", "creator", "created_at")
