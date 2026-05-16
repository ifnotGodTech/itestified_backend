from django.contrib import admin

from .models import FeaturedHomeTestimony, HomeSectionOrder, InspirationalPicture, ScriptureOfTheDay


@admin.register(InspirationalPicture)
class InspirationalPictureAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "category", "publish_at", "expires_at", "created_at")
    list_filter = ("status", "category")
    search_fields = ("title", "caption", "category")


@admin.register(ScriptureOfTheDay)
class ScriptureOfTheDayAdmin(admin.ModelAdmin):
    list_display = ("id", "date", "bible_text", "bible_version", "status", "published_at")
    list_filter = ("status", "bible_version")
    search_fields = ("bible_text", "scripture", "prayer")


@admin.register(HomeSectionOrder)
class HomeSectionOrderAdmin(admin.ModelAdmin):
    list_display = ("section", "position", "updated_at")
    list_editable = ("position",)


@admin.register(FeaturedHomeTestimony)
class FeaturedHomeTestimonyAdmin(admin.ModelAdmin):
    list_display = ("id", "testimony", "position", "updated_at")
    list_filter = ("testimony__testimony_type", "testimony__status")
