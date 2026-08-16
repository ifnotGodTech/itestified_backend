from django.contrib import admin

from .models import (
    FeaturedHomeTestimony,
    HomePromoCard,
    HomeSectionOrder,
    InspirationalPicture,
    InspirationalPictureCategory,
    ScriptureOfTheDay,
    ScriptureReadReceipt,
)


@admin.register(InspirationalPictureCategory)
class InspirationalPictureCategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "slug", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(InspirationalPicture)
class InspirationalPictureAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "category", "publish_at", "expires_at", "created_at")
    list_filter = ("status", "category")
    search_fields = ("title", "caption", "category__name")


@admin.register(ScriptureOfTheDay)
class ScriptureOfTheDayAdmin(admin.ModelAdmin):
    list_display = ("id", "date", "bible_text", "bible_version", "status", "published_at")
    list_filter = ("status", "bible_version")
    search_fields = ("bible_text", "scripture", "prayer")


@admin.register(ScriptureReadReceipt)
class ScriptureReadReceiptAdmin(admin.ModelAdmin):
    list_display = ("user", "read_date", "created_at")
    list_filter = ("read_date",)
    search_fields = ("user__email",)


@admin.register(HomeSectionOrder)
class HomeSectionOrderAdmin(admin.ModelAdmin):
    list_display = ("section", "position", "updated_at")
    list_editable = ("position",)


@admin.register(FeaturedHomeTestimony)
class FeaturedHomeTestimonyAdmin(admin.ModelAdmin):
    list_display = ("id", "testimony", "position", "updated_at")
    list_filter = ("testimony__testimony_type", "testimony__status")


@admin.register(HomePromoCard)
class HomePromoCardAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "is_active", "starts_at", "ends_at", "updated_at")
    list_filter = ("is_active", "cta_destination")
    search_fields = ("title", "body")
