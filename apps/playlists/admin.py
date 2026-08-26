from django.contrib import admin

from .models import Playlist, PlaylistItem


class PlaylistItemInline(admin.TabularInline):
    model = PlaylistItem
    extra = 0
    ordering = ["position"]


@admin.register(Playlist)
class PlaylistAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "title", "visibility", "show_owner_name", "created_at")
    list_filter = ("visibility", "show_owner_name")
    search_fields = ("title", "owner__email")
    inlines = [PlaylistItemInline]
